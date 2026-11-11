#!/usr/bin/env python3
"""V13: scan ALL Stage 0.72 maps in one resumable, read-only batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pt_asset_tool.app_config import discover_client_root
from pt_asset_tool.stage072_batch_audit import run_all, worker_preview


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Audit all Etervale Stage0.72 maps; no game assets modified')
    ap.add_argument('--client-root', type=Path, help='defaults to configured PT client root')
    ap.add_argument('--output', type=Path, help='default app/pt_build/etervale/stage072_all_maps')
    ap.add_argument('--stage', type=int, default=0, help='texture paint target stage 0..7 (default 0)')
    ap.add_argument('--blender', action='store_true', help='headless import/transport/view for all maps; heavier; run when other Blender jobs idle')
    ap.add_argument('--limit', type=int, default=0, help='test only first N maps (default 0=all)')
    ap.add_argument('--fresh', action='store_true', help='recheck all maps; retains already produced working .blend files')
    ap.add_argument('--timeout', type=int, default=360, help='maximum seconds per map for Blender worker')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--worker-preview', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--asset', help=argparse.SUPPRESS)
    ap.add_argument('--worker-report', type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    project = Path(__file__).resolve().parent
    try:
        root = args.client_root.resolve() if args.client_root else discover_client_root(project)
        out = args.output or project / 'pt_build/etervale/stage072_all_maps'
        if args.worker_preview:
            if not args.asset or not args.worker_report:
                raise ValueError('WORKER_ASSET_AND_REPORT_REQUIRED')
            return worker_preview(project=project, root=root, rel=args.asset,
                                  output=out.resolve(), report=args.worker_report.resolve())
        result = run_all(project=project, client_root=root, output=out, stage=args.stage,
                         blender=args.blender, limit=args.limit, fresh=args.fresh,
                         timeout=args.timeout, quiet=args.quiet)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result['status'].startswith('PASS_') else 3
    except KeyboardInterrupt:
        print('INTERRUPTED: checkpoint preserved; rerun command to resume', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'STAGE072_BATCH_ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
