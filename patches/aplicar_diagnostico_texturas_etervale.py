#!/usr/bin/env python3
"""Aplica diagnóstico incremental de texturas/GLB para a ponte Etervale (com backup e SHA-256).

Na raiz do Asset Tool:
    python3 patches/aplicar_diagnostico_texturas_etervale.py --dry-run
    python3 patches/aplicar_diagnostico_texturas_etervale.py

Espera o ZIP patches/assetTool_Etervale_texture_diagnostics_patch.zip.
NÃO toca o repositório Etervale nem conteúdo do jogo.
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

EXPECTED_FORMAT = 'ETERVALE_TEXTURE_DIAGNOSTICS_PATCH_V1'
PATCH_FILE = 'assetTool_Etervale_texture_diagnostics_patch.zip'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_target(root: Path, rel: str) -> Path:
    path = PurePosixPath(rel)
    if (path.is_absolute() or '\\' in rel or not path.parts or
            any(part in ('', '.', '..') for part in path.parts)):
        raise ValueError(f'Caminho inseguro no patch: {rel}')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Link simbólico proibido no destino: {current}')
    if current.is_dir():
        raise ValueError(f'Destino é diretório: {current}')
    return current


def load_payload(zip_path: Path) -> tuple[dict[str, dict], dict[str, bytes]]:
    with zipfile.ZipFile(zip_path) as pack:
        files = {item.filename: item for item in pack.infolist() if not item.is_dir()}
        name = 'ETERVALE_TEXTURE_DIAGNOSTICS_PATCH_MANIFEST.json'
        if name not in files:
            raise ValueError('Manifesto do patch ausente')
        meta = json.loads(pack.read(name).decode('utf-8'))
        if meta.get('format') != EXPECTED_FORMAT:
            raise ValueError('Formato de patch inesperado')
        entries = meta.get('files')
        if not isinstance(entries, list) or len(entries) != 3:
            raise ValueError('O patch deve conter exatamente 3 arquivos de código/documentação')
        plans: dict[str, dict] = {}
        payloads: dict[str, bytes] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Entrada inválida no manifesto')
            rel = entry.get('path')
            if not isinstance(rel, str) or rel in plans or rel not in files:
                raise ValueError(f'Entrada inválida ou duplicada no ZIP: {rel}')
            # Malicious ZIPs could contain unusual file types.
            mode = files[rel].external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError(f'Entrada ZIP não é arquivo comum: {rel}')
            data = pack.read(rel)
            if sha(data) != entry.get('sha256'):
                raise ValueError(f'SHA-256 incorreto no patch: {rel}')
            plans[rel] = entry
            payloads[rel] = data
        if set(files) != set(plans) | {name}:
            raise ValueError('ZIP inclui arquivos inesperados')
        return plans, payloads


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.bridge_patch_')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path.cwd())
    ap.add_argument('--patch', type=Path)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    root = args.root.expanduser().resolve()
    patch = (args.patch or root / 'patches' / PATCH_FILE).expanduser().resolve()
    try:
        if not (root / 'app/pt_asset.py').is_file() or not (root / 'app/pt_asset_tool/etervale_integration.py').is_file():
            raise ValueError(f'Asset Tool com a ponte Etervale não encontrado: {root}')
        if not patch.is_file():
            raise FileNotFoundError(f'ZIP não encontrado: {patch}')
        metadata, payloads = load_payload(patch)
        plan = {}
        already = []
        for rel, meta in sorted(metadata.items()):
            target = safe_target(root, rel)
            current = target.read_bytes() if target.exists() else None
            existing_hash = sha(current) if current is not None else None
            if existing_hash == meta['sha256']:
                already.append(rel)
                continue
            if existing_hash != meta['base_sha256']:
                raise ValueError(
                    f'CONFLITO_LOCAL:{rel}:hash={existing_hash}:esperado={meta["base_sha256"]}. '
                    'O instalador não sobrescreve customizações; revise o arquivo antes de aplicar.'
                )
            plan[rel] = (payloads[rel], current)
        print(f'Projeto: {root}\nPatch: {patch}')
        print(f'Arquivos: {len(metadata)} | novos: {sum(old is None for _, old in plan.values())} '
              f'| modificados: {sum(old is not None for _, old in plan.values())} '
              f'| já aplicados: {len(already)}')
        for rel, (_, old) in plan.items():
            if old is not None:
                print(f'  MODIFICAR (backup automático): {rel}')
        if args.dry_run:
            print('DRY-RUN: nenhum arquivo foi alterado.')
            return 0
        if not plan:
            print('Patch já aplicado. Nenhuma alteração necessária.')
            return 0
        backup = (root / 'patches' / '_backups' /
                  f'etervale-texture-audit-{dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")}')
        backup.mkdir(parents=True, exist_ok=False)
        for rel, (_, old) in plan.items():
            if old is not None:
                target = backup / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / rel, target)
        (backup / 'install_manifest.json').write_text(json.dumps({
            'format': EXPECTED_FORMAT, 'patch': str(patch),
            'changes': [{'path': rel, 'previous_sha256': sha(old) if old is not None else None,
                         'new_sha256': sha(data)} for rel, (data, old) in plan.items()],
        }, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        written = []
        try:
            for rel, (data, old) in plan.items():
                dest = root / rel
                mode = stat.S_IMODE(dest.stat().st_mode) if old is not None else 0o644
                atomic_write(dest, data, mode)
                written.append(rel)
        except Exception:
            for rel in reversed(written):
                data, old = plan[rel]
                dest = root / rel
                if old is None:
                    dest.unlink(missing_ok=True)
                else:
                    mode = stat.S_IMODE((backup / rel).stat().st_mode)
                    atomic_write(dest, old, mode)
            raise
        print('Patch aplicado com sucesso.')
        print(f'Backup e manifesto: {backup}')
        print('Próximas verificações:')
        print('  python3 -m pytest -q app/dev_tests/test_etervale_unified_bridge.py app/dev_tests/test_etervale_texture_audit_bridge.py')
        print('  python3 app/pt_asset.py etervale export-glb --help')
        print('  python3 app/pt_asset.py etervale inspect-glb --help')
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
