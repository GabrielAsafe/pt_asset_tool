#!/usr/bin/env python3
"""SUMMIT 383A: publica snapshot JSON do catalogo real do cliente, fail-closed.

Nao edita .inc, items, DAT, packs nem a SQLite. inspect/apply/undo.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from client_profile_map_383a import CLIENT_SOURCE, MAP_SOURCE, MAP_SCHEMA, rows_from_inc, sha, validate_map

PROFILE = 'Content/canonical/item_profiles/client.items.json'
BASE_REL = 'bugfixes/SUMMIT_PATCH_383A_PERFIL_CLIENTE_JSON_2026-10-30/fixtures/baseline_client_item_codes.json'
BACKUPS = 'bugfixes/_backups_383a_client_sync'
STATE = 'bugfixes/_state_383a_client_sync.json'
SERVER_MAP = 'Content/canonical/item_profiles/item_code_map.json'
TEXT_INDEX = 'Content/canonical/text/index.json'


def require(cond, message):
    if not cond:
        raise ValueError(message)


def read_regular(root: Path, relative: str) -> bytes:
    p = root / 'SourceCode' / relative
    require(p.is_file() and not p.is_symlink(), 'ficheiro necessario ausente/symlink: ' + str(p))
    return p.read_bytes()


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.summit383a_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def encode(doc) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def canonical_explicit_client(root: Path) -> set[str]:
    r = root / 'SourceCode/Content/canonical/text'
    index = json.loads(read_regular(root, TEXT_INDEX))
    result = set()
    for row in index.get('documents', []):
        if row.get('kind') != 'open_item_definition':
            continue
        p = r / row['json_path']
        require(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(r.resolve()), 'item canonical inseguro: ' + str(p))
        doc = json.loads(p.read_text(encoding='utf-8'))
        profiles = doc.get('runtime_profiles')
        if not isinstance(profiles, list) or 'client' not in profiles:
            continue
        code = doc.get('semantic', {}).get('fields', {}).get('code')
        if isinstance(code, str):
            result.add(code.casefold())
    return result


def check_baseline(root: Path, rows: list[dict[str,str]]):
    base = root / BASE_REL
    require(base.is_file() and not base.is_symlink(), 'fixture do patch 383A ausente: ' + str(base))
    baseline = json.loads(base.read_text(encoding='utf-8'))
    require(baseline.get('schema') == 'summit.client-item-code-baseline/v1', 'baseline invalido')
    baseline_rows = baseline['entries']
    old_by_code = collections.defaultdict(collections.Counter)
    for x in baseline_rows:
        old_by_code[x['code'].casefold()][x['numeric']] += 1
    new_by_code = collections.defaultdict(collections.Counter)
    for x in rows:
        new_by_code[x['code'].casefold()][x['numeric']] += 1
    missing = sorted(set(old_by_code) - set(new_by_code))
    changed = sorted(x for x in old_by_code if x in new_by_code and old_by_code[x] != new_by_code[x])
    require(not missing, 'catalogo atual remove codigos legados: ' + ', '.join(missing[:12]))
    require(not changed, 'IDs/variantes existentes alterados no cliente: ' + ', '.join(changed[:12]))
    return set(old_by_code)


def plan(root: Path):
    inc = read_regular(root, CLIENT_SOURCE)
    rows = rows_from_inc(inc)
    old_codes = check_baseline(root, rows)
    raw_profile = read_regular(root, PROFILE)
    profile = json.loads(raw_profile.decode('utf-8-sig'))
    require(profile.get('schema') == 'summit.item-profile/v1' and profile.get('profile') == 'client' and profile.get('matching') == 'ascii-case-insensitive', 'client.items.json invalido')
    source = profile.get('source')
    require(isinstance(source, dict) and set(source) == {'path','sha256'} and source['path'] in (CLIENT_SOURCE, MAP_SOURCE), 'origem atual do perfil nao reconhecida')
    codes = profile.get('codes')
    require(isinstance(codes,list) and len(codes) >= 100 and all(isinstance(x,str) for x in codes) and len(codes) == len(set(x.casefold() for x in codes)), 'codigos atuais invalidos')
    previous = set(x.casefold() for x in codes)
    current = set(x['code'].casefold() for x in rows)
    require(previous <= current, 'codigos do perfil desaparecidos do catalogo C++: ' + ', '.join(sorted(previous-current)[:12]))
    added = sorted(current - previous)
    # New additions require explicit client runtime policy; an INC alone is not proof of allowed materialization.
    if added:
        allowed = canonical_explicit_client(root)
        require(set(added) <= allowed, 'codigos novos sem runtime_profiles=[client] explicito no Content: ' + ', '.join(sorted(set(added)-allowed)[:12]))
        new_num = collections.defaultdict(set)
        for x in rows:
            if x['code'].casefold() in added:
                new_num[x['code'].casefold()].add(x['numeric'])
        require(all(len(v) == 1 for v in new_num.values()), 'codigos novos com IDs multiplos')
        num_by_code = collections.defaultdict(set)
        for x in rows:
            num_by_code[x['numeric']].add(x['code'].casefold())
        for code in added:
            numeric = next(iter(new_num[code]))
            require(num_by_code[numeric] == {code}, 'ID do novo item colide no cliente: ' + code)
        server_raw = read_regular(root, SERVER_MAP)
        server = json.loads(server_raw.decode('utf-8-sig'))
        require(server.get('schema') == 'summit.item-code-map/v1', 'item_code_map.json do servidor invalido')
        server_values = {x['code'].casefold(): x['numeric'] for x in server['entries']}
        for code in added:
            if code in server_values:
                require(server_values[code] == next(iter(new_num[code])), 'IDs diferentes entre cliente e servidor: ' + code)
    map_data = encode({'schema': MAP_SCHEMA, 'source': {'path': CLIENT_SOURCE, 'sha256': sha(inc)}, 'entries': rows})
    profile['codes'] = codes + [next(x['code'] for x in rows if x['code'].casefold() == c) for c in added]
    profile['source'] = {'path': MAP_SOURCE, 'sha256': sha(map_data)}
    new_profile = encode(profile)
    map_path = root/'SourceCode'/MAP_SOURCE
    existing_map = None
    if map_path.exists():
        require(map_path.is_file() and not map_path.is_symlink(), 'snapshot JSON symlink/diretorio recusado')
        existing_map = map_path.read_bytes()
        # Only rewrite a published snapshot if it is the one pinned by the profile.
        require(source['path'] == MAP_SOURCE and source['sha256'] == sha(existing_map), 'snapshot existente nao confere com o perfil; recusa sobrescrever')
        validate_map(json.loads(existing_map))
    return {'before_profile':raw_profile,'before_map':existing_map,'after_profile':new_profile,'after_map':map_data,'new':added,'rows':len(rows),'old_count':len(old_codes),'inc_sha':sha(inc)}


def write_backup(root: Path, label: str, content: bytes) -> str:
    p = root/BACKUPS/(label+'_'+sha(content)+'.bak')
    require(not p.is_symlink(), 'backup symlink recusado')
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        require(p.read_bytes() == content, 'backup existente com conteudo divergente')
    else:
        with p.open('xb') as fd:
            fd.write(content)
            fd.flush()
            os.fsync(fd.fileno())
    return str(p.relative_to(root))


def apply(root, x):
    state_path = root/STATE
    require(not state_path.exists() and not state_path.is_symlink(), 'ja existe estado da sincronizacao 383A; usar inspect ou undo')
    current_profile = (root/'SourceCode'/PROFILE).read_bytes()
    require(current_profile == x['before_profile'], 'perfil alterado durante operacao')
    require(sha(read_regular(root,CLIENT_SOURCE)) == x['inc_sha'], 'catalogo do cliente alterado durante operacao')
    mp = root/'SourceCode'/MAP_SOURCE
    require((mp.read_bytes() if mp.exists() else None) == x['before_map'], 'snapshot alterado durante operacao')
    bp = write_backup(root, 'client_profile', x['before_profile'])
    bm = write_backup(root, 'client_snapshot', x['before_map']) if x['before_map'] is not None else None
    atomic(mp,x['after_map'])
    atomic(root/'SourceCode'/PROFILE,x['after_profile'])
    state = {'schema':'summit383a-client-sync/v1','profile_backup':bp,'map_backup':bm,'profile_after':sha(x['after_profile']),'map_after':sha(x['after_map'])}
    atomic(state_path,encode(state))
    print('SUMMIT383A_APPLY_PASS codes='+str(len(json.loads(x['after_profile'])['codes']))+' added='+str(len(x['new']))+' backup='+bp)


def undo(root):
    st=root/STATE
    require(st.is_file() and not st.is_symlink(),'estado 383A ausente')
    d=json.loads(st.read_bytes())
    require(d.get('schema') == 'summit383a-client-sync/v1', 'estado 383A invalido')
    p=root/'SourceCode'/PROFILE
    m=root/'SourceCode'/MAP_SOURCE
    require(p.is_file() and m.is_file() and not p.is_symlink() and not m.is_symlink() and sha(p.read_bytes()) == d['profile_after'] and sha(m.read_bytes()) == d['map_after'], 'perfil ou snapshot mudaram depois de 383A; recusa undo')
    bp=root/d['profile_backup']
    require(bp.is_file() and bp.resolve().is_relative_to((root/BACKUPS).resolve()),'backup de perfil invalido')
    old=bp.read_bytes()
    if d['map_backup']:
        bm=root/d['map_backup']
        require(bm.is_file() and bm.resolve().is_relative_to((root/BACKUPS).resolve()),'backup do snapshot invalido')
        atomic(m,bm.read_bytes())
    else:
        m.unlink()
    atomic(p,old)
    st.unlink()
    print('SUMMIT383A_UNDO_PASS')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['inspect','apply','undo'])
    ap.add_argument('--root',type=Path,default=Path('.'))
    args=ap.parse_args()
    root=args.root.expanduser().resolve()
    require((root/'SourceCode').is_dir() and (root/'bugfixes').is_dir(), 'executar --root na raiz summit')
    if args.action == 'undo':
        undo(root);return
    x=plan(root)
    print(f'SUMMIT383A_INSPECT catalog_rows={x["rows"]} legacy_baseline={x["old_count"]} added={x["new"]} needs_update={int(x["before_profile"]!=x["after_profile"] or x["before_map"]!=x["after_map"])}')
    if args.action=='inspect':
        print('SUMMIT383A_INSPECT_PASS');return
    if (root/STATE).exists():
        if x['before_profile']==x['after_profile'] and x['before_map']==x['after_map']:
            print('SUMMIT383A_ALREADY_APPLIED');return
        raise ValueError('estado existe com alteracoes adicionais: recusa')
    apply(root,x)


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError) as exc:
        print('SUMMIT383A_BLOCKED: '+str(exc),file=sys.stderr)
        sys.exit(2)
