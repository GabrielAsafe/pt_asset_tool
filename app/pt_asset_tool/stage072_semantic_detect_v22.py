"""V22: conservative, Blender-independent Stage0.72 geometry/object proposals.

Input is geometry in *view/proxy world space* (Z up).  A stage SMD is Y-up.
The algorithm never asserts collision, rewrites meshes or publishes game assets.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from pt_asset_tool.stage072_semantic_core import (
    CATEGORIES, atomic_write_json, suggest_material, view_to_source,
)

FORMAT = 'PT_ETERVALE_STAGE072_OBJECT_PROPOSALS_V22'
VERSION = 1
STATUSES = ('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_REVIEW')
LABELS = ('ARVORE', 'ARBUSTO', 'PEDRA', 'FOGO')

# These are safety ceilings, not geometry model definitions.
MAX_FACES = 250_000
MAX_CANDIDATES = 240
PROHIBITED_NAME_PARTS = ('wall', 'city', 'floor', 'roof', 'door', 'building', 'house', 'bridge', 'road', 'ground', 'collision', 'nowalk')


@dataclass(frozen=True)
class Face:
    index: int
    material: str
    center: tuple[float, float, float]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    normal_z: float
    area: float
    proxy_object: str = 'PT_STAGE072_VIEW_STAGE'

    def __post_init__(self):
        if self.index < 0 or not all(math.isfinite(float(v)) for v in
                                  (*self.center, *self.bounds_min, *self.bounds_max,
                                   self.normal_z, self.area)):
            raise ValueError('INVALID_FACE_GEOMETRY')


def manual_material_evidence(regions: list[dict]) -> dict[str, dict]:
    """Weak hints from V21: tiny/ambiguous strokes do not train the detector."""
    rows = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in regions:
        cat = r.get('category')
        n = len(r.get('faces', []))
        if cat not in LABELS or n < 4 or n > 1000:
            continue
        for name in set(r.get('materials', [])):
            low = name.lower()
            if any(token in low for token in PROHIBITED_NAME_PARTS):
                continue
            rows[name][cat][0] += 1
            rows[name][cat][1] += n
    out = {}
    for name, cats in rows.items():
        wins = sorted(cats.items(), key=lambda x: (x[1][0], x[1][1]), reverse=True)
        cat, (marks, count) = wins[0]
        total_marks = sum(x[0] for x in cats.values())
        if marks >= 3 and count >= 48 and marks / total_marks >= .8:
            out[name] = {'category': cat, 'kind': 'V21_WEAK_LABEL',
                         'marks': marks, 'marked_faces': count}
    return out


def _material_category(name: str, learned: dict[str, dict]):
    hint = suggest_material(name)
    if hint['category'] in LABELS and hint['confidence'] == 'SUGESTAO_NOME':
        return hint['category'], 'EXPLICIT_MATERIAL_KEYWORD'
    if name in learned:
        return learned[name]['category'], 'V21_WEAK_LABEL'
    return None, None


class _Ground:
    """Lowest locally observed upward-facing surface, not collision proof."""

    def __init__(self, faces: list[Face], cell_size: float = 2.0):
        self.s = cell_size
        bucket = defaultdict(list)
        for f in faces:
            if f.normal_z >= 0.80 and f.area > 0.015 and not any(x in f.material.lower() for x in ('leaf', 'folha', 'flame', 'fire')):
                i, j = math.floor(f.center[0]/self.s), math.floor(f.center[1]/self.s)
                bucket[i, j].append(f.center[2])
        # Select a low quantile, not absolute minimum which can be a hidden face.
        self.tiles = {}
        for key, vals in bucket.items():
            vals.sort()
            self.tiles[key] = vals[max(0, int(len(vals)*.20)-1)]

    def height(self, x: float, y: float):
        i, j = math.floor(x/self.s), math.floor(y/self.s)
        values = [self.tiles[(i+dx, j+dy)] for dx in (-1, 0, 1)
                  for dy in (-1, 0, 1) if (i+dx, j+dy) in self.tiles]
        return median(values) if values else None


def _clusters(faces: list[Face], *, link_radius: float, max_diameter: float):
    """XY proximity groups, with a *diameter cap* to prevent joining forests.

    Repeated leaf cards aren't necessarily connected in the SMD, so topology-only
    connected components are insufficient. Every group has a fixed horizontal
    bounding envelope rather than unrestricted DBSCAN chaining.
    """
    if not faces:
        return []
    cell = link_radius
    cells = defaultdict(list)
    for i, f in enumerate(faces):
        cells[math.floor(f.center[0]/cell), math.floor(f.center[1]/cell)].append(i)
    remaining = set(range(len(faces)))
    result = []
    while remaining:
        # Stable behavior irrespective of hash randomization.
        start = min(remaining, key=lambda k: (round(faces[k].center[0], 5), round(faces[k].center[1], 5), faces[k].index))
        origin = faces[start].center
        queue = [start]
        remaining.remove(start)
        selected = []
        while queue:
            ix = queue.pop()
            face = faces[ix]
            selected.append(face)
            cx, cy = math.floor(face.center[0]/cell), math.floor(face.center[1]/cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for iy in cells.get((cx+dx,cy+dy), ()):
                        if iy not in remaining:
                            continue
                        other = faces[iy]
                        if math.dist(other.center[:2], face.center[:2]) > link_radius:
                            continue
                        if math.dist(other.center[:2], origin[:2]) > max_diameter/2:
                            continue
                        # Do not grow a single candidate through unrelated levels.
                        if abs(other.center[2]-face.center[2]) > max(2.0, max_diameter):
                            continue
                        remaining.remove(iy)
                        queue.append(iy)
        result.append(selected)
    return result


def build_candidates(*, asset: str, source_sha256: str, faces: list[Face],
                     manual_regions: list[dict], center_xyz: tuple[float, float, float],
                     view_scale: float, radius: float = 1.5, max_candidates: int = MAX_CANDIDATES):
    if len(faces) > MAX_FACES:
        raise ValueError('TOO_MANY_FACES_FOR_V22_PILOT')
    if not (0.4 <= radius <= 4.0):
        raise ValueError('INVALID_CLUSTER_RADIUS')
    if not (1 <= max_candidates <= MAX_CANDIDATES):
        raise ValueError('INVALID_CANDIDATE_LIMIT')
    if not len(source_sha256) == 64:
        raise ValueError('SOURCE_SHA_REQUIRED')
    ground = _Ground(faces)
    learned = manual_material_evidence(manual_regions)
    by_category = defaultdict(list)
    hint_counts = Counter()
    for face in faces:
        cat, ev = _material_category(face.material, learned)
        if cat is None:
            continue
        if cat in ('ARVORE', 'ARBUSTO'):
            # In trees/bushes, textured cards should not merely describe a
            # horizontal road or roof with a mistakenly labeled material.
            local_ground = ground.height(*face.center[:2])
            elevated = local_ground is not None and face.bounds_max[2] > local_ground + .35
            not_flat = abs(face.normal_z) < .82
            if not (not_flat or elevated):
                continue
        by_category[cat].append(face)
        hint_counts[ev] += 1

    candidates = []
    min_count = {'ARVORE': 5, 'ARBUSTO': 3, 'PEDRA': 4, 'FOGO': 2}
    for cat in LABELS:
        for cluster in _clusters(by_category.get(cat, []), link_radius=radius,
                                 max_diameter=max(4.0, radius*4.0)):
            if len(cluster) < min_count[cat]:
                continue
            bmin = [min(f.bounds_min[k] for f in cluster) for k in range(3)]
            bmax = [max(f.bounds_max[k] for f in cluster) for k in range(3)]
            width = max(bmax[0]-bmin[0], bmax[1]-bmin[1])
            height = bmax[2]-bmin[2]
            if width <= .07 or height <= .02:
                continue
            if cat == 'ARVORE' and (height < 1.0 or height < width*.35):
                continue
            if cat == 'ARBUSTO' and (height > width*2.4 or height < .08):
                continue
            if cat == 'PEDRA' and height > width*3:
                continue
            # Fire can use almost planar quads, but label only explicit names
            # or known manually inspected materials.
            cx, cy = (bmin[0]+bmax[0])/2, (bmin[1]+bmax[1])/2
            g = ground.height(cx, cy)
            bottom = bmin[2]
            if g is None:
                anchor_z = bottom
                ground_state = 'GROUND_NOT_FOUND'
            elif abs(bottom-g) > 2.5:
                anchor_z = bottom
                ground_state = 'GROUND_AMBIGUOUS'
            else:
                anchor_z = g
                ground_state = 'LOCAL_GROUND_ESTIMATE_NOT_CERTIFIED'
            anchor_view = [cx, cy, anchor_z]
            anchor_game = list(view_to_source(anchor_view, center_xyz, view_scale))
            mats = sorted(set(f.material for f in cluster))
            evidence = sorted(set(_material_category(n, learned)[1] for n in mats))
            if 'V21_WEAK_LABEL' in evidence:
                confidence = 'LOW_REVIEW_REQUIRED'
            elif ground_state != 'LOCAL_GROUND_ESTIMATE_NOT_CERTIFIED':
                confidence = 'LOW_GROUND_UNCERTAIN'
            else:
                confidence = 'MEDIUM_GEOMETRY_AND_MATERIAL'
            if width > max(6.0, radius*5):
                confidence = 'LOW_GROUP_TOO_WIDE'
            indices = sorted(f.index for f in cluster)
            objnames = set(f.proxy_object for f in cluster)
            if len(objnames) != 1:
                continue
            objname = next(iter(objnames))
            token = hashlib.sha256(f'{source_sha256}|{cat}|{objname}|{indices}'.encode()).hexdigest()[:14]
            candidates.append({
                'id': token, 'category': cat, 'status': 'PENDING',
                'confidence': confidence, 'evidence': evidence,
                'proxy_object': objname, 'faces': indices,
                'materials': mats, 'face_count': len(indices),
                'view_bounds_min': bmin, 'view_bounds_max': bmax,
                'view_anchor': anchor_view, 'game_anchor': anchor_game,
                'ground_status': ground_state, 'ground_height_view': g,
                'width_view': width, 'height_view': height,
                'offset_game': [0., 0., 0.], 'asset_scale': 1., 'yaw_degrees': 0.,
                'note': '', 'replacement_asset': '',
                'accepted_for_runtime': False,
            })
    # Heaviest candidates first to aid user review. Truncate with explicit count.
    candidates.sort(key=lambda c: (-c['face_count'], c['category'], c['id']))
    total = len(candidates)
    candidates = candidates[:max_candidates]
    return {
        'format': FORMAT, 'version': VERSION, 'asset': asset,
        'source_sha256': source_sha256,
        'coordinate_basis': 'GAME_Y_UP_LEFT_HANDED',
        'proxy_basis': 'BLENDER_Z_UP_VIEW_V19',
        'not_game_runtime_certified': True, 'publish_enabled': False,
        'source_face_count': len(faces),
        'source_vertex_count': None,  # inserted by integration before saving
        'classifier': 'V22_GEOMETRY_TERRAIN_MATERIAL_CONSERVATIVE',
        'config': {'cluster_radius_view': radius, 'max_candidates': max_candidates},
        'counts': {'geometry_faces_inspected': len(faces),
                   'material_faces_considered': sum(map(len, by_category.values())),
                   'ground_cells': len(ground.tiles),
                   'candidate_count_before_limit': total,
                   'truncated': total > max_candidates,
                   'learned_materials': len(learned)},
        'candidates': candidates,
    }


def check_proposals(doc: dict, *, asset: str, source_sha256: str,
                    vertex_count: int, face_count: int):
    if doc.get('format') != FORMAT or doc.get('version') != VERSION:
        raise ValueError('V22_FORMAT_MISMATCH')
    if doc.get('asset') != asset or doc.get('source_sha256') != source_sha256:
        raise ValueError('V22_SOURCE_MISMATCH')
    if doc.get('source_vertex_count') != vertex_count or doc.get('source_face_count') != face_count:
        raise ValueError('V22_TOPOLOGY_MISMATCH')
    if doc.get('publish_enabled') or not doc.get('not_game_runtime_certified'):
        raise ValueError('V22_NO_RUNTIME_PUBLICATION')
    ids = set()
    for p in doc.get('candidates', []):
        if p['id'] in ids:
            raise ValueError('V22_DUPLICATE_PROPOSAL')
        ids.add(p['id'])
        if p['status'] not in STATUSES or p['category'] not in LABELS:
            raise ValueError('V22_INVALID_CLASSIFICATION')
        if p.get('accepted_for_runtime'):
            raise ValueError('V22_RUNTIME_PUBLICATION_FORBIDDEN')
        if any(not isinstance(f, int) or not 0 <= f < face_count for f in p['faces']):
            raise ValueError('V22_FACE_OUT_OF_RANGE')
        if sorted(set(p['faces'])) != p['faces']:
            raise ValueError('V22_INVALID_FACE_LIST')


def preserve_review_decisions(new: dict, old: dict):
    """Carry review labels only when proposal identity or near-exact face overlap holds."""
    existing = old.get('candidates', [])
    old_by_id = {c['id']: c for c in existing}
    for n in new['candidates']:
        old_c = old_by_id.get(n['id'])
        if old_c is None:
            ns = set(n['faces'])
            best = 0.0
            for p in existing:
                if p['category'] != n['category'] or p['proxy_object'] != n['proxy_object']:
                    continue
                ps = set(p['faces'])
                overlap = len(ns & ps) / max(len(ns | ps), 1)
                if overlap >= .90 and overlap > best:
                    best, old_c = overlap, p
        if old_c is not None:
            for key in ('status','category','note','offset_game','replacement_asset','asset_scale','yaw_degrees'):
                if key in old_c:
                    n[key] = old_c[key]
    return new


def proposals_path(annotation: Path):
    return annotation.with_name(annotation.stem + '.v22_proposals.json')
