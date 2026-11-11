"""V31: review-only face expansion for residual Stage072 vegetation.

Does not edit SMDs, classify a whole texture implicitly, or approve publication.
All indices refer to the single V19 proxy, tied to its original Stage SHA.
"""
from __future__ import annotations
from collections import defaultdict, deque
from datetime import datetime, timezone
import math

FORMAT = 'PT_ETERVALE_ENVIRONMENT_RESIDUAL_V31'
MODES = ('ILHA_MATERIAL', 'ARVORE_LOCAL', 'MATERIAL_TODO', 'FOLHAGEM_TODA')
MAX_SELECT = 12000
MAX_SAVED = 45000


def face_neighbors(face_vertices):
    """Build edge neighbors, preserving topological islands despite texture reuse."""
    edges = defaultdict(list)
    for i, vs in enumerate(face_vertices):
        if len(vs) < 3 or len(set(vs)) < 3:
            raise ValueError('V31_FACE_DEGENERADA')
        for j in range(len(vs)):
            a, b = vs[j], vs[(j+1) % len(vs)]
            edges[(min(a, b), max(a, b))].append(i)
    n = [set() for _ in face_vertices]
    for peers in edges.values():
        if len(peers) > 1:
            for f in peers:
                n[f].update(p for p in peers if p != f)
    return n


def expand(seed, mode, *, face_vertices, face_keys, face_centers,
           hidden=(), foliage_keys=(), radius=3.0, maximum=MAX_SELECT):
    if mode not in MODES:
        raise ValueError('V31_MODO_INVALIDO')
    count = len(face_keys)
    if not (0 <= seed < count and len(face_vertices) == count and len(face_centers) == count):
        raise ValueError('V31_SEMENTE_OU_MALHA_INVALIDA')
    blocked = set(hidden)
    if any(type(i) is not int or not 0 <= i < count for i in blocked):
        raise ValueError('V31_MASCARA_INVALIDA')
    if seed in blocked:
        raise ValueError('V31_FACE_JA_SUBSTITUIDA')
    if type(radius) not in (int, float) or not math.isfinite(radius) or not .15 <= radius <= 12:
        raise ValueError('V31_RAIO_INVALIDO')
    key = face_keys[seed]
    if not key:
        raise ValueError('V31_SEMENTE_SEM_MATERIAL')
    foliage = set(foliage_keys)
    if mode == 'ILHA_MATERIAL':
        neighbors = face_neighbors(face_vertices)
        found = {seed}
        todo = deque([seed])
        while todo:
            current = todo.popleft()
            for other in neighbors[current]:
                if other not in blocked and other not in found and face_keys[other] == key:
                    found.add(other)
                    todo.append(other)
                    if len(found) > maximum:
                        raise ValueError('V31_SELECAO_ACIMA_LIMITE')
    elif mode == 'MATERIAL_TODO':
        found = {i for i, k in enumerate(face_keys) if k == key and i not in blocked}
    elif mode == 'FOLHAGEM_TODA':
        if key not in foliage:
            raise ValueError('V31_NAO_E_MATERIAL_FOLHAGEM_CONFIRMADO_OU_V22')
        found = {i for i, k in enumerate(face_keys) if k in foliage and i not in blocked}
    else:
        # Planar proximity, with vertical tolerance, handles disconnected leaf
        # cards without flooding an entire forest that shares leaf textures.
        if key not in foliage:
            foliage = {key}  # Restrict unrecognized textures to seed texture.
        sx, sy, sz = face_centers[seed]
        if any(not math.isfinite(v) for v in (sx, sy, sz)):
            raise ValueError('V31_CENTRO_INVALIDO')
        found = set()
        for i, center in enumerate(face_centers):
            if i in blocked or face_keys[i] not in foliage:
                continue
            x, y, z = center
            if (x - sx)**2 + (y - sy)**2 <= radius**2 and abs(z - sz) <= max(2., radius*1.7):
                found.add(i)
        found.add(seed)
    if len(found) > maximum:
        raise ValueError(f'V31_SELECAO_ACIMA_LIMITE:{len(found)}/{maximum}')
    return sorted(found)


def blank(asset, sha, face_count):
    return {'format':FORMAT, 'version':1, 'asset':asset,
            'source_sha256':sha, 'source_face_count':face_count,
            'extra_faces':[], 'selections':[], 'publish_enabled':False,
            'game_assets_modified':False, 'runtime_certified':False}


def check_state(doc, *, asset, sha, face_count):
    if (doc.get('format') != FORMAT or doc.get('version') != 1 or
        doc.get('asset') != asset or doc.get('source_sha256') != sha or
        doc.get('source_face_count') != face_count or
        doc.get('publish_enabled') is not False or doc.get('game_assets_modified') is not False or
        doc.get('runtime_certified') is not False):
        raise ValueError('V31_FONTE_OU_ESTADO_INVALIDO')
    used = doc.get('extra_faces')
    if not isinstance(used, list) or len(used) > MAX_SAVED or len(set(used)) != len(used) or any(type(i) is not int or not 0 <= i < face_count for i in used):
        raise ValueError('V31_INDICES_PERSISTIDOS_INVALIDOS')
    selections = doc.get('selections')
    if not isinstance(selections, list) or len(selections) > 1000:
        raise ValueError('V31_SELECOES_INVALIDAS')
    for selected in selections:
        if (not isinstance(selected, dict) or selected.get('mode') not in MODES or
            type(selected.get('seed')) is not int or not 0 <= selected['seed'] < face_count or
            type(selected.get('count')) is not int or selected['count'] < 1):
            raise ValueError('V31_REGISTO_INVALIDO')
    return doc


def accept(doc, selected, *, seed, mode, material_key, asset, sha, face_count):
    check_state(doc, asset=asset, sha=sha, face_count=face_count)
    if mode not in MODES or type(seed) is not int or seed not in selected:
        raise ValueError('V31_APROVACAO_INVALIDA')
    indices = set(selected)
    if any(type(i) is not int or not 0 <= i < face_count for i in indices):
        raise ValueError('V31_FACE_FORA_MAPA')
    import copy
    updated = copy.deepcopy(doc)
    previous = set(updated['extra_faces'])
    if not indices - previous:
        raise ValueError('V31_SELECAO_JA_GUARDADA')
    updated['extra_faces'] = sorted(previous | indices)
    updated['selections'].append({'seed':seed,'mode':mode,'material_key':material_key,
                                  'count':len(indices),'saved_utc':datetime.now(timezone.utc).isoformat(),
                                  'review_only':True})
    return check_state(updated, asset=asset, sha=sha, face_count=face_count)
