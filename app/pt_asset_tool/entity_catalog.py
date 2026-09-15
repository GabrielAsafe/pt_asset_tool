from __future__ import annotations

import json
import pathlib
from collections import Counter
from typing import Any, Iterable

SEED_REL = pathlib.Path('data/entity_catalog/monster_npc_entities_v1.json')
ENTITY_CATEGORIES = {'MONSTER', 'NPC'}


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
    # Prefer catalog-previewable files when scores tie.
    if row.get('previewable'):
        score += 5
    return -score, path.lower()


def _registry_entity_key(path: str) -> str | None:
    """Return the physical entity key for a registry model path.

    Folder identity is useful catalog evidence, but it is deliberately kept
    separate from runtime/binding authority.  This helper only associates an
    already-built registry asset with its physical Monster/NPC folder.
    """
    parts = pathlib.PurePosixPath(str(path).replace('\\', '/')).parts
    if len(parts) < 4 or parts[0].casefold() != 'char':
        return None
    branch = parts[1].casefold()
    if branch == 'monster':
        group = 'MONSTER'
    elif branch == 'npc':
        group = 'NPC'
    else:
        return None
    folder_root = '/'.join(parts[:3])
    return f'{group}|{folder_root.lower()}'


def _registry_evidence(registry, *, include_assets: bool = False, include_physical: bool = False) -> dict[str, dict[str, Any]]:
    def empty() -> dict[str, Any]:
        return {
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
        }

    grouped: dict[str, dict[str, Any]] = {}
    for asset in getattr(registry, 'assets', []) or []:
        key = _registry_entity_key(getattr(asset, 'primary_path', ''))
        if not key:
            continue
        e = grouped.setdefault(key, empty())
        e['registry_asset_count'] += 1
        e['registry_family_counts'][str(getattr(asset, 'family', '') or 'UNKNOWN')] += 1
        e['registry_binding_mode_counts'][str(getattr(asset, 'binding_mode', '') or 'NONE')] += 1
        if getattr(asset, 'family', '') == 'SMD_MODEL_062_RIGID_PHYSIQUE':
            e['rigid_model_count'] += 1
        if bool(getattr(asset, 'rigid_binding_ready', False)):
            e['rigid_binding_ready_count'] += 1
        if bool(getattr(asset, 'animation_binding_ready', False)):
            e['animation_binding_ready_count'] += 1
        skeleton = str(getattr(asset, 'binding_skeleton_smb', '') or '')
        if skeleton:
            e['binding_skeleton_paths'].add(skeleton)
        for motion in getattr(asset, 'motions', []) or []:
            if motion:
                e['motion_smb_paths'].add(str(motion))

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
                'path': getattr(asset, 'primary_path', None),
                'family': getattr(asset, 'family', None),
                'kind': getattr(asset, 'kind', None),
                'binding_mode': getattr(asset, 'binding_mode', None),
                'binding_source': getattr(asset, 'binding_source', None),
                'rigid_binding_ready': bool(getattr(asset, 'rigid_binding_ready', False)),
                'animation_binding_ready': bool(getattr(asset, 'animation_binding_ready', False)),
                'binding_skeleton_smb': skeleton or None,
                'motions': list(getattr(asset, 'motions', []) or []),
                'configs': [
                    {
                        'inx': c.get('inx'),
                        'motion_smb': c.get('motion_smb'),
                    }
                    for c in (getattr(asset, 'configs', []) or [])
                    if isinstance(c, dict)
                ],
            }
            if physical is not None:
                row['physical_dependency_status'] = physical
            e['registry_assets'].append(row)

    # Pairing rows can contain explicit cross-folder model/motion references.
    # Preserve those as relationship evidence rather than guessing from similar
    # entity names.  Example: an INX under Bcn05_ can resolve a model/skeleton
    # under Bcn05; the two folder identities remain distinct catalog entities.
    for pair in getattr(registry, 'pairing', []) or []:
        if not isinstance(pair, dict):
            continue
        inx = str(pair.get('inx') or '').replace('\\', '/')
        model = str(pair.get('model_smd') or '').replace('\\', '/')
        motion = str(pair.get('motion_smb') or '').replace('\\', '/')
        source_key = _registry_entity_key(inx)
        target_keys = sorted({
            k for k in (_registry_entity_key(model), _registry_entity_key(motion)) if k
        })
        if not source_key or not target_keys:
            continue
        source = grouped.setdefault(source_key, empty())
        for target_key in target_keys:
            if target_key == source_key:
                continue
            source['related_entity_keys'].add(target_key)
            target = grouped.setdefault(target_key, empty())
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
        e['binding_skeleton_paths'] = sorted(e['binding_skeleton_paths'], key=str.lower)
        e['motion_smb_paths'] = sorted(e['motion_smb_paths'], key=str.lower)
        e['related_entity_keys'] = sorted(e['related_entity_keys'], key=str.lower)
        e['referenced_by_entity_keys'] = sorted(e['referenced_by_entity_keys'], key=str.lower)
        e['cross_entity_links'] = sorted(
            e['cross_entity_links'],
            key=lambda x: (str(x.get('inx') or '').lower(), str(x.get('model_smd') or '').lower()),
        )
        if include_assets:
            e['registry_assets'] = sorted(e['registry_assets'], key=lambda x: str(x.get('path') or '').lower())
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
            row.update(ev)
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
            })
            if include_assets:
                row['registry_assets'] = []
        # Registry evidence can describe technical readiness, but does not by
        # itself certify a runtime entity or authorize a writer.
        row['runtime_status'] = 'UNPROVEN'
        row['writer_status'] = 'UNAUTHORIZED'
        out.append(row)
    return out


def build_live_entities(rows: Iterable[dict[str, Any]], seed: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = list(rows)
    rows_by_path = {str(r.get('path') or ''): r for r in rows}
    known = {}
    if seed:
        for item in seed.get('entities') or []:
            if isinstance(item, dict):
                key = str(item.get('entity_key') or '')
                if key:
                    known[key] = item

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = str(row.get('category') or '').upper()
        if group not in ENTITY_CATEGORIES:
            continue
        folder_root = str(row.get('folder_path') or '')
        name = str(row.get('folder') or '')
        if not folder_root or not name or name == '(raiz)':
            continue
        key = f'{group}|{folder_root.lower()}'
        e = grouped.setdefault(key, {
            'entity_key': key,
            'semantic_group': group,
            'display_name': name,
            'folder_root': folder_root,
            'asset_count': 0,
            'total_bytes': 0,
            'role_counts': Counter(),
            'extension_counts': Counter(),
            'model_paths': [],
            'config_paths': [],
            'animation_paths': [],
            'texture_paths': [],
            'audio_paths': [],
            'support_paths': [],
            'representative_model': None,
            'representative_preview': None,
            'known_canonical_entity': key in known,
            'runtime_status': 'UNPROVEN',
            'writer_status': 'UNAUTHORIZED',
            'identity_evidence': 'LIVE_PHYSICAL_FOLDER',
        })
        path = str(row.get('path') or '')
        role = str(row.get('role') or 'SUPPORT').upper()
        ext = str(row.get('ext') or '').lower()
        e['asset_count'] += 1
        e['total_bytes'] += int(row.get('size') or 0)
        e['role_counts'][role] += 1
        e['extension_counts'][ext or '(none)'] += 1
        if role in {'MODEL', 'DROP_MODEL'}:
            e['model_paths'].append(path)
        elif role == 'CONFIG':
            e['config_paths'].append(path)
        elif role == 'ANIMATION':
            e['animation_paths'].append(path)
        elif role == 'TEXTURE' or bool(row.get('previewable')):
            e['texture_paths'].append(path)
        elif role == 'AUDIO':
            e['audio_paths'].append(path)
        else:
            e['support_paths'].append(path)

    for e in grouped.values():
        for field in ('model_paths', 'config_paths', 'animation_paths', 'texture_paths', 'audio_paths', 'support_paths'):
            e[field] = sorted(set(e[field]), key=str.lower)
        if e['model_paths']:
            exact = [x for x in e['model_paths'] if pathlib.PurePosixPath(x).stem.lower() == e['display_name'].lower()]
            e['representative_model'] = (exact or e['model_paths'])[0]
        if e['texture_paths']:
            e['representative_preview'] = sorted(
                e['texture_paths'], key=lambda p: _preview_score(e['display_name'], rows_by_path.get(p, {'path': p}))
            )[0]
        if e['entity_key'] in known:
            seed_item = known[e['entity_key']]
            e['seed_file_count'] = int(seed_item.get('file_count') or 0)
            e['seed_representative_preview'] = seed_item.get('representative_preview')
            e['seed_representative_model'] = seed_item.get('representative_model')
        e['role_counts'] = dict(sorted(e['role_counts'].items()))
        e['extension_counts'] = dict(sorted(e['extension_counts'].items()))
        e['has_model'] = bool(e['model_paths'])
        e['has_config'] = bool(e['config_paths'])
        e['has_animation'] = bool(e['animation_paths'])
        e['has_preview_candidate'] = bool(e['representative_preview'])
    return sorted(grouped.values(), key=lambda x: (x['semantic_group'], x['display_name'].lower()))


def query_entities(
    rows: Iterable[dict[str, Any]],
    seed: dict[str, Any] | None = None,
    *,
    group: str = '',
    q: str = '',
    limit: int = 500,
    registry=None,
) -> dict[str, Any]:
    entities = build_live_entities(list(rows), seed)
    if registry is not None:
        entities = enrich_entities_with_registry(entities, registry)
    group = group.strip().upper()
    terms = [x.lower() for x in q.split() if x.strip()]
    out = []
    for e in entities:
        if group and e['semantic_group'] != group:
            continue
        if terms:
            hay = ' '.join([e['display_name'], e['folder_root'], ' '.join(e['role_counts'])]).lower()
            if not all(t in hay for t in terms):
                continue
        out.append(e)
    out = out[: max(1, min(2000, int(limit)))]
    counts = Counter(x['semantic_group'] for x in entities)
    return {
        'format': 'PT_LIVE_ENTITY_CATALOG_V1',
        'status': 'PASS',
        'policy': {
            'identity': 'physical folder + live client evidence',
            'runtime': 'UNPROVEN unless separately validated',
            'writer': 'UNAUTHORIZED unless separately certified',
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
    """Return one entity with detailed registry/physical dependency evidence."""
    wanted = str(entity_key or '').strip()
    if not wanted:
        return None
    entities = build_live_entities(list(rows), seed)
    found = next((e for e in entities if str(e.get('entity_key')) == wanted), None)
    if found is None:
        return None
    if registry is not None:
        found = enrich_entities_with_registry(
            [found], registry, include_assets=True, include_physical=True
        )[0]
    return {
        'format': 'PT_LIVE_ENTITY_DETAIL_V1',
        'status': 'PASS',
        'entity': found,
        'policy': {
            'folder_identity_is_runtime_evidence': False,
            'registry_binding_is_runtime_certification': False,
            'writer_requires_separate_certification': True,
        },
        'client_modified': False,
    }
