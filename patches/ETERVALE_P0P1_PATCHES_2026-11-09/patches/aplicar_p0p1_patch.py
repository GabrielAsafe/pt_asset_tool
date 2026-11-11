#!/usr/bin/env python3
"""Apply one/all incremental Etervale P0/P1 patches to the existing Asset Tool.

Strict hash preflight, no silent overwrites, per-patch backups, safe file names,
rollback of the current patch on failure. This script does not touch Etervale.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import time
import zipfile

PATCH_FILES = {
    'P0_01': 'etervale_P0_01_writers.zip',
    'P0_02': 'etervale_P0_02_content.zip',
    'P1_03': 'etervale_P1_03_missing_assets.zip',
    'P1_04': 'etervale_P1_04_quality.zip',
    'P1_05': 'etervale_P1_05_fields.zip',
    'P1_06': 'etervale_P1_06_ui.zip',
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def validate_path(raw: str, root: Path) -> Path:
    rel = PurePosixPath(raw)
    if not rel.parts or rel.is_absolute() or any(x in ('..','.') for x in rel.parts) or '\\' in raw or ':' in raw:
        raise ValueError(f'INVALID_PATCH_PATH:{raw}')
    target = root.joinpath(*rel.parts)
    parent = target.parent
    while parent != root:
        if parent.is_symlink():
            raise ValueError(f'PATCH_SYMLINK_PARENT_BLOCKED:{parent}')
        parent = parent.parent
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f'PATCH_TARGET_IS_SYMLINK_OR_NOT_FILE:{target}')
    if not inside(target.resolve(strict=False), root):
        raise ValueError(f'PATCH_OUTSIDE_PROJECT:{raw}')
    return target


def plan_patch(root: Path, zip_path: Path, patch_id: str, *, assumed_foundation: bool=False):
    if not zip_path.is_file():
        raise FileNotFoundError(f'PATCH_ZIP_NOT_FOUND:{zip_path}')
    with zipfile.ZipFile(zip_path) as z:
        if z.testzip() is not None:
            raise ValueError('PATCH_ZIP_CRC_FAILED')
        names = z.namelist()
        if len(set(names)) != len(names):
            raise ValueError('PATCH_ZIP_DUPLICATE_ENTRIES')
        if 'PATCH_MANIFEST.json' not in names:
            raise ValueError('PATCH_MANIFEST_MISSING')
        m = json.loads(z.read('PATCH_MANIFEST.json').decode('utf-8'))
        if m.get('format') != 'PT_ASSET_ETERVALE_SAFE_PATCH_V1' or m.get('id') != patch_id:
            raise ValueError('WRONG_PATCH_MANIFEST_OR_ID')
        rows = m.get('changes')
        if not isinstance(rows, list) or not rows:
            raise ValueError('PATCH_EMPTY_OR_BAD_MANIFEST')
        expected = {entry['path'] for entry in rows}
        if set(names) != expected | {'PATCH_MANIFEST.json'}:
            raise ValueError('PATCH_HAS_EXTRA_OR_MISSING_FILES')
        for path in m.get('requires', []):
            target = validate_path(path, root)
            if not target.is_file() and not assumed_foundation:
                raise ValueError(f'REQUIRED_PREVIOUS_PATCH_MISSING:{path}')
        plan = []
        for entry in rows:
            raw = entry['path']
            target = validate_path(raw, root)
            info=z.getinfo(raw)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'PATCH_ZIP_SYMLINK_BLOCKED:{raw}')
            payload=z.read(raw)
            if sha(payload) != entry.get('sha256') or len(payload)!=entry.get('bytes'):
                raise ValueError(f'PATCH_PAYLOAD_MISMATCH:{raw}')
            if not target.exists():
                if entry.get('before_sha256') is not None:
                    raise ValueError(f'EXPECTED_EXISTING_FILE_MISSING:{raw}')
                action='NEW'
            else:
                got=sha_file(target)
                if got == entry['sha256']:
                    action='ALREADY'
                elif entry.get('before_sha256') is not None and got == entry['before_sha256']:
                    action='MODIFY'
                else:
                    raise ValueError(f'LOCAL_FILE_CONFLICT:{raw}:sha256={got}:expected_before={entry.get("before_sha256")}')
            plan.append((raw,target,action,payload))
        return plan


def atomic_write(target: Path, data: bytes):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.etervale_patch_',delete=False) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        tmp=Path(stream.name)
    try:
        tmp.chmod(0o644)
        os.replace(tmp,target)
    finally:
        tmp.unlink(missing_ok=True)


def apply_one(root: Path, patches_dir: Path, patch_id: str, dry_run: bool,
              *, assumed_foundation: bool=False) -> dict:
    zip_path=patches_dir/PATCH_FILES[patch_id]
    plan=plan_patch(root, zip_path, patch_id, assumed_foundation=assumed_foundation)
    counts={item:sum(1 for x in plan if x[2]==item) for item in ('NEW','MODIFY','ALREADY')}
    print(f'{patch_id}: {zip_path.name} | novos={counts["NEW"]} modificados={counts["MODIFY"]} ja_aplicados={counts["ALREADY"]}')
    for raw, _target, action, _data in plan:
        if action=='MODIFY': print('  MODIFICAR COM BACKUP:',raw)
    if dry_run:
        return {'id':patch_id, 'status':'DRY_RUN', 'counts':counts}
    if counts['NEW']==counts['MODIFY']==0:
        print(f'  {patch_id}: ja aplicado; nenhuma alteracao.')
        return {'id':patch_id, 'status':'ALREADY_APPLIED', 'counts':counts}
    backup_root=patches_dir/'_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    backup=Path(tempfile.mkdtemp(prefix=f'etervale-{patch_id}-{stamp}-',dir=backup_root))
    backed={}
    done=[]
    try:
        # Copy all previous bytes before applying anything.
        for raw,target,action,payload in plan:
            if action=='MODIFY':
                out=backup/'files'/raw
                out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,out)
                backed[raw]=str(out)
        backup_manifest={'format':'PT_ASSET_ETERVALE_PATCH_BACKUP_V1','patch':patch_id,
                         'source_zip':str(zip_path),'entries':[{'path':raw,'action':action,
                          'before_sha256':sha_file(target) if target.is_file() else None,
                          'after_sha256':sha(payload)} for raw,target,action,payload in plan],
                         'backup_paths':backed}
        (backup/'manifest.json').write_text(json.dumps(backup_manifest,ensure_ascii=False,indent=2)+'\n')
        for raw,target,action,payload in plan:
            if action=='ALREADY':continue
            # Recheck content after preflight to protect against user modifications.
            if action=='MODIFY' and sha_file(target)!=next(x['before_sha256'] for x in backup_manifest['entries'] if x['path']==raw):
                raise RuntimeError(f'FILE_CHANGED_DURING_INSTALL:{raw}')
            if action=='NEW' and (target.exists() or target.is_symlink()):
                raise RuntimeError(f'NEW_FILE_APPEARED_DURING_INSTALL:{raw}')
            atomic_write(target,payload)
            done.append((raw,target,action))
        for raw,target,action,payload in plan:
            if sha_file(target)!=sha(payload):
                raise RuntimeError(f'POST_INSTALL_HASH_MISMATCH:{raw}')
    except Exception:
        for raw,target,action in reversed(done):
            if action=='NEW': target.unlink(missing_ok=True)
            elif action=='MODIFY': shutil.copy2(backed[raw],target)
        raise
    print(f'  {patch_id}: aplicado; backup {backup}')
    return {'id':patch_id, 'status':'APPLIED', 'counts':counts, 'backup':str(backup)}


def main() -> int:
    ap=argparse.ArgumentParser(description='Patch incremental Etervale P0/P1 com hash, backup e rollback')
    opt=ap.add_mutually_exclusive_group(required=True)
    opt.add_argument('--all',action='store_true')
    opt.add_argument('--id',choices=PATCH_FILES)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--project-root',type=Path,help='Asset Tool root (default: parent of patches/)')
    args=ap.parse_args()
    patches_dir=Path(__file__).resolve().parent
    root=(args.project_root or patches_dir.parent).resolve()
    if not (root/'app/pt_asset.py').is_file() or not (root/'app/pt_asset_tool/etervale_integration.py').is_file():
        raise ValueError(f'ASSET_TOOL_ROOT_NOT_FOUND:{root}')
    sequence=PATCH_FILES if args.all else (args.id,)
    summaries=[]
    for patch_id in sequence:
        try:
            r=apply_one(root,patches_dir,patch_id,args.dry_run,
                        assumed_foundation=bool(args.all and args.dry_run and patch_id!='P0_01'))
            summaries.append(r)
        except Exception as exc:
            print(f'ERRO EM {patch_id}: {type(exc).__name__}: {exc}',file=sys.stderr)
            return 2
    print('TOTAL:',len(summaries),'patches; modo=' + ('DRY-RUN' if args.dry_run else 'APLICADO/JA APLICADO'))
    return 0


if __name__=='__main__':
    sys.exit(main())
