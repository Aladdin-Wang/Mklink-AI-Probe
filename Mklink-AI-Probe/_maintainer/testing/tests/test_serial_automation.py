"""GUI/AI parsed snapshots reuse the sole backend parser and have no history."""
import json
import queue
import struct
import time
import pytest
from mklink.remote.dashboards import SerialStreamManager
from mklink.serial import _monitor
from mklink.serial._frame import FrameParser
from mklink.serial._profile import validate_profile
from test_runtime_uart import uart_app, client_factory, uart_attach, call


def profile(**field):
    return {'name':'P','version':'1','frame':{'header':'AA','tail':'FF'},
            'fields':[dict({'name':'value','offset':1,'size':1,'type':'uint8','unit':'V'},**field)]}


def wait_for(predicate):
    deadline=time.monotonic()+2
    while not predicate():
        assert time.monotonic()<deadline
        time.sleep(.005)


@pytest.fixture
def ports(monkeypatch):
    class Port:
        instances=[]
        def __init__(self,**kw):self.is_open=False;self.rx=queue.Queue();self.instances.append(self)
        def open(self):self.is_open=True;return True
        def close(self):self.is_open=False
        def read_available(self):
            try:return self.rx.get_nowait()
            except queue.Empty:return b''
    monkeypatch.setattr(_monitor,'SerialPort',Port)
    return Port


def test_snapshots_are_per_port_copied_bounded_and_restart_clears(ports):
    manager=SerialStreamManager();manager.start([{'port':'A'},{'port':'B'}],profile=profile())
    old=manager._monitor;initial=manager.get_history()
    a,b=ports.instances[-2:]
    try:
        a.rx.put(b'\xaa\x01\xff\xaa\x02\xff');b.rx.put(b'\xaa\x03\xff')
        wait_for(lambda:manager.get_status()['latest_frames'].get('A',{}).get('seq')==2)
        wait_for(lambda:'B' in manager.get_status()['latest_frames'])
        status=manager.get_status();assert manager._bridge.client_count==0
        assert status['latest_frames']['A']['fields']['value']['value']==2
        assert status['latest_frames']['B']['fields']['value']['value']==3
        status['latest_frames']['A']['fields']['value']['value']=99
        assert manager.get_status()['latest_frames']['A']['fields']['value']['value']==2
        a.rx.put(b'\xaa'+b'\0'*300+b'\xff')
        wait_for(lambda:manager.get_status()['latest_frames']['A']['seq']==3)
        frame=manager.get_status()['latest_frames']['A']
        assert frame['size']==302 and len(frame['hex_preview'])==512 and frame['truncated']
        assert len(manager.get_status()['latest_frames'])==2
        manager.stop()
        history=manager.get_history(initial['session'],initial['next_seq'])
        assert sum(e['size'] for e in history['entries'])==311
        assert manager.get_status()['latest_frames']['A']==frame
        session=manager.get_status()['session']
        manager.start([{'port':'A'}],profile=profile())
        assert manager.get_status()['session']!=session and manager.get_status()['latest_frames']=={}
        old._process_rx_data('A',b'\xaa\x77\xff',old._parsers['A'],bytearray())
        assert manager.get_status()['latest_frames']=={}
    finally:manager.stop()


def test_nonfinite_device_float_is_visible_json_safe_not_faked_zero(ports):
    manager=SerialStreamManager();manager.start([{'port':'A'}],profile=profile(type='float32',size=4))
    try:
        ports.instances[-1].rx.put(b'\xaa'+struct.pack('<f',float('nan'))+b'\xff')
        wait_for(lambda:bool(manager.get_status()['latest_frames']))
        status=manager.get_status();json.dumps(status,allow_nan=False)
        assert status['latest_frames']['A']['fields']['value']['value']=='nan'
    finally:manager.stop()


@pytest.mark.parametrize('reading', ['nan', 'inf', '-inf'])
def test_nonfinite_serial_sse_matches_snapshot(ports, reading):
    import asyncio
    async def run():
        manager = SerialStreamManager()
        manager.start([{'port': 'A'}], profile=profile(type='float32', size=4))
        subscription = manager._bridge.add_client()
        try:
            # A different tail avoids -inf's FF byte terminating the frame early.
            parser = FrameParser({'frame': {'header': 'AA', 'tail': '55'},
                'fields': profile(type='float32', size=4)['fields']})
            raw = b'\xaa' + struct.pack('<f', float(reading)) + b'\x55'
            manager._monitor._process_rx_data('A', raw, parser, bytearray())
            event = await asyncio.wait_for(subscription.get(), 2)
            if event['event'] == 'terminal':
                event = await asyncio.wait_for(subscription.get(), 2)
            json.dumps(event, allow_nan=False)
            assert event['fields']['value']['value'] == reading
            assert manager.get_status()['latest_frames']['A']['fields']['value']['value'] == reading
        finally:
            manager._bridge.remove_client(subscription)
            manager.stop()
    asyncio.run(run())


@pytest.mark.parametrize('field',[{'size':1,'type':'float32'},{'scale':float('nan')},
    {'scale':float('inf')},{'scale':True},{'type':'float32','size':4,'enum':{'0x00':'zero'}},
    {'enum':{'0x00':{'nested':'not scalar'}}}, {'size':[]}, {'type':{}}, {'endian':[]}, {'scale':10**400}])
def test_bad_profile_rejected_before_open(uart_app,monkeypatch,field):
    http,control,managers,_,monitor=uart_app
    monkeypatch.setattr(monitor,'start',lambda *a:pytest.fail('invalid profile opened port'))
    # HTTP JSON itself cannot encode NaN/inf through httpx's strict encoder.
    if isinstance(field.get('scale'),float):
        assert validate_profile(profile(**field))
        with pytest.raises(ValueError):managers['serial'].start([{'port':'TEST'}],profile=profile(**field))
    else:
        session=uart_attach(http)
        assert call(http,session,'serial_start',{'ports':[{'port':'TEST'}],'profile':profile(**field)}).status_code==400
    assert not managers['serial'].running


def test_configuration_size_limit_applies_to_direct_rest(uart_app):
    http,_,managers,_,_=uart_app
    response=http.post('/api/dash/serial/start',json={'ports':[{'port':'TEST'}],
        'profile':dict(profile(),name='P'*17000)})
    assert response.status_code==400 and not managers['serial'].running


def test_zero_scale_is_applied():
    parser=FrameParser(profile(scale=0))
    assert parser.feed(b'\xaa\x7f\xff')[0].fields['value']=={'raw':127,'value':0,'unit':'V'}


@pytest.mark.parametrize('length', [0, 1])
@pytest.mark.parametrize('crc', [False, True])
def test_corrupt_length_cannot_extract_empty_or_partial_header(length, crc):
    frame = {'header':'AA', 'length_field':{'offset':1,'size':1,'includes_header':True}}
    if crc: frame['crc'] = {'algorithm':'checksum8','offset':-1,'scope':'all'}
    parser = FrameParser({'frame':frame})
    parser._buffer.extend(bytes([0xAA, length, 0, 0]))
    # Single extraction keeps this regression safe even with the old infinite loop.
    with pytest.raises(ValueError, match='frame length'):
        parser._try_extract_frame(1)


@pytest.mark.parametrize('header', ['AA', 'AA BB', 'AA BB CC'])
def test_noise_discard_keeps_split_headers_and_all_valid_frames(header):
    parser = FrameParser({'frame':{'header':header,'tail':'FF'}}, max_buffer_bytes=64)
    prefix = bytes.fromhex(header)
    for _ in range(100):
        assert parser.feed(b'x'*32) == []
        assert len(parser._buffer) <= len(prefix)-1
    result = parser.feed(prefix[:-1])
    result += parser.feed(prefix[-1:]+b'\x01\xff'+prefix+b'\x02\xff')
    assert [f.raw for f in result] == [prefix+b'\x01\xff', prefix+b'\x02\xff']


@pytest.mark.parametrize('includes_header', [False, True])
def test_valid_lengths_split_and_multiple_frames(includes_header):
    cfg = {'header':'AA', 'length_field':{'offset':1,'size':1,'includes_header':includes_header}}
    parser = FrameParser({'frame':cfg})
    frame = bytes([0xAA, 3 if includes_header else 2, 0x42])
    assert parser.feed(frame[:2]) == []
    assert [f.raw for f in parser.feed(frame[2:]+frame)] == [frame, frame]


@pytest.mark.parametrize('change', [{'header':'  '}, {'tail':'\t\t'},
    {'length_field':{'offset':-1,'size':1,'includes_header':True}},
    {'length_field':{'offset':True,'size':1,'includes_header':True}},
    {'length_field':{'offset':1,'size':True,'includes_header':True}}])
def test_invalid_framing_rejected_before_open(uart_app, monkeypatch, change):
    http, _, managers, _, monitor = uart_app
    monkeypatch.setattr(monitor, 'start', lambda *a: pytest.fail('invalid profile opened port'))
    cfg = profile(); cfg['frame'].update(change)
    response = http.post('/api/dash/serial/start', json={'ports':[{'port':'TEST'}],'profile':cfg})
    assert response.status_code == 400 and not managers['serial'].running


def test_spaced_hex_profile_is_valid():
    cfg = profile(); cfg['frame'] = {'header':'AA BB', 'tail':'CC DD'}
    assert validate_profile(cfg) == []


def test_corrupt_wire_length_stops_reader_visibly_and_preserves_raw_history(ports):
    cfg = profile(); cfg['frame'] = {'header':'AA','length_field':{
        'offset':1,'size':1,'includes_header':True}}
    manager = SerialStreamManager(); manager.start([{'port':'A'}], profile=cfg)
    initial = manager.get_history()
    try:
        ports.instances[-1].rx.put(b'\xaa\x00')
        wait_for(lambda: manager.get_history()['ports']['A'].startswith('error:'))
        wait_for(lambda: not ports.instances[-1].is_open)
        assert 'frame length' in manager.get_history()['ports']['A']
        assert not ports.instances[-1].is_open
        assert manager.get_status()['latest_frames'] == {}
        manager.stop()
        history = manager.get_history(initial['session'], initial['next_seq'])
        assert ''.join(e['hex'] for e in history['entries']) == 'aa00'
        assert not manager.worker_alive
        manager.start([{'port':'A'}], profile=cfg)
        ports.instances[-1].rx.put(b'\xaa\x03\x42')
        wait_for(lambda: bool(manager.get_status()['latest_frames']))
        assert manager.get_status()['latest_frames']['A']['hex_preview'] == 'AA0342'
    finally:
        manager.stop()
