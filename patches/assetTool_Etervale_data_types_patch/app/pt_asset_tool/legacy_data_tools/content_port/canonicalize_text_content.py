#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from materialize_localization_catalog import build_catalog

SCHEMA_VERSION = 1
INCLUDED_KINDS = {
    'monster_definition',
    'npc_definition',
    'open_item_definition',
    'localization_resource',
    'sin_resource',
    'message_catalog',
}
GAMEPLAY_CONFIGS = {
    'servidor/configs/skill/mech.ini',
    'servidor/configs/skill/fighter.ini',
    'servidor/configs/skill/archer.ini',
    'servidor/configs/skill/pike.ini',
    'servidor/configs/skill/atalanta.ini',
    'servidor/configs/skill/knight.ini',
    'servidor/configs/skill/mage.ini',
    'servidor/configs/skill/sacer.ini',
    'servidor/configs/companion.ini',
    'servidor/configs/bellatra.ini',
}
UI_TEXT_CONFIGS = {
    'cliente/image/clanimage/help/autohelp/levelup_content.ini',
    'cliente/image/clanimage/help/autohelp/levelsubj.ini',
}
UI_TEXT_FILES = {
    'cliente/image/sinimage/petdata/petmessage.txt',
    'cliente/image/sinimage/help/mothersday.json',
}
MUTABLE_OR_MIXED_CONFIGS = {
    'servidor/configs/expmanager.ini': 'runtime_mutable',
    'servidor/configs/sistemas.ini': 'runtime_mutable',
    'servidor/configs/hotuk.ini': 'mixed_operational_gameplay',
}


def norm(path: str) -> str:
    s = path.replace('\\', '/').strip()
    parts = []
    for p in s.split('/'):
        if not p or p == '.':
            continue
        if p == '..':
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return '/'.join(parts)


def runtime_path(source_path: str) -> str:
    s = norm(source_path)
    low = s.casefold()
    if low.startswith('servidor/'):
        return s[len('Servidor/'):]
    if low.startswith('cliente/'):
        return s[len('cliente/'):]
    return s


def slug(value: str) -> str:
    value = value.strip().casefold()
    value = re.sub(r'[^a-z0-9]+', '_', value)
    return value.strip('_') or 'unnamed'


def canonical_id(doc: dict) -> str:
    path = norm(doc['source']['path'])
    low = path.casefold()
    kind = doc['kind']
    # Explicitly disambiguate the historically colliding NPCs.
    if low.endswith('/gameserver/npc/donation box.npc'):
        return 'npc.donation_box'
    if low.endswith('/gameserver/npc/donation-box.npc'):
        return 'npc.donation_box_legacy_alt'
    existing = doc.get('id')
    if existing:
        return existing
    stem = PurePosixPath(path).stem
    prefix = {
        'monster_definition': 'monster',
        'npc_definition': 'npc',
        'open_item_definition': 'item',
        'localization_resource': 'loc',
        'sin_resource': 'text',
        'message_catalog': 'text',
        'ini_config': 'config',
    }.get(kind, 'text')
    return f'{prefix}.{slug(stem)}'


def parse_ini_lines(lines: list[str]) -> dict:
    section = ''
    entries = []
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or s.startswith(';') or s.startswith('#'):
            continue
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip()
            continue
        if '=' in raw:
            key, value = raw.split('=', 1)
            entries.append({'line': i, 'section': section, 'key': key.strip(), 'value': value.strip()})
        else:
            entries.append({'line': i, 'section': section, 'key': '', 'value': raw})
    return {'entries': entries}


def resource_aliases(source_path: str) -> list[str]:
    aliases = [norm(source_path), runtime_path(source_path)]
    # Client and server historically address the same Bellatra config by two paths.
    if norm(source_path).casefold() == 'servidor/configs/bellatra.ini':
        aliases.append('Bellatra/bellatra.ini')
    # The legacy source uses both slash styles and inconsistent case. Runtime
    # lookup is case-insensitive and slash-normalized, so one semantic alias is
    # enough. Keep source path too for diagnostics/tools.
    out = []
    seen = set()
    for a in aliases:
        k = a.casefold()
        if k not in seen:
            out.append(a)
            seen.add(k)
    return out


def is_selected(doc: dict) -> tuple[bool, str]:
    kind = doc['kind']
    path = norm(doc['source']['path']).casefold()
    if kind in INCLUDED_KINDS:
        return True, 'runtime_text_family'
    if kind == 'ini_config' and path in GAMEPLAY_CONFIGS:
        return True, 'immutable_gameplay_config'
    if kind == 'ini_config' and path in UI_TEXT_CONFIGS:
        return True, 'ui_text_config'
    if kind == 'generic_text' and path in UI_TEXT_FILES:
        return True, 'ui_text_resource'
    return False, ''


def main() -> None:
    ap = argparse.ArgumentParser(description='Build canonical JSON UTF-8 authoring tree from the lossless shadow import')
    ap.add_argument('--shadow', type=Path, required=True)
    ap.add_argument('--corpus', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    shadow = args.shadow.resolve()
    corpus = args.corpus.resolve()
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / 'resources').mkdir(parents=True)

    index = json.loads((shadow / 'index.json').read_text(encoding='utf-8'))['documents']
    docs = []
    excluded = Counter()
    exclusion_examples = defaultdict(list)
    id_to_paths = defaultdict(list)

    for entry in index:
        shadow_doc = json.loads((shadow / entry['json_path']).read_text(encoding='utf-8'))
        selected, reason = is_selected(shadow_doc)
        source_path = norm(shadow_doc['source']['path'])
        low = source_path.casefold()
        if not selected:
            why = MUTABLE_OR_MIXED_CONFIGS.get(low, 'outside_runtime_text_scope')
            excluded[why] += 1
            if len(exclusion_examples[why]) < 20:
                exclusion_examples[why].append(source_path)
            continue

        raw_path = corpus / Path(*PurePosixPath(source_path).parts)
        if not raw_path.is_file():
            raise FileNotFoundError(f'canonical source is missing from corpus: {source_path}')
        raw = raw_path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected_sha = shadow_doc['source']['sha256']
        if actual_sha != expected_sha:
            raise ValueError(f'corpus/shadow SHA mismatch for {source_path}')

        cid = canonical_id(shadow_doc)
        id_to_paths[cid].append(source_path)
        semantic = {}
        content = shadow_doc.get('content', {})
        if shadow_doc['kind'] in ('monster_definition', 'npc_definition', 'open_item_definition'):
            semantic = {
                'fields': content.get('fields', {}),
                'directives': content.get('directives', []),
                'unknown_tokens': content.get('unknown_tokens', {}),
            }
        elif shadow_doc['kind'] == 'localization_resource':
            semantic = {'entries': content.get('entries', [])}
        elif shadow_doc['kind'] in ('sin_resource', 'message_catalog', 'generic_text'):
            semantic = {'lines': content.get('lines', [])}
        elif shadow_doc['kind'] == 'ini_config':
            semantic = parse_ini_lines(content.get('lines', []))

        canon = {
            'schema': 'summit.canonical-text-resource/v1',
            'schema_version': SCHEMA_VERSION,
            'id': cid,
            'kind': shadow_doc['kind'],
            'selection_reason': reason,
            'runtime_paths': resource_aliases(source_path),
            'source': {
                'legacy_path': source_path,
                'legacy_sha256': actual_sha,
                'legacy_size': len(raw),
            },
            'semantic': semantic,
            # Compatibility envelope. This is intentionally stored in JSON so
            # subsequent pack builds no longer need any proprietary text file.
            # It may be retired family-by-family after every legacy parser is
            # replaced by a direct semantic adapter.
            'compatibility': {
                'encoding': 'base64',
                'legacy_payload_base64': base64.b64encode(raw).decode('ascii'),
            },
        }
        docs.append(canon)

    # Collapse corpus duplicates that differ only by path casing. The original
    # archive contains a small number of such duplicates (for example
    # GameServer/... and gameserver/...) with byte-identical content. Windows
    # resolves them as the same runtime path, so they are one canonical resource
    # with multiple provenance aliases rather than two IDs.
    merged = {}
    for d in docs:
        runtime_key = norm(runtime_path(d['source']['legacy_path'])).casefold()
        key = (d['kind'], runtime_key)
        old = merged.get(key)
        if old is None:
            merged[key] = d
            continue
        if old['source']['legacy_sha256'] != d['source']['legacy_sha256']:
            raise ValueError(f'case-insensitive runtime path collision with different payloads: {old["source"]["legacy_path"]} vs {d["source"]["legacy_path"]}')
        aliases = old['source'].setdefault('legacy_aliases', [old['source']['legacy_path']])
        if d['source']['legacy_path'] not in aliases:
            aliases.append(d['source']['legacy_path'])
        for alias in d['runtime_paths']:
            if alias.casefold() not in {x.casefold() for x in old['runtime_paths']}:
                old['runtime_paths'].append(alias)
    docs = list(merged.values())

    # Recompute proposed-ID collisions after duplicate-path collapsing.
    id_to_paths = defaultdict(list)
    for d in docs:
        id_to_paths[d['id']].append(d['source']['legacy_path'])

    # Resolve accidental IDs deterministically. Explicit overrides above remain
    # readable; all other collisions receive a stable path hash suffix.
    collisions = {k: v for k, v in id_to_paths.items() if len(v) > 1}
    if collisions:
        by_path = {d['source']['legacy_path']: d for d in docs}
        for cid, paths in collisions.items():
            for path in sorted(paths, key=str.casefold):
                d = by_path[path]
                h = hashlib.sha256(path.casefold().encode('utf-8')).hexdigest()[:10]
                d['id'] = f'{cid}.path_{h}'

    docs.sort(key=lambda d: (d['kind'], d['source']['legacy_path'].casefold()))
    manifest = []
    id_seen = set()
    path_seen = {}
    for d in docs:
        if d['id'] in id_seen:
            raise ValueError(f'duplicate canonical id after disambiguation: {d["id"]}')
        id_seen.add(d['id'])
        for alias in d['runtime_paths']:
            key = norm(alias).casefold()
            previous = path_seen.get(key)
            if previous and previous != d['id']:
                raise ValueError(f'conflicting runtime path {alias}: {previous} vs {d["id"]}')
            path_seen[key] = d['id']

        rel = PurePosixPath(d['source']['legacy_path'] + '.json')
        dest = out / 'resources' / Path(*rel.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        manifest.append({
            'id': d['id'],
            'kind': d['kind'],
            'legacy_path': d['source']['legacy_path'],
            'json_path': dest.relative_to(out).as_posix(),
            'runtime_paths': d['runtime_paths'],
            'legacy_sha256': d['source']['legacy_sha256'],
        })

    counts = Counter(d['kind'] for d in docs)
    report = {
        'schema': 'summit.canonical-text-report/v1',
        'schema_version': 1,
        'resources': len(docs),
        'families': dict(sorted(counts.items())),
        'runtime_aliases': len(path_seen),
        'canonical_ids': len(id_seen),
        'id_collisions_resolved': collisions,
        'gameplay_configs_packed': sorted(GAMEPLAY_CONFIGS),
        'ui_text_configs_packed': sorted(UI_TEXT_CONFIGS),
        'ui_text_files_packed': sorted(UI_TEXT_FILES),
        'mutable_or_mixed_configs_kept_external': MUTABLE_OR_MIXED_CONFIGS,
        'excluded_counts': dict(excluded),
        'excluded_examples': dict(exclusion_examples),
    }
    (out / 'index.json').write_text(json.dumps({'schema': 'summit.canonical-text-index/v1', 'documents': manifest}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    localization_report = build_catalog(out)
    report['localization'] = localization_report
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'resources': len(docs), 'families': dict(counts), 'aliases': len(path_seen), 'localization_keys': localization_report['keys'], 'out': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
