"""V21: source-locked Stage072 semantic labels; pure Python, no Blender dependency.

Everything exported is a PROPOSAL, never a rebuilt SMD or approved game placement.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

FORMAT = 'PT_ETERVALE_STAGE072_SEMANTIC_V21'
VERSION = 1
CATEGORIES = (
    'ARVORE', 'ARBUSTO', 'FOGO', 'PEDRA', 'SOLO', 'PAREDE',
    'EDIFICIO', 'AGUA', 'OUTRO', 'POSSIVEL_COLISAO',
)
COLORS = {
    'ARVORE': (0.15, 0.8, 0.25), 'ARBUSTO': (0.55, 0.9, 0.12),
    'FOGO': (1.0, 0.32, 0.04), 'PEDRA': (0.58, 0.58, 0.62),
    'SOLO': (0.55, 0.37, 0.18), 'PAREDE': (0.32, 0.55, 0.9),
    'EDIFICIO': (0.9, 0.75, 0.27), 'AGUA': (0.14, 0.72, 0.95),
    'OUTRO': (0.7, 0.35, 0.88), 'POSSIVEL_COLISAO': (1.0, 0.1, 0.65),
}
# Conservative hints. A material name is never proof of placement/collision.
_RULES = (
    ('POSSIVEL_COLISAO', re.compile(r'(?:^|[_\\/\-.])(?:collision|colisao|nowalk|no_walk|invisiblewall)(?:[_\\/\-.]|$)', re.I)),
    ('FOGO', re.compile(r'(?:^|[_\\/\-.])(?:flame|fire|fogo|chama|torch|tocha)(?:[_\\/\-.]|\d|$)', re.I)),
    ('ARVORE', re.compile(r'(?:^|[_\\/\-.])(?:leaf|leaves|folha|folhas|tree|arvore|foliage)(?:[_\\/\-.]|\d|$)', re.I)),
    ('ARBUSTO', re.compile(r'(?:^|[_\\/\-.])(?:bush|shrub|arbusto|grass|grama|gramina)(?:[_\\/\-.]|\d|$)', re.I)),
    ('PEDRA', re.compile(r'(?:^|[_\\/\-.])(?:rock|stone|pedra|rocha)(?:[_\\/\-.]|\d|$)', re.I)),
    ('AGUA', re.compile(r'(?:^|[_\\/\-.])(?:water|agua|river|lake)(?:[_\\/\-.]|\d|$)', re.I)),
)


def suggest_material(name: str) -> dict[str, str]:
    """Name-only hint; conservative with WALL: don't assume invisible collision."""
    n = str(name)
    for category, rule in _RULES:
        if rule.search(n):
            return {'category': category, 'confidence': 'SUGESTAO_NOME', 'reason': 'keyword_in_material_name'}
    if re.search(r'wall', n, re.I):
        return {'category': 'PAREDE', 'confidence': 'REVER_WALL', 'reason': 'WALL_not_collision_proof'}
    return {'category': 'OUTRO', 'confidence': 'SEM_EVIDENCIA', 'reason': 'no_reliable_keyword'}


def source_to_view(game_xyz: tuple[float, float, float], center_xyz: tuple[float, float, float], scale: float):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('INVALID_VIEW_SCALE')
    return (
        (game_xyz[0] - center_xyz[0]) * scale,
        (game_xyz[2] - center_xyz[2]) * scale,
        (game_xyz[1] - center_xyz[1]) * scale,
    )


def view_to_source(view_xyz: tuple[float, float, float], center_xyz: tuple[float, float, float], scale: float):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('INVALID_VIEW_SCALE')
    return (
        view_xyz[0] / scale + center_xyz[0],
        view_xyz[2] / scale + center_xyz[1],
        view_xyz[1] / scale + center_xyz[2],
    )


def source_anchor_from_view_vertices(view_xyzs, center_xyz, scale):
    """Bottom-center of selected geometry; NOT necessarily a tree's ground contact."""
    pts = list(view_xyzs)
    if not pts:
        raise ValueError('NO_VERTICES_FOR_ANCHOR')
    mn = [min(float(p[i]) for p in pts) for i in range(3)]
    mx = [max(float(p[i]) for p in pts) for i in range(3)]
    a_view = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2])
    anchor = view_to_source(a_view, center_xyz, scale)
    return {
        'view_anchor': [float(x) for x in a_view],
        'game_anchor': [float(x) for x in anchor],
        'view_bounds_min': mn, 'view_bounds_max': mx,
        'method': 'SELECTED_GEOMETRY_BOTTOM_CENTER_NOT_GROUND_CERTIFIED',
    }


def replace_overlapping_faces(regions: list[dict], *, obj_name: str, chosen_faces: list[int],
                              category: str, region_id: str, anchor: dict,
                              material_names: list[str]) -> list[dict]:
    """Keep face ownership exclusive; erasing doesn't invent replacement geometry."""
    chosen = set(int(i) for i in chosen_faces)
    if not chosen or any(x < 0 for x in chosen):
        raise ValueError('INVALID_FACE_SELECTION')
    if category != 'APAGAR' and category not in CATEGORIES:
        raise ValueError('UNKNOWN_CATEGORY')
    next_regions = []
    for old in regions:
        copied = dict(old)
        old_faces = set(int(x) for x in old['faces'])
        if old.get('proxy_object') == obj_name:
            old_faces -= chosen
        if old_faces:
            copied['faces'] = sorted(old_faces)
            # A partially erased region keeps its original anchor as a candidate;
            # it is not recertified as geometrically grounded after the erase.
            if len(old_faces) != len(old['faces']):
                copied['anchor_needs_review'] = True
            next_regions.append(copied)
    if category != 'APAGAR':
        next_regions.append({
            'id': region_id, 'category': category, 'proxy_object': obj_name,
            'faces': sorted(chosen), 'materials': sorted(set(material_names)),
            'anchor': anchor, 'anchor_needs_review': True,
            'offset_game': [0., 0., 0.], 'yaw_degrees': 0., 'asset_scale': 1.,
            'replacement_asset': '', 'note': '', 'accepted_for_runtime': False,
        })
    return next_regions


def check_document(doc: dict, *, asset: str, source_sha256: str, vertex_count: int, face_count: int):
    if doc.get('format') != FORMAT or doc.get('version') != VERSION:
        raise ValueError('INCOMPATIBLE_ANNOTATION_FORMAT')
    if doc.get('asset') != asset or doc.get('source_sha256') != source_sha256:
        raise ValueError('SOURCE_IDENTITY_MISMATCH')
    if doc.get('source_face_count') != face_count or doc.get('source_vertex_count') != vertex_count:
        raise ValueError('SOURCE_TOPOLOGY_MISMATCH')
    taken = set()
    ids = set()
    for region in doc.get('regions', []):
        if region['id'] in ids:
            raise ValueError('DUPLICATE_REGION_ID')
        ids.add(region['id'])
        if region['category'] not in CATEGORIES:
            raise ValueError('UNKNOWN_REGION_CATEGORY')
        for face in region['faces']:
            if not isinstance(face, int) or face < 0 or face >= face_count:
                raise ValueError('REGION_FACE_OUT_OF_BOUNDS')
            key = (region['proxy_object'], face)
            if key in taken:
                raise ValueError('REGION_FACE_OWNERSHIP_COLLISION')
            taken.add(key)
        if region.get('accepted_for_runtime', False):
            raise ValueError('V21_IS_NOT_RUNTIME_PUBLICATION')


def atomic_write_json(path: Path, document: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.pt_semantic_', suffix='.tmp', delete=False) as f:
            tmp = Path(f.name)
            json.dump(document, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def annotation_path(base: Path, logical: str) -> Path:
    if logical.startswith('/') or '..' in logical.replace('\\', '/').split('/'):
        raise ValueError('UNSAFE_LOGICAL_ASSET')
    token = hashlib.sha256(logical.encode('utf-8')).hexdigest()[:16]
    return Path(base) / 'maps' / f'{token}.json'
