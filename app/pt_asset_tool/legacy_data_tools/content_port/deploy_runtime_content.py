#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

COMMON_PACKS = (
    'field_runtime.sfld',
    'skin_reforms.sskm',
    'text_resources.sres',
    'gameplay_config.sgcf',
    'gameplay_reference.sgrf',
)
ROLE_PACKS = {
    'client': ('definitions_client.scfg', 'maps_client.smap') + COMMON_PACKS,
    'server': ('definitions_server.scfg', 'maps_server.smap', 'coin_shop.scsp') + COMMON_PACKS,
}
STALE_COMMON_PACKS = ('stage_spawns.sspb', 'localization.sloc')
KNOWN_ROLE_SPECIFIC = {
    'client': ('definitions_server.scfg', 'maps_server.smap'),
    'server': ('definitions_client.scfg', 'maps_client.smap'),
}
LEGACY_ROLE_PATHS = {
    'client': (Path('content/maps/maps_client.smap'),),
    'server': (Path('content/maps/maps_server.smap'),),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def deploy_role(source_packs: Path, destination_root: Path, role: str) -> dict:
    destination = destination_root / 'Content' / 'packs'
    destination.mkdir(parents=True, exist_ok=True)

    # Remove stale lowercase map-pack layouts left by pre-Content/packs tools.
    # On case-sensitive hosts these coexist with Content/packs and can mislead
    # operators or older launch scripts into consuming a different map catalog.
    for legacy_rel in LEGACY_ROLE_PATHS[role]:
        legacy = destination_root / legacy_rel
        if legacy.is_file():
            legacy.unlink()

    # Validate the complete candidate and old-pack backup before any deployment write.
    for name in ROLE_PACKS[role]:
        source = source_packs / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f'missing or unsafe source pack: {source}')
    retired = destination / 'localization.sloc'
    if retired.is_symlink():
        raise RuntimeError(f'refusing symlink legacy pack: {retired}')
    if retired.is_file():
        backup = destination_root.parent / 'bugfixes' / '.summit_sres_merge' / f'{role}_localization.sloc'
        if backup.exists() and (backup.is_symlink() or not backup.is_file() or sha256(backup) != sha256(retired)):
            raise RuntimeError(f'conflicting legacy localization backup: {backup}')

    files = []
    for name in ROLE_PACKS[role]:
        source = source_packs / name
        if not source.is_file():
            raise FileNotFoundError(f'missing source pack: {source}')
        target = destination / name
        shutil.copy2(source, target)
        if sha256(source) != sha256(target):
            raise RuntimeError(f'hash mismatch after copy: {target}')
        files.append({
            'name': name,
            'bytes': target.stat().st_size,
            'sha256': sha256(target),
        })

    # Retire old pack only after the new consolidated SRES is deployed and verified.
    for stale_name in STALE_COMMON_PACKS + KNOWN_ROLE_SPECIFIC[role]:
        stale = destination / stale_name
        if stale.is_symlink():
            raise RuntimeError(f'refusing to delete symlink: {stale}')
        if stale.is_file():
            if stale_name == 'localization.sloc':
                backup = destination_root.parent / 'bugfixes' / '.summit_sres_merge' / f'{role}_localization.sloc'
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    if backup.is_symlink() or not backup.is_file() or sha256(backup) != sha256(stale):
                        raise RuntimeError(f'conflicting legacy localization backup: {backup}')
                else:
                    shutil.copy2(stale, backup)
            stale.unlink()

    manifest = {
        'schema': 'summit.runtime-content-deploy/v1',
        'role': role,
        'layout': 'standalone-executable-content',
        'files': files,
    }
    manifest_path = destination_root / 'Content' / 'RUNTIME_CONTENT.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return {'root': destination_root, 'manifest': manifest_path, 'files': files}


def main() -> int:
    ap = argparse.ArgumentParser(description='Deploy compiled runtime content into standalone Summit client/server trees')
    ap.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[3], help='repository root containing SourceCode/, cliente/, Servidor/')
    ap.add_argument('--client-dir', type=Path, default=Path('cliente'))
    ap.add_argument('--server-dir', type=Path, default=Path('Servidor'))
    args = ap.parse_args()

    repo = args.repo_root.resolve()
    source_packs = repo / 'SourceCode' / 'Content' / 'packs'
    client_root = args.client_dir if args.client_dir.is_absolute() else repo / args.client_dir
    server_root = args.server_dir if args.server_dir.is_absolute() else repo / args.server_dir

    print(f'REPO_ROOT={repo}')
    print(f'SOURCE_PACK_ROOT={source_packs}')

    try:
        client = deploy_role(source_packs, client_root.resolve(), 'client')
        server = deploy_role(source_packs, server_root.resolve(), 'server')
    except (OSError, RuntimeError) as exc:
        print(f'ERROR={exc}')
        print('RESULT=FAIL')
        return 1

    for role, result in (('client', client), ('server', server)):
        print(f'ROLE={role} ROOT={result["root"]}')
        for item in result['files']:
            print(f'DEPLOY role={role} pack={item["name"]} bytes={item["bytes"]} sha256={item["sha256"]}')
        print(f'MANIFEST role={role} path={result["manifest"]}')

    print('RESULT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
