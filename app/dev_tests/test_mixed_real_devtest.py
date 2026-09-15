from types import SimpleNamespace

from pt_asset_tool.mixed_real_devtest import (
    choose_mixed_physique_representatives,
    choose_mixed_physical_context,
    mixed_skeleton_candidates,
)


def _asset(**kw):
    base=dict(
        asset_id='MIX', primary_path='Effect/Mixed/mix.smd', family='SMD_MODEL_062_MIXED_PHYSIQUE',
        category='EFFECT', object_count=3, total_vertices=9, total_faces=3,
        configs=[], binding_skeleton_smb='', source_record={'object_count':3,'physique_objects':1},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_mixed_representative_planner_never_samples_physical_mixed_assets():
    mixed1=_asset(asset_id='A',primary_path='Effect/Mixed/a.smd')
    mixed2=_asset(asset_id='B',primary_path='char/monster/M/b.smd',category='MONSTER')
    static=SimpleNamespace(asset_id='S',primary_path='Effect/s.smd',family='SMD_MODEL_062_STATIC',category='EFFECT',object_count=1,total_vertices=3,total_faces=1)
    registry=SimpleNamespace(assets=[mixed2,static,mixed1])
    rows=choose_mixed_physique_representatives(registry)
    assert {r['asset'] for r in rows}=={'Effect/Mixed/a.smd','char/monster/M/b.smd'}
    assert len(rows)==2


def test_mixed_skeleton_candidate_prefers_authoritative_config_over_sibling_hypothesis():
    asset=_asset(configs=[{'motion_smb':'Effect/Mixed/auth.smb'}])
    registry=SimpleNamespace(records=[
        {'extension':'.smb','relative_path':'Effect/Mixed/mix.smb'},
    ])
    rows=mixed_skeleton_candidates(registry,asset)
    assert rows[0]=={'skeleton_smb':'Effect/Mixed/auth.smb','basis':'MODEL_INFO_MOTION_SMB'}


def test_mixed_physical_context_standalone_requires_and_covers_both_adapters():
    asset=_asset(binding_skeleton_smb='Effect/Mixed/mix.smb')
    registry=SimpleNamespace(records=[])
    analysis={
        'eligible_rigid_objects':['rigidA'],
        'eligible_static_objects':['staticA','staticB'],
    }
    context=choose_mixed_physical_context(registry,asset,analysis)
    assert context['mode']=='STANDALONE_SKELETON'
    assert context['skeleton_smb']=='Effect/Mixed/mix.smb'
    assert context['rigid_targets']==['rigidA']
    assert context['static_targets']==['staticA','staticB']
    assert context['target_count']==3
