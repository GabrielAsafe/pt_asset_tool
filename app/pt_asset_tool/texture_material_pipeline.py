"""Post-upscale Priston Tale material lab (read-only input, staged output).

Processes EXISTING resolutions only; NEVER calls any upscale backend. Builds
provenance-bound visual review and optional offline-only material maps. The
renderer/mesh certification gate deliberately remains closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

from PIL import Image, ImageChops, ImageFilter

from .runtime_paths import external_process_env
from . import texture_upscale as tex
from .texture_material_maps import height_from_diffuse, normals_from_height, renormalize_normals, parallax_demo
from .texture_material_quality import assess, difference_preview
from . import texture_material_profiles as profiles

FORMAT = 'PT_TEXTURE_MATERIAL_LAB_V1'
MATERIALS = ('stone','wood','metal','terrain','fabric','foliage','skin','painted','unknown')
MATERIAL_PATTERNS = {
    'stone': ('stone','rock','brick','wall','cliff','cave'),
    'wood': ('wood','tree','log','plank','door','bark'),
    'metal': ('metal','iron','steel','armor','armour','shield','sword'),
    'terrain': ('ground','grass','sand','dirt','terrain','field','soil','road'),
    'fabric': ('cloth','fabric','cape','robe','shirt','banner'),
    'foliage': ('leaf','leaves','bush','flower','foliage'),
    'skin': ('face','skin','body','hand','head'),
    'painted': ('ui','icon','sprite','effect','font','interface'),
}
MODES = ('off','light','medium','ai')
MAP_MODES = ('off','from-diffuse','from-height')


def dump(path: Path, data: object, *, overwrite: bool = False) -> None:
    tex._json_dump(path, data, overwrite=overwrite)


def _file_hash(path: Path) -> str:
    return tex.sha256_file(path)


def material_of(rel: str, overrides: dict) -> str:
    for pattern, material in overrides.items():
        if tex._matches_any(rel, [pattern]):
            if material not in MATERIALS:
                raise ValueError(f'INVALID_MATERIAL: {material}')
            return material
    name = rel.lower().replace('\\','/')
    tokens = set(re.split(r'[^a-z0-9]+', name))
    for material, keys in MATERIAL_PATTERNS.items():
        if tokens.intersection(keys):
            return material
    return 'unknown'


def load_config(path: Path | None) -> dict:
    if not path:
        return {'material_overrides': {}, 'models': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('CONFIG_MUST_BE_OBJECT')
    overrides = data.get('material_overrides', {})
    models = data.get('models', {})
    if not isinstance(overrides, dict) or not isinstance(models, dict):
        raise ValueError('INVALID_CONFIG_REGISTRY')
    for mat, row in models.items():
        if mat not in MATERIALS and mat != 'default':
            raise ValueError('INVALID_MODEL_MATERIAL')
        if not isinstance(row, dict) or row.get('engine') not in {'spandrel','external','ncnn_vulkan'}:
            raise ValueError('MODEL_ENGINE_MUST_BE_SPANDREL_EXTERNAL_OR_NCNN_VULKAN')
        hash_ = str(row.get('sha256') or '')
        if not re.fullmatch(r'[0-9a-fA-F]{64}', hash_):
            raise ValueError('MODEL_MUST_HAVE_SHA256')
        if row.get('engine') == 'spandrel' and not row.get('model'):
            raise ValueError('SPANDREL_MODEL_PATH_REQUIRED')
        if row.get('engine') == 'external' and (not isinstance(row.get('argv'), list) or not row.get('argv')):
            raise ValueError('EXTERNAL_ARGV_REQUIRED')
        if row.get('engine') == 'ncnn_vulkan':
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in
                       ('model_param', 'model_bin', 'python', 'runtime_root')):
                raise ValueError('NCNN_CONFIG_PATHS_REQUIRED')
            if not re.fullmatch(r'[0-9a-fA-F]{64}', str(row.get('sha256_bin') or '')):
                raise ValueError('NCNN_BIN_SHA256_REQUIRED')
            tile, halo, gpu_id = (int(row.get('tile', 256)), int(row.get('halo', 24)),
                                  int(row.get('gpu_id', 0)))
            if not (32 <= tile <= 1024 and 0 <= halo < tile // 2 and gpu_id >= 0):
                raise ValueError('NCNN_INVALID_TILE_HALO_OR_GPU')
    return data


def model_for(material: str, config: dict) -> dict | None:
    models = config.get('models') or {}
    return models.get(material) or models.get('default')


def _model_path(model: dict, config_path: Path | None) -> Path:
    path = Path(str(model.get('model_param') if model.get('engine') == 'ncnn_vulkan' else model.get('model') or '')).expanduser()
    if not path.is_absolute() and config_path:
        path = config_path.parent / path
    return path.resolve()


def _config_file_path(value: str, config_path: Path | None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and config_path:
        path = config_path.parent / path
    return path.resolve()


def validate_model(model: dict, config_path: Path | None) -> Path:
    p = _model_path(model, config_path)
    if not p.is_file():
        raise FileNotFoundError(f'MODEL_NOT_INSTALLED: {p}')
    if _file_hash(p).lower() != model['sha256'].lower():
        raise ValueError('MODEL_SHA256_MISMATCH')
    if model['engine'] == 'ncnn_vulkan':
        other = _config_file_path(model['model_bin'], config_path)
        if not other.is_file() or _file_hash(other).lower() != model['sha256_bin'].lower():
            raise ValueError('NCNN_BIN_SHA256_MISMATCH')
        py = _config_file_path(model['python'], config_path)
        runtime = _config_file_path(model['runtime_root'], config_path)
        if not py.is_file() or not os.access(py, os.X_OK):
            raise FileNotFoundError(f'NCNN_PYTHON_NOT_EXECUTABLE: {py}')
        if not runtime.is_dir():
            raise FileNotFoundError(f'NCNN_RUNTIME_NOT_INSTALLED: {runtime}')
    return p


def restore_rgb(image: Image.Image, model: dict, config_path: Path | None) -> tuple[Image.Image, dict]:
    p = validate_model(model, config_path)
    alpha = image.getchannel('A') if 'A' in image.getbands() else None
    with tempfile.TemporaryDirectory(prefix='pt_material_ai_') as td:
        before, after = Path(td)/'before.png', Path(td)/'after.png'
        image.convert('RGB').save(before)
        if model['engine'] == 'spandrel':
            cmd = [sys.executable, '-m', 'pt_asset_tool.texture_model_runner',
                   '--input', str(before), '--output', str(after), '--model', str(p),
                   '--sha256', model['sha256'], '--tile', str(int(model.get('tile',256))),
                   '--halo', str(int(model.get('halo',24))),
                   '--device', str(model.get('device','cpu'))]
        elif model['engine'] == 'ncnn_vulkan':
            python_bin = _config_file_path(model['python'], config_path)
            runtime_root = _config_file_path(model['runtime_root'], config_path)
            other = _config_file_path(model['model_bin'], config_path)
            runner = Path(__file__).with_name('texture_ncnn_runner.py')
            cmd = [str(python_bin), str(runner), '--input', str(before), '--output', str(after),
                   '--model-param', str(p), '--model-bin', str(other),
                   '--sha256', model['sha256'], '--sha256-bin', model['sha256_bin'],
                   '--runtime-root', str(runtime_root), '--gpu-id', str(int(model.get('gpu_id',0))),
                   '--tile', str(int(model.get('tile',256))), '--halo', str(int(model.get('halo',24)))]
            if model.get('tile_cache_root'):
                cmd += ['--cache-root', str(_config_file_path(model['tile_cache_root'], config_path))]
        else:
            # Argument arrays only, never shell=True or eval. Substitution can
            # only inject the three deliberately documented literal tokens.
            cmd = [str(v).replace('{input}',str(before)).replace('{output}',str(after)).replace('{model}',str(p)) for v in model['argv']]
            if not all(isinstance(v,str) and v for v in model['argv']):
                raise ValueError('INVALID_EXTERNAL_COMMAND')
            if not any('{output}' in v for v in model['argv']):
                raise ValueError('EXTERNAL_COMMAND_MUST_USE_OUTPUT_TOKEN')
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=int(model.get('timeout',900)), env=external_process_env())
        if cp.returncode != 0 or not after.is_file():
            raise RuntimeError('RESTORER_FAILED: ' + (cp.stderr or cp.stdout or str(cp.returncode))[-600:])
        with Image.open(after) as loaded:
            loaded.load()
            if loaded.size != image.size:
                raise ValueError('AI_RESTORER_CHANGED_DIMENSIONS_UPSCALE_FORBIDDEN')
            output = loaded.convert('RGB')
    if alpha:
        output=output.convert('RGBA')
        output.putalpha(alpha)
    return output, {'engine': model['engine'], 'model_sha256': model['sha256'],
                    **({'model_bin_sha256': model['sha256_bin'],
                        'gpu_id': int(model.get('gpu_id', 0)),
                        'tile': int(model.get('tile', 256)),
                        'halo': int(model.get('halo', 24)),
                        'cache_configured': bool(model.get('tile_cache_root'))}
                       if model['engine'] == 'ncnn_vulkan' else {}),
                    'scale': 1}


def _decode_bytes_verifiable(raw: bytes, rec, meta):
    """Force exact same approved codec path on both pre-/post-serialization."""
    with tempfile.TemporaryDirectory(prefix='pt_material_verify_') as td:
        path=Path(td)/('check'+rec.suffix)
        path.write_bytes(raw)
        check, metadata = tex.inspect_texture(path)
        if (check.width != rec.width or check.height != rec.height or
                check.protected != rec.protected or check.protection_mode != rec.protection_mode):
            raise ValueError('ENCODED_FORMAT_OR_DIMENSIONS_CHANGED')
        return tex.decode_texture(path, check, metadata)


def _stage_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.png', delete=False) as tmp:
        tmp_path=Path(tmp.name)
    try:
        image.save(tmp_path, format='PNG')
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _thumbnail(image: Image.Image, path: Path) -> None:
    pic=image.convert('RGBA')
    pic.thumbnail((360,260), Image.Resampling.LANCZOS)
    # Convert transparency to checker / neutral background for UI.
    canvas=Image.new('RGB', pic.size, (110,110,110))
    canvas.paste(pic,mask=pic.getchannel('A'))
    _stage_image(canvas,path)


def _find_height(root: Path, rel: str) -> Path | None:
    p=Path(rel)
    for name in (p.stem+'_height',p.stem+'_h',p.stem+'.height',p.stem):
        for suffix in ('.png','.tga','.bmp'):
            target = (root/p.parent/(name+suffix)).resolve()
            if tex._is_within(root,target) and target.is_file():
                return target
    return None


def mesh_diagnostics(mesh_root: Path | None, *, limit: int = 5000) -> dict:
    if mesh_root is None:
        return {'state': 'NOT_CONFIGURED', 'reason': 'Provide --mesh-root (read-only .smd scan); this does not repair model geometry.', 'runtime_parallax_certified': False}
    from pt_character_structural_gate_v2 import parse_smd
    mesh_root=mesh_root.expanduser().resolve()
    if not mesh_root.is_dir():
        raise FileNotFoundError(mesh_root)
    rows=[]
    for path in sorted(mesh_root.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.smd':
            continue
        if len(rows) >= limit:
            break
        row={'path':path.relative_to(mesh_root).as_posix(),'sha256':_file_hash(path),'status':'MANUAL_MESH_REVIEW','client_modified':False}
        try:
            parsed=parse_smd(path)
            row.update({'object_count':parsed['object_count'],
                        'vertex_count':sum(o['vertices'] for o in parsed['objects']),
                        'face_count':sum(o['faces'] for o in parsed['objects']),
                        'texlink_count':sum(o['texlinks'] for o in parsed['objects']),
                        'zero_face_objects':[o['name'] for o in parsed['objects'] if o['faces'] == 0],
                        'untextured_objects':[o['name'] for o in parsed['objects'] if o['texlinks'] == 0]})
            row['status']='STRUCTURE_READ_ONLY_OK'
        except Exception as exc:
            row['status']='UNSUPPORTED_OR_INVALID_SMD'
            row['reason']=f'{type(exc).__name__}: {exc}'[:300]
        rows.append(row)
    return {'state':'READ_ONLY_AUDIT', 'mesh_count':len(rows), 'limit':limit,
            'note':'Model 0.62 structural summary only; stage 0.72, UV seams, tangent space, lighting and in-game mesh fixes need manual/engine validation.',
            'runtime_parallax_certified': False,'mesh_fixes_applied':0,'meshes':rows}


def prepare(input_root: Path, output_root: Path, *, include: list[str], exact: list[str], all_: bool,
            include_ui: bool=False, include_technical: bool=False, config_path: Path | None=None,
            denoise: str='off', maps: str='off', height_root: Path | None=None,
            mesh_root: Path | None=None, max_dimension: int=8192, checkpoint_every: int=25,
            alpha_tolerance: int=0, profile: str='legacy', profile_config: Path | None=None) -> dict:
    if profile not in ('legacy', profiles.PROFILE, profiles.ADAPTIVE_PROFILE):
        raise ValueError('INVALID_PROFILE')
    if denoise not in MODES or maps not in MAP_MODES:
        raise ValueError('INVALID_PIPELINE_OPTION')
    if not (all_ ^ bool(include or exact)):
        raise ValueError('EXPLICIT_SELECTION_REQUIRED: --all OR --include/--include-exact')
    if max_dimension < 1 or alpha_tolerance != 0:
        raise ValueError('INVALID_LIMIT_OR_ALPHA_TOLERANCE')
    input_root=input_root.expanduser().resolve()
    output_root=output_root.expanduser().resolve()
    if not input_root.is_dir():
        raise FileNotFoundError(input_root)
    if input_root == output_root or tex._is_within(input_root,output_root) or tex._is_within(output_root,input_root):
        raise ValueError('OUTPUT_MUST_BE_DISJOINT_FROM_INPUT')
    if output_root.exists():
        raise FileExistsError(f'RUN_DESTINATION_ALREADY_EXISTS: {output_root}')
    if height_root:
        height_root=height_root.expanduser().resolve()
        if not height_root.is_dir():
            raise FileNotFoundError(height_root)
    config_path=config_path.expanduser().resolve() if config_path else None
    config=load_config(config_path)
    profile_config=profile_config.expanduser().resolve() if profile_config else None
    policy=profiles.load_profile_config(profile_config) if profile != 'legacy' else {}
    # Tile checkpoints are explicitly outside the read-only client tree.
    for model in (config.get('models') or {}).values():
        if model.get('engine') == 'ncnn_vulkan' and model.get('tile_cache_root'):
            cache = _config_file_path(model['tile_cache_root'], config_path)
            if cache == input_root or tex._is_within(input_root, cache):
                raise ValueError('NCNN_TILE_CACHE_INSIDE_CLIENT_BLOCKED')
    rows=[]; counts=Counter(); used_models={}
    run_config={'denoise':denoise,'maps':maps,'include_ui':include_ui,'include_technical':include_technical,
                'all':all_, 'include':include,'exact':exact,'max_dimension':max_dimension,
                'config_path':str(config_path) if config_path else None,
                'config_sha256':_file_hash(config_path) if config_path else None,
                'profile':profile,'profile_config':str(profile_config) if profile_config else None,
                'profile_config_sha256':_file_hash(profile_config) if profile_config else None}
    if profile == profiles.ADAPTIVE_PROFILE:
        run_config['adaptive_policy'] = profiles.adaptive_policy_summary()
    report={'format':FORMAT,'action':'run','state':'RUNNING_CHECKPOINT','input_root':str(input_root),
            'output_root':str(output_root),'source_mutated':False,'upscale_performed':False,
            'scaling_factor':1,'generated_materials_for_engine':False,'model_ai_enabled':(denoise=='ai' or profile in (profiles.PROFILE, profiles.ADAPTIVE_PROFILE)),
            'run_config':run_config,'records':rows,'status_counts':{},'model_hashes':used_models,
            'engine_parallax_gate':'BLOCKED_REQUIRES_RENDERER_SHADER_INTEGRATION',
            'mesh_fix_gate':'BLOCKED_REQUIRES_VALIDATED_MODEL_AUTHORING'}
    manifest=output_root/'manifest.json'
    overlay=output_root/'overlay'
    preview=output_root/'previews'
    for path in sorted(tex.iter_textures(input_root)):
        rel=path.relative_to(input_root).as_posix()
        if not all_ and not tex._selected(rel,include,exact):
            continue
        if not tex._is_within(input_root,path.resolve()):
            raise ValueError('SYMLINK_OUTSIDE_INPUT_ROOT_BLOCKED')
        start=time.monotonic()
        role=tex.detect_texture_role(rel)
        mat=material_of(rel,config.get('material_overrides') or {})
        choice=(profiles.decide(rel,role=role,base_material=mat,config=policy,
                                 context='/'.join(input_root.parts[-4:]))
                if profile != 'legacy' else None)
        if choice is not None:
            mat=choice['material']
        effective_denoise=choice['action'] if choice is not None else denoise
        row={'source':rel,'role':role,'material':mat, 'status':'pending',
             'source_sha256':_file_hash(path),'review':'pending','output_sha256':None,
             'upscaled':False,'technical_maps_deployable':False}
        if choice is not None:
            row['profile_decision']=choice
        try:
            if choice is not None and choice['action']=='skip':
                row.update(status='skipped_profile',reason=choice['reason'])
                continue
            if not include_ui and tex._risk_class(rel)=='UI_ATLAS_RISK':
                row.update(status='skipped_ui_atlas',reason='UI/masks/atlases need explicit --include-ui; RGB cleanup may change colorkeys')
                continue
            if role != 'diffuse_candidate' and not include_technical:
                row.update(status='skipped_technical',reason='Normal/height maps require explicit --include-technical')
                continue
            record, meta = tex.inspect_texture(path)
            if max(record.width,record.height) > max_dimension:
                row.update(status='skipped_dimension',reason='Existing source exceeds max dimension; NO auto resize')
                continue
            row['dimensions']=[record.width,record.height]
            if profile == profiles.ADAPTIVE_PROFILE:
                # Inspected dimensions include protected Priston headers.
                # A skipped source never reaches decoding, AI, or serialization.
                choice=profiles.adapt_by_dimensions(choice, width=record.width, height=record.height)
                row['profile_decision']=choice
                effective_denoise=choice['action']
                if choice['action']=='skip':
                    row.update(status='skipped_profile', reason=choice['reason'])
                    continue
            source=tex.decode_texture(path,record,meta)
            processed=source
            if role == 'normal_candidate':
                processed=renormalize_normals(source)
                row['restoration']='normal_vectors_renormalized'
            elif role == 'height_candidate':
                processed=source
                row['restoration']='technical_height_unchanged'
            elif effective_denoise in ('light','medium'):
                processed=tex.clean_compression_artifacts(source,effective_denoise)
                row['restoration']='conservative_rgb_median_not_ai'
            elif effective_denoise=='ai':
                model=model_for(mat,config)
                if model is None:
                    raise ValueError(f'AI_MODEL_NOT_CONFIGURED_FOR_MATERIAL:{mat}')
                processed, ai_meta=restore_rgb(source,model,config_path)
                row['restoration']='ai_dxt_1x'
                row['ai']=ai_meta
                used_models[mat]=ai_meta['model_sha256']
            else:
                row['restoration']='original_bytes_unchanged'
            if processed.size != source.size:
                raise RuntimeError('NO_UPSCALE_DIMENSION_GUARD')
            # Classic PT BMP may use RGB(0,0,0) as color key, not an alpha
            # channel. Preserve the exact transparent-pixel mask, including
            # preventing new key-black pixels caused by AI/median filtering.
            if record.suffix == '.bmp' and effective_denoise != 'off' and role == 'diffuse_candidate':
                import numpy as np
                before_rgb = np.asarray(source.convert('RGB'),dtype=np.uint8)
                after_rgb = np.array(processed.convert('RGB'),dtype=np.uint8,copy=True)
                original_key = np.all(before_rgb == 0,axis=2)
                new_key = np.all(after_rgb == 0,axis=2)
                after_rgb[original_key] = 0
                after_rgb[new_key & ~original_key,0] = 1
                processed = Image.fromarray(after_rgb)
                row['bmp_black_colorkey_preserved'] = True
            # Protected legacy files retain exact bytes when no pixel editing
            # takes place. RGB edits go through proven, versioned codecs.
            changed=(ImageChops.difference(source.convert('RGB'),processed.convert('RGB')).getbbox() is not None or
                     ('A' in source.getbands() and ImageChops.difference(source.getchannel('A'),processed.getchannel('A')).getbbox() is not None))
            if changed:
                original_raw=path.read_bytes()
                encoded=tex.encode_texture(processed,original_raw,record,meta)
                decoded=_decode_bytes_verifiable(encoded,record,meta)
                if decoded.size != source.size:
                    raise RuntimeError('ROUNDTRIP_DIMENSIONS_CHANGED')
                if 'A' in source.getbands() and ('A' not in decoded.getbands() or ImageChops.difference(source.getchannel('A'),decoded.getchannel('A')).getbbox()):
                    raise ValueError('ALPHA_NOT_PRESERVED')
                # lossy JPEG reencoding cannot be pixel-for-pixel witness;
                # transparency and resolution are still strictly checked.
            else:
                encoded=path.read_bytes()
            target=overlay/rel
            tex._atomic_publish(target,encoded,overwrite=False)
            if _file_hash(target) != tex.sha256_bytes(encoded):
                raise RuntimeError('OUTPUT_HASH_MISMATCH')
            row.update(output=str(target.relative_to(output_root).as_posix()),output_sha256=_file_hash(target),
                       size_unchanged=True,bytes_changed=changed,status='staged')
            _thumbnail(source,preview/(rel+'.before.png'))
            _thumbnail(processed,preview/(rel+'.after.png'))
            row['quality']=assess(source,processed)
            row['preview_difference']=str((Path('previews')/(rel+'.difference.png')).as_posix())
            _thumbnail(difference_preview(source,processed),preview/(rel+'.difference.png'))
            row['preview_before']=str((Path('previews')/(rel+'.before.png')).as_posix())
            row['preview_after']=str((Path('previews')/(rel+'.after.png')).as_posix())
            if maps != 'off' and role == 'diffuse_candidate':
                if maps == 'from-height':
                    hpath=_find_height(height_root,rel) if height_root else None
                    if not hpath:
                        raise FileNotFoundError(f'AUTHORED_HEIGHT_MISSING: {rel}')
                    hr,hm=tex.inspect_texture(hpath)
                    h=tex.decode_texture(hpath,hr,hm).convert('L')
                    if h.size != processed.size:
                        raise ValueError('AUTHORED_HEIGHT_SIZE_MISMATCH')
                    row['height_source']={'path':str(hpath),'sha256':_file_hash(hpath),'basis':'authored'}
                else:
                    h=height_from_diffuse(processed)
                    row['height_source']={'basis':'luminance_estimate_NOT_physical'}
                mp=output_root/'maps'/rel
                hp=mp.with_name(mp.name+'.height.png')
                dx=mp.with_name(mp.name+'.normal_dx.png')
                gl=mp.with_name(mp.name+'.normal_gl.png')
                demo=mp.with_name(mp.name+'.parallax_demo.png')
                _stage_image(h,hp)
                _stage_image(normals_from_height(h,convention='directx'),dx)
                _stage_image(normals_from_height(h,convention='opengl'),gl)
                _stage_image(parallax_demo(processed,h),demo)
                row['maps']={name:{'path':f.relative_to(output_root).as_posix(),'sha256':_file_hash(f)}
                             for name,f in (('height',hp),('normal_dx',dx),('normal_gl',gl),('parallax_demo',demo))}
                row['material_map_state']='OFFLINE_AUTHORING_REQUIRES_SHADER_AND_ARTIST_APPROVAL'
        except Exception as exc:
            row['status']='failed'
            row['reason']=f'{type(exc).__name__}: {exc}'[:800]
            # Remove all partially staged files for this source; an erroneous
            # map must never leave a publishable candidate behind.
            (overlay/rel).unlink(missing_ok=True)
            (preview/(rel+'.before.png')).unlink(missing_ok=True)
            (preview/(rel+'.after.png')).unlink(missing_ok=True)
            (preview/(rel+'.difference.png')).unlink(missing_ok=True)
            for suffix in ('.height.png','.normal_dx.png','.normal_gl.png','.parallax_demo.png'):
                (output_root/'maps'/(rel+suffix)).unlink(missing_ok=True)
            row['output_sha256']=None
            row.pop('output',None)
            row.pop('maps',None)
        finally:
            row['input_unchanged']=path.is_file() and _file_hash(path)==row['source_sha256']
            if not row['input_unchanged']:
                if row.get('output'):
                    (output_root/row['output']).unlink(missing_ok=True)
                row.pop('output',None)
                row.pop('maps',None)
                row['output_sha256']=None
                row['status']='failed'
                row['reason']='SOURCE_DRIFT_DURING_RUN'
            row['elapsed_seconds']=round(time.monotonic()-start,3)
            rows.append(row)
            counts[row['status']]+=1
            if len(rows) % max(1,checkpoint_every)==0:
                report['status_counts']=dict(counts)
                dump(manifest,report,overwrite=True)
    report['status_counts']=dict(counts)
    report['mesh_audit']=mesh_diagnostics(mesh_root)
    report['state']='COMPLETE_WITH_ERRORS' if counts['failed'] else 'AWAITING_REVIEW'
    report['readiness']={'ai_1x_executed':any(x.get('restoration')=='ai_dxt_1x' and x['status']=='staged' for x in rows),
                        'normal_height_maps_generated':sum(bool(x.get('maps')) for x in rows),
                        'normal_height_runtime_certified':False,
                        'mesh_fixes_runtime_certified':False,
                        'all_candidates_human_approved':False,
                        'eligible_for_client_publish':False}
    dump(manifest,report,overwrite=True)
    write_gallery(report)
    return report


def _verified_manifest(path: Path) -> dict:
    d=json.loads(path.read_text(encoding='utf-8'))
    if d.get('format')!=FORMAT or d.get('action')!='run' or not isinstance(d.get('records'),list):
        raise ValueError('INVALID_MATERIAL_LAB_MANIFEST')
    if path.resolve() != (Path(d['output_root'])/'manifest.json').resolve():
        raise ValueError('MANIFEST_ROOT_MISMATCH')
    return d


def _gallery_script() -> str:
    return '''<script>
function downloadReviews(){
 const entries=[...document.querySelectorAll('select[data-path]')].map(s=>({source:s.dataset.path,output_sha256:s.dataset.sha,decision:s.value})).filter(x=>x.decision!=='pending');
 const doc={format:'PT_MATERIAL_REVIEWS_V1',entries};
 const blob=new Blob([JSON.stringify(doc,null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='material-reviews.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);
}
</script>'''


def write_gallery(d: dict, *, page_size: int=80) -> list[Path]:
    base=Path(d['output_root'])
    staged=[r for r in d['records'] if r['status']=='staged']
    pages=[]
    for pageidx in range(0,max(1,len(staged)),page_size):
        items=staged[pageidx:pageidx+page_size]
        target=base/f'review_{pageidx//page_size+1:03}.html'
        cells=[]
        for r in items:
            rel=html.escape(r['source'])
            before=quote(r['preview_before'],safe='/')
            after=quote(r['preview_after'],safe='/')
            maps=r.get('maps') or {}
            quality=r.get('quality') or {}
            diff=quote(r.get('preview_difference',''),safe='/')
            extra=''.join(f'<a href="{quote(v["path"],safe="/")}" target="_blank">{html.escape(name)}</a> ' for name,v in maps.items())
            cells.append(f'<article><h3>{rel}</h3><p>{html.escape(r["material"])} · {html.escape(r["restoration"])} · {r["dimensions"]}</p>'
                         f'<div class="pictures"><figure><img src="{before}" loading="lazy"><figcaption>Antes</figcaption></figure><figure><img src="{after}" loading="lazy"><figcaption>Depois</figcaption></figure></div>'
                         f'<p>Alteração RGB: {quality.get("pixel_change_percent","?")}% dos pixels; erro médio {quality.get("rgb_mean_absolute_error_255","?")}/255. <a href="{diff}">Ver mapa de diferenças</a> (vermelho = alteração)</p>'
                         f'<p>Mapas (pré-visualização offline): {extra or "não gerados"}</p>'
                         f'<label>Revisão: <select data-path="{html.escape(r["source"],quote=True)}" data-sha="{r["output_sha256"]}">'
                         '<option value="pending">Pendente</option><option value="approve">Aprovar</option><option value="reject">Rejeitar</option></select></label></article>')
        nav=' · '.join(f'<a href="review_{i+1:03}.html">Página {i+1}</a>' for i in range((len(staged)+page_size-1)//page_size))
        page='''<!doctype html><html lang="pt"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PT Material Lab · Revisão</title>
<style>body{font:15px system-ui;background:#10151d;color:#eee;max-width:1400px;margin:25px auto;padding:0 20px}a{color:#9bd5fc}
article{background:#222a35;border:1px solid #526079;border-radius:12px;padding:18px;margin:20px 0}h3{overflow-wrap:anywhere}
.pictures{display:flex;gap:15px;flex-wrap:wrap}figure{margin:0}img{max-width:360px;image-rendering:auto;background:#666}figcaption{opacity:.8}
button,select{font:inherit;padding:9px;background:#e3ebf5;color:#10151d;border:0;border-radius:5px}</style>''' + f'''<h1>Material Lab · revisão manual</h1><p>Sem novo upscale e sem publicação automática. Altura derivada da cor é estimada; normal e parallax não funcionam no jogo sem suporte do shader. Cada aprovação fica vinculada ao SHA-256 do candidato.</p><p>{nav}</p><button onclick="downloadReviews()">Exportar decisões desta página (JSON)</button>'''+''.join(cells)+_gallery_script()+'</html>'
        tex._atomic_publish(target,page.encode('utf-8'),overwrite=True)
        pages.append(target)
    return pages


def import_reviews(manifest: Path, decisions: Path) -> dict:
    d=_verified_manifest(manifest.resolve())
    approvals_path=manifest.parent/'reviews.json'
    data=json.loads(decisions.read_text(encoding='utf-8'))
    if data.get('format')!='PT_MATERIAL_REVIEWS_V1' or not isinstance(data.get('entries'),list):
        raise ValueError('INVALID_REVIEW_DOCUMENT')
    accepted={r['source']:r for r in d['records'] if r['status']=='staged'}
    if any((r['status']=='failed' or not r.get('input_unchanged',False)) for r in d['records']):
        raise ValueError('CANNOT_IMPORT_APPROVALS_FOR_INCOMPLETE_RUN')
    for r in d['records']:
        input_file=_resolved_candidate(Path(d['input_root']).resolve(),r['source'])
        if not input_file.is_file() or _file_hash(input_file)!=r['source_sha256']:
            raise ValueError('SOURCE_DRIFT_CANNOT_APPROVE')
    stored=json.loads(approvals_path.read_text()) if approvals_path.exists() else {'format':'PT_MATERIAL_REVIEWS_V1','decisions':{}}
    rows=stored['decisions']
    for r in data['entries']:
        path=r.get('source'); sha=r.get('output_sha256')
        if path not in accepted or accepted[path]['output_sha256'] != sha:
            raise ValueError('REVIEW_SOURCE_OR_SHA256_MISMATCH')
        if r.get('decision') not in ('approve','reject'):
            raise ValueError('INVALID_REVIEW_DECISION')
        target=manifest.parent / accepted[path]['output']
        if not target.is_file() or _file_hash(target)!=sha:
            raise ValueError('OUTPUT_DRIFT_CANNOT_APPROVE')
        rows[path]={'output_sha256':sha,'decision':r['decision']}
    dump(approvals_path,stored,overwrite=True)
    return audit(manifest)


def _resolved_candidate(root: Path, relative: str) -> Path:
    """Only allow files belonging to this run, never path escape or symlinks."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('INVALID_CANDIDATE_PATH')
    p = root / relative
    if not tex._is_within(root.resolve(), p.resolve()) or p.is_symlink():
        raise ValueError('CANDIDATE_PATH_ESCAPE_OR_SYMLINK')
    return p


def audit(manifest: Path) -> dict:
    d=_verified_manifest(manifest.resolve()); root=manifest.parent.resolve()
    approvals_path=root/'reviews.json'
    stored=json.loads(approvals_path.read_text(encoding='utf-8')) if approvals_path.exists() else {'decisions':{}}
    rows=stored['decisions']
    issues=[]; total=0; ok=0
    source_root=Path(d['input_root']).resolve()
    for rec in d['records']:
        if rec['status']=='failed' or not rec.get('input_unchanged',False):
            issues.append({'source':rec['source'],'reason':'RUN_HAS_FAILED_OR_DRIFTED_INPUT'})
        try:
            source=_resolved_candidate(source_root,rec['source'])
            if not source.is_file() or _file_hash(source)!=rec['source_sha256']:
                issues.append({'source':rec['source'],'reason':'SOURCE_CHANGED_SINCE_RUN'})
        except (ValueError, OSError):
            issues.append({'source':rec['source'],'reason':'SOURCE_INVALID_OR_ESCAPED'})
        if rec['status']!='staged':
            continue
        total+=1
        try:
            p=_resolved_candidate(root,rec['output'])
            if not p.is_file() or _file_hash(p)!=rec['output_sha256']:
                issues.append({'source':rec['source'],'reason':'CANDIDATE_HASH_DRIFT'})
                continue
            map_drift=False
            for mapping in (rec.get('maps') or {}).values():
                q=_resolved_candidate(root,mapping['path'])
                if not q.is_file() or _file_hash(q)!=mapping['sha256']:
                    issues.append({'source':rec['source'],'reason':'MATERIAL_MAP_DRIFT'})
                    map_drift=True
        except (ValueError, KeyError, OSError):
            issues.append({'source':rec['source'],'reason':'UNSAFE_OR_MISSING_CANDIDATE'})
            continue
        decision=rows.get(rec['source'],{})
        if decision.get('output_sha256') != rec['output_sha256'] or decision.get('decision')!='approve':
            issues.append({'source':rec['source'],'reason':'AWAITING_OR_REJECTED_REVIEW'})
        elif not map_drift:
            ok+=1
    if d.get('state') != 'AWAITING_REVIEW':
        issues.append({'reason':'RUN_NOT_SUCCESSFULLY_COMPLETED','state':d.get('state')})
    reviewed=total>0 and not issues
    return {'format':FORMAT,'action':'audit','manifest':str(manifest),'staged_candidates':total,
            'human_approved_candidates':ok,'issues':issues,
            'all_staged_reviewed':reviewed,
            'offline_candidate_ready':reviewed,
            'runtime_parallax_certified':False,'runtime_mesh_fixes_certified':False,
            'client_publish_authorized':False,'source_mutated':False,
            'next_step':'Export to independent review workspace only; certify renderer, shader and mesh in real client before any deployment.'}


def export_approved(manifest: Path, output_root: Path) -> dict:
    """Create a *new*, non-deployable verification bundle for in-engine authors.

    Requires current input hashes, all approvals, maps and stage hashes; never
    writes within the input tree, run tree, client or implicit project folders.
    """
    manifest=manifest.expanduser().resolve()
    check=audit(manifest)
    if not check['offline_candidate_ready']:
        raise ValueError('AUDIT_BLOCKED_EXPORT: ' + ','.join(sorted({x['reason'] for x in check['issues']})))
    d=_verified_manifest(manifest)
    source_root=Path(d['input_root']).resolve()
    run_root=manifest.parent.resolve()
    output_root=output_root.expanduser().resolve()
    project_root=tex.PROJECT_ROOT.resolve()
    # User must explicitly choose a fresh folder OUTSIDE all project and
    # data roots to avoid accidental mistaken deployment into a client tree.
    for forbidden in (source_root,run_root,project_root):
        if output_root==forbidden or tex._is_within(forbidden,output_root) or tex._is_within(output_root,forbidden):
            raise ValueError('REVIEW_EXPORT_MUST_BE_DISJOINT_FROM_PROJECT_INPUT_AND_RUN')
    if output_root.exists():
        raise FileExistsError(f'EXPORT_DESTINATION_ALREADY_EXISTS: {output_root}')
    overlay=output_root/'candidates'
    rows=[]
    try:
        for rec in d['records']:
            if rec['status']!='staged':
                continue
            rel=rec['source']
            source=_resolved_candidate(run_root,rec['output'])
            if _file_hash(source)!=rec['output_sha256']:
                raise ValueError('CANDIDATE_CHANGED_DURING_EXPORT')
            dest=_resolved_candidate(overlay,rel)
            tex._atomic_publish(dest,source.read_bytes(),overwrite=False)
            copied_maps={}
            for name, mapping in (rec.get('maps') or {}).items():
                map_source=_resolved_candidate(run_root,mapping['path'])
                if _file_hash(map_source)!=mapping['sha256']:
                    raise ValueError('MAP_CHANGED_DURING_EXPORT')
                map_dest=_resolved_candidate(output_root,mapping['path'])
                tex._atomic_publish(map_dest,map_source.read_bytes(),overwrite=False)
                copied_maps[name]={'path':mapping['path'],'sha256':mapping['sha256']}
            rows.append({'source':rel,'sha256':rec['output_sha256'],'size':dest.stat().st_size,
                         'maps':copied_maps,'material':rec.get('material'),'role':rec.get('role')})
        # Any source drift during copying aborts the bundle rather than
        # exporting candidates tied to the wrong source snapshot.
        if not audit(manifest)['offline_candidate_ready']:
            raise ValueError('AUDIT_CHANGED_DURING_EXPORT')
        report={'format':'PT_MATERIAL_OFFLINE_REVIEW_BUNDLE_V1',
                'purpose':'EXTERNAL_TEST_AND_INSPECTION_ONLY',
                'may_publish_to_client':False,'in_game_tested':False,
                'runtime_parallax_certified':False,'run_manifest_sha256':_file_hash(manifest),
                'run_manifest':str(manifest),'candidate_count':len(rows),'files':rows,
                'note':'Both candidates and offline maps copied with hashes. Not a client deployment bundle.'}
        dump(output_root/'OFFLINE_REVIEW_BUNDLE.json',report)
    except Exception:
        if output_root.exists():
            shutil.rmtree(output_root)
        raise
    return report


def build_parser():
    p=argparse.ArgumentParser(prog='pt_asset.py texture-material', description='Finish texture restoration AFTER existing upscale; no resizing or client publishing.')
    sp=p.add_subparsers(dest='action',required=True)
    cap=sp.add_parser('capabilities')
    cap.add_argument('--model-config',type=Path)
    run=sp.add_parser('run')
    run.add_argument('--input-root',required=True,type=Path,help='existing upscaled textures directory (read-only), not necessarily original client')
    run.add_argument('--output-root',type=Path,help='fresh staging directory; defaults to unique pt_build/texture_material/runs')
    run.add_argument('--all',action='store_true')
    run.add_argument('--include',action='append',default=[])
    run.add_argument('--include-exact',action='append',default=[])
    run.add_argument('--include-ui',action='store_true')
    run.add_argument('--include-technical',action='store_true')
    run.add_argument('--denoise',choices=MODES,default='off')
    run.add_argument('--maps',choices=MAP_MODES,default='off')
    run.add_argument('--height-root',type=Path)
    run.add_argument('--mesh-root',type=Path)
    run.add_argument('--model-config',type=Path)
    run.add_argument('--profile',choices=('legacy',profiles.PROFILE,profiles.ADAPTIVE_PROFILE),default='legacy',
                     help='safe-game-v1: existing policy; refocus-adaptive-v1: stone/terrain >=1024 long and >=256 short, requires review')
    run.add_argument('--profile-config',type=Path,help='optional safe profile overrides JSON')
    run.add_argument('--max-dimension',type=int,default=8192)
    run.add_argument('--checkpoint-every',type=int,default=25)
    scan=sp.add_parser('profile-scan',help='read-only inventory of AI/skip decisions; no model execution')
    scan.add_argument('--input-root',required=True,type=Path)
    scan.add_argument('--all',action='store_true')
    scan.add_argument('--include',action='append',default=[])
    scan.add_argument('--include-exact',action='append',default=[])
    scan.add_argument('--profile',choices=(profiles.PROFILE, profiles.ADAPTIVE_PROFILE),default=profiles.PROFILE)
    scan.add_argument('--profile-config',type=Path)
    scan.add_argument('--model-config',type=Path,help='optional material_overrides')
    review=sp.add_parser('review-import')
    review.add_argument('--manifest',required=True,type=Path)
    review.add_argument('--decisions',required=True,type=Path)
    audit_p=sp.add_parser('audit')
    audit_p.add_argument('--manifest',required=True,type=Path)
    exp=sp.add_parser('export-approved')
    exp.add_argument('--manifest',required=True,type=Path)
    exp.add_argument('--output-root',required=True,type=Path,help='fresh folder OUTSIDE project, input and stage; offline only')
    mesh=sp.add_parser('mesh-audit')
    mesh.add_argument('--mesh-root',required=True,type=Path)
    mesh.add_argument('--output',type=Path)
    return p


def main(argv=None) -> int:
    a=build_parser().parse_args(argv)
    if a.action=='capabilities':
        configured=load_config(a.model_config)
        status={'tool':FORMAT, 'post_upscale_only':True,'requires_second_upscale':False,
                'models_configured':list((configured.get('models') or {}).keys()),
                'models_present':{k: (_model_path(v,a.model_config).is_file() and
                   (v.get('engine') != 'ncnn_vulkan' or _config_file_path(v['model_bin'],a.model_config).is_file()))
                   for k,v in (configured.get('models') or {}).items()},
                'external_weights_required_for_AI':True,
                'spandrel_optional':'python -m pip install "torch>=2.6" spandrel packaging',
                'shader_runtime_parallax':False, 'mesh_writer_certified':False,
                'maps_offline_available':True,'no_client_writes':True}
        print(json.dumps(status,indent=2,ensure_ascii=False));return 0
    if a.action=='profile-scan':
        model_config=load_config(a.model_config)
        result=profiles.scan(a.input_root,include=a.include,exact=a.include_exact,
                             all_=a.all,config=profiles.load_profile_config(a.profile_config),
                             overrides=model_config.get('material_overrides'),profile=a.profile)
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    if a.action=='run':
        dest=a.output_root or (tex.enhancement_root(tex.PROJECT_ROOT).parent/'texture_material'/'runs'/('run_'+time.strftime('%Y%m%d_%H%M%S')+'_'+os.urandom(3).hex()))
        report=prepare(a.input_root,dest,include=a.include,exact=a.include_exact,all_=a.all,
                       include_ui=a.include_ui,include_technical=a.include_technical,
                       config_path=a.model_config,denoise=a.denoise,maps=a.maps,
                       height_root=a.height_root,mesh_root=a.mesh_root,
                       max_dimension=a.max_dimension,checkpoint_every=a.checkpoint_every,
                       profile=a.profile,profile_config=a.profile_config)
        print(json.dumps({'tool':FORMAT,'manifest':str(dest/'manifest.json'),'gallery':str(dest/'review_001.html'),
                          'status_counts':report['status_counts'],'upscale_performed':False,
                          'client_modified':False,'runtime_parallax_certified':False},indent=2,ensure_ascii=False))
        return 1 if report['status_counts'].get('failed') else 0
    if a.action=='review-import':
        result=import_reviews(a.manifest,a.decisions)
    elif a.action=='audit':
        result=audit(a.manifest)
    elif a.action=='export-approved':
        result=export_approved(a.manifest,a.output_root)
    else:
        result=mesh_diagnostics(a.mesh_root)
        if a.output:
            dump(a.output,result,overwrite=False)
    print(json.dumps(result,indent=2,ensure_ascii=False));return 0

if __name__=='__main__':
    raise SystemExit(main())
