#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import runpy
import sys
import tempfile
from pathlib import Path
from typing import Any

FIELD_MAGIC = b'SFLD'
FIELD_VERSION = 1
FIELD_HEADER = struct.Struct('<4sHHIIIIII32s')  # 64 bytes
FIELD_SECTION = struct.Struct('<4sHHII32s')      # 48 bytes

SPPT_MAGIC = b'SPPT'
SPPT_VERSION = 1
SPPT_HEADER = struct.Struct('<4sHHIIIIII32s')    # 64 bytes
SPPT_MAP = struct.Struct('<IIII')                # path,id,start,count
SPPT_POINT = struct.Struct('<Iiii')              # slot,state,x,z

SPCN_MAGIC = b'SPCN'
SPCN_VERSION = 1
SPCN_HEADER = struct.Struct('<4sHHIIIIII32s')    # 64 bytes
SPCN_MAP = struct.Struct('<IIII')
SPCN_NPC = struct.Struct('<III7i')               # slot,npc_id,definition_path,x,y,z,ax,ay,az,state


def sha(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_docs(root: Path) -> list[dict[str, Any]]:
    index_path = root / 'index.json'
    if not index_path.is_file():
        raise FileNotFoundError(f'missing canonical index: {index_path}')
    index = json.loads(index_path.read_text(encoding='utf-8'))
    docs = []
    for entry in index.get('documents', []):
        path = root / entry['json_path']
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc.get('id') != entry.get('id') or doc.get('logical_path') != entry.get('logical_path'):
            raise ValueError(f'canonical index/document identity mismatch: {path}')
        docs.append(doc)
    docs.sort(key=lambda d: d['logical_path'].replace('\\', '/').casefold())
    return docs


class Strings:
    def __init__(self) -> None:
        self.data = bytearray()
        self.offsets: dict[bytes, int] = {}
        self.add_bytes(b'')

    def add_bytes(self, raw: bytes) -> int:
        if b'\0' in raw:
            raise ValueError('NUL is not allowed in field pack strings')
        if raw not in self.offsets:
            self.offsets[raw] = len(self.data)
            self.data.extend(raw + b'\0')
        return self.offsets[raw]

    def add(self, value: str) -> int:
        return self.add_bytes(str(value).encode('utf-8'))


def build_start_points(root: Path) -> tuple[bytes, dict[str, Any]]:
    docs = load_docs(root)
    strings = Strings()
    maps = []
    points = []
    for doc in docs:
        if doc.get('schema') != 'summit.stage-start-points/v1':
            raise ValueError(f'unsupported start-point schema: {doc.get("schema")!r}')
        seen = set()
        start = len(points)
        for row in sorted(doc.get('points') or [], key=lambda x: int(x['slot'])):
            slot = int(row['slot'])
            if not 0 <= slot < 200 or slot in seen:
                raise ValueError(f'invalid/duplicate SPP slot {slot}: {doc["logical_path"]}')
            seen.add(slot)
            state = int(row['state'])
            if state == 0:
                raise ValueError(f'canonical SPP stores active points only; state=0 at {doc["logical_path"]}:{slot}')
            points.append((slot, state, int(row['x']), int(row['z'])))
        maps.append((strings.add(doc['logical_path'].replace('\\', '/').lower()), strings.add(doc['id']), start, len(points) - start))

    map_off = SPPT_HEADER.size
    point_off = map_off + len(maps) * SPPT_MAP.size
    string_off = point_off + len(points) * SPPT_POINT.size
    body = bytearray()
    for row in maps:
        body.extend(SPPT_MAP.pack(*row))
    for row in points:
        body.extend(SPPT_POINT.pack(*row))
    body.extend(strings.data)
    header = SPPT_HEADER.pack(
        SPPT_MAGIC, SPPT_VERSION, 0,
        len(maps), map_off, len(points), point_off,
        string_off, len(strings.data), sha(body),
    )
    data = header + body
    return data, {'maps': len(maps), 'points': len(points), 'bytes': len(data), 'sha256': sha_hex(data)}


def definition_paths(canonical_text: Path) -> dict[str, str]:
    index = json.loads((canonical_text / 'index.json').read_text(encoding='utf-8'))
    result: dict[str, str] = {}
    for entry in index.get('documents', []):
        if entry.get('kind') != 'npc_definition':
            continue
        cid = str(entry.get('id') or '')
        candidates = [str(x) for x in (entry.get('runtime_paths') or []) if x]
        if entry.get('legacy_path'):
            candidates.append(str(entry['legacy_path']))
        preferred = None
        for p in candidates:
            q = p.replace('\\', '/').lstrip('/')
            if q.casefold().startswith('gameserver/'):
                preferred = q
                break
        if preferred is None:
            for p in candidates:
                q = p.replace('\\', '/').lstrip('/')
                if q.casefold().startswith('servidor/'):
                    q = q[len('Servidor/'):]
                if q.casefold().startswith('gameserver/'):
                    preferred = q
                    break
        if cid and preferred:
            result[cid] = preferred
    return result


def build_fixed_npcs(root: Path, canonical_text: Path) -> tuple[bytes, dict[str, Any]]:
    docs = load_docs(root)
    paths = definition_paths(canonical_text)
    strings = Strings()
    maps = []
    npcs = []
    for doc in docs:
        if doc.get('schema') != 'summit.fixed-npcs/v1':
            raise ValueError(f'unsupported fixed-NPC schema: {doc.get("schema")!r}')
        seen = set()
        start = len(npcs)
        for row in sorted(doc.get('npcs') or [], key=lambda x: int(x['slot'])):
            slot = int(row['slot'])
            if not 0 <= slot < 100 or slot in seen:
                raise ValueError(f'invalid/duplicate SPC slot {slot}: {doc["logical_path"]}')
            seen.add(slot)
            npc_id = str(row['npc_id'])
            definition_path = paths.get(npc_id)
            if not definition_path:
                raise ValueError(f'fixed NPC has no canonical NPC definition path: {doc["logical_path"]}:{slot}:{npc_id}')
            npcs.append((
                slot, strings.add(npc_id), strings.add(definition_path),
                int(row['x']), int(row['y']), int(row['z']),
                int(row['ax']), int(row['ay']), int(row['az']), int(row['state']),
            ))
        maps.append((strings.add(doc['logical_path'].replace('\\', '/').lower()), strings.add(doc['id']), start, len(npcs) - start))

    map_off = SPCN_HEADER.size
    npc_off = map_off + len(maps) * SPCN_MAP.size
    string_off = npc_off + len(npcs) * SPCN_NPC.size
    body = bytearray()
    for row in maps:
        body.extend(SPCN_MAP.pack(*row))
    for row in npcs:
        body.extend(SPCN_NPC.pack(*row))
    body.extend(strings.data)
    header = SPCN_HEADER.pack(
        SPCN_MAGIC, SPCN_VERSION, 0,
        len(maps), map_off, len(npcs), npc_off,
        string_off, len(strings.data), sha(body),
    )
    data = header + body
    return data, {'maps': len(maps), 'npcs': len(npcs), 'bytes': len(data), 'sha256': sha_hex(data)}


def build_container(sections: list[tuple[bytes, int, bytes]]) -> bytes:
    table_off = FIELD_HEADER.size
    data_off = table_off + len(sections) * FIELD_SECTION.size
    cursor = data_off
    table = bytearray()
    payload = bytearray()
    for tag, version, data in sections:
        if len(tag) != 4:
            raise ValueError(f'field section tag must be 4 bytes: {tag!r}')
        table.extend(FIELD_SECTION.pack(tag, version, 0, cursor, len(data), sha(data)))
        payload.extend(data)
        cursor += len(data)
    body = bytes(table + payload)
    file_size = FIELD_HEADER.size + len(body)
    header = FIELD_HEADER.pack(
        FIELD_MAGIC, FIELD_VERSION, 0,
        len(sections), table_off, data_off, file_size, 0, 0, sha(body),
    )
    return header + body


# SUMMIT386A GMSP JSON GM XYZ
from build_gm_spawn_runtime_386a import compile_gm

def main() -> int:
    ap = argparse.ArgumentParser(description='Compile editable field JSON families into one Summit field_runtime.sfld pack')
    ap.add_argument('--canonical-spawns', type=Path, required=True)
    ap.add_argument('--canonical-start-points', type=Path, required=True)
    ap.add_argument('--canonical-fixed-npcs', type=Path, required=True)
    ap.add_argument('--canonical-text', type=Path, required=True)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='summit_field_pack_') as td:
        spawn_pack = Path(td) / 'stage_spawns.sspb'
        # Use the bundled Python runtime so this compiler also works in
        # the Asset Tool's frozen portable executable (sys.executable is not
        # an external Python interpreter in that context).
        prior_argv = sys.argv
        try:
            sys.argv = [str(here / 'compile_stage_spawns_canonical.py'),
                        str(args.canonical_spawns.resolve()), str(spawn_pack),
                        '--canonical-text', str(args.canonical_text.resolve())]
            runpy.run_path(sys.argv[0], run_name='__main__')
        finally:
            sys.argv = prior_argv
        spawn_data = spawn_pack.read_bytes()

    start_data, start_report = build_start_points(args.canonical_start_points.resolve())
    npc_data, npc_report = build_fixed_npcs(args.canonical_fixed_npcs.resolve(), args.canonical_text.resolve())
    gm_data, gm_report = compile_gm(args.canonical_spawns.resolve().parent / 'gm_spawn_points', args.canonical_text.resolve())
    result = build_container([
        (b'SSPB', 2, spawn_data),
        (b'SPPT', SPPT_VERSION, start_data),
        (b'SPCN', SPCN_VERSION, npc_data),
        (b'GMSP', 1, gm_data),
    ])
    args.output.write_bytes(result)
    report = {
        'format': 'SFLD', 'version': FIELD_VERSION,
        'sections': {
            'stage_spawns': {'tag': 'SSPB', 'bytes': len(spawn_data), 'sha256': sha_hex(spawn_data)},
            'stage_start_points': start_report,
            'fixed_npcs': npc_report,
            'gm_spawn_points': gm_report,
        },
        'bytes': len(result), 'sha256': sha_hex(result),
    }
    args.output.with_suffix(args.output.suffix + '.report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
