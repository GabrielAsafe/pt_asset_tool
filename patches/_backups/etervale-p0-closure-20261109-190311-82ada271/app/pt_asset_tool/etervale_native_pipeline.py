"""Native JSON authoring -> GameServer overlay -> disposable WorldImport SQLite gate.

No reader changes. No writes into Etervale. An import gate is not runtime certification.
All filesystem outputs live in Asset Tool pt_build/etervale/native_pipeline.
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
import uuid
from typing import Any

from . import etervale_integration as bridge
from .runtime_paths import external_process_env

FORMAT = 'PT_ASSET_ETERVALE_NATIVE_RECIPE_V2'
MANIFEST = 'PT_ASSET_ETERVALE_NATIVE_OVERLAY_V2'
TYPES = {'OpenItem': '.txt', 'Monster': '.inf', 'NPC': '.npc', 'Field': '.spm'}
MAX_FILES = 100
MAX_SOURCE_SIZE = 2 * 1024 * 1024
MAX_GAME_FILES = 100_000
MAX_GAME_BYTES = 2 * 1024**3
KEY = re.compile(r'^\*{1,2}[^\s"\r\n\0]{1,78}$')
NAME = re.compile(r'^[^/\\\x00-\x1f]{1,160}$')


def _path(raw: str) -> pathlib.PurePosixPath:
    if not isinstance(raw, str) or '\\' in raw or raw.startswith('/') or raw.startswith('~'):
        raise ValueError('NATIVE_PATH_MUST_BE_RELATIVE_POSIX')
    rel = pathlib.PurePosixPath(raw)
    if (len(rel.parts) != 2 or any(p in ('.', '..') for p in rel.parts)
        or rel.parts[0] not in TYPES or rel.suffix.lower() != TYPES[rel.parts[0]]
        or not NAME.fullmatch(rel.name)):
        raise ValueError(f'NATIVE_PATH_INVALID:{raw}')
    return rel


def _inside(path: pathlib.Path, parent: pathlib.Path) -> pathlib.Path:
    path = path.resolve(strict=True)
    if not bridge._within(path, parent.resolve(strict=True)):
        raise ValueError('NATIVE_PATH_OUTSIDE_ALLOWED_ROOT')
    return path


def _source(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path:
    target = root.joinpath(*rel.parts)
    # Legacy tree has mixed case; casefold matching avoids creating a second
    # entity with the same name on a case-sensitive Linux filesystem.
    folder = root / rel.parts[0]
    if not folder.is_dir() or folder.is_symlink():
        raise FileNotFoundError(f'NATIVE_SUBDIRECTORY_NOT_FOUND_OR_UNSAFE:{folder}')
    matches = [p for p in folder.iterdir() if p.name.casefold() == rel.name.casefold()]
    if len(matches) > 1:
        raise ValueError(f'AMBIGUOUS_CASE_INSENSITIVE_NAME:{rel.as_posix()}')
    if matches and matches[0].is_symlink():
        raise ValueError('NATIVE_SOURCE_SYMLINK_FORBIDDEN')
    return _inside(matches[0], root) if matches else target


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encode_value(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('NATIVE_SCALAR_REQUIRED')
    text = str(value)
    if not text or any(c in text for c in ('\r', '\n', '\0', '"')):
        raise ValueError('NATIVE_VALUE_UNSAFE')
    if any(c.isspace() for c in text):
        return f'"{text}"'
    return text


def _directive(op: dict) -> str:
    key = op.get('key')
    if not isinstance(key, str) or not KEY.fullmatch(key) or key in ('*연결파일', '**연결파일'):
        raise ValueError('NATIVE_DIRECTIVE_KEY_INVALID_OR_LINK_FORBIDDEN')
    values = op.get('values', [])
    if not isinstance(values, list) or len(values) > 32:
        raise ValueError('NATIVE_VALUES_LIST_INVALID')
    line = ' '.join([key, *(_encode_value(v) for v in values)])
    line.encode('cp949', errors='strict')
    return line


def _leading(line: str) -> str:
    # Mirror Tokenizer.LeadingKey; unknown/comment lines are left untouched.
    pieces = line.strip(' \t').split(None, 1)
    return pieces[0] if pieces else ''


def _prepare_recipe(spec: dict, root: pathlib.Path) -> list[tuple[pathlib.PurePosixPath, bytes, dict]]:
    if not isinstance(spec, dict) or spec.get('format') != FORMAT:
        raise ValueError('NATIVE_RECIPE_V2_REQUIRED')
    files = spec.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('NATIVE_RECIPE_FILES_INVALID')
    originals = set()
    plans = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('NATIVE_RECIPE_FILE_NOT_OBJECT')
        target_rel = _path(item.get('path'))
        if target_rel.as_posix().casefold() in originals:
            raise ValueError('NATIVE_DUPLICATE_TARGET')
        originals.add(target_rel.as_posix().casefold())
        original_rel = _path(item.get('template', item['path']))
        if original_rel.parts[0] != target_rel.parts[0] or original_rel.suffix.lower() != target_rel.suffix.lower():
            raise ValueError('NATIVE_TEMPLATE_TYPE_MISMATCH')
        original = _source(root, original_rel)
        if not original.is_file() or original.is_symlink():
            raise FileNotFoundError(f'NATIVE_TEMPLATE_NOT_FOUND:{original_rel}')
        raw = original.read_bytes()
        if len(raw) > MAX_SOURCE_SIZE:
            raise ValueError('NATIVE_SOURCE_TOO_LARGE')
        expected = item.get('sha256')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError(f'NATIVE_SOURCE_SHA256_REQUIRED:{original_rel}')
        if _hash(raw) != expected:
            raise ValueError(f'NATIVE_SOURCE_CHANGED:{original_rel}')
        target_existing = _source(root, target_rel)
        if target_existing.is_file() and target_existing != original:
            raise ValueError('NATIVE_TARGET_ALREADY_EXISTS_USE_ITS_OWN_TEMPLATE')
        if target_existing.is_symlink():
            raise ValueError('NATIVE_SYMLINK_TARGET_FORBIDDEN')
        # Keep source line comments, unknown tokens, ordering and case. The
        # initial snapshot is a copy of an already working native definition.
        content = raw.decode('cp949', errors='strict')
        lines = content.splitlines()
        newline = '\r\n' if b'\r\n' in raw else '\n'
        final_newline = content.endswith(('\r', '\n'))
        ops = item.get('operations', [])
        if not isinstance(ops, list) or len(ops) > 250:
            raise ValueError('NATIVE_OPERATIONS_INVALID')
        changes=[]
        for op in ops:
            if not isinstance(op, dict) or op.get('op') not in ('set', 'append', 'delete'):
                raise ValueError('NATIVE_OPERATION_UNKNOWN')
            action = op['op']
            key = op.get('key')
            if not isinstance(key, str) or not KEY.fullmatch(key) or key in ('*연결파일', '**연결파일'):
                raise ValueError('NATIVE_OPERATION_KEY_INVALID')
            idx = [i for i, line in enumerate(lines) if _leading(line) == key]
            occurrence = op.get('occurrence')
            if occurrence is not None:
                if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0 or occurrence >= len(idx):
                    raise ValueError('NATIVE_OCCURRENCE_INVALID')
                idx = [idx[occurrence]]
            if action in ('set', 'delete') and len(idx) != 1:
                raise ValueError(f'NATIVE_OPERATION_REQUIRES_EXACT_MATCH:{key}:{len(idx)}')
            if action == 'set':
                lines[idx[0]] = _directive(op)
            elif action == 'delete':
                lines.pop(idx[0])
            else:
                lines.append(_directive(op))
            changes.append({'op': action, 'key': key, 'matched': len(idx)})
        if not ops:
            new_raw = raw  # exact byte-preserving no-op roundtrip
        else:
            new_raw = (newline.join(lines) + (newline if final_newline else '')).encode('cp949', errors='strict')
        target_path = target_rel.as_posix()
        # Cross-entity rules: a cloned monster identity/name or NPC filename
        # needs explicit review/identity registry work; never certify implicitly.
        new_entity = not target_existing.exists()
        plans.append((target_rel, new_raw, {'path': target_path, 'template': original_rel.as_posix(),
                                            'source_sha256': _hash(raw), 'new_sha256': _hash(new_raw),
                                            'new_entity': new_entity, 'operations': changes,
                                            'identity_registry_review': new_entity and target_rel.parts[0] in ('Monster','NPC')}))
    return plans


def build_overlay(spec: dict, game_root: pathlib.Path, work_root: pathlib.Path) -> dict:
    source_root = _inside(game_root/'assets'/'GameServer', game_root)
    prepared = _prepare_recipe(spec, source_root)
    output_root = work_root/'native_pipeline'/uuid.uuid4().hex
    output_root.mkdir(parents=True, exist_ok=False)
    outputs=[]
    for rel, raw, info in prepared:
        dst = output_root/'overlay'/pathlib.Path(*rel.parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        outputs.append({**info, 'output': str(dst), 'bytes': len(raw)})
    report = {'format': MANIFEST, 'status': 'OVERLAY_READY_REQUIRES_NATIVE_IMPORT',
              'proof_level': 'CP949_AND_SOURCE_HASH_CHECK_ONLY', 'game_root': str(game_root),
              'source_root': str(source_root), 'files': outputs,
              'identity_review_required': any(f['identity_registry_review'] for f in outputs),
              'game_assets_modified': False, 'no_reader_changes': True,
              'note': 'Use native-content-verify to run WorldImport against disposable SQLite copies; no publishing'}
    manifest = output_root/'manifest.json'
    report['manifest'] = str(manifest)
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def _load_manifest(path: pathlib.Path, work_root: pathlib.Path) -> tuple[dict, pathlib.Path]:
    path = _inside(path.expanduser(), work_root)
    if path.is_symlink() or not path.is_file() or path.name != 'manifest.json':
        raise ValueError('NATIVE_MANIFEST_MUST_BE_PRIVATE_FILE')
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict) or obj.get('format') != MANIFEST or not isinstance(obj.get('files'), list):
        raise ValueError('NATIVE_MANIFEST_FORMAT_INVALID')
    if not 1 <= len(obj['files']) <= MAX_FILES:
        raise ValueError('NATIVE_MANIFEST_FILE_COUNT_INVALID')
    overlay = path.parent/'overlay'
    for f in obj['files']:
        rel = _path(f['path'])
        fp = _inside(overlay.joinpath(*rel.parts), overlay)
        if fp.is_symlink() or _hash(fp.read_bytes()) != f['new_sha256']:
            raise ValueError('NATIVE_OVERLAY_HASH_CHANGED')
    return obj, path


def _scan(root: pathlib.Path) -> tuple[int, int, dict[str, str]]:
    count = size = 0
    fingerprints={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError(f'NATIVE_GAMESERVER_SYMLINK_REFUSED:{p.relative_to(root)}')
        if not p.is_file():
            continue
        count += 1
        size += p.stat().st_size
        if count > MAX_GAME_FILES or size > MAX_GAME_BYTES:
            raise ValueError('NATIVE_GAMESERVER_SNAPSHOT_BUDGET_EXCEEDED')
        fingerprints[p.relative_to(root).as_posix()] = bridge._hash_file(p)
    return count, size, fingerprints


def _db_evidence(path: pathlib.Path) -> dict:
    with sqlite3.connect(str(path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'items', 'monsters', 'npcs', 'fields', 'world_import_unresolved_refs',
                  'world_source_files', 'world_entity_variants'}
        if not required.issubset(tables):
            raise ValueError('WORLDIMPORT_SQLITE_CATALOG_TABLES_MISSING')
        counts={t:int(db.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0]) for t in sorted(required)}
        missing=collections.Counter((kind, owner, ref) for kind, owner, ref in db.execute(
            'SELECT kind,owner_key,raw_reference FROM world_import_unresolved_refs'))
        sources={rel:checksum.lower() for rel,checksum in db.execute('SELECT source_path,sha256 FROM world_source_files')}
        variants={rel:(kind, selected) for rel,kind,selected in db.execute(
            'SELECT source_path,kind,is_catalog_entry FROM world_entity_variants')}
        # Exclude source-preservation tables. Only changes to typed catalog
        # rows establish that a gameplay field was actually consumed.
        domains = {
            'OpenItem': ('items','item_definitions','item_texts','item_spec_bonuses','item_spec_random_classes','item_sets'),
            'Monster': ('monsters','monster_texts','monster_drop_lines','monster_drop_line_items','monster_bonus_drops'),
            'NPC': ('npcs','npc_texts','npc_dialog_lines','npc_services','npc_shop_items'),
            'Field': ('fields','field_spawn_points','field_monster_spawns','field_bosses','field_boss_hours','field_npcs'),
        }
        table_hashes={}
        for table in {t for group in domains.values() for t in group} & tables:
            digest=hashlib.sha256()
            # Independent connections should return the same table order for
            # logically identical data, even if the import query order differs.
            rows=list(db.execute('SELECT * FROM "'+table+'"'))
            for row in sorted(repr(tuple(r)) for r in rows):
                digest.update(row.encode('utf-8'))
                digest.update(b'\n')
            table_hashes[table]=digest.hexdigest()
    return {'row_counts':counts,'unresolved': missing,'sources':sources,
            'variants':variants, 'table_hashes':table_hashes}


def _execute_import(repo: pathlib.Path, project: pathlib.Path, source: pathlib.Path,
                    database: pathlib.Path, empty_assets: pathlib.Path, *, build: bool) -> dict:
    steps=[]
    env=external_process_env()
    if build:
        cmd=['dotnet','build',str(project),'-c','Release','-m:1']
        p=subprocess.run(cmd,cwd=repo,env=env,capture_output=True,text=True,timeout=1200)
        steps.append({'command':cmd,'exit_code':p.returncode,
                      'stdout_tail':p.stdout[-4000:],'stderr_tail':p.stderr[-4000:]})
        if p.returncode:
            return {'exit_code':p.returncode, 'steps':steps}
    cmd=['dotnet','run','--project',str(project),'-c','Release','--no-build','--',
         'import','--sqlite',str(database),'--source',str(source),'--assets',str(empty_assets)]
    p=subprocess.run(cmd,cwd=repo,env=env,capture_output=True,text=True,timeout=1800)
    steps.append({'command':cmd,'exit_code':p.returncode,
                  'stdout_tail':p.stdout[-18000:], 'stderr_tail':p.stderr[-9000:]})
    return {'exit_code':p.returncode,'steps':steps}


def verify_overlay(manifest_path: pathlib.Path, root: pathlib.Path, work_root: pathlib.Path,
                   *, execute: bool = False, build: bool = False) -> dict:
    if build and not execute:
        raise ValueError('NATIVE_BUILD_REQUIRES_EXECUTE')
    obj, manifest_path = _load_manifest(manifest_path, work_root)
    if str(root.resolve(strict=True)) != obj['game_root']:
        raise ValueError('NATIVE_MANIFEST_GAME_ROOT_CHANGED')
    source_root = root/'assets'/'GameServer'
    count, size, before = _scan(source_root)
    for f in obj['files']:
        rel = _path(f['template'])
        origin = _source(source_root, rel)
        if not origin.is_file() or bridge._hash_file(origin) != f['source_sha256']:
            raise ValueError(f'NATIVE_TEMPLATE_STALE:{f["template"]}')
    report={'format':'PT_ASSET_ETERVALE_NATIVE_IMPORT_GATE_V2','manifest':str(manifest_path),
            'source_files':count,'source_bytes':size,'status':'PLAN_ONLY',
            'proof_level':'NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE_NOT_GAME_RUNTIME',
            'game_assets_modified':False, 'no_reader_changes':True,
            'notes':['Native importer parses the entire GameServer source tree',
                     'Motion/texture proof not performed (isolated empty assets root)',
                     'New monster/NPC identities need review of embedded Identities JSON and a build']}
    if not execute:
        return report
    if not shutil.which('dotnet'):
        raise FileNotFoundError('DOTNET_REQUIRED_FOR_NATIVE_IMPORT_GATE')
    project = root/'tools'/'PristonTale.WorldImport'/'PristonTale.WorldImport.csproj'
    if not project.is_file():
        raise FileNotFoundError('WORLDIMPORT_PROJECT_NOT_FOUND')
    work_dir = work_root/'native_pipeline'/('verify_'+uuid.uuid4().hex)
    work_dir.mkdir(parents=True,exist_ok=False)
    source_a, source_b = work_dir/'baseline', work_dir/'candidate'
    for dest in (source_a,source_b):
        shutil.copytree(source_root,dest,symlinks=False)
    for f in obj['files']:
        rel = _path(f['path'])
        original = manifest_path.parent/'overlay'/pathlib.Path(*rel.parts)
        target = source_b.joinpath(*rel.parts)
        # Follow pre-existing same-case name, preserving actual case on disk.
        actual = _source(source_b, rel)
        if actual.is_file(): target=actual
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
    empty = work_dir/'no_game_assets'
    empty.mkdir()
    baseline_db = work_dir/'baseline.sqlite'
    candidate_db = work_dir/'candidate.sqlite'
    first = _execute_import(root,project,source_a,baseline_db,empty,build=build)
    second = _execute_import(root,project,source_b,candidate_db,empty,build=False) if first['exit_code']==0 else None
    report['steps']={'baseline':first,'candidate':second}
    if first['exit_code']==0 and second and second['exit_code']==0:
        a,b = _db_evidence(baseline_db),_db_evidence(candidate_db)
        added = b['unresolved']-a['unresolved']
        removed = a['unresolved']-b['unresolved']
        report['baseline_counts']=a['row_counts']
        report['candidate_counts']=b['row_counts']
        report['count_deltas']={key:b['row_counts'][key]-a['row_counts'][key] for key in a['row_counts']}
        report['new_unresolved']=[{'kind':k[0],'owner':k[1],'reference':k[2],'count':v} for k,v in added.items()]
        report['resolved_from_baseline']=[{'kind':k[0],'owner':k[1],'reference':k[2],'count':v} for k,v in removed.items()]
        report['changed_entities']=[]
        errors=[]
        domains = {
            'OpenItem': ('items','item_definitions','item_texts','item_spec_bonuses','item_spec_random_classes','item_sets'),
            'Monster': ('monsters','monster_texts','monster_drop_lines','monster_drop_line_items','monster_bonus_drops'),
            'NPC': ('npcs','npc_texts','npc_dialog_lines','npc_services','npc_shop_items'),
            'Field': ('fields','field_spawn_points','field_monster_spawns','field_bosses','field_boss_hours','field_npcs'),
        }
        for domain in sorted({f['path'].split('/')[0] for f in obj['files'] if f['new_sha256'] != f['source_sha256']}):
            consumed=[table for table in domains[domain]
                      if a['table_hashes'].get(table) != b['table_hashes'].get(table)]
            report.setdefault('semantic_catalog_changes',{})[domain]=consumed
            if not consumed:
                errors.append('NO_GAMEPLAY_CATALOG_CHANGE:'+domain)
        for f in obj['files']:
            rel=f['path']
            if b['sources'].get(rel.lower()) != f['new_sha256'] and b['sources'].get(rel) != f['new_sha256']:
                # Actual casing can differ from the user-supplied relative path.
                hits=[val for key,val in b['sources'].items() if key.casefold()==rel.casefold()]
                if hits != [f['new_sha256']]:
                    errors.append('IMPORTER_SOURCE_BYTES_NOT_RECORDED:'+rel)
            hits=[(key,val) for key,val in b['variants'].items() if key.casefold()==rel.casefold()]
            if f['path'].startswith(('OpenItem/','Monster/','NPC/')) and not hits:
                errors.append('IMPORTER_ENTITY_PARSER_SKIPPED:'+rel)
            if hits:
                report['changed_entities'].append({'path':rel,'kind':hits[0][1][0],
                                                   'selected_in_catalog':bool(hits[0][1][1])})
                if not hits[0][1][1]:
                    errors.append('ENTITY_NOT_SELECTED_IN_CATALOG:'+rel)
        report['semantic_errors']=errors
        report['status'] = ('FAILED_NATIVE_SEMANTICS' if added or errors else
                            'PASS_UNCHANGED_BASELINE_IMPORT' if all(f['new_sha256']==f['source_sha256'] for f in obj['files']) else
                            'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED')
    else:
        report['status']='FAILED_NATIVE_IMPORT'
    after_count, after_size, after = _scan(source_root)
    report['game_assets_modified'] = (before != after or count!=after_count or size!=after_size)
    if report['game_assets_modified']:
        report['status']='SOURCE_CHANGED_DURING_VERIFICATION'
    report_path=work_dir/'report.json'
    report['report_file']=str(report_path)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Show real semantic gate results in the pre-existing P0 content UI card,
    # but never pretend that historical Summit packs are runtime compatible.
    summary={'format':'PT_ASSET_ETERVALE_NATIVE_IMPORT_GATE_V2',
             'status':report['status'], 'proof_level':report['proof_level'],
             'scope':'GAME_SERVER_NATIVE_TEXT_ONLY_NOT_SUMMIT_PACKS',
             'full_report':str(report_path), 'new_unresolved_count':len(report.get('new_unresolved',[])),
             'game_assets_modified':report['game_assets_modified']}
    report['readiness_report_file']=bridge._write_report('content_compat',summary)
    return report


def snapshot(a: Any) -> int:
    root=bridge._game_root(a)
    source=root/'assets'/'GameServer'
    seen=set()
    files=[]
    for raw in a.asset:
        rel=_path(raw)
        p=_source(source,rel)
        if not p.is_file(): raise FileNotFoundError(f'NATIVE_SOURCE_NOT_FOUND:{rel}')
        real_rel=p.relative_to(source).as_posix()
        if real_rel.casefold() in seen: raise ValueError('DUPLICATE_NATIVE_SOURCE')
        seen.add(real_rel.casefold())
        files.append({'path':real_rel,'sha256':bridge._hash_file(p),'operations':[]})
    recipe={'format':FORMAT,'files':files}
    dest=bridge._private_output('native_pipeline/recipe_'+uuid.uuid4().hex+'.json',suffix='.json')
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(recipe,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    bridge._print({'format':'PT_ASSET_ETERVALE_NATIVE_SNAPSHOT_V2','status':'RECIPE_READY',
                   'recipe':str(dest),'files':files,'game_assets_modified':False})
    return 0


def build(a: Any) -> int:
    root=bridge._game_root(a)
    spec=json.loads(pathlib.Path(a.spec).expanduser().resolve(strict=True).read_text(encoding='utf-8'))
    result=build_overlay(spec,root,bridge._work_root())
    bridge._print(result)
    return 0


def verify(a: Any) -> int:
    root=bridge._game_root(a)
    result=verify_overlay(pathlib.Path(a.manifest),root,bridge._work_root(),
                          execute=a.execute,build=a.build)
    bridge._print(result)
    return 0 if result['status'] in ('PLAN_ONLY','PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED','PASS_UNCHANGED_BASELINE_IMPORT') else 3


def register(sp: Any) -> None:
    p=sp.add_parser('native-content-snapshot',help='capture SHA-bound GameServer native files as editable JSON recipe')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--asset',action='append',required=True,help='relative to assets/GameServer/; repeat')
    p.set_defaults(func=snapshot)
    p=sp.add_parser('native-content-build',help='JSON recipe -> native CP949 GameServer overlay in pt_build only')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--spec',required=True,type=pathlib.Path)
    p.set_defaults(func=build)
    p=sp.add_parser('native-content-verify',help='diff baseline/candidate via real WorldImport and disposable SQLite')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--manifest',required=True,type=pathlib.Path)
    p.add_argument('--execute',action='store_true',help='make isolated copies and run .NET WorldImport twice')
    p.add_argument('--build',action='store_true',help='build .NET WorldImport first; requires --execute')
    p.set_defaults(func=verify)
