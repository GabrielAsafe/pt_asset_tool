#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CLIENT_RE = re.compile(r'^\s*sITEM\([^,]+,\s*"[^"]*",\s*"([^"]+)"', re.M)
SERVER_RE = re.compile(r'\{\s*0x[0-9A-Fa-f]+u,\s*"([^"]+)"\s*\}')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_codes(path: Path, pattern: re.Pattern[str]) -> list[str]:
    values = pattern.findall(path.read_text(encoding='utf-8', errors='replace'))
    out: list[str] = []
    seen: set[str] = set()
    for code in values:
        key = code.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(code)
    return out


def write_profile(output: Path, profile: str, source: Path, source_label: str, codes: list[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        'schema': 'summit.item-profile/v1',
        'profile': profile,
        'matching': 'ascii-case-insensitive',
        'codes': codes,
        'source': {
            'path': source_label,
            'sha256': sha256(source),
        },
    }
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser(description='Materialize legacy client/server item-code fallback profiles for SCFG compilation')
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    src = args.source_root.resolve()
    out = args.out.resolve()
    client = src / 'SrcGame/src/systems/inventory/legacy/item_catalog_recovered.inc'
    server = src / 'Shared/inventory/item_code_map_mingw_legacy_server.inc'
    if not client.is_file():
        raise SystemExit(f'missing client item catalog: {client}')
    if not server.is_file():
        raise SystemExit(f'missing server item code map: {server}')

    client_codes = read_codes(client, CLIENT_RE)
    server_codes = read_codes(server, SERVER_RE)
    if not client_codes:
        raise SystemExit('client item profile is empty')
    if not server_codes:
        raise SystemExit('server item profile is empty')

    write_profile(out / 'client.items.json', 'client', client, client.relative_to(src).as_posix(), client_codes)
    write_profile(out / 'server.items.json', 'server', server, server.relative_to(src).as_posix(), server_codes)
    (out / 'index.json').write_text(json.dumps({
        'schema': 'summit.item-profile-index/v1',
        'profiles': {
            'client': 'client.items.json',
            'server': 'server.items.json',
        },
    }, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'client_codes': len(client_codes),
        'server_codes': len(server_codes),
        'out': str(out),
    }))


if __name__ == '__main__':
    main()
