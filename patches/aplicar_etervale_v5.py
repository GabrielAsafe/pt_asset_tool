#!/usr/bin/env python3
"""Safe incremental installer for Etervale V5 migration evidence and legacy audit.

Place this script next to etervale_V5_UI_PROVAS_LEGACY_AUDIT_patch.zip inside
~/Transferências/pt_asset_tool/patches/. Run from the Asset Tool root.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

PATCH_NAME = 'etervale_V5_UI_PROVAS_LEGACY_AUDIT_patch.zip'

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def atomic(path: pathlib.Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.etervale-install-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o644)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def apply(root: pathlib.Path, archive: pathlib.Path, dry_run: bool) -> int:
    root=root.expanduser().resolve(strict=True)
    if not (root/'app'/'pt_asset.py').is_file() or not (root/'app'/'pt_asset_tool'/'etervale_p0p1_plugins.py').is_file():
        raise ValueError('ASSET_TOOL_ROOT_NOT_FOUND:'+str(root))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('PATCH_ZIP_CORRUPT')
        manifest=json.loads(z.read('PATCH_MANIFEST.json'))
        if manifest.get('patch_id')!='etervale-v5-evidence-and-legacy-audit':
            raise ValueError('PATCH_ID_MISMATCH')
        files=manifest['files']
        expected={f['path'] for f in files}|{'PATCH_MANIFEST.json'}
        if set(z.namelist()) != expected:
            raise ValueError('UNEXPECTED_PATCH_MEMBERS')
        changes=[]
        counters={'new':0,'modified':0,'already':0}
        for f in files:
            rel=pathlib.PurePosixPath(f['path'])
            if rel.is_absolute() or '..' in rel.parts or not rel.parts or f['kind'] not in ('new','modified'):
                raise ValueError('UNSAFE_PATCH_PATH')
            dest=root.joinpath(*rel.parts)
            if any(parent.is_symlink() for parent in [dest,*dest.parents] if parent!=root and root in parent.parents):
                raise ValueError('PATCH_PATH_SYMLINK_FORBIDDEN:'+str(rel))
            contents=z.read(f['path'])
            if digest(contents)!=f['sha256']:
                raise ValueError('PATCH_MEMBER_HASH_MISMATCH:'+str(rel))
            if dest.exists() or dest.is_symlink():
                if dest.is_symlink() or not dest.is_file():
                    raise ValueError('UNSAFE_EXISTING_DESTINATION:'+str(rel))
                existing=digest(dest.read_bytes())
                if existing==f['sha256']:
                    counters['already']+=1
                    continue
                if f['kind']!='modified' or existing!=f.get('old_sha256'):
                    raise ValueError('LOCAL_FILE_CONFLICT:'+str(rel))
                counters['modified']+=1
            elif f['kind']=='modified':
                raise ValueError('EXPECTED_EXISTING_FILE_MISSING:'+str(rel))
            else:
                counters['new']+=1
            changes.append((dest,contents,f['kind'],f['path']))
        print('Projeto:',root)
        print('Patch:',archive)
        print('Novos:',counters['new'],'modificados:',counters['modified'],'já aplicados:',counters['already'])
        for dest,_,kind,rel in changes:
            print(('  MODIFICAR (backup): ' if kind=='modified' else '  CRIAR: ')+rel)
        if dry_run:
            print('DRY-RUN: nenhum arquivo alterado.');return 0
        if not changes:
            print('Patch já aplicado; nenhuma alteração.');return 0
        tag=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        backup=root/'patches'/'_backups'/('etervale-v5-'+tag)
        backup.mkdir(parents=True,exist_ok=False)
        applied=[]
        try:
            for dest,data,kind,rel in changes:
                if kind=='modified':
                    back=backup/pathlib.Path(rel)
                    back.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(dest,back)
                atomic(dest,data)
                applied.append((dest,kind,rel))
            record={'format':'ETERVALE_PATCH_INSTALL_V1','patch':str(archive),'project':str(root),
                    'changes':[{'kind':kind,'path':rel} for _,kind,rel in applied]}
            (backup/'install_manifest.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
            for f in files:
                path=root.joinpath(*pathlib.PurePosixPath(f['path']).parts)
                assert digest(path.read_bytes())==f['sha256']
        except BaseException:
            for dest,kind,rel in reversed(applied):
                if kind=='new':dest.unlink(missing_ok=True)
                else:
                    shutil.copy2(backup/pathlib.Path(rel),dest)
            raise
        print('Patch aplicado. Backup:',backup)
        print('Valide: python3 -m pytest -q app/dev_tests/test_etervale_v5_migration_evidence.py')
        return 0

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=pathlib.Path,default=pathlib.Path.cwd())
    p.add_argument('--patch',type=pathlib.Path,default=pathlib.Path(__file__).resolve().with_name(PATCH_NAME))
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    try:return apply(a.project_root,a.patch,a.dry_run)
    except (ValueError,KeyError,FileNotFoundError,AssertionError,zipfile.BadZipFile) as e:
        print('ERRO:',e,file=sys.stderr)
        return 2
if __name__=='__main__':sys.exit(main())
