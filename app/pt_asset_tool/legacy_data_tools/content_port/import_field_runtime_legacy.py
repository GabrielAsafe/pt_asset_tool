#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path, PurePosixPath
from typing import Any

from active_tokens import load_active_token_sets
from import_corpus import parse_directive_document, parse_localization
from source_tokens import load_source_token_maps

SPP_RECORD_COUNT = 200
SPP_RECORD_SIZE = 12
SPP_FILE_SIZE = SPP_RECORD_COUNT * SPP_RECORD_SIZE
SPC_RECORD_COUNT = 100
SPC_RECORD_SIZE = 504
SPC_FILE_SIZE = SPC_RECORD_COUNT * SPC_RECORD_SIZE
SCFG_HEADER = struct.Struct('<4sHH10I32s')
SCFG_RECORD = struct.Struct('<5I')
SCFG_DIRECTIVE = struct.Struct('<3I')
SCFG_KIND_NPC = 2

# These legacy fixed-NPC placements were explicitly approved for removal during
# the Field runtime migration.  Their definition files are absent from the
# canonical source, deployed SCFG packs, and legacy server tree, so retaining
# them would create dangling runtime references.  Keep this list exact: any
# other unresolved SPC row must still fail migration.
APPROVED_DROPPED_FIXED_NPC_PATHS = {
    'gameserver/npc/battle-equip.npc',
    'gameserver/npc/battle-magic.npc',
    'gameserver/npc/eragonteleport.npc',
    'gameserver/npc/salinha1.npc',
    'gameserver/npc/salinha2.npc',
    'gameserver/npc/salinha3.npc',
    'gameserver/npc/salinha4.npc',
    'gameserver/npc/salinha5.npc',
    'gameserver/npc/salinha6.npc',
    'gameserver/npc/salinha7.npc',
    'gameserver/npc/salinha8.npc',
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


HASH_UNICODE = re.compile(r'#u([0-9a-f]{4})', re.IGNORECASE)


def decode_legacy_escaped_unicode(value: str) -> str:
    # The canonical text migration encoded a handful of non-ASCII filename
    # characters as #Uxxxx (for example S#U00e1bio).  The legacy SPC stores
    # the real Unicode path.  Treat both spellings as the same runtime key.
    return HASH_UNICODE.sub(lambda m: chr(int(m.group(1), 16)), str(value or ''))


def normalize_runtime_path(value: str) -> str:
    text = decode_legacy_escaped_unicode(str(value or '')).replace('\\', '/').strip().lstrip('/')
    while text.startswith('./'):
        text = text[2:]
    if text.casefold().startswith('servidor/'):
        text = text[len('Servidor/'):]
    parts = [p for p in text.split('/') if p and p != '.']
    return '/'.join(parts).casefold()


def decode_cstr(data: bytes) -> str:
    raw = data.split(b'\0', 1)[0]
    for enc in ('utf-8', 'cp949', 'cp1252', 'latin1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('latin1', errors='replace')


def slug_for_field(path: Path) -> str:
    name = path.name
    lower = name.casefold()
    for suffix in ('.spp', '.spc'):
        if lower.endswith(suffix):
            name = name[:-len(suffix)]
            break
    if name.casefold().endswith('.ase'):
        name = name[:-4]
    slug = re.sub(r'[^a-z0-9]+', '_', name.casefold()).strip('_')
    return slug or 'field'


def load_npc_path_index(canonical_text: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    index = json.loads((canonical_text / 'index.json').read_text(encoding='utf-8'))
    path_to_id: dict[str, str] = {}
    id_to_paths: dict[str, list[str]] = {}
    for entry in index.get('documents', []):
        if entry.get('kind') != 'npc_definition':
            continue
        cid = str(entry.get('id') or '')
        paths: list[str] = []
        for key in ('runtime_paths',):
            for p in entry.get(key) or []:
                if p:
                    paths.append(str(p))
        if entry.get('legacy_path'):
            paths.append(str(entry['legacy_path']))
        unique: list[str] = []
        seen = set()
        for p in paths:
            norm = normalize_runtime_path(p)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            unique.append(p)
            previous = path_to_id.get(norm)
            if previous and previous != cid:
                raise ValueError(f'NPC runtime path maps to multiple canonical IDs: {p}: {previous}/{cid}')
            path_to_id[norm] = cid
        id_to_paths[cid] = unique
    return path_to_id, id_to_paths


def slug(value: str) -> str:
    value = decode_legacy_escaped_unicode(value).strip().casefold()
    value = re.sub(r'[^a-z0-9]+', '_', value).strip('_')
    return value or 'unnamed'


def runtime_paths_for_source(source_path: str) -> list[str]:
    source_path = source_path.replace('\\', '/')
    out = [source_path]
    if source_path.casefold().startswith('servidor/'):
        out.append(source_path[len('Servidor/'):])
    result: list[str] = []
    seen = set()
    for item in out:
        # Keep both provenance path (Servidor/...) and runtime path
        # (GameServer/...).  compile_definitions intentionally prefers the
        # latter; collapsing them here would produce an unusable SCFG alias.
        key = item.casefold()
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def load_canonical_index(canonical_text: Path) -> tuple[dict[str, Any], set[str], dict[str, str]]:
    data = json.loads((canonical_text / 'index.json').read_text(encoding='utf-8'))
    ids: set[str] = set()
    aliases: dict[str, str] = {}
    for entry in data.get('documents', []):
        cid = str(entry.get('id') or '')
        if cid:
            ids.add(cid)
        for p in entry.get('runtime_paths') or []:
            if p:
                aliases[normalize_runtime_path(str(p))] = cid
        if entry.get('legacy_path'):
            aliases[normalize_runtime_path(str(entry['legacy_path']))] = cid
    return data, ids, aliases


def unique_id(prefix: str, stem: str, source_path: str, used_ids: set[str]) -> str:
    base = f'{prefix}.{slug(stem)}'
    if base not in used_ids:
        used_ids.add(base)
        return base
    suffix = hashlib.sha256(source_path.casefold().encode('utf-8')).hexdigest()[:10]
    candidate = f'{base}.path_{suffix}'
    counter = 2
    while candidate in used_ids:
        candidate = f'{base}.path_{suffix}_{counter}'
        counter += 1
    used_ids.add(candidate)
    return candidate


def canonical_entry(doc: dict[str, Any], json_path: str) -> dict[str, Any]:
    return {
        'id': doc['id'],
        'kind': doc['kind'],
        'legacy_path': doc['source']['legacy_path'],
        'json_path': json_path,
        'runtime_paths': doc['runtime_paths'],
        'legacy_sha256': doc['source']['legacy_sha256'],
    }


def make_npc_doc(raw: bytes, source_path: str, cid: str, source_root: Path) -> dict[str, Any]:
    token_maps = load_source_token_maps(source_root)
    active = load_active_token_sets(source_root)
    parsed = parse_directive_document(raw, token_maps['character'], active['character'])
    return {
        'schema': 'summit.canonical-text-resource/v1',
        'schema_version': 1,
        'id': cid,
        'kind': 'npc_definition',
        'selection_reason': 'runtime_text_family',
        'runtime_paths': runtime_paths_for_source(source_path),
        'source': {
            'legacy_path': source_path,
            'legacy_sha256': sha256_bytes(raw),
            'legacy_size': len(raw),
        },
        'semantic': {
            'fields': parsed.get('fields', {}),
            'directives': parsed.get('directives', []),
            'unknown_tokens': parsed.get('unknown_tokens', {}),
        },
        'compatibility': {
            'encoding': 'base64',
            'legacy_payload_base64': base64.b64encode(raw).decode('ascii'),
        },
    }


def make_localization_doc(raw: bytes, source_path: str, cid: str) -> dict[str, Any]:
    parsed = parse_localization(raw)
    return {
        'schema': 'summit.canonical-text-resource/v1',
        'schema_version': 1,
        'id': cid,
        'kind': 'localization_resource',
        'selection_reason': 'runtime_text_family',
        'runtime_paths': runtime_paths_for_source(source_path),
        'source': {
            'legacy_path': source_path,
            'legacy_sha256': sha256_bytes(raw),
            'legacy_size': len(raw),
        },
        'semantic': {'entries': parsed.get('entries', [])},
        'compatibility': {
            'encoding': 'base64',
            'legacy_payload_base64': base64.b64encode(raw).decode('ascii'),
        },
    }


def legacy_file_index(server: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    npc_root = server / 'GameServer' / 'NPC'
    if not npc_root.is_dir():
        return result
    for path in npc_root.rglob('*'):
        if not path.is_file():
            continue
        logical = 'GameServer/NPC/' + path.relative_to(npc_root).as_posix()
        key = normalize_runtime_path(logical)
        previous = result.get(key)
        if previous is not None and previous != path:
            raise ValueError(f'case-insensitive legacy NPC path collision: {previous} / {path}')
        result[key] = path
    return result


def linked_runtime_path(definition_path: str, linked_value: str) -> str:
    parent = PurePosixPath(definition_path.replace('\\', '/')).parent
    return (parent / PurePosixPath(str(linked_value).replace('\\', '/'))).as_posix()


def scfg_candidates(repo: Path, server: Path) -> list[Path]:
    paths = [
        server / 'Content' / 'packs' / 'definitions_server.scfg',
        repo / 'SourceCode' / 'Content' / 'packs' / 'definitions_server.scfg',
        repo / 'cliente' / 'Content' / 'packs' / 'definitions_server.scfg',
    ]
    out: list[Path] = []
    seen = set()
    for path in paths:
        key = str(path).casefold()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        out.append(path)
    return out


def parse_scfg_npc_records(path: Path) -> dict[str, dict[str, Any]]:
    data = path.read_bytes()
    if len(data) < SCFG_HEADER.size:
        raise ValueError(f'SCFG too small: {path}')
    (magic, version, flags, record_count, record_offset, record_size,
     directive_count, directive_offset, directive_size, string_offset, string_size,
     reserved0, reserved1, digest) = SCFG_HEADER.unpack_from(data, 0)
    if magic != b'SCFG' or version != 1 or flags or reserved0 or reserved1:
        raise ValueError(f'invalid SCFG header: {path}')
    if record_size != SCFG_RECORD.size or directive_size != SCFG_DIRECTIVE.size:
        raise ValueError(f'invalid SCFG record sizes: {path}')
    if record_offset != SCFG_HEADER.size:
        raise ValueError(f'non-canonical SCFG record offset: {path}')
    if directive_offset != record_offset + record_count * record_size:
        raise ValueError(f'non-canonical SCFG directive offset: {path}')
    if string_offset != directive_offset + directive_count * directive_size:
        raise ValueError(f'non-canonical SCFG string offset: {path}')
    if string_offset + string_size != len(data):
        raise ValueError(f'non-canonical SCFG total size: {path}')
    if hashlib.sha256(data[record_offset:]).digest() != digest:
        raise ValueError(f'SCFG body hash mismatch: {path}')

    string_end = string_offset + string_size

    def raw_string(offset: int) -> bytes:
        if offset >= string_size:
            raise ValueError(f'SCFG string offset out of range: {path}: {offset}')
        start = string_offset + offset
        end = data.find(b'\0', start, string_end)
        if end < 0:
            raise ValueError(f'unterminated SCFG string: {path}: {offset}')
        return data[start:end]

    out: dict[str, dict[str, Any]] = {}
    for index in range(record_count):
        path_off, id_off, kind, directive_start, directive_len = SCFG_RECORD.unpack_from(
            data, record_offset + index * record_size
        )
        if kind != SCFG_KIND_NPC:
            continue
        if directive_start + directive_len > directive_count:
            raise ValueError(f'SCFG directive range out of bounds: {path}: record {index}')
        logical_path = raw_string(path_off).decode('utf-8')
        content_id = raw_string(id_off).decode('utf-8')
        lines: list[bytes] = []
        for offset in range(directive_len):
            command_off, values_off, _directive_flags = SCFG_DIRECTIVE.unpack_from(
                data, directive_offset + (directive_start + offset) * directive_size
            )
            command = raw_string(command_off)
            values = raw_string(values_off)
            lines.append(command + (b'\t' + values if values else b''))
        payload = b'\r\n'.join(lines) + (b'\r\n' if lines else b'')
        key = normalize_runtime_path(logical_path)
        previous = out.get(key)
        row = {
            'path': logical_path,
            'id': content_id,
            'payload': payload,
            'pack_path': str(path),
        }
        if previous is not None and previous['id'] != content_id:
            raise ValueError(f'SCFG NPC path collision: {logical_path}: {previous["id"]}/{content_id}')
        out[key] = row
    return out


def load_scfg_npc_index(repo: Path, server: Path) -> dict[str, dict[str, Any]]:
    # Candidate order is trust order: the deployed server pack is the strongest
    # evidence of what runtime currently uses, followed by the source build pack.
    # A stale/missing secondary pack must never block recovery from a stronger one.
    merged: dict[str, dict[str, Any]] = {}
    for pack in scfg_candidates(repo, server):
        try:
            rows = parse_scfg_npc_records(pack)
        except (OSError, ValueError):
            continue
        for key, row in rows.items():
            if key not in merged:
                merged[key] = row
    return merged


def plan_missing_npc_imports(
    unresolved: list[dict[str, Any]],
    repo: Path,
    server: Path,
    canonical_text: Path,
    source_root: Path,
    npc_paths: dict[str, str],
) -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    index_data, used_ids, all_aliases = load_canonical_index(canonical_text)
    files = legacy_file_index(server)
    packed_npcs = load_scfg_npc_index(repo, server)
    planned_docs: list[tuple[Path, dict[str, Any]]] = []
    planned_entries: list[dict[str, Any]] = []
    missing_files: list[dict[str, Any]] = []
    missing_links: list[dict[str, Any]] = []
    planned_by_alias: dict[str, str] = {}

    def add_doc(doc: dict[str, Any]) -> None:
        source_path = doc['source']['legacy_path']
        rel = PurePosixPath(source_path + '.json')
        target = canonical_text / 'resources' / Path(*rel.parts)
        json_path = target.relative_to(canonical_text).as_posix()
        planned_docs.append((target, doc))
        planned_entries.append(canonical_entry(doc, json_path))
        for alias in doc['runtime_paths']:
            key = normalize_runtime_path(alias)
            all_aliases[key] = doc['id']
            planned_by_alias[key] = doc['id']

    # First pass: import only exact legacy definitions that are absent from the
    # canonical path index.  Never collapse two legacy NPC files merely because
    # their model/name happens to match.
    for row in unresolved:
        definition_path = str(row.get('legacy_definition_path') or '')
        key = normalize_runtime_path(definition_path)
        if not key or key in npc_paths or key in planned_by_alias:
            continue
        legacy = files.get(key)
        packed = packed_npcs.get(key)
        if legacy is None and packed is None:
            problem = dict(row)
            problem['reason'] = 'definition_missing_from_canonical_deployed_scfg_and_legacy_tree'
            missing_files.append(problem)
            continue

        recovered_from_pack = legacy is None and packed is not None
        if recovered_from_pack:
            source_path = 'Servidor/' + definition_path.replace('\\', '/').lstrip('/')
            raw = packed['payload']
            preferred_id = str(packed.get('id') or '')
            if preferred_id and preferred_id not in used_ids:
                cid = preferred_id
                used_ids.add(cid)
            else:
                cid = unique_id('npc', PurePosixPath(definition_path.replace('\\', '/')).stem, source_path, used_ids)
            npc_doc = make_npc_doc(raw, source_path, cid, source_root)
            # The SCFG already contains linked localization flattened into the
            # directive stream.  Keeping it inline is byte-semantic equivalent
            # for future SCFG builds and avoids inventing a missing .zhoon file.
            add_doc(npc_doc)
            npc_paths[key] = cid
            continue

        source_path = 'Servidor/' + legacy.relative_to(server).as_posix()
        raw = legacy.read_bytes()
        cid = unique_id('npc', legacy.stem, source_path, used_ids)
        npc_doc = make_npc_doc(raw, source_path, cid, source_root)
        add_doc(npc_doc)
        npc_paths[key] = cid

        # Import the linked .zhoon too when this definition switches to one.
        for directive in npc_doc['semantic']['directives']:
            if directive.get('key') != 'linked_file':
                continue
            values = directive.get('values') or []
            if not values:
                break
            linked_logical = linked_runtime_path(definition_path, str(values[0]))
            linked_key = normalize_runtime_path(linked_logical)
            if linked_key in all_aliases:
                break
            linked_file = files.get(linked_key)
            if linked_file is None:
                missing_links.append({
                    'npc_id': cid,
                    'definition_path': definition_path,
                    'linked_path': linked_logical,
                    'reason': 'linked_localization_missing_from_canonical_and_legacy_tree',
                })
                break
            linked_source = 'Servidor/' + linked_file.relative_to(server).as_posix()
            linked_id = unique_id('text', linked_file.stem, linked_source, used_ids)
            add_doc(make_localization_doc(linked_file.read_bytes(), linked_source, linked_id))
            break

    return planned_docs, planned_entries, npc_paths, missing_files + missing_links


def commit_canonical_imports(canonical_text: Path, docs: list[tuple[Path, dict[str, Any]]], entries: list[dict[str, Any]]) -> None:
    if not docs:
        return
    index_path = canonical_text / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    existing_paths = {str(x.get('json_path')) for x in index.get('documents', [])}
    for target, doc in docs:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for entry in entries:
        if entry['json_path'] not in existing_paths:
            index.setdefault('documents', []).append(entry)
            existing_paths.add(entry['json_path'])
    index['documents'].sort(key=lambda e: (str(e.get('kind', '')), str(e.get('legacy_path', '')).casefold()))
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def parse_spp(path: Path, logical_path: str) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) != SPP_FILE_SIZE:
        raise ValueError(f'non-canonical SPP size: {path}: {len(data)} != {SPP_FILE_SIZE}')
    points = []
    for slot in range(SPP_RECORD_COUNT):
        state, x, z = struct.unpack_from('<iii', data, slot * SPP_RECORD_SIZE)
        if state:
            points.append({'slot': slot, 'state': state, 'x': x, 'z': z})
    slug = slug_for_field(path)
    return {
        'schema': 'summit.stage-start-points/v1',
        'id': f'start_points.{slug}',
        'logical_path': logical_path,
        'points': points,
        'provenance': {
            'source': logical_path,
            'legacy_size': len(data),
            'legacy_sha256': sha256_bytes(data),
        },
    }


def split_approved_dropped_fixed_npcs(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unresolved: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        key = normalize_runtime_path(str(row.get('legacy_definition_path') or ''))
        if key in APPROVED_DROPPED_FIXED_NPC_PATHS:
            item = dict(row)
            item['reason'] = 'explicitly_removed_missing_legacy_fixed_npc'
            dropped.append(item)
        else:
            unresolved.append(row)
    return unresolved, dropped


def parse_spc(path: Path, logical_path: str, npc_paths: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = path.read_bytes()
    if len(data) != SPC_FILE_SIZE:
        raise ValueError(f'non-canonical SPC size: {path}: {len(data)} != {SPC_FILE_SIZE}')
    npcs = []
    unresolved = []
    for slot in range(SPC_RECORD_COUNT):
        rec = data[slot * SPC_RECORD_SIZE:(slot + 1) * SPC_RECORD_SIZE]
        _size, code_u32 = struct.unpack_from('<iI', rec, 0)
        if not code_u32:
            continue
        definition_path = decode_cstr(rec[104:164])
        normalized = normalize_runtime_path(definition_path)
        npc_id = npc_paths.get(normalized)
        tail = struct.unpack_from('<I7i', rec, 472)
        row = {
            'slot': slot,
            'npc_id': npc_id or '',
            'x': tail[1], 'y': tail[2], 'z': tail[3],
            'ax': tail[4], 'ay': tail[5], 'az': tail[6], 'state': tail[7],
        }
        if not npc_id:
            unresolved.append({
                'slot': slot,
                'logical_path': logical_path,
                'legacy_definition_path': definition_path,
                'legacy_name': decode_cstr(rec[8:40]),
                'legacy_model_ini': decode_cstr(rec[40:104]),
                'code_u32': code_u32,
            })
        else:
            npcs.append(row)
    slug = slug_for_field(path)
    doc = {
        'schema': 'summit.fixed-npcs/v1',
        'id': f'fixed_npcs.{slug}',
        'logical_path': logical_path,
        'npcs': npcs,
        'provenance': {
            'source': logical_path,
            'legacy_size': len(data),
            'legacy_sha256': sha256_bytes(data),
        },
    }
    return doc, unresolved


def iter_files(field_root: Path, suffix: str) -> list[Path]:
    return sorted(
        (p for p in field_root.rglob('*') if p.is_file() and p.suffix.casefold() == suffix),
        key=lambda p: p.relative_to(field_root).as_posix().casefold(),
    )


def write_family(root: Path, subdir: str, schema: str, docs: list[dict[str, Any]]) -> None:
    if root.exists():
        shutil.rmtree(root)
    base = root / subdir / 'GameServer' / 'Field'
    base.mkdir(parents=True, exist_ok=True)
    index_docs = []
    for doc in docs:
        filename = PurePosixPath(doc['logical_path']).name + '.json'
        target = base / filename
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        rel = target.relative_to(root).as_posix()
        index_docs.append({'id': doc['id'], 'logical_path': doc['logical_path'], 'json_path': rel})
    index = {'schema': schema, 'documents': index_docs}
    (root / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser(description='Import legacy GameServer/Field SPP/SPC files into editable Summit canonical JSON')
    ap.add_argument('--repo-root', type=Path, default=here.parents[3])
    ap.add_argument('--server-root', type=Path, default=None, help='Server tree containing GameServer/Field (default: <repo>/Servidor)')
    ap.add_argument('--canonical-root', type=Path, default=None, help='Canonical root (default: <repo>/SourceCode/Content/canonical)')
    ap.add_argument('--allow-unresolved-npcs', action='store_true', help='Write resolved rows and report unresolved active SPC rows instead of failing')
    args = ap.parse_args()

    repo = args.repo_root.expanduser().resolve()
    server = (args.server_root or (repo / 'Servidor')).expanduser().resolve()
    canonical = (args.canonical_root or (repo / 'SourceCode/Content/canonical')).expanduser().resolve()
    field_root = server / 'GameServer' / 'Field'
    canonical_text = canonical / 'text'
    if not field_root.is_dir():
        raise SystemExit(f'missing legacy field root: {field_root}')
    if not (canonical_text / 'index.json').is_file():
        raise SystemExit(f'missing canonical text index: {canonical_text / "index.json"}')

    npc_paths, _ = load_npc_path_index(canonical_text)
    spp_docs = []
    spc_docs = []
    unresolved: list[dict[str, Any]] = []
    spp_files = iter_files(field_root, '.spp')
    spc_files = iter_files(field_root, '.spc')
    if not spp_files and not spc_files:
        raise SystemExit(
            'no legacy SPP/SPC files remain to import; canonical field JSON is already the source of truth. '
            'Use consolidate_canonical_content.py for subsequent rebuilds.'
        )

    for path in spp_files:
        logical = 'GameServer/Field/' + path.relative_to(field_root).as_posix()
        spp_docs.append(parse_spp(path, logical))
    for path in spc_files:
        logical = 'GameServer/Field/' + path.relative_to(field_root).as_posix()
        doc, missing = parse_spc(path, logical, npc_paths)
        spc_docs.append(doc)
        unresolved.extend(missing)

    unresolved, dropped_fixed_npcs = split_approved_dropped_fixed_npcs(unresolved)

    imported_docs: list[tuple[Path, dict[str, Any]]] = []
    imported_entries: list[dict[str, Any]] = []
    import_problems: list[dict[str, Any]] = []
    if unresolved:
        imported_docs, imported_entries, npc_paths, import_problems = plan_missing_npc_imports(
            unresolved, repo, server, canonical_text, repo / 'SourceCode', npc_paths
        )

        # Re-parse every SPC with the expanded identity map.  This also resolves
        # canonical #Uxxxx filename escapes without creating duplicate NPCs.
        spc_docs = []
        unresolved = []
        for path in spc_files:
            logical = 'GameServer/Field/' + path.relative_to(field_root).as_posix()
            doc, missing = parse_spc(path, logical, npc_paths)
            spc_docs.append(doc)
            unresolved.extend(missing)
        unresolved, dropped_fixed_npcs = split_approved_dropped_fixed_npcs(unresolved)

    if (unresolved or import_problems) and not args.allow_unresolved_npcs:
        print(json.dumps({
            'status': 'FAIL',
            'unresolved_fixed_npcs': unresolved,
            'dropped_legacy_fixed_npcs': dropped_fixed_npcs,
            'canonical_import_problems': import_problems,
        }, ensure_ascii=False, indent=2))
        return 1

    # Only commit the recovered NPC/text definitions after every active SPC row
    # can be represented.  A failed migration therefore leaves canonical JSON
    # untouched, just like the original importer.
    if not unresolved and not import_problems:
        commit_canonical_imports(canonical_text, imported_docs, imported_entries)

    if spp_files:
        write_family(canonical / 'stage_start_points', 'points', 'summit.stage-start-points-index/v1', spp_docs)
    if spc_files:
        write_family(canonical / 'fixed_npcs', 'npcs', 'summit.fixed-npcs-index/v1', spc_docs)
    report = {
        'status': 'PASS' if not unresolved else 'REVIEW',
        'stage_start_point_maps': len(spp_docs),
        'fixed_npc_maps': len(spc_docs),
        'active_start_points': sum(len(x['points']) for x in spp_docs),
        'fixed_npcs': sum(len(x['npcs']) for x in spc_docs),
        'canonical_npc_or_text_resources_imported': len(imported_docs) if not unresolved and not import_problems else 0,
        'canonical_imported_resources': [
            {'id': doc['id'], 'kind': doc['kind'], 'legacy_path': doc['source']['legacy_path']}
            for _target, doc in imported_docs
        ] if not unresolved and not import_problems else [],
        'unresolved_fixed_npcs': unresolved,
        'dropped_legacy_fixed_npcs': dropped_fixed_npcs,
        'canonical_import_problems': import_problems,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not unresolved or args.allow_unresolved_npcs else 1


if __name__ == '__main__':
    raise SystemExit(main())
