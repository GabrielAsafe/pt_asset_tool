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


def _npc_probe_op(lines: list[str]) -> dict:
    """Pick a typed NPC field that reaches WorldImport's gameplay catalog.

    Display names are not a reliable proof: EnglishNames.Npc(path, label)
    can replace a source *NAME. ModelScale is persisted in `npcs` and has
    a documented default of 1 in ParsedNpc. Use a controlled, staging-only
    value if no suitable existing typed field is present.
    """
    # SourceTextReader.ReadChain stops reading the current file as soon as
    # *연결파일 is encountered. Anything appended after it would be ignored.
    link_at = next((i for i, line in enumerate(lines)
                    if native._leading(line).casefold() == '*연결파일'), None)
    if link_at is not None:
        lines = lines[:link_at]
    numeric = ('*레벨', '*이동범위', '*모델크기')
    for key in numeric:
        hits = [(i, line) for i, line in enumerate(lines)
                if native._leading(line).casefold() == key.casefold()]
        if not hits:
            continue
        # Avoid a duplicate directive whose last occurrence would override
        # the first. The importer reads and applies these in source order.
        line_no, line = hits[-1]
        rest = line.strip().split(None, 1)
        if len(rest) < 2:
            continue
        tokens = _tokens(rest[1])
        if not tokens:
            continue
        try:
            if key == '*모델크기':
                import math
                old = float(tokens[0]); new = old + 0.25
                if not math.isfinite(old) or not math.isfinite(new) or not 0 < old < 1000:
                    continue
            else:
                if not re.fullmatch(r'-?\d+', tokens[0]):
                    continue
                old = int(tokens[0])
                if not -1000000 <= old < 1000000:
                    continue
                new = old + 1
        except ValueError:
            continue
        return {'op': 'set', 'key': key, 'occurrence': len(hits)-1,
                'values': [new]}

    if link_at is not None:
        raise ValueError('P0_NPC_REQUIRES_TYPED_FIELD_BEFORE_LINK')
    # If no appearance/level scalar is defined locally, the C# parser accepts
    # this directive and stores ModelScale. Do not edit localized display
    # labels, which may be overridden by EnglishNames.Npc.
    return {'op': 'append', 'key': '*모델크기', 'values': [1.25]}


def _probe_op(src: pathlib.Path, area: str) -> dict:
    lines = src.read_bytes().decode('cp949', errors='strict').splitlines()
    if area == 'NPC':
        return _npc_probe_op(lines)
    # SourceTextReader.ReadChain ignores the rest of a source after the first
    # *연결파일, for items and monsters as well as NPCs.
    link_at = next((i for i, line in enumerate(lines)
                    if native._leading(line).casefold() == '*연결파일'), None)
    if link_at is not None:
        lines = lines[:link_at]
    for token in OPTIONS[area]:
        keys = {v.casefold() for v in logical_candidates(area, token)}
        hits = [(i, line) for i, line in enumerate(lines)
                if native._leading(line).casefold() in keys]
        if not hits:
            continue
        for hit_no, (line_no, line) in enumerate(hits):
            rest = line.strip().split(None, 1)
            if len(rest) < 2:
                continue
            values = _tokens(rest[1])
            if not values or not re.fullmatch(r'-?\d+', values[0]):
                continue
            old = int(values[0])
            if not -1000000 <= old < 1000000:
                continue
            val = old + 1
            tail = [int(x) if re.fullmatch(r'-?\d+', x) else x.strip('"')
                    for x in values[1:]]
            return {'op': 'set', 'key': token, 'occurrence': hit_no,
                    'values': [val, *tail]}
    raise ValueError(f'P0_NO_SAFE_SCALAR_OR_DIALOG_IN:{area}:{src.name}')


def _item_catalog_candidates(folder: pathlib.Path) -> list[pathlib.Path]:
    """Replicate the deterministic winner rule in Importer.ParseItems.

    The C# importer groups files by *코드 and selects the filename matching the
    code, if present; otherwise it selects the first file in ordinal path
    order. Picking the first item file alphabetically can choose an unselected
    variant, yielding false-negative semantic tests.
    """
    winners: dict[str, tuple[tuple[int, str], pathlib.Path]] = {}
    for file in folder.iterdir():
        if (not file.is_file() or file.is_symlink()
                or file.suffix.lower() != native.TYPES['OpenItem']
                or file.stat().st_size > native.MAX_SOURCE_SIZE):
            continue
        try:
            lines = file.read_bytes().decode('cp949', errors='strict').splitlines()
        except UnicodeError:
            continue
        code = None
        for line in lines:
            if native._leading(line) != '*코드':
                continue
            parts = _tokens(line.strip())
            if len(parts) >= 2:
                code = parts[1].strip('"')
            break
        if not code or not re.fullmatch(r'[A-Za-z]{2}[A-Za-z0-9][0-9]{2}', code):
            continue
        # StringComparer.Ordinal and IgnoreCase match on ASCII item codes.
        ranking = (0 if file.stem.casefold() == code.casefold() else 1, str(file))
        old = winners.get(code.casefold())
        if old is None or ranking < old[0]:
            winners[code.casefold()] = (ranking, file)
    return sorted((row[1] for row in winners.values()), key=lambda p: p.name.casefold())

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


def _npc_candidates(folder: pathlib.Path) -> list[pathlib.Path]:
    """Prefer self-contained sources: chained files can override earlier values."""
    ranked = []
    for file in folder.iterdir():
        if not file.is_file() or file.is_symlink() or file.suffix.lower() != '.npc':
            continue
        try:
            lines = file.read_bytes().decode('cp949', errors='strict').splitlines()
            has_link = any(native._leading(line).casefold() == '*연결파일' for line in lines)
        except UnicodeError:
            has_link = True
        ranked.append((int(has_link), file.name.casefold(), file))
    return [row[2] for row in sorted(ranked)]


def choose_auto(root: pathlib.Path) -> list[str]:
    server = root/'assets'/'GameServer'
    selections=[]
    for area, suffix in native.TYPES.items():
        folder=server/area
        if not folder.is_dir() or folder.is_symlink():
            raise FileNotFoundError('P0_NATIVE_DOMAIN_DIR_MISSING:'+area)
        selected=None
        if area == 'OpenItem':
            candidates = _item_catalog_candidates(folder)
        elif area == 'NPC':
            candidates = _npc_candidates(folder)
        else:
            candidates = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        for file in candidates:
            if (not file.is_file() or file.is_symlink() or file.suffix.lower()!=suffix
                    or file.stat().st_size>native.MAX_SOURCE_SIZE):
                continue
            try:
                _probe_op(file,area)
            except (UnicodeError,ValueError):
                continue
            selected=file.relative_to(server).as_posix()
            break
        if not selected:
            raise ValueError('P0_AUTO_NO_SAFE_EXISTING_DEFINITION:'+area)
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
