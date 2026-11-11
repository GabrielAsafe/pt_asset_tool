#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

COMMON_PACKS = (
    'field_runtime.sfld',
    'skin_reforms.sskm',
    'text_resources.sres',
    'gameplay_config.sgcf',
)
ROLE_PACKS = {
    'client': ('definitions_client.scfg', 'maps_client.smap') + COMMON_PACKS,
    'server': ('definitions_server.scfg', 'maps_server.smap') + COMMON_PACKS,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate executable-first Summit runtime content resolution and deployed packs when present')
    ap.add_argument('--repo-root', type=Path, default=None, help='Summit repository root, or a source-only SourceCode snapshot; defaults to the root derived from this script location')
    args = ap.parse_args()
    repo = (args.repo_root if args.repo_root is not None else Path(__file__).resolve().parents[3]).resolve()
    nested_source = repo / 'SourceCode'
    source_root = nested_source if (nested_source / 'Content' / 'packs').is_dir() else repo
    source_packs = source_root / 'Content' / 'packs'
    errors: list[str] = []

    print(f'REPO_ROOT={repo}')
    print(f'SOURCE_ROOT={source_root}')
    print(f'SOURCE_PACK_ROOT={source_packs}')

    # SRES is now the sole deployed text pack.
    if (source_packs / 'localization.sloc').exists():
        errors.append('obsolete source localization.sloc remains: rebuild canonical content')

    runtime_roots = (('client', repo / 'cliente'), ('server', repo / 'Servidor'))
    deployment_available = any(runtime_root.is_dir() for _, runtime_root in runtime_roots)
    for role, runtime_root in runtime_roots:
        pack_root = runtime_root / 'Content' / 'packs'
        print(f'ROLE={role} RUNTIME_PACK_ROOT={pack_root}')
        if (pack_root / 'localization.sloc').exists():
            errors.append(f'obsolete deployed localization.sloc remains: {pack_root}')
        for name in ROLE_PACKS[role]:
            source = source_packs / name
            source_exists = source.is_file()
            if not source_exists:
                errors.append(f'missing source pack: {source}')
            if runtime_root.is_dir():
                deployed = pack_root / name
                deployed_exists = deployed.is_file()
                same = source_exists and deployed_exists and sha256(source) == sha256(deployed)
                print(f'PACK role={role} name={name} SOURCE_EXISTS={int(source_exists)} DEPLOYED_EXISTS={int(deployed_exists)} HASH_MATCH={int(same)}')
                if source_exists and not deployed_exists:
                    errors.append(f'missing standalone deployed pack: {deployed}')
                elif source_exists and deployed_exists and not same:
                    errors.append(f'deployed pack differs from source pack: {deployed}')
            else:
                print(f'PACK role={role} name={name} SOURCE_EXISTS={int(source_exists)} DEPLOYMENT_CHECK=SKIP')

    if not deployment_available:
        print('DEPLOYMENT_CHECK=SKIP (cliente/ and Servidor/ omitted from source snapshot)')

    helper = source_root / 'Shared' / 'content' / 'v1' / 'runtime' / 'RuntimeContentPath.h'
    if not helper.is_file():
        errors.append(f'missing runtime resolver: {helper}')
    else:
        text = helper.read_text(encoding='utf-8', errors='replace')
        shipped_token = 'candidates[count++] = RuntimeJoinPath(executableDirectory, "Content\\\\packs\\\\" + fileName);'
        source_token = 'SourceCode\\\\Content\\\\packs'
        for needle in ('GetModuleFileNameA', 'Content\\\\packs\\\\', 'RuntimeRegularFileExists(candidates[i])'):
            if needle not in text:
                errors.append(f'runtime resolver missing executable-first contract: {needle}')
        if shipped_token not in text:
            errors.append('runtime resolver does not add executable-local Content/packs first')
        if source_token in text and shipped_token in text and text.find(source_token) < text.find(shipped_token):
            errors.append('source-tree development fallback precedes executable-local Content/packs')

    if errors:
        for error in errors:
            print(f'ERROR={error}')
        print('RESULT=FAIL')
        return 1

    print('PACK_RESOLUTION=EXECUTABLE_FIRST_WITH_SOURCE_TREE_DEV_FALLBACK')
    print('RESULT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
