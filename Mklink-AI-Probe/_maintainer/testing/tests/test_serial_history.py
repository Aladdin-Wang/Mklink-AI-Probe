"""Raw serial history is bounded, non-destructive and distinct from line parsing."""
import threading
import pytest
from mklink.remote.serial_stream import SerialHistory
from mklink.remote.dashboards import SerialStreamManager
from mklink.serial import _monitor
from test_runtime_uart import uart_app, client_factory, uart_attach, call


def test_independent_cursors_gap_paging_and_copies():
    history = SerialHistory()
    cursor = history.read()
    for i in range(600):
        history.append(bytes([i % 256]) * 4096, 'RX', 'A' if i % 2 else 'B')
    assert history.read()['entries'] == []
    first = history.read(cursor['session'], 0)
    assert len(first['entries']) == 256
    assert (first['dropped_batches'], first['next_seq'], first['latest_seq']) == (88, 344, 600)
    assert history.read(cursor['session'], 0) == first
    first['entries'][0]['hex'] = 'tampered'
    assert history.read(cursor['session'], 0)['entries'][0]['hex'] != 'tampered'
    second = history.read(cursor['session'], 344)
    assert len(second['entries']) == 256 and second['next_seq'] == 600
    assert second['dropped_batches'] == 0
    assert history.read(cursor['session'], 600)['entries'] == []
    with pytest.raises(RuntimeError, match='session changed'):
        SerialHistory().read(cursor['session'], 0)


@pytest.mark.parametrize('args', [dict(after=0), dict(session='x'), dict(limit=True),
    dict(limit=0), dict(limit=257), dict(limit=1.5), dict(limit='1'),
    dict(after=-1, session='x'), dict(after=True, session='x')])
def test_invalid_cursors(args):
    with pytest.raises(ValueError): SerialHistory().read(**args)


def test_raw_bounds_and_ahead_cursor():
    history = SerialHistory()
    for data in (b'', b'A' * 4097):
        with pytest.raises(ValueError): history.append(data, 'RX', 'A')
    with pytest.raises(ValueError, match='ahead'):
        history.read(history.read()['session'], 1)
    assert history.read()['next_seq'] == 0


def test_real_monitor_stop_flushes_unterminated_bytes_and_restart_isolates(monkeypatch):
    class Port:
        def __init__(self, **kwargs): self.is_open = True
        def open(self): return True
        def close(self): self.is_open = False
        def read_available(self): return b''
    monkeypatch.setattr(_monitor, 'SerialPort', Port)
    manager = SerialStreamManager()
    manager.start([{'port': 'TEST'}, {'port': 'OTHER'}])
    first = manager.get_history()
    try:
        monitor = manager._monitor
        assert not hasattr(monitor, '_events')
        monitor._process_rx_data('TEST', b'no newline\x00\xff', None, bytearray())
        monitor._process_rx_data('OTHER', b'other', None, bytearray())
        manager.stop()
        page = manager.get_history(first['session'], first['next_seq'])
        assert not page['running'] and not manager.worker_alive
        assert [(e['port'], bytes.fromhex(e['hex'])) for e in page['entries']] == [
            ('TEST', b'no newline\x00\xff'), ('OTHER', b'other')]
        assert all(e['direction'] == 'RX' and e['timestamp_ns'] > 0 for e in page['entries'])
        page['config'][0]['port'] = 'tampered'
        assert manager.get_history()['config'][0]['port'] == 'TEST'
        manager.start([{'port': 'TEST'}])
        with pytest.raises(RuntimeError, match='session changed'):
            manager.get_history(first['session'], 0)
        assert manager.get_history()['next_seq'] == 0
    finally:
        manager.stop()


def test_concurrent_publishers_preserve_sequence_and_payloads():
    history = SerialHistory()
    session = history.read()['session']
    threads = [threading.Thread(target=lambda port=p: [history.append(bytes([i]), 'RX', port)
               for i in range(100)]) for p in ('A', 'B')]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2); assert not thread.is_alive()
    entries = history.read(session, 0)['entries']
    assert [entry['seq'] for entry in entries] == list(range(1, 201))
    for port in ('A', 'B'):
        assert [int(e['hex'], 16) for e in entries if e['port'] == port] == list(range(100))


@pytest.mark.parametrize('args,status', [({}, 200), ({'limit': 0}, 400), ({'limit': 257}, 400),
    ({'limit': True}, 422), ({'limit': '1'}, 422), ({'after': 0}, 400),
    ({'session': 'other', 'after': 0}, 409), ({'after': 1.5}, 422), ({'unknown': 1}, 422)])
def test_history_rpc_does_not_open_uart_or_target(uart_app, args, status):
    http, control, managers, factory, _ = uart_app
    result = call(http, uart_attach(http), 'serial_history', args)
    assert result.status_code == status, result.text
    assert not factory.instances and managers['serial']._monitor is None
    assert control.app.state.mklink_state['device'] is None
