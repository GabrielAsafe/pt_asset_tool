#!/usr/bin/env python3
"""V14 read-only triage for two Stage072 failures not proven to be tool bugs.

Shows the exact texture-overlay failure of pilai and the serialized hTexture
mismatch of dark_boss. It never launches Blender, repairs bytes or guesses
replacement textures, and does not rewrite any V13 audit checkpoint.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

PROJECT_APP = Path(__file__).resolve().parent
if str(PROJECT_APP) not in sys.path:
    sys.path.insert(0, str(PROJECT_APP))

from pt_asset_tool.stage072_corpus import parse_stage072
from pt_asset_tool.stage072_batch_audit import _load_checkpoint


DARK = 'Field/Boss/dark_boss.smd'
PILAI = 'Field/forever-fall/pilai.smd'


def _read_overlay(report_root: Path) -> dict:
    # V13 worker paths originate from a deterministic uppercase SHA256 prefix.
    import hashlib
    digest = hashlib.sha256(PILAI.encode('utf-8')).hexdigest()[:16].upper()
    base = report_root / 'preview_work' / f'STG-BATCH-{digest}' / 'stage072_preview'
    source = base / 'texture_overlay_report.json'
    if not source.is_file():
        return {'status': 'REPORT_NOT_FOUND', 'path': str(source)}
    try:
        data = json.loads(source.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'status':'REPORT_UNREADABLE', 'path':str(source), 'error':str(exc)}
    prepared = {'LINK_READY', 'BMP_PROTECTED_DECODED', 'BMP_SHIP_PROTECTED_DECODED', 'TGA_READY',
                'LINK_READY_RUNTIME_ALIAS', 'BMP_PROTECTED_DECODED_RUNTIME_ALIAS',
                'BMP_SHIP_PROTECTED_DECODED_RUNTIME_ALIAS', 'TGA_READY_RUNTIME_ALIAS'}
    failures = []
    for row in data.get('entries') or []:
        if not row.get('affects_ready'):
            continue
        status = str(row.get('status') or '')
        if status in prepared or status == 'MISSING':
            continue
        failures.append({key:row[key] for key in
                         ('logical','status','physical','error','log','returncode','required_by_faces')
                         if key in row})
    return {'status': 'EXISTING_TEXTURE_PREPARATION_FAILURE' if failures else 'NO_HARD_FAILURES_IN_SAVED_OVERLAY',
            'path': str(source), 'hard_failures': failures[:50], 'hard_failure_count': len(failures),
            'missing_or_invalid_count': sum(1 for row in data.get('entries') or [] if row.get('status') == 'MISSING')}


def _read_dark(client_root: Path) -> dict:
    source = client_root / DARK
    if not source.is_file():
        return {'status':'SOURCE_NOT_FOUND', 'path': str(source)}
    try:
        parsed = parse_stage072(source)
    except Exception as exc:
        return {'status': 'PARSER_EXCEPTION', 'error':f'{type(exc).__name__}: {exc}'}
    mats = parsed.get('materials') or []
    sample = (parsed.get('errors') or {}).get('htexture_mapping') or []
    ids = sorted({int(err.get('material', -1)) for err in sample if 'material' in err})
    material_rows = []
    for mid in ids[:10]:
        if not 0 <= mid < len(mats):
            continue
        m = mats[mid]
        material_rows.append({'id':mid, 'TextureCounter':m.get('TextureCounter'),
                              'AnimTexCounter':m.get('AnimTexCounter'),
                              'TextureType':m.get('TextureType'),
                              'BlendType':m.get('BlendType'),
                              'TextureStageState':(m.get('TextureStageState') or [])[:4],
                              'textures':(m.get('textures') or [])[:4]})
    return {'status':'SOURCE_HARD_MAPPING_FAILURE' if sample else 'NO_HANDLE_MISMATCH_IN_SAVED_SOURCE',
            'parse':parsed.get('full_parse'), 'source_sha256':parsed.get('sha256'),
            'htexture_mapping_sample':sample[:12], 'material_context':material_rows,
            'other_parser_errors':{k:v for k,v in (parsed.get('errors') or {}).items() if k != 'htexture_mapping' and v}}


def run(app: Path, client_root: Path, output: Path | None = None) -> dict:
    report_root = app / 'pt_build' / 'etervale' / 'stage072_all_maps'
    result = {'format':'PT_ETERVALE_STAGE072_V14_RESIDUAL_TRIAGE_V1',
              'readonly':True,'client_modified':False,
              'pilai':_read_overlay(report_root),
              'dark_boss':_read_dark(client_root)}
    # Output is optional and always outside the client root; no automatic
    # changes to checkpoint/overlay/model files.
    if output is not None:
        destination = output.expanduser().resolve()
        root = client_root.resolve()
        if destination == root or root in destination.parents:
            raise ValueError('TRIAGE_OUTPUT_INSIDE_CLIENT_REFUSED')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path, default=PROJECT_APP.parent)
    parser.add_argument('--client-root',type=Path,default=None)
    parser.add_argument('--output',type=Path,default=None)
    args=parser.parse_args()
    project=args.project_root.expanduser().resolve()
    app=project / 'app' if (project / 'app/pt_asset.py').is_file() else project
    summary=app / 'pt_build/etervale/stage072_all_maps/stage_0_summary.json'
    if args.client_root is not None:
        client=args.client_root.expanduser().resolve()
    elif summary.is_file():
        client=Path(json.loads(summary.read_text(encoding='utf-8'))['client_root']).resolve()
    else:
        parser.error('necessário --client-root, pois não existe stage_0_summary.json')
    data=run(app,client,args.output)
    print(json.dumps(data,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
