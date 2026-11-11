#!/usr/bin/env python3
"""Append-only, reversible CSS hotfix for V10 catalog gallery row collapse.

Does not touch model assets, generated previews, Python backends or SMD workers.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BEGIN = b'/* ETERVALE_V11_GALLERY_IMAGE_RATIO_BEGIN'
END = b'/* ETERVALE_V11_GALLERY_IMAGE_RATIO_END */'
NAME = 'app/pt_asset_tool/ui_static/app.css'


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description='V11: restaurar dimensoes das miniaturas de Catalog Gallery, sem alterar assets')
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    target = root / NAME
    patch = Path(__file__).with_name('etervale_v11_gallery_fix.css')
    if not (root / 'app/pt_asset.py').is_file():
        print('ERRO: PROJECT_ROOT_INVALID; falta app/pt_asset.py', file=sys.stderr)
        return 2
    if not target.is_file() or target.is_symlink():
        print('ERRO: CSS_NOT_REGULAR_FILE_OR_SYMLINK', file=sys.stderr)
        return 2
    if not patch.is_file() or patch.is_symlink():
        print('ERRO: PATCH_CSS_MISSING_OR_SYMLINK', file=sys.stderr)
        return 2

    original = target.read_bytes()
    addition = patch.read_bytes().strip() + b'\n'
    if not (addition.startswith(BEGIN) and addition.endswith(END + b'\n')):
        print('ERRO: PATCH_CSS_MARKERS_INVALID', file=sys.stderr)
        return 2
    if not all(x in original for x in (b'.gallery', b'.asset-card', b'.thumb')):
        print('ERRO: CSS_LAYOUT_SIGNATURE_UNKNOWN; nao sobrescrever versao inesperada', file=sys.stderr)
        return 2
    has_begin = BEGIN in original
    has_end = END in original
    if has_begin != has_end:
        print('ERRO: LOCAL_CSS_PATCH_CONFLICT (marcador parcial)', file=sys.stderr)
        return 2
    if has_begin:
        start = original.index(BEGIN)
        stop = original.index(END, start) + len(END)
        block = original[start:stop].strip()
        if block != addition.strip():
            print('ERRO: LOCAL_CSS_PATCH_CONFLICT (bloco modificado)', file=sys.stderr)
            return 2
        print(f'JA APLICADO: {target} sha256={digest(original)}')
        return 0
    if b'ETERVALE_V11_GALLERY_IMAGE_RATIO' in original:
        print('ERRO: LOCAL_CSS_PATCH_CONFLICT (marcador inesperado)', file=sys.stderr)
        return 2

    updated = original + (b'' if original.endswith(b'\n') else b'\n') + addition
    print(f'Projeto: {root}')
    print(f'CSS: {target}')
    print(f'Original sha256: {digest(original)}')
    print(f'Corrigido sha256: {digest(updated)}')
    if args.dry_run:
        print('DRY-RUN: adicionar regras de proporcao, nenhum ficheiro modificado')
        return 0

    backup_dir = root / 'patches' / '_backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ('etervale-v11-gallery-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '-' + digest(original)[:8] + '.css')
    with backup.open('xb') as stream:
        stream.write(original)
    old_mode = stat.S_IMODE(target.stat().st_mode)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.etervale-v11-', suffix='.css', dir=target.parent, delete=False) as stream:
            tmp_name = stream.name
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, old_mode)
        # Fail closed if another process changed CSS while preparing the backup.
        if target.read_bytes() != original:
            print('ERRO: CSS_CHANGED_DURING_INSTALL', file=sys.stderr)
            return 2
        os.replace(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    print(f'PATCH APLICADO. Backup: {backup}')
    print('Apenas CSS alterado; nao reiniciar o job SMD. Recarregue a pagina com Ctrl+Shift+R.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
