"""Safety boundaries for the nRF54L15 online security recipe."""

from __future__ import annotations

import pytest

from mklink.cmsis_dap import nrf54l_security as recipe
from mklink.cmsis_dap.backend import PyOcdBackend
from mklink.cmsis_dap.security import security_capability
from mklink.security_operations import run_security_operation


class FakeDP:
    def __init__(self, *, protected: bool = False, targetid: int = recipe.TARGET_ID):
        self.targetid = targetid
        self.registers = {
            recipe.CTRL_AP | 0xFC: recipe.CTRL_AP_IDR,
            recipe.CTRL_AP | 0x0C: 0,
            recipe.CTRL_AP | 0x14: 3 if protected else 0,
            recipe.CTRL_AP | 0x08: 0,
            0: 0 if protected else 0x40,
        }
        self.writes = []

    def read_dp(self, address):
        assert address == 0x24
        return self.targetid

    def read_ap(self, address):
        return self.registers[address]

    def write_ap(self, address, value):
        self.writes.append((address, value))
        if address == recipe.CTRL_AP | 0x04 and value == 1:
            self.registers[recipe.CTRL_AP | 0x08] = 1
        if address == recipe.CTRL_AP and value == 0:
            self.registers[recipe.CTRL_AP | 0x14] = 0

    def flush(self):
        pass


class FakeFlash:
    class Operation:
        PROGRAM = object()

    def __init__(self, target):
        self.target = target
        self.programmed = []
        self.cleaned = False

    def init(self, operation, *, reset):
        assert operation is self.Operation.PROGRAM and reset is False

    def program_page(self, address, data):
        self.programmed.append(address)
        self.target.words[address] = int.from_bytes(data, "little")

    def cleanup(self):
        self.cleaned = True


class FakeTarget:
    def __init__(self):
        self.dp = FakeDP()
        self.words = {0x00FFC31C: recipe.PART_ID}
        self.words.update({address: 0xFFFFFFFF for address in
                           (*recipe.APPROTECT_ADDRESSES, *recipe.ERASEPROTECT_ADDRESSES)})
        self.flash = FakeFlash(self)
        self.memory_map = self
        self.reset_count = 0

    def read32(self, address):
        return self.words[address]

    def reset_and_halt(self):
        self.reset_count += 1

    def get_region_for_address(self, address):
        assert address == recipe.APPROTECT_ADDRESSES[0]
        return self


def test_capability_exposes_only_nrf54l15_aliases():
    for part in ("nrf54l", "nRF54L15"):
        capability = security_capability(part).public()
        assert capability["family"] == "nrf54l15-ctrl-ap"
        assert capability["unlock_supported"] and capability["lock_supported"]
        assert capability["unlock_erases_flash"]
    assert not security_capability("nRF54L10").supported


def test_ctrl_ap_entry_rejects_voltage_argument_before_target_access():
    with pytest.raises(ValueError, match="omit voltage_mv"):
        run_security_operation(
            "unlock", "nrf54l", voltage_mv=3300,
            confirm_user=True, confirm_data_loss=True,
        )


def test_recovery_checks_identity_before_erase(monkeypatch):
    dp = FakeDP(protected=True, targetid=0x12345678)
    monkeypatch.setattr(recipe.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="TARGETID mismatch"):
        recipe.recover(dp)
    assert dp.writes == []


def test_recovery_triggers_erase_once_and_resets(monkeypatch):
    dp = FakeDP(protected=True)
    monkeypatch.setattr(recipe.time, "sleep", lambda _seconds: None)
    assert recipe.recover(dp)
    assert dp.writes == [
        (recipe.CTRL_AP | 0x04, 1),
        (recipe.CTRL_AP, 2),
        (recipe.CTRL_AP, 0),
    ]


def test_recovery_rejects_eraseprotect_without_writing():
    dp = FakeDP(protected=True)
    dp.registers[recipe.CTRL_AP | 0x0C] = 1
    with pytest.raises(RuntimeError, match="ERASEPROTECT"):
        recipe.recover(dp)
    assert dp.writes == []


def test_lock_writes_only_pinned_approtect_words():
    target = FakeTarget()
    assert recipe.write_approtect(target)
    assert target.flash.programmed == list(recipe.APPROTECT_ADDRESSES)
    assert target.flash.cleaned
    assert target.reset_count == 1
    assert all(target.words[address] == 0xFFFFFFFF for address in
               recipe.ERASEPROTECT_ADDRESSES)


def test_lock_rejects_partial_uicr_without_programming():
    target = FakeTarget()
    target.words[recipe.APPROTECT_ADDRESSES[1]] = 0
    with pytest.raises(RuntimeError, match="unexpected values"):
        recipe.write_approtect(target)
    assert target.flash.programmed == []


def test_lock_reset_requires_both_protection_bits_and_closed_ahb(monkeypatch):
    class LockDP(FakeDP):
        def write_ap(self, address, value):
            super().write_ap(address, value)
            if address == recipe.CTRL_AP and value == 0:
                self.registers[recipe.CTRL_AP | 0x14] = 3
                self.registers[0] = 0

    monkeypatch.setattr(recipe.time, "sleep", lambda _seconds: None)
    dp = LockDP()
    recipe.activate_and_verify_lock(dp)
    assert dp.writes == [(recipe.CTRL_AP, 2), (recipe.CTRL_AP, 0)]
    class BadDP(LockDP):
        def write_ap(self, address, value):
            super().write_ap(address, value)
            if address == recipe.CTRL_AP and value == 0:
                self.registers[recipe.CTRL_AP | 0x14] = 1

    with pytest.raises(RuntimeError, match="not active"):
        recipe.activate_and_verify_lock(BadDP())


def test_backend_reconnects_full_session_after_ctrl_ap_recovery(monkeypatch):
    opens = []
    sessions = []

    class Probe:
        unique_id = "test-probe"

    class DP(FakeDP):
        def connect(self):
            pass

    class Target(FakeTarget):
        def __init__(self, protected):
            super().__init__()
            self.dp = DP(protected=protected)

        def read_memory_block8(self, _address, size):
            return b"\xFF" * size

    class Session:
        def __init__(self, protected, options):
            self.target = Target(protected)
            self.options = options
            self.delegate = None

        def open(self, *, init_board=True):
            opens.append(init_board)

        def close(self):
            pass

    def make_session(_probe, options):
        session = Session(protected=not sessions, options=options)
        sessions.append(session)
        return session

    monkeypatch.setattr(recipe.time, "sleep", lambda _seconds: None)
    backend = PyOcdBackend(session_factory=make_session, probe_provider=lambda: [Probe()])
    backend.connect(
        probe="test-probe", target="nrf54l", frequency=1_000_000,
        connect_mode="attach", security_family="nrf54l15-ctrl-ap",
    )
    assert "erased and verified" in backend.unlock_security()
    assert opens == [False, True]
    assert sessions[0].target.dp.writes == [
        (recipe.CTRL_AP | 0x04, 1),
        (recipe.CTRL_AP, 2),
        (recipe.CTRL_AP, 0),
    ]
    backend.disconnect()
