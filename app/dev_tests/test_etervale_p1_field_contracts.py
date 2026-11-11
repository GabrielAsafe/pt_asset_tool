import struct
from pt_asset_tool.etervale_field_contracts import inspect_bytes

def test_spp_csharp_compatible_structural_shape():
    b=bytearray(2400);struct.pack_into('<iii',b,0,1,12,13)
    result=inspect_bytes('.spp',bytes(b))
    assert result['status']=='PASS' and result['active_count']==1

def test_spc_shape_and_csharp_live_flag():
    b=bytearray(50400);struct.pack_into('<i',b,4,1)
    result=inspect_bytes('.spc',bytes(b))
    assert result['status']=='PASS' and result['active_csharp_rows']==1

def test_wrong_size_not_certified():
    assert inspect_bytes('.spp',b'x')['status']!='PASS'
    assert inspect_bytes('.spc',b'x')['status']!='PASS'

def test_spm_offline_only():
    result=inspect_bytes('.spm',b'*ACTOR "goblin" 10\n')
    assert result['status']=='PASS' and result['spawn_actor_references'][0]['name']=='goblin'
