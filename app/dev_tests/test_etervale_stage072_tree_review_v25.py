"""V25: conservative human-confirmed links; real fore-1 V24 evidence when provided."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from pt_asset_tool.stage072_tree_review_v25 import (
    build_review, check_review, set_decision, approve_high_review,
    virtual_groups, review_path,
)


def sample():
    def group(id, *, stem, suggest=None, x=0.0, width=4.5, height=4.0, faces=None):
        foliage, trunk = (faces or [1, 2]), ([faces[-1] + 1] if stem else [])
        return {
            'id': id, 'faces': sorted(foliage + trunk),
            'foliage_faces': sorted(foliage), 'trunk_faces': trunk,
            'source_tree_ids': [id], 'anchor_view': [x, 0.0, 1.0],
            'anchor_game': [x * 100, 20, 50],
            'height_view': height, 'width_view': width,
            'suggested_trunk_id': suggest, 'suggestion_distance': 0.5 if suggest else None,
            'completion': 'TRUNK_WITH_FOLIAGE_REVIEW' if stem else 'FOLIAGE_ONLY',
            'category': 'ARVORE', 'review_status': 'PENDING',
            'accepted_for_runtime': False, 'manual_merged_from': [],
        }
    return {
        'format':'PT_ETERVALE_STAGE072_TREE_GROUPS_V24', 'version':1,
        'asset':'Field/test.smd', 'source_sha256':'a'*64,
        'source_face_count':100, 'source_vertex_count':200,
        'coordinate_basis':'GAME_Y_UP_LEFT_HANDED', 'publish_enabled':False,
        'not_game_runtime_certified':True,
        'groups':[
            group('stem_a', stem=True, x=0.0, faces=[1,2]),
            group('stem_b', stem=True, x=10.0, faces=[4,5]),
            group('foliage_a', stem=False, suggest='stem_a', x=0.2, faces=[7,8]),
            group('foliage_b', stem=False, suggest=None, x=30.0, faces=[10,11]),
        ],
    }


def test_build_review_does_not_merge_without_approval():
    v24 = sample()
    snapshot = deepcopy(v24)
    doc = build_review(v24=v24)
    assert len(doc['matches']) == 1
    assert doc['matches'][0]['decision'] == 'PENDING'
    assert len(virtual_groups(doc, v24=v24)) == 4
    assert v24 == snapshot
    assert doc['publish_enabled'] is False
    assert doc['not_game_runtime_certified'] is True


def test_manual_approval_merges_only_selected_pair():
    v24 = sample()
    doc = build_review(v24=v24)
    m = doc['matches'][0]
    set_decision(doc, v24=v24, orphan_id=m['id'], decision='APPROVED', note='inspecionado')
    merged = virtual_groups(doc, v24=v24)
    assert len(merged) == 3
    stem = next(g for g in merged if g['id'] == 'stem_a')
    assert set(stem['faces']) == {1,2,3,7,8}
    assert stem['v25_approved_links'] == ['foliage_a']
    assert stem['review_status'] == 'NEEDS_REVIEW'
    assert all(not g['accepted_for_runtime'] for g in merged)
    assert [g['id'] for g in v24['groups']] == ['stem_a','stem_b','foliage_a','foliage_b']


def test_rejection_does_not_merge():
    v24 = sample()
    doc = build_review(v24=v24)
    set_decision(doc, v24=v24, orphan_id='foliage_a', decision='REJECTED')
    assert len(virtual_groups(doc, v24=v24)) == 4


def test_source_or_group_change_invalidates_old_review():
    v24 = sample()
    doc = build_review(v24=v24)
    other = deepcopy(v24)
    other['groups'][0]['width_view'] += 0.1
    with pytest.raises(ValueError, match='V25_V24_CHANGED'):
        check_review(doc,v24=other)
    other = deepcopy(v24)
    other['source_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='V25_SOURCE'):
        check_review(doc,v24=other)


def test_reject_forged_decision_and_publication():
    v24 = sample()
    doc = build_review(v24=v24)
    forged = deepcopy(doc)
    forged['publish_enabled'] = True
    with pytest.raises(ValueError,match='V25_PUBLICATION'):
        check_review(forged,v24=v24)
    forged = deepcopy(doc)
    forged['matches'][0]['target_id']='stem_b'
    with pytest.raises(ValueError,match='V25_TARGET'):
        check_review(forged,v24=v24)
    with pytest.raises(ValueError,match='V25_DECISION'):
        set_decision(doc,v24=v24,orphan_id='foliage_a',decision='PUBLISH')


def test_duplicate_source_faces_block_virtual_merge():
    v24=sample()
    v24['groups'][2]['faces'].append(1)
    v24['groups'][2]['foliage_faces'].append(1)
    doc=build_review(v24=v24)
    with pytest.raises(ValueError,match='V25_DUPLICATE_SOURCE_FACE'):
        virtual_groups(doc,v24=v24)


def test_path_is_sidecar():
    p=Path('/tmp/trees/xyz.v24_groups.json')
    assert review_path(p)==Path('/tmp/trees/xyz.v25_review.json')
    with pytest.raises(ValueError,match='V25_EXPECTS'):
        review_path(Path('/tmp/other.json'))


def test_static_blender_ui_exposes_review_no_game_publish():
    script = (APP / 'pt_asset_tool/blender/stage072_tree_review_v25.py').read_text()
    registration = (APP / 'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    compile(script, 'stage072_tree_review_v25.py', 'exec')
    assert 'from __future__ import annotations' not in script  # Blender bpy.props annotations
    for item in ('v25_analyze','v25_inspect_pair','v25_decide',
                 'v25_batch_high_review','v25_inspection_objects'):
        assert item in script
    assert 'tree_v25.CLASSES' in registration
    assert 'tree_v25.configure()' in registration
    assert 'V25_PUBLICATION' not in script


def test_real_fore_1_v24_snapshot_if_present():
    path=Path('/mnt/data/6cd0d6e8c7586543.v24_groups.json')
    if not path.exists():
        pytest.skip('Amostra real V24 não fornecida nesta instalação')
    v24=json.loads(path.read_text(encoding='utf-8'))
    doc=build_review(v24=v24)
    assert len(doc['matches']) == 41
    assert Counter(m['tier'] for m in doc['matches']) == {'HIGH_REVIEW':16,'MANUAL_REVIEW':25}
    before=sum(len(g['faces']) for g in v24['groups'])
    assert len(virtual_groups(doc,v24=v24)) == 99
    assert approve_high_review(doc,v24=v24)==16
    after=virtual_groups(doc,v24=v24)
    assert len(after)==83
    assert sum(len(g['faces']) for g in after)==before
    assert len({i for g in after for i in g['faces']})==before
    assert all(not g['accepted_for_runtime'] for g in after)


def test_high_approval_is_opt_in_and_idempotent():
    v24=sample()
    doc=build_review(v24=v24)
    # No automatic approval on construction.
    assert all(m['decision']=='PENDING' for m in doc['matches'])
    n=approve_high_review(doc,v24=v24)
    assert n in (0,1)
    assert approve_high_review(doc,v24=v24)==0
