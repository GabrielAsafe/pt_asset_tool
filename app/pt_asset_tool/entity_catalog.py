from __future__ import annotations

import hashlib
import json
import pathlib
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

SEED_REL = pathlib.Path('data/reference/entity_catalog/monster_npc_entities_v1.json')
ENTITY_CATEGORIES = {'MONSTER', 'NPC', 'CHARACTER', 'ITEM', 'EFFECT', 'MAP_FIELD'}

PLAYABLE_CLASSES = (
    'Mechanician', 'Fighter', 'Pikeman', 'Archer', 'Knight',
    'Atalanta', 'Priestess', 'Magician', 'Assassin', 'Shaman',
)
_CLASS_ALIASES = {x.casefold(): x for x in PLAYABLE_CLASSES}
_CLASS_ALIASES['assassine'] = 'Assassin'
# These config families mirror the source-proven class config contract in
# player_class_motion_contract.py. They classify config identity, not arbitrary
# model/texture filename prefixes such as mfbB/mfhB.
_CLASS_CONFIG_PATTERNS = {
    'Mechanician': (re.compile(r'^a\d+$', re.I), re.compile(r'^ca\d+$', re.I)),
    'Fighter': (re.compile(r'^b\d+$', re.I), re.compile(r'^cb\d+$', re.I)),
    'Pikeman': (re.compile(r'^c\d+$', re.I), re.compile(r'^cc\d+$', re.I)),
    'Archer': (re.compile(r'^d\d+$', re.I), re.compile(r'^cd\d+$', re.I)),
    'Knight': (re.compile(r'^ma\d+$', re.I), re.compile(r'^cma\d+$', re.I)),
    'Atalanta': (re.compile(r'^mb\d+$', re.I), re.compile(r'^cmb\d+$', re.I)),
    'Priestess': (re.compile(r'^mc\d+$', re.I), re.compile(r'^cmc\d+$', re.I)),
    'Magician': (re.compile(r'^md\d+$', re.I), re.compile(r'^cmd\d+$', re.I)),
    'Assassin': (re.compile(r'^e\d+$', re.I), re.compile(r'^ce\d+$', re.I)),
    'Shaman': (re.compile(r'^me\d+$', re.I), re.compile(r'^cme\d+$', re.I)),
}


def load_entity_seed(project_root: pathlib.Path) -> dict[str, Any]:
    path = project_root / SEED_REL
    if not path.is_file():
        return {
            'format': 'PT_ENTITY_CATALOG_SEED_V1',
            'status': 'MISSING',
            'entity_count': 0,
            'monster_count': 0,
            'npc_count': 0,
            'entities': [],
        }
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('entities'), list):
        raise ValueError('ENTITY_CATALOG_SEED_INVALID')
    return data


def _norm(path: str) -> str:
    return str(path or '').replace('\\', '/').strip('/')


def _preview_score(entity_name: str, row: dict[str, Any]) -> tuple[int, str]:
    path = str(row.get('path') or '')
    stem = pathlib.PurePosixPath(path).stem.lower()
    n = entity_name.lower()
    score = 0
    if stem == n:
        score = 100
    elif stem in {f'{n}-up', f'{n}_up', f'{n}-body', f'{n}_body'}:
        score = 90
    elif stem.startswith(n):
        score = 80
    elif 'body' in stem:
        score = 60
    elif 'head' in stem or stem.endswith('h'):
        score = 50
    if row.get('previewable'):
        score += 5
    return -score, path.lower()


def _class_from_path_component(path: str) -> str | None:
    for part in pathlib.PurePosixPath(_norm(path)).parts:
        hit = _CLASS_ALIASES.get(part.casefold())
        if hit:
            return hit
    return None


def _class_from_config_path(path: str) -> str | None:
    stem = pathlib.PurePosixPath(_norm(path)).stem
    hits = [name for name, pats in _CLASS_CONFIG_PATTERNS.items() if any(rx.fullmatch(stem) for rx in pats)]
    return hits[0] if len(hits) == 1 else None


def _binding_context(asset: Any) -> tuple[str, tuple[str, ...]] | None:
    skeleton = _norm(getattr(asset, 'binding_skeleton_smb', '')).casefold()
    roots = sorted({
        _norm(c.get('motion_inx')).casefold()
        for c in (getattr(asset, 'configs', []) or [])
        if isinstance(c, dict) and c.get('motion_inx')
    })
    if not skeleton and not roots:
        return None
    return skeleton, tuple(roots)


def _direct_character_class(asset: Any) -> tuple[str | None, str | None]:
    hits: set[str] = set()
    path_class = _class_from_path_component(getattr(asset, 'primary_path', ''))
    if path_class:
        hits.add(path_class)
    for cfg in getattr(asset, 'configs', []) or []:
        if not isinstance(cfg, dict):
            continue
        for key in ('inx', 'motion_inx'):
            value = cfg.get(key)
            if not value:
                continue
            exact = _class_from_path_component(str(value))
            source_cfg = _class_from_config_path(str(value))
            if exact:
                hits.add(exact)
            if source_cfg:
                hits.add(source_cfg)
    if len(hits) != 1:
        return None, None
    evidence = 'EXACT_CANONICAL_CLASS_PATH_COMPONENT' if path_class in hits else 'SOURCE_PROVEN_CLASS_CONFIG_FAMILY'
    return next(iter(hits)), evidence


def _physical_entity_descriptor(path: str, category: str, folder: str = '', folder_path: str = '') -> dict[str, str] | None:
    path = _norm(path)
    cat = str(category or '').upper()
    if cat == 'MAP':
        cat = 'MAP_FIELD'
    if cat in {'MONSTER', 'NPC'}:
        # A MONSTER/NPC category on audio/UI support does not establish entity
        # identity. Only the canonical actor trees do; registry relations can
        # still attach support files from elsewhere to those entities later.
        parts = pathlib.PurePosixPath(path).parts
        expected = 'monster' if cat == 'MONSTER' else 'npc'
        if len(parts) < 3 or parts[0].casefold() != 'char' or parts[1].casefold() != expected:
            return None
        root = '/'.join(parts[:3])
        name = parts[2]
        return {
            'entity_key': f'{cat}|{root.casefold()}',
            'semantic_group': cat,
            'display_name': name,
            'folder_root': root,
            'identity_evidence': 'CANONICAL_ACTOR_FOLDER',
        }
    if cat in {'EFFECT', 'MAP_FIELD'}:
        root = _norm(folder_path)
        name = str(folder or '')
        if not root or not name or name == '(raiz)':
            parent = pathlib.PurePosixPath(path).parent
            if parent.as_posix() in {'.', ''}:
                return None
            root = parent.as_posix()
            name = parent.name
        return {
            'entity_key': f'{cat}|{root.casefold()}',
            'semantic_group': cat,
            'display_name': name,
            'folder_root': root,
            'identity_evidence': 'LIVE_PHYSICAL_FOLDER',
        }
    if cat == 'ITEM':
        stem = pathlib.PurePosixPath(path).stem
        if not stem:
            return None
        return {
            'entity_key': f'ITEM|model:{stem.casefold()}',
            'semantic_group': 'ITEM',
            'display_name': stem,
            'folder_root': pathlib.PurePosixPath(path).parent.as_posix(),
            'identity_evidence': 'ITEM_MODEL_CODE',
        }
    return None


def _registry_descriptors(registry) -> dict[str, dict[str, str]]:
    assets = list(getattr(registry, 'assets', []) or [])
    direct_classes: dict[str, tuple[str, str]] = {}
    context_classes: dict[tuple[str, tuple[str, ...]], set[str]] = defaultdict(set)
    for asset in assets:
        if str(getattr(asset, 'category', '') or '').upper() != 'CHARACTER':
            continue
        cls, evidence = _direct_character_class(asset)
        if cls:
            direct_classes[str(getattr(asset, 'asset_id', id(asset)))] = (cls, evidence or 'SOURCE_PROVEN_CLASS_CONFIG_FAMILY')
            ctx = _binding_context(asset)
            if ctx:
                context_classes[ctx].add(cls)

    out: dict[str, dict[str, str]] = {}
    for asset in assets:
        cat = str(getattr(asset, 'category', '') or '').upper()
        path = _norm(getattr(asset, 'primary_path', ''))
        parts = pathlib.PurePosixPath(path).parts
        if not cat and len(parts) >= 3 and parts[0].casefold() == 'char':
            if parts[1].casefold() == 'npc':
                cat = 'NPC'
            elif parts[1].casefold() == 'monster':
                cat = 'MONSTER'
        desc = None
        if cat == 'CHARACTER':
            pair = direct_classes.get(str(getattr(asset, 'asset_id', id(asset))))
            evidence = pair[1] if pair else None
            cls = pair[0] if pair else None
            if not cls:
                ctx = _binding_context(asset)
                classes = context_classes.get(ctx, set()) if ctx else set()
                if len(classes) == 1:
                    cls = next(iter(classes))
                    evidence = 'VERIFIED_BINDING_CONTEXT_TO_CLASS'
            if cls:
                desc = {
                    'entity_key': f'CHARACTER|class:{cls.casefold()}',
                    'semantic_group': 'CHARACTER',
                    'display_name': cls,
                    'folder_root': f'CHARACTER/{cls}',
                    'identity_evidence': evidence or 'VERIFIED_CHARACTER_RELATION',
                }
        elif cat in {'MONSTER', 'NPC', 'EFFECT', 'MAP'}:
            parts = pathlib.PurePosixPath(path).parts
            folder = pathlib.PurePosixPath(path).parent.name
            folder_path = pathlib.PurePosixPath(path).parent.as_posix()
            # For known entity trees use the same physical directory identity as
            # CatalogIndex. Effect/map paths still group by their concrete parent.
            if cat in {'MONSTER', 'NPC'} and len(parts) >= 3 and parts[0].casefold() == 'char':
                folder = parts[2]
                folder_path = '/'.join(parts[:3])
            desc = _physical_entity_descriptor(path, cat, folder, folder_path)
        elif cat == 'ITEM' or '/items/dropitem/' in ('/' + path.casefold() + '/'):
            desc = _physical_entity_descriptor(path, 'ITEM')
        if desc:
            out[str(getattr(asset, 'asset_id', id(asset)))] = desc
    return out


def _empty_registry_evidence(meta: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        **(meta or {}),
        'registry_asset_count': 0,
        'registry_family_counts': Counter(),
        'registry_binding_mode_counts': Counter(),
        'rigid_model_count': 0,
        'rigid_binding_ready_count': 0,
        'animation_binding_ready_count': 0,
        'physical_rigid_binding_ready_count': 0,
        'physical_animation_binding_ready_count': 0,
        'binding_skeleton_paths': set(),
        'motion_smb_paths': set(),
        'related_entity_keys': set(),
        'referenced_by_entity_keys': set(),
        'cross_entity_links': [],
        'registry_assets': [],
        'related_asset_paths': set(),
        'model_paths': set(),
        'config_paths': set(),
        'animation_paths': set(),
        'texture_paths': set(),
        'relationships': [],
    }


def _registry_evidence(registry, *, include_assets: bool = False, include_physical: bool = False) -> dict[str, dict[str, Any]]:
    descriptors = _registry_descriptors(registry)
    grouped: dict[str, dict[str, Any]] = {}
    asset_to_key: dict[str, str] = {}

    for asset in getattr(registry, 'assets', []) or []:
        aid = str(getattr(asset, 'asset_id', id(asset)))
        meta = descriptors.get(aid)
        if not meta:
            continue
        key = meta['entity_key']
        asset_to_key[aid] = key
        e = grouped.setdefault(key, _empty_registry_evidence(meta))
        e['registry_asset_count'] += 1
        e['registry_family_counts'][str(getattr(asset, 'family', '') or 'UNKNOWN')] += 1
        e['registry_binding_mode_counts'][str(getattr(asset, 'binding_mode', '') or 'NONE')] += 1
        if getattr(asset, 'family', '') == 'SMD_MODEL_062_RIGID_PHYSIQUE':
            e['rigid_model_count'] += 1
        if bool(getattr(asset, 'rigid_binding_ready', False)):
            e['rigid_binding_ready_count'] += 1
        if bool(getattr(asset, 'animation_binding_ready', False)):
            e['animation_binding_ready_count'] += 1

        model = _norm(getattr(asset, 'primary_path', ''))
        if model:
            e['model_paths'].add(model)
            e['related_asset_paths'].add(model)
        skeleton = _norm(getattr(asset, 'binding_skeleton_smb', ''))
        if skeleton:
            e['binding_skeleton_paths'].add(skeleton)
            e['animation_paths'].add(skeleton)
            e['related_asset_paths'].add(skeleton)
            e['relationships'].append({'type': 'MODEL_USES_SKELETON', 'from': model, 'to': skeleton, 'evidence': 'VERIFIED_REGISTRY_BINDING'})
        for motion in getattr(asset, 'motions', []) or []:
            motion = _norm(motion)
            if motion:
                e['motion_smb_paths'].add(motion)
                e['animation_paths'].add(motion)
                e['related_asset_paths'].add(motion)
        for texture in getattr(asset, 'textures', []) or []:
            texture = _norm(texture)
            if texture:
                e['texture_paths'].add(texture)
                e['related_asset_paths'].add(texture)
                e['relationships'].append({'type': 'MODEL_USES_TEXTURE', 'from': model, 'to': texture, 'evidence': 'SMD_MATERIAL_TEXLINK'})
        config_rows = []
        for c in getattr(asset, 'configs', []) or []:
            if not isinstance(c, dict):
                continue
            for field in ('inx', 'motion_inx'):
                logical = _norm(c.get(field) or '')
                if logical:
                    e['config_paths'].add(logical)
                    e['related_asset_paths'].add(logical)
                    e['relationships'].append({'type': 'MODEL_USES_CONFIG', 'from': model, 'to': logical, 'evidence': 'REGISTRY_CONFIG'})
            config_rows.append({'inx': c.get('inx'), 'motion_inx': c.get('motion_inx'), 'motion_smb': c.get('motion_smb')})

        physical = None
        if include_physical:
            try:
                physical = registry.physical_dependency_status(asset)
            except Exception as exc:
                physical = {'status': 'ERROR', 'error': f'{type(exc).__name__}:{exc}'}
            if physical.get('rigid_binding_ready_physical'):
                e['physical_rigid_binding_ready_count'] += 1
            if physical.get('animation_binding_ready_physical'):
                e['physical_animation_binding_ready_count'] += 1

        if include_assets:
            row = {
                'asset_id': getattr(asset, 'asset_id', None),
                'path': model,
                'family': getattr(asset, 'family', None),
                'kind': getattr(asset, 'kind', None),
                'category': getattr(asset, 'category', None),
                'binding_mode': getattr(asset, 'binding_mode', None),
                'binding_source': getattr(asset, 'binding_source', None),
                'rigid_binding_ready': bool(getattr(asset, 'rigid_binding_ready', False)),
                'animation_binding_ready': bool(getattr(asset, 'animation_binding_ready', False)),
                'binding_skeleton_smb': skeleton or None,
                'motions': list(getattr(asset, 'motions', []) or []),
                'textures': list(getattr(asset, 'textures', []) or []),
                'configs': config_rows,
            }
            if physical is not None:
                row['physical_dependency_status'] = physical
            e['registry_assets'].append(row)

    # Preserve explicit INX cross-folder relationships for Monster/NPC without
    # merging their folder identities.
    for pair in getattr(registry, 'pairing', []) or []:
        if not isinstance(pair, dict):
            continue
        inx = _norm(pair.get('inx') or '')
        model = _norm(pair.get('model_smd') or '')
        motion = _norm(pair.get('motion_smb') or '')
        def mn_key(path: str) -> str | None:
            parts = pathlib.PurePosixPath(path).parts
            if len(parts) < 3 or parts[0].casefold() != 'char' or parts[1].casefold() not in {'npc', 'monster'}:
                return None
            group = 'NPC' if parts[1].casefold() == 'npc' else 'MONSTER'
            return f'{group}|{("/".join(parts[:3])).casefold()}'
        source_key = mn_key(inx)
        target_keys = sorted({x for x in (mn_key(model), mn_key(motion)) if x})
        if not source_key or not target_keys:
            continue
        source = grouped.setdefault(source_key, _empty_registry_evidence({
            'entity_key': source_key,
            'semantic_group': source_key.split('|', 1)[0],
            'display_name': pathlib.PurePosixPath(inx).parts[2],
            'folder_root': '/'.join(pathlib.PurePosixPath(inx).parts[:3]),
            'identity_evidence': 'LIVE_PHYSICAL_FOLDER',
        }))
        for target_key in target_keys:
            if target_key == source_key:
                continue
            source['related_entity_keys'].add(target_key)
            target = grouped.setdefault(target_key, _empty_registry_evidence())
            target['referenced_by_entity_keys'].add(source_key)
        cross_targets = [k for k in target_keys if k != source_key]
        if cross_targets:
            source['cross_entity_links'].append({
                'evidence': 'INX_PHYSICAL_PAIRING',
                'inx': inx or None,
                'model_smd': model or None,
                'motion_smb': motion or None,
                'target_entity_keys': cross_targets,
                'model_resolved': str(pair.get('model_resolved') or '').casefold() == 'true',
                'motion_resolved': str(pair.get('motion_resolved') or '').casefold() == 'true',
            })

    for e in grouped.values():
        e['registry_family_counts'] = dict(sorted(e['registry_family_counts'].items()))
        e['registry_binding_mode_counts'] = dict(sorted(e['registry_binding_mode_counts'].items()))
        for field in ('binding_skeleton_paths', 'motion_smb_paths', 'related_entity_keys', 'referenced_by_entity_keys',
                      'related_asset_paths', 'model_paths', 'config_paths', 'animation_paths', 'texture_paths'):
            e[field] = sorted(e[field], key=str.casefold)
        e['cross_entity_links'] = sorted(e['cross_entity_links'], key=lambda x: (str(x.get('inx') or '').casefold(), str(x.get('model_smd') or '').casefold()))
        # De-duplicate relationship records while preserving deterministic order.
        seen = set()
        rels = []
        for rel in e['relationships']:
            key = (rel.get('type'), str(rel.get('from') or '').casefold(), str(rel.get('to') or '').casefold())
            if key in seen:
                continue
            seen.add(key)
            rels.append(rel)
        e['relationships'] = sorted(rels, key=lambda x: (str(x.get('type')), str(x.get('to') or '').casefold()))
        if include_assets:
            e['registry_assets'] = sorted(e['registry_assets'], key=lambda x: str(x.get('path') or '').casefold())
        else:
            e.pop('registry_assets', None)
    return grouped


def enrich_entities_with_registry(
    entities: Iterable[dict[str, Any]],
    registry,
    *,
    include_assets: bool = False,
    include_physical: bool = False,
) -> list[dict[str, Any]]:
    evidence = _registry_evidence(registry, include_assets=include_assets, include_physical=include_physical)
    out: list[dict[str, Any]] = []
    for entity in entities:
        row = dict(entity)
        ev = evidence.get(str(row.get('entity_key') or ''))
        if ev:
            # Don't replace already aggregated path lists here; merge registry
            # readiness and relationship evidence onto the live entity.
            for key, value in ev.items():
                if key in {'model_paths', 'config_paths', 'animation_paths', 'texture_paths'} and key in row:
                    row[key] = sorted(set(row[key]) | set(value or []), key=str.casefold)
                else:
                    row[key] = value
            row['registry_evidence'] = True
        else:
            row.update({
                'registry_evidence': False,
                'registry_asset_count': 0,
                'registry_family_counts': {},
                'registry_binding_mode_counts': {},
                'rigid_model_count': 0,
                'rigid_binding_ready_count': 0,
                'animation_binding_ready_count': 0,
                'physical_rigid_binding_ready_count': 0,
                'physical_animation_binding_ready_count': 0,
                'binding_skeleton_paths': [],
                'motion_smb_paths': [],
                'related_entity_keys': [],
                'referenced_by_entity_keys': [],
                'cross_entity_links': [],
                'related_asset_paths': [],
                'relationships': [],
            })
            if include_assets:
                row['registry_assets'] = []
        row['runtime_status'] = 'UNPROVEN'
        row['writer_status'] = 'UNAUTHORIZED'
        out.append(row)
    return out


def _new_entity(meta: dict[str, Any], known: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = str(meta['entity_key'])
    return {
        'entity_key': key,
        'semantic_group': meta['semantic_group'],
        'display_name': meta['display_name'],
        'folder_root': meta.get('folder_root') or '',
        'asset_count': 0,
        'total_bytes': 0,
        'role_counts': Counter(),
        'extension_counts': Counter(),
        'model_paths': [],
        'config_paths': [],
        'animation_paths': [],
        'texture_paths': [],
        'icon_paths': [],
        'audio_paths': [],
        'support_paths': [],
        'all_paths': [],
        'representative_model': None,
        'representative_preview': None,
        'known_canonical_entity': key in known,
        'runtime_status': 'UNPROVEN',
        'writer_status': 'UNAUTHORIZED',
        'identity_evidence': meta.get('identity_evidence') or 'LIVE_RELATION',
    }


def _append_role_path(entity: dict[str, Any], path: str, row: dict[str, Any] | None = None, forced: str = '') -> None:
    path = _norm(path)
    if not path:
        return
    entity['all_paths'].append(path)
    role = forced or str((row or {}).get('role') or 'SUPPORT').upper()
    ext = str((row or {}).get('ext') or pathlib.PurePosixPath(path).suffix).lower()
    physical = str((row or {}).get('physical_family') or '').upper()
    if role in {'MODEL', 'DROP_MODEL', 'BODY', 'HEAD'} or ext == '.smd':
        entity['model_paths'].append(path)
    elif role == 'CONFIG' or ext in {'.inx', '.inf', '.ini'}:
        entity['config_paths'].append(path)
    elif role in {'ANIMATION', 'SKELETON_MOTION'} or ext == '.smb':
        entity['animation_paths'].append(path)
    elif physical == 'AUDIO' or role == 'AUDIO' or ext in {'.wav', '.ogg', '.mp3', '.mid', '.bgm'}:
        entity['audio_paths'].append(path)
    elif forced == 'ICON' or role.startswith('ITEM_ICON') or (row and row.get('category') == 'UI' and row.get('previewable')):
        entity['icon_paths'].append(path)
    elif forced == 'TEXTURE' or role in {'TEXTURE', 'DROP_TEXTURE'} or (row and row.get('previewable')):
        entity['texture_paths'].append(path)
    else:
        entity['support_paths'].append(path)



def _item_code_from_entity(entity: dict[str, Any]) -> str:
    stem = str(entity.get('display_name') or '').casefold()
    return stem[2:] if stem.startswith('it') else stem


def _annotate_item_visual_bundles(
    entities: list[dict[str, Any]],
    rows_by_path: dict[str, dict[str, Any]],
    registry=None,
) -> None:
    """Attach visual-bundle evidence without collapsing runtime item identity.

    Priston item identity and visual representation are different contracts:
    runtime sITEM/OpenItem codes may point at DorpItem assets, while equipped
    armor configs can reuse model/texture combinations. A bundle therefore
    groups only strongly evidenced visual dependencies; runtime codes remain a
    list of distinct identities inside that bundle.
    """
    items = [e for e in entities if str(e.get('semantic_group') or '') == 'ITEM']
    if not items:
        return

    try:
        from .item_runtime_catalog import item_runtime_catalog
        runtime_entries = list(item_runtime_catalog().get('entries') or [])
    except Exception:
        runtime_entries = []
    by_dorp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in runtime_entries:
        dorp = str(row.get('dorp_item') or '').casefold()
        if dorp:
            by_dorp[dorp].append(row)

    # Strong visual fingerprint: the complete non-empty registry texture set
    # for a concrete item model entity. Shared single path names are not enough;
    # equality is evaluated on the full dependency set.
    signature_groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for e in items:
        code = _item_code_from_entity(e)
        matches = by_dorp.get(code, [])
        runtime_codes = sorted({str(x.get('code') or '') for x in matches if x.get('code')}, key=str.casefold)
        e['runtime_item_codes'] = runtime_codes
        e['runtime_dorp_item'] = code if matches else None
        for r in matches:
            expected = r.get('expected_client_paths') or {}
            for kind, path in expected.items():
                if path:
                    e.setdefault('relationships', []).append({
                        'type': 'RUNTIME_ITEM_EXPECTS_VISUAL',
                        'from': str(r.get('code') or ''),
                        'to': _norm(path),
                        'evidence': f'SITEM_{str(kind).upper()}',
                    })
        textures = sorted({
            _norm(t).casefold()
            for asset in (e.get('registry_assets') or [])
            for t in (asset.get('textures') or [])
            if _norm(t)
        })
        if textures:
            signature_groups[tuple(textures)].append(e)

    # Build lookup of registry assets by exact texture dependency signature so
    # equipped armor configs/models can join a drop-item visual bundle without
    # filename guessing.
    registry_by_signature: dict[tuple[str, ...], list[Any]] = defaultdict(list)
    if registry is not None:
        for asset in getattr(registry, 'assets', []) or []:
            textures = tuple(sorted({
                _norm(t).casefold() for t in (getattr(asset, 'textures', []) or []) if _norm(t)
            }))
            if textures:
                registry_by_signature[textures].append(asset)

    for signature, members in signature_groups.items():
        digest = hashlib.sha1(('\n'.join(signature)).encode('utf-8')).hexdigest()[:16]
        bundle_key = f'ITEM_VISUAL|texset:{digest}'
        entity_keys = sorted({str(e.get('entity_key') or '') for e in members}, key=str.casefold)
        runtime_codes = sorted({
            code for e in members for code in (e.get('runtime_item_codes') or []) if code
        }, key=str.casefold)
        paths: set[str] = set()
        for e in members:
            paths.update(_norm(x) for x in (e.get('all_paths') or []) if _norm(x))
        for texture in signature:
            row = rows_by_path.get(texture)
            paths.add(_norm((row or {}).get('path') or texture))

        # Include equipped-model/config paths only when the registry proves the
        # exact same complete texture dependency set. If an INX has a physical
        # same-stem INI sibling, include it as a companion config path.
        for asset in registry_by_signature.get(signature, []):
            primary = _norm(getattr(asset, 'primary_path', ''))
            if primary:
                paths.add(primary)
            for cfg in getattr(asset, 'configs', []) or []:
                if not isinstance(cfg, dict):
                    continue
                for field in ('inx', 'motion_inx'):
                    config = _norm(cfg.get(field) or '')
                    if not config:
                        continue
                    paths.add(config)
                    pure = pathlib.PurePosixPath(config)
                    ini = pure.with_suffix('.ini').as_posix()
                    row = rows_by_path.get(ini.casefold())
                    if row:
                        paths.add(_norm(row.get('path') or ini))
            skeleton = _norm(getattr(asset, 'binding_skeleton_smb', ''))
            if skeleton:
                paths.add(skeleton)

        evidence = 'EXACT_FULL_TEXTURE_DEPENDENCY_SET'
        for e in members:
            e['visual_bundle_key'] = bundle_key
            e['visual_bundle_evidence'] = evidence
            e['visual_bundle_entity_keys'] = entity_keys
            e['visual_bundle_runtime_codes'] = runtime_codes
            e['visual_bundle_paths'] = sorted(paths, key=str.casefold)
            e['visual_bundle_member_count'] = len(entity_keys)
            e.setdefault('relationships', []).append({
                'type': 'ITEM_VISUAL_BUNDLE',
                'from': e.get('entity_key'),
                'to': bundle_key,
                'evidence': evidence,
            })

    # Items without a shared/full texture signature still get a stable local
    # bundle so UI semantics are uniform. This bundle has no cross-item claim.
    for e in items:
        if e.get('visual_bundle_key'):
            continue
        digest = hashlib.sha1(str(e.get('entity_key') or '').encode('utf-8')).hexdigest()[:16]
        e['visual_bundle_key'] = f'ITEM_VISUAL|entity:{digest}'
        e['visual_bundle_evidence'] = 'ENTITY_LOCAL_ONLY'
        e['visual_bundle_entity_keys'] = [str(e.get('entity_key') or '')]
        e['visual_bundle_runtime_codes'] = list(e.get('runtime_item_codes') or [])
        e['visual_bundle_paths'] = list(e.get('all_paths') or [])
        e['visual_bundle_member_count'] = 1

def build_live_entities(rows: Iterable[dict[str, Any]], seed: dict[str, Any] | None = None, registry=None) -> list[dict[str, Any]]:
    rows = list(rows)
    rows_by_path = {str(r.get('path') or '').casefold(): r for r in rows}
    known: dict[str, dict[str, Any]] = {}
    if seed:
        for item in seed.get('entities') or []:
            if isinstance(item, dict) and item.get('entity_key'):
                known[str(item['entity_key'])] = item

    grouped: dict[str, dict[str, Any]] = {}

    # Physical entities remain valid for Monster/NPC/Effect/Map. Item entities
    # are model-code based so DropItem does not collapse into one giant folder.
    for row in rows:
        category = str(row.get('category') or '').upper()
        desc = None
        if category in {'MONSTER', 'NPC', 'EFFECT', 'MAP'}:
            desc = _physical_entity_descriptor(row.get('path', ''), category, row.get('folder', ''), row.get('folder_path', ''))
        elif category == 'ITEM' and str(row.get('role') or '').upper() in {'MODEL', 'DROP_MODEL'}:
            desc = _physical_entity_descriptor(row.get('path', ''), 'ITEM')
        if desc:
            entity = grouped.setdefault(desc['entity_key'], _new_entity(desc, known))
            _append_role_path(entity, row.get('path', ''), row)

        # Exact canonical class path components are useful explicit evidence for
        # skill icons/audio. They never classify ha*/mfb* filename families.
        cls = _class_from_path_component(row.get('path', ''))
        if cls:
            meta = {
                'entity_key': f'CHARACTER|class:{cls.casefold()}',
                'semantic_group': 'CHARACTER',
                'display_name': cls,
                'folder_root': f'CHARACTER/{cls}',
                'identity_evidence': 'EXACT_CANONICAL_CLASS_PATH_COMPONENT',
            }
            entity = grouped.setdefault(meta['entity_key'], _new_entity(meta, known))
            forced = 'ICON' if row.get('category') == 'UI' and row.get('previewable') else ''
            _append_role_path(entity, row.get('path', ''), row, forced=forced)

    registry_evidence = _registry_evidence(registry, include_assets=True) if registry is not None else {}
    for key, ev in registry_evidence.items():
        meta = {
            'entity_key': key,
            'semantic_group': ev.get('semantic_group') or key.split('|', 1)[0],
            'display_name': ev.get('display_name') or key.split('|', 1)[-1],
            'folder_root': ev.get('folder_root') or '',
            'identity_evidence': ev.get('identity_evidence') or 'REGISTRY_RELATION',
        }
        entity = grouped.setdefault(key, _new_entity(meta, known))
        for path in ev.get('model_paths') or []:
            _append_role_path(entity, path, rows_by_path.get(path.casefold()), forced='MODEL')
        for path in ev.get('config_paths') or []:
            _append_role_path(entity, path, rows_by_path.get(path.casefold()), forced='CONFIG')
        for path in ev.get('animation_paths') or []:
            _append_role_path(entity, path, rows_by_path.get(path.casefold()), forced='ANIMATION')
        for path in ev.get('texture_paths') or []:
            _append_role_path(entity, path, rows_by_path.get(path.casefold()), forced='TEXTURE')
        # Preserve technical readiness/relationship evidence.
        for field, value in ev.items():
            if field not in {'model_paths', 'config_paths', 'animation_paths', 'texture_paths', 'related_asset_paths'}:
                entity[field] = value
        entity['registry_evidence'] = True

    # Attach Monster/NPC support trees (notably wav/Effects/monster/<name>)
    # only after a canonical actor entity exists. Exact folder-component identity
    # can enrich a known actor, but support-only folders never create actors.
    actor_by_group_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entity in grouped.values():
        group = str(entity.get('semantic_group') or '').upper()
        if group in {'MONSTER', 'NPC'}:
            actor_by_group_name[(group, str(entity.get('display_name') or '').casefold())].append(entity)
    for row in rows:
        group = str(row.get('category') or '').upper()
        if group not in {'MONSTER', 'NPC'}:
            continue
        path = _norm(row.get('path', ''))
        parts = pathlib.PurePosixPath(path).parts
        token = 'monster' if group == 'MONSTER' else 'npc'
        names = [parts[i + 1] for i, part in enumerate(parts[:-1]) if part.casefold() == token]
        if not names:
            continue
        candidates = actor_by_group_name.get((group, names[0].casefold()), [])
        if len(candidates) != 1:
            continue
        entity = candidates[0]
        if path in set(entity.get('all_paths') or []):
            continue
        _append_role_path(entity, path, row)
        entity.setdefault('relationships', []).append({
            'type': 'ENTITY_HAS_SUPPORT_ASSET',
            'from': entity.get('entity_key'),
            'to': path,
            'evidence': 'EXACT_ACTOR_FOLDER_COMPONENT',
        })

    # Add same-stem item siblings only after a model has established item
    # identity. This links drop textures/support without making a folder itself
    # the item entity.
    item_by_stem = {
        e['display_name'].casefold(): e
        for e in grouped.values() if e.get('semantic_group') == 'ITEM'
    }
    for row in rows:
        category = str(row.get('category') or '').upper()
        role = str(row.get('role') or '').upper()
        is_item_support = category == 'ITEM'
        is_item_icon = category == 'UI' and role.startswith('ITEM_ICON')
        if not (is_item_support or is_item_icon):
            continue
        path = str(row.get('path') or '')
        stem = pathlib.PurePosixPath(path).stem.casefold()
        entity = item_by_stem.get(stem)
        if entity:
            if is_item_icon:
                _append_role_path(entity, path, row, forced='ICON')
                entity.setdefault('relationships', []).append({
                    'type': 'ITEM_HAS_ICON', 'from': entity.get('representative_model') or entity.get('model_paths', [''])[0],
                    'to': _norm(path), 'evidence': 'EXACT_ITEM_CODE_STEM',
                })
            else:
                _append_role_path(entity, path, row)

    # Finalize all path/count/facet fields from unique membership.
    out: list[dict[str, Any]] = []
    for e in grouped.values():
        for field in ('model_paths', 'config_paths', 'animation_paths', 'texture_paths', 'icon_paths', 'audio_paths', 'support_paths', 'all_paths'):
            e[field] = sorted(set(e.get(field) or []), key=str.casefold)
        e['all_paths'] = sorted(set(e['all_paths']) | set(e['model_paths']) | set(e['config_paths']) | set(e['animation_paths']) |
                                set(e['texture_paths']) | set(e['icon_paths']) | set(e['audio_paths']) | set(e['support_paths']), key=str.casefold)
        e['asset_count'] = len(e['all_paths'])
        e['total_bytes'] = sum(int((rows_by_path.get(p.casefold()) or {}).get('size') or 0) for p in e['all_paths'])
        role_counts = Counter()
        extension_counts = Counter()
        for p in e['all_paths']:
            row = rows_by_path.get(p.casefold())
            if row:
                role_counts[str(row.get('role') or 'SUPPORT').upper()] += 1
                extension_counts[str(row.get('ext') or '(none)').lower() or '(none)'] += 1
            else:
                extension_counts[pathlib.PurePosixPath(p).suffix.lower() or '(none)'] += 1
        e['role_counts'] = dict(sorted(role_counts.items()))
        e['extension_counts'] = dict(sorted(extension_counts.items()))
        if e['model_paths']:
            exact = [x for x in e['model_paths'] if pathlib.PurePosixPath(x).stem.casefold() == e['display_name'].casefold()]
            e['representative_model'] = (exact or e['model_paths'])[0]
        previews = [p for p in e['icon_paths'] + e['texture_paths'] if (rows_by_path.get(p.casefold()) or {}).get('previewable')]
        if previews:
            e['representative_preview'] = sorted(previews, key=lambda p: _preview_score(e['display_name'], rows_by_path.get(p.casefold(), {'path': p})))[0]
        if e['entity_key'] in known:
            seed_item = known[e['entity_key']]
            e['seed_file_count'] = int(seed_item.get('file_count') or 0)
            e['seed_representative_preview'] = seed_item.get('representative_preview')
            e['seed_representative_model'] = seed_item.get('representative_model')
        e.setdefault('registry_evidence', False)
        e.setdefault('registry_asset_count', 0)
        e.setdefault('registry_family_counts', {})
        e.setdefault('registry_binding_mode_counts', {})
        e.setdefault('rigid_model_count', 0)
        e.setdefault('rigid_binding_ready_count', 0)
        e.setdefault('animation_binding_ready_count', 0)
        e.setdefault('physical_rigid_binding_ready_count', 0)
        e.setdefault('physical_animation_binding_ready_count', 0)
        e.setdefault('binding_skeleton_paths', [])
        e.setdefault('motion_smb_paths', [])
        e.setdefault('related_entity_keys', [])
        e.setdefault('referenced_by_entity_keys', [])
        e.setdefault('cross_entity_links', [])
        e.setdefault('relationships', [])
        e['runtime_status'] = 'UNPROVEN'
        e['writer_status'] = 'UNAUTHORIZED'
        e['has_model'] = bool(e['model_paths'])
        e['has_config'] = bool(e['config_paths'])
        e['has_animation'] = bool(e['animation_paths'])
        e['has_preview_candidate'] = bool(e['representative_preview'])
        out.append(e)
    _annotate_item_visual_bundles(out, rows_by_path, registry=registry)
    return sorted(out, key=lambda x: (x['semantic_group'], x['display_name'].casefold()))


def _entity_summary(entity: dict[str, Any]) -> dict[str, Any]:
    """Thin entity row for list/grid endpoints.

    Entity detail owns the large path/relationship payload. Keeping list rows
    compact avoids serializing thousands of path strings on every search.
    """
    keep = (
        'entity_key', 'semantic_group', 'display_name', 'folder_root',
        'identity_evidence', 'known_canonical_entity', 'asset_count', 'total_bytes',
        'role_counts', 'extension_counts', 'representative_model',
        'representative_preview', 'registry_evidence', 'registry_asset_count',
        'registry_family_counts', 'registry_binding_mode_counts', 'rigid_model_count',
        'rigid_binding_ready_count', 'animation_binding_ready_count',
        'physical_rigid_binding_ready_count', 'physical_animation_binding_ready_count',
        'runtime_status', 'writer_status', 'has_model', 'has_config',
        'has_animation', 'has_preview_candidate', 'visual_bundle_key',
        'visual_bundle_runtime_codes', 'visual_bundle_member_count',
        'visual_bundle_evidence',
    )
    return {k: entity.get(k) for k in keep if k in entity}


def _entity_search_text(entity: dict[str, Any]) -> str:
    cached = entity.get('_search_text')
    if isinstance(cached, str):
        return cached
    text = ' '.join([
        str(entity.get('display_name') or ''),
        str(entity.get('folder_root') or ''),
        ' '.join(str(x) for x in (entity.get('role_counts') or {})),
        ' '.join(str(x) for x in (entity.get('all_paths') or [])),
        str(entity.get('identity_evidence') or ''),
        ' '.join(str(x) for x in (entity.get('visual_bundle_runtime_codes') or [])),
    ]).casefold()
    entity['_search_text'] = text
    return text


def query_built_entities(
    entities: Iterable[dict[str, Any]],
    seed: dict[str, Any] | None = None,
    *,
    group: str = '',
    q: str = '',
    limit: int = 500,
) -> dict[str, Any]:
    entities = list(entities)
    group = group.strip().upper()
    if group == 'MAP':
        group = 'MAP_FIELD'
    terms = [x.casefold() for x in q.split() if x.strip()]
    out = []
    for e in entities:
        if group and e.get('semantic_group') != group:
            continue
        if terms and not all(t in _entity_search_text(e) for t in terms):
            continue
        out.append(_entity_summary(e))
    out = out[: max(1, min(2000, int(limit)))]
    counts = Counter(x.get('semantic_group') for x in entities)
    return {
        'format': 'PT_LIVE_ENTITY_CATALOG_V3',
        'status': 'PASS',
        'policy': {
            'identity': 'typed physical/registry relationships; filename-family guesses are not entity truth',
            'runtime': 'UNPROVEN unless separately validated',
            'writer': 'UNAUTHORIZED unless separately certified',
            'character_priority': 'source-proven class config + verified binding context + exact canonical class path component',
            'item_priority': 'runtime DorpItem + registry model/material relations; visual bundles do not merge runtime item identities',
        },
        'live_entity_count': len(entities),
        'live_group_counts': dict(counts),
        'known_seed_entity_count': int((seed or {}).get('entity_count') or 0),
        'items': out,
    }


def _add_targeted_physical_evidence(found: dict[str, Any], registry) -> None:
    """Add expensive physical dependency evidence only for one selected entity."""
    assets = list(found.get('registry_assets') or [])
    rigid = 0
    animated = 0
    for row in assets:
        path = str(row.get('path') or '')
        if not path:
            continue
        try:
            asset = registry.resolve(path)
        except Exception:
            continue
        try:
            physical = registry.physical_dependency_status(asset)
        except Exception as exc:
            physical = {'status': 'ERROR', 'error': f'{type(exc).__name__}:{exc}'}
        row['physical_dependency_status'] = physical
        if physical.get('rigid_binding_ready_physical'):
            rigid += 1
        if physical.get('animation_binding_ready_physical'):
            animated += 1
    found['physical_rigid_binding_ready_count'] = rigid
    found['physical_animation_binding_ready_count'] = animated


def entity_detail_from_built(
    entities: Iterable[dict[str, Any]],
    entity_key: str,
    *,
    registry=None,
) -> dict[str, Any] | None:
    wanted = str(entity_key or '').strip()
    if not wanted:
        return None
    found0 = next((e for e in entities if str(e.get('entity_key')) == wanted), None)
    if found0 is None:
        return None
    # Cached entities are shared across request threads. Copy mutable nested
    # fields that detail enrichment may update so the cache remains immutable.
    found = dict(found0)
    found['registry_assets'] = [dict(x) for x in (found0.get('registry_assets') or [])]
    if registry is not None:
        _add_targeted_physical_evidence(found, registry)
    found.pop('_search_text', None)
    return {
        'format': 'PT_LIVE_ENTITY_DETAIL_V3',
        'status': 'PASS',
        'entity': found,
        'policy': {
            'folder_identity_is_runtime_evidence': False,
            'registry_binding_is_runtime_certification': False,
            'writer_requires_separate_certification': True,
            'naming_guess_is_entity_identity': False,
            'visual_bundle_merges_runtime_identity': False,
        },
        'client_modified': False,
    }


def query_entities(
    rows: Iterable[dict[str, Any]],
    seed: dict[str, Any] | None = None,
    *,
    group: str = '',
    q: str = '',
    limit: int = 500,
    registry=None,
) -> dict[str, Any]:
    entities = build_live_entities(list(rows), seed, registry=registry)
    return query_built_entities(entities, seed, group=group, q=q, limit=limit)


def entity_detail(
    rows: Iterable[dict[str, Any]],
    seed: dict[str, Any] | None,
    entity_key: str,
    *,
    registry=None,
) -> dict[str, Any] | None:
    entities = build_live_entities(list(rows), seed, registry=registry)
    return entity_detail_from_built(entities, entity_key, registry=registry)

# PT_POST_CONSOLIDATION_REGRESSION_REPAIR_2026-09-25
# Compatibility enrichment restored after technical-debt consolidation dropped
# path/registry relationship facets from the public entity catalog contract.
_PT_ENTITY_QUERY_BASE = query_entities
_PT_ENTITY_DETAIL_BASE = entity_detail

def _pt_rr_norm_path(value):
    return str(value or "").replace("\\", "/").strip("/")

def _pt_rr_row_bucket(row):
    import pathlib as _p
    path = _pt_rr_norm_path(row.get("path"))
    role = str(row.get("role") or "").upper()
    ext = str(row.get("ext") or _p.PurePosixPath(path).suffix).lower()
    if role.startswith("ITEM_ICON") or role in {"ICON", "SKILL", "ITEM_ICON"}:
        return "icon_paths"
    if ext in {".wav", ".mp3", ".ogg"} or role == "AUDIO":
        return "audio_paths"
    if ext in {".smd", ".ase"} or "MODEL" in role:
        return "model_paths"
    if ext in {".inx", ".ini"} or role == "CONFIG":
        return "config_paths"
    if ext in {".smb"} or "ANIMATION" in role or "MOTION" in role:
        return "animation_paths"
    if ext in {".bmp", ".tga", ".png", ".jpg", ".jpeg", ".dds"} or "TEXTURE" in role:
        return "texture_paths"
    return "support_paths"

def _pt_rr_canonical_actor_key(path):
    import pathlib as _p
    parts = _p.PurePosixPath(_pt_rr_norm_path(path)).parts
    if len(parts) >= 3 and parts[0].casefold() == "char" and parts[1].casefold() in {"npc", "monster"}:
        group = "NPC" if parts[1].casefold() == "npc" else "MONSTER"
        return f"{group}|{('/'.join(parts[:3])).casefold()}"
    return None

def _pt_rr_registry_match(entity, asset):
    import pathlib as _p
    group = str(entity.get("semantic_group") or "").upper()
    key = str(entity.get("entity_key") or "").casefold()
    display = str(entity.get("display_name") or "").casefold()
    primary = _pt_rr_norm_path(getattr(asset, "primary_path", ""))
    if primary and primary.casefold() in {str(x).casefold() for x in entity.get("model_paths", [])}:
        return True
    if group in {"NPC", "MONSTER"}:
        return _pt_rr_canonical_actor_key(primary) == key
    if group == "ITEM" and primary:
        return _p.PurePosixPath(primary).stem.casefold() == display
    return False

def _pt_rr_enrich_entity(entity, rows, registry=None, *, include_assets=False, include_physical=False):
    import pathlib as _p
    from collections import Counter as _Counter
    group = str(entity.get("semantic_group") or "").upper()
    display = str(entity.get("display_name") or "")
    display_cf = display.casefold()
    key = str(entity.get("entity_key") or "")
    all_existing = {_pt_rr_norm_path(x) for x in (entity.get("all_paths") or []) if x}
    buckets = {name: set(entity.get(name) or []) for name in (
        "model_paths", "config_paths", "animation_paths", "texture_paths",
        "icon_paths", "audio_paths", "support_paths")}
    candidate_rows = []
    for row in rows:
        path = _pt_rr_norm_path(row.get("path"))
        if not path: continue
        pp = _p.PurePosixPath(path)
        role = str(row.get("role") or "").upper()
        cat = str(row.get("category") or "").upper()
        include = path in all_existing
        if group == "ITEM":
            include = include or (pp.stem.casefold() == display_cf and (cat == "ITEM" or (cat == "UI" and role.startswith("ITEM_ICON"))))
        elif group in {"NPC", "MONSTER"}:
            token = "npc" if group == "NPC" else "monster"
            parts = pp.parts
            include = include or (len(parts) >= 3 and parts[0].casefold() == "char" and parts[1].casefold() == token and parts[2].casefold() == display_cf)
            for i, part in enumerate(parts[:-1]):
                if part.casefold() == token and i + 1 < len(parts) and parts[i + 1].casefold() == display_cf:
                    include = True; break
        if include:
            candidate_rows.append(row)
            buckets[_pt_rr_row_bucket(row)].add(path)
    relationships = list(entity.get("relationships") or [])
    model = sorted(buckets["model_paths"], key=str.casefold)
    model0 = model[0] if model else None
    if group == "ITEM" and model0:
        for p in sorted(buckets["texture_paths"], key=str.casefold):
            relationships.append({"type":"MODEL_USES_TEXTURE","from":model0,"to":p,"evidence":"EXACT_ITEM_CODE_STEM"})
        for p in sorted(buckets["icon_paths"], key=str.casefold):
            relationships.append({"type":"ITEM_HAS_ICON","from":model0,"to":p,"evidence":"EXACT_ITEM_CODE_STEM"})
    if group in {"NPC", "MONSTER"}:
        canonical_prefix = f"char/{'npc' if group == 'NPC' else 'monster'}/{display}/".casefold()
        for row in candidate_rows:
            p = _pt_rr_norm_path(row.get("path"))
            if not p.casefold().startswith(canonical_prefix):
                relationships.append({"type":"ENTITY_HAS_SUPPORT_ASSET","from":key,"to":p,"evidence":"EXACT_ACTOR_FOLDER_COMPONENT"})
    reg_assets=[]; fam=_Counter(); bind_modes=_Counter(); rigid_ready=anim_ready=phys_rigid=phys_anim=0
    skeletons=set(entity.get("binding_skeleton_paths") or []); motions=set(entity.get("motion_smb_paths") or [])
    if registry is not None:
        probe_entity = {**entity, **{k:list(v) for k,v in buckets.items()}}
        for asset in getattr(registry,"assets",[]) or []:
            if not _pt_rr_registry_match(probe_entity, asset): continue
            fam[str(getattr(asset,"family","") or "UNKNOWN")]+=1
            bind_modes[str(getattr(asset,"binding_mode","") or "NONE")]+=1
            rigid_ready += int(bool(getattr(asset,"rigid_binding_ready",False)))
            anim_ready += int(bool(getattr(asset,"animation_binding_ready",False)))
            skeleton=_pt_rr_norm_path(getattr(asset,"binding_skeleton_smb",""))
            if skeleton: skeletons.add(skeleton); buckets["animation_paths"].add(skeleton)
            for motion in getattr(asset,"motions",[]) or []:
                motion=_pt_rr_norm_path(motion)
                if motion: motions.add(motion); buckets["animation_paths"].add(motion)
            for texture in getattr(asset,"textures",[]) or []:
                texture=_pt_rr_norm_path(texture)
                if texture:
                    buckets["texture_paths"].add(texture)
                    if model0: relationships.append({"type":"MODEL_USES_TEXTURE","from":model0,"to":texture,"evidence":"SMD_MATERIAL_TEXLINK"})
            cfg_rows=[]
            for c in getattr(asset,"configs",[]) or []:
                if not isinstance(c,dict): continue
                for field in ("inx","motion_inx"):
                    logical=_pt_rr_norm_path(c.get(field))
                    if logical: buckets["config_paths"].add(logical)
                cfg_rows.append({"inx":c.get("inx"),"motion_inx":c.get("motion_inx"),"motion_smb":c.get("motion_smb")})
            physical=None
            if include_physical and hasattr(registry,"physical_dependency_status"):
                try: physical=registry.physical_dependency_status(asset)
                except Exception as exc: physical={"status":"ERROR","error":f"{type(exc).__name__}:{exc}"}
                phys_rigid += int(bool((physical or {}).get("rigid_binding_ready_physical")))
                phys_anim += int(bool((physical or {}).get("animation_binding_ready_physical")))
            if include_assets:
                rr={"asset_id":getattr(asset,"asset_id",None),"path":_pt_rr_norm_path(getattr(asset,"primary_path","")),"family":getattr(asset,"family",None),"kind":getattr(asset,"kind",None),"category":getattr(asset,"category",None),"binding_mode":getattr(asset,"binding_mode",None),"binding_source":getattr(asset,"binding_source",None),"rigid_binding_ready":bool(getattr(asset,"rigid_binding_ready",False)),"animation_binding_ready":bool(getattr(asset,"animation_binding_ready",False)),"binding_skeleton_smb":skeleton or None,"motions":list(getattr(asset,"motions",[]) or []),"textures":list(getattr(asset,"textures",[]) or []),"configs":cfg_rows}
                if physical is not None: rr["physical_dependency_status"]=physical
                reg_assets.append(rr)
        for pair in getattr(registry,"pairing",[]) or []:
            if not isinstance(pair,dict): continue
            source_key=_pt_rr_canonical_actor_key(pair.get("inx") or "")
            if source_key != key: continue
            targets=sorted({k for k in (_pt_rr_canonical_actor_key(pair.get("model_smd") or ""),_pt_rr_canonical_actor_key(pair.get("motion_smb") or "")) if k and k != source_key})
            if targets:
                entity["related_entity_keys"]=sorted(set(entity.get("related_entity_keys") or [])|set(targets),key=str.casefold)
                entity.setdefault("cross_entity_links",[]).append({"evidence":"INX_PHYSICAL_PAIRING","inx":_pt_rr_norm_path(pair.get("inx") or "") or None,"model_smd":_pt_rr_norm_path(pair.get("model_smd") or "") or None,"motion_smb":_pt_rr_norm_path(pair.get("motion_smb") or "") or None,"target_entity_keys":targets,"model_resolved":str(pair.get("model_resolved") or "").casefold()=="true","motion_resolved":str(pair.get("motion_resolved") or "").casefold()=="true"})
    for field, values in buckets.items(): entity[field]=sorted({_pt_rr_norm_path(x) for x in values if x},key=str.casefold)
    entity["all_paths"]=sorted(set(entity.get("all_paths") or [])|set().union(*buckets.values()),key=str.casefold)
    seen=set(); dedup=[]
    for rel in relationships:
        rk=(rel.get("type"),str(rel.get("from") or "").casefold(),str(rel.get("to") or "").casefold())
        if rk in seen: continue
        seen.add(rk); dedup.append(rel)
    entity["relationships"]=dedup
    if registry is not None:
        count=sum(fam.values())
        if count:
            entity["registry_evidence"]=True; entity["registry_asset_count"]=count; entity["registry_family_counts"]=dict(sorted(fam.items())); entity["registry_binding_mode_counts"]=dict(sorted(bind_modes.items())); entity["rigid_binding_ready_count"]=rigid_ready; entity["animation_binding_ready_count"]=anim_ready
        entity["binding_skeleton_paths"]=sorted(skeletons,key=str.casefold); entity["motion_smb_paths"]=sorted(motions,key=str.casefold)
        if include_physical:
            entity["physical_rigid_binding_ready_count"]=phys_rigid; entity["physical_animation_binding_ready_count"]=phys_anim
        if include_assets: entity["registry_assets"]=sorted(reg_assets,key=lambda x:str(x.get("path") or "").casefold())
    entity.setdefault("registry_evidence",False); entity.setdefault("registry_asset_count",0); entity.setdefault("registry_family_counts",{}); entity.setdefault("rigid_binding_ready_count",0); entity.setdefault("animation_binding_ready_count",0); entity.setdefault("binding_skeleton_paths",[]); entity.setdefault("motion_smb_paths",[]); entity.setdefault("related_entity_keys",[]); entity.setdefault("referenced_by_entity_keys",[]); entity.setdefault("cross_entity_links",[]); entity.setdefault("runtime_status","UNPROVEN"); entity.setdefault("writer_status","UNAUTHORIZED")
    return entity

def _pt_rr_apply_reverse_pair_links(items):
    by_key={str(x.get("entity_key") or ""):x for x in items}
    for item in items:
        for target in item.get("related_entity_keys") or []:
            if target in by_key:
                tgt=by_key[target]
                tgt["referenced_by_entity_keys"]=sorted(set(tgt.get("referenced_by_entity_keys") or [])|{str(item.get("entity_key") or "")},key=str.casefold)

def query_entities(rows, seed=None, *, group="", q="", limit=500, registry=None):
    rows_list=list(rows)
    report=_PT_ENTITY_QUERY_BASE(rows_list,seed,group=group,q=q,limit=limit,registry=registry)
    items=report.get("items") or []
    for entity in items: _pt_rr_enrich_entity(entity,rows_list,registry,include_assets=False,include_physical=False)
    _pt_rr_apply_reverse_pair_links(items)
    return report

def entity_detail(rows, seed, entity_key, *, registry=None):
    rows_list=list(rows)
    report=_PT_ENTITY_DETAIL_BASE(rows_list,seed,entity_key,registry=registry)
    if report and isinstance(report.get("entity"),dict): _pt_rr_enrich_entity(report["entity"],rows_list,registry,include_assets=True,include_physical=True)
    return report

