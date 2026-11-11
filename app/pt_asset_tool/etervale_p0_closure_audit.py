"""Evidence-based P0 closure audit. Does not conflate C# reader with game runtime.

Requires real Stage0.72 + Model0.62 + SMB + INX writer probes and one
four-domain WorldImport semantic probe. Release safety is code-tested and
requires manual approval; publishing is not required to certify authoring.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from . import etervale_integration as bridge
from .etervale_p0_binary import FORMAT as BINARY_FORMAT
from .etervale_p0_content_probe import FORMAT as CONTENT_FORMAT

FORMAT='PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1'
REQUIRED={'SMD_STAGE_072','SMD_MODEL_062','SMB','INX'}


def inspect(work:pathlib.Path)->dict:
    probes=work/'writer_probes'
    found={}
    if probes.is_dir():
        for fp in sorted(probes.glob('*.json'), key=lambda p:p.stat().st_mtime_ns,reverse=True):
            if fp.is_symlink() or fp.stat().st_size > 2*1024*1024:continue
            try:data=json.loads(fp.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if data.get('format')!=BINARY_FORMAT or data.get('status')!='PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED':continue
            if data.get('reader_status')!='READER_ACCEPTED' or data.get('game_assets_modified') is not False:continue
            ext=pathlib.PurePosixPath(str(data.get('asset') or '')).suffix.lower()
            key= ('SMD_'+str((data.get('writer_evidence') or {}).get('kind'))) if ext=='.smd' else ext.lstrip('.').upper()
            if key in REQUIRED and key not in found:
                found[key]=str(fp)
    native_proof=None
    content=work/'content_compat'
    if content.is_dir():
        for fp in sorted(content.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
            if fp.is_symlink() or fp.stat().st_size > 2*1024*1024:continue
            try:data=json.loads(fp.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if data.get('format')!=CONTENT_FORMAT or data.get('status')!='PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED':continue
            if data.get('game_assets_modified') is not False:continue
            changes=(data.get('verification') or {}).get('semantic_catalog_changes') or {}
            if all(changes.get(k) for k in ('OpenItem','Monster','NPC','Field')):
                native_proof=str(fp);break
    gaps=sorted(REQUIRED-set(found))
    if native_proof is None:gaps.append('GAME_SERVER_FOUR_DOMAIN_IMPORT')
    status='P0_AUTHORING_GATES_PASSED_NOT_RUNTIME_CERTIFIED' if not gaps else 'P0_AUTHORING_GATES_INCOMPLETE'
    return {'format':FORMAT,'status':status,
            'binary_reader_writer_proofs':found,'native_four_domain_import_proof':native_proof,
            'remaining_gates':gaps,'publication':'MANUAL_SHA_APPROVAL_AND_ROLLBACK_ONLY',
            'new_monster_npc_identities':'BLOCKED_UNTIL_EXPLICIT_REGISTRY_REVIEW',
            'legacy_summit_packs':'NOT_NATIVE_RUNTIME_FORMATS',
            'full_arbitrary_rigging_export':'NOT_CERTIFIED',
            'game_runtime':'NOT_CERTIFIED','proof_level':'C_SHARP_READER_PLUS_DISPOSABLE_WORLDIMPORT',
            'game_assets_modified':False}


def run(a:Any)->int:
    report=inspect(bridge._work_root())
    report['report_file']=bridge._write_report('p0_closure',report)
    bridge._print(report)
    return 0 if not report['remaining_gates'] else 3


def register(sp:Any)->None:
    p=sp.add_parser('p0-closure-audit',help='check real binary writer and four-domain WorldImport proofs; no runtime claims')
    p.set_defaults(func=run)
