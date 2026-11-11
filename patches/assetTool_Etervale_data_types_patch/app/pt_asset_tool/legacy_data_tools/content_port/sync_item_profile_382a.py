#!/usr/bin/env python3
"""SUMMIT 382A: Reconcile compiled server item profile with verified canonical JSON.

Never manufactures item identities; only server.items.json source metadata and (if
verified against the current client catalog) appended codes are eligible for edits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

CANON = Path('SourceCode/Content/canonical/item_profiles/item_code_map.json')
PROFILE = Path('SourceCode/Content/canonical/item_profiles/server.items.json')
RUNTIME = Path('Servidor/Content/packs/item_code_map.json')
LEGACY = Path('SourceCode/Shared/inventory/item_code_map_mingw_legacy_server.inc')
CLIENT = Path('SourceCode/SrcGame/src/systems/inventory/legacy/item_catalog_recovered.inc')
SOURCE_RELATIVE = 'Content/canonical/item_profiles/item_code_map.json'
LEGACY_RELATIVE = 'Shared/inventory/item_code_map_mingw_legacy_server.inc'
SCHEMA = 'summit.item-code-map/v1'
RX_LEGACY = re.compile(r'\{\s*(0x[0-9A-Fa-f]+)[uUlL]*\s*,\s*"([A-Za-z]{2}[0-9]{3})"\s*\}')
RX_CLIENT = re.compile(r'\bsITEM\s*\(\s*(0x[0-9A-Fa-f]+)[uUlL]*\s*,\s*"(?:[^"\\]|\\.)*"\s*,\s*"([^"\\]+)"')


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def require(ok: bool, msg: str):
    if not ok:
        raise ValueError(msg)


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.summit382a_')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_file(root: Path, path: Path) -> Path:
    full = root / path
    require(full.is_file() and not full.is_symlink(), f'Ficheiro ausente/symlink recusado: {full}')
    return full


def parse_map(doc: object) -> list[tuple[str, str]]:
    require(isinstance(doc, dict) and set(doc) == {'schema', 'entries'} and doc['schema'] == SCHEMA,
            'JSON de codigos invalido; schema SUMMIT 381B exigido')
    entries = doc['entries']
    require(isinstance(entries, list) and 1 <= len(entries) <= 2000, 'Quantidade de codigos fora dos limites 1..2000')
    rows = []
    used = set()
    for i, row in enumerate(entries):
        require(isinstance(row, dict) and set(row) == {'code', 'numeric'}, f'Campos invalidos em entries[{i}]')
        code, num = row['code'], row['numeric']
        require(isinstance(code, str) and re.fullmatch(r'[A-Z]{2}[0-9]{3}', code) is not None,
                f'Codigo invalido: {code!r}')
        require(isinstance(num, str) and re.fullmatch(r'0x[0-9A-F]{8}', num) is not None and int(num, 16) != 0,
                f'ID invalido para {code}: {num!r}')
        require(code not in used, f'Codigo repetido: {code}')
        used.add(code)
        rows.append((code, num))
    return rows


def parse_client(root: Path):
    src = safe_file(root, CLIENT)
    byname, bynumber = defaultdict(set), defaultdict(set)
    for num, code in RX_CLIENT.findall(src.read_text(encoding='utf-8', errors='replace')):
        number = f'0x{int(num, 16):08X}'
        name = code.upper()
        byname[name].add(number)
        bynumber[number].add(name)
    require(len(byname) > 100, 'Catalogo do cliente nao reconhecido (sITEM)')
    return byname, bynumber


def plan(root: Path):
    map_path = safe_file(root, CANON)
    profile_path = safe_file(root, PROFILE)
    map_bytes = map_path.read_bytes()
    rows = parse_map(json.loads(map_bytes.decode('utf-8-sig')))
    mapping = dict(rows)
    original = profile_path.read_bytes()
    doc = json.loads(original.decode('utf-8-sig'))
    require(isinstance(doc, dict) and doc.get('schema') == 'summit.item-profile/v1' and doc.get('profile') == 'server',
            'server.items.json nao tem schema/perfil esperado')
    source = doc.get('source')
    require(isinstance(source, dict) and set(source) == {'path', 'sha256'}, 'Metadados source nao reconhecidos')
    require(source.get('path') in (LEGACY_RELATIVE, SOURCE_RELATIVE),
            'Origem de perfil desconhecida; recusa substituir: ' + repr(source.get('path')))
    codes = doc.get('codes')
    require(isinstance(codes, list) and len(codes) > 100 and all(isinstance(c, str) and re.fullmatch('[A-Z]{2}[0-9]{3}', c) for c in codes),
            'Lista de codigos do perfil invalida')
    require(len(codes) == len(set(codes)), 'Codigos duplicados no perfil')
    previous = set(codes)
    current = set(mapping)
    missing = sorted(previous - current)
    require(not missing, 'JSON nao contem codigos do perfil atual (nao apagar): ' + ', '.join(missing[:12]))

    # Legacy file is not the authority, but if it still declares a known code,
    # its numeric identity must not silently contradict the new JSON catalog.
    if (root / LEGACY).is_file():
        legacy_bytes = (root / LEGACY).read_bytes()
        pairs = RX_LEGACY.findall(legacy_bytes.decode('utf-8-sig', 'replace'))
        bycode = defaultdict(set)
        for numeric, code in pairs:
            bycode[code.upper()].add(f'0x{int(numeric, 16):08X}')
        conflicts = [c for c in previous if c in bycode and bycode[c] != {mapping[c]}]
        require(not conflicts, 'IDs antigos em conflito entre JSON e INC: ' + ', '.join(sorted(conflicts)[:12]))
    added = [c for c, _ in rows if c not in previous]
    if added:
        client_byname, client_bynumber = parse_client(root)
        for code in added:
            numeric = mapping[code]
            require(client_byname.get(code) == {numeric} and client_bynumber.get(numeric) == {code},
                    'ID novo sem validacao inequivoca no cliente atual: ' + code)
        num_to_existing = defaultdict(list)
        for code in codes:
            num_to_existing[mapping[code]].append(code)
        num_to_added = defaultdict(list)
        for code in added:
            num_to_added[mapping[code]].append(code)
        for numeric, names in num_to_added.items():
            require(len(names) == 1 and numeric not in num_to_existing,
                    'ID numerico novo colide com outro item: ' + ', '.join(names))

    # Unchanged members retain their order. Verified new members are appended.
    doc['codes'] = codes + added
    doc['source'] = {'path': SOURCE_RELATIVE, 'sha256': sha(map_bytes)}
    new = (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    oldprofile_hash = sha(original)
    rt_state = 'MISSING'
    if (root / RUNTIME).is_file():
        rt_state = 'MATCH' if (root / RUNTIME).read_bytes() == map_bytes else 'DIFFERENT'
    return original, new, len(rows), added, oldprofile_hash, rt_state


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['inspect', 'apply'])
    ap.add_argument('--root', type=Path, default=Path('.'))
    args = ap.parse_args(argv)
    root = args.root.expanduser().resolve()
    original, new, n, added, oldhash, runtime = plan(root)
    changed = original != new
    print(f'SUMMIT382A_PROFILE_CHECK entries={n} new_verified={len(added)} profile_needs_update={int(changed)} runtime_json={runtime}')
    if args.action == 'inspect':
        print('SUMMIT382A_INSPECT_PASS')
        return 0
    if changed:
        backup = root / 'bugfixes' / '_backups_382a_profile_sync' / f'server.items.before_{oldhash}.json'
        require(not backup.is_symlink(), 'Backup symlink recusado')
        if backup.exists():
            require(backup.read_bytes() == original, 'Backup da mesma versao invalido')
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open('xb') as f:
                f.write(original)
                f.flush()
                os.fsync(f.fileno())
        # Fail closed if another process edited the profile after inspection.
        require((root / PROFILE).read_bytes() == original, 'Perfil mudou durante operacao; recusa')
        atomic(root / PROFILE, new)
        print('BACKUP=' + str(backup))
    print(f'SUMMIT382A_APPLY_PASS server_profile_sha256={sha(new)} updated={int(changed)}')
    if runtime == 'DIFFERENT':
        print('WARNING_RUNTIME_JSON_DIFFERS=Publicar item_code_map.json com 381B antes de arrancar Server.exe')
    if runtime == 'MISSING':
        print('WARNING_RUNTIME_JSON_MISSING=Instalacao 381B incompleta ou runtime em pasta diferente')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print('SUMMIT382A_BLOCKED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
