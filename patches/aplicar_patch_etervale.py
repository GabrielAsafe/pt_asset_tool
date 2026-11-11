#!/usr/bin/env python3
"""Aplica incrementalmente a migracao de ferramentas de dados ao PT Asset Tool.

Executar a partir da raiz de ~/Transferencias/pt_asset_tool:
    python3 /caminho/aplicar_patch_etervale.py --dry-run
    python3 /caminho/aplicar_patch_etervale.py

Lê patches/assetTool_Etervale_data_types_patch.zip por padrão (ou a pasta
extraída se o ZIP não existir). Não altera Etervale-git ou configurações.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

MARKER = '## Etervale data-format tooling import'
CLI_ANCHOR = '    sp = p.add_subparsers(dest="command", required=True)'
CLI_LINES = ('    from .data_type_tools import register_parser as register_data_type_tools\n'
             '    register_data_type_tools(sp)\n')
SPECIAL = {'README.md', 'app/pt_asset_tool/cli.py'}
SINGLE_FILES = {
    'MIGRATED_DATA_TOOL_SOURCES.json',
    'app/dev_tests/test_data_type_migration_etervale.py',
    'app/pt_asset_tool/data_type_tools.py',
    'docs/etervale/DATA_TYPE_TOOLS.md',
    'docs/etervale/VALIDATION_RESULTS.json',
}
PREFIX = 'app/pt_asset_tool/legacy_data_tools/'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_name(name: str) -> bool:
    p = PurePosixPath(name)
    return (name != '' and not name.startswith('/') and '\\' not in name and
            all(x not in ('.', '..', '') for x in name.split('/')) and
            (name in SINGLE_FILES or name in SPECIAL or name.startswith(PREFIX)))


def load_patch(patch: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    if patch.is_dir():
        for item in patch.rglob('*'):
            if item.is_symlink():
                raise ValueError(f'Link simbolico no patch: {item}')
            if not item.is_file():
                continue
            rel = item.relative_to(patch).as_posix()
            if not valid_name(rel):
                raise ValueError(f'Caminho inesperado no patch: {rel}')
            contents[rel] = item.read_bytes()
    elif patch.is_file():
        with zipfile.ZipFile(patch) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if not valid_name(name):
                    raise ValueError(f'Caminho inesperado no ZIP: {name}')
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type not in (0, stat.S_IFREG):
                    raise ValueError(f'Tipo de arquivo proibido: {name}')
                if name in contents:
                    raise ValueError(f'Entrada duplicada: {name}')
                contents[name] = z.read(info)
    else:
        raise FileNotFoundError(f'Patch não encontrado: {patch}')
    if len(contents) != 116 or not (SPECIAL | SINGLE_FILES) <= contents.keys():
        raise ValueError(f'Patch não corresponde ao pacote esperado: {len(contents)} arquivos')
    return contents


def target_is_safe(root: Path, relative: str) -> bool:
    cur = root
    for part in PurePosixPath(relative).parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    return True


def replace_cli(old: bytes) -> bytes:
    src = old.decode('utf-8')
    if 'register_data_type_tools(sp)' in src:
        return old
    anchor = CLI_ANCHOR + '\n'
    if src.count(anchor) != 1:
        raise ValueError('CLI modificada: ponto de inserção não encontrado exatamente uma vez')
    return src.replace(anchor, anchor + CLI_LINES, 1).encode('utf-8')


def extend_readme(old: bytes, patch_readme: bytes) -> bytes:
    src = old.decode('utf-8')
    if MARKER in src:
        return old
    prepared = patch_readme.decode('utf-8')
    if prepared.count(MARKER) != 1:
        raise ValueError('README do patch não tem seção Etervale esperada')
    section = prepared[prepared.index(MARKER):].rstrip() + '\n'
    return (src.rstrip() + '\n\n' + section).encode('utf-8')


def atomic_write(dest: Path, data: bytes, original_mode: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.etervale_patch_', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, original_mode if original_mode is not None else 0o644)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path.cwd(), help='Raiz do pt_asset_tool (padrão: cwd)')
    ap.add_argument('--patch', type=Path, help='Arquivo ZIP ou pasta extraída do patch')
    ap.add_argument('--dry-run', action='store_true', help='Apenas verifica, sem alterar arquivos')
    args = ap.parse_args()
    root = args.root.expanduser().resolve()
    if not (root / 'app/pt_asset.py').is_file() or not (root / 'app/pt_asset_tool/cli.py').is_file():
        ap.error(f'Não parece ser a raiz do PT Asset Tool: {root}')
    patch = args.patch
    if patch is None:
        patch = root / 'patches/assetTool_Etervale_data_types_patch.zip'
        if not patch.is_file():
            patch = root / 'patches/assetTool_Etervale_data_types_patch'
    patch = patch.expanduser().resolve()
    try:
        contents = load_patch(patch)
        plan: dict[str, tuple[bytes, bytes | None]] = {}
        unchanged: list[str] = []
        for rel, data in sorted(contents.items()):
            target = root / rel
            if not target_is_safe(root, rel):
                raise ValueError(f'Link simbólico encontrado no destino: {rel}')
            if target.is_dir():
                raise ValueError(f'Destino é diretório: {rel}')
            old = target.read_bytes() if target.is_file() else None
            if rel == 'app/pt_asset_tool/cli.py':
                assert old is not None
                data = replace_cli(old)
            elif rel == 'README.md':
                assert old is not None
                data = extend_readme(old, contents['README.md'])
            elif old is not None and old != data:
                raise ValueError(f'Conflito em arquivo novo que já existe e difere: {rel}')
            if old == data:
                unchanged.append(rel)
            else:
                plan[rel] = (data, old)
        new_count = sum(old is None for _, old in plan.values())
        modified_count = len(plan) - new_count
        print(f'Projeto: {root}\nPatch: {patch}')
        print(f'Arquivos: {len(contents)} | novos: {new_count} | modificados: {modified_count} | já aplicados: {len(unchanged)}')
        for rel, (_, old) in plan.items():
            if old is not None:
                print(f'  MODIFICAR (com backup): {rel}')
        if args.dry_run:
            print('DRY-RUN: nenhuma alteração realizada.')
            return 0
        if not plan:
            print('Patch já aplicado. Nenhuma alteração necessária.')
            return 0
        now = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = root / 'patches' / '_backups' / f'etervale-data-types-{now}'
        backup.mkdir(parents=True, exist_ok=False)
        manifest = {
            'root': str(root), 'patch': str(patch), 'created_at': dt.datetime.now().isoformat(),
            'changes': [{'path': name, 'previous_sha256': sha(old) if old is not None else None,
                         'new_sha256': sha(data)} for name, (data, old) in plan.items()],
        }
        # Salvar os anteriores antes de alterar qualquer arquivo.
        for rel, (data, old) in plan.items():
            if old is not None:
                dest = backup / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / rel, dest)
        (backup / 'install_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        done: list[str] = []
        try:
            for rel, (data, old) in plan.items():
                dest = root / rel
                mode = stat.S_IMODE(dest.stat().st_mode) if old is not None else 0o644
                atomic_write(dest, data, mode)
                done.append(rel)
        except Exception:
            print('Falha na aplicação: restaurando arquivos alterados...', file=sys.stderr)
            for rel in reversed(done):
                data, old = plan[rel]
                dest = root / rel
                if old is None:
                    dest.unlink(missing_ok=True)
                else:
                    atomic_write(dest, old, stat.S_IMODE((backup / rel).stat().st_mode))
            raise
        print(f'Patch aplicado. Backup: {backup}')
        print('Verifique com:\n'
              '  python3 app/pt_asset.py data-types list\n'
              '  python3 -m pytest -q app/dev_tests/test_data_type_migration_etervale.py')
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
