from __future__ import annotations
import json, struct, zipfile
from pathlib import Path
from pt_asset_tool.official_payload_provenance_extraction import _is_target, _validate_smd_bytes, _prior_contamination

SH,SI,SO=556,40,2236
SV=24
O_PHYS,O_NV=16,84

def _smd_bytes(bone='Bip01 Head', name='BodyNew'):
    off=SH+SI; length=SO+SV+32
    b=bytearray(off+length); b[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<iiii',b,24,1,0,off,off)
    b[SH:SH+len(name)]=name.encode(); struct.pack_into('<ii',b,SH+32,length,off)
    struct.pack_into('<I',b,off+O_PHYS,1); struct.pack_into('<iiiiii',b,off+O_NV,1,0,0,0,0,0)
    b[off+172:off+172+len(name)]=name.encode(); phys=off+SO+SV; b[phys:phys+len(bone)]=bone.encode()
    return bytes(b)

def test_target_names():
    assert _is_target('TfbF01.smd') and _is_target('TfhF01.smd') and _is_target('CtfbF01.smd')
    assert not _is_target('test_TfbF01.smd')

def test_validate_strict_model(tmp_path):
    r=_validate_smd_bytes(_smd_bytes(),tmp_path,'TfbF01.smd')
    assert r['pass'] is True

def test_prior_workspace_contamination(tmp_path):
    proj=tmp_path/'design_work'; proj.mkdir(); ext=tmp_path/'official'; ext.mkdir()
    prior={'search_roots':[{'archive_candidates':[
        {'path':str(proj/'asset_v0_test.zip'),'target_name_hits':[{'name':'tfbf01.smd'}],'archive_member_hits':[],'strict_lha_record_count':1,'model062_magic_count':2},
        {'path':str(ext/'patch.upw'),'target_name_hits':[{'name':'tfbf01.smd'}],'archive_member_hits':[],'strict_lha_record_count':0,'model062_magic_count':0},
    ]}]}
    r=_prior_contamination(prior,proj)
    assert r['workspace_positive_count']==1 and r['nonworkspace_positive_count']==1
