import pytest
from fastapi.testclient import TestClient
from mklink.remote.api import create_app
from mklink.watch_workspace import load_workspace, save_workspace
from mklink.watch_preferences import PreferencesConflict


def test_workspace_roundtrip_and_isolation(tmp_path):
    root=str(tmp_path/'one'); initial=load_workspace(root)
    workspace=initial['workspace']
    workspace['groups']=[{'id':'motor','name':'电机'}]
    workspace['panes'] += [{'id':'current','name':'电流'},{'id':'voltage','name':'电压'}]
    workspace['signals']={'motor.rpm':{'alias':'转速','emphasis':True,'group':'motor','pane':'current','address':1234}}
    saved=save_workspace(root,workspace,initial['revision'])
    assert load_workspace(root)==saved
    assert saved['workspace']['signals']['motor.rpm']=={'alias':'转速','emphasis':True,'group':'motor','pane':'current'}
    assert load_workspace(str(tmp_path/'two'))['workspace']['signals']=={}
    with pytest.raises(PreferencesConflict): save_workspace(root,workspace,initial['revision'])


def test_workspace_api_conflict_and_invalid_import(tmp_path):
    client=TestClient(create_app(auth_token=None,project_root=str(tmp_path)))
    route='/api/dash/superwatch/workspace'
    first=client.get(route).json()
    data={**first,'workspace':{**first['workspace'],'groups':[{'id':'g','name':'控制'}]}}
    assert client.put(route,json=data).status_code==200
    assert client.put(route,json=data).status_code==409
    state=client.get(route).json()
    bad={**state,'workspace':{'version':99}}
    assert client.put(route,json=bad).status_code==422
    assert client.get(route).json()==state


def test_missing_groups_and_panes_fall_back_without_addresses(tmp_path):
    state=load_workspace(str(tmp_path))
    w={'version':1,'signals':{'a':{'alias':'测试','pane':'missing','group':'missing'}}}
    result=save_workspace(str(tmp_path),w,state['revision'])['workspace']
    assert result['signals']['a']['pane']=='main'
    assert result['signals']['a']['group']==''


def test_space_search_is_and_commas_are_or(tmp_path):
    from mklink.dwarf_parser import DwarfInfo,DwarfVariable
    from mklink.symbol_catalog import SymbolCatalog
    axf=tmp_path/'app.axf';axf.write_bytes(b'axf')
    names=['CCU_ABC','ABC_CCU','CCU_DEF','PWM']
    info=DwarfInfo(base_types={1:('float',4)},variables={n:DwarfVariable(n,i,1,0x20000000+i*4,4,'float') for i,n in enumerate(names)})
    catalog=SymbolCatalog.from_dwarf(info,axf_path=str(axf),generation=1,ram_ranges=[(0x20000000,0x20001000)])
    assert {x.path for x in catalog.search('ccu   ABC')}=={'CCU_ABC','ABC_CCU'}
    assert {x.path for x in catalog.search('CCU ABC, PWM')}=={'CCU_ABC','ABC_CCU','PWM'}

def test_lazy_nested_member_after_large_array_is_searchable(tmp_path):
    from mklink.dwarf_parser import DwarfInfo,DwarfVariable,DwarfStruct,DwarfMember
    from mklink.symbol_catalog import SymbolCatalog
    axf=tmp_path/'app.axf';axf.write_bytes(b'axf')
    info=DwarfInfo(base_types={1:('uint32_t',4)})
    info.arrays={10:(1,4096)}
    info.structs={
        'Params':DwarfStruct('Params',offset=20,size=4,members=[DwarfMember('bat_num',offset=0,type_offset=1,type_name='uint32_t',size=4)]),
        'HouTai':DwarfStruct('HouTai',offset=30,size=4100,members=[
            DwarfMember('large_buffer',offset=0,type_offset=10,type_name='uint32_t[]',size=4096),
            DwarfMember('Prama_Set',offset=4096,type_offset=20,type_name='Params',size=4)])}
    info.variables={'HouTai_data':DwarfVariable('HouTai_data',100,type_offset=30,address=0x20000000,size=4100,type_name='HouTai')}
    cat=SymbolCatalog.from_dwarf(info,axf_path=str(axf),ram_ranges=[(0x20000000,0x20010000)],max_leaves_per_root=2)
    assert not any(x.path.endswith('bat_num') for x in cat.items)
    for query in ['bat_num','HouTai bat_num','prama BAT_num','bat_num, missing']:
        result=cat.search(query)
        assert [x.path for x in result]==['HouTai_data.Prama_Set.bat_num']
        assert result[0].address==0x20001000
