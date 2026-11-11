#!/usr/bin/env python3
"""V23.1: restore one user-supplied, source-locked V22 forest detection.

Independent of Blender; restores *only* proposals lost after a zero-result
redetection. No edits to game assets or any original SMD are ever performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ASSET='Field/forest/fore-1.smd'
SOURCE_SHA='df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'
OUT_NAME='6cd0d6e8c7586543.v22_proposals.json'
EXPECTED_COUNT=103
FORMAT='PT_ETERVALE_STAGE072_OBJECT_PROPOSALS_V22'
RECOVERY_NAME='etervale_v23_1_fore1_v22_recovery.json'


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):
            h.update(block)
    return h.hexdigest()


def validate(doc, *, expected_candidates=None):
    if not isinstance(doc, dict) or doc.get('format') != FORMAT or doc.get('asset') != ASSET:
        raise ValueError('V22_RECOVERY_FORMAT_OR_ASSET_MISMATCH')
    if doc.get('source_sha256') != SOURCE_SHA or doc.get('source_face_count') != 35519 or doc.get('source_vertex_count') != 28732:
        raise ValueError('V22_RECOVERY_SOURCE_OR_TOPOLOGY_MISMATCH')
    if doc.get('publish_enabled') or not doc.get('not_game_runtime_certified'):
        raise ValueError('V22_RECOVERY_RUNTIME_FORBIDDEN')
    candidates=doc.get('candidates')
    if not isinstance(candidates,list) or (expected_candidates is not None and len(candidates) != expected_candidates):
        raise ValueError('V22_RECOVERY_CANDIDATE_COUNT_MISMATCH')
    ids=set()
    for c in candidates:
        if c.get('id') in ids or c.get('category') != 'ARVORE' or c.get('status') not in {'PENDING','APPROVED','NEEDS_REVIEW','REJECTED'} or c.get('accepted_for_runtime'):
            raise ValueError('V22_RECOVERY_BAD_CANDIDATE')
        ids.add(c['id'])
        faces=c.get('faces')
        if not isinstance(faces,list) or not faces or len(faces) != len(set(faces)) or any(type(i) is not int or i < 0 or i >= 35519 for i in faces):
            raise ValueError('V22_RECOVERY_BAD_FACE_IDS')
    return len(candidates)


def safe_target(root: Path):
    if not (root/'app/pt_asset.py').is_file():
        raise ValueError('PROJECT_ROOT_INVALID')
    output=root/'app/pt_build/etervale/stage072_semantic_v21/maps'/OUT_NAME
    for p in (output,output.parent,*[q for q in output.parents if q==root or root in q.parents]):
        if p.is_symlink():
            raise ValueError('TARGET_SYMLINK_BLOCKED')
    return output


def restore(root: Path,recovery: Path,*,dry_run:bool=False):
    root=root.expanduser().resolve()
    recovery=recovery.expanduser().resolve()
    if not recovery.is_file() or recovery.is_symlink():
        raise ValueError('RECOVERY_FILE_MISSING_OR_SYMLINK')
    target=safe_target(root)
    good=json.loads(recovery.read_text(encoding='utf-8'))
    validate(good,expected_candidates=EXPECTED_COUNT)
    if target.exists():
        existing=json.loads(target.read_text(encoding='utf-8'))
        n=validate(existing)
        if n:
            print(f'PRESERVADO: {n} propostas existentes; recuperação não substitui dados válidos')
            return 0
    else:
        print('SEM_FICHEIRO: um novo V22 será criado a partir da cópia fornecida')
    source=root.parent/'Etervale-git/assets'/ASSET
    if source.is_file() and sha(source)!=SOURCE_SHA:
        raise ValueError('SOURCE_SMD_SHA_MISMATCH_RESTORE_BLOCKED')
    if dry_run:
        print(f'DRY-RUN: restauraria {EXPECTED_COUNT} árvores em {target}; nenhum ficheiro alterado')
        return EXPECTED_COUNT
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        backup=target.parent/'_recovery_backups'/datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True,exist_ok=False)
        shutil.copy2(target,backup/OUT_NAME)
        print(f'BACKUP={backup/OUT_NAME}')
    data=recovery.read_bytes()
    fd,tmp=tempfile.mkstemp(prefix='.v23-1-restore-',dir=str(target.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    print(f'V22_RESTORED=PASS proposals={EXPECTED_COUNT} source_sha256={SOURCE_SHA} path={target}')
    print('V23: voltar ao Blender e clicar RECONSTRUIR ÁRVORES; não clicar V22 DETETAR')
    return EXPECTED_COUNT


def main():
    p=argparse.ArgumentParser(description='V23.1: recuperar V22 103 propostas fore-1 sem tocar no SMD')
    p.add_argument('--project-root',type=Path,default=Path.cwd())
    p.add_argument('--recovery-file',type=Path,default=Path(__file__).resolve().parents[1]/'patches'/RECOVERY_NAME)
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    try:
        restore(args.project_root,args.recovery_file,dry_run=args.dry_run)
        return 0
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print(f'VERIFICACAO_FALHOU: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
