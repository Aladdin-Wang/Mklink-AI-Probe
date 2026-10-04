"""Shared serial log must preserve raw traffic and fail honestly without owning a reader."""
import csv
import json
from types import SimpleNamespace
import pytest
from mklink.serial._logger import FileLogger
from mklink.serial._capture import SerialCapture
from mklink.serial._frame import FrameParser
from mklink.runtime import RuntimeErrorResponse
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory


def arguments(path, **changes):
    return SimpleNamespace(**dict(dict(serial_command='log', port='TEST', baud=19200,
        databits=7, stop=2, parity='E', probe=None, output=str(path), format=None,
        profile=None, duration=.04), **changes))


def test_csv_quoting_and_fields_after_plain_first_record(tmp_path):
    path = tmp_path / 'log.csv'
    with FileLogger(str(path), 'csv') as logger:
        logger.log('TX', 'COM,1', b'a,b"c\r\n')
        logger.log('RX', 'COM,1', b'\x00\xff', {'temperature': {'value': 25, 'unit': 'C'}})
    rows = list(csv.DictReader(path.open(encoding='utf-8', newline='')))
    assert all(None not in row for row in rows)
    assert rows[0]['ascii'] == 'a,b"c\r\n' and rows[0]['port'] == 'COM,1'
    assert rows[1]['raw_hex'] == '00FF'
    assert json.loads(rows[1]['decoded_json'])[0]['fields']['temperature']['value'] == 25


def test_text_preserves_trailing_bytes_and_timestamp(tmp_path):
    path = tmp_path / 'log.txt'
    with FileLogger(str(path)) as logger:
        logger.log('RX', 'TEST', b'a\r\n', timestamp=0)
    text = path.read_text(encoding='utf-8')
    assert '61 0D 0A' in text and "'a\\r\\n'" in text and '1970-' in text


def test_close_releases_file_when_flush_fails():
    class Broken:
        closed = False
        def flush(self): raise OSError('full disk')
        def close(self): self.closed = True
    logger = FileLogger('unused')
    broken = logger._file = Broken()
    with pytest.raises(OSError, match='full disk'): logger.close()
    assert broken.closed and logger._file is None


@pytest.mark.parametrize('format', ['txt', 'csv'])
def test_rapid_rotation_preserves_every_record_and_existing_archive(tmp_path, monkeypatch, format):
    from datetime import datetime
    import mklink.serial._logger as module
    class FixedClock(datetime):
        @classmethod
        def now(cls): return cls(2026, 10, 4, 12)
    monkeypatch.setattr(module, 'datetime', FixedClock)
    path = tmp_path / f'capture.{format}'
    existing = tmp_path / f'capture_20261004_120000.{format}'
    existing.write_text('keep', encoding='utf-8')
    with FileLogger(str(path), format, max_size=1) as logger:
        for value in range(20):
            logger.log('RX', 'TEST', bytes([value]))
    assert existing.read_text(encoding='utf-8') == 'keep'
    archives = sorted(p for p in tmp_path.iterdir() if p not in (path, existing))
    assert len(archives) == 20 and path.read_bytes() == b''
    if format == 'csv':
        records = []
        for archive in archives:
            with archive.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 1 and None not in rows[0]
            records.append(rows[0]['raw_hex'])
        assert sorted(records) == [f'{value:02X}' for value in range(20)]
    else:
        records = [p.read_text(encoding='utf-8').split('TEST: ')[1].split()[0] for p in archives]
        assert sorted(records) == [f'{value:02X}' for value in range(20)]


@pytest.mark.parametrize('failure', ['reserve', 'replace', 'reopen'])
def test_rotation_failure_retains_data_and_closes_cleanly(tmp_path, monkeypatch, failure):
    from pathlib import Path
    import builtins
    path = tmp_path / 'capture.txt'
    logger = FileLogger(str(path), max_size=1)
    logger.start()
    stream = logger._file
    if failure == 'reserve':
        monkeypatch.setattr(Path, 'open', lambda *a, **kw: (_ for _ in ()).throw(OSError('reserve failed')))
    elif failure == 'replace':
        monkeypatch.setattr(Path, 'replace', lambda *a, **kw: (_ for _ in ()).throw(OSError('replace failed')))
    else:
        monkeypatch.setattr(builtins, 'open', lambda *a, **kw: (_ for _ in ()).throw(OSError('reopen failed')))
    with pytest.raises(OSError, match=f'{failure} failed'):
        logger.log('RX', 'TEST', b'abc')
    assert stream.closed and logger._file is None
    with pytest.raises(RuntimeError, match='not open'):
        logger.log('RX', 'TEST', b'next')
    logger.close()
    logger.close()
    monkeypatch.undo()
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and '61 62 63' in files[0].read_text(encoding='utf-8')


def test_repeated_start_does_not_truncate_active_log(tmp_path):
    path = tmp_path / 'capture.txt'
    with FileLogger(str(path)) as logger:
        logger.log('RX', 'TEST', b'keep')
        with pytest.raises(RuntimeError, match='already open'):
            logger.start()
        logger.log('RX', 'TEST', b'next')
    assert 'keep' in path.read_text() and 'next' in path.read_text()


@pytest.mark.parametrize('params', [dict(duration=-1), dict(duration=float('nan')),
    dict(duration=float('inf')), dict(duration=True), dict(baud=0), dict(databits=4),
    dict(parity='X'), dict(stop=3), dict(profile='missing.json'), dict(format='bad')])
def test_invalid_log_never_attaches_or_truncates(monkeypatch, tmp_path, params):
    from mklink import cli
    output = tmp_path / 'out.csv'; output.write_text('keep')
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid log attached'))
    with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(output, **params))
    assert output.read_text() == 'keep'


@pytest.mark.parametrize('bad_path', ['missing/out.csv', '.'])
def test_bad_output_before_attach(monkeypatch, tmp_path, bad_path):
    from mklink import cli
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid path attached'))
    with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(tmp_path / bad_path))


@pytest.mark.parametrize('existing', [False, True])
def test_cli_borrows_or_stops_and_drains_final_batch(scan_cli, uart_app, monkeypatch, tmp_path, existing, capsys):
    cli, _, http, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    settings = {'ports': [{'port': 'TEST', 'baudrate': 19200, 'databits': 7, 'stopbits': 2, 'parity': 'E'}]}
    if existing: assert http.post('/api/dash/serial/start', json=settings).status_code == 200
    original_run = SerialCapture.run
    def run(capture, duration):
        manager._byte_batcher.feed(b'RAW\x00\xff', 'RX', 'TEST')
        manager._byte_batcher.feed(b'other', 'RX', 'OTHER')
        manager._byte_batcher.flush()
        original_run(capture, duration)
        # Only owned stop commits this final pending fragment.
        if not existing: manager._byte_batcher.feed(b'final', 'RX', 'TEST')
    monkeypatch.setattr(SerialCapture, 'run', run)
    output = tmp_path / 'out.csv'
    cli._cli_serial_dispatch(arguments(output))
    rows = list(csv.DictReader(output.open(encoding='utf-8', newline='')))
    assert bytes.fromhex(''.join(row['raw_hex'] for row in rows)) == b'RAW\x00\xff' + (b'' if existing else b'final')
    assert manager.running == existing and not control.sessions
    assert '[OK] 日志已保存' in capsys.readouterr().out


def test_connection_conflict_does_not_truncate(scan_cli, uart_app, tmp_path):
    cli, _, http, control, _, _ = scan_cli
    assert http.post('/api/dash/serial/start', json={'ports': [{'port':'TEST','baudrate':9600}]}).status_code == 200
    output = tmp_path / 'out.csv'; output.write_text('keep')
    with pytest.raises(SystemExit, match='different port/settings'):
        cli._cli_serial_dispatch(arguments(output))
    assert output.read_text() == 'keep' and not control.sessions and uart_app[2]['serial'].running


@pytest.mark.parametrize('failure', ['write', 'gap', 'port', 'session', 'close'])
def test_log_failure_nonzero_no_saved_and_no_leaked_owner(scan_cli, uart_app, monkeypatch, tmp_path, capsys, failure):
    cli, _, http, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    original_run = SerialCapture.run
    def run(capture, duration):
        if failure == 'gap':
            for _ in range(513): manager._history.append(b'A','RX','TEST')
        elif failure == 'session': manager._history.reset('replacement')
        elif failure == 'port': manager._monitor.port_status['TEST'] = 'error: removed'
        else: manager._history.append(b'A','RX','TEST')
        original_run(capture, duration)
    monkeypatch.setattr(SerialCapture, 'run', run)
    if failure == 'write':
        monkeypatch.setattr(FileLogger, 'log', lambda *a, **kw: (_ for _ in ()).throw(OSError('disk full')))
    if failure == 'close':
        original_close = FileLogger.close
        def close(self): original_close(self); raise OSError('close failed')
        monkeypatch.setattr(FileLogger, 'close', close)
    with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(tmp_path / 'out.csv'))
    assert '[OK] 日志已保存' not in capsys.readouterr().out
    assert not control.sessions and not manager.worker_alive and not manager.running


def test_capture_profile_keeps_raw_chunks_and_multiple_frames(tmp_path):
    profile = {'frame': {'header':'AA', 'tail':'FF'}, 'fields': []}
    parser = FrameParser(profile, max_buffer_bytes=1024)
    class Client:
        pages = 0
        def call(self, capability, args=None):
            self.pages += 1
            entries = [] if self.pages == 1 else [dict(seq=1, port='TEST', direction='RX', hex='aa01ffaa02ffaa',timestamp_ns=1,first_monotonic=1.,last_monotonic=1.)]
            return dict(session='session', next_seq=0, entries=entries, running=True,
                        ports={'TEST':'open'}, latest_seq=len(entries), dropped_batches=0,idle_cutoffs={'TEST':1.,'A':1.,'B':1.})
    path = tmp_path/'out.csv'
    with FileLogger(str(path),'csv') as logger:
        capture = SerialCapture(Client(),{'TEST':parser},logger); capture.page()
    row = next(csv.DictReader(path.open(encoding='utf-8',newline='')))
    assert row['raw_hex'] == 'AA01FFAA02FFAA'
    assert [f['raw_hex'] for f in json.loads(row['decoded_json'])] == ['aa01ff','aa02ff']
    with pytest.raises(ValueError, match='buffer limit'): parser.feed(b'A'*1024)


@pytest.mark.parametrize('bad_data', ['aa00', 'aa02'+'00'*64])
def test_capture_keeps_faulting_raw_batch_once_before_reporting_parser_error(tmp_path, bad_data):
    parser = FrameParser({'frame':{'header':'AA','length_field':{
        'offset':1,'size':1,'includes_header':True}}}, max_buffer_bytes=32)
    class Client:
        def call(self, capability, args=None):
            entries = [dict(seq=1,port='TEST',direction='RX',hex=bad_data,timestamp_ns=1,first_monotonic=1.,last_monotonic=1.)] if args and args['after']==0 else []
            return dict(session='one',next_seq=0,entries=entries,running=True,
                        ports={'TEST':'open'},latest_seq=1,dropped_batches=0,idle_cutoffs={'TEST':1.,'A':1.,'B':1.})
    path = tmp_path/'fault.csv'
    with FileLogger(str(path), 'csv') as logger:
        capture = SerialCapture(Client(), {'TEST':parser}, logger)
        with pytest.raises(ValueError): capture.page()
        assert capture.cursor == 1
        capture.drain()
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]['raw_hex'] == bad_data.upper()


def test_final_drain_write_failure_closes_owner_and_file(scan_cli, uart_app, monkeypatch, tmp_path, capsys):
    cli, _, _, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    monkeypatch.setattr(SerialCapture, 'run', lambda capture, duration: manager._byte_batcher.feed(b'final','RX','TEST'))
    closed = []
    original_close = FileLogger.close
    def close(self): original_close(self); closed.append(self._file is None)
    monkeypatch.setattr(FileLogger, 'close', close)
    monkeypatch.setattr(FileLogger, 'log', lambda *a, **kw: (_ for _ in ()).throw(OSError('final write failed')))
    with pytest.raises(SystemExit, match='final write failed'):
        cli._cli_serial_dispatch(arguments(tmp_path/'out.csv'))
    assert closed == [True] and not control.sessions and not manager.worker_alive
    assert '日志已保存' not in capsys.readouterr().out


def test_interrupt_drains_and_open_failure_releases(scan_cli, uart_app, monkeypatch, tmp_path):
    cli, _, _, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    original_run = SerialCapture.run
    def run(capture, duration):
        manager._byte_batcher.feed(b'interrupted','RX','TEST')
        original_page = capture.page
        def page(target=None):
            capture.page = original_page
            raise KeyboardInterrupt
        capture.page = page
        original_run(capture, duration)
    monkeypatch.setattr(SerialCapture, 'run', run)
    output=tmp_path/'out.csv'
    cli._cli_serial_dispatch(arguments(output,duration=0))
    rows=list(csv.DictReader(output.open(encoding='utf-8',newline='')))
    assert bytes.fromhex(''.join(row['raw_hex'] for row in rows)) == b'interrupted'
    assert not control.sessions and not manager.worker_alive
    monkeypatch.setattr(FileLogger,'start',lambda self: (_ for _ in ()).throw(OSError('no write access')))
    with pytest.raises(SystemExit,match='no write access'):
        cli._cli_serial_dispatch(arguments(output))
    assert not control.sessions and not manager.worker_alive
