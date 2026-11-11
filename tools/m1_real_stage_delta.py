#!/usr/bin/env python3
"""Etervale M1.1: Stage0.72 visual-mask build and existing transactional deploy.

No game writes unless --publish-game is given with an exact confirmation string.
The published Stage changes only 16-bit material indices on selected SAFE faces;
all geometry, UV values, area index and collision classification remain intact.
Hidden faces lose their texlink reference; the original texlink table bytes are untouched.
Models are NOT rendered by this stage-only milestone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import struct
import sys
import time
import uuid
from typing import Any

ORIGINAL_SHA = 'df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'
MAP = pathlib.PurePosixPath('Field/forest/fore-1.smd')
SOURCE_FACES = 35519
APPLY_GAME_CONFIRM = 'PUBLICAR_STAGE_EXPERIMENTAL'
RESTORE_GAME_CONFIRM = 'RESTAURAR_STAGE_ORIGINAL'
FORMAT = 'ETERVALE_M1_REAL_STAGE_DELTA_V1'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'EXPECTED_JSON_OBJECT:{path}')
    return value


def write_json_atomic(path: pathlib.Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def locate(map_dir: pathlib.Path, suffix: str) -> pathlib.Path:
    matches = list(map_dir.glob('*' + suffix))
    if len(matches) != 1:
        raise ValueError(f'EXPECTED_ONE_METADATA_FILE:{suffix}:{len(matches)}')
    return matches[0]


def _source_match(doc: dict, stage_sha: str, face_count: int, label: str):
    if doc.get('asset') != MAP.as_posix() or doc.get('source_sha256') != stage_sha:
        raise ValueError(f'METADATA_SOURCE_DRIFT:{label}')
    if int(doc.get('source_face_count', face_count)) != face_count:
        raise ValueError(f'METADATA_FACE_COUNT_DRIFT:{label}')


def collect_selections(v24: dict, v30: dict, v31: dict, *, stage_sha: str, face_count: int) -> tuple[set[int], dict]:
    for label, doc in (('v24', v24), ('v30', v30), ('v31', v31)):
        _source_match(doc, stage_sha, face_count, label)
    if v30.get('format') != 'PT_ETERVALE_ENVIRONMENT_BATCH_V30' or v30.get('lod') != 'LOD0':
        raise ValueError('V30_PREVIEW_FORMAT_INVALID')
    if v24.get('format') != 'PT_ETERVALE_STAGE072_TREE_GROUPS_V24':
        raise ValueError('V24_GROUPS_FORMAT_INVALID')
    if v31.get('format') != 'PT_ETERVALE_ENVIRONMENT_RESIDUAL_V31':
        raise ValueError('V31_RESIDUAL_FORMAT_INVALID')
    groups: dict[str, dict] = {}
    for group in v24.get('groups') or []:
        gid = group.get('id')
        if not isinstance(gid, str) or gid in groups:
            raise ValueError('V24_DUPLICATE_OR_INVALID_GROUP_ID')
        groups[gid] = group
    ids = v30.get('instance_group_ids') or []
    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
        raise ValueError('V30_INVALID_INSTANCE_IDS')
    base: set[int] = set()
    placements: list[dict] = []
    for gid in ids:
        if gid not in groups:
            raise ValueError('V30_GROUP_UNKNOWN:' + str(gid))
        row = groups[gid]
        for fi in row.get('faces') or []:
            if type(fi) is not int or fi < 0 or fi >= face_count:
                raise ValueError(f'V24_FACE_OUT_OF_RANGE:{gid}:{fi}')
            if fi in base:
                raise ValueError(f'V30_DUPLICATED_GROUP_FACE:{gid}:{fi}')
            base.add(fi)
        placements.append({
            'group_id': gid, 'anchor_game': row.get('anchor_game'),
            'model': v30.get('model_name'), 'model_sha256': v30.get('model_sha256'),
            'lod': 'LOD0', 'runtime_rendered': False, 'ground_certified': False,
        })
    if len(base) != v30.get('masked_face_count') or len(placements) != v30.get('instance_count'):
        raise ValueError('V30_FACE_OR_INSTANCE_COUNT_DRIFT')
    extra = v31.get('extra_faces', [])
    if not isinstance(extra, list) or len(set(extra)) != len(extra) or any(type(i) is not int or i < 0 or i >= face_count for i in extra):
        raise ValueError('V31_EXTRA_FACES_INVALID')
    for row in v31.get('v32_replacements', []):
        if not isinstance(row, dict) or row.get('review_only') is not True or row.get('ground_certified') is not False:
            raise ValueError('V32_UNVERIFIED_PLACEMENT')
        if row.get('seed') not in extra:
            raise ValueError('V32_SEED_NOT_IN_MASK')
        placements.append({
            'group_id': None, 'seed': row['seed'], 'anchor_view': row.get('anchor_view'),
            'model': row.get('model'), 'model_sha256': row.get('model_sha256'),
            'lod': row.get('lod', 'LOD0'), 'runtime_rendered': False,
            'ground_certified': False,
        })
    masks = base.union(extra)
    if not masks:
        raise ValueError('NO_FACES_SELECTED')
    return masks, {
        'base_faces': len(base), 'extra_faces': len(extra), 'unique_faces': len(masks),
        'overlap': len(base.intersection(extra)), 'planned_model_instances': len(placements),
        'model_preview_only': True, 'placements': placements,
    }


def _physics(mat: dict) -> tuple:
    # PristonCollisionWorld: material.MeshState & StageCollisionReader.CheckFace (0x1)
    # If no collision: IsWater || Transparency > 0.1; if solid: Ice flag.
    solid = bool(int(mat['MeshState']) & 0x1)
    state = int(mat['UseState'])
    if solid:
        return 'SOLID', bool(state & 0x8000)
    return 'NO_COLLISION', bool(state & 0x0200 or float(mat['Transparency']) > .1)


def _materials(raw: bytes, parsed: dict) -> list[dict]:
    from pt_asset_tool.stage072_corpus import DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, MAT_GROUP_SIZE, MATERIAL_SIZE
    materials = [dict(row) for row in parsed['materials']]
    offset = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE + MAT_GROUP_SIZE
    for material in materials:
        material['MeshState'] = struct.unpack_from('<I', raw, offset + 168)[0]
        if material['InUse']:
            length = struct.unpack_from('<i', raw, offset + MATERIAL_SIZE)[0]
            if length < 0:
                raise ValueError('NEGATIVE_MATERIAL_STRING_LENGTH')
            offset += MATERIAL_SIZE + 4 + length
        else:
            offset += MATERIAL_SIZE
    return materials


def patch_stage(source: pathlib.Path, selections: set[int], dest: pathlib.Path, *, expected_sha: str,
                expected_faces: int = SOURCE_FACES) -> dict:
    from pt_asset_tool.stage072_corpus import parse_stage072, STAGE_FACE_SIZE, STAGE_VERTEX_SIZE, DFILE_HEADER_SIZE, STAGE_HEADER_SIZE
    raw = source.read_bytes()
    if sha256(raw) != expected_sha:
        raise ValueError('STAGE_ORIGINAL_SHA256_MISMATCH')
    original = parse_stage072(source, include_payload=True)
    if original.get('full_parse') != 'PASS' or original.get('counts', {}).get('faces') != expected_faces:
        raise ValueError('STAGE072_SOURCE_PARSE_OR_FACE_COUNT_FAILED')
    nface = original['counts']['faces']
    if any(type(fi) is not int or not 0 <= fi < nface for fi in selections):
        raise ValueError('FACE_INDEX_OUT_OF_RANGE')
    mats = _materials(raw, original)
    invisible = [row for row in mats if int(row['UseState']) & 0x400 or
                 (int(row['TextureCounter']) == 0 and int(row['AnimTexCounter']) == 0)]
    if not invisible:
        raise ValueError('NO_EXISTING_INVISIBLE_MATERIAL_NO_SOURCE_WRITE')
    vertex_base = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE + (int(original['file_header']['First_ObjInfoPoint']) - int(original['file_header']['MatFilePoint']))
    face_base = vertex_base + original['counts']['vertices'] * STAGE_VERTEX_SIZE
    out = bytearray(raw)
    changed: list[int] = []
    skipped: list[dict] = []
    initial_ids = {}
    final_ids = {}
    for fi in sorted(selections):
        byte_offset = face_base + fi*STAGE_FACE_SIZE + 14
        mid = struct.unpack_from('<H', raw, byte_offset)[0]
        origin = mats[mid]
        matching = [m for m in invisible if _physics(m) == _physics(origin)]
        if not matching:
            skipped.append({'face_index': fi, 'material': mid, 'reason': 'PHYSICS_SIGNATURE_UNMATCHED', 'physics': _physics(origin)})
            continue
        new_id = int(next((m['id'] for m in matching if int(m['id']) == mid), matching[0]['id']))
        if mid == new_id:
            continue
        struct.pack_into('<H', out, byte_offset, new_id)
        # A TexLink points at the *old* material handle. Remove the face's
        # reference to it; do not rewrite any shared UV/texlink table entry.
        # The invisible material is skipped by the client renderer.
        struct.pack_into('<I', out, byte_offset + 2, 0)
        changed.append(fi)
        initial_ids[fi] = mid
        final_ids[fi] = new_id
    if not changed:
        raise ValueError(f'NO_SAFE_VISIBLE_FACE_CHANGES:requested={len(selections)}:skipped={len(skipped)}')
    data = bytes(out)
    if sha256(data) == expected_sha:
        raise AssertionError('STAGE_DELTA_SAME_SHA')
    dest.parent.mkdir(parents=True, exist_ok=True)
    # parse output from staging; do not leave an invalid final file
    tmp = dest.with_name(dest.name + '.tmp')
    try:
        tmp.write_bytes(data)
        modified = parse_stage072(tmp, include_payload=True)
        if modified.get('full_parse') != 'PASS':
            raise RuntimeError(f'PATCHED_STAGE_PARSER_FAIL:{modified.get("errors")}:{modified.get("flags")}')
        if len(raw) != len(data):
            raise AssertionError('STAGE_SIZE_DRIFT')
        if original['counts'] != modified['counts']:
            raise AssertionError('STAGE_COUNTS_DRIFT')
        if original['payload']['vertices'] != modified['payload']['vertices']:
            raise AssertionError('STAGE_VERTICES_DRIFT')
        if original['payload']['texlinks'] != modified['payload']['texlinks']:
            raise AssertionError('STAGE_TEXLINKS_DRIFT')
        if original['payload']['lights'] != modified['payload']['lights']:
            raise AssertionError('STAGE_LIGHTS_DRIFT')
        if original['area'] != modified['area']:
            raise AssertionError('STAGE_AREA_DRIFT')
        if any(_physics(mats[row['material']]) != _physics(mats[modified['payload']['faces'][i]['material']])
               for i, row in enumerate(original['payload']['faces'])):
            raise AssertionError('STAGE_COLLISION_CLASSIFICATION_DRIFT')
        changed_offsets = {face_base + fi*STAGE_FACE_SIZE + 14 + j for fi in changed for j in range(6)}
        if any(i not in changed_offsets for i, (x,y) in enumerate(zip(raw,data)) if x != y):
            raise AssertionError('STAGE_UNAUTHORIZED_BYTE_DIFF')
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {'format': FORMAT, 'source_sha256': expected_sha, 'output_sha256': sha256(data),
            'source_bytes': len(raw), 'output_bytes': len(data), 'requested_mask_faces': len(selections),
            'remapped_faces': len(changed), 'already_invisible_faces': len(selections)-len(changed)-len(skipped),
            'skipped_unsafe_count': len(skipped), 'skipped_unsafe': skipped[:200],
            'changed_material_ids': sorted({int(v) for v in final_ids.values()}),
            'full_parse': 'PASS', 'vertex_uv_area_and_lights_unchanged': True,
            'face_material_and_texlink_pointer_delta_only': True, 'collision_classification_unchanged': True,
            'rendered_models_in_game': 0, 'runtime_visual_stage_change': 'MATERIAL_REMAP_TO_INVISIBLE_AND_CLEAR_FACE_TEXLINK'}


def inputs(tool_root: pathlib.Path, game_root: pathlib.Path, map_dir: pathlib.Path | None):
    assets = game_root / 'assets'
    stage = assets / MAP
    if not assets.is_dir() or not stage.is_file() or stage.is_symlink():
        raise ValueError('CLIENT_STAGE_NOT_FOUND_OR_UNSAFE')
    if map_dir is None:
        map_dir = tool_root/'app/pt_build/etervale/stage072_semantic_v21/maps'
    if not map_dir.is_dir():
        raise ValueError('BLENDER_MAP_METADATA_DIRECTORY_NOT_FOUND')
    return assets, stage, [locate(map_dir, suffix) for suffix in (
        '.v24_groups.json', '.v24_groups.v26_environment.v30_full_preview.json', '.v24_groups.v31_residuais.json')]


def prepare(tool_root: pathlib.Path, game_root: pathlib.Path, map_dir: pathlib.Path | None,
            *, expected_sha: str = ORIGINAL_SHA, expected_faces: int = SOURCE_FACES,
            output: pathlib.Path | None = None, write: bool = False) -> dict:
    sys.path.insert(0, str(tool_root/'app'))
    assets, stage, paths = inputs(tool_root,game_root,map_dir)
    real_sha = file_sha(stage)
    if real_sha != expected_sha:
        raise ValueError(f'STAGE_SHA_DRIFT:{real_sha}')
    v24,v30,v31 = map(read_json,paths)
    masks, model_plan = collect_selections(v24,v30,v31,stage_sha=real_sha,face_count=expected_faces)
    res = {'format':FORMAT, 'status':'READY_FOR_STAGE_BUILD' if not write else 'STAGE_BUILT',
           'source':str(stage), 'source_sha256':real_sha, 'game_assets_written':False,
           'selection':{k:v for k,v in model_plan.items() if k!='placements'},
           'models_runtime_loaded':False}
    if write:
        if output is None: raise ValueError('OUTPUT_REQUIRED')
        detail = patch_stage(stage,masks,output,expected_sha=real_sha,expected_faces=expected_faces)
        res['stage_delta'] = detail
        res['output'] = str(output)
        res['output_sha256'] = detail['output_sha256']
        positions = output.parent/'planned_models_not_yet_in_game.json'
        write_json_atomic(positions, {'format':'ETERVALE_M1_PLANNED_MODEL_INSTANCES_V1',
                                      'source_sha256':real_sha,'rendered_in_game':False, **model_plan})
        res['planned_models_manifest'] = str(positions)
    return res


def _make_recipe(stage_file: pathlib.Path, delta_sha: str) -> dict:
    from pt_asset_tool.asset_compiler import BUNDLE_RECIPE_FORMAT
    return {'format':BUNDLE_RECIPE_FORMAT,'id':'etervale_m1_real_stage_mask',
            'bundle_type':'FIELD','payload':{'stage_asset':{
            'output': MAP.as_posix(), 'source_path':str(stage_file),
            'expected_sha256':delta_sha,'target_policy':'REPLACE_EXISTING'}}}


def clone_rehearsal(tool_root: pathlib.Path, game_root: pathlib.Path, *, map_dir: pathlib.Path | None = None,
                   expected_sha: str = ORIGINAL_SHA, expected_faces: int = SOURCE_FACES) -> dict:
    sys.path.insert(0, str(tool_root/'app'))
    from pt_asset_tool.asset_compiler import plan_asset_bundle, compile_asset_bundle
    from pt_asset_tool.asset_bundle_deploy import APPLY_CONFIRM, RESTORE_CONFIRM, publish_asset_bundle, restore_asset_bundle
    assets, source, _ = inputs(tool_root,game_root,map_dir)
    run_dir = tool_root/'app/pt_build/etervale/m1_real_stage_delta'/('run_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True,exist_ok=False)
    output = run_dir/'modified_stage'/MAP
    result = prepare(tool_root,game_root,map_dir,expected_sha=expected_sha,expected_faces=expected_faces,output=output,write=True)
    if result['stage_delta']['skipped_unsafe_count']:
        result['status']='BLOCKED_UNSAFE_FACES'
        result['run_dir']=str(run_dir)
        write_json_atomic(run_dir/'audit.json',result)
        return result
    recipe = _make_recipe(output,result['output_sha256'])
    plan = plan_asset_bundle(recipe,client_root=assets,server_root=None)
    result['bundle_plan_status']=plan.get('status')
    result['bundle_plan_errors']=plan.get('errors',[])
    if plan.get('status') != 'READY':
        result['status']='BLOCKED_BUNDLE_PLAN'
        result['run_dir']=str(run_dir)
        write_json_atomic(run_dir/'audit.json',result)
        return result
    clone = run_dir/'client_clone'
    target = clone/MAP
    target.parent.mkdir(parents=True)
    shutil.copy2(source,target)
    build = compile_asset_bundle(run_dir,recipe,client_root=assets,server_root=None)
    manifest = pathlib.Path(build['manifest'])
    if file_sha(target)!=expected_sha or file_sha(source)!=expected_sha:
        raise RuntimeError('ORIGINAL_DRIFT_BEFORE_CLONE_PUBLISH')
    published = publish_asset_bundle(run_dir,clone,None,manifest,confirm=APPLY_CONFIRM)
    result['clone_publish_state']=published.get('state')
    result['clone_published_sha256']=file_sha(target)
    if published.get('state')!='APPLIED_VERIFIED' or file_sha(target)!=result['output_sha256']:
        raise RuntimeError('CLONE_PUBLISH_HASH_MISMATCH')
    restored = restore_asset_bundle(run_dir,clone,None,manifest,confirm=RESTORE_CONFIRM)
    result['clone_restore_state']=restored.get('state')
    if restored.get('state')!='RESTORED_VERIFIED' or file_sha(target)!=expected_sha or file_sha(source)!=expected_sha:
        raise RuntimeError('CLONE_RESTORE_HASH_MISMATCH')
    result['status']='CLONE_MODIFIED_STAGE_COMMIT_ROLLBACK_PASS'
    result['run_dir']=str(run_dir)
    result['build_manifest']=str(manifest)
    write_json_atomic(run_dir/'audit.json',result)
    write_json_atomic(run_dir.parent/'latest_clone_pass.json',{
        'run_dir':str(run_dir), 'build_manifest':str(manifest),'expected_source_sha256':expected_sha,
        'modified_stage_sha256':result['output_sha256'],'status':result['status']})
    return result


def real_publish(tool_root: pathlib.Path, game_root: pathlib.Path, *, restore=False, confirmation: str) -> dict:
    sys.path.insert(0, str(tool_root/'app'))
    from pt_asset_tool.asset_bundle_deploy import APPLY_CONFIRM, RESTORE_CONFIRM, publish_asset_bundle, restore_asset_bundle
    base = tool_root/'app/pt_build/etervale/m1_real_stage_delta'
    if restore:
        if confirmation!=RESTORE_GAME_CONFIRM: raise ValueError('EXPLICIT_RESTORE_CONFIRMATION_REQUIRED')
        state=read_json(base/'game_publish.json')
        if state.get('status')!='GAME_PUBLISHED_VERIFIED':
            raise ValueError('NO_ACTIVE_GAME_PUBLICATION')
    else:
        if confirmation!=APPLY_GAME_CONFIRM: raise ValueError('EXPLICIT_PUBLISH_CONFIRMATION_REQUIRED')
        state=read_json(base/'latest_clone_pass.json')
        if state.get('status')!='CLONE_MODIFIED_STAGE_COMMIT_ROLLBACK_PASS':
            raise ValueError('CLONE_TEST_NOT_PASSED')
        if (base/'game_publish.json').exists() and read_json(base/'game_publish.json').get('status')=='GAME_PUBLISHED_VERIFIED':
            raise ValueError('GAME_PUBLICATION_ALREADY_ACTIVE')
    run_dir = pathlib.Path(state['run_dir']).resolve(strict=True)
    if not run_dir.is_relative_to(base.resolve()): raise ValueError('RUN_ESCAPES_PROJECT')
    manifest = pathlib.Path(state['build_manifest']).resolve(strict=True)
    if not manifest.is_relative_to(run_dir): raise ValueError('MANIFEST_ESCAPES_RUN')
    assets = game_root/'assets'
    target=assets/MAP
    if target.is_symlink() or not target.is_file(): raise ValueError('GAME_TARGET_UNSAFE')
    expected_source=state['expected_source_sha256']
    expected_mod=state['modified_stage_sha256']
    current=file_sha(target)
    if not restore and current!=expected_source:
        raise ValueError('GAME_SOURCE_CHANGED_BEFORE_PUBLISH')
    if restore and current!=expected_mod:
        raise ValueError('GAME_STAGE_CHANGED_AFTER_PUBLICATION')
    if restore:
        tx=restore_asset_bundle(run_dir,assets,None,manifest,confirm=RESTORE_CONFIRM)
        status='GAME_RESTORED_VERIFIED'
        wanted=expected_source
        previous=state
    else:
        tx=publish_asset_bundle(run_dir,assets,None,manifest,confirm=APPLY_CONFIRM)
        status='GAME_PUBLISHED_VERIFIED'
        wanted=expected_mod
        previous=dict(state)
    if tx.get('state') != ('RESTORED_VERIFIED' if restore else 'APPLIED_VERIFIED') or file_sha(target)!=wanted:
        raise RuntimeError('GAME_DEPLOY_OR_RESTORE_NOT_VERIFIED')
    result={**previous,'status':status,'game_assets_written':True,'game_stage_sha256':file_sha(target),
            'transaction_state':tx['state'],'stage_path':str(target), 'models_runtime_loaded':False}
    write_json_atomic(base/'game_publish.json',result)
    return result


def main(argv: list[str]|None=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tool-root',type=pathlib.Path,default=pathlib.Path.cwd())
    ap.add_argument('--game-root',type=pathlib.Path,required=True)
    ap.add_argument('--map-dir',type=pathlib.Path)
    ap.add_argument('--expected-sha256',default=ORIGINAL_SHA,help=argparse.SUPPRESS)
    ap.add_argument('--expected-faces',type=int,default=SOURCE_FACES,help=argparse.SUPPRESS)
    actions=ap.add_mutually_exclusive_group()
    actions.add_argument('--clone-test',action='store_true')
    actions.add_argument('--publish-game',action='store_true')
    actions.add_argument('--restore-game',action='store_true')
    ap.add_argument('--confirm',default='')
    args=ap.parse_args(argv)
    try:
        tool_root=args.tool_root.expanduser().resolve(strict=True)
        game_root=args.game_root.expanduser().resolve(strict=True)
        if args.clone_test:
            out=clone_rehearsal(tool_root,game_root,map_dir=args.map_dir,
                                expected_sha=args.expected_sha256,expected_faces=args.expected_faces)
        elif args.publish_game or args.restore_game:
            out=real_publish(tool_root,game_root,restore=args.restore_game,confirmation=args.confirm)
        else:
            out=prepare(tool_root,game_root,args.map_dir,expected_sha=args.expected_sha256,
                        expected_faces=args.expected_faces)
        print(json.dumps(out,indent=2,ensure_ascii=False))
        return 0 if out.get('status') not in ('BLOCKED_UNSAFE_FACES','BLOCKED_BUNDLE_PLAN') else 2
    except Exception as error:
        print(json.dumps({'format':FORMAT,'status':'FAILED','error':f'{type(error).__name__}:{error}'},indent=2,ensure_ascii=False))
        return 3


if __name__=='__main__':
    raise SystemExit(main())
