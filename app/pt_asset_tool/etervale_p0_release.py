"""Fail-closed P0 release gate for native authoring and binary writer probes.

Only existing assets; no new entities or identities. Every source/candidate/proof
is hash anchored. Atomic per-file promotion, journaled backups and guarded
rollback. This never certifies runtime behavior and never touches C# readers.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import stat
import tempfile
import uuid
from typing import Any

from . import etervale_integration as bridge
from . import etervale_native_pipeline as native
from . import etervale_p0_binary as binary

PLAN_FORMAT='PT_ASSET_ETERVALE_P0_RELEASE_PLAN_V1'
RELEASE_FORMAT='PT_ASSET_ETERVALE_P0_RELEASE_JOURNAL_V1'


def digest(data:bytes)->str: return hashlib.sha256(data).hexdigest()


def hashfile(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def private_file(path:pathlib.Path,work:pathlib.Path)->pathlib.Path:
    path=path.expanduser().resolve(strict=True)
    if not bridge._within(path,work.resolve(strict=True)) or not path.is_file():
        raise ValueError('P0_PROOF_OR_CANDIDATE_MUST_BE_UNDER_PRIVATE_PT_BUILD')
    if path.is_symlink():raise ValueError('P0_PRIVATE_SYMLINK_FORBIDDEN')
    return path


def _asset_target(root:pathlib.Path,relative:str)->pathlib.Path:
    if not isinstance(relative,str) or not relative or '\\' in relative or relative.startswith('/'):
        raise ValueError('P0_ASSET_PATH_NOT_RELATIVE')
    rel=pathlib.PurePosixPath(relative)
    if '..' in rel.parts or '.' in rel.parts or len(rel.parts)<2:
        raise ValueError('P0_ASSET_PATH_UNSAFE')
    asset_root=root/'assets'
    if asset_root.is_symlink():raise ValueError('P0_ASSETS_SYMLINK_FORBIDDEN')
    path=asset_root.joinpath(*rel.parts)
    for ancestor in (path,*path.parents):
        if ancestor==asset_root.parent:break
        if ancestor.is_symlink():raise ValueError('P0_GAME_ASSET_SYMLINK_FORBIDDEN')
    resolved=path.resolve(strict=True)
    if not bridge._within(resolved,asset_root.resolve(strict=True)) or not resolved.is_file():
        raise ValueError('P0_GAME_ASSET_INVALID_OR_NEW_ENTITY')
    return resolved


def _read_proof(path:pathlib.Path,work:pathlib.Path)->tuple[pathlib.Path,dict]:
    path=private_file(path,work)
    obj=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj,dict):raise ValueError('P0_PROOF_NOT_JSON_OBJECT')
    return path,obj


def _entry(root:pathlib.Path,work:pathlib.Path,rel:str,src_sha:str,candidate:pathlib.Path,cand_sha:str)->dict:
    target=_asset_target(root,rel)
    candidate=private_file(candidate,work)
    if target==candidate:raise ValueError('P0_CANDIDATE_IS_GAME_SOURCE')
    if hashfile(target)!=src_sha:raise ValueError('P0_GAME_SOURCE_HASH_STALE:'+rel)
    if hashfile(candidate)!=cand_sha:raise ValueError('P0_CANDIDATE_HASH_STALE:'+rel)
    if src_sha==cand_sha:raise ValueError('P0_UNCHANGED_CANDIDATE_NOT_PUBLISHABLE:'+rel)
    return {'asset':rel,'target':str(target),'previous_sha256':src_sha,
            'candidate':str(candidate),'candidate_sha256':cand_sha}


def make_native_plan(root:pathlib.Path,work:pathlib.Path,manifest:pathlib.Path,verification:pathlib.Path)->dict:
    obj, mp=native._load_manifest(manifest,work)
    pf,report=_read_proof(verification,work)
    if report.get('status')!='PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED':
        raise ValueError('P0_NATIVE_SEMANTIC_PROOF_NOT_APPROVED')
    if pathlib.Path(str(report.get('manifest',''))).resolve()!=mp or report.get('game_assets_modified') is not False:
        raise ValueError('P0_NATIVE_PROOF_MANIFEST_OR_SOURCE_MISMATCH')
    if report.get('new_unresolved') or report.get('semantic_errors'):
        raise ValueError('P0_NATIVE_PROOF_HAS_ERRORS')
    steps=report.get('steps') or {}
    if not all(isinstance(steps.get(k),dict) and steps[k].get('exit_code')==0
               and steps[k].get('steps') for k in ('baseline','candidate')):
        raise ValueError('P0_NATIVE_WORLDIMPORT_EXECUTION_EVIDENCE_REQUIRED')
    if obj.get('probe_only') is not False or obj.get('authoring_intent')!='USER_JSON_RECIPE':
        raise ValueError('P0_NATIVE_EXPERIMENTAL_PROBE_NOT_PUBLISHABLE_USE_AUTHORED_RECIPE')
    if pathlib.Path(obj['game_root']).resolve()!=root.resolve() or obj.get('identity_review_required'):
        raise ValueError('P0_NATIVE_IDENTITY_OR_ROOT_NOT_APPROVED')
    entries=[]
    for f in obj['files']:
        if f.get('new_entity') or f.get('identity_registry_review'):
            raise ValueError('P0_NEW_ENTITY_PUBLICATION_BLOCKED')
        rel=native._path(f['path'])
        entries.append(_entry(root,work,'GameServer/'+rel.as_posix(),
                              f['source_sha256'],mp.parent/'overlay'/pathlib.Path(*rel.parts),f['new_sha256']))
    changes=report.get('semantic_catalog_changes') or {}
    if any(e['asset'].split('/')[1] not in changes or not changes[e['asset'].split('/')[1]] for e in entries):
        raise ValueError('P0_NATIVE_DOMAIN_HAS_NO_SEMANTIC_CATALOG_EVIDENCE')
    return _save_plan(root,work,'NATIVE_GAME_SERVER',entries,pf)


def make_binary_plan(root:pathlib.Path,work:pathlib.Path,proof:pathlib.Path)->dict:
    pf,obj=_read_proof(proof,work)
    if obj.get('format')!=binary.FORMAT or obj.get('status')!='PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED' or obj.get('reader_status')!='READER_ACCEPTED':
        raise ValueError('P0_BINARY_NATIVE_READER_EVIDENCE_REQUIRED')
    if obj.get('probe_only') is not False or obj.get('authoring_intent') != 'USER_SCALAR_EDIT':
        raise ValueError('P0_BINARY_PROBE_CANDIDATE_NOT_PUBLISHABLE_USE_MANUAL_EDITOR')
    if obj.get('game_assets_modified') is not False or obj.get('writer_status')!='PASS':
        raise ValueError('P0_BINARY_WRITER_UNVERIFIED')
    reader=obj.get('reader_result') or {}
    if reader.get('exit_code')!=0 or not reader.get('steps'):
        raise ValueError('P0_BINARY_CSHARP_READER_EXECUTION_EVIDENCE_REQUIRED')
    evidence=obj.get('writer_evidence') or {}
    if evidence.get('status')!='PASS' or evidence.get('allowed_offsets_only') is not True:
        raise ValueError('P0_BINARY_OFFSETS_NOT_CERTIFIED')
    rel=str(obj['asset'])
    entry=_entry(root,work,rel,obj['source_sha256'],pathlib.Path(obj['candidate']),obj['candidate_sha256'])
    if pathlib.Path(obj.get('source','')).resolve()!=pathlib.Path(entry['target']):
        raise ValueError('P0_BINARY_SOURCE_PATH_MISMATCH')
    return _save_plan(root,work,'SMD_SMB_INX', [entry],pf)


def _canonical(data:dict)->bytes:
    return json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')


def _write_status(work:pathlib.Path, status:str, **extra)->None:
    folder=work/'p0_release';folder.mkdir(parents=True,exist_ok=True)
    payload={'format':'PT_ASSET_ETERVALE_P0_RELEASE_STATUS_V1',
             'status':status,'proof_level':'SHA_ANCHORED_STAGING_WITH_MANUAL_APPROVAL',
             'runtime_certification':'NOT_CERTIFIED',**extra}
    _atomic(folder/('status_'+uuid.uuid4().hex+'.json'),_canonical(payload)+b'\n')


def _save_plan(root:pathlib.Path,work:pathlib.Path,kind:str,entries:list[dict],proof:pathlib.Path)->dict:
    if not 1<=len(entries)<=100 or len({x['target'].casefold() for x in entries})!=len(entries):
        raise ValueError('P0_RELEASE_ENTRIES_INVALID')
    bare={'format':PLAN_FORMAT,'kind':kind,'game_root':str(root.resolve()),'entries':entries,
          'proof_file':str(proof),'proof_sha256':hashfile(proof),
          'runtime_certification':'NOT_CERTIFIED','manual_approval_required':True}
    bare['approval_sha256']=digest(_canonical(bare))
    folder=work/'p0_release'/'plans';folder.mkdir(parents=True,exist_ok=True)
    output=folder/(uuid.uuid4().hex+'.json')
    _atomic(output,_canonical(bare)+b'\n')
    _write_status(work,'PLAN_CREATED_NO_GAME_CHANGES',plan=str(output),kind=kind)
    return {'status':'PLAN_CREATED_NO_GAME_CHANGES','plan':str(output),
            'approval_sha256':bare['approval_sha256'],'files':len(entries),'kind':kind,
            'game_assets_modified':False}


def _atomic(dest:pathlib.Path,raw:bytes):
    dest.parent.mkdir(parents=True,exist_ok=True)
    mode=stat.S_IMODE(dest.stat().st_mode) if dest.exists() else 0o644
    fd,temp=tempfile.mkstemp(prefix='.p0-safe-',dir=str(dest.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(temp,mode)
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)


@contextlib.contextmanager
def _lock(work:pathlib.Path):
    parent=work/'p0_release'; parent.mkdir(parents=True,exist_ok=True)
    with (parent/'release.lock').open('ab') as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def _load_plan(root:pathlib.Path,work:pathlib.Path,plan:pathlib.Path)->dict:
    fp=private_file(plan,work)
    if fp.parent!= (work/'p0_release'/'plans').resolve():
        raise ValueError('P0_RELEASE_PLAN_WRONG_DIRECTORY')
    obj=json.loads(fp.read_text(encoding='utf-8'))
    if obj.get('format')!=PLAN_FORMAT or obj.get('game_root')!=str(root.resolve()):
        raise ValueError('P0_RELEASE_PLAN_INVALID_GAME_ROOT')
    approve=obj.pop('approval_sha256',None)
    if approve!=digest(_canonical(obj)):
        raise ValueError('P0_RELEASE_PLAN_INTEGRITY_FAILURE')
    obj['approval_sha256']=approve
    proof=private_file(pathlib.Path(obj['proof_file']),work)
    if hashfile(proof)!=obj['proof_sha256']:
        raise ValueError('P0_RELEASE_PROOF_CHANGED_SINCE_PLAN')
    if not isinstance(obj.get('entries'),list) or not 1<=len(obj['entries'])<=100:
        raise ValueError('P0_RELEASE_PLAN_ENTRIES_INVALID')
    seen=set()
    for e in obj['entries']:
        target=_asset_target(root,e['asset'])
        if str(target)!=e['target']:
            raise ValueError('P0_RELEASE_TARGET_CHANGED')
        if e['target'].casefold() in seen:raise ValueError('P0_RELEASE_DUPLICATE_TARGET')
        seen.add(e['target'].casefold())
        if hashfile(target)!=e['previous_sha256']:
            raise ValueError('P0_RELEASE_GAME_ASSET_CHANGED_SINCE_PLAN')
        candidate=private_file(pathlib.Path(e['candidate']),work)
        if hashfile(candidate)!=e['candidate_sha256']:
            raise ValueError('P0_RELEASE_CANDIDATE_CHANGED_SINCE_PLAN')
    return obj


def apply(root:pathlib.Path,work:pathlib.Path,plan:pathlib.Path,approve:str)->dict:
    with _lock(work):
        obj=_load_plan(root,work,plan)
        if approve!=obj['approval_sha256']:
            raise ValueError('P0_APPROVAL_SHA256_REQUIRED_AND_MUST_MATCH_PLAN')
        release=work/'p0_release'/'releases'/uuid.uuid4().hex
        release.mkdir(parents=True,exist_ok=False)
        journal={'format':RELEASE_FORMAT,'status':'PREPARED','game_root':obj['game_root'],
                 'approval_sha256':obj['approval_sha256'],'entries':obj['entries'],
                 'backup_directory':str(release/'backups'),'runtime_certification':'NOT_CERTIFIED'}
        for i,e in enumerate(obj['entries']):
            src=pathlib.Path(e['target']);back=release/'backups'/f'{i:04d}.backup'
            back.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,back)
            if hashfile(back)!=e['previous_sha256']:raise ValueError('P0_BACKUP_HASH_MISMATCH')
        journal_path=release/'journal.json'
        _atomic(journal_path,_canonical(journal)+b'\n')
        try:
            journal['status']='IN_PROGRESS'
            _atomic(journal_path,_canonical(journal)+b'\n')
            for e in obj['entries']:
                _atomic(pathlib.Path(e['target']),pathlib.Path(e['candidate']).read_bytes())
                if hashfile(pathlib.Path(e['target']))!=e['candidate_sha256']:
                    raise ValueError('P0_POST_PUBLICATION_HASH_MISMATCH')
            journal['status']='PUBLISHED_NOT_RUNTIME_CERTIFIED'
            _atomic(journal_path,_canonical(journal)+b'\n')
        except BaseException:
            for i,e in reversed(list(enumerate(obj['entries']))):
                back=release/'backups'/f'{i:04d}.backup'
                if back.exists():_atomic(pathlib.Path(e['target']),back.read_bytes())
            journal['status']='ROLLED_BACK_AFTER_APPLY_ERROR'
            _atomic(journal_path,_canonical(journal)+b'\n')
            raise
        _write_status(work,journal['status'],journal=str(journal_path),files=len(obj['entries']))
        return {'status':journal['status'],'journal':str(journal_path),'files':len(obj['entries']),
                'rollback_available':True,'runtime_certification':'NOT_CERTIFIED'}


def rollback(root:pathlib.Path,work:pathlib.Path,journal_path:pathlib.Path,approve:str)->dict:
    with _lock(work):
        fp=private_file(journal_path,work)
        releases=(work/'p0_release'/'releases').resolve()
        if fp.name!='journal.json' or fp.parent.parent!=releases:
            raise ValueError('P0_ROLLBACK_JOURNAL_WRONG_DIRECTORY')
        journal=json.loads(fp.read_text(encoding='utf-8'))
        if journal.get('format')!=RELEASE_FORMAT or journal.get('game_root')!=str(root.resolve()):
            raise ValueError('P0_ROLLBACK_JOURNAL_INVALID')
        if journal.get('approval_sha256')!=approve:
            raise ValueError('P0_ROLLBACK_REQUIRES_ORIGINAL_PLAN_APPROVAL_SHA256')
        if journal.get('status') not in ('PUBLISHED_NOT_RUNTIME_CERTIFIED','IN_PROGRESS','PREPARED'):
            raise ValueError('P0_ROLLBACK_ALREADY_COMPLETED_OR_INVALID')
        entries=journal['entries']
        for i,e in enumerate(entries):
            target=_asset_target(root,e['asset'])
            if str(target)!=e['target'] or hashfile(target) not in (e['previous_sha256'],e['candidate_sha256']):
                raise ValueError('P0_ROLLBACK_TARGET_CHANGED_EXTERNALLY')
            backup=fp.parent/'backups'/f'{i:04d}.backup'
            if not backup.is_file() or backup.is_symlink() or hashfile(backup)!=e['previous_sha256']:
                raise ValueError('P0_ROLLBACK_BACKUP_CORRUPT')
        for i,e in enumerate(entries):
            _atomic(pathlib.Path(e['target']),(fp.parent/'backups'/f'{i:04d}.backup').read_bytes())
        journal['status']='ROLLED_BACK'
        _atomic(fp,_canonical(journal)+b'\n')
        _write_status(work,'ROLLED_BACK',journal=str(fp),files=len(entries))
        return {'status':'ROLLED_BACK','journal':str(fp),'files':len(entries)}


def plan_run(a:Any)->int:
    root=bridge._game_root(a);work=bridge._work_root()
    if a.manifest and a.verification and not a.binary_evidence:
        report=make_native_plan(root,work,a.manifest,a.verification)
    elif a.binary_evidence and not a.manifest and not a.verification:
        report=make_binary_plan(root,work,a.binary_evidence)
    else:raise ValueError('P0_CHOOSE_NATIVE_MANIFEST_PLUS_VERIFICATION_OR_BINARY_EVIDENCE')
    bridge._print(report);return 0


def apply_run(a:Any)->int:
    bridge._print(apply(bridge._game_root(a),bridge._work_root(),a.plan,a.approve));return 0


def rollback_run(a:Any)->int:
    bridge._print(rollback(bridge._game_root(a),bridge._work_root(),a.journal,a.approve));return 0


def register(sp:Any)->None:
    p=sp.add_parser('p0-release-plan',help='validate proof and create immutable SHA-approved promotion plan')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--manifest',type=pathlib.Path)
    p.add_argument('--verification',type=pathlib.Path)
    p.add_argument('--binary-evidence',type=pathlib.Path)
    p.set_defaults(func=plan_run)
    p=sp.add_parser('p0-release-apply',help='EXPLICITLY publish approved existing files; backup and journal')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--plan',type=pathlib.Path,required=True)
    p.add_argument('--approve',required=True,help='full approval_sha256 from p0-release-plan')
    p.set_defaults(func=apply_run)
    p=sp.add_parser('p0-release-rollback',help='restore backups, refusing overwritten/newer assets')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--journal',type=pathlib.Path,required=True)
    p.add_argument('--approve',required=True)
    p.set_defaults(func=rollback_run)
