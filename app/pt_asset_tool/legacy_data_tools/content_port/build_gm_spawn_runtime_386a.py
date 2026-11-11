#!/usr/bin/env python3
"""SUMMIT 386A: compile validated, explicitly published GM XYZ into the SFLD GMSP section.
SPM/SPP/SPC are unchanged. Does not read SQLite; draft canonical is the source of truth.
"""
from __future__ import annotations
import hashlib
import json
import re
import struct
from pathlib import Path

HEADER = struct.Struct('<4sHHII32s')
ROW = struct.Struct('<IIiiiIII64s')
MAX_TOTAL = 96
KEY = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_hash(obj: dict) -> str:
    return digest(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8'))


def secure_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 15_000_000:
        raise ValueError('missing, oversized or symlink JSON: ' + str(path))
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('expected JSON object: ' + str(path))
    return result


def monster_index(text_root: Path) -> dict:
    index = secure_json(text_root / 'index.json')
    records = {}
    for d in index.get('documents', []):
        if d.get('kind') != 'monster_definition':
            continue
        rel = d.get('json_path', '')
        if not isinstance(rel, str) or '..' in Path(rel).parts or Path(rel).is_absolute():
            raise ValueError('unsafe canonical text reference')
        key = d.get('id')
        if not isinstance(key, str) or not key:
            raise ValueError('invalid canonical monster ID')
        records[key] = text_root / rel
    return records


def check_placement(p: dict, map_id: int, available: dict) -> tuple:
    if p.get('runtime_enabled') is not True or p.get('status') != 'published_gmsp_386a':
        raise ValueError('unpublished placement in published snapshot')
    plan_id = p.get('plan_id')
    if type(plan_id) is not int or not 1 <= plan_id <= 2**31-1:
        raise ValueError('invalid plan id')
    if p.get('map_id') != map_id or p.get('kind') != 'monster':
        raise ValueError('nonmonster or map mismatch')
    key = p.get('content_key')
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError('invalid content key')
    mid = p.get('monster_id')
    if not isinstance(mid, str) or mid not in available:
        raise ValueError('unresolved monster id: ' + str(mid))
    monster = secure_json(available[mid])
    fields = monster.get('semantic', {}).get('fields', {})
    name = fields.get('name')
    model = fields.get('model_file')
    if not isinstance(name, str) or not name or not isinstance(model, str) or not model:
        raise ValueError('invalid canonical monster name or model: ' + mid)
    if monster.get('id') != mid or name != p.get('monster_name') or model != p.get('model_file'):
        raise ValueError('monster content changed since GM publication: ' + mid)
    tokens = model.replace('\\', '/').lower().split('/')
    if len(tokens) < 4 or tokens[0] != 'char' or tokens[1] != 'monster' or tokens[2] != key.lower():
        raise ValueError('model family does not match GM content key: ' + key)
    pos = p.get('position')
    if not isinstance(pos, dict):
        raise ValueError('missing position')
    coords = []
    for axis in ('x', 'y', 'z'):
        v = pos.get(axis)
        if type(v) is not int or not -(2**23) <= v <= 2**23:
            raise ValueError('coordinate out of range: ' + axis)
        coords.append(v)
    max_alive, radius, respawn = p.get('max_alive'), p.get('radius'), p.get('respawn_seconds')
    if type(max_alive) is not int or not 1 <= max_alive <= 12:
        raise ValueError('max_alive outside 1..12')
    if type(radius) is not int or not 30 <= radius <= 1500:
        raise ValueError('radius outside 30..1500')
    if type(respawn) is not int or not 10 <= respawn <= 3600:
        raise ValueError('respawn outside 10..3600')
    try:
        raw_name = name.encode('cp1252')
    except UnicodeEncodeError as exc:
        raise ValueError('monster name not representable in Windows CP1252: ' + mid) from exc
    if len(raw_name) > 63 or b'\0' in raw_name:
        raise ValueError('monster name exceeds binary field')
    return (plan_id, map_id, *coords, max_alive, radius, respawn, raw_name.ljust(64, b'\0'))


def compile_gm(gm_root: Path, text_root: Path) -> tuple[bytes, dict]:
    rows = []
    available = monster_index(text_root) if gm_root.is_dir() and list(gm_root.glob('map_*.published.json')) else {}
    seen = set()
    maps = set()
    for path in sorted(gm_root.glob('map_*.published.json')) if gm_root.is_dir() else []:
        doc = secure_json(path)
        m = re.fullmatch(r'map_(\d{3})\.published\.json', path.name)
        mi = int(m.group(1)) if m else -1
        if mi > 255 or doc.get('map_id') != mi or doc.get('schema') != 'summit.gm-spawn-published/v1':
            raise ValueError('bad GM published map document: ' + str(path))
        draft_path = gm_root / ('map_%03d.json' % mi)
        draft = secure_json(draft_path)
        if draft.get('schema') != 'summit.gm-spawn-points/v1' or draft.get('map_id') != mi or canonical_hash(draft) != doc.get('source_draft_sha256'):
            raise ValueError('GM draft changed after publication; re-publish: ' + str(path))
        drafts = {p['plan_id']: p for p in draft.get('points', [])}
        plans = doc.get('points')
        if not isinstance(plans, list) or not plans:
            raise ValueError('empty published GM map')
        if len(plans) > 96:
            raise ValueError('too many placements per GM map')
        maps.add(mi)
        for p in plans:
            if not isinstance(p, dict) or type(p.get('plan_id')) is not int or drafts.get(p['plan_id']) is None:
                raise ValueError('unknown GM plan in published snapshot')
            if p.get('source_point_sha256') != canonical_hash(drafts[p['plan_id']]):
                raise ValueError('GM plan changed after publication: ' + str(p.get('plan_id')))
            r = check_placement(p, mi, available)
            if (mi, r[0]) in seen:
                raise ValueError('duplicate GM plan in pack')
            seen.add((mi, r[0]))
            rows.append(r)
    rows.sort(key=lambda r: (r[1], r[0]))
    if len(rows) > MAX_TOTAL or sum(r[5] for r in rows) > 96:
        raise ValueError('GM spawn density exceeds global cap 96')
    payload = b''.join(ROW.pack(*row) for row in rows)
    blob = HEADER.pack(b'GMS1', 1, 0, len(rows), ROW.size, hashlib.sha256(payload).digest()) + payload
    return blob, {'format': 'GMS1', 'maps': len(maps), 'points': len(rows), 'maximum_monsters': sum(r[5] for r in rows), 'bytes': len(blob), 'sha256': digest(blob)}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--gm-root', type=Path, required=True)
    ap.add_argument('--text-root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    buf, rep = compile_gm(args.gm_root, args.text_root)
    args.out.write_bytes(buf)
    print(json.dumps(rep, sort_keys=True))
