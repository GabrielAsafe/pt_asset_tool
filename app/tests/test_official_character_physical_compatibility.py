from __future__ import annotations
import os, struct
from pathlib import Path

from pt_asset_tool.official_character_physical_compatibility import _logical, _compat_score, _skeleton_matches, run

SH,SI,SO=556,40,2236
SV=24
O_PHYS,O_NV,O_NF,O_NT,O_NR,O_NP,O_NS=16,84,88,92,684,688,692


def _smd(path:Path, bone='Bip01 Head', name='Body'):
    off=SH+SI
    nv=1
    length=SO+SV+32
    b=bytearray(off+length)
    b[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<i',b,24,1)
    b[SH:SH+len(name)]=name.encode()
    struct.pack_into('<ii',b,SH+32,length,off)
    struct.pack_into('<I',b,off+O_PHYS,1)
    struct.pack_into('<iiiiii',b,off+O_NV,nv,0,0,0,0,0)
    # head/object name is only diagnostic for this parser
    b[off+172:off+172+len(name)]=name.encode()
    phys=off+SO+SV
    b[phys:phys+len(bone)]=bone.encode()
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b)


def _smb(path:Path, bones=('Bip01 Head','Bip01 Spine1')):
    off0=SH+len(bones)*SI
    total=off0+len(bones)*SO
    b=bytearray(total)
    b[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<i',b,24,len(bones))
    for i,name in enumerate(bones):
        io=SH+i*SI; off=off0+i*SO
        b[io:io+len(name)]=name.encode(); struct.pack_into('<ii',b,io+32,SO,off)
        b[off+172:off+172+len(name)]=name.encode()
        struct.pack_into('<16i',b,off+240,*([0]*16))
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b)


def test_logical_strips_image_prefix():
    assert _logical('image/char/TM/foo.smd') == 'char/TM/foo.smd'
    assert _logical('char/TM/foo.smd') == 'char/TM/foo.smd'


def test_compat_exact_bones_scores_high():
    d={'parse_status':'PASS','bone_key':['bip01 head'],'physique_mode':'RIGID','object_count':1,'total_vertices':10,'total_faces':8,'logical_path':'char/a.smd'}
    s={**d,'logical_path':'char/b.smd'}
    score,ev=_compat_score(d,s)
    assert score >= 80
    assert 'EXACT_BIND_BONE_SET' in ev


def test_skeleton_subset_match():
    m={'parse_status':'PASS','bind_bones':['Bip01 Head']}
    sk=[{'parse_status':'PASS','bones':['Bip01 Head','Bip01 Spine1'],'logical_path':'char/m.smb','relative_path':'image/char/m.smb','sha256':'x','bone_count':2}]
    r=_skeleton_matches(m,sk)
    assert len(r)==1 and r[0]['extra_bone_count']==1


def test_end_to_end_read_only_mapping(tmp_path, monkeypatch):
    project=tmp_path/'project'; client=tmp_path/'summit'; donor=tmp_path/'donor'
    project.mkdir(); client.mkdir(); donor.mkdir()
    # required certified writers copied from package payload by pytest cwd-independent path
    payload=Path(__file__).resolve().parents[1]/'payload'
    for rel in ('rare_rigid_edit.py','rare_rigid_multivertex.py','rare_rigid_multibone_bridge.py','rare_rigid_normal_bridge.py'):
        dst=project/'pt_asset_tool'/rel; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes((payload/'pt_asset_tool'/rel).read_bytes())
    # production policies may be absent in synthetic root; snapshot permits None.
    _smd(client/'char/slot/body.smd','Bip01 Head','Body')
    _smb(client/'char/slot/m.smb')
    _smd(donor/'image/char/newhero/body_new.smd','Bip01 Head','BodyNew')
    _smb(donor/'image/char/newhero/m.smb')
    monkeypatch.setenv('PT_CLIENT_ROOT',str(client))
    before=(donor/'image/char/newhero/body_new.smd').read_bytes()
    out=project/'pt_build/out.json'
    r=run(project,out,[f'official={donor}'])
    assert r['status']=='PASS'
    assert r['mapping_summary']['physical_transplant_mapping_candidate_unique_assets']==1
    cand=r['priority_candidates'][0]
    assert cand['donor_logical_path']=='char/newhero/body_new.smd'
    assert cand['summit_model_compatibility_candidates'][0]['summit_logical_path']=='char/slot/body.smd'
    assert (donor/'image/char/newhero/body_new.smd').read_bytes()==before
    assert r['client_and_donors_read_only'] is True


def test_end_to_end_discovers_player_by_skeleton_without_char_path(tmp_path, monkeypatch):
    project=tmp_path/'project'; client=tmp_path/'summit'; donor=tmp_path/'donor'
    project.mkdir(); client.mkdir(); donor.mkdir()
    payload=Path(__file__).resolve().parents[1]/'payload'
    for rel in ('rare_rigid_edit.py','rare_rigid_multivertex.py','rare_rigid_multibone_bridge.py','rare_rigid_normal_bridge.py'):
        dst=project/'pt_asset_tool'/rel; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes((payload/'pt_asset_tool'/rel).read_bytes())
    _smd(client/'char/slot/body.smd','Bip01 Head','Body')
    _smb(client/'char/slot/m.smb')
    # Real donors need not place player models under image/char.  Physical SMB
    # containment must discover this model even when semantic_group is UNKNOWN.
    _smd(donor/'image/legacy_models/TmbC01.smd','Bip01 Head','BodyNew')
    _smb(donor/'image/legacy_anim/m4.smb')
    monkeypatch.setenv('PT_CLIENT_ROOT',str(client))
    out=project/'pt_build/out.json'
    r=run(project,out,[f'official={donor}'])
    d=r['donors'][0]
    assert d['all_smd_count']==1
    assert d['player_discovery']['semantic_player_count']==0
    assert d['player_discovery']['skeleton_bound_player_count']==1
    assert d['player_model_count']==1
    assert r['mapping_summary']['physical_transplant_mapping_candidate_unique_assets']==1
    assert r['priority_candidates'][0]['donor_logical_path']=='legacy_models/TmbC01.smd'
