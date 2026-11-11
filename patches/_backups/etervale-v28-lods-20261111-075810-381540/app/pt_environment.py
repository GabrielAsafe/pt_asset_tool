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
