"""V23: conservative tree completion from V22 foliage + Stage072 proxy geometry.

Pure Python; no Blender dependency.  Source-locked proposals, NEVER a game export.
All distances are Blender V19 proxy/view units (Z up); game coordinates are Y up.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

from pt_asset_tool.stage072_semantic_core import view_to_source

FORMAT = 'PT_ETERVALE_STAGE072_TREES_V23'
VERSION = 1
MAX_SOURCE_FACES = 250_000
MAX_TREES = 240
MAX_FACES_PER_TREE = 12_000
STATE = frozenset(('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_REVIEW'))


@dataclass(frozen=True)
class TreeFace:
    index: int
    material: str
    center: tuple[float, float, float]
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    normal_z: float
    area: float
    vertices: tuple[int, ...] = ()

    def __post_init__(self):
        if self.index < 0 or not all(math.isfinite(float(x)) for x in
                                      (*self.center, *self.lo, *self.hi, self.normal_z, self.area)):
            raise ValueError('INVALID_TREE_FACE')


# Conservative architectural and terrain blockers; material names alone are not proof.
PROTECTED = ('wall', 'city', 'roof', 'floor', 'road', 'bridge', 'building', 'house',
             'collision', 'nowalk', 'no_texture', 't_city', 'stairs', 'stonefloor')


def _trunk_faces(candidate: dict, faces: list[TreeFace], claimed_foliage: set[int]) -> list[int]:
    """Only compact, near-central, upright polygons below the canopy.

    This is a proposal, not evidence of a trunk in the game. Candidate selection
    intentionally prefers missed trees over hiding ground/architecture.
    """
    bmin = candidate['view_bounds_min']
    bmax = candidate['view_bounds_max']
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    width = max(float(candidate.get('width_view', 0.)), bmax[0]-bmin[0], bmax[1]-bmin[1])
    height = max(float(candidate.get('height_view', 0.)), bmax[2]-bmin[2])
    ground = float(candidate['view_anchor'][2])
    search_radius = max(.35, min(1.7, width * .26))
    face_limit = max(.18, width * .46)
    possible = []
    for f in faces:
        if f.index in claimed_foliage:
            continue
        lower = f.material.lower()
        if any(token in lower for token in PROTECTED):
            continue
        if abs(f.normal_z) > .58:  # upright sides rather than ground or roof
            continue
        if math.dist(f.center[:2], (cx,cy)) > search_radius:
            continue
        if f.hi[0] - f.lo[0] > face_limit or f.hi[1] - f.lo[1] > face_limit:
            continue
        if f.hi[2] - f.lo[2] < .045 or f.hi[2] - f.lo[2] > max(6., height * 1.2):
            continue
        if f.hi[2] < ground + .08 or f.lo[2] > ground + max(.8, height*.72):
            continue
        if f.lo[2] < ground - max(.8, height*.25):
            continue
        if f.area > max(1.5, height * width * .4):
            continue
        possible.append(f)
    return [f.index for f in possible]


def _components(ids: list[int], lookup: dict[int, TreeFace]) -> list[list[int]]:
    """Connected components of polygons by shared native vertex IDs.

    Individual billboards need not be connected; those remain foliage-only
    until human review and must not be invented as trunks.
    """
    idset = set(ids)
    vert_to_faces = defaultdict(list)
    for fid in ids:
        for v in lookup[fid].vertices:
            vert_to_faces[v].append(fid)
    neighbor = defaultdict(set)
    for group in vert_to_faces.values():
        for f in group:
            neighbor[f].update(x for x in group if x != f)
    groups = []
    while idset:
        start = min(idset)
        q = [start]
        idset.remove(start)
        group = []
        while q:
            f = q.pop()
            group.append(f)
            for other in neighbor.get(f, ()):
                if other in idset:
                    idset.remove(other)
                    q.append(other)
        groups.append(sorted(group))
    return groups


def _choose_trunk(candidate: dict, faces: list[TreeFace], lookup: dict[int, TreeFace],
                  claimed_foliage: set[int]):
    ids = _trunk_faces(candidate, faces, claimed_foliage)
    if not ids:
        return [], None, 'LEAVES_ONLY_REVIEW'
    groups = _components(ids, lookup)
    g = float(candidate['view_anchor'][2])
    width = max(.1, float(candidate.get('width_view', 1.0)))
    tree_height = max(.1, float(candidate.get('height_view', 1.0)))
    cx,cy = candidate['view_anchor'][:2]
    eligible = []
    for group in groups:
        if len(group) < 2:
            continue
        low = min(lookup[i].lo[2] for i in group)
        high = max(lookup[i].hi[2] for i in group)
        if high-low < max(.24, tree_height*.14):
            continue
        if low > g + max(.65, tree_height*.3):
            continue
        pts = [lookup[i].center for i in group]
        x = sum(p[0] for p in pts) / len(pts)
        y = sum(p[1] for p in pts) / len(pts)
        radial = math.dist((cx,cy), (x,y))
        if radial > max(.45, min(width*.3, 1.9)):
            continue
        score = ((high-low)/max(tree_height,.01)) * 2.5 + min(len(group),20)*.05 - radial/max(.1,width)
        eligible.append((score, min(group), group))
    if not eligible:
        return [], None, 'LEAVES_ONLY_REVIEW'
    eligible.sort(key=lambda x: (-x[0], x[1]))
    winner = eligible[0][2]
    # A trunk proposal is only trustworthy when it is a connected vertical stem.
    bottom = min(lookup[i].lo[2] for i in winner)
    low_faces = [lookup[i] for i in winner if lookup[i].lo[2] <= bottom+.30]
    if not low_faces:
        return [], None, 'LEAVES_ONLY_REVIEW'
    bx = sum(p.center[0] for p in low_faces) / len(low_faces)
    by = sum(p.center[1] for p in low_faces) / len(low_faces)
    return winner, (bx, by, g), 'TRUNK_CANDIDATE_REVIEW'


def build_tree_plan(*, v22: dict, faces: list[TreeFace], center_xyz: tuple[float,float,float],
                    view_scale: float) -> dict:
    """Reconstruct a proposal for each V22 tree; never edit V22 or original Stage.

    Tree count is preserved by design. Suspicious split/merged candidates are
    explicitly flagged rather than silently collapsed or deleted.
    """
    if len(faces) > MAX_SOURCE_FACES:
        raise ValueError('TREE_SOURCE_TOO_LARGE')
    if v22.get('format') != 'PT_ETERVALE_STAGE072_OBJECT_PROPOSALS_V22':
        raise ValueError('REQUIRES_V22_PROPOSALS')
    if not (math.isfinite(view_scale) and view_scale > 0):
        raise ValueError('INVALID_VIEW_SCALE')
    ids = {f.index for f in faces}
    if len(ids) != len(faces):
        raise ValueError('DUPLICATE_GEOMETRY_FACE_ID')
    lookup = {f.index:f for f in faces}
    targets = [p for p in v22['candidates'] if p['category'] == 'ARVORE' and p['status'] != 'REJECTED']
    if len(targets) > MAX_TREES:
        raise ValueError('TOO_MANY_TREE_CANDIDATES')
    foliage_all = {fid for p in targets for fid in p['faces']}
    if not foliage_all <= ids:
        raise ValueError('V22_FACE_OUT_OF_RANGE')
    used_trunks = {}
    trees = []
    for p in targets:
        leaf_ids = sorted(set(p['faces']))
        trunk, root, state = _choose_trunk(p, faces, lookup, foliage_all)
        if root is None:
            root = tuple(p['view_anchor'])
        shared = [i for i in trunk if i in used_trunks]
        if shared:
            state = 'TRUNK_SHARED_REVIEW'
            # Do not mark dubious shared geometry for visual removal.
            trunk = []
            root = tuple(p['view_anchor'])
        else:
            for fid in trunk:
                used_trunks[fid] = p['id']
        # Candidate anchor may use heuristic terrain, not certified collision.
        game = list(view_to_source(tuple(root), center_xyz, view_scale))
        tree_faces = sorted(set(leaf_ids) | set(trunk))
        if len(tree_faces) > MAX_FACES_PER_TREE:
            raise ValueError('TREE_TOO_MANY_FACES')
        trees.append({
            'id': p['id'], 'source_proposal_id': p['id'],
            'category': 'ARVORE', 'status': p['status'],
            'confidence': p.get('confidence', 'LOW_REVIEW_REQUIRED'),
            'completion': state,
            'foliage_faces': leaf_ids, 'trunk_faces': sorted(trunk),
            'faces': tree_faces,
            'anchor_view': [float(x) for x in root],
            'anchor_game': game,
            'ground_status': p.get('ground_status', 'GROUND_NOT_CERTIFIED'),
            'width_view': p.get('width_view'), 'height_view': p.get('height_view'),
            'asset_scale': float(p.get('asset_scale',1.)),
            'yaw_degrees': float(p.get('yaw_degrees',0.)),
            'offset_game': list(p.get('offset_game',[0.,0.,0.])),
            'note': p.get('note',''),
            'accepted_for_runtime': False,
        })
    return {
        'format': FORMAT, 'version': VERSION, 'asset': v22['asset'],
        'source_sha256': v22['source_sha256'],
        'source_vertex_count': v22['source_vertex_count'],
        'source_face_count': v22['source_face_count'],
        'source': 'V22_FOLIAGE_AND_V19_VIEW_PROXY',
        'coordinate_basis': 'GAME_Y_UP_LEFT_HANDED',
        'not_game_runtime_certified': True, 'publish_enabled': False,
        'counts': {'trees':len(trees), 'with_trunk':sum(bool(t['trunk_faces']) for t in trees),
                   'leaves_only':sum(not t['trunk_faces'] for t in trees)},
        'trees': trees,
    }


def check_tree_plan(doc: dict, *, asset: str, source_sha256: str,
                    vertex_count: int, face_count: int):
    if doc.get('format') != FORMAT or doc.get('version') != VERSION:
        raise ValueError('V23_FORMAT_MISMATCH')
    if doc.get('asset') != asset or doc.get('source_sha256') != source_sha256:
        raise ValueError('V23_SOURCE_MISMATCH')
    if doc.get('source_vertex_count') != vertex_count or doc.get('source_face_count') != face_count:
        raise ValueError('V23_TOPOLOGY_MISMATCH')
    if not doc.get('not_game_runtime_certified') or doc.get('publish_enabled'):
        raise ValueError('V23_PUBLICATION_FORBIDDEN')
    if len(doc.get('trees', [])) > MAX_TREES:
        raise ValueError('V23_TOO_MANY_TREES')
    ids = set()
    for t in doc.get('trees', []):
        if t['id'] in ids:
            raise ValueError('V23_DUPLICATE_TREE')
        ids.add(t['id'])
        if t.get('status') not in STATE or t.get('category') != 'ARVORE':
            raise ValueError('V23_BAD_TREE_STATUS')
        if t.get('accepted_for_runtime'):
            raise ValueError('V23_RUNTIME_FORBIDDEN')
        if sorted(set(t['faces'])) != t['faces'] or any(not isinstance(i,int) or not 0 <= i < face_count for i in t['faces']):
            raise ValueError('V23_INVALID_TREE_FACES')
        if sorted(set(t['trunk_faces'])) != t['trunk_faces'] or not set(t['trunk_faces']) <= set(t['faces']):
            raise ValueError('V23_INVALID_TRUNK_FACES')
        if not all(math.isfinite(float(x)) for x in (*t['anchor_view'], *t['anchor_game'])):
            raise ValueError('V23_INVALID_ANCHOR')


def preserve_tree_review(new: dict, old: dict) -> dict:
    if new.get('asset') != old.get('asset') or new.get('source_sha256') != old.get('source_sha256'):
        raise ValueError('V23_REVIEW_SOURCE_MISMATCH')
    earlier = {t['id']:t for t in old.get('trees',[])}
    for t in new['trees']:
        prev = earlier.get(t['id'])
        if prev is None:
            continue
        for key in ('status','note','asset_scale','yaw_degrees','offset_game'):
            if key in prev:
                t[key] = prev[key]
    return new


def tree_plan_path(v22_json_path: Path) -> Path:
    return Path(v22_json_path).with_name(Path(v22_json_path).name.replace('.v22_proposals.json','.v23_trees.json'))
