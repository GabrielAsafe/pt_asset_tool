"""V27: source-locked Stage 0.72 texture/connected-component classification.

Every classification is a *proposal*, unless explicitly confirmed for this
particular Stage SHA. Never edits a polygon, its material, UV or an SMD file.
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import re

FORMAT = 'PT_ETERVALE_STAGE072_TEXTURE_COMPONENTS_V27'
ROLES = ('OUTRO', 'SOLO', 'FOLHAGEM', 'ARBUSTO', 'FOGO', 'PEDRA', 'PAREDE', 'AGUA')
MAX_FACES = 250_000
_STAGE_MAT = re.compile(r'^PT_STAGE072_MAT_\d+_(.+)$', re.IGNORECASE)


def texture_identity(material_name: str, image_name: str = '', slot_index: int = 0) -> str:
    """An image basename is stable *within a map*; slot fallback is unique."""
    matched = _STAGE_MAT.match(material_name or '')
    texture = matched.group(1) if matched else ''
    if not texture or texture.upper() in ('NO_TEXTURE', 'NONE'):
        texture = image_name
    texture = texture.replace('\\', '/').rsplit('/', 1)[-1].strip().casefold()
    if texture and texture not in ('no_texture', 'none'):
        return 'tex:' + texture
    return 'slot:%04d:%s' % (slot_index, (material_name or 'unnamed').casefold())


def proposed_role(name: str, *, v22_foliage: bool, up_ratio: float, face_count: int) -> tuple[str, str]:
    """Non-binding suggestions, never treated as a verified semantic rule."""
    s = name.casefold()
    if v22_foliage:
        return 'FOLHAGEM', 'V22_FOLHAGEM_REVISAO_ARVORE_OU_ARBUSTO'
    if any(x in s for x in ('fire', 'flame', 'fogo', 'chama')):
        return 'FOGO', 'PALAVRA_CHAVE_REVISAO'
    if any(x in s for x in ('water', 'agua', 'river', 'lake')):
        return 'AGUA', 'PALAVRA_CHAVE_REVISAO'
    if any(x in s for x in ('leaf', 'leaves', 'foliage', 'folha')):
        return 'FOLHAGEM', 'PALAVRA_CHAVE_REVISAO'
    if any(x in s for x in ('grass', 'soil', 'ground', 'floor', 'road', 'dirt', 'terrain', 'solo')):
        return 'SOLO', 'PALAVRA_CHAVE_REVISAO'
    if up_ratio >= .88 and face_count >= 90:
        return 'SOLO', 'NORMAL_PREDOMINANTEMENTE_VERTICAL_REVISAO_TELHADOS'
    return 'OUTRO', 'SEM_EVIDENCIA'


def build_catalog(*, asset: str, source_sha256: str, source_face_count: int,
                  slots: list[dict], faces: list[dict], v22_material_names=(),
                  previous: dict | None = None) -> dict:
    if not asset or len(source_sha256) != 64 or not re.fullmatch('[0-9a-f]{64}', source_sha256):
        raise ValueError('FONTE_SHA_INVALIDA')
    if not 0 <= source_face_count <= MAX_FACES or len(faces) != source_face_count:
        raise ValueError('CONTAGEM_FACES_INCONSISTENTE')
    if previous is not None:
        check_catalog(previous, asset=asset, sha=source_sha256,
                      face_count=source_face_count)
    slot_index = {}
    for s in slots:
        idx = int(s['index'])
        if idx in slot_index or idx < 0:
            raise ValueError('MATERIAL_SLOT_DUPLICADO')
        slot_index[idx] = {
            'index': idx, 'name': str(s.get('name', '') or ''),
            'texture_key': texture_identity(str(s.get('name', '') or ''),
                                            str(s.get('image', '') or ''), idx),
        }
    face_ids = set()
    by_key = defaultdict(list)
    edge_faces = defaultdict(list)
    for face in faces:
        idx = int(face['index'])
        if not 0 <= idx < source_face_count or idx in face_ids:
            raise ValueError('INDICES_FACES_INVALIDOS')
        face_ids.add(idx)
        slot = slot_index.get(int(face['material_index']))
        if slot is None:
            raise ValueError('MATERIAL_SLOT_AUSENTE')
        vs = tuple(int(v) for v in face['vertices'])
        if len(vs) < 3 or len(set(vs)) < 3 or min(vs) < 0:
            raise ValueError('FACE_VERTICES_INVALIDOS')
        key = slot['texture_key']
        by_key[key].append(face)
        for k in range(len(vs)):
            edge = tuple(sorted((vs[k], vs[(k + 1) % len(vs)])))
            edge_faces[(key, edge)].append(idx)
    if face_ids != set(range(source_face_count)):
        raise ValueError('INDICES_FACES_NAO_CONTIGUOS')
    neighbors = defaultdict(set)
    for collection in edge_faces.values():
        if len(collection) > 1:
            for f in collection:
                neighbors[f].update(i for i in collection if i != f)
    known = {s.casefold() for s in v22_material_names}
    materials = []
    for key in sorted(by_key):
        grouped = by_key[key]
        lookup = {int(f['index']):f for f in grouped}
        remaining = set(lookup)
        components = []
        while remaining:
            first = min(remaining)
            remaining.remove(first)
            todo = deque([first])
            component = []
            while todo:
                cur = todo.popleft()
                component.append(cur)
                for other in neighbors.get(cur, ()):
                    if other in remaining:
                        remaining.remove(other)
                        todo.append(other)
            component.sort()
            total_area = sum(max(0., float(lookup[f].get('area', 0.))) for f in component)
            up_area = sum(max(0., float(lookup[f].get('area', 0.)))
                          for f in component if float(lookup[f].get('normal_z', 0.)) >= .7)
            components.append({'id': f'{key}#{component[0]}', 'faces': component,
                               'face_count': len(component),
                               'up_ratio': round(up_area / total_area, 4) if total_area > 0 else 0.,
                               'area_view': round(total_area, 5)})
        components.sort(key=lambda c: (-c['face_count'], c['faces'][0]))
        named_slots = [s for s in slot_index.values() if s['texture_key'] == key]
        count = len(grouped)
        total_a = sum(max(0., float(f.get('area', 0.))) for f in grouped)
        up_a = sum(max(0., float(f.get('area', 0.))) for f in grouped
                   if float(f.get('normal_z', 0.)) >= .7)
        ratio = up_a / total_a if total_a else 0.
        suggestion, reason = proposed_role(' '.join(s['name'] for s in named_slots),
              v22_foliage=any(s['name'].casefold() in known for s in named_slots),
              up_ratio=ratio, face_count=count)
        materials.append({'key': key, 'name': named_slots[0]['name'],
                          'slots': sorted(s['index'] for s in named_slots),
                          'faces': count, 'component_count': len(components),
                          'up_ratio': round(ratio, 4),
                          'suggestion': suggestion, 'reason': reason,
                          'components': components})
    materials.sort(key=lambda s: (-s['faces'], s['key']))
    old_rules = previous.get('rules', {}) if previous else {}
    doc = {'format': FORMAT, 'version': 1, 'asset': asset,
           'source_sha256': source_sha256, 'source_face_count': source_face_count,
           'coordinate_basis': 'GAME_Y_UP_LEFT_HANDED',
           'proxy_basis': 'BLENDER_Z_UP_VIEW_V19',
           'publish_enabled': False, 'game_assets_modified': False,
           'not_game_runtime_certified': True,
           'rules': {k:v for k,v in old_rules.items() if k in by_key},
           'textures': materials,
           'counts': {'textures': len(materials),
                      'components': sum(m['component_count'] for m in materials),
                      'classified': sum(k in by_key for k in old_rules)}}
    check_catalog(doc, asset=asset, sha=source_sha256, face_count=source_face_count)
    return doc


def check_catalog(doc: dict, *, asset: str, sha: str, face_count: int) -> None:
    if (doc.get('format') != FORMAT or doc.get('source_sha256') != sha or
        doc.get('asset') != asset or doc.get('source_face_count') != face_count or
        doc.get('publish_enabled') is not False or
        doc.get('game_assets_modified') is not False):
        raise ValueError('V27_MAPA_OU_FONTE_INCOMPATIVEL')
    seen = set()
    keys = set()
    for material in doc.get('textures', []):
        key = material['key']
        if key in keys:
            raise ValueError('V27_CHAVE_DUPLICADA')
        keys.add(key)
        all_faces = set()
        for component in material['components']:
            nums = component['faces']
            if len(nums) != len(set(nums)) or len(nums) != component['face_count']:
                raise ValueError('V27_COMPONENTE_INCONSISTENTE')
            if any(not isinstance(n, int) or n < 0 or n >= face_count for n in nums):
                raise ValueError('V27_FACE_FORA_MAPA')
            if seen.intersection(nums):
                raise ValueError('V27_FACE_DUPLICADA')
            seen.update(nums)
            all_faces.update(nums)
        if len(all_faces) != material['faces'] or material['component_count'] != len(material['components']):
            raise ValueError('V27_MATERIAL_INCONSISTENTE')
    if len(seen) != face_count:
        raise ValueError('V27_FACES_SEM_COBERTURA')
    for key, rule in doc.get('rules', {}).items():
        if key not in keys or rule.get('category') not in ROLES or rule.get('confirmed') is not True:
            raise ValueError('V27_REGRA_INVALIDA')


def assign_rule(doc: dict, key: str, category: str, note: str = '') -> dict:
    if key not in {m['key'] for m in doc['textures']}:
        raise ValueError('V27_TEXTURE_NAO_EXISTE_NESTE_MAPA')
    if category not in ROLES:
        raise ValueError('V27_CATEGORIA_INVALIDA')
    import copy
    updated = copy.deepcopy(doc)
    updated['rules'][key] = {'category': category, 'confirmed': True,
                              'scope': 'THIS_STAGE_SHA_ONLY', 'note': note[:250]}
    updated['counts']['classified'] = len(updated['rules'])
    return updated


def remove_rule(doc: dict, key: str) -> dict:
    import copy
    updated = copy.deepcopy(doc)
    updated['rules'].pop(key, None)
    updated['counts']['classified'] = len(updated['rules'])
    return updated
