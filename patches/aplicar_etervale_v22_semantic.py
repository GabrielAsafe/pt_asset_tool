#!/usr/bin/env python3
"""V22 Stage072 geometry-based semantic classification proposals, incremental over V21.1."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from zipfile import ZipFile

PATCH_NAME = 'etervale_V22_STAGE072_CLASSIFICADOR_patch.zip'
PATCH_ID = 'etervale-v22-stage072-semantic-geometry-object-detection'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace_atomically(target: Path, data: bytes, mode: int = 0o644):
    fd, temp_path = tempfile.mkstemp(prefix='.etervale-v22-', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def install(project_root: Path, patch: Path, dry_run: bool) -> int:
    root = project_root.expanduser().resolve()
    if not (root / 'app/pt_asset.py').is_file():
        print('PROJECT_ROOT_INVALID: falta app/pt_asset.py', file=sys.stderr)
        return 2
    if not patch.is_file() or patch.is_symlink():
        print('PATCH_MISSING_OR_SYMLINK', file=sys.stderr)
        return 2
    with ZipFile(patch) as archive:
        meta = json.loads(archive.read('PATCH_MANIFEST.json'))
        if meta.get('patch_id') != PATCH_ID:
            print('PATCH_MANIFEST_ID_MISMATCH', file=sys.stderr)
            return 2
        files = meta['files']
        expected = {entry['path'] for entry in files} | {'PATCH_MANIFEST.json'}
        if set(archive.namelist()) != expected:
            print('PATCH_ARCHIVE_FILESET_INVALID', file=sys.stderr)
            return 2
        staged = []
        for entry in files:
            relative = PurePosixPath(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or not str(relative).startswith(('app/', 'docs/')):
                print('PATCH_PATH_INVALID', file=sys.stderr)
                return 2
            target = root.joinpath(*relative.parts)
            # Prevent writes through symlink directories even on a valid root.
            if any(p.is_symlink() for p in (target, *list(target.parents)[:-2]) if p == root or root in p.parents):
                print(f'TARGET_SYMLINK_CONFLICT: {target}', file=sys.stderr)
                return 2
            data = archive.read(entry['path'])
            if sha(data) != entry['sha256']:
                print(f'PATCH_PAYLOAD_CORRUPTED: {entry["path"]}', file=sys.stderr)
                return 2
            current = target.read_bytes() if target.is_file() else None
            current_sha = sha(current) if current is not None else ''
            if current_sha == entry['sha256']:
                status = 'JA_APLICADO'
            elif entry['kind'] == 'modified' and current is not None and current_sha == entry['old_sha256']:
                status = 'MODIFICAR'
            elif entry['kind'] == 'new' and current is None and not target.exists():
                status = 'CRIAR'
            else:
                print(f'SOURCE_FILE_CONFLICT: {entry["path"]} actual_sha256={current_sha or "MISSING"}', file=sys.stderr)
                return 2
            staged.append((entry, target, data, current, status))

        print(f'Projeto: {root}')
        print(f'Patch: {patch} id={PATCH_ID}')
        for entry, _, _, _, status in staged:
            print(f'  {status}: {entry["path"]}')
        changed = [row for row in staged if row[-1] != 'JA_APLICADO']
        if dry_run:
            print(f'DRY-RUN: {len(changed)} ficheiros pendentes; nenhum alterado')
            return 0
        if not changed:
            print('JA_APLICADO: nenhum ficheiro alterado')
            return 0

        backup = root / 'patches' / '_backups' / ('etervale-v22-semantic-'
                   + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
        backup.mkdir(parents=True, exist_ok=False)
        original = {}
        written = []
        try:
            for entry, target, data, previous, status in changed:
                if previous is not None:
                    old = backup / entry['path']
                    old.parent.mkdir(parents=True, exist_ok=True)
                    old.write_bytes(previous)
                    original[target] = (previous, target.stat().st_mode & 0o777)
                else:
                    original[target] = (None, 0o644)
            (backup / 'PATCH_MANIFEST.json').write_text(json.dumps(meta, indent=2) + '\n')
            for entry, target, data, previous, status in changed:
                target.parent.mkdir(parents=True, exist_ok=True)
                now = target.read_bytes() if target.is_file() else None
                if now != previous:
                    raise RuntimeError(f'FILE_CHANGED_DURING_INSTALL: {entry["path"]}')
                written.append(target)
                _replace_atomically(target, data, original[target][1])
        except Exception as exc:
            for target in reversed(written):
                previous, mode = original[target]
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    _replace_atomically(target, previous, mode)
            print(f'PATCH_ABORTED_AND_ROLLED_BACK: {exc}', file=sys.stderr)
            return 2
        print(f'PATCH_APLICADO: {len(changed)} ficheiros; backup: {backup}')
        print('V22: detetor geometrico, propostas em JSON separado; SMD, assets e checkpoints intactos.')
    return 0


def main():
    ap = argparse.ArgumentParser(description='V22: Classificador geometrico conservador de objetos em mapas Stage 0.72')
    ap.add_argument('--project-root', type=Path, default=Path.cwd())
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--patch', type=Path)
    args = ap.parse_args()
    patch = args.patch or Path(__file__).with_name(PATCH_NAME)
    try:
        return install(args.project_root, patch, args.dry_run)
    except (OSError, ValueError, KeyError) as exc:
        print(f'PATCH_ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
