"""P0 native smoke changes on *existing* four-domain definitions.

Non-destructive: snapshots and edited overlays are stored in pt_build only;
optionally tests WorldImport in separate SQLite databases. Never changes
identities, paths, item codes, model links, or game assets.
"""
from __future__ import annotations

import json
import pathlib
import re
import uuid
from typing import Any

from . import etervale_integration as bridge
from . import etervale_native_pipeline as native
from .etervale_p0_alias import logical_candidates

FORMAT='PT_ASSET_ETERVALE_P0_CONTENT_PROBE_V1'
OPTIONS={
    'OpenItem': ('*레벨','*가격','*무게'),
    'Monster': ('*레벨','*경험치','*방어력'),
    'NPC': ('*E_CHAT','*B_CHAT','*J_CHAT','*T_CHAT','*E_NAME','*B_NAME','*NAME'),
    'Field': ('*DELAY','*MAX_ACTOR_POS','*MAX_ACTOR'),
}


def _tokens(text: str) -> list[str]:
    """Minimal safe tokenization, never guesses at importer grammar beyond scalar."""
    return re.findall(r'"[^"]*"|\S+',text)


def _probe_op(src: pathlib.Path, area: str) -> dict:
    lines=src.read_bytes().decode('cp949',errors='strict').splitlines()
    for token in OPTIONS[area]:
        keys={v.casefold() for v in logical_candidates(area,token)}
        hits=[(i,line) for i,line in enumerate(lines) if native._leading(line).casefold() in keys]
        if not hits: continue
        for hit_no,(line_no,line) in enumerate(hits):
            rest=line.strip().split(None,1)
            if len(rest)<2: continue
            values=_tokens(rest[1])
            if not values: continue
            if area=='NPC':
                # Prefer dialog. A display label is a fallback; identity uses
                # NPC file basename in IdentityRegistry.cs, not display name.
                word=values[0].strip('"')
                if not word or len(word)>150:continue
                changed=word+' P0_TEST'
                changed.encode('cp949')
                return {'op':'set','key':token,'occurrence':hit_no,'values':[changed]}
            else:
                # Choose a nonnegative scalar already parsed by WorldImport;
                # preserve every other value on the directive.
                if not re.fullmatch(r'-?\d+',values[0]):continue
                old=int(values[0])
                if not -1000000<=old<1000000:continue
                val=old+1
                tail=[int(x) if re.fullmatch(r'-?\d+',x) else x.strip('"') for x in values[1:]]
                return {'op':'set','key':token,'occurrence':hit_no,
                        'values':[val,*tail]}
    raise ValueError(f'P0_NO_SAFE_SCALAR_OR_DIALOG_IN:{area}:{src.name}')


def prepare(root:pathlib.Path, paths:list[str],work:pathlib.Path)->dict:
    server=root/'assets'/'GameServer'
    if len(paths)!=4: raise ValueError('P0_EXPECTS_FOUR_DOMAINS')
    files=[]
    for path in paths:
        rel=native._path(path)
        fp=native._source(server,rel)
        if not fp.is_file():raise FileNotFoundError(f'P0_SOURCE_MISSING:{path}')
        op=_probe_op(fp,rel.parts[0])
        files.append({'path':fp.relative_to(server).as_posix(),
                      'sha256':bridge._hash_file(fp),'operations':[op]})
    if {f['path'].split('/')[0] for f in files}!=set(OPTIONS):
        raise ValueError('P0_REQUIRES_ONE_OF_EACH_NATIVE_DOMAIN')
    recipe={'format':native.FORMAT,'files':files}
    filename=work/'native_pipeline'/('p0_recipe_'+uuid.uuid4().hex+'.json')
    filename.parent.mkdir(parents=True,exist_ok=True)
    filename.write_text(json.dumps(recipe,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    overlay=native.build_overlay(recipe,root,work)
    # Auto-generated test mutations must never be promoted as authored data.
    overlay['probe_only']=True
    overlay['authoring_intent']='AUTOMATED_EXPERIMENT'
    pathlib.Path(overlay['manifest']).write_text(json.dumps(overlay,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'recipe':str(filename),'manifest':overlay['manifest'],
            'operation_summaries':[{'path':f['path'],'operation':f['operations'][0]} for f in files],
            'overlay':overlay}


def choose_auto(root:pathlib.Path)->list[str]:
    server=root/'assets'/'GameServer'
    selections=[]
    for area, suffix in native.TYPES.items():
        folder=server/area
        if not folder.is_dir() or folder.is_symlink():
            raise FileNotFoundError('P0_NATIVE_DOMAIN_DIR_MISSING:'+area)
        selected=None
        for file in sorted(folder.iterdir(),key=lambda p:p.name.casefold()):
            if not file.is_file() or file.is_symlink() or file.suffix.lower()!=suffix or file.stat().st_size>native.MAX_SOURCE_SIZE:
                continue
            try:_probe_op(file,area)
            except (UnicodeError,ValueError):continue
            selected=file.relative_to(server).as_posix()
            break
        if not selected:raise ValueError('P0_AUTO_NO_SAFE_EXISTING_DEFINITION:'+area)
        selections.append(selected)
    return selections


def run(a:Any)->int:
    if a.build and not a.execute:raise ValueError('BUILD_REQUIRES_EXECUTE')
    root=bridge._game_root(a)
    paths=choose_auto(root) if a.auto else [a.item,a.monster,a.npc,a.field]
    if not a.auto and not all(paths):raise ValueError('P0_REQUIRES_FOUR_PATHS_OR_AUTO')
    if a.auto and any((a.item,a.monster,a.npc,a.field)):
        raise ValueError('P0_AUTO_AND_EXPLICIT_PATHS_ARE_MUTUALLY_EXCLUSIVE')
    out=prepare(root,paths,bridge._work_root())
    report={'format':FORMAT,'status':'CANDIDATES_READY_NOT_NATIVE_VERIFIED',
            'recipe':out['recipe'],'manifest':out['manifest'],
            'operations':out['operation_summaries'],'game_assets_modified':False,
            'identity_changes':False,'runtime_status':'NOT_CERTIFIED'}
    if a.execute:
        result=native.verify_overlay(pathlib.Path(out['manifest']),root,bridge._work_root(),execute=True,build=a.build)
        report['verification']=result
        report['status']=result['status']
    report['report_file']=bridge._write_report('content_compat',report)
    bridge._print(report)
    return 0 if report['status'] in ('CANDIDATES_READY_NOT_NATIVE_VERIFIED','PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED') else 3


def register(sp:Any)->None:
    p=sp.add_parser('p0-content-probe',help='probe real Item/Monster/NPC/Field authoring via WorldImport; staging only')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--auto',action='store_true',help='choose one safe existing file from each of four native domains')
    for key in ('item','monster','npc','field'):
        p.add_argument('--'+key,help='GameServer-relative file of matching format')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--build',action='store_true')
    p.set_defaults(func=run)
