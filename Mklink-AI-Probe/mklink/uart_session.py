"""Shared UART attachment lifecycle for CLI and remote adapters."""
from contextlib import contextmanager
import logging
import sys


def _notify(level, message):
    getattr(logging.getLogger(__name__), level)(message)


@contextmanager
def uart_session(stream, settings, *, probe=None, project_root=".", kind="cli",
                 name=None, after_stop=None, notify=None):
    """Borrow an existing stream, or stop only the connection this caller started."""
    notify = notify or _notify
    from mklink.runtime import RuntimeClient, RuntimeErrorResponse
    client = RuntimeClient(project_root=project_root, kind=kind, name=name or f'{stream.title()} client')
    created = False
    try:
        client.connect(scope='uart', probe=probe)
        if client.call(f'{stream}_status')['running']:
            client.call(f'{stream}_start', {})
        else:
            client.call(f'{stream}_start', settings)
            created = True
        yield client
    finally:
        operation_error = sys.exc_info()[1]
        cleanup_errors = []
        try:
            if created:
                try:
                    client.call(f'{stream}_stop')
                except BaseException as exc:
                    if isinstance(exc, RuntimeErrorResponse) and exc.status_code == 409:
                        notify('info', '未取得停止权限，保留连接；可在后台管理中显式停止。')
                    else:
                        cleanup_errors.append(exc)
            if after_stop is not None and operation_error is None and not cleanup_errors:
                try:
                    after_stop(client)
                except BaseException as exc:
                    cleanup_errors.append(exc)
        finally:
            try:
                client.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            if operation_error is None:
                raise cleanup_errors[0]
            for error in cleanup_errors:
                notify('warning', f'{stream.title()} 会话清理失败，请检查共享后台: {error}')



@contextmanager
def modbus_session(connection, *, scan=False, **options):
    """Validate settings after subscribing, while reconfiguration is blocked."""
    from mklink.runtime import RuntimeErrorResponse
    settings = {'timeout': .15 if scan else 1.0, 'retries': 0,
                **connection, 'registers': []}
    with uart_session('modbus', settings, **options) as client:
        actual = client.call('modbus_status')['connection']
        if any(actual.get(key) != value for key, value in connection.items()):
            raise RuntimeErrorResponse('Existing Modbus connection uses different port/settings; stop it explicitly before changing settings')
        yield client
