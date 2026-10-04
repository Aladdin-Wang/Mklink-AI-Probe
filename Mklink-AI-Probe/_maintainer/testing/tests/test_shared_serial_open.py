"""Terminal input uses shared ownership and the same passive capture pipeline."""
import json
from types import SimpleNamespace
import pytest
from mklink.serial._terminal import SerialTerminal
from mklink.serial._console_monitor import ConsoleMonitor
from mklink.serial._autoreply import normalize_rules
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory, uart_attach, call


def args(**changes):
    return SimpleNamespace(**(dict(serial_command='open', port='TEST', baud=115200,
        databits=8, stop=1, parity='N', profile=None, auto_reply=None, log=None,
        mode='ascii', filter=None, duration=0, probe=None) | changes))


@pytest.fixture
def input_text(monkeypatch):
    def configure(*pieces):
        source = iter(pieces)
        monkeypatch.setattr(SerialTerminal, '_read', lambda self: next(source, None))
    terminal_init = SerialTerminal.__init__
    # pytest stdin is deliberately unreadable; retain real terminal logic with
    # a descriptor-bearing fake stream, and inject only ready keyboard text.
    def init(self, send, console, stdin=None):
        terminal_init(self, send, console, SimpleNamespace(fileno=lambda: 0, isatty=lambda: False))
    monkeypatch.setattr(SerialTerminal, '__init__', init)
    return configure


@pytest.mark.parametrize('existing', [False, True])
def test_open_shared_send_whitespace_hex_eof_and_cleanup(scan_cli, uart_app, input_text, existing, capsys):
    cli, _, http, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    if existing:
        assert http.post('/api/dash/serial/start', json={'ports': [{'port':'TEST'}, {'port':'OTHER'}]}).status_code == 200
    input_text('  文本  \r\n>hex 00 FF\n', 'tail')
    cli._cli_serial_dispatch(args())
    assert uart_app[4].sent == [('TEST', '  文本  \r\n'.encode()), ('TEST', b'\x00\xff'), ('TEST', b'tail\r\n')]
    assert not control.sessions and manager.running == existing
    assert '终端已结束' in capsys.readouterr().out


@pytest.mark.parametrize('existing', [False, True])
def test_rules_live_only_in_backend_and_borrow_matches(scan_cli, uart_app, input_text, tmp_path, existing):
    cli, _, http, control, _, _ = scan_cli
    rules = [{'match_contains':'Q', 'reply_ascii':'R'}]
    path = tmp_path/'rules.json'; path.write_text(json.dumps(rules), encoding='utf-8')
    if existing:
        assert http.post('/api/dash/serial/start', json={'ports':[{'port':'TEST'}], 'auto_reply_rules':rules}).status_code == 200
    input_text('>quit\n')
    cli._cli_serial_dispatch(args(auto_reply=str(path)))
    assert uart_app[2]['serial'].get_status()['automation'] == {'profile':None, 'rules':normalize_rules(rules)}
    assert not uart_app[4].sent and not control.sessions
    assert uart_app[2]['serial'].running == existing


def test_rule_conflict_preserves_gui_configuration_and_log(scan_cli, uart_app, input_text, tmp_path):
    cli, _, http, control, _, _ = scan_cli
    assert http.post('/api/dash/serial/start', json={'ports':[{'port':'TEST'}]}).status_code == 200
    rules = tmp_path/'rules.json'; rules.write_text('[{"match_contains":"Q","reply_ascii":"R"}]')
    output = tmp_path/'capture.csv'; output.write_text('KEEP')
    input_text('SHOULD NOT SEND\n')
    with pytest.raises(SystemExit, match='automation differs'):
        cli._cli_serial_dispatch(args(auto_reply=str(rules), log=str(output)))
    assert output.read_text() == 'KEEP' and not uart_app[4].sent and not control.sessions
    assert uart_app[2]['serial'].running


@pytest.mark.parametrize('invalid', ['not json', '[{"delay":-1}]', '{}'])
def test_bad_rules_before_attach_or_output(monkeypatch, tmp_path, invalid):
    from mklink import cli
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **kw: pytest.fail('invalid rules attached'))
    path=tmp_path/'rules.json'; path.write_text(invalid)
    output=tmp_path/'out.csv'; output.write_text('KEEP')
    with pytest.raises(SystemExit):cli._cli_serial_dispatch(args(auto_reply=str(path),log=str(output)))
    assert output.read_text()=='KEEP'


def test_unconfirmed_send_exits_without_replay_or_success(scan_cli, uart_app, input_text, monkeypatch, capsys):
    cli, _, _, control, _, _ = scan_cli
    def failed(self, port, data):
        self.sent.append((port,data)); return False
    monkeypatch.setattr(uart_app[4], 'send', failed)
    input_text('one\ntwo\n')
    with pytest.raises(SystemExit):cli._cli_serial_dispatch(args())
    assert uart_app[4].sent==[('TEST',b'one\r\n')]
    assert not control.sessions and not uart_app[2]['serial'].running
    assert '终端已结束' not in capsys.readouterr().out


def test_terminal_commands_bounds_and_backspace(input_text, tmp_path):
    sent=[]; console=ConsoleMonitor()
    terminal=SerialTerminal(sent.append,console)
    terminal.tty=True
    input_text('ab\x08c\r\n>mode hex\n>filter OK\n>quit\nnever\n')
    for _ in range(3):
        assert terminal.poll() is True
    assert terminal.poll() is False
    assert sent==[b'ac\r\n'] and console._mode=='hex' and console._filter.pattern=='OK'
    file=tmp_path/'data';file.write_bytes(b'a'*4096)
    terminal.command('>file '+str(file)); assert sent[-1]==b'a'*4096
    file.write_bytes(b'a'*4097)
    for line in ('>file '+str(file), '>hex GG', 'a'*4095, '>mode bogus', '>filter ['):
        before=len(sent)
        with pytest.raises(ValueError):terminal.command(line)
        assert len(sent)==before
    input_text('a'*8193)
    with pytest.raises(ValueError,match='8192'):terminal.poll()


def test_shared_cleanup_closes_client_on_second_interrupt(monkeypatch):
    from mklink.cli import _shared_uart_client
    events=[]
    class Client:
        def __init__(self,**kw):pass
        def connect(self,**kw):pass
        def call(self,name,*a):
            events.append(name)
            return {'running':False}
        def close(self):events.append('closed')
    monkeypatch.setattr('mklink.runtime.RuntimeClient',Client)
    def interrupted(client):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        with _shared_uart_client(args(),'serial',{},after_stop=interrupted):pass
    assert events[-2:]==['serial_stop','closed']


def test_api_validates_configuration_before_open_and_subscriber_cannot_replace(uart_app):
    http, control, managers, _, _ = uart_app
    owner,peer=uart_attach(http),uart_attach(http)
    for extra in ({'auto_reply_rules':[{'match_contains':'Q','reply_ascii':'R','delay':-1}]},
                  {'profile':{'name':'invalid'}}):
        response=call(http,owner,'serial_start',{'ports':[{'port':'TEST'}],**extra})
        assert response.status_code==400 and not managers['serial'].running
    config={'ports':[{'port':'TEST'}], 'profile':{'name':'P','version':'1','frame':{'header':'AA','tail':'FF'}},
            'auto_reply_rules':[{'match_hex':'AA','reply_hex':'BB'}]}
    assert call(http,owner,'serial_start',config).status_code==200
    assert call(http,peer,'serial_start',config).status_code==409
    assert call(http,peer,'serial_start').status_code==200
    assert call(http,owner,'serial_stop').status_code==409
    status=managers['serial'].get_status();status['automation']['rules'].clear()
    assert managers['serial'].get_status()['automation']['rules']
    assert not control.app.state.mklink_state['device']


@pytest.mark.parametrize('case', ['same_file', 'oversized', 'stdin'])
def test_open_preflight_preserves_files_without_attachment(monkeypatch, tmp_path, case):
    from mklink import cli
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **kw: pytest.fail('preflight attached'))
    rules=tmp_path/'rules.json'
    rules.write_text(json.dumps([{'match_contains':'Q','reply_ascii':'a'*4096}]*5))
    output=tmp_path/'out.csv';output.write_text('KEEP')
    options={'log':str(output)}
    if case=='same_file':
        rules.write_text('[]');options.update(auto_reply=str(rules),log=str(rules))
    elif case=='oversized':options['auto_reply']=str(rules)
    else:
        def fail(*a,**kw):raise ValueError('stdin has no descriptor')
        monkeypatch.setattr(SerialTerminal,'__init__',fail)
    before=rules.read_text()
    with pytest.raises(SystemExit):cli._cli_serial_dispatch(args(**options))
    assert output.read_text()=='KEEP' and rules.read_text()==before


def test_capture_never_polls_sender_after_backend_stops():
    from mklink.serial._capture import SerialCapture
    class Client:
        calls=0
        def call(self,*a):
            self.calls+=1
            return {'session':'one','next_seq':0,'latest_seq':0,'running':self.calls==1,
                    'ports':{'TEST':'open'},'entries':[],'dropped_batches':0}
    capture=SerialCapture(Client(),{'TEST':None},ConsoleMonitor())
    capture.run(0,on_poll=lambda:pytest.fail('sender polled after producer stopped'))


def test_each_poll_admits_one_pipe_command(input_text):
    sent=[];terminal=SerialTerminal(sent.append,ConsoleMonitor())
    input_text('one\ntwo\nthree\n')
    for count in (1,2,3):
        assert terminal.poll() is True
        assert len(sent)==count
    assert terminal.poll() is False


def test_cleanup_detaches_even_when_conflict_notice_cannot_print(monkeypatch):
    from mklink.cli import _shared_uart_client
    from mklink.runtime import RuntimeErrorResponse
    closed=[]
    class Client:
        def __init__(self,**kw):pass
        def connect(self,**kw):pass
        def call(self,name,*a):
            if name=='serial_stop':raise RuntimeErrorResponse('borrowed',status_code=409)
            return {'running':False}
        def close(self):closed.append(True)
    monkeypatch.setattr('mklink.runtime.RuntimeClient',Client)
    def broken(*a,**kw):raise BrokenPipeError('stdout closed')
    monkeypatch.setattr('builtins.print',broken)
    with pytest.raises(BrokenPipeError):
        with _shared_uart_client(args(),'serial',{}):pass
    assert closed==[True]
