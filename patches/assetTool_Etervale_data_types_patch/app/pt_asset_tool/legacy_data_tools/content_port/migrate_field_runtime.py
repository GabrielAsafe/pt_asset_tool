#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

LEGACY_EXTENSIONS = {'.spm', '.spp', '.spc'}


def run(*args: object) -> None:
    print('+', ' '.join(str(x) for x in args), flush=True)
    result = subprocess.run([str(x) for x in args])
    if result.returncode:
        raise SystemExit(result.returncode)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def legacy_field_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.rglob('*') if p.is_file() and p.suffix.casefold() in LEGACY_EXTENSIONS),
        key=lambda p: p.as_posix().casefold(),
    )


def backup_and_prune(repo: Path, roots: list[Path]) -> tuple[Path | None, int]:
    files: list[tuple[Path, Path]] = []
    for runtime_root in roots:
        for path in legacy_field_files(runtime_root / 'GameServer' / 'Field'):
            files.append((runtime_root, path))
    if not files:
        return None, 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_dir = repo / 'SourceCode' / 'Content' / 'migration_backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f'legacy_field_runtime_{stamp}.zip'
    with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for runtime_root, path in files:
            role = runtime_root.name
            rel = path.relative_to(runtime_root).as_posix()
            zf.write(path, f'{role}/{rel}')
    for _runtime_root, path in files:
        path.unlink()
    return backup, len(files)


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description='One-shot Summit SPM/SPP/SPC -> canonical JSON -> field_runtime.sfld migration')
    ap.add_argument('--repo-root', type=Path, default=here.parents[2], help='Repository root containing SourceCode/, Servidor/, cliente/')
    ap.add_argument('--no-deploy', action='store_true', help='Build SourceCode packs only')
    ap.add_argument('--prune-legacy', action='store_true', help='After successful deploy, back up and remove runtime .spm/.spp/.spc files')
    args = ap.parse_args()

    repo = args.repo_root.expanduser().resolve()
    tools = repo / 'SourceCode' / 'tools' / 'content_port'
    source_pack = repo / 'SourceCode' / 'Content' / 'packs' / 'field_runtime.sfld'

    if args.prune_legacy and args.no_deploy:
        raise SystemExit('--prune-legacy requires deployment')

    run(sys.executable, tools / 'import_field_runtime_legacy.py', '--repo-root', repo)
    consolidate = [sys.executable, tools / 'consolidate_canonical_content.py', '--repo-root', repo]
    if args.no_deploy:
        consolidate.append('--no-deploy')
    run(*consolidate)

    if not source_pack.is_file():
        raise SystemExit(f'field runtime pack missing after build: {source_pack}')
    run(sys.executable, tools / 'inspect_field_runtime.py', source_pack)

    if not args.no_deploy:
        for role in ('Servidor', 'cliente'):
            deployed = repo / role / 'Content' / 'packs' / 'field_runtime.sfld'
            if not deployed.is_file() or sha256(deployed) != sha256(source_pack):
                raise SystemExit(f'deployed field runtime pack mismatch: {deployed}')

    if args.prune_legacy:
        backup, count = backup_and_prune(repo, [repo / 'Servidor', repo / 'cliente'])
        print(f'LEGACY_FIELD_FILES_REMOVED={count}')
        if backup:
            print(f'LEGACY_FIELD_BACKUP={backup}')

    print('FIELD_RUNTIME_MIGRATION=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
