import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.jobs import OnlineFlashJobManager
from mklink.cmsis_dap.models import ImageInspection, JobRequest, JobState
from mklink.remote.resource_manager import ResourceGroup, ResourceManager


class FakeBackend:
    def __init__(self):
        self.calls = []

    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs))

    def erase_chip(self):
        self.calls.append(("erase", None))

    def erase_sectors(self, addresses):
        self.calls.append(("erase_sectors", tuple(addresses)))

    def program(self, image):
        self.calls.append(("program", image))

    def verify(self, image):
        self.calls.append(("verify", image))

    def reset_run(self, reset_mode):
        self.calls.append(("reset", reset_mode))

    def disconnect(self):
        self.calls.append(("disconnect", None))


class BlockingBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.program_started = threading.Event()
        self.allow_program = threading.Event()

    def program(self, image):
        self.calls.append(("program", image))
        self.program_started.set()
        assert self.allow_program.wait(2)


class BlockingDisconnectBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.disconnect_started = threading.Event()
        self.allow_disconnect = threading.Event()

    def disconnect(self):
        self.calls.append(("disconnect", None))
        self.disconnect_started.set()
        assert self.allow_disconnect.wait(2)


class ShutdownBlockingBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.connect_started = threading.Event()
        self.allow_connect = threading.Event()

    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs))
        self.connect_started.set()
        self.allow_connect.wait()


class FailingBackend(FakeBackend):
    def __init__(self, failure):
        super().__init__()
        self.failure = failure

    def _fail(self, stage):
        if self.failure == stage:
            raise RuntimeError(f"{stage} boom")

    def connect(self, **kwargs):
        super().connect(**kwargs)
        self._fail("connect")

    def erase_chip(self):
        super().erase_chip()
        self._fail("erase")

    def program(self, image):
        super().program(image)
        self._fail("program")

    def verify(self, image):
        super().verify(image)
        self._fail("verify")

    def reset_run(self, reset_mode):
        super().reset_run(reset_mode)
        self._fail("reset")

    def disconnect(self):
        super().disconnect()
        self._fail("disconnect")


class StageAndDisconnectFailingBackend(FailingBackend):
    def disconnect(self):
        FakeBackend.disconnect(self)
        raise RuntimeError("disconnect boom")


class BlockingAcquireResourceManager(ResourceManager):
    def __init__(self):
        super().__init__()
        self.acquire_started = threading.Event()
        self.allow_acquire_return = threading.Event()

    def acquire(self, *args, **kwargs):
        lease = super().acquire(*args, **kwargs)
        self.acquire_started.set()
        assert self.allow_acquire_return.wait(2)
        return lease


class ReleaseFailingResourceManager(ResourceManager):
    def __init__(self, delete_lease):
        super().__init__()
        self.delete_lease = delete_lease

    def release(self, owner):
        if self.delete_lease:
            super().release(owner)
        raise RuntimeError("release boom")


class CountingResourceManager(ResourceManager):
    def __init__(self):
        super().__init__()
        self.acquire_calls = 0

    def acquire(self, *args, **kwargs):
        self.acquire_calls += 1
        return super().acquire(*args, **kwargs)


class FailingSubmitExecutor:
    def submit(self, *_args, **_kwargs):
        raise RuntimeError("submit boom")

    def shutdown(self, wait=True):
        pass


class ControlledExecutor:
    def __init__(self):
        self.tasks = []
        self.submit_count = 0

    def submit(self, fn, *args, **kwargs):
        future = Future()
        self.submit_count += 1
        self.tasks.append((future, fn, args, kwargs))
        return future

    def run_next(self):
        future, fn, args, kwargs = self.tasks.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
        return future

    def shutdown(self, wait=True):
        pass


def image(image_id="image-1"):
    return ImageInspection(
        image_id=image_id,
        file_name="app.bin",
        file_path="/snapshots/app.bin",
        format="bin",
        size=1024,
        sha256="abc123",
        start=0x8000000,
        end=0x8000400,
        base_address=0x8000000,
    )


def test_full_job_releases_resource_and_records_snapshot():
    backend = FakeBackend()
    resources = ResourceManager()
    inspected = image()
    manager = OnlineFlashJobManager(
        lambda: backend, resources, image_provider=lambda image_id: inspected
    )
    request = JobRequest(
        actions=("connect", "erase", "program", "verify", "reset", "disconnect"),
        image_id=inspected.image_id,
        probe_id="probe-1",
        target_part="HPM5301",
        pack_path="/packs/HPM5301.pack",
        frequency=2_000_000,
        connect_mode="under-reset",
        reset_mode="hw",
    )

    job_id = manager.start(request)
    snapshot = manager.wait(job_id, timeout=2)
    manager.shutdown()

    assert snapshot.state is JobState.SUCCEEDED
    assert [call[0] for call in backend.calls] == [
        "connect",
        "erase",
        "program",
        "verify",
        "reset",
        "disconnect",
    ]
    assert backend.calls[0][1] == {
        "probe": "probe-1",
        "target": "HPM5301",
        "frequency": 2_000_000,
        "pack": "/packs/HPM5301.pack",
        "connect_mode": "under-reset",
        "reset_mode": "hw",
    }
    assert snapshot.file_path == inspected.file_path
    assert snapshot.image_format == inspected.format
    assert snapshot.image_start == inspected.start
    assert snapshot.image_end == inspected.end
    assert snapshot.image_size == inspected.size
    assert snapshot.image_sha256 == inspected.sha256
    assert snapshot.total_progress == 1.0
    assert snapshot.stage_progress == 1.0
    assert snapshot.current_action == "disconnect"
    assert snapshot.elapsed_seconds >= 0
    assert "target_debug" not in resources.get_status()


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("connect", FlashErrorCode.CONNECT_FAIL),
        ("erase", FlashErrorCode.ERASE_FAIL),
        ("program", FlashErrorCode.PROGRAM_FAIL),
        ("verify", FlashErrorCode.VERIFY_FAIL),
        ("reset", FlashErrorCode.RESET_FAIL),
    ],
)
def test_backend_failure_is_mapped_and_disconnects_once(stage, code):
    backend = FailingBackend(stage)
    resources = ResourceManager()
    inspected = image()
    manager = OnlineFlashJobManager(
        lambda: backend, resources, image_provider=lambda _image_id: inspected
    )

    result = manager.wait(
        manager.start(JobRequest.full_sequence(inspected)), timeout=2
    )
    manager.shutdown()

    assert result.state is JobState.FAILED
    assert result.error_code == code.value
    assert [name for name, _ in backend.calls].count("disconnect") == 1
    assert "target_debug" not in resources.get_status()


def test_resource_conflict_fails_job_and_ai_owner_can_be_preempted():
    inspected = image()
    resources = ResourceManager()
    resources.acquire(ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt")
    blocked_backend = FakeBackend()
    blocked = OnlineFlashJobManager(
        lambda: blocked_backend,
        resources,
        image_provider=lambda _image_id: inspected,
    )

    failed = blocked.wait(blocked.start(JobRequest.full_sequence(inspected)), timeout=2)
    blocked.shutdown()

    assert failed.state is JobState.FAILED
    assert failed.error_code == FlashErrorCode.PROBE_BUSY.value
    assert "user:dashboard:rtt" in failed.error_message
    assert blocked_backend.calls == []
    resources.release("user:dashboard:rtt")
    resources.acquire(ResourceGroup.TARGET_DEBUG, "ai:session:observer")
    backend = FakeBackend()
    preempting = OnlineFlashJobManager(
        lambda: backend, resources, image_provider=lambda _image_id: inspected
    )
    succeeded = preempting.wait(
        preempting.start(JobRequest.full_sequence(inspected, preempt_ai=True)),
        timeout=2,
    )
    preempting.shutdown()
    assert succeeded.state is JobState.SUCCEEDED
    assert "target_debug" not in resources.get_status()


def test_second_start_is_rejected_while_program_is_blocked():
    backend = BlockingBackend()
    inspected = image()
    manager = OnlineFlashJobManager(
        lambda: backend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
    )
    first_id = manager.start(JobRequest.full_sequence(inspected))
    assert backend.program_started.wait(2)

    with pytest.raises(FlashError) as raised:
        manager.start(JobRequest.full_sequence(inspected))

    assert raised.value.code is FlashErrorCode.PROBE_BUSY
    backend.allow_program.set()
    manager.wait(first_id, timeout=2)
    manager.shutdown()


def test_stop_during_program_skips_remaining_stages_and_stays_stopping():
    backend = BlockingBackend()
    inspected = image()
    resources = ResourceManager()
    manager = OnlineFlashJobManager(
        lambda: backend, resources, image_provider=lambda _image_id: inspected
    )
    job_id = manager.start(JobRequest.full_sequence(inspected))
    assert backend.program_started.wait(2)

    stopping = manager.stop(job_id)
    repeated = manager.stop(job_id)

    assert stopping.state is JobState.STOPPING
    assert repeated.state is JobState.STOPPING
    with pytest.raises(TimeoutError):
        manager.wait(job_id, timeout=0.001)
    backend.allow_program.set()
    stopped = manager.wait(job_id, timeout=2)
    manager.shutdown()
    assert stopped.state is JobState.STOPPED
    assert 0 < stopped.total_progress < 1
    assert [name for name, _ in backend.calls] == [
        "connect",
        "erase",
        "program",
        "disconnect",
    ]
    assert "target_debug" not in resources.get_status()


def test_stop_during_disconnect_is_idempotent_and_finishes_stopped():
    backend = BlockingDisconnectBackend()
    manager = OnlineFlashJobManager(lambda: backend, ResourceManager())
    job_id = manager.start(JobRequest(actions=("connect", "disconnect")))
    assert backend.disconnect_started.wait(2)

    stopping = manager.stop(job_id)
    repeated = manager.stop(job_id)

    assert stopping.state is JobState.DISCONNECTING
    assert repeated.state is JobState.DISCONNECTING
    assert sum(
        event.message == "stop requested while disconnecting"
        for event in manager.events(job_id)
    ) == 1
    backend.allow_disconnect.set()
    assert manager.wait(job_id, timeout=2).state is JobState.STOPPED
    assert manager.stop(job_id).state is JobState.STOPPED
    manager.shutdown()


def test_stop_after_worker_claim_releases_without_provider_or_backend_factory():
    resources = BlockingAcquireResourceManager()
    inspected = image()
    provider_calls = []
    factory_calls = []

    def provide(image_id):
        provider_calls.append(image_id)
        return inspected

    def backend_factory():
        factory_calls.append(True)
        return FakeBackend()

    manager = OnlineFlashJobManager(backend_factory, resources, provide)
    job_id = manager.start(JobRequest.program_only(inspected))
    assert resources.acquire_started.wait(2)

    assert manager.stop(job_id).state is JobState.STOPPING
    resources.allow_acquire_return.set()
    assert manager.wait(job_id, timeout=2).state is JobState.STOPPED
    manager.shutdown()
    assert provider_calls == []
    assert factory_calls == []


def test_stop_before_worker_claim_has_no_external_side_effects():
    gate = threading.Event()
    entered = threading.Event()
    backend = FakeBackend()
    resources = ResourceManager()
    inspected = image()
    provider_calls = []
    manager = OnlineFlashJobManager(
        lambda: backend,
        resources,
        image_provider=lambda image_id: provider_calls.append(image_id) or inspected,
    )
    original_run = manager._run

    def gated_run(job_id):
        entered.set()
        assert gate.wait(2)
        original_run(job_id)

    manager._run = gated_run
    job_id = manager.start(JobRequest.program_only(inspected))
    assert entered.wait(2)

    assert manager.stop(job_id).state is JobState.STOPPED
    gate.set()
    assert manager.wait(job_id, timeout=2).state is JobState.STOPPED
    manager.shutdown()
    assert provider_calls == []
    assert backend.calls == []
    assert resources.get_status() == {}


def test_stop_while_queued_is_terminal_and_worker_does_not_touch_backend():
    gate = threading.Event()
    backend = FakeBackend()
    inspected = image()
    manager = OnlineFlashJobManager(
        lambda: backend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
    )
    blocker = manager._executor.submit(lambda: gate.wait(2))
    job_id = manager.start(JobRequest.full_sequence(inspected))

    assert manager.stop(job_id).state is JobState.STOPPED
    assert manager.wait(job_id, timeout=0.1).state is JobState.STOPPED
    gate.set()
    blocker.result(2)
    manager.shutdown()
    assert backend.calls == []


def test_disconnect_failure_overrides_success_or_stop():
    inspected = image()
    backend = FailingBackend("disconnect")
    manager = OnlineFlashJobManager(
        lambda: backend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
    )
    result = manager.wait(manager.start(JobRequest.full_sequence(inspected)), timeout=2)
    manager.shutdown()

    assert result.state is JobState.FAILED
    assert result.error_code == FlashErrorCode.UNKNOWN_ERROR.value
    assert "disconnect failed" in result.error_message


def test_disconnect_failure_does_not_replace_primary_stage_error():
    inspected = image()
    backend = StageAndDisconnectFailingBackend("program")
    manager = OnlineFlashJobManager(
        lambda: backend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
    )
    result = manager.wait(manager.start(JobRequest.full_sequence(inspected)), timeout=2)
    manager.shutdown()

    assert result.state is JobState.FAILED
    assert result.error_code == FlashErrorCode.PROGRAM_FAIL.value
    assert result.error_message == "program boom"


@pytest.mark.parametrize("delete_lease", [True, False])
def test_release_failure_still_terminalizes_and_clears_active_gate(delete_lease):
    resources = ReleaseFailingResourceManager(delete_lease)
    manager = OnlineFlashJobManager(FakeBackend, resources)
    request = JobRequest(actions=("connect", "disconnect"))

    first = manager.wait(manager.start(request), timeout=2)

    assert first.state is JobState.FAILED
    assert first.error_code == FlashErrorCode.UNKNOWN_ERROR.value
    assert "release failed" in first.error_message
    second_id = manager.start(request)
    second = manager.wait(second_id, timeout=2)
    assert second.state is JobState.FAILED
    manager.shutdown()


def test_release_failure_preserves_primary_error_and_emits_cleanup_log():
    resources = ReleaseFailingResourceManager(delete_lease=True)
    backend = FailingBackend("connect")
    manager = OnlineFlashJobManager(lambda: backend, resources)
    job_id = manager.start(JobRequest(actions=("connect", "disconnect")))

    result = manager.wait(job_id, timeout=2)

    assert result.state is JobState.FAILED
    assert result.error_code == FlashErrorCode.CONNECT_FAIL.value
    assert result.error_message == "connect boom"
    assert any(
        event.event == "log" and "release also failed" in event.message
        for event in manager.events(job_id)
    )
    manager.shutdown()


def test_worker_event_failure_still_sets_error_and_clears_active_gate():
    gate = threading.Event()
    manager = OnlineFlashJobManager(FakeBackend, ResourceManager())
    blocker = manager._executor.submit(lambda: gate.wait(2))
    request = JobRequest(actions=("connect", "disconnect"))
    job_id = manager.start(request)
    original_emit = manager._emit_locked

    def fail_emit(*_args, **_kwargs):
        raise RuntimeError("event boom")

    manager._emit_locked = fail_emit
    gate.set()
    blocker.result(2)
    result = manager.wait(job_id, timeout=2)

    assert result.state is JobState.FAILED
    assert result.error_code == FlashErrorCode.UNKNOWN_ERROR.value
    assert "event boom" in result.error_message
    manager._emit_locked = original_emit
    second_id = manager.start(request)
    assert manager.wait(second_id, timeout=2).state is JobState.SUCCEEDED
    manager.shutdown()


def test_stop_after_succeeded_or_failed_is_a_no_op():
    request = JobRequest(actions=("connect", "disconnect"))
    succeeded_manager = OnlineFlashJobManager(FakeBackend, ResourceManager())
    succeeded_id = succeeded_manager.start(request)
    succeeded = succeeded_manager.wait(succeeded_id, timeout=2)
    assert succeeded_manager.stop(succeeded_id) == succeeded
    succeeded_manager.shutdown()

    failed_manager = OnlineFlashJobManager(
        lambda: FailingBackend("connect"), ResourceManager()
    )
    failed_id = failed_manager.start(request)
    failed = failed_manager.wait(failed_id, timeout=2)
    assert failed_manager.stop(failed_id) == failed
    failed_manager.shutdown()


def test_events_are_capped_without_reusing_sequences_and_can_be_waited_for():
    inspected = image()
    manager = OnlineFlashJobManager(
        FakeBackend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
        max_events=4,
    )
    job_id = manager.start(JobRequest.full_sequence(inspected))
    manager.wait(job_id, timeout=2)
    retained = manager.events(job_id)

    assert len(retained) == 4
    assert [event.sequence for event in retained] == list(
        range(retained[0].sequence, retained[-1].sequence + 1)
    )
    assert retained[0].sequence > 1
    assert manager.events(job_id, after=retained[-2].sequence) == [retained[-1]]
    assert manager.wait_for_events(job_id, after=retained[-2].sequence, timeout=0) == [
        retained[-1]
    ]
    assert {event.event for event in retained} <= {"state", "progress", "log", "error"}
    manager.shutdown()


def test_wait_for_events_unblocks_concurrent_waiter():
    backend = BlockingBackend()
    inspected = image()
    manager = OnlineFlashJobManager(
        lambda: backend,
        ResourceManager(),
        image_provider=lambda _image_id: inspected,
    )
    job_id = manager.start(JobRequest.full_sequence(inspected))
    assert backend.program_started.wait(2)
    after = manager.events(job_id)[-1].sequence
    observed = []
    waiter = threading.Thread(
        target=lambda: observed.extend(manager.wait_for_events(job_id, after, timeout=2))
    )
    waiter.start()
    manager.stop(job_id)
    waiter.join(2)
    backend.allow_program.set()
    manager.wait(job_id, timeout=2)
    manager.shutdown()
    assert not waiter.is_alive()
    assert observed[0].state is JobState.STOPPING


def test_image_is_revalidated_only_immediately_before_program():
    inspected = image()
    inspections = []

    def provide(image_id):
        inspections.append(image_id)
        return inspected

    manager = OnlineFlashJobManager(FakeBackend, ResourceManager(), provide)
    result = manager.wait(manager.start(JobRequest.program_only(inspected)), timeout=2)
    manager.shutdown()
    assert result.state is JobState.SUCCEEDED
    assert inspections == [inspected.image_id]


def test_verify_only_refreshes_image_immediately_before_backend_verify():
    inspected = image()
    inspections = []
    backend = FakeBackend()

    def provide(image_id):
        inspections.append(image_id)
        return inspected

    manager = OnlineFlashJobManager(lambda: backend, ResourceManager(), provide)
    request = JobRequest(
        actions=("connect", "verify", "disconnect"), image_id=inspected.image_id
    )

    result = manager.wait(manager.start(request), timeout=2)
    manager.shutdown()

    assert result.state is JobState.SUCCEEDED
    assert inspections == [inspected.image_id]
    assert backend.calls[1] == ("verify", inspected)
    assert result.image_sha256 == inspected.sha256


def test_full_sequence_refreshes_image_before_program_and_verify():
    first = image()
    latest = ImageInspection(
        image_id=first.image_id,
        file_name="latest.bin",
        file_path="/snapshots/latest.bin",
        format="bin",
        size=2048,
        sha256="latest-hash",
        start=0x8000000,
        end=0x8000800,
        base_address=0x8000000,
    )
    supplied = iter((first, latest))
    backend = FakeBackend()
    manager = OnlineFlashJobManager(
        lambda: backend, ResourceManager(), lambda _image_id: next(supplied)
    )

    result = manager.wait(manager.start(JobRequest.full_sequence(first)), timeout=2)
    manager.shutdown()

    assert result.state is JobState.SUCCEEDED
    assert next(value for name, value in backend.calls if name == "program") is first
    assert next(value for name, value in backend.calls if name == "verify") is latest
    assert result.file_path == latest.file_path
    assert result.image_sha256 == latest.sha256


def test_image_provider_failure_before_verify_disconnects_and_releases():
    backend = FakeBackend()
    resources = ResourceManager()

    def fail_provider(_image_id):
        raise FlashError(FlashErrorCode.FILE_NOT_FOUND, "snapshot changed")

    manager = OnlineFlashJobManager(lambda: backend, resources, fail_provider)
    request = JobRequest(
        actions=("connect", "verify", "disconnect"), image_id="missing-image"
    )

    result = manager.wait(manager.start(request), timeout=2)
    manager.shutdown()

    assert result.state is JobState.FAILED
    assert result.error_code == FlashErrorCode.FILE_NOT_FOUND.value
    assert [name for name, _ in backend.calls] == ["connect", "disconnect"]
    assert resources.get_status() == {}


def test_stop_while_verify_provider_is_blocked_skips_backend_verify():
    backend = FakeBackend()
    inspected = image()
    provider_started = threading.Event()
    allow_provider = threading.Event()

    def blocking_provider(_image_id):
        provider_started.set()
        assert allow_provider.wait(2)
        return inspected

    manager = OnlineFlashJobManager(
        lambda: backend, ResourceManager(), blocking_provider
    )
    request = JobRequest(
        actions=("connect", "verify", "disconnect"), image_id=inspected.image_id
    )
    job_id = manager.start(request)
    assert provider_started.wait(2)

    assert manager.stop(job_id).state is JobState.STOPPING
    allow_provider.set()
    assert manager.wait(job_id, timeout=2).state is JobState.STOPPED
    manager.shutdown()
    assert [name for name, _ in backend.calls] == ["connect", "disconnect"]


def test_completed_history_is_bounded_and_shutdown_rejects_new_jobs():
    manager = OnlineFlashJobManager(
        FakeBackend, ResourceManager(), max_completed=2
    )
    request = JobRequest(actions=("connect", "disconnect"))
    ids = []
    for _ in range(3):
        job_id = manager.start(request)
        ids.append(job_id)
        manager.wait(job_id, timeout=2)

    assert [item.job_id for item in manager.list()] == ids[-2:]
    with pytest.raises(KeyError):
        manager.get(ids[0])
    manager.shutdown()
    with pytest.raises(RuntimeError):
        manager.start(request)


def test_shutdown_timeout_requests_stop_and_returns_without_waiting_forever():
    backend = ShutdownBlockingBackend()
    manager = OnlineFlashJobManager(lambda: backend, ResourceManager())
    job_id = manager.start(JobRequest(actions=("connect", "disconnect")))
    assert backend.connect_started.wait(1)

    completed = None
    try:
        started = time.monotonic()
        completed = manager.shutdown(wait=True, timeout=0.05)
        elapsed = time.monotonic() - started
        assert completed is False
        assert elapsed < 0.5
        assert manager.get(job_id).state is JobState.STOPPING
        with pytest.raises(RuntimeError, match="shut down"):
            manager.start(JobRequest(actions=("connect", "disconnect")))
    finally:
        backend.allow_connect.set()
        if completed is None:
            manager.shutdown(wait=True)
        else:
            assert manager.wait(job_id, timeout=2).state is JobState.STOPPED


def test_shutdown_waits_gracefully_when_active_job_finishes_within_timeout():
    backend = ShutdownBlockingBackend()
    manager = OnlineFlashJobManager(lambda: backend, ResourceManager())
    job_id = manager.start(JobRequest(actions=("connect", "disconnect")))
    assert backend.connect_started.wait(1)
    releaser = threading.Timer(0.05, backend.allow_connect.set)
    releaser.start()

    try:
        completed = manager.shutdown(wait=True, timeout=1.0)
    finally:
        backend.allow_connect.set()
        releaser.join(1)
        manager.shutdown(wait=True)
    assert completed is True
    assert manager.get(job_id).state is JobState.STOPPED


def test_queued_stop_holds_admission_until_work_item_is_drained():
    backend = FakeBackend()
    resources = CountingResourceManager()
    manager = OnlineFlashJobManager(lambda: backend, resources, max_completed=5)
    manager._executor.shutdown()
    executor = ControlledExecutor()
    manager._executor = executor
    request = JobRequest(actions=("connect", "disconnect"))
    stopped_id = manager.start(request)
    stopped_job = manager._jobs[stopped_id]

    assert manager.stop(stopped_id).state is JobState.STOPPED
    assert stopped_job.future is not None and not stopped_job.future.cancelled()
    for _ in range(500):
        with pytest.raises(FlashError) as raised:
            manager.start(request)
        assert raised.value.code is FlashErrorCode.PROBE_BUSY

    assert executor.submit_count == 1
    assert len(executor.tasks) == 1
    assert resources.acquire_calls == 0
    assert backend.calls == []
    assert [item.job_id for item in manager.list()] == [stopped_id]
    assert executor.run_next().exception() is None
    assert manager._active_id is None
    real_id = manager.start(JobRequest(actions=("connect", "disconnect")))
    assert executor.submit_count == 2
    assert executor.run_next().exception() is None
    assert manager.wait(real_id, timeout=2).state is JobState.SUCCEEDED
    manager.shutdown()
    assert resources.acquire_calls == 1


def test_cancelled_future_done_callback_drains_active_gate_without_running_job():
    backend = FakeBackend()
    resources = CountingResourceManager()
    manager = OnlineFlashJobManager(lambda: backend, resources)
    manager._executor.shutdown()
    executor = ControlledExecutor()
    manager._executor = executor
    request = JobRequest(actions=("connect", "disconnect"))
    job_id = manager.start(request)
    job = manager._jobs[job_id]

    assert job.future is not None and job.future.cancel()
    assert manager.wait(job_id, timeout=0.1).state is JobState.STOPPED
    assert manager._active_id is None
    assert executor.run_next().cancelled()
    assert resources.acquire_calls == 0
    assert backend.calls == []
    manager.shutdown()


def test_submit_failure_rolls_back_active_job_transactionally():
    manager = OnlineFlashJobManager(FakeBackend, ResourceManager())
    manager._executor.shutdown()
    manager._executor = FailingSubmitExecutor()

    with pytest.raises(RuntimeError, match="submit"):
        manager.start(JobRequest(actions=("connect", "disconnect")))

    assert manager.list() == []
    assert manager._active_id is None
    assert manager._jobs == {}
    manager._executor = ThreadPoolExecutor(max_workers=1)
    job_id = manager.start(JobRequest(actions=("connect", "disconnect")))
    assert manager.wait(job_id, timeout=2).state is JobState.SUCCEEDED
    manager.shutdown()


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("max_completed", 0),
        ("max_completed", -1),
        ("max_completed", True),
        ("max_events", 0),
        ("max_events", -1),
        ("max_events", False),
    ],
)
def test_constructor_rejects_non_positive_or_boolean_limits(argument, value):
    options = {argument: value}
    with pytest.raises(ValueError):
        OnlineFlashJobManager(FakeBackend, ResourceManager(), **options)


def test_shutdown_is_rejected_before_request_validation():
    manager = OnlineFlashJobManager(FakeBackend, ResourceManager())
    manager.shutdown()
    invalid = JobRequest(actions=("invalid",))
    with pytest.raises(RuntimeError, match="shut down"):
        manager.start(invalid)


@pytest.mark.parametrize(
    "job_request",
    [
        JobRequest(actions=("erase", "disconnect")),
        JobRequest(actions=("connect", "erase")),
        JobRequest(actions=("connect", "dance", "disconnect")),
        JobRequest(actions=("connect", "reset", "reset", "disconnect")),
        JobRequest(actions=("connect", "program", "disconnect")),
        JobRequest(actions=("connect", "disconnect"), sector_addresses=(0x8000000,)),
        JobRequest(actions=("connect", "erase", "verify", "disconnect"), image_id="x"),
    ],
)
def test_invalid_requests_are_rejected(job_request):
    manager = OnlineFlashJobManager(FakeBackend, ResourceManager())
    with pytest.raises(ValueError):
        manager.start(job_request)
    manager.shutdown()


def test_sector_erase_uses_addresses_and_snapshots_are_immutable():
    backend = FakeBackend()
    manager = OnlineFlashJobManager(lambda: backend, ResourceManager())
    request = JobRequest(
        actions=("connect", "erase", "disconnect"),
        sector_addresses=(0x8000000, 0x8001000),
    )
    job_id = manager.start(request)
    snapshot = manager.wait(job_id, timeout=2)
    manager.shutdown()
    assert backend.calls[1] == ("erase_sectors", request.sector_addresses)
    with pytest.raises(Exception):
        snapshot.state = JobState.FAILED
