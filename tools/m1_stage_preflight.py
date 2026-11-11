#!/usr/bin/env python3
"""Read-only M1 audit of a Stage 0.72 source, Blender metadata and deployment history.
No asset or game writes. Python standard library only.
"""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_ASSET = "Field/forest/fore-1.smd"
EXPECTED_SOURCE_SHA256 = "df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62"
EXPECTED_FACE_COUNT = 35519

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as fd:
        for chunk in iter(lambda: fd.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def safe_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        return {'__read_error__': f'{type(exc).__name__}:{exc}'}

def stage_candidates(game_root, relative):
    return [game_root / 'assets' / relative,
            game_root / 'Assets' / relative,
            game_root / 'Client' / 'PristonTale' / 'Assets' / relative,
            game_root / relative]

def inspect(tool_root, game_root, relative, source_smd=None):
    relative = Path(relative.replace('\\', '/'))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('asset path must be relative to asset root')
    result = {'format': 'PT_ETERVALE_M1_STAGE_PREFLIGHT_V1',
              'asset': relative.as_posix(),
              'scope': 'READ_ONLY_NO_CLIENT_WRITES',
              'game_runtime_executed': False,
              'source': {}, 'blender': {}, 'pipeline': {}, 'transactions': []}
    paths = ([Path(source_smd).expanduser().resolve()] if source_smd else
             stage_candidates(game_root.resolve(), relative))
    source = next((p for p in paths if p.is_file()), None)
    if source is None:
        result['source'] = {'status': 'NOT_FOUND', 'searched': [str(p) for p in paths]}
    else:
        with source.open('rb') as fd:
            header = fd.read(64)
        sha = sha256(source)
        is_stage = header.startswith(b'SMD Stage data Ver 0.72')
        expected = EXPECTED_SOURCE_SHA256 if relative.as_posix().casefold() == EXPECTED_ASSET.casefold() else None
        result['source'] = {'status': 'PASS' if is_stage and (not expected or sha == expected) else 'REVIEW_REQUIRED',
                            'path': str(source), 'bytes': source.stat().st_size, 'stage072_magic': is_stage,
                            'sha256': sha, 'matches_blender_source': (sha == expected) if expected else None}
    code_files = ['app/pt_asset_tool/asset_bundle_deploy.py',
                  'app/pt_asset_tool/asset_compiler.py',
                  'app/pt_asset_tool/workspace_bundle_deploy.py']
    result['pipeline'] = {'available_files': {p: (tool_root / p).is_file() for p in code_files},
                          'stage_publish_support': 'REQUIRES_VERIFIED_BUILD_MANIFEST',
                          'v32_preview_not_game_artifact': True}
    report_dirs = [tool_root/'app/pt_build/etervale/stage072_semantic_v21/maps',
                   tool_root/'pt_build/etervale/stage072_semantic_v21/maps']
    rows = {}
    for directory in report_dirs:
        if not directory.is_dir():
            continue
        for suffix, key in (('.v30_full_preview.json', 'v30'),
                            ('.v31_residuais.json', 'v31_v32')):
            for path in directory.glob('*' + suffix):
                data = safe_json(path)
                if data.get('asset', '').casefold() != relative.as_posix().casefold():
                    continue
                if key in rows and path.stat().st_mtime <= rows[key][0]:
                    continue
                rows[key] = (path.stat().st_mtime, path, data)
    for key, (_mtime, path, data) in rows.items():
        sha = data.get('source_sha256')
        same = bool(source and sha == result['source'].get('sha256'))
        if key == 'v30':
            result['blender'][key] = {'path': str(path), 'source_hash_matches': same,
                                      'instances': data.get('instance_count'),
                                      'masked_faces': data.get('masked_face_count'),
                                      'publish_enabled': data.get('publish_enabled')}
        else:
            actions = [s.get('v32_action') for s in data.get('selections', []) if s.get('v32_action')]
            result['blender'][key] = {'path': str(path), 'source_hash_matches': same,
                                      'extra_faces': len(set(data.get('extra_faces', []))),
                                      'v32_replace_actions': actions.count('REPLACE_TREE'),
                                      'v32_hide_actions': actions.count('HIDE_LEAVES'),
                                      'publish_enabled': data.get('publish_enabled')}
    if not rows:
        result['blender'] = {'status': 'NO_LOCAL_V30_V32_REPORTS'}
    lod_caches = [tool_root/'app/pt_build/etervale/environment_v28/prepared_models',
                  tool_root/'pt_build/etervale/environment_v28/prepared_models']
    result['lod_cache'] = {'directories': [str(p) for p in lod_caches if p.is_dir()],
                            'prepared_model_folders': sum(len([x for x in p.iterdir() if x.is_dir()]) for p in lod_caches if p.is_dir())}
    for base in [tool_root/'app/pt_build/asset_compiler/bundles', tool_root/'pt_build/asset_compiler/bundles',
                 tool_root/'app/pt_build/deploy_bundles', tool_root/'pt_build/deploy_bundles']:
        if base.is_dir():
            for path in base.glob('**/transaction.json'):
                data = safe_json(path)
                files = data.get('files', [])
                if not isinstance(files, list):
                    continue
                touches_stage = any(relative.as_posix().casefold() == str(row.get('path') or row.get('relative_path') or '').casefold() for row in files if isinstance(row, dict))
                result['transactions'].append({'path': str(path), 'state': data.get('state'), 'stage_target': touches_stage})
    result['transactions'] = sorted(result['transactions'], key=lambda item:item['path'])[-20:]
    if result['source'].get('status') != 'PASS':
        result['overall'] = 'BLOCKED_SOURCE_MISSING_OR_CHANGED'
    elif any(v.get('source_hash_matches') is False for v in result['blender'].values() if isinstance(v, dict) and 'source_hash_matches' in v):
        result['overall'] = 'REVIEW_METADATA_SOURCE_DRIFT'
    else:
        result['overall'] = 'SOURCE_PASS_RUNTIME_NOT_TESTED'
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, default=Path('.'))
    parser.add_argument('--game-root', type=Path, default=Path.home()/'Transferências/Etervale-git')
    parser.add_argument('--source-smd', type=Path, help='explicit path to original Stage 0.72')
    parser.add_argument('--map', default=EXPECTED_ASSET)
    args = parser.parse_args()
    report = inspect(args.tool_root.expanduser().resolve(), args.game_root.expanduser().resolve(), args.map, args.source_smd)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['overall'] == 'SOURCE_PASS_RUNTIME_NOT_TESTED' else 2

if __name__ == '__main__':
    raise SystemExit(main())
