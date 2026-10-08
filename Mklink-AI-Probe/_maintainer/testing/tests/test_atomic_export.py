import errno

import pytest

from mklink import file_content


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failure', ['write', 'sync', 'replace', None])
def test_export_preserves_destination_until_complete(tmp_path, monkeypatch, existing, failure):
    target = tmp_path / 'capture.bin'
    if existing:
        target.write_bytes(b'previous')

    def chunks():
        yield b'first'
        if failure == 'write':
            raise OSError(errno.ENOSPC, 'disk full after partial output')
        yield b'second'

    def fail(*args):
        raise OSError(errno.EACCES, 'injected sync or replacement failure')

    if failure == 'sync':
        monkeypatch.setattr(file_content, 'sync_file', fail)
    if failure == 'replace':
        monkeypatch.setattr(file_content.os, 'replace', fail)
    if failure:
        with pytest.raises(OSError):
            file_content.write_atomic_chunks(target, chunks())
        assert target.read_bytes() == b'previous' if existing else not target.exists()
    else:
        file_content.write_atomic_chunks(target, chunks())
        assert target.read_bytes() == b'firstsecond'
    assert not list(tmp_path.glob('.mklink-export-*'))


@pytest.mark.parametrize('short', [False, True])
def test_partial_stream_write_never_replaces_export(tmp_path, monkeypatch, short):
    target = tmp_path / 'capture.bin'
    target.write_bytes(b'previous')
    create = file_content.tempfile.NamedTemporaryFile

    class BrokenStream:
        def __init__(self, **kwargs):
            self.stream = create(**kwargs)
            self.name = self.stream.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, chunk):
            self.stream.write(chunk[:2])
            if short:
                return 2
            raise OSError(errno.ENOSPC, 'disk full')

    monkeypatch.setattr(file_content.tempfile, 'NamedTemporaryFile', BrokenStream)
    with pytest.raises(OSError):
        file_content.write_atomic_chunks(target, [b'complete sample'])
    assert target.read_bytes() == b'previous'
    assert not list(tmp_path.glob('.mklink-export-*'))
