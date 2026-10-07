import asyncio
import threading
import pytest
from test_shared_runtime import runtime, attach, call


def test_selection_and_validation(runtime):
    client, control, calls, managers, _ = runtime
    session = attach(client)
    assert call(client, session, 'gui_windows').json() == {'windows': []}
    assert call(client, session, 'gui_present').status_code == 409
    for tab in ['https://evil', [], None, 'serial']:
        assert call(client, session, 'gui_present', {'tab': tab}).status_code == 422
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/old') as old:
        old.receive_json()
        assert call(client, session, 'gui_windows').json() == {'windows': []}
    assert calls == []


def test_targeted_ack_during_capture(runtime):
    client, control, calls, managers, _ = runtime
    session = attach(client)
    managers['rtt'].running = True
    managers['superwatch'].running = True
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/a?presentation=1') as a, client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/b?presentation=1') as b:
        a.receive_json(); b.receive_json()
        assert len(call(client, session, 'gui_windows').json()['windows']) == 2
        assert call(client, session, 'gui_present').status_code == 409
        result = []
        worker = threading.Thread(target=lambda: result.append(call(client, session, 'gui_present', {'window_id': 'a'})))
        worker.start()
        msg = a.receive_json()
        assert msg['tab'] == 'superwatch'
        assert call(client, session, 'gui_present', {'window_id': 'a'}).status_code == 409
        a.send_json({'type': 'present_result', 'request_id': msg['request_id'], 'ok': True})
        worker.join(5)
        assert not worker.is_alive()
        assert result[0].json()['status'] == 'displayed'
        assert not control.views['b'].get('pending')
        assert calls == []
        assert managers['rtt'].running and managers['superwatch'].running
    assert call(client, session, 'gui_windows').json() == {'windows': []}


def test_socket_loss_is_not_success(runtime):
    client, control, calls, _, _ = runtime
    session = attach(client)
    result = []
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/a?presentation=1') as a:
        a.receive_json()
        worker = threading.Thread(target=lambda: result.append(call(client, session, 'gui_present')))
        worker.start(); a.receive_json()
    worker.join(5)
    assert result[0].json()['status'] == 'disconnected'
    assert calls == []



def test_unacknowledged_request_expires_without_replay(runtime):
    client, control, calls, _, _ = runtime
    session = attach(client)
    result = []
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/a?presentation=1') as a:
        a.receive_json()
        worker = threading.Thread(target=lambda: result.append(call(client, session, 'gui_present')))
        worker.start(); message = a.receive_json()
        a.send_json({'type': 'present_result', 'request_id': 'wrong', 'ok': True})
        worker.join(5)
        assert not worker.is_alive()
        assert result[0].json()['status'] == 'unconfirmed'
        assert 'pending' not in control.views['a']
        a.send_json({'type': 'present_result', 'request_id': message['request_id'], 'ok': True})
    assert calls == []
