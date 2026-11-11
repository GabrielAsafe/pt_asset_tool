"""Read-only P0/P1 board with provenance-aware evidence selection.

A JSON file's filesystem timestamp is not itself proof of successful migration.
When P0 closure names a concrete four-domain proof, use that exact report, but
never hide a later failure: surface the newer attempt as REVIEW_REQUIRED.
Release selftests are clearly distinguished from publishing game assets.
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

CLOSURE_PASS = 'P0_AUTHORING_GATES_PASSED_NOT_RUNTIME_CERTIFIED'
CONTENT_PASS = 'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED'
CONTENT_FORMAT = 'PT_ASSET_ETERVALE_P0_CONTENT_PROBE_V1'
SELFTEST_FORMAT = 'PT_ASSET_ETERVALE_P0_RELEASE_SELFTEST_V1'
SELFTEST_PASS = 'PASS_ISOLATED_RELEASE_ROLLBACK_NOT_PRODUCTION'
MAX_BYTES = 8*1024*1024


def _load(path:pathlib.Path, allowed:pathlib.Path)->dict|None:
    """Only small, regular, private JSON reports; never follow symlinks."""
    try:
        if path.is_symlink() or not path.is_file() or path.suffix!='.json':return None
        if path.parent.resolve()!=allowed.resolve():return None
        if path.stat().st_size>MAX_BYTES:return None
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) and isinstance(value.get('status'),str) else None
    except (ValueError, OSError, UnicodeError):
        return None


def _recent(folder:pathlib.Path, maximum:int=300)->list[tuple[pathlib.Path,dict]]:
    if not folder.is_dir() or folder.is_symlink():return []
    paths=sorted((p for p in folder.glob('*.json') if p.is_file() and not p.is_symlink()),
                 key=lambda p:(p.stat().st_mtime_ns,p.name),reverse=True)
    found=[]
    for p in paths[:maximum]:
        value=_load(p,folder)
        if value is not None:found.append((p,value))
    return found


def _evidence(row:tuple[pathlib.Path,dict]|None, root:pathlib.Path,
              *, selected_by:str='MOST_RECENT_VALID_REPORT',source_kind:str='REPORT')->dict|None:
    if row is None:return None
    path,obj=row
    return {'status':str(obj['status']), 'format':str(obj.get('format','')),
            'evidence_file':path.relative_to(root).as_posix(),
            'proof_level':str(obj.get('proof_level','')),
            'selected_by':selected_by,'source_kind':source_kind}


def _closure_content(work:pathlib.Path)->tuple[tuple[pathlib.Path,dict]|None, pathlib.Path|None]:
    """Return the concrete 4-domain proof bound to the latest *passing* closure.

    The closure is an evidence index, not evidence that game runtime passed.
    The referenced report is checked independently before it can be displayed.
    """
    content_root=work/'content_compat'
    closures=_recent(work/'p0_closure')
    # A newer negative closure supersedes any older approval.
    if closures and closures[0][1].get('format')=='PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1' \
            and closures[0][1].get('status')!=CLOSURE_PASS:
        return None,None
    for closure_path,closure in closures:
        if closure.get('format')!='PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1':continue
        if closure.get('status')!=CLOSURE_PASS or closure.get('remaining_gates')!=[]:continue
        raw=closure.get('native_four_domain_import_proof')
        if not isinstance(raw,str) or not raw:continue
        try:
            target=pathlib.Path(raw).resolve(strict=True)
        except (OSError,ValueError):continue
        record=_load(target,content_root)
        if not record or record.get('format')!=CONTENT_FORMAT or record.get('status')!=CONTENT_PASS:continue
        if record.get('game_assets_modified') is not False:continue
        changes=(record.get('verification') or {}).get('semantic_catalog_changes') or {}
        if not all(changes.get(x) for x in ('OpenItem','Monster','NPC','Field')):continue
        return (target,record),closure_path
    return None,None


def board(root:pathlib.Path)->dict[str,Any]:
    root=pathlib.Path(root).resolve()
    work=root/'etervale'
    selected_content,closure_file=_closure_content(work)
    items=[]
    for key,(folder,title) in DOMAINS.items():
        reports=_recent(work/folder)
        current=reports[0] if reports else None
        choice=current
        source='MOST_RECENT_VALID_REPORT'
        state='EVIDENCE_AVAILABLE' if current is not None else 'NO_EVIDENCE'
        comment=None
        if key=='content' and selected_content is not None and closure_file is not None:
            # An attempt after the approval cannot be quietly ignored.
            newer_failure=next((row for row in reports if row[0].stat().st_mtime_ns>closure_file.stat().st_mtime_ns
                                and row[1].get('format') in (CONTENT_FORMAT,'PT_ASSET_ETERVALE_NATIVE_IMPORT_GATE_V2')
                                and row[1].get('status')!=CONTENT_PASS),None)
            if newer_failure is not None:
                choice=newer_failure
                state='REVIEW_NEWER_FAILURE'
                source='NEWER_ATTEMPT_AFTER_CLOSURE'
                comment='An older certified four-domain import exists, but a later attempt requires review.'
            else:
                choice=selected_content
                source='FOUR_DOMAIN_PROOF_REFERENCED_BY_PASSING_P0_CLOSURE'
                state='CERTIFIED_BY_P0_CLOSURE_NOT_RUNTIME'
                comment='Four-domain semantic import certified by the P0 closure; runtime not certified.'
        if key=='release':
            selftests=_recent(work/'p0_release_selftest')
            latest_pass=next(((p,d) for p,d in selftests if d.get('format')==SELFTEST_FORMAT and
                              d.get('status')==SELFTEST_PASS and d.get('selftest_only') is True and
                              d.get('production_assets_modified') is False),None)
            if current is None and latest_pass is not None:
                choice=latest_pass
                source='ISOLATED_RELEASE_SELFTEST_ONLY'
                state='ISOLATED_SELFTEST_ONLY'
                comment='Apply and rollback mechanics tested in a disposable directory; no production publication.'
            elif current is not None and latest_pass is not None:
                comment='Isolated release/rollback evidence also available; separate from actual publication history.'
        evidence=_evidence(choice,root,selected_by=source,
                           source_kind='ISOLATED_SELFTEST' if source=='ISOLATED_RELEASE_SELFTEST_ONLY' else 'REPORT')
        item={'id':key,'title':title,'evidence':evidence,'state':state}
        if comment:item['note']=comment
        if key=='content' and closure_file is not None:
            item['closure_evidence_file']=closure_file.relative_to(root).as_posix()
            if state=='REVIEW_NEWER_FAILURE':
                item['previous_certified_evidence']=_evidence(selected_content,root,
                    selected_by='PRIOR_PASSING_CLOSURE')
        items.append(item)
    return {'format':'PT_ASSET_ETERVALE_UI_BOARD_V2','status':'READ_ONLY',
            'authoritative_root':'ETERVALE_UNIFIED_V1',
            'runtime_certification':'NOT_AUTOMATICALLY_INFERRED',
            'items':items,'game_assets_modified':False}


def run(a:Any)->int:
    bridge._print(board(bridge.persistent_pt_build()))
    return 0


def register(sp):
    x=sp.add_parser('ui-board',help='show evidence provenance and P0/P1 statuses without publishing assets')
    x.set_defaults(func=run)
