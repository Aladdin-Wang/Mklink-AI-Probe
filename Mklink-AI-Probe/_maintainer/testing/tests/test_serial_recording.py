"""Shared file consumer ownership, bounded draining and disk failure isolation."""
import csv
import threading

import pytest

from mklink.remote.dashboards import SerialStreamManager
from mklink.serial._logger import FileLogger
from test_serial_automation import ports, wait_for
from test_runtime_uart import uart_app, client_factory, uart_attach, call


def rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def test_record_selected_ports_stop_drains_pending_bytes_once(ports, tmp_path):
    manager = SerialStreamManager(); manager.start([{'port':'A'}, {'port':'B'}])
    path = tmp_path/'log.csv'
    try:
        manager.start_recording(str(path), 'csv', ports=['A'])
        # Leave the last batch pending in the actual batcher; manager stop must drain it.
        manager._byte_batcher.feed(b'abc', 'RX', 'A')
        manager._byte_batcher.feed(b'other', 'RX', 'B')
        manager._byte_batcher.feed(b'end', 'TX', 'A')
        manager.stop()
        assert [(r['direction'], r['raw_hex']) for r in rows(path)] == [('RX','616263'), ('TX','656E64')]
        assert manager.get_status()['recording']['state'] == 'completed'
        assert not manager.worker_alive and len(ports.instances) == 2
        assert manager.stop_recording()['state'] == 'completed'
    finally: manager.stop()


def test_repeated_start_rejects_before_file_creation_and_old_files_are_not_truncated(ports, tmp_path):
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    first, second = tmp_path/'one.txt', tmp_path/'two.txt'
    try:
        manager.start_recording(str(first))
        with pytest.raises(RuntimeError, match='already active'): manager.start_recording(str(second))
        assert not second.exists()
        manager.stop_recording()
        first.write_text('keep', encoding='utf-8')
        with pytest.raises(FileExistsError): manager.start_recording(str(first))
        assert first.read_text(encoding='utf-8') == 'keep'
        assert manager.get_status()['recording']['state'] == 'failed'
        manager.start_recording(str(second)); manager.stop_recording()
    finally: manager.stop()


@pytest.mark.parametrize('changes', [dict(ports=[]), dict(ports=['A','A']), dict(ports=['B']),
    dict(max_size=True), dict(max_size=-1), dict(format='json'), dict(path='')])
def test_invalid_request_never_creates_file(ports, tmp_path, changes):
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    path = tmp_path/'invalid.txt'
    try:
        with pytest.raises(ValueError): manager.start_recording(**dict(dict(path=str(path)), **changes))
        assert not path.exists()
    finally: manager.stop()


def test_disk_failure_is_visible_and_reader_keeps_working(ports, tmp_path, monkeypatch):
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    def fail(*args, **kw): raise OSError('disk full')
    monkeypatch.setattr(FileLogger, 'log', fail)
    try:
        manager.start_recording(str(tmp_path/'full.txt'))
        ports.instances[-1].rx.put(b'first')
        wait_for(lambda: manager.get_status()['recording']['state'] == 'failed')
        assert 'disk full' in manager.get_status()['recording']['error']
        assert manager._recorder._logger._file is None
        ports.instances[-1].rx.put(b'second')
        wait_for(lambda: manager.get_status()['stats']['rx_bytes'] == 11)
        assert manager.get_status()['ports']['A'] == 'open'
    finally: manager.stop()


def test_blocked_disk_stop_retains_worker_and_prevents_session_replacement(ports, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = FileLogger.log
    def slow(self, *args, **kw):
        entered.set(); assert release.wait(5)
        return original(self, *args, **kw)
    monkeypatch.setattr(FileLogger, 'log', slow)
    manager = SerialStreamManager(); manager.start([{'port':'A'}, {'port':'B'}])
    try:
        manager.start_recording(str(tmp_path/'slow.csv'), 'csv')
        ports.instances[-2].rx.put(b'a'); assert entered.wait(1)
        ports.instances[-1].rx.put(b'b')
        wait_for(lambda: manager.get_status()['stats']['rx_bytes'] == 2)
        with pytest.raises(TimeoutError): manager._recorder.stop(timeout=.01)
        assert manager.get_status()['recording']['state'] == 'stopping'
        with pytest.raises(RuntimeError): manager.start_recording(str(tmp_path/'other.csv'))
        # Stop with the real lifecycle lock held: the local history reader must not need it.
        release.set(); manager.stop()
        assert not manager.worker_alive
        assert manager.get_status()['recording']['state'] == 'completed'
        assert {r['raw_hex'] for r in rows(tmp_path/'slow.csv')} == {'61','62'}
        manager.start([{'port':'A'}]); manager.stop()
    finally: release.set(); manager.stop()


def test_slow_consumer_reports_ring_overflow_instead_of_success(ports, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = FileLogger.log
    def slow(self, *args, **kw):
        entered.set(); assert release.wait(5)
        return original(self, *args, **kw)
    monkeypatch.setattr(FileLogger, 'log', slow)
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    try:
        manager.start_recording(str(tmp_path/'overflow.txt'))
        manager._history.append(b'a','RX','A'); assert entered.wait(1)
        for _ in range(520): manager._history.append(b'b','RX','A')
        release.set()
        wait_for(lambda: manager.get_status()['recording']['state'] == 'failed')
        assert 'incomplete' in manager.get_status()['recording']['error']
    finally: release.set(); manager.stop()


def test_api_clients_share_recording_and_disconnect_does_not_stop_it(uart_app, tmp_path):
    client, control, managers, _, _ = uart_app
    owner, peer = uart_attach(client), uart_attach(client)
    assert call(client, owner, 'serial_start', {'ports':[{'port':'TEST'}]}).status_code == 200
    path = tmp_path/'shared.csv'
    response = call(client, peer, 'serial_recording_start', {'path':str(path), 'format':'csv'})
    assert response.status_code == 200, response.text
    assert call(client, owner, 'serial_recording_start', {'path':str(tmp_path/'other.csv')}).status_code == 409
    assert not (tmp_path/'other.csv').exists()
    assert client.post('/_runtime/detach', json={'session_id':peer}).status_code == 200
    status = call(client, owner, 'serial_status').json()['recording']
    assert status['active'] and status['path'] == str(path)
    managers['serial']._byte_batcher.feed(b'keep', 'RX', 'TEST')
    stopped = client.post('/api/dash/serial/recording/stop')
    assert stopped.status_code == 200 and stopped.json()['state'] == 'completed'
    assert rows(path)[0]['raw_hex'] == '6B656570'
    assert managers['serial'].running
    assert call(client, owner, 'serial_recording_start', {'path':str(path)}).status_code == 409
    assert call(client, owner, 'serial_recording_start', {'path':str(tmp_path/'bad'), 'max_size':True}).status_code == 422
    assert call(client, owner, 'serial_recording_start', {'path':str(tmp_path/'bad'), 'ports':['missing']}).status_code == 400
    assert not (tmp_path/'bad').exists()
    assert not control.uart_operations


def test_manager_timeout_keeps_recording_owned_until_late_drain_finishes(ports, tmp_path, monkeypatch):
    from mklink.serial._recording import SerialRecorder
    entered, release = threading.Event(), threading.Event()
    original_log, original_stop = FileLogger.log, SerialRecorder.stop
    def slow(self, *args, **kw):
        entered.set(); assert release.wait(5)
        return original_log(self, *args, **kw)
    monkeypatch.setattr(FileLogger, 'log', slow)
    monkeypatch.setattr(SerialRecorder, 'stop', lambda self: original_stop(self, timeout=.01))
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    try:
        manager.start_recording(str(tmp_path/'late.txt'))
        manager._history.append(b'a','RX','A'); assert entered.wait(1)
        with pytest.raises(TimeoutError): manager.stop()
        assert manager.worker_alive and not manager.running
        with pytest.raises(RuntimeError, match='workers'): manager.start([{'port':'B'}])
        assert len(ports.instances) == 1
        release.set(); wait_for(lambda: not manager.worker_alive)
        manager.stop(); manager.start([{'port':'B'}])
        assert manager.get_status()['recording']['state'] == 'completed'
    finally: release.set(); manager.stop()


def test_stop_does_not_overwrite_terminal_result_during_thread_exit(ports, tmp_path, monkeypatch):
    from mklink.serial._recording import SerialRecorder
    exited, release = threading.Event(), threading.Event()
    original = SerialRecorder._run
    def exiting(self):
        original(self); exited.set(); assert release.wait(5)
    monkeypatch.setattr(SerialRecorder, '_run', exiting)
    manager = SerialStreamManager(); manager.start([{'port':'A'}])
    try:
        manager.start_recording(str(tmp_path/'exit.txt'))
        recorder = manager._recorder
        recorder._cancel.set(); assert exited.wait(1)
        with pytest.raises(TimeoutError): recorder.stop(timeout=.01)
        assert recorder.status()['state'] == 'completed'
        release.set(); recorder.stop()
        assert recorder.status()['state'] == 'completed' and not recorder.worker_alive
    finally: release.set(); manager.stop()
