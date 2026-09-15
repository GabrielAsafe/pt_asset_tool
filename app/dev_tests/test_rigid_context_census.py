from __future__ import annotations

import pathlib
import struct
from types import SimpleNamespace

import pt_asset_tool.rigid_context_census as census
from pt_asset_tool.rigid_context_census import audit_rigid_context_census

SH, SI, SO, SV, SF, ST = 556, 40, 2236, 24, 36, 32


def _node_block(name: str, *, physique: bool, bone: str = "Bone") -> bytes:
    nv, nf, nt = 3, 1, 1
    length = SO + nv*SV + nf*SF + nt*ST + (nv*32 if physique else 0)
    b = bytearray(length); texbase = 0x100000
    struct.pack_into('<I', b, 12, texbase)
    struct.pack_into('<I', b, 16, 1 if physique else 0)
    struct.pack_into('<iii', b, 84, nv, nf, nt)
    b[172:172+len(name)] = name.encode('ascii')
    vo = SO
    for i, xyz in enumerate(((0,0,0),(256,0,0),(0,256,0))):
        struct.pack_into('<6i', b, vo+i*SV, *(xyz+(0,0,256)))
    fo = vo + nv*SV
    struct.pack_into('<4H', b, fo, 0,1,2,0); struct.pack_into('<I', b, fo+32, texbase)
    if physique:
        po = fo + SF + nt*ST
        for i in range(nv):
            raw = bone.encode('ascii'); b[po+i*32:po+i*32+len(raw)] = raw
    return bytes(b)


def _model(path: pathlib.Path, *, physique: bool, name: str = 'mesh', bone: str='Bone'):
    block = _node_block(name, physique=physique, bone=bone)
    first = SH + SI
    out = bytearray(first + len(block)); out[:23] = b'SMD Model data Ver 0.62'
    struct.pack_into('<i', out, 24, 1); struct.pack_into('<i', out, 28, 0)
    struct.pack_into('<i', out, 32, first); struct.pack_into('<i', out, 36, first)
    out[SH:SH+len(name)] = name.encode('ascii'); struct.pack_into('<i', out, SH+32, len(block)); struct.pack_into('<i', out, SH+36, first)
    out[first:] = block; path.write_bytes(out); return path


def _smb(path: pathlib.Path, bone: str='Bone'):
    block = bytearray(SO); block[172:172+len(bone)] = bone.encode('ascii')
    first = SH + SI
    out = bytearray(first + len(block)); out[:23] = b'SMD Model data Ver 0.62'
    struct.pack_into('<i', out, 24, 1); struct.pack_into('<i', out, 28, 0)
    struct.pack_into('<i', out, 32, first); struct.pack_into('<i', out, 36, first)
    out[SH:SH+len(bone)] = bone.encode('ascii'); struct.pack_into('<i', out, SH+32, len(block)); struct.pack_into('<i', out, SH+36, first)
    out[first:] = block; path.write_bytes(out); return path


class Registry:
    def __init__(self, assets, records): self.assets=assets; self.records=records


class Resolver:
    def __init__(self, mapping): self.mapping=mapping
    def resolve(self, logical, required=True):
        p=self.mapping.get(str(logical).replace('\\','/'))
        if p is None and required: raise FileNotFoundError(logical)
        return p


def _asset(path, *, skeleton='', configs=None, category='EFFECT'):
    return SimpleNamespace(
        asset_id='AST-'+path, primary_path=path, family='SMD_MODEL_062_RIGID_PHYSIQUE',
        category=category, binding_mode='ROOT_SKELETON_BOUND' if skeleton else 'NONE',
        binding_source='TEST' if skeleton else 'NONE', binding_skeleton_smb=skeleton,
        configs=list(configs or []),
    )


def test_census_physically_promotes_only_structurally_valid_sibling(tmp_path):
    smd=_model(tmp_path/'fx.smd',physique=True,bone='Bone')
    smb=_smb(tmp_path/'fx.smb',bone='Bone')
    asset=_asset('Effect/fx.smd')
    records=[{'extension':'.smb','relative_path':'Effect/fx.smb','category_hint':'EFFECT'}]
    reg=Registry([asset],records)
    resolver=Resolver({'Effect/fx.smd':smd,'Effect/fx.smb':smb})
    r=audit_rigid_context_census(reg,resolver,physical=True)
    assert r['status']=='PASS'
    assert r['rigid_asset_count']==1
    assert r['by_domain']['EFFECT']['STANDALONE_STRUCTURAL_PASS']==1
    assert r['unresolved_count']==0


def test_census_blocks_sibling_when_physique_bone_is_absent(tmp_path):
    smd=_model(tmp_path/'fx.smd',physique=True,bone='Missing')
    smb=_smb(tmp_path/'fx.smb',bone='Bone')
    asset=_asset('Effect/fx.smd')
    reg=Registry([asset],[{'extension':'.smb','relative_path':'Effect/fx.smb','category_hint':'EFFECT'}])
    resolver=Resolver({'Effect/fx.smd':smd,'Effect/fx.smb':smb})
    r=audit_rigid_context_census(reg,resolver,physical=True)
    assert r['status']=='FAIL'
    assert r['unresolved_count']==1
    assert r['unresolved_sample'][0]['structural_gate']['missing_bind_bones']==['Missing']


def test_census_accepts_registry_resolved_skeleton_without_model_info_lod_offline():
    asset=_asset('char/npc/Test/body.smd',skeleton='char/npc/Test/body.smb',category='NPC')
    reg=Registry([asset],[])
    r=audit_rigid_context_census(reg,physical=False)
    assert r['status']=='PASS'
    assert r['by_domain']['NPC']['RESOLVED_SKELETON']==1


def test_census_physically_rechecks_self_contained_model_info_skeleton(tmp_path, monkeypatch):
    smd=_model(tmp_path/'body.smd',physique=True,bone='Bone')
    smb=_smb(tmp_path/'body.smb',bone='Bone')
    inx=tmp_path/'body.inx'; inx.write_bytes(b'physical-inx')
    asset=_asset('char/npc/Test/body.smd',configs=[{'inx':'char/npc/Test/body.inx','motion_smb':'char/npc/Test/body.smb'}],category='NPC')
    reg=Registry([asset],[])
    resolver=Resolver({
        'char/npc/Test/body.smd':smd,
        'char/npc/Test/body.smb':smb,
        'char/npc/Test/body.inx':inx,
    })
    monkeypatch.setattr(census,'model_info_lod_context_available',lambda _asset:True)
    monkeypatch.setattr(census,'exact_lod_model_info_contexts',lambda _asset,require_motion_smb=True:[{
        'inx':'char/npc/Test/body.inx','motion_smb':'char/npc/Test/body.smb','lod':'default','nodes':['mesh'],
    }])
    r=audit_rigid_context_census(reg,resolver,physical=True)
    assert r['status']=='PASS'
    row=r['rows'][0]
    assert row['context_class']=='MODEL_INFO_LOD'
    assert row['physical_contexts'][0]['structural_gate']['status']=='PASS'


def test_census_blocks_self_contained_model_info_with_structural_mismatch(tmp_path, monkeypatch):
    smd=_model(tmp_path/'body.smd',physique=True,bone='Missing')
    smb=_smb(tmp_path/'body.smb',bone='Bone')
    inx=tmp_path/'body.inx'; inx.write_bytes(b'physical-inx')
    asset=_asset('char/npc/Test/body.smd',configs=[{'inx':'char/npc/Test/body.inx','motion_smb':'char/npc/Test/body.smb'}],category='NPC')
    reg=Registry([asset],[])
    resolver=Resolver({
        'char/npc/Test/body.smd':smd,
        'char/npc/Test/body.smb':smb,
        'char/npc/Test/body.inx':inx,
    })
    monkeypatch.setattr(census,'model_info_lod_context_available',lambda _asset:True)
    monkeypatch.setattr(census,'exact_lod_model_info_contexts',lambda _asset,require_motion_smb=True:[{
        'inx':'char/npc/Test/body.inx','motion_smb':'char/npc/Test/body.smb','lod':'default','nodes':['mesh'],
    }])
    r=audit_rigid_context_census(reg,resolver,physical=True)
    assert r['status']=='FAIL'
    assert r['unresolved_count']==1
    assert 'STRUCTURAL_GATE_FAIL' in r['rows'][0]['reason']


def test_census_accepts_exact_multi_context_link_binding_only_after_every_physical_context_passes(tmp_path):
    smd=_model(tmp_path/'multi.smd',physique=True,bone='Bone')
    smb1=_smb(tmp_path/'m1.smb',bone='Bone')
    smb3=_smb(tmp_path/'m3.smb',bone='Bone')
    smb4=_smb(tmp_path/'m4.smb',bone='Bone')
    inx_paths={}
    mapping={'src1.inx':tmp_path/'src1.inx','src2.inx':tmp_path/'src2.inx','src3.inx':tmp_path/'src3.inx',
             'm1bip.inx':tmp_path/'m1bip.inx','m3bip.inx':tmp_path/'m3bip.inx','m4bip.inx':tmp_path/'m4bip.inx'}
    for p in mapping.values(): p.write_bytes(b'inx')
    configs=[
        {'inx':'src1.inx','motion_inx':'m1bip.inx','motion_smb':'m1.smb','lod_groups':{}},
        {'inx':'src2.inx','motion_inx':'m3bip.inx','motion_smb':'m3.smb','lod_groups':{}},
        {'inx':'src3.inx','motion_inx':'m4bip.inx','motion_smb':'m4.smb','lod_groups':{}},
    ]
    asset=SimpleNamespace(
        asset_id='AST-multi',primary_path='multi.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE',category='CHARACTER',
        binding_mode='MULTI_CONTEXT_BOUND',binding_source='INX_LINK_FILE_MULTI_CONTEXT',binding_skeleton_smb='',configs=configs,
    )
    resolver=Resolver({'multi.smd':smd,'m1.smb':smb1,'m3.smb':smb3,'m4.smb':smb4,**mapping})
    r=audit_rigid_context_census(Registry([asset],[]),resolver,physical=True)
    assert r['status']=='PASS'
    assert r['unresolved_count']==0
    row=r['rows'][0]
    assert row['context_class']=='INX_LINK_MULTI_CONTEXT'
    assert row['context_count']==3
    assert row['unique_skeleton_count']==3
    assert row['animation_pose_certified'] is False
    assert all(x['structural_gate']['status']=='PASS' for x in row['physical_contexts'])


def test_census_multicontext_fails_if_one_skeleton_is_structurally_incompatible(tmp_path):
    smd=_model(tmp_path/'multi.smd',physique=True,bone='Bone')
    smb1=_smb(tmp_path/'m1.smb',bone='Bone')
    smb3=_smb(tmp_path/'m3.smb',bone='Missing')
    for name in ('src1.inx','src2.inx','m1bip.inx','m3bip.inx'):
        (tmp_path/name).write_bytes(b'inx')
    configs=[
        {'inx':'src1.inx','motion_inx':'m1bip.inx','motion_smb':'m1.smb','lod_groups':{}},
        {'inx':'src2.inx','motion_inx':'m3bip.inx','motion_smb':'m3.smb','lod_groups':{}},
    ]
    asset=SimpleNamespace(
        asset_id='AST-multi',primary_path='multi.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE',category='CHARACTER',
        binding_mode='MULTI_CONTEXT_BOUND',binding_source='INX_LINK_FILE_MULTI_CONTEXT',binding_skeleton_smb='',configs=configs,
    )
    resolver=Resolver({
        'multi.smd':smd,'m1.smb':smb1,'m3.smb':smb3,
        'src1.inx':tmp_path/'src1.inx','src2.inx':tmp_path/'src2.inx',
        'm1bip.inx':tmp_path/'m1bip.inx','m3bip.inx':tmp_path/'m3bip.inx',
    })
    r=audit_rigid_context_census(Registry([asset],[]),resolver,physical=True)
    assert r['status']=='FAIL'
    assert r['unresolved_count']==1
    assert 'STRUCTURAL_GATE_FAIL:m3.smb' in r['rows'][0]['reason']
