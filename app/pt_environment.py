#!/usr/bin/env python3
"""V26 unified Environment Modernizer command; old CLI remains compatible."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

from pt_asset_tool.environment_library_v26 import inventory


def main(argv=None):
    ap = argparse.ArgumentParser(description='Etervale Environment Modernizer — Blender + biblioteca local')
    ap.add_argument('--project-root', type=Path, default=Path.cwd())
    ap.add_argument('--inventory', action='store_true', help='Listar modelos e materiais, sem abrir Blender')
    ap.add_argument('--prepare-model', metavar='FICHEIRO', help='Preparar 3 LODs numa sessão Blender em background')
    ap.add_argument('--prepare-all-models', action='store_true', help='Preparar todos os modelos de árvore, um de cada vez')
    ap.add_argument('--list-lods', action='store_true', help='Mostrar cache de LODs validada')
    ap.add_argument('--blender-command', help='Comando Blender explícito, ex: "flatpak run org.blender.Blender"')
    ap.add_argument('--map', default='Field/forest/fore-1.smd')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    root = args.project_root.expanduser().resolve()
    if args.inventory:
        doc = inventory(root/'AssetsForAutomaticSubstitution')
        print(f'BIBLIOTECA={doc["library_root"]} MODELOS={doc["model_candidates"]} MATERIAIS={doc["material_files"]}')
        for e in doc['entries']:
            print(f'{e["kind"]:11} {e["source"]:10} {e["name"]}')
        return 0
    if args.prepare_model or args.prepare_all_models or args.list_lods:
        from pt_asset_tool.environment_library_v26 import model_entries
        from pt_asset_tool.environment_lods_v28 import (
            ROOT_REL, LOD_BUDGETS, prepare_asset, validate_prepared,
        )
        choices = model_entries(root/'AssetsForAutomaticSubstitution')
        if args.list_lods:
            for e in choices:
                try:
                    _, doc = validate_prepared(root / ROOT_REL, Path(e.path), 'LOD1')
                    print(f'V28_LOD=READY name={e.name} '
                          f'faces_LOD0={doc["levels"]["LOD0"]["faces"]} '
                          f'faces_LOD1={doc["levels"]["LOD1"]["faces"]} '
                          f'faces_LOD2={doc["levels"]["LOD2"]["faces"]}')
                except (FileNotFoundError, ValueError, OSError):
                    print(f'V28_LOD=PENDING name={e.name}')
            return 0
        names = [e.name for e in choices] if args.prepare_all_models else [args.prepare_model]
        if not names:
            print('V28_NAO_HA_MODELOS_DE_ARVORE')
            return 2
        failed = 0
        for name in names:
            try:
                result = prepare_asset(name=name, project_root=root,
                     blender=args.blender_command, dry_run=args.dry_run)
                print(f'PT_V28_PREPARE={result["status"]} model={name} '
                      f'path={result.get("path", result.get("cache_destination", ""))}')
                if result.get('levels'):
                    for lod, detail in result['levels'].items():
                        quality = detail.get('quality', 'NAO_AVALIADA')
                        print(f'  {lod}: {detail["faces"]} faces, {detail["vertices"]} vertices, '
                              f'quality={quality}, passes={detail.get("passes", 0)}')
                if result.get('missing_textures'):
                    print(f'PT_V28_TEXTURES=REVIEW missing={result["missing_textures"][:12]}')
            except Exception as error:
                print(f'PT_V28_PREPARE=FAIL model={name} reason={type(error).__name__}:{error}', file=sys.stderr)
                failed += 1
                if not args.prepare_all_models:
                    break
        return 2 if failed else 0
    # One canonical launcher.  Reuse the source SHA validation, disposable
    # .blend lifecycle, and cross-platform Blender selection already tested.
    from pt_stage072_semantic_paint import main as original_main
    forwarded = ['--project-root', str(root)]
    if args.all:
        forwarded.append('--all')
    else:
        forwarded += ['--map', args.map]
    if args.dry_run:
        forwarded.append('--dry-run')
    return original_main(forwarded)


if __name__ == '__main__':
    sys.exit(main())
