"""V25: source-locked, human-confirmed foliage -> trunk associations.

Reads V24 groups, produces separate V25 decisions and virtual merged groups.
No Blender dependency; never exports to the game or rewrites V22/V23/V24.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

FORMAT = 'PT_ETERVALE_STAGE072_TREE_REVIEW_V25'
VERSION = 1
DECISIONS = frozenset({'PENDING', 'APPROVED', 'REJECTED', 'NEEDS_REVIEW'})
MAX_MATCHES = 240


def _fingerprint(doc):
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _distance(a, b):
    return math.hypot(float(a[0])-float(b[0]), float(a[1])-float(b[1]))


def _score_match(orphan, target, stems, conflicts):
    """Rank structural plausibility, not semantic certainty.

    The cached V24 suggestion already required material and local height evidence.
    Additional checks guard near-neighbour stems and same-stem competing canopies.
    """
    dist = _distance(orphan['anchor_view'], target['anchor_view'])
    td = max(.1, float(target['width_view']))
    th = max(.1, float(target['height_view']))
    oh = max(.1, float(orphan['height_view']))
    ow = max(.1, float(orphan['width_view']))
    dz = abs(float(orphan['anchor_view'][2])-float(target['anchor_view'][2]))
    rivals = sorted(_distance(orphan['anchor_view'], st['anchor_view'])
                    for st in stems if st['id'] != target['id']
                    and abs(float(st['anchor_view'][2])-float(orphan['anchor_view'][2]))
                    <= max(.55, float(st['height_view'])*.30))
    runner_up = rivals[0] if rivals else None
    ratio = oh/th
    evidence = ['V24_MATERIAL_AND_LOCAL_GROUND_COMPATIBLE']
    flags = []
    if dz <= .32:
        evidence.append('GROUND_LEVEL_CLOSE')
    else:
        flags.append('GROUND_LEVEL_DIFFERENCE')
    if dist <= min(1.42, td*.31):
        evidence.append('CENTRE_NEAR_STEM')
    else:
        flags.append('CENTRE_OFFSET_REVIEW')
    if .64 <= ratio <= 1.30:
        evidence.append('HEIGHT_SIMILAR')
    else:
        flags.append('HEIGHT_MISMATCH')
    if runner_up is None or runner_up >= max(dist*1.6, dist+1.15):
        evidence.append('NEAREST_TRUNK_DISTINCT')
    else:
        flags.append('POSSIBLE_OTHER_TRUNK')
    if ow <= td*1.35:
        evidence.append('CANOPY_WIDTH_COMPATIBLE')
    else:
        flags.append('CANOPY_WIDER_THAN_STEM')
    if conflicts > 1:
        flags.append('MULTIPLE_FOLIAGE_GROUPS_TARGET_ONE_TRUNK')
    # Use an intelligible 0..100 heuristic; not a calibrated likelihood.
    score = max(0, min(100, round(100 - 25*dist/td - 24*dz/th
             - 20*abs(math.log(ratio)) - 10*max(0, ow/td-1)
             - (22 if 'POSSIBLE_OTHER_TRUNK' in flags else 0)
             - (9 if conflicts>1 else 0))))
    strong = all(k in evidence for k in ('GROUND_LEVEL_CLOSE', 'CENTRE_NEAR_STEM',
                'HEIGHT_SIMILAR', 'NEAREST_TRUNK_DISTINCT', 'CANOPY_WIDTH_COMPATIBLE'))
    # Even 'HIGH_REVIEW' is only a prioritized *suggestion*. Never auto-merge.
    tier = 'HIGH_REVIEW' if strong and conflicts == 1 and score >= 75 else 'MANUAL_REVIEW'
    return {'score':score, 'tier':tier, 'evidence':evidence, 'flags':flags,
            'distance_view':round(dist, 6), 'height_ratio':round(ratio, 5),
            'ground_delta_view':round(dz, 6),
            'second_stem_distance_view':round(runner_up, 6) if runner_up is not None else None}


def build_review(*, v24:dict)->dict:
    if v24.get('format') != 'PT_ETERVALE_STAGE072_TREE_GROUPS_V24' or v24.get('version') != 1:
        raise ValueError('V25_REQUIRES_VALID_V24')
    groups = v24.get('groups', [])
    by_id = {g['id']:g for g in groups}
    if len(by_id) != len(groups) or not 0 < len(groups) <= MAX_MATCHES:
        raise ValueError('V25_GROUPS_INVALID')
    stems = [g for g in groups if g['trunk_faces']]
    sources = [g for g in groups if not g['trunk_faces'] and g.get('suggested_trunk_id')]
    target_counts = Counter(g['suggested_trunk_id'] for g in sources)
    matches = []
    for g in sources:
        target = by_id.get(g['suggested_trunk_id'])
        if target is None or not target['trunk_faces'] or target['id'] == g['id']:
            raise ValueError('V25_INVALID_SUGGESTED_TARGET')
        detail = _score_match(g, target, stems, target_counts[target['id']])
        matches.append({'id':g['id'], 'orphan_id':g['id'], 'target_id':target['id'],
                        'orphan_face_count':len(g['faces']),
                        'target_face_count':len(target['faces']),
                        'decision':'PENDING', 'note':'', **detail})
    matches.sort(key=lambda m: (0 if m['tier']=='HIGH_REVIEW' else 1, -m['score'], m['id']))
    result = {'format':FORMAT, 'version':VERSION, 'asset':v24['asset'],
              'source_sha256':v24['source_sha256'],
              'source_face_count':v24['source_face_count'],
              'source_vertex_count':v24['source_vertex_count'],
              'v24_fingerprint':_fingerprint(v24),
              'coordinate_basis':'GAME_Y_UP_LEFT_HANDED',
              'not_game_runtime_certified':True, 'publish_enabled':False,
              'anchor_policy':'V24_STEM_BASE_PROPOSAL_NOT_COLLISION_CERTIFIED',
              'matches':matches}
    check_review(result, v24=v24)
    return result


def check_review(doc:dict, *, v24:dict):
    if doc.get('format') != FORMAT or doc.get('version') != VERSION:
        raise ValueError('V25_FORMAT_INVALID')
    for field in ('asset', 'source_sha256', 'source_face_count', 'source_vertex_count'):
        if doc.get(field) != v24.get(field):
            raise ValueError('V25_SOURCE_MISMATCH')
    if doc.get('v24_fingerprint') != _fingerprint(v24):
        raise ValueError('V25_V24_CHANGED_PRESERVE_PREVIOUS_DECISIONS')
    if doc.get('publish_enabled') or not doc.get('not_game_runtime_certified'):
        raise ValueError('V25_PUBLICATION_FORBIDDEN')
    expected = {g['id']:g['suggested_trunk_id'] for g in v24['groups']
                if not g['trunk_faces'] and g.get('suggested_trunk_id')}
    found = {}
    for m in doc.get('matches', []):
        if m['id'] in found or m['id'] != m['orphan_id'] or m['decision'] not in DECISIONS:
            raise ValueError('V25_DUPLICATE_ID_OR_BAD_DECISION')
        if m['target_id'] != expected.get(m['id']):
            raise ValueError('V25_TARGET_CHANGED')
        if not isinstance(m.get('note'), str) or len(m['note']) > 600:
            raise ValueError('V25_NOTE_INVALID')
        if m.get('tier') not in ('HIGH_REVIEW', 'MANUAL_REVIEW'):
            raise ValueError('V25_TIER_INVALID')
        if not isinstance(m.get('score'), int) or not 0 <= m['score'] <= 100:
            raise ValueError('V25_SCORE_INVALID')
        found[m['id']] = m['target_id']
    if found != expected or len(found) > MAX_MATCHES:
        raise ValueError('V25_ASSOCIATION_COVERAGE_CHANGED')
    return True


def set_decision(doc:dict, *, v24:dict, orphan_id:str, decision:str, note:str|None=None):
    check_review(doc, v24=v24)
    if decision not in DECISIONS:
        raise ValueError('V25_DECISION_INVALID')
    m = next((m for m in doc['matches'] if m['id']==orphan_id), None)
    if m is None:
        raise ValueError('V25_ASSOCIATION_NOT_FOUND')
    if note is not None and len(note) > 600:
        raise ValueError('V25_NOTE_TOO_LONG')
    m['decision']=decision
    if note is not None:
        m['note']=note
    check_review(doc, v24=v24)
    return m


def approve_high_review(doc:dict, *, v24:dict)->int:
    """Explicit user action only. No merging/publication happens here."""
    check_review(doc, v24=v24)
    count = 0
    for m in doc['matches']:
        if m['tier']=='HIGH_REVIEW' and m['decision']=='PENDING':
            m['decision']='APPROVED'
            count += 1
    check_review(doc, v24=v24)
    return count


def virtual_groups(doc:dict, *, v24:dict)->list[dict]:
    """Materialize a read-only V25 *inspection view* of explicitly approved links.

    No source faces are hidden from the game; no updates to V24 or writer SMD.
    """
    check_review(doc, v24=v24)
    groups = {g['id']:deepcopy(g) for g in v24['groups']}
    source_faces = {i for g in groups.values() for i in g['faces']}
    source_ids = {i for g in groups.values() for i in g['source_tree_ids']}
    if sum(len(g['faces']) for g in groups.values()) != len(source_faces):
        raise ValueError('V25_DUPLICATE_SOURCE_FACE')
    for m in sorted(doc['matches'], key=lambda x:x['id']):
        if m['decision']!='APPROVED':
            continue
        orphan = groups.get(m['orphan_id'])
        target = groups.get(m['target_id'])
        if orphan is None or target is None or orphan['trunk_faces'] or not target['trunk_faces']:
            raise ValueError('V25_MERGE_TARGET_INVALID')
        if set(orphan['faces']) & set(target['faces']):
            raise ValueError('V25_FACE_OVERLAP_BEFORE_MERGE')
        target['faces'] = sorted(set(target['faces']) | set(orphan['faces']))
        target['foliage_faces'] = sorted(set(target['foliage_faces']) | set(orphan['foliage_faces']))
        target['source_tree_ids'] = sorted(set(target['source_tree_ids']) | set(orphan['source_tree_ids']))
        target['completion']='V25_HUMAN_CONFIRMED_FOLIAGE_AND_TRUNK'
        target.setdefault('v25_approved_links',[]).append(m['id'])
        target['review_status']='NEEDS_REVIEW'  # link approved != tree/game approved
        target['accepted_for_runtime']=False
        # Use the existing stem anchor as a proposal; we cannot claim collision-certified ground.
        del groups[m['orphan_id']]
    result = sorted(groups.values(), key=lambda g:(0 if g['trunk_faces'] else 1,g['id']))
    after_faces = [i for g in result for i in g['faces']]
    after_sources = [i for g in result for i in g['source_tree_ids']]
    if len(after_faces)!=len(source_faces) or set(after_faces)!=source_faces or len(after_sources)!=len(source_ids) or set(after_sources)!=source_ids:
        raise ValueError('V25_FACE_OR_SOURCE_COVERAGE_CHANGED')
    for g in result:
        f,l,t = (set(g[k]) for k in ('faces','foliage_faces','trunk_faces'))
        if f!=l|t or l&t or g['accepted_for_runtime']:
            raise ValueError('V25_BAD_GROUP_PARTITION')
    return result


def review_path(v24_path:Path)->Path:
    p=Path(v24_path)
    suffix='.v24_groups.json'
    if not p.name.endswith(suffix):
        raise ValueError('V25_EXPECTS_V24_PATH')
    return p.with_name(p.name[:-len(suffix)]+'.v25_review.json')
