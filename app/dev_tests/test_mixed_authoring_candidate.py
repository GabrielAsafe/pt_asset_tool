from __future__ import annotations

import pathlib
import struct
from types import SimpleNamespace

from pt_asset_tool.mixed_authoring_candidate import analyze_mixed_source, validate_mixed_candidate_output
from pt_asset_tool.static_roundtrip import _parse

SH,SI,SO,SV,SF,ST=556,40,2236,24,36,32


def _block(name: str, *, physique: bool) -> bytes:
    nv,nf,nt=3,1,1
    length=SO+nv*SV+nf*SF+nt*ST+(nv*32 if physique else 0)
    b=bytearray(length); texbase=0x100000
    struct.pack_into('<I',b,12,texbase)
    struct.pack_into('<I',b,16,1 if physique else 0)
    struct.pack_into('<iii',b,84,nv,nf,nt)
    b[172:172+len(name)]=name.encode('ascii')
    vo=SO
    for i,xyz in enumerate(((0,0,0),(256,0,0),(0,256,0))):
        struct.pack_into('<6i',b,vo+i*SV,*(xyz+(0,0,256)))
    fo=vo+nv*SV
    struct.pack_into('<4H',b,fo,0,1,2,0); struct.pack_into('<I',b,fo+32,texbase)
    to=fo+SF
    struct.pack_into('<3f',b,to,0.0,1.0,0.0); struct.pack_into('<3f',b,to+12,0.0,0.0,1.0)
    struct.pack_into('<I',b,to+28,0)
    return bytes(b)


def _mixed(path: pathlib.Path) -> pathlib.Path:
    blocks=[('rigid',_block('rigid',physique=True)),('static',_block('static',physique=False)),('untouched',_block('untouched',physique=False))]
    first=SH+len(blocks)*SI
    total=first+sum(len(x[1]) for x in blocks)
    out=bytearray(total); out[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<i',out,24,len(blocks)); struct.pack_into('<i',out,28,0)
    struct.pack_into('<i',out,32,first); struct.pack_into('<i',out,36,first)
    cur=first
    for i,(name,block) in enumerate(blocks):
        info=SH+i*SI; out[info:info+len(name)]=name.encode('ascii')
        struct.pack_into('<i',out,info+32,len(block)); struct.pack_into('<i',out,info+36,cur)
        out[cur:cur+len(block)]=block; cur+=len(block)
    path.write_bytes(out); return path


def _edit_vertex(path: pathlib.Path, object_name: str, component: int, delta: int):
    data=bytearray(path.read_bytes()); parsed=_parse(bytes(data)); obj=parsed['objects'][object_name]
    off=int(obj['vertex_offset'])+component*4
    old=struct.unpack_from('<i',data,off)[0]; struct.pack_into('<i',data,off,old+delta)
    path.write_bytes(data)


def test_mixed_source_analysis_classifies_rigid_and_static_objects(tmp_path):
    src=_mixed(tmp_path/'mixed.smd')
    report=analyze_mixed_source(src)
    assert report['status']=='PASS'
    assert report['mode']=='MIXED'
    assert report['rigid_objects']==['rigid']
    assert report['static_objects']==['static','untouched']
    assert report['eligible_rigid_objects']==['rigid']
    assert set(report['eligible_static_objects'])=={'static','untouched'}
    assert report['client_modified'] is False


def test_mixed_candidate_verifier_accepts_combined_rigid_static_edits_and_preserves_other_block(tmp_path):
    src=_mixed(tmp_path/'source.smd'); out=tmp_path/'candidate.smd'; out.write_bytes(src.read_bytes())
    _edit_vertex(out,'rigid',0,1); _edit_vertex(out,'static',1,2)
    result=validate_mixed_candidate_output(src,out,target_objects=['rigid','static'])
    assert result['status']=='PASS'
    assert result['mixed_modes_preserved'] is True
    assert result['non_target_changed']==[]
    assert {r['adapter'] for r in result['target_results']}=={'RIGID','STATIC'}
    assert all(r['edit_observed'] for r in result['target_results'])
    assert result['production_authorized'] is False


def test_mixed_candidate_verifier_detects_non_target_drift(tmp_path):
    src=_mixed(tmp_path/'source.smd'); out=tmp_path/'candidate.smd'; out.write_bytes(src.read_bytes())
    _edit_vertex(out,'rigid',0,1); _edit_vertex(out,'untouched',0,7)
    result=validate_mixed_candidate_output(src,out,target_objects=['rigid'])
    assert result['status']=='FAIL'
    assert result['non_target_changed']==['untouched']
    assert 'NON_TARGET_BLOCK_CHANGED' in result['errors']


def test_mixed_candidate_plan_uses_standalone_workspace_context(tmp_path):
    from pt_asset_tool.authoring import build_standalone_rigid_authoring_context, write_workspace_manifest
    from pt_asset_tool.blender_workspace import blender_edit_root
    from pt_asset_tool.mixed_authoring_candidate import plan_mixed_saved_blender_candidate
    source_dir=tmp_path/'client'; source_dir.mkdir()
    src=_mixed(source_dir/'mixed.smd')
    smb=source_dir/'mixed.smb'; smb.write_bytes(b'smb')
    structural=tmp_path/'structural.json'; structural.write_text('{"status":"PASS"}')
    asset=SimpleNamespace(
        asset_id='AST-MIXED',primary_path='char/test/mixed.smd',family='SMD_MODEL_062_MIXED_PHYSIQUE',kind='SMD_MODEL_062',
        physique_mode='MIXED',binding_skeleton_smb='',configs=[],
    )
    ctx=build_standalone_rigid_authoring_context(
        asset_logical=asset.primary_path,source_path=src,skeleton_logical='char/test/mixed.smb',skeleton_path=smb,
        selected_nodes=['rigid'],structural_gate_report=structural,
    )
    work=blender_edit_root(tmp_path,'generic_import',asset.primary_path); work.mkdir(parents=True)
    (work/'imported.blend').write_bytes(b'blend')
    write_workspace_manifest(work,asset,src,{'generic_build_authorized':False},[smb],selected_context=ctx)
    class Resolver:
        def resolve(self,logical,required=True):
            return {'char/test/mixed.smd':src,'char/test/mixed.smb':smb}[str(logical).replace('\\','/')]
    plan=plan_mixed_saved_blender_candidate(tmp_path,Resolver(),asset)
    assert plan['status']=='READY'
    assert plan['selected_context']['format']=='PT_ASSET_STANDALONE_RIGID_CONTEXT_V1'
    assert plan['skeleton']==str(smb.resolve())
    assert plan['object_adapters']['rigid']=='pt_blender_to_smd_free_mesh_v3.py'
    assert plan['object_adapters']['static']=='pt_blender_to_smd_static_v1.py'
    assert plan['production_authorized'] is False


def test_mixed_candidate_verifier_requires_every_target_edit_when_checked_by_caller(tmp_path):
    src=_mixed(tmp_path/'source.smd'); out=tmp_path/'candidate.smd'; out.write_bytes(src.read_bytes())
    _edit_vertex(out,'rigid',0,1)
    result=validate_mixed_candidate_output(src,out,target_objects=['rigid','static'])
    assert result['status']=='PASS'
    assert result['all_target_edits_observed'] is False
    assert result['targets_without_observed_edit']==['static']
