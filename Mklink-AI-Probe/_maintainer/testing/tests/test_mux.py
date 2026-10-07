import struct
import threading
from concurrent.futures import Future

import pytest

from mklink.mux import MuxTransport, MuxError, packet
from mklink.mux_watch import MuxWatchSession
from mklink.mux_rtt import MuxRTTSession
from mklink.rtt_cache import RttChannelCache
from test_shared_runtime import runtime, attach, call


def peer():
    calls = []
    def write(wire):
        _, _, op, size, epoch, req = struct.unpack_from('<4sBBHII', wire)
        payload = wire[16:16+size]
        calls.append((op, payload))
        answer = {1: struct.pack('<IHH', 15, 256, 1), 4: payload}.get(op, b'')
        raw = packet(op | 0x80, 17, req, b'\0'+answer)
        transport.feed(raw[:9])
        transport.feed(raw[9:])
        return len(wire)
    transport = MuxTransport(write)
    return transport, calls


@pytest.mark.parametrize('split', range(27))
def test_raw_watch_fragmentation_and_following_crc_reply(split):
    transport, _ = peer()
    transport.handshake()
    transport.capabilities |= 16
    payload = struct.pack('<BBI', 0, 0, 123) + b'abcd'
    wire = struct.pack('<4sBBHII', b'MLX1', 2, 0x41, len(payload), 17, 1) + payload
    transport.feed(wire[:split])
    transport.feed(wire[split:])
    assert transport.drain(0x41, 255) == [payload]
    assert transport.request(2, b'') == b''


@pytest.mark.parametrize('caps,op', [(15, 0x41), (31, 0x40), (31, 0x92)])
def test_raw_version_rejected_outside_advertised_watch(caps, op):
    transport, _ = peer()
    transport.handshake()
    transport.capabilities = caps
    transport.feed(struct.pack('<4sBBHII', b'MLX1', 2, op, 0, 17, 1))
    with pytest.raises(MuxError, match='Malformed'):
        transport.request(2)


@pytest.mark.parametrize('port,attach', [(1, True), (2, False)])
def test_bridge_mux_attach_respects_reported_debug_port(monkeypatch, tmp_path, port, attach):
    from unittest.mock import Mock
    from mklink.bridge import MKLinkSerialBridge
    transport = Mock()
    transport.request.return_value = bytes(15) + bytes([port])
    monkeypatch.setattr('mklink.mux.MuxTransport', Mock(return_value=transport))
    bridge = MKLinkSerialBridge.__new__(MKLinkSerialBridge)
    bridge._cmd_lock = threading.RLock()
    bridge._mux = None
    bridge._mux_supported = True
    bridge._mux_marker = tmp_path / 'mux'
    bridge._serial = Mock()
    assert bridge.enable_multiplex() is transport
    assert [call.args[0] for call in transport.request.call_args_list] == ([0x10, 0x13] if attach else [0x10])
    transport.fail.assert_not_called()


@pytest.mark.parametrize('status', [b'', bytes(15), bytes(16), bytes(15)+b'\x03'])
def test_bridge_mux_rejects_unknown_or_malformed_debug_port(monkeypatch, tmp_path, status):
    from unittest.mock import Mock
    from mklink.bridge import MKLinkSerialBridge
    transport = Mock()
    transport.request.return_value = status
    monkeypatch.setattr('mklink.mux.MuxTransport', Mock(return_value=transport))
    bridge = MKLinkSerialBridge.__new__(MKLinkSerialBridge)
    bridge._cmd_lock = threading.RLock()
    bridge._mux = None
    bridge._mux_supported = True
    bridge._mux_marker = tmp_path / 'mux'
    bridge._serial = Mock()
    with pytest.raises(RuntimeError, match='supported debug interface'):
        bridge.enable_multiplex()
    transport.request.assert_called_once_with(0x10)
    transport.fail.assert_called_once()
    bridge._serial.write.assert_called_once_with(b'~MKLINK-MUX1\n')


def test_framing_claim_event_isolation_and_heartbeat():
    transport, calls = peer()
    transport.handshake()
    assert transport.epoch == 17 and transport.ready
    transport.feed(packet(0x40, 17, 1, struct.pack('<BBI', 1, 0, 3)+b'\xff'))
    transport.request(0x12, b'data')
    assert calls[-1][1] == transport.nonce+b'data'
    assert transport.drain(0x40, 0) == []
    assert transport.drain(0x40, 1)[0][6:] == b'\xff'
    transport._last_command -= 2
    transport.tick()
    assert calls[-1][0] == 2 and transport._pending is None
    transport.close()
    assert not transport.ready


def test_unknown_write_is_never_replayed_or_followed_by_commands():
    writes = []
    transport = MuxTransport(writes.append)
    def expire():
        while transport._pending is None:
            threading.Event().wait(.001)
        transport.fail('response lost')
    thread = threading.Thread(target=expire)
    thread.start()
    with pytest.raises(MuxError, match='response lost'):
        transport.write_memory(0x20000000, b'abc')
    thread.join()
    with pytest.raises(MuxError):
        transport.request(0x11)
    transport.close()
    assert len(writes) == 1


def test_crc_and_expired_epoch_poison_stream():
    transport, _ = peer()
    transport.handshake()
    raw = bytearray(packet(0x40, 17, 1, b'\0'*6))
    raw[-1] ^= 1
    transport.feed(raw)
    with pytest.raises(MuxError, match='CRC'):
        transport.drain(0x40, 0)
    transport, _ = peer()
    transport.handshake()
    transport.feed(packet(0x40, 18, 1, b'\0'*6))
    with pytest.raises(MuxError):
        transport.request(2)


def test_channel_cache_clients_do_not_consume_each_other_and_report_loss():
    cache = RttChannelCache()
    cache.reset('one', [0, 1])
    cache.append(1, b'x'*(cache.LIMIT+7))
    first = cache.read(1)
    assert first == cache.read(1)
    assert first['lost_bytes'] == 7
    assert len(bytes.fromhex(first['data_hex'])) == cache.READ_LIMIT
    assert cache.read(0)['data_hex'] == ''
    cache.reset('two', [0, 1])
    result = cache.read(1, first['cursor'], 'one')
    assert result['reset'] and result['cursor'] == 0


@pytest.mark.parametrize('channel', range(8))
@pytest.mark.parametrize('excess', [-1, 0, 1, 65539])
def test_channel_history_capacity_pages_and_session_reset(channel, excess):
    cache = RttChannelCache()
    cache.reset('capture-one', list(range(8)))
    payload = bytes((index * 17 + channel) % 256 for index in range(65536 + excess))
    # Unequal delivery chunks exercise eviction across real delivery boundaries.
    for offset in range(0, len(payload), 997):
        cache.append(channel, payload[offset:offset + 997])
    cursor = 0
    received = bytearray()
    losses = []
    while cursor < len(payload):
        page = cache.read(channel, cursor, 'capture-one')
        assert page == cache.read(channel, cursor, 'capture-one')
        block = bytes.fromhex(page['data_hex'])
        assert 0 < len(block) <= 16384
        losses.append(page['lost_bytes'])
        received.extend(block)
        cursor = page['cursor']
    assert received == payload[-65536:]
    assert losses == [max(0, excess)] + [0] * (len(losses) - 1)
    assert cache.read(channel, cursor, 'capture-one')['data_hex'] == ''
    assert cache.read((channel + 1) % 8)['data_hex'] == ''
    for bad in (-1, True, '0', cursor + 1):
        with pytest.raises(ValueError):
            cache.read(channel, bad, 'capture-one')
    cache.reset('capture-two', list(range(8)))
    cache.append(channel, b'new capture\x00\xff')
    page = cache.read(channel, cursor, 'capture-one')
    assert page['reset'] and page['lost_bytes'] == 0
    assert bytes.fromhex(page['data_hex']) == b'new capture\x00\xff'


def test_watch_split_and_gaps_do_not_mix_rounds():
    transport, _ = peer()
    transport.handshake()
    watch = MuxWatchSession(transport, [(0x20000000, 130), (0x20000200, 4)], .001)
    watch.start()
    assert len(watch.parts) == 3 and transport.watch_running
    def event(index, data, timestamp=100):
        transport.feed(packet(0x41, 17, 1, struct.pack('<BBI', index, 0, timestamp)+data))
    event(0, b'a'*128)
    event(2, b'd'*4)
    assert watch.read_frames() == []
    event(0, b'b'*128)
    event(1, b'cc')
    event(2, b'eeee')
    frames = watch.read_frames()
    assert frames[0]['regions'] == [(0, b'b'*128+b'cc'), (1, b'eeee')]
    assert watch.gaps > 0 and frames[0]['timestamp_us'] == 100
    watch.stop()
    assert not transport.watch_running


def test_watch_bound_and_memory_write_no_retry_after_verification_mismatch():
    transport, _ = peer()
    with pytest.raises(ValueError, match='15 regions'):
        MuxWatchSession(transport, [(0x20000000, 2048)], .1)
    watch = MuxWatchSession(transport, [(0x20000000, 4)], .1)
    calls = []
    transport.write_memory = lambda address, data: calls.append((address, data))
    transport.read_memory = lambda address, size: b'bad!'
    future = Future()
    with pytest.raises(RuntimeError, match='mismatch'):
        watch.write(0x20000000, b'good', future)
    assert future.exception() and len(calls) == 1


@pytest.mark.parametrize('channel', range(8))
def test_dap_takeover_invalidates_each_rtt_channel_without_poisoning_transport(channel):
    transport, _ = peer()
    transport.handshake()
    session = MuxRTTSession(transport, {}, channel=channel)
    transport.feed(packet(0x40, 17, 1, struct.pack('<BBI', channel, 7, 100)))
    with pytest.raises(RuntimeError, match='DAP changed the target'):
        session.read_channels(0)
    assert transport.ready
    assert transport.request(4, b'control still alive') == b'control still alive'


def test_dap_takeover_discards_partial_watch_sample_and_surfaces_reason():
    transport, _ = peer()
    transport.handshake()
    watch = MuxWatchSession(transport, [(0x20000000, 256)], .1)
    transport.feed(packet(0x41, 17, 1, struct.pack('<BBI', 0, 0, 100) + b'x' * 128))
    assert watch.read_frames() == [] and watch._pending
    transport.feed(packet(0x41, 17, 2, struct.pack('<BBI', 0, 7, 101)))
    with pytest.raises(RuntimeError, match='DAP changed the target'):
        watch.read_frames()
    assert watch._pending == [] and watch.samples == 0 and transport.ready


def test_shared_admission_allows_mux_memory_but_keeps_unsafe_boundaries(runtime):
    from types import SimpleNamespace
    from mklink.remote.api import acquire_dashboard_resources, target_debug_lease
    from mklink.remote.resource_manager import ResourceError
    client, _, calls, managers, app = runtime
    state = app.state.mklink_state
    state['device']._bridge = SimpleNamespace(_mux_supported=True, supports_multiplex=lambda: True)
    state['shared_runtime'] = True
    session = attach(client)
    acquire_dashboard_resources(state, 'rtt')
    acquire_dashboard_resources(state, 'superwatch')
    managers['rtt'].running = managers['superwatch'].running = True
    assert call(client, session, 'read_memory', {'address': '0x20000000', 'size': 4}).status_code == 200
    with target_debug_lease(state, 'read-memory'):
        pass
    with pytest.raises(ResourceError):
        with target_debug_lease(state, 'halt'):
            pytest.fail('Unsafe command admitted')
    assert client.post('/api/device/halt').status_code == 409
    assert client.post('/api/dash/systemview/start', json={}).status_code == 409
    assert calls == ['read']

@pytest.mark.parametrize('ordered',[False,True])
def test_mux_watch_complete_frames_reuse_dump_coverage_validation(ordered):
    from mklink.dump_memory import DumpSampleAssembler,DumpMemoryReadError
    transport,_=peer();transport.handshake()
    watch=MuxWatchSession(transport,[(0x20000001,130),(0x20000203,4)],.01)
    watch.start()
    for index,payload in enumerate([b'a'*128,b'bc',b'defg']):
        transport.feed(packet(0x41,17,1,struct.pack('<BBI',index,0,123)+payload))
    frame=watch.read_frames()[0]
    assert DumpSampleAssembler([130,4],ordered=ordered).feed(frame)==(b'a'*128+b'bc',b'defg')
    for regions in [[(0,b'a'*130)],[(0,b'a'*129),(1,b'defg')]]:
        assembler=DumpSampleAssembler([130,4],ordered=ordered)
        invalid={**frame,'regions':regions}
        if ordered:
            with pytest.raises(DumpMemoryReadError):assembler.feed(invalid)
        else:assert assembler.feed(invalid) is None
    watch.stop()

@pytest.mark.parametrize('size,bulk',[(1920,False),(1921,False),(1921,True),(4096,True)])
def test_finite_bulk_selects_protocol_before_hardware(size,bulk):
    from unittest.mock import Mock
    from mklink.dump_memory import DumpMemoryStreamSession
    from test_dump_memory_session import FakeBridge
    transport,_=peer();transport.handshake()
    bridge=FakeBridge([])
    bridge.supports_multiplex=lambda:True
    bridge.enable_multiplex=Mock(return_value=transport)
    bridge._leave_multiplex=Mock()
    session=DumpMemoryStreamSession(bridge,[(0x08005000,size)],.01,allow_legacy_bulk=bulk)
    if size>1920 and not bulk:
        with pytest.raises(ValueError,match='15 regions'):session.start()
        bridge.enable_multiplex.assert_not_called();bridge._leave_multiplex.assert_not_called()
        assert not bridge.calls
        return
    session.start()
    if size<=1920:
        bridge.enable_multiplex.assert_called_once();bridge._leave_multiplex.assert_not_called()
        assert session._mux_watch is not None
    else:
        bridge.enable_multiplex.assert_not_called();bridge._leave_multiplex.assert_called_once()
        assert session._mux_watch is None and session.started
        assert any(call[0]=='write' and b'cmd.dump_memory' in call[1] for call in bridge.calls)
    session.stop()


def test_finite_bulk_never_falls_back_after_mux_start_failure():
    from unittest.mock import Mock
    from mklink.dump_memory import DumpMemoryStreamSession
    from test_dump_memory_session import FakeBridge
    transport,_=peer();transport.handshake()
    transport.request=Mock(side_effect=RuntimeError('response lost'))
    bridge=FakeBridge([]);bridge.supports_multiplex=lambda:True
    bridge.enable_multiplex=Mock(return_value=transport);bridge._leave_multiplex=Mock()
    session=DumpMemoryStreamSession(bridge,[(0x08005000,4)],.01,allow_legacy_bulk=True)
    with pytest.raises(RuntimeError,match='response lost'):session.start()
    bridge._leave_multiplex.assert_not_called()
    assert not bridge.calls


@pytest.mark.parametrize('capabilities,op,unit', [(15, 0x32, 1)])
def test_watch_negotiates_precision_and_clock_wrap(capabilities, op, unit):
    transport, calls = peer()
    transport.handshake()
    transport.capabilities = capabilities
    watch = MuxWatchSession(transport, [(0x20000000, 4)], .000001)
    watch.start()
    assert calls[-1][0] == op
    expected = struct.pack('<IB' if unit == 1 else '<HB', 1 if unit == 1 else 2, 1)
    assert calls[-1][1][8:].startswith(expected)
    for seq, timestamp in enumerate([0xfffffffe, 3], 1):
        transport.feed(packet(0x41, 17, seq, struct.pack('<BBI', 0, 0, timestamp)+b'abcd'))
    frames = watch.read_frames()
    assert frames[1]['timestamp_us']-frames[0]['timestamp_us'] == 5*unit


@pytest.mark.parametrize('period', [-.1, -1, float('nan'), float('inf'), 60.1])
def test_watch_rejects_invalid_period_before_target_command(period):
    transport, calls = peer()
    transport.capabilities = 15
    with pytest.raises(ValueError):
        MuxWatchSession(transport, [(0x20000000, 4)], period)
    assert not calls


def test_watch_compact_batch_preserves_values_and_microsecond_wrap():
    transport, _ = peer()
    transport.handshake()
    transport.capabilities = 15
    watch = MuxWatchSession(transport, [(0x20000000, 4)], .000019)
    watch.start()
    payload = bytes([0, 9, 2, 4])+struct.pack('<IIII', 0xfffffffe, 123, 3, 456)
    transport.feed(packet(0x41, 17, 1, payload))
    frames = watch.read_frames()
    assert [struct.unpack('<I', f['regions'][0][1])[0] for f in frames] == [123, 456]
    assert frames[1]['timestamp_us']-frames[0]['timestamp_us'] == 5
    assert watch.samples == 2


@pytest.mark.parametrize('payload', [bytes([0,9,0,4,0,0]), bytes([0,9,128,4,0,0]),
                                      bytes([0,9,1,1])+bytes(8), bytes([0,9,2,4])+bytes(8)])
def test_watch_rejects_malformed_compact_batch(payload):
    transport, _ = peer()
    transport.handshake()
    transport.capabilities = 15
    watch = MuxWatchSession(transport, [(0x20000000, 4)], .000001)
    transport.feed(packet(0x41, 17, 1, payload))
    with pytest.raises(RuntimeError, match='Invalid multiplex watch batch'):
        watch.read_frames()


def test_watch_negotiates_after_deferred_transport_assignment():
    watch = MuxWatchSession(None, [(0x20000000, 4)], .000020)
    transport, calls = peer()
    transport.handshake()
    transport.capabilities = 15
    watch.transport = transport
    watch.start()
    assert calls[-1][0] == 0x32
    assert calls[-1][1][8:13] == struct.pack('<IB', 20, 1)


def test_watch_accepts_bounded_large_event_only_after_capability_negotiation():
    payload = bytes([0,9,127,4])+b''.join(struct.pack('<II', i*4,i) for i in range(127))
    for capabilities in (3,15):
        transport, _ = peer()
        transport.handshake()
        transport.capabilities = capabilities
        watch = MuxWatchSession(transport, [(0x20000000,4)], .000001)
        import binascii
        raw = struct.pack('<4sBBHII', b'MLX1', 1, 0x41, len(payload), 17, 1)+payload
        transport.feed(raw+struct.pack('<I', binascii.crc32(raw)&0xffffffff))
        if capabilities==3:
            with pytest.raises(MuxError): watch.read_frames()
        else:
            frames=watch.read_frames()
            assert len(frames)==127 and frames[-1]['timestamp_us']==504


@pytest.mark.parametrize('capabilities', [0, 3, 7])
def test_watch_requires_matching_firmware_without_legacy_fallback(capabilities):
    transport, calls = peer()
    transport.handshake()
    transport.capabilities = capabilities
    count = len(calls)
    with pytest.raises(RuntimeError, match='update the probe firmware and host together'):
        MuxWatchSession(transport, [(0x20000000, 4)], 1e-6).start()
    assert len(calls) == count


@pytest.mark.parametrize('sizes', [[4]*4, [16], [4]*15, [64], [4, 8, 12]])
def test_grouped_batch_preserves_region_order_and_capacity(sizes):
    transport, _ = peer()
    transport.handshake()
    watch = MuxWatchSession(transport, [(0x20000000+128*i,n) for i,n in enumerate(sizes)], 1e-6)
    watch.start()
    size = sum(sizes)
    count = min(127, 1020//(4+size))
    payload = bytes([0,9,count,size])+b''.join(struct.pack('<I',t)+bytes([t])*size for t in range(count))
    import binascii
    raw = struct.pack('<4sBBHII', b'MLX1', 1, 0x41, len(payload), 17, 1)+payload
    transport.feed(raw+struct.pack('<I', binascii.crc32(raw)&0xffffffff))
    frames = watch.read_frames()
    assert len(frames) == count
    for t, frame in enumerate(frames):
        assert frame['regions'] == [(i,bytes([t])*n) for i,n in enumerate(sizes)]
    assert watch.gaps == 0


def test_bounded_drain_keeps_order_and_queue_accounting():
    transport, _ = peer()
    transport.handshake()
    payloads = [bytes([0, 0])+struct.pack('<I', i)+bytes(100) for i in range(10)]
    for i, payload in enumerate(payloads):
        transport.feed(packet(0x41, 17, i+1, payload))
    assert transport.drain(0x41, 255, max_bytes=220) == payloads[:2]
    assert transport._sizes[(0x41, 255)] == 8*106
    # A budget smaller than one event still makes progress without splitting it.
    assert transport.drain(0x41, 255, max_bytes=1) == payloads[2:3]
    assert transport.drain(0x41, 255) == payloads[3:]
    assert (0x41, 255) not in transport._sizes
    assert transport.stats()['watch_dropped_bytes'] == 0


def test_watch_burst_budget_is_bounded_and_does_not_enlarge_rtt_queues():
    transport, _ = peer()
    transport.handshake()
    for i in range(3000):
        transport.feed(packet(0x41, 17, i+1, bytes([0, 0])+struct.pack('<I', i)+bytes(100)))
    assert 0 < transport._sizes[(0x41, 255)] <= transport.WATCH_QUEUE_BYTES
    assert transport.stats()['watch_dropped_bytes'] > 0
    for i in range(1000):
        transport.feed(packet(0x40, 17, i+3001, bytes(106)))
    assert 0 < transport._sizes[(0x40, 0)] <= transport.MAX_QUEUE_BYTES
    assert transport.stats()['rtt_dropped_bytes'][0] > 0
    assert transport.request(2, b'alive') == b''
