"""V30 all-canopy experimental face coverage, wall candidate policy, safety."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import pytest
from pt_asset_tool.environment_batch_v30 import plan_complete_preview,preview_record,FORMAT

SHA='e'*64


def g(i, faces, *, trunk=True, category='ARVORE', status='PENDING'):
    return {'id':i,'category':category, 'review_status':status,'accepted_for_runtime':False,
            'anchor_view':[float(faces[0]),0.,2.], 'height_view':3.,'faces':faces,
            'foliage_faces':faces[:-1] if trunk else faces,
            'trunk_faces':faces[-1:] if trunk else []}


def plan(groups, n=1000):
    return plan_complete_preview(groups,source_face_count=n,source_sha256=SHA,
                                 asset='Field/forest/fore-1.smd')


def test_uses_foliage_only_without_certifying_or_merging():
    doc=plan([g('z',[3,4],trunk=True),g('l',[7,8],trunk=False)])
    assert doc['count']==2 and doc['with_trunk']==1 and doc['foliage_only']==1
    assert doc['masked_face_indices']==[3,4,7,8]
    assert [x['id'] for x in doc['trees']]==['z','l']
    assert doc['trees'][1]['placement']=='FOLIAGE_ONLY_UNVERIFIED'
    assert not doc['publish_enabled'] and not doc['runtime_certified']
    assert not doc['wall_mounting_certified'] and not doc['foliage_semantics_certified']


def test_rejects_intergroup_duplicates_and_partition_mismatch():
    with pytest.raises(ValueError,match='ENTRE_GRUPOS'):
        plan([g('a',[1]),g('b',[1],trunk=False)])
    group=g('a',[1,2]);group['foliage_faces']=[1,2]
    with pytest.raises(ValueError,match='PARTICAO'):
        plan([group])
    with pytest.raises(ValueError,match='DUPLICADA'):
        plan([g('a',[1,1],trunk=False)])


def test_rejects_invalid_face_and_anchor():
    with pytest.raises(ValueError,match='FORA'):
        plan([g('a',[1000],trunk=False)])
    a=g('a',[2]); a['anchor_view'][0]=float('nan')
    with pytest.raises(ValueError,match='ANCHOR'):
        plan([a])
    a=g('a',[2]); a['height_view']=-1.
    with pytest.raises(ValueError,match='ALTURA'):
        plan([a])


def test_explicit_rejected_group_not_masked_or_instanced():
    doc=plan([g('a',[1,2]),g('b',[3,4],trunk=False,status='REJECTED')])
    assert doc['count']==1 and doc['excluded_groups']==1
    assert doc['masked_face_indices']==[1,2]


def test_max_instances_and_lod0_restriction():
    groups=[g(f'g{i}',[i+1],trunk=False) for i in range(101)]
    with pytest.raises(ValueError,match='ACIMA_DO_LIMITE'):
        plan(groups)
    with pytest.raises(ValueError,match='LOD0'):
        plan_complete_preview([g('a',[1])],source_face_count=100,source_sha256=SHA,
                              asset='Field/forest/fore-1.smd',lod='LOD2')


def test_review_status_not_runtime_approval():
    group=g('a',[1]);group['accepted_for_runtime']=True
    with pytest.raises(ValueError,match='PUBLICACAO'):
        plan([group])


def test_input_unmodified():
    data=[g('a',[1,2]),g('l',[3],trunk=False)]
    original=deepcopy(data)
    plan(data)
    assert data==original


def test_record_preserves_not_approved_and_diagnostic():
    doc=plan([g('a',[1,2]),g('b',[3,4],trunk=False)])
    cache={'source_sha256':'b'*64,'publish_enabled':False,'levels':{'LOD0':{'faces':102933}}}
    out=preview_record(doc,model_name='island_tree_01_1k.blend.zip',
        model_sha256='b'*64,mask_originals=True,cache_manifest=cache,
        wall_candidates=1,residual_material_faces=19)
    assert out['masked_face_count']==4 and out['instance_count']==2
    assert out['foliage_only_unverified']==1 and out['wall_candidates_unverified']==1
    assert out['residual_suspect_material_faces']==19
    assert not out['publish_enabled'] and out['approval_status']=='NOT_APPROVED'
    with pytest.raises(ValueError,match='CACHE'):
        preview_record(doc,model_name='x',model_sha256='c'*64,
            mask_originals=True,cache_manifest=cache,wall_candidates=0,
            residual_material_faces=0)


def test_report_omits_mask_if_visual_overlay_only():
    doc=plan([g('a',[1])]);cache={'source_sha256':'b'*64,
        'publish_enabled':False,'levels':{'LOD0':{'faces':102933}}}
    record=preview_record(doc,model_name='a',model_sha256='b'*64,
        mask_originals=False,cache_manifest=cache,wall_candidates=0,
        residual_material_faces=0)
    assert record['masked_face_count']==0


def test_real_v24_produces_99_4817_and_preserves_source_hash_if_fixture_exists():
    file=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.json')
    if not file.is_file():
        pytest.skip('fixture privado ausente')
    d=json.loads(file.read_text())
    p=plan_complete_preview(d['groups'],source_face_count=d['source_face_count'],
                            source_sha256=d['source_sha256'],asset=d['asset'])
    assert p['count']==99 and p['with_trunk']==56 and p['foliage_only']==43
    assert len(p['masked_face_indices'])==4817
    assert p['source_sha256']==d['source_sha256']


def test_blender_patch_keeps_original_proxy_and_v29_controls():
    source=(Path(__file__).parents[1] /'pt_asset_tool/blender/stage072_environment_v26.py').read_text()
    assert 'class PT_OT_V30PreviewAllLOD0' in source
    assert "v27._clear()" in source
    assert 'plan_complete_preview(source_groups' in source
    assert '_mask_v29_faces(plan[' in source
    assert 'PT_V30_BATCH=PASS' in source
    assert 'wall_v30.candidate_wall_contact' in source
    assert 'class PT_OT_V29PreviewAllLOD0' in source
    assert 'PT_V30_COBERTURA_COMPLETA_SO_PREVIEW' in source
    op=source.split('class PT_OT_V30PreviewAllLOD0')[1].split('class PT_OT_V29Clear')[0]
    assert "SESSION['approvals']" not in op
    assert 'write_smd' not in op
