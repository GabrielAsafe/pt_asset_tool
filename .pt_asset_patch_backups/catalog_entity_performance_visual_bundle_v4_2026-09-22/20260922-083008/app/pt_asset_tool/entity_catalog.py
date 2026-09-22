from __future__ import annotations

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
    return sorted(out, key=lambda x: (x['semantic_group'], x['display_name'].casefold()))


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
    group = group.strip().upper()
    if group == 'MAP':
        group = 'MAP_FIELD'
    terms = [x.lower() for x in q.split() if x.strip()]
    out = []
    for e in entities:
        if group and e['semantic_group'] != group:
            continue
        if terms:
            hay = ' '.join([
                e['display_name'], e['folder_root'], ' '.join(e['role_counts']),
                ' '.join(e.get('all_paths') or []), e.get('identity_evidence', ''),
            ]).lower()
            if not all(t in hay for t in terms):
                continue
        out.append({k: v for k, v in e.items() if k != 'registry_assets'})
    out = out[: max(1, min(2000, int(limit)))]
    counts = Counter(x['semantic_group'] for x in entities)
    return {
        'format': 'PT_LIVE_ENTITY_CATALOG_V2',
        'status': 'PASS',
        'policy': {
            'identity': 'typed physical/registry relationships; filename-family guesses are not entity truth',
            'runtime': 'UNPROVEN unless separately validated',
            'writer': 'UNAUTHORIZED unless separately certified',
            'character_priority': 'source-proven class config + verified binding context + exact canonical class path component',
            'item_priority': 'registry model identity + SMD material/TexLink texture relationships',
        },
        'live_entity_count': len(entities),
        'live_group_counts': dict(counts),
        'known_seed_entity_count': int((seed or {}).get('entity_count') or 0),
        'items': out,
    }


def entity_detail(
    rows: Iterable[dict[str, Any]],
    seed: dict[str, Any] | None,
    entity_key: str,
    *,
    registry=None,
) -> dict[str, Any] | None:
    wanted = str(entity_key or '').strip()
    if not wanted:
        return None
    entities = build_live_entities(list(rows), seed, registry=registry)
    found = next((e for e in entities if str(e.get('entity_key')) == wanted), None)
    if found is None:
        return None
    if registry is not None:
        # Re-run only to add physical dependency details to registry assets.
        physical = _registry_evidence(registry, include_assets=True, include_physical=True).get(wanted)
        if physical:
            for field in (
                'physical_rigid_binding_ready_count', 'physical_animation_binding_ready_count',
                'registry_assets', 'relationships', 'cross_entity_links', 'related_entity_keys',
                'referenced_by_entity_keys',
            ):
                if field in physical:
                    found[field] = physical[field]
    return {
        'format': 'PT_LIVE_ENTITY_DETAIL_V2',
        'status': 'PASS',
        'entity': found,
        'policy': {
            'folder_identity_is_runtime_evidence': False,
            'registry_binding_is_runtime_certification': False,
            'writer_requires_separate_certification': True,
            'naming_guess_is_entity_identity': False,
        },
        'client_modified': False,
    }
