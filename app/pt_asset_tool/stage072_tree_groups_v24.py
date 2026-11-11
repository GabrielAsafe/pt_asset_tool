"""V24: non-destructive, trunk-guided grouping of V23 tree fragments.

Deliberately conservative: orphan canopy fragments are assigned automatically
only with strong spatial and material evidence. Other candidates retain their
faces and appear as explicit review entries, never silently discarded.
This module does not import Blender and cannot write game assets.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from pt_asset_tool.stage072_trees_v23 import FORMAT as V23_FORMAT, TreeFace

FORMAT = 'PT_ETERVALE_STAGE072_TREE_GROUPS_V24'
VERSION = 1
STATES = frozenset({'PENDING', 'APPROVED', 'REJECTED', 'NEEDS_REVIEW'})
MAX_GROUPS = 240


def _fingerprint(doc):
    payload = [(t['id'], sorted(t['faces']), sorted(t['foliage_faces']), sorted(t['trunk_faces']))
               for t in sorted(doc['trees'], key=lambda x:x['id'])]
    return hashlib.sha256(json.dumps(payload, separators=(',',':')).encode()).hexdigest()


def _distxy(a, b):
    return math.hypot(float(a[0])-float(b[0]), float(a[1])-float(b[1]))


def _materials(t, lookup):
    return {lookup[i].material.casefold() for i in t['foliage_faces']}


def _proposal_dist(orphan, seed, lookup):
    """Return distance only if candidate shares material and terrain band.

    This is not a claim of semantic identity; anchors and materials in these
    maps can be misleading, so ambiguous proposals must remain visible.
    """
    if not (_materials(orphan, lookup) & _materials(seed, lookup)):
        return None
    p, s = orphan['anchor_view'], seed['anchor_view']
    width = max(.1, float(seed['width_view'] or 1.))
    height = max(.1, float(seed['height_view'] or 1.))
    d = _distxy(p, s)
    if d > min(2.65, max(.65, .56 * width)):
        return None
    if abs(float(p[2])-float(s[2])) > max(.55, height*.28):
        return None
    # Reject candidates with substantial geometry entirely below / above the
    # possible stem's canopy; we don't know the actual ground collision height.
    cen = [lookup[i].center[2] for i in orphan['foliage_faces']]
    if cen and (max(cen) < float(s[2]) + .16 or min(cen) > float(s[2]) + height + .8):
        return None
    return d


def _root_group(t):
    return {
        'id':t['id'], 'category':'ARVORE', 'source_tree_ids':[t['id']],
        'faces':sorted(set(t['faces'])),
        'foliage_faces':sorted(set(t['foliage_faces'])),
        'trunk_faces':sorted(set(t['trunk_faces'])),
        'anchor_view':list(t['anchor_view']), 'anchor_game':list(t['anchor_game']),
        'height_view':float(t.get('height_view') or 1.),
        'width_view':float(t.get('width_view') or 1.),
        'review_status':'PENDING', 'note':'',
        'completion':('TRUNK_WITH_FOLIAGE_REVIEW' if t['trunk_faces'] else 'FOLIAGE_ONLY_REVIEW'),
        'suggested_trunk_id':None, 'suggestion_distance':None,
        'auto_merged_from':[], 'manual_merged_from':[],
        'accepted_for_runtime':False,
    }


def build_v24_groups(*, v23:dict, faces:list[TreeFace]) -> dict:
    """Build face-disjoint groups from V23 without changing V23 or SMD.

    Complete *small* foliage fragments with one unambiguous stem are merged.
    Two objects with trunks are NEVER merged. Larger, full-height orphan
    canopies get a suggestion, but stay separate for manual review.
    """
    if v23.get('format') != V23_FORMAT:
        raise ValueError('V24_REQUIRES_VALID_V23')
    trees = v23.get('trees', [])
    if len(trees) > MAX_GROUPS:
        raise ValueError('V24_TOO_MANY_SOURCE_TREES')
    lookup = {f.index:f for f in faces}
    if len(lookup) != len(faces):
        raise ValueError('V24_DUPLICATE_FACE_INDEX')
    all_ids = set()
    for t in trees:
        these = set(t['faces'])
        if not these or not these <= lookup.keys() or all_ids.intersection(these):
            raise ValueError('V24_SOURCE_FACES_INVALID_OR_OVERLAPPING')
        all_ids.update(these)
    stems = sorted((t for t in trees if t['trunk_faces']), key=lambda t:t['id'])
    orphans = sorted((t for t in trees if not t['trunk_faces']), key=lambda t:t['id'])
    groups = {t['id']:_root_group(t) for t in trees}
    auto_count = 0
    suggestion_count = 0
    for orphan in orphans:
        ranked = []
        for seed in stems:
            dist = _proposal_dist(orphan, seed, lookup)
            if dist is not None:
                ranked.append((dist,seed['id'],seed))
        ranked.sort()
        if not ranked:
            continue
        d, target_id, seed = ranked[0]
        near_tie = len(ranked) > 1 and ranked[1][0] <= max(d*1.65, d+.50)
        width = max(.1, float(seed.get('width_view') or 1.))
        height = max(.1, float(seed.get('height_view') or 1.))
        # A whole orphan tree can have foliage material and anchor like a stem
        # tree close by. Do not absorb these simply because canopies overlap.
        small_fragment = (len(orphan['foliage_faces']) <= 9 or
                          (float(orphan.get('height_view') or 0) < height * .49 and
                           len(orphan['foliage_faces']) <= max(12, len(seed['foliage_faces'])//3)))
        very_near = d < min(1.0, width*.21)
        g = groups[orphan['id']]
        g['suggested_trunk_id'] = target_id
        g['suggestion_distance'] = round(d, 6)
        suggestion_count += 1
        if not (small_fragment and very_near and not near_tie):
            g['completion'] = 'FOLIAGE_ONLY_REVIEW_SUGGESTED_STEM'
            continue
        target = groups[target_id]
        target['faces'] = sorted(set(target['faces']) | set(g['faces']))
        target['foliage_faces'] = sorted(set(target['foliage_faces']) | set(g['foliage_faces']))
        target['source_tree_ids'] = sorted(set(target['source_tree_ids']) | set(g['source_tree_ids']))
        target['auto_merged_from'].append(orphan['id'])
        target['completion'] = 'TRUNK_WITH_AUTO_FOLIAGE_REVIEW'
        del groups[orphan['id']]
        auto_count += 1
    ordered = sorted(groups.values(), key=lambda g:(0 if g['trunk_faces'] else 1, g['id']))
    doc = {
        'format':FORMAT, 'version':VERSION, 'asset':v23['asset'],
        'source_sha256':v23['source_sha256'],
        'source_vertex_count':v23['source_vertex_count'],
        'source_face_count':v23['source_face_count'],
        'v23_fingerprint':_fingerprint(v23),
        'coordinate_basis':'GAME_Y_UP_LEFT_HANDED',
        'not_game_runtime_certified':True, 'publish_enabled':False,
        'counts':{
            'source_proposals':len(trees), 'groups':len(ordered),
            'with_trunk':sum(bool(g['trunk_faces']) for g in ordered),
            'foliage_only':sum(not g['trunk_faces'] for g in ordered),
            'auto_attached':auto_count, 'review_suggestions':suggestion_count - auto_count,
        },
        'groups':ordered,
    }
    check_v24_groups(doc, v23=v23)
    return doc


def check_v24_groups(doc:dict, *, v23:dict):
    if doc.get('format') != FORMAT or doc.get('version') != VERSION:
        raise ValueError('V24_FORMAT_INVALID')
    for field in ('asset','source_sha256','source_vertex_count','source_face_count'):
        if doc.get(field) != v23.get(field):
            raise ValueError('V24_SOURCE_MISMATCH')
    if doc.get('v23_fingerprint') != _fingerprint(v23):
        raise ValueError('V24_V23_FACE_PLAN_CHANGED')
    if not doc.get('not_game_runtime_certified') or doc.get('publish_enabled'):
        raise ValueError('V24_PUBLICATION_FORBIDDEN')
    if not 0 < len(doc.get('groups', [])) <= MAX_GROUPS:
        raise ValueError('V24_GROUP_COUNT_INVALID')
    expected_sources = {t['id'] for t in v23['trees']}
    expected_faces = {x for t in v23['trees'] for x in t['faces']}
    seen_sources, seen_faces, seen_groups = set(),set(),set()
    for g in doc['groups']:
        if g['id'] in seen_groups or g['review_status'] not in STATES or g['accepted_for_runtime']:
            raise ValueError('V24_GROUP_STATUS_OR_ID_INVALID')
        seen_groups.add(g['id'])
        ids = set(g['source_tree_ids'])
        if not ids or seen_sources.intersection(ids):
            raise ValueError('V24_DUPLICATE_OR_MISSING_SOURCE_TREE')
        seen_sources.update(ids)
        faces, leaf, trunk = (set(g[k]) for k in ('faces','foliage_faces','trunk_faces'))
        if not faces or leaf | trunk != faces or not leaf.isdisjoint(trunk) or seen_faces.intersection(faces):
            raise ValueError('V24_DUPLICATE_OR_MISSING_FACES')
        seen_faces.update(faces)
        if any(not math.isfinite(float(x)) for x in (*g['anchor_view'], *g['anchor_game'])):
            raise ValueError('V24_ANCHOR_INVALID')
        if g['suggested_trunk_id'] is not None and g['suggested_trunk_id'] not in expected_sources:
            raise ValueError('V24_SUGGESTION_INVALID')
    if seen_sources != expected_sources or seen_faces != expected_faces:
        raise ValueError('V24_SOURCE_COVERAGE_CHANGED')
    return True


def accept_manual_attachment(doc:dict, *, orphan_id:str, v23:dict):
    """Human-confirmed: merge a complete orphan group into its suggested stem.

    Never accept automatic publication, never merge two trunk-containing groups.
    Caller must present/highlight the proposal first. Only V24 JSON changes.
    """
    check_v24_groups(doc, v23=v23)
    by_id = {g['id']:g for g in doc['groups']}
    if orphan_id not in by_id:
        raise ValueError('V24_ORPHAN_NOT_FOUND')
    src = by_id[orphan_id]
    target = by_id.get(src['suggested_trunk_id'])
    if src['trunk_faces'] or target is None or not target['trunk_faces']:
        raise ValueError('V24_NO_VALID_SUGGESTED_STEM')
    if src['review_status']=='REJECTED' or target['review_status']=='REJECTED':
        raise ValueError('V24_REJECTED_GROUP_CANNOT_MERGE')
    target['faces'] = sorted(set(target['faces']) | set(src['faces']))
    target['foliage_faces'] = sorted(set(target['foliage_faces']) | set(src['foliage_faces']))
    target['source_tree_ids'] = sorted(set(target['source_tree_ids']) | set(src['source_tree_ids']))
    target['manual_merged_from'] = sorted(set(target['manual_merged_from']) | set(src['source_tree_ids']))
    target['completion'] = 'TRUNK_WITH_MANUAL_FOLIAGE_REVIEW'
    target['review_status'] = 'NEEDS_REVIEW'
    doc['groups'] = [g for g in doc['groups'] if g['id'] != orphan_id]
    doc['counts']['groups'] = len(doc['groups'])
    doc['counts']['foliage_only'] = sum(not g['trunk_faces'] for g in doc['groups'])
    doc['counts']['review_suggestions'] = sum(not g['trunk_faces'] and g['suggested_trunk_id'] is not None for g in doc['groups'])
    check_v24_groups(doc,v23=v23)
    return target['id']


def group_plan_path(v23_path:Path)->Path:
    p=Path(v23_path)
    if not p.name.endswith('.v23_trees.json'):
        raise ValueError('V24_EXPECTS_V23_PATH')
    return p.with_name(p.name[:-len('.v23_trees.json')]+'.v24_groups.json')
