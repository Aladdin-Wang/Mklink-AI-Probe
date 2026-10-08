import sys
from types import SimpleNamespace

import pytest
from mklink import cli, systemview_cli
from mklink.remote.dashboards import SystemViewStreamManager
from mklink.runtime import RuntimeErrorResponse


class CaptureClient:
    def __init__(self, reused=False, lost=False, stop_error=False):
        self.manager = SystemViewStreamManager()
        self.reused, self.lost, self.stop_error = reused, lost, stop_error
        self.calls = []
        self.manager._process_events([{'kind': 'init'}], now=0)

    def connect(self, **kwargs):
        self.connection = kwargs

    def call(self, name, arguments=None):
        self.calls.append(name)
        if name == 'systemview_start':
            return {'reused': self.reused}
        if name == 'systemview_capture_history':
            return self.manager.read_history(**(arguments or {}))
        if name == 'systemview_status':
            if self.lost:
                self.manager._max_history = 1
            self.manager._process_events([
                {'kind': 'task_start_exec' if n % 2 == 0 else 'task_stop_exec',
                 'task_id': 7, 'task_name': 'capture-task-unique', 't_us': n}
                for n in range(1100)], now=0)
            return {'running': True, 'cpu_freq': 72000000}
        if name == 'systemview_stop':
            if self.stop_error:
                raise RuntimeErrorResponse('borrowed', status_code=409)
            return {}
        raise AssertionError(name)

    def close(self):
        self.calls.append('close')


@pytest.mark.parametrize('reused', [False, True])
def test_cli_report_uses_shared_capture_and_preserves_borrowed_session(monkeypatch, tmp_path, reused):
    client = CaptureClient(reused=reused)
    monkeypatch.setattr(systemview_cli, 'RuntimeClient', lambda **kwargs: client)
    clock = iter([0, 1])
    monkeypatch.setattr(systemview_cli, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr('mklink.connect', lambda **kwargs: pytest.fail('direct connection'))
    output = tmp_path/'report.html'
    monkeypatch.setattr(sys, 'argv', ['mklink', 'systemview-report', '--probe', 'board',
                                    '--duration', '.5', '--out', str(output), '--no-browser'])
    cli.main()
    assert output.is_file() and 'capture-task-unique' in output.read_text(encoding='utf-8')
    assert client.connection['probe'] == 'board'
    assert client.calls.count('systemview_stop') == (0 if reused else 1)
    assert client.calls[-1] == 'close'
    assert client.calls.count('systemview_capture_history') == 4


def test_lost_history_prevents_report_and_stops_owned_capture_once(monkeypatch, tmp_path):
    client = CaptureClient(lost=True, stop_error=True)
    monkeypatch.setattr(systemview_cli, 'RuntimeClient', lambda **kwargs: client)
    output = tmp_path/'missing.html'
    args = SimpleNamespace(command='systemview-report', duration=1, port=None, probe='board',
                           out=str(output), no_browser=True)
    with pytest.raises(SystemExit, match='lost events'):
        systemview_cli.run(args)
    assert not output.exists()
    assert client.calls.count('systemview_stop') == 1 and client.calls[-1] == 'close'


def test_analysis_uses_existing_formatter_and_stops_owned_capture(monkeypatch, capsys):
    client = CaptureClient()
    monkeypatch.setattr(systemview_cli, 'RuntimeClient', lambda **kwargs: client)
    clock = iter([0, 1])
    monkeypatch.setattr(systemview_cli, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'systemview-analyze', '--probe', 'board', '--duration', '.5'])
    cli.main()
    assert capsys.readouterr().out
    assert client.calls.count('systemview_stop') == 1


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf')])
def test_invalid_duration_does_not_attach(monkeypatch, duration):
    monkeypatch.setattr(systemview_cli, 'RuntimeClient', lambda **kwargs: pytest.fail('attached'))
    with pytest.raises(SystemExit, match='positive'):
        systemview_cli.run(SimpleNamespace(duration=duration))
