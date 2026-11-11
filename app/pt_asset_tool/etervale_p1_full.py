"""P1 V4: native-corpus evidence suite, never a game-runtime certification.

No asset writes. A single command collects complete serialized material references,
reader evidence, field byte contracts and optional disposable SQLite import.
All output stays under pt_build/etervale. Missing assets are reported, not fabricated.
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import uuid
from typing import Any

from . import etervale_integration as bridge
from . import etervale_p0_binary as binary
from . import etervale_native_pipeline as native
from .etervale_field_contracts import inspect_bytes
from .material_group_compiler import inspect_material_group
from .stage072_corpus import parse_stage072
from .static_roundtrip import _parse as parse_model

FORMAT = 'PT_ASSET_ETERVALE_P1_FULL_AUDIT_V4'
IMG_SUFFIXES = {'.bmp', '.tga', '.dds', '.png', '.jpg', '.jpeg'}
RUNTIME_FALLBACK_EXTENSIONS = ('.bmp', '.tga', '.jpg', '.jpeg')
NATIVE_EXTS = {'.smd', '.smb', '.inx', '.tga', '.bmp'}
DEFAULT_MODELS = (
    'Field/Ricarten/village-2.smd',
    'char/monster/Acero/Acero.smd',
    'char/monster/Acero/Acero.smb',
    'char/monster/Acero/Acero.inx',
    'char/monster/Acero/Acero.tga',
    'char/monster/arcuda/arcuda.smd',
    'char/monster/arcuda/marcuda.smb',
    'char/monster/arcuda/arcuda.inx',
    'char/monster/arcuda/arcuda.tga',
)
DEFAULT_FIELDS = ('Field/Dcave.ase.spm', 'Field/Dcave.ase.spp', 'Field/Dcave.ase.spc')


def material_report(path: pathlib.Path) -> dict:
    """Use existing binary parsers rather than regex over filenames.

    Include *all* regular texture stages and animated stages, plus their alpha
    filename slots. Only materials actually assigned to faces count as used.
    """
    raw = path.read_bytes()
    group_start, offsets, kind = binary.material_offsets(raw)
    if kind == 'STAGE_072':
        start = int.from_bytes(raw[32:36], 'little')
        end = int.from_bytes(raw[36:40], 'little')
        group = raw[group_start:group_start + end - start]
        parsed = parse_stage072(path)
        if parsed.get('full_parse') != 'PASS':
            raise ValueError('STAGE_FULL_PARSE_NOT_PASS')
        uses = {int(i): int(n) for i, n in parsed['material_face_counts'].items()}
        geo = {'faces': sum(uses.values()), 'materials_used': len(uses),
               'max_uv_links': parsed.get('max_texlink_depth'),
               'multilayer_faces': parsed.get('multilayer_faces'),
               'collision_semantics': 'STRUCTURAL_ONLY_NOT_PHYSICS'}
    else:
        parsed = parse_model(raw)
        group = parsed['mat_region']
        uses = collections.Counter(int(f['material']) for obj in parsed['object_list'] for f in obj['faces'])
        geo = {'objects': len(parsed['object_list']),
               'vertices': sum(obj['nv'] for obj in parsed['object_list']),
               'faces': sum(uses.values()), 'materials_used': len(uses),
               'physique_vertices': sum(obj['nv'] for obj in parsed['object_list'] if obj['phys']),
               'max_uv_links': max((len(f['uv_layers']) for obj in parsed['object_list'] for f in obj['faces']), default=0)}
    inspected = inspect_material_group(group, expected_count=len(offsets))
    if not inspected.get('valid'):
        raise ValueError('MATERIAL_GROUP_INVALID:' + ','.join(inspected.get('errors', [])[:5]))
    refs=[]
    for material in inspected['materials']:
        mid = material['index']
        face_count = uses.get(mid, 0)
        if not face_count:
            continue
        for kind_name, records in (('REGULAR', material['textures']), ('ANIMATED', material['animated_textures'])):
            for slot, entry in enumerate(records):
                for role, key in (('COLOR', 'name'), ('OPACITY', 'alpha')):
                    name = entry.get(key, '')
                    if name:
                        refs.append({'material': mid, 'faces': face_count, 'kind': kind_name,
                                     'slot': slot, 'role': role, 'reference': name})
    if any(mid >= len(inspected['materials']) or mid < 0 for mid in uses):
        raise ValueError('MODEL_FACE_MATERIAL_OUT_OF_RANGE')
    return {'kind': kind, 'materials_declared': len(inspected['materials']),
            'geometry': geo, 'references': refs,
            'material_fields': 'LEGACY_MULTISTAGE_ALPHA_BLEND_NOT_PBR_TEXTURE_SLOTS'}


def _lookup_child(directory: pathlib.Path, name: str) -> tuple[pathlib.Path | None, str]:
    if not directory.is_dir():
        return None, 'NO_DIRECTORY'
    exact=directory/name
    if exact.exists() and not exact.is_symlink():
        return exact, 'EXACT'
    matches = [p for p in directory.iterdir() if p.name.casefold()==name.casefold() and p.exists() and not p.is_symlink()]
    if len(matches)==1:
        return matches[0], 'CASEFOLD_UNIQUE'
    return None, 'AMBIGUOUS' if matches else 'NOT_FOUND'


def resolve_texture(smd: pathlib.Path, token: str, assets: pathlib.Path, index: dict[str, list[str]]) -> dict:
    """Differentiate real local proof from unverified same-name elsewhere.

    A global same-basename hit is never automatically substituted for an absent
    texture. No path traversal, ambiguity, extension rewriting or symlink escape.
    """
    val = token.replace('\\', '/')
    rel = pathlib.PurePosixPath(val)
    if not val or val.startswith('/') or ':' in val or any(p in ('', '.', '..') for p in rel.parts):
        return {'state': 'UNSAFE_REFERENCE'}
    if rel.suffix.lower() not in IMG_SUFFIXES:
        return {'state': 'NON_IMAGE_REFERENCE'}
    # PristonSmdReader.ReadMaterial calls PristonBinaryUtil.BaseName() on the
    # serialized reference *before* calling PristonTextureLoader.ResolvePath().
    # Runtime looks up that basename in the SMD's own directory, then falls
    # back to BMP/TGA/JPG/JPEG there. Do not incorrectly join serialized dirs.
    filename=rel.name
    cur=smd.parent
    named, state=_lookup_child(cur,filename)
    if named is not None and named.is_file() and named.resolve().is_relative_to(assets.resolve()):
        return {'state':'PRESENT_ADJACENT', 'case':state,
                'resolution':'CSHARP_BASENAME', 'resolved':named.relative_to(assets).as_posix()}
    for extension in RUNTIME_FALLBACK_EXTENSIONS:
        candidate, fallback_state=_lookup_child(cur,rel.stem+extension)
        if candidate is not None and candidate.is_file() and candidate.resolve().is_relative_to(assets.resolve()):
            return {'state':'PRESENT_RUNTIME_EXTENSION_FALLBACK', 'case':fallback_state,
                    'resolution':'CSHARP_BASENAME',
                    'resolved':candidate.relative_to(assets).as_posix(),
                    'requested_extension':rel.suffix.lower(), 'resolved_extension':extension}
    candidates=index.get(rel.name.casefold(), [])
    return {'state': 'MISSING_ADJACENT', 'unverified_global_candidates': candidates[:12],
            'global_candidate_count': len(candidates), 'lookup_reason': state,
            'resolution': 'CSHARP_BASENAME'}


def build_index(assets: pathlib.Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = collections.defaultdict(list)
    for p in assets.rglob('*'):
        if p.is_symlink() or not p.is_file() or p.suffix.lower() not in IMG_SUFFIXES:
            continue
        index[p.name.casefold()].append(p.relative_to(assets).as_posix())
    return {k: sorted(v) for k, v in index.items()}


def field_report(path: pathlib.Path, assets_root: pathlib.Path) -> dict:
    game_server=assets_root/'GameServer'
    if not path.resolve().is_relative_to(game_server.resolve()):
        raise ValueError('P1_FIELD_OUTSIDE_GAMESERVER')
    detail=inspect_bytes(path.suffix.lower(), path.read_bytes())
    return {'path': path.relative_to(game_server).as_posix(), 'sha256':bridge._hash_file(path), **detail}


def _native_reader(root: pathlib.Path, path: pathlib.Path) -> dict:
    tool=bridge._csproj(root, 'inspect')
    proc=bridge._run_game_tool(root, tool, [str(path), '--full'], build=False)
    output='\n'.join(step.get('stdout_tail','') for step in proc['steps'])
    is_image=path.suffix.lower() in ('.bmp','.tga')
    decoded=bool(re.search(r'\bsize\s*:\s*\d+\s*x\s*\d+',output)) if is_image else None
    accepted=proc['exit_code']==0 and (decoded is True if is_image else True)
    return {'status':'READER_ACCEPTED' if accepted else 'READER_FAILED',
            'exit_code':proc['exit_code'], 'image_pixels_decoded':decoded,
            'material_aggregate_reported':'-- MATERIAL AGGREGATES --' in output,
            'output_tail':output[-2500:] if not accepted else output[-450:]}


def _build_project(root: pathlib.Path, project: pathlib.Path) -> dict:
    proc=subprocess.run(['dotnet','build',str(project),'-c','Release','-m:1'],cwd=root,
                        env=bridge.external_process_env(),capture_output=True,text=True,
                        timeout=900,check=False)
    return {'exit_code':proc.returncode,'stdout_tail':proc.stdout[-2000:],
            'stderr_tail':proc.stderr[-2000:]}


def _field_world_import(root: pathlib.Path, work: pathlib.Path, field_rows: list[dict], *, build: bool) -> dict:
    """Import original GameServer into an entirely private SQLite database.

    Reads live paths; never writes to GameServer nor production persistence. The
    content hashes before and after must match for accepted evidence.
    """
    source=root/'assets'/'GameServer'
    assets=root/'assets'
    project=root/'tools'/'PristonTale.WorldImport'/'PristonTale.WorldImport.csproj'
    if not project.is_file():raise FileNotFoundError('WORLDIMPORT_PROJECT_NOT_FOUND')
    folder=work/'p1_world_import'/uuid.uuid4().hex
    folder.mkdir(parents=True,exist_ok=False)
    expected={r['path']:r['sha256'] for r in field_rows}
    before_count,before_bytes,before_hashes=native._scan(source)
    db=folder/'isolated.sqlite'
    result=native._execute_import(root,project,source,db,assets,build=build)
    after_count,after_bytes,after_hashes=native._scan(source)
    changed={p for p,h in expected.items() if bridge._hash_file(source/p)!=h}
    if (before_count,before_bytes,before_hashes)!=(after_count,after_bytes,after_hashes):
        changed.add('GAMESERVER_TREE_CHANGED')
    status='SOURCE_CHANGED' if changed else 'FAILED_NATIVE_IMPORT' if result['exit_code'] else 'NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE'
    record={'status':status,'steps':result,'sqlite':str(db),
            'source_changed':sorted(changed),'source_kind':'REAL_ASSETS_ROOT_READ_ONLY',
            'game_assets_modified':bool(changed),'runtime_status':'NOT_CERTIFIED'}
    if result['exit_code']==0:
        evidence=native._db_evidence(db)
        record['table_counts']=evidence['row_counts']
        record['unresolved_ref_count']=sum(evidence['unresolved'].values())
        record['fields_hash']=evidence['table_hashes'].get('fields')
        record['field_rows_in_catalog']=evidence['row_counts'].get('fields',0)
        if not evidence['row_counts'].get('fields',0):record['status']='NO_FIELDS_IMPORTED'
    return record


def audit(root: pathlib.Path, work: pathlib.Path, assets_list: list[str], fields: list[str],
          known_missing: list[str], *, execute: bool, build: bool, world_import: bool, effects: list[str] | None = None) -> dict:
    if build and not execute:raise ValueError('BUILD_REQUIRES_EXECUTE')
    if world_import and not execute:raise ValueError('WORLD_IMPORT_REQUIRES_EXECUTE')
    if not 1<=len(assets_list)<=50 or len(set(assets_list))!=len(assets_list):
        raise ValueError('P1_REQUIRE_1_TO_50_UNIQUE_ASSETS')
    if not 1<=len(fields)<=150 or len(set(fields))!=len(fields):
        raise ValueError('P1_REQUIRE_1_TO_150_UNIQUE_FIELDS')
    asset_root=(root/'assets').resolve(strict=True)
    source=[]
    field_files=[]
    for rel in assets_list:
        path=bridge._input_path(root,rel,None,NATIVE_EXTS)
        source.append((rel,path))
    for name in fields:
        norm=pathlib.PurePosixPath(name.replace('\\','/'))
        if norm.is_absolute() or '..' in norm.parts or norm.suffix.lower() not in {'.spm','.spp','.spc'}:
            raise ValueError('P1_INVALID_FIELD_PATH')
        path=bridge._input_path(root,'GameServer/'+norm.as_posix(),None,{'.spm','.spp','.spc'})
        field_files.append(path)
    effect_files=[]
    if effects is None:
        # One deterministic read-only .part sample for baseline VFX coverage.
        candidate=next((p for p in sorted(asset_root.rglob('*'))
                        if p.is_file() and not p.is_symlink() and p.suffix.lower()=='.part'),None)
        effects=[candidate.relative_to(asset_root).as_posix()] if candidate else []
    if len(effects)>10 or len(set(effects))!=len(effects):
        raise ValueError('P1_EFFECT_LIMIT_OR_DUPLICATE')
    for name in effects:
        effect_files.append(bridge._input_path(root,name,None,{'.part'}))
    tracked={path:bridge._hash_file(path) for _,path in source}
    tracked.update((path,bridge._hash_file(path)) for path in field_files)
    tracked.update((path,bridge._hash_file(path)) for path in effect_files)
    report={'format':FORMAT,'game_root':str(root),'status':'PLANNED',
            'proof_level':'LEGACY_BINARY_PARSE_AND_OPTIONAL_NATIVE_READERS_DISPOSABLE_WORLDIMPORT',
            'game_assets_modified':False,'runtime_visual':'NOT_CERTIFIED',
            'sample_scope':'EXPLICIT_ASSETS_ONLY_NOT_ENTIRE_GAME',
            'material_reference_scope':'ALL_REGULAR_ANIMATED_AND_OPACITY_SLOTS_IN_FACE_USED_MATERIALS',
            'assets':[],'fields':[],'effects':[],'texture_references':[], 'known_missing':sorted(set(known_missing))}
    idx=build_index(asset_root)
    for rel,path in source:
        item={'path':rel,'sha256':tracked[path], 'size':path.stat().st_size}
        if path.suffix.lower()=='.smd':
            material=material_report(path)
            item.update({k:v for k,v in material.items() if k!='references'})
            for ref in material['references']:
                verdict=resolve_texture(path,ref['reference'],asset_root,idx)
                row={'asset':rel,**ref,**verdict}
                row['acknowledged_known_missing']=(row['state']=='MISSING_ADJACENT' and
                    pathlib.PurePosixPath(ref['reference'].replace('\\','/')).name.casefold()
                    in {pathlib.PurePosixPath(n.replace('\\','/')).name.casefold() for n in known_missing})
                report['texture_references'].append(row)
        report['assets'].append(item)
    report['fields']=[field_report(p,asset_root) for p in field_files]
    for effect in effect_files:
        size=effect.stat().st_size
        if size>64*1024*1024:raise ValueError('P1_EFFECT_TOO_LARGE_FOR_STATIC_READ')
        raw=effect.read_bytes()
        report['effects'].append({'path':effect.relative_to(asset_root).as_posix(),
                                  'sha256':tracked[effect],'bytes':size,
                                  'zero_bytes':raw.count(b'\0'),
                                  'status':'STATIC_PART_NONEMPTY_NOT_RENDER_CERTIFIED' if size else 'EMPTY_PART'})
    report['field_structural_failures']=[r['path'] for r in report['fields'] if r['status']!='PASS']
    report['dependency_counts']=dict(collections.Counter(r['state'] for r in report['texture_references']))
    report['missing_unacknowledged']=[r for r in report['texture_references'] if r['state'] not in ('PRESENT_ADJACENT','PRESENT_RUNTIME_EXTENSION_FALLBACK') and not r['acknowledged_known_missing']]
    report['acknowledged_unresolved']=[r for r in report['texture_references'] if r['acknowledged_known_missing']]
    if execute:
        if build:
            b=_build_project(root,bridge._csproj(root,'inspect'))
            report['assetdump_build']=b
            if b['exit_code']:
                report['status']='NATIVE_BUILD_FAILED'
        if report['status']!='NATIVE_BUILD_FAILED':
            for (rel,path),item in zip(source,report['assets']):
                item['native_reader']=_native_reader(root,path)
    if world_import and report['status']!='NATIVE_BUILD_FAILED':
        report['field_native_import']=_field_world_import(root,work,report['fields'],build=build)
    failures=[r['path'] for r in report['assets'] if execute and r.get('native_reader',{}).get('status')!='READER_ACCEPTED']
    report['reader_failures']=failures
    report['game_assets_modified']=any(bridge._hash_file(p)!=h for p,h in tracked.items()) or bool(
        report.get('field_native_import',{}).get('game_assets_modified'))
    if report['game_assets_modified']:
        report['status']='SOURCE_CHANGED'
    elif report['status']=='NATIVE_BUILD_FAILED':
        pass
    elif report['field_structural_failures'] or failures or any(e['status']=='EMPTY_PART' for e in report['effects']) or (world_import and report['field_native_import']['status']!='NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE'):
        report['status']='P1_TECHNICAL_FAILURE'
    elif not execute:
        report['status']='P1_OFFLINE_PARSED_NATIVE_PENDING'
    elif not report['effects']:
        report['status']='P1_EFFECT_SAMPLE_PENDING'
    elif report['missing_unacknowledged']:
        report['status']='P1_REVIEW_DEPENDENCIES'
    elif report['acknowledged_unresolved']:
        report['status']='P1_AUTOMATED_GATES_PASSED_WITH_ACKNOWLEDGED_GAPS_RUNTIME_PENDING'
    elif not world_import:
        report['status']='P1_READERS_PASSED_WORLDIMPORT_PENDING_RUNTIME_PENDING'
    else:
        report['status']='P1_AUTOMATED_GATES_PASSED_RUNTIME_PENDING'
    report['next_steps']=['Do not infer real-time gameplay, particle playback, collision physics or visual fidelity from readers',
                          'Inspect unresolved/ambiguous material references before visual signoff',
                          'Run P1 visual checklist with gameplay screenshots for manual review']
    # P1/06: publish narrow, explicit evidence summaries to the *existing*
    # read-only UI folders as well as the consolidated P1 folder. This prevents
    # stale old P1/03-05 cards after a new V4 run.
    deps_clear=bool(report['texture_references']) and not report['missing_unacknowledged'] and not report['acknowledged_unresolved']
    all_readers=bool(report['assets']) and all(row.get('native_reader',{}).get('status')=='READER_ACCEPTED'
                                               for row in report['assets'])
    effect_static_ok=bool(report['effects']) and all(r['status']=='STATIC_PART_NONEMPTY_NOT_RENDER_CERTIFIED' for r in report['effects'])
    field_clean=bool(report['fields']) and not report['field_structural_failures']
    field_import=report.get('field_native_import',{}).get('status')=='NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE'
    shared={'game_assets_modified':report['game_assets_modified'],
            'runtime_certification':'NOT_CERTIFIED',
            'scope':'EXPLICIT_SAMPLE_NOT_ENTIRE_ASSET_LIBRARY',
            'origin_format':FORMAT}
    summaries={
        'asset_gaps':{'format':'PT_ASSET_ETERVALE_P1_TEXTURE_GAPS_V4',
                      'status':'PASS_SAMPLED_TEXTURE_REFERENCES' if deps_clear else 'REVIEW_MISSING_OR_UNVERIFIED_REFERENCES',
                      'counts':report['dependency_counts'],
                      'missing_unacknowledged':len(report['missing_unacknowledged']),
                      'missing_acknowledged':len(report['acknowledged_unresolved'])},
        'quality':{'format':'PT_ASSET_ETERVALE_P1_QUALITY_SAMPLE_V4',
                   'status':'PASS_NATIVE_READERS_PART_STATIC_NOT_RUNTIME_CERTIFIED' if all_readers and effect_static_ok else
                            'PENDING_EFFECT_SAMPLE_OR_NATIVE_READERS',
                   'models_checked':len(report['assets']),
                   'parts_sampled':len(report['effects']),
                   'reader_failures':report['reader_failures']},
        'fields':{'format':'PT_ASSET_ETERVALE_P1_FIELDS_V4',
                  'status':'PASS_STRUCTURAL_AND_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED' if field_clean and field_import else
                           'PASS_STRUCTURAL_ONLY' if field_clean else 'FIELD_CONTRACT_FAILURE',
                  'files_checked':len(report['fields']),
                  'world_import':'PASS' if field_import else 'NOT_CERTIFIED'},
    }
    report['component_report_files']={}
    for folder,summary in summaries.items():
        report['component_report_files'][folder]=bridge._write_report(folder,{**shared,**summary})
    report['report_file']=bridge._write_report('p1_full',report)
    return report


def run(a: Any) -> int:
    root=bridge._game_root(a)
    report=audit(root,bridge._work_root(),list(a.asset or DEFAULT_MODELS),
                 list(a.field or DEFAULT_FIELDS),list(a.known_missing or []),
                 execute=a.execute,build=a.build,world_import=a.world_import,effects=a.effect)
    bridge._print({'format':FORMAT,'status':report['status'],
                   'report_file':report['report_file'],
                   'assets_checked':len(report['assets']),
                   'fields_checked':len(report['fields']),
                   'effects_sampled':len(report['effects']),
                   'dependency_counts':report['dependency_counts'],
                   'unacknowledged_count':len(report['missing_unacknowledged']),
                   'acknowledged_unresolved_count':len(report['acknowledged_unresolved']),
                   'first_unresolved':report['missing_unacknowledged'][:5],
                   'reader_failures':report['reader_failures'],
                   'field_native_import_status':report.get('field_native_import',{}).get('status','NOT_RUN'),
                   'game_assets_modified':report['game_assets_modified'],
                   'runtime_visual':report['runtime_visual']})
    return 3 if report['status'] in ('NATIVE_BUILD_FAILED','P1_TECHNICAL_FAILURE','SOURCE_CHANGED') or (
        a.strict and report['status'] != 'P1_AUTOMATED_GATES_PASSED_RUNTIME_PENDING') else 0


def register(sp: Any) -> None:
    p=sp.add_parser('p1-full-audit',help='read all legacy material texture slots, native models and fields; optional disposable WorldImport')
    p.add_argument('--repo-root',type=pathlib.Path)
    p.add_argument('--asset',action='append',help='relative to Etervale/assets; repeat (default Ricarten, Acero, Arcuda)')
    p.add_argument('--field',action='append',help='relative to Etervale/assets/GameServer; repeat')
    p.add_argument('--effect',action='append',help='relative .part; repeat; default first found automatically')
    p.add_argument('--known-missing',action='append',help='acknowledge unresolved name; NOT a fix or substitute')
    p.add_argument('--execute',action='store_true',help='run native C# reader for each asset')
    p.add_argument('--build',action='store_true',help='build C# projects once')
    p.add_argument('--world-import',action='store_true',help='import original data to isolated SQLite, reading real assets')
    p.add_argument('--strict',action='store_true',help='nonzero exit for unacknowledged gaps or absent native proofs')
    p.set_defaults(func=run)
