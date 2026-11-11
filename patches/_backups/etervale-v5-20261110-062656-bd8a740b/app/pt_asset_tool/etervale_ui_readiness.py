"""P1/06: read-only evidence board for integration workflows.

Only reads fixed directories under the private pt_build/etervale tree; no
publishing, execution, or ability to display arbitrary filesystem files.
"""
from __future__ import annotations
import json
import pathlib
from typing import Any
from . import etervale_integration as bridge

DOMAINS={
    'writers': ('writer_probes', 'P0 Writer certification'),
    'closure': ('p0_closure', 'P0 Authoring integration gates'),
    'release': ('p0_release', 'P0 Controlled publication and rollback'),
    'content': ('content_compat', 'P0 Canonical content adaptation'),
    'dependencies': ('asset_gaps', 'P1 Missing assets'),
    'quality': ('quality', 'P1 Geometry, material, motion, effect quality'),
    'fields': ('fields', 'P1 SPM/SPP/SPC fields'),
    'p1_closure': ('p1_closure', 'P1 Consolidated gates (runtime separate)'),
}


def board(root: pathlib.Path) -> dict[str, Any]:
    evidence_root=root/'etervale'
    results=[]
    for key,(folder,title) in DOMAINS.items():
        folder_path=evidence_root/folder
        files=sorted((p for p in folder_path.glob('*.json') if p.is_file() and not p.is_symlink()),
                     key=lambda p: p.stat().st_mtime_ns, reverse=True)[:10] if folder_path.is_dir() else []
        latest=None
        for fp in files:
            if fp.stat().st_size > 8*1024*1024:
                continue
            try:
                obj=json.loads(fp.read_text(encoding='utf-8'))
                if isinstance(obj,dict) and 'status' in obj:
                    latest={'status':str(obj['status']), 'format':str(obj.get('format','')),
                            'evidence_file': fp.relative_to(root).as_posix(),
                            'proof_level':str(obj.get('proof_level',''))}
                    break
            except (OSError,ValueError):
                continue
        results.append({'id':key,'title':title,'evidence':latest,
                        'state':'NO_EVIDENCE' if latest is None else 'EVIDENCE_AVAILABLE'})
    return {'format':'PT_ASSET_ETERVALE_UI_BOARD_V1', 'status':'READ_ONLY',
            'authoritative_root':'ETERVALE_UNIFIED_V1',
            'runtime_certification':'NOT_AUTOMATICALLY_INFERRED',
            'items':results, 'game_assets_modified':False}


def run(a: Any) -> int:
    result=board(bridge.persistent_pt_build())
    bridge._print(result)
    return 0


def register(sp):
    x=sp.add_parser('ui-board', help='show latest P0/P1 evidence status used by UI')
    x.set_defaults(func=run)
