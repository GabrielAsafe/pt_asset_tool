#!/usr/bin/env python3
"""V21 — Open a validated Stage072 map with semantic painting in Blender 5.x.

No source modifications; no changes to V13/V19/V20 checkpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from pt_asset_tool.stage072_semantic_core import (annotation_path, FORMAT, check_document)
from pt_stage072_review_sequencial import load_validated_maps, _safe_relative_asset, _file_sha256


def _summarize(path: Path, entry: dict) -> str:
    if not path.is_file():
        return 'SEM_CLASSIFICACOES'
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
        # Validate against source identity and topology when available in doc.
        check_document(doc, asset=entry['asset'], source_sha256=entry['source_sha256'],
                       vertex_count=doc['source_vertex_count'], face_count=doc['source_face_count'])
        counts = {}
        for region in doc.get('regions', []):
            counts[region['category']] = counts.get(region['category'], 0) + 1
        return f"REGIOES={len(doc['regions'])} CATEGORIAS={counts}"
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        return f'ANOTACAO_INVALIDA={type(e).__name__}:{e}'


def run(*, project_root: Path, selected_asset: str | None, all_maps: bool,
        list_only: bool, dry_run: bool, limit: int, include_classified: bool,
        blender_command: list[str] | None = None, report_path: Path | None = None) -> int:
    project_root = project_root.resolve(strict=True)
    app_root = project_root / 'app'
    report = report_path or app_root / 'pt_build/etervale/stage072_all_maps/stage_0_summary.json'
    maps, _ = load_validated_maps(project_root, report)
    if selected_asset:
        logical = _safe_relative_asset(selected_asset)
        maps = [m for m in maps if m['asset'] == logical]
        if not maps:
            raise ValueError(f'MAPA_NAO_ENCONTRADO:{logical}')
    elif not all_maps and not list_only:
        raise ValueError('USA_--map_MAPA_ou_--all')
    base = app_root / 'pt_build/etervale/stage072_semantic_v21'
    work = app_root / 'pt_asset_tool/blender/stage072_semantic_paint.py'
    if not work.is_file():
        raise FileNotFoundError(f'BLENDER_ADDON_V21_AUSENTE:{work}')
    if blender_command is None and not (dry_run or list_only):
        from pt_asset_tool.dependencies import resolve_blender_command
        blender_command, ready, detail = resolve_blender_command(app_root)
        if not ready:
            raise RuntimeError(f'BLENDER_UNAVAILABLE:{detail}')
    pending = []
    for m in maps:
        dest = annotation_path(base, m['asset'])
        status = _summarize(dest, m)
        print(f"MAPA={m['asset']} status={status} audit={m['audit_status']}", flush=True)
        if list_only:
            continue
        if all_maps and not include_classified and status.startswith('REGIOES=') and not status.startswith('REGIOES=0 '):
            continue
        pending.append((m, dest))
    if list_only:
        return 0
    if limit > 0:
        pending = pending[:limit]
    print(f'CLASSIFICACAO_V21 pendentes={len(pending)} modo={"LOTE_SEQUENCIAL" if all_maps else "MAPA_UNICO"}', flush=True)
    if dry_run:
        for m, dest in pending:
            print(f"DRY_RUN abriria={m['preview_blend']} exportaria={dest}", flush=True)
        return 0
    failed = 0
    for i, (m, dest) in enumerate(pending, 1):
        if _file_sha256(m['source']) != m['source_sha256']:
            print(f"BLOQUEADO_FONTE_ALTERADA={m['asset']}", file=sys.stderr, flush=True)
            failed += 1
            continue
        if dest.exists() and _summarize(dest, m).startswith('ANOTACAO_INVALIDA='):
            print(f"BLOQUEADO_CLASSIFICACAO_INCOMPATIVEL={dest}", file=sys.stderr, flush=True)
            failed += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Same directory: image paths relative to the validated preview remain valid.
        fd, name = tempfile.mkstemp(prefix='.pt_v21_semantic_', suffix='.blend', dir=m['preview_blend'].parent)
        import os
        os.close(fd)
        disposable = Path(name)
        try:
            shutil.copy2(m['preview_blend'], disposable)
            args = list(blender_command) + [
                str(disposable), '--python', str(work), '--',
                '--asset', m['asset'], '--source-sha256', m['source_sha256'],
                '--output', str(dest),
            ]
            print(f"[{i}/{len(pending)}] BLENDER_ABRINDO={m['asset']} ", flush=True)
            print('Blender: painel N > Etervale > Classificação V21. Esc desativa pincel; fecha janela para próximo.', flush=True)
            rc = subprocess.run(args, cwd=project_root, check=False).returncode
            print(f"BLENDER_FECHADO={m['asset']} rc={rc} export={dest} status={_summarize(dest, m)}", flush=True)
            if rc != 0:
                failed += 1
        except KeyboardInterrupt:
            print('INTERRUPTED: os JSON já guardados permanecem disponíveis.', file=sys.stderr)
            raise
        finally:
            disposable.unlink(missing_ok=True)
            Path(str(disposable) + '1').unlink(missing_ok=True)
    print(f'RELATORIOS_V21={base / "maps"}')
    return 3 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Pincel semântico Etervale no Blender (proposta, read-only SMD)')
    ap.add_argument('--project-root', type=Path, default=Path.cwd())
    ap.add_argument('--map', dest='selected_asset', help='Ex.: Field/forest/fore-1.smd')
    ap.add_argument('--all', dest='all_maps', action='store_true', help='Abre todos sequencialmente')
    ap.add_argument('--list', dest='list_only', action='store_true', help='Lista classificações existentes')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--include-classified', action='store_true', help='No --all reabre também mapas já classificados')
    args = ap.parse_args(argv)
    try:
        return run(project_root=args.project_root, selected_asset=args.selected_asset,
                   all_maps=args.all_maps, list_only=args.list_only, dry_run=args.dry_run,
                   limit=max(0, args.limit), include_classified=args.include_classified)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'CLASSIFICACAO_V21_ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
