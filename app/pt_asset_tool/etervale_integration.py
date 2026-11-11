"""Etervale unified-source bridge.

All C# tools remain in the game repository and are invoked in their own build
context. Operations are read-only on the game assets. GLB outputs and validation
reports live under the Asset Tool's private pt_build/etervale directory.

This module does NOT claim that glTF or historical Summit packs are loadable by
Etervale's game runtime. Parsing success != visual/runtime certification.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import uuid
from collections import Counter
from typing import Any

from .app_config import configured_etervale_root, validate_etervale_root
from .runtime_paths import bundle_root, external_process_env, persistent_pt_build, is_frozen

PROJ = {
    'inspect': 'PristonTale.AssetDump',
    'export-glb': 'PristonTale.GltfExport',
}
CS_AREAS = ('Client', 'Server', 'Shared', 'Persistence', 'tools', 'scripts')
CS_EXCLUDED = {'.git', 'bin', 'obj', '.vs', '__pycache__', 'node_modules', 'vendor', 'packages'}
ASSET_TYPES = {'.smd', '.smb', '.inx', '.bmp', '.tga'}
GLB_INPUT_TYPES = {'.smd', '.smb', '.inx'}
CSharp_MARKERS = (
    'PristonSmdReader', 'PristonInxReader', 'StageCollisionReader',
    'PristonActorLoader', 'GltfSceneExport', 'SharpGLTF',
    '.smd', '.smb', '.inx', '.glb', '.gltf', '.part', '.spm',
)


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    return path == root or root in path.parents


def _game_root(a: Any) -> pathlib.Path:
    candidate = getattr(a, 'repo_root', None) or configured_etervale_root(bundle_root())
    if candidate is None:
        raise ValueError('ETERVALE_ROOT_NOT_CONFIGURED:run config set-etervale-root PATH or pass --repo-root')
    return validate_etervale_root(candidate)


def _work_root() -> pathlib.Path:
    return persistent_pt_build() / 'etervale'


def _candidate_staging_roots() -> tuple[pathlib.Path, ...]:
    """Accept both historical project-root staging and app-root staging.

    Both are owned by Asset Tool; the game's asset tree is never eligible.
    """
    roots = [persistent_pt_build().resolve()]
    if not is_frozen():
        legacy = (bundle_root().parent / 'pt_build').resolve()
        if legacy not in roots:
            roots.append(legacy)
    return tuple(roots)


def _which_candidate_root(path: pathlib.Path) -> pathlib.Path | None:
    return next((root for root in _candidate_staging_roots() if _within(path, root)), None)


def _private_output(relative: str, *, suffix: str) -> pathlib.Path:
    raw = pathlib.Path(relative)
    if raw.is_absolute() or '..' in raw.parts or raw.suffix.lower() != suffix:
        raise ValueError('OUTPUT_MUST_BE_RELATIVE_UNDER_PT_BUILD_ETERVALE')
    result = (_work_root() / raw).resolve()
    if not _within(result, _work_root().resolve()):
        raise ValueError('OUTPUT_PATH_ESCAPES_PRIVATE_STAGING')
    if result.exists() or result.is_symlink():
        raise FileExistsError(f'OUTPUT_ALREADY_EXISTS:{result}')
    return result


def _input_path(root: pathlib.Path, asset: str | None, candidate: str | None, allowed: set[str]) -> pathlib.Path:
    if bool(asset) == bool(candidate):
        raise ValueError('CHOOSE_EXACTLY_ONE_OF_ASSET_OR_CANDIDATE')
    if asset:
        # Asset must be a game-root/assets/-relative path. Never allow any
        # symlink traversal to reach private source, config, or system files.
        asset_root = (root / 'assets').resolve(strict=True)
        requested = pathlib.Path(asset)
        if requested.is_absolute() or '..' in requested.parts:
            raise ValueError('ASSET_MUST_BE_RELATIVE_TO_ETERVALE_ASSETS')
        selected = (asset_root / requested).resolve(strict=True)
        if not _within(selected, asset_root):
            raise ValueError('ASSET_OUTSIDE_ETERVALE_ASSETS')
    else:
        requested = pathlib.Path(candidate).expanduser()
        selected = requested.resolve(strict=True)
        if _which_candidate_root(selected) is None:
            raise ValueError('CANDIDATE_MUST_BE_UNDER_ASSET_TOOL_PT_BUILD')
    if not selected.is_file():
        raise ValueError(f'ASSET_NOT_FILE:{selected}')
    if selected.suffix.lower() not in allowed:
        raise ValueError(f'ASSET_UNSUPPORTED_EXTENSION:{selected.suffix}')
    return selected


def _hash_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _csproj(game_root: pathlib.Path, command: str) -> pathlib.Path:
    name = PROJ[command]
    candidate = game_root / 'tools' / name / (name + '.csproj')
    if not candidate.is_file():
        raise FileNotFoundError(f'ETERVALE_CSHARP_TOOL_NOT_FOUND:{candidate}')
    return candidate


def _print(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=False, indent=2))


def status(a: Any) -> int:
    root = _game_root(a)
    roles = {
        'assets': 'assets',
        'server_data': 'assets/GameServer',
        'client_source': 'Client',
        'server_source': 'Server',
        'shared_source': 'Shared',
        'persistence': 'Persistence',
        'tools': 'tools',
        'scripts': 'scripts',
        'blender_workspace': '3d_glb/blender',
        'documentation': 'docs',
    }
    role_status = {key: {'path': str(root / rel), 'exists': (root / rel).is_dir()}
                   for key, rel in roles.items()}
    tools = {key: {'project': str(_csproj(root, key)), 'source_owned_by': 'ETERVALE'}
             for key in PROJ}
    _print({
        'format': 'PT_ASSET_ETERVALE_BRIDGE_V1',
        'status': 'READY_TO_VALIDATE' if role_status['server_data']['exists'] else 'PARTIAL_MISSING_GAMESERVER',
        'game_root': str(root), 'roles': role_status, 'csharp_tools': tools,
        'dotnet_available': bool(shutil.which('dotnet')),
        'glb_runtime_loading': 'NOT_ESTABLISHED:the current Etervale implementation exports GLB; its active readers consume SMD/SMB/INX',
        'summit_packs_runtime_loading': 'NOT_ESTABLISHED',
        'legacy_c_cpp_contracts': 'ISOLATED_FROM_CSHARP_SCAN',
        'staging_directory': str(_work_root()),
        'game_assets_modified': False,
    })
    return 0


def audit_source(a: Any) -> int:
    root = _game_root(a)
    counts: dict[str, int] = {}
    marker_count: Counter[str] = Counter()
    samples: dict[str, list[str]] = {term: [] for term in CSharp_MARKERS}
    errors = []
    total = 0
    for area in CS_AREAS:
        path = root / area
        if not path.is_dir():
            counts[area] = 0
            continue
        found = 0
        for current, dirs, files in os.walk(path):
            dirs[:] = sorted((d for d in dirs if d.casefold() not in CS_EXCLUDED), key=str.casefold)
            for filename in sorted(files, key=str.casefold):
                if not filename.lower().endswith('.cs'):
                    continue
                found += 1
                total += 1
                fp = pathlib.Path(current) / filename
                try:
                    # A textual census, not proof of executable references.
                    data = fp.read_text(encoding='utf-8-sig', errors='replace')
                except OSError as exc:
                    errors.append({'path': str(fp), 'error': str(exc)})
                    continue
                for marker in CSharp_MARKERS:
                    occurrences = data.casefold().count(marker.casefold())
                    if occurrences:
                        marker_count[marker] += occurrences
                        if len(samples[marker]) < 8:
                            samples[marker].append(fp.relative_to(root).as_posix())
        counts[area] = found
    report = {
        'format': 'PT_ASSET_ETERVALE_CSHARP_CENSUS_V1',
        'status': 'PASS' if not errors else 'PARTIAL',
        'game_root': str(root), 'total_csharp_files': total,
        'files_by_tree': counts,
        'textual_markers': {name: {'occurrences': marker_count[name], 'sample_files': samples[name]}
                            for name in CSharp_MARKERS},
        'read_errors': errors[:50],
        'proof_level': 'TEXTUAL_CENSUS_ONLY:includes_comments_and_tests;not_proof_of_runtime_dependency',
        'legacy_contract_scanner': 'UNMODIFIED_C_CPP_ONLY',
        'game_assets_modified': False,
    }
    if a.report:
        target = _private_output('reports/' + str(a.report), suffix='.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        report['report_file'] = str(target)
    _print(report)
    return 0 if not errors else 3


def _run_game_tool(
    root: pathlib.Path, project: pathlib.Path, args: list[str], *,
    build: bool, extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not shutil.which('dotnet'):
        raise FileNotFoundError('DOTNET_NOT_INSTALLED')
    env = external_process_env()
    if extra_env:
        env.update(extra_env)
    actions = []
    if build:
        build_cmd = ['dotnet', 'build', str(project), '-c', 'Release', '-m:1']
        b = subprocess.run(build_cmd, cwd=root, env=env, capture_output=True, text=True, check=False)
        actions.append({'command': build_cmd, 'exit_code': b.returncode,
                        'stdout_tail': b.stdout[-8000:], 'stderr_tail': b.stderr[-8000:]})
        if b.returncode:
            return {'exit_code': b.returncode, 'steps': actions}
    run_cmd = ['dotnet', 'run', '--project', str(project), '-c', 'Release', '--no-build', '--', *args]
    run = subprocess.run(run_cmd, cwd=root, env=env, capture_output=True, text=True, check=False)
    actions.append({'command': run_cmd, 'exit_code': run.returncode,
                    'stdout_tail': run.stdout[-12000:], 'stderr_tail': run.stderr[-12000:]})
    return {'exit_code': run.returncode, 'steps': actions}


def _write_report(subdir: str, record: dict[str, Any]) -> str:
    rel = f'{subdir}/{uuid.uuid4().hex}.json'
    path = _private_output(rel, suffix='.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return str(path)


def validate_asset(a: Any) -> int:
    root = _game_root(a)
    source = _input_path(root, a.asset, a.candidate, ASSET_TYPES)
    project = _csproj(root, 'inspect')
    flags = []
    if a.full:
        flags.append('--full')
    cmd = ['dotnet', 'run', '--project', str(project), '-c', 'Release', '--no-build', '--', str(source), *flags]
    data: dict[str, Any] = {
        'format': 'PT_ASSET_ETERVALE_ASSETDUMP_VALIDATION_V1',
        'game_root': str(root), 'file': str(source), 'original_sha256': _hash_file(source),
        'tool': 'PristonTale.AssetDump', 'command': cmd,
        'execute': bool(a.execute), 'build_requested': bool(a.build),
        'proof_level': 'CSHARP_READER_ACCEPTANCE_ONLY:NOT_RUNTIME_VISUAL_CERTIFICATION',
        'game_assets_modified': False,
    }
    if not a.execute:
        data['status'] = 'PLANNED_NOT_EXECUTED'
        _print(data)
        return 0
    outcome = _run_game_tool(root, project, [str(source), *flags], build=bool(a.build))
    data.update(outcome)
    data['source_unchanged'] = _hash_file(source) == data['original_sha256']
    data['status'] = 'READER_ACCEPTED' if outcome['exit_code'] == 0 and data['source_unchanged'] else 'FAILED'
    data['report_file'] = _write_report('validation', data)
    _print(data)
    return 0 if data['status'] == 'READER_ACCEPTED' else 3


def export_glb(a: Any) -> int:
    root = _game_root(a)
    source = _input_path(root, a.asset, a.candidate, GLB_INPUT_TYPES)
    project = _csproj(root, 'export-glb')
    relative = a.output or ('glb/' + source.stem + '-' + uuid.uuid4().hex[:10] + '.glb')
    dest = _private_output(relative, suffix='.glb')
    argv = [str(source), str(dest)]
    if source.suffix.casefold() == '.inx':
        argv += ['--asset-root', str(root / 'assets')]
    plan: dict[str, Any] = {
        'format': 'PT_ASSET_ETERVALE_GLTF_EXPORT_V1',
        'game_root': str(root), 'asset': str(source), 'source_sha256': _hash_file(source),
        'output': str(dest), 'tool': 'PristonTale.GltfExport',
        'command': ['dotnet', 'run', '--project', str(project), '-c', 'Release', '--no-build', '--', *argv],
        'execute': bool(a.execute), 'build_requested': bool(a.build),
        'strict_textures': bool(a.strict_textures),
        'proof_level': 'GLB_EXPORT_NOT_GAME_RUNTIME_COMPATIBILITY',
        'game_assets_modified': False,
    }
    if not a.execute:
        plan['status'] = 'PLANNED_NOT_EXECUTED'
        _print(plan)
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The native exporter already emits exact fallback texture names and reasons
    # when PTGLTF_DEBUG=1. Capture this evidence without modifying C# sources.
    outcome = _run_game_tool(root, project, argv, build=bool(a.build),
                             extra_env={'PTGLTF_DEBUG': '1'})
    plan.update(outcome)
    trace = '\n'.join(str(step.get('stderr_tail', '')) for step in outcome['steps'])
    summary = '\n'.join(str(step.get('stdout_tail', '')) for step in outcome['steps'])
    fallbacks = []
    for line in trace.splitlines():
        match = re.match(r"\s*texture fallback: '(.*)' \((.*)\)\s*$", line)
        if match:
            fallbacks.append({'name': match.group(1), 'reason': match.group(2)})
    match = re.search(r'(\d+) textures \((\d+) missing or invalid\)', summary)
    missing = int(match.group(2)) if match else None
    plan['exported_texture_count'] = int(match.group(1)) if match else None
    plan['missing_or_invalid_texture_count'] = missing
    plan['texture_fallbacks'] = fallbacks
    plan['texture_trace_complete'] = missing is not None and len(fallbacks) == missing
    plan['texture_diagnostic_status'] = (
        'UNKNOWN' if missing is None else
        'COMPLETE' if missing == 0 else
        'FALLBACKS_IDENTIFIED' if plan['texture_trace_complete'] else
        'PARTIAL_TRACE'
    )
    # Basic GLB container proof: magic/version/declared size (not visual proof).
    valid_glb = False
    if dest.is_file() and dest.stat().st_size >= 12:
        with dest.open('rb') as stream:
            signature, version, length = struct.unpack('<4sII', stream.read(12))
        valid_glb = signature == b'glTF' and version == 2 and length == dest.stat().st_size
    plan['valid_glb_v2_container'] = valid_glb
    plan['source_unchanged'] = _hash_file(source) == plan['source_sha256']
    plan['output_sha256'] = _hash_file(dest) if dest.is_file() else None
    successful_export = outcome['exit_code'] == 0 and valid_glb and plan['source_unchanged']
    if not successful_export:
        plan['status'] = 'FAILED'
    elif a.strict_textures and missing is None:
        plan['status'] = 'FAILED_TEXTURE_COVERAGE_UNKNOWN'
    elif a.strict_textures and missing > 0:
        plan['status'] = 'FAILED_TEXTURE_FALLBACKS'
    else:
        plan['status'] = 'EXPORTED_NOT_RUNTIME_CERTIFIED'
    plan['report_file'] = _write_report('exports', plan)
    _print(plan)
    return 0 if plan['status'] == 'EXPORTED_NOT_RUNTIME_CERTIFIED' else 3



def inspect_glb(a: Any) -> int:
    """Inspect the glTF 2.0 container and graph without running the game.

    This is stronger than a 12-byte header check, but remains structural
    evidence only: geometry, materials and gameplay must be tested separately.
    """
    selected = pathlib.Path(a.file).expanduser().resolve(strict=True)
    if not selected.is_file() or _which_candidate_root(selected) is None:
        raise ValueError('GLB_MUST_BE_UNDER_ASSET_TOOL_PT_BUILD')
    if selected.suffix.lower() != '.glb':
        raise ValueError('GLB_FILE_EXTENSION_REQUIRED')
    record: dict[str, Any] = {
        'format': 'PT_ASSET_ETERVALE_GLB_INSPECTION_V1',
        'file': str(selected), 'sha256': _hash_file(selected),
        'bytes': selected.stat().st_size,
        'proof_level': 'GLTF_CONTAINER_AND_REFERENCE_STRUCTURE_ONLY_NOT_RUNTIME_CERTIFICATION',
        'game_assets_modified': False,
    }
    errors: list[str] = []
    gltf: dict[str, Any] = {}
    chunks: list[dict[str, Any]] = []
    try:
        with selected.open('rb') as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise ValueError('TRUNCATED_GLB_HEADER')
            magic, version, declared = struct.unpack('<4sII', header)
            if magic != b'glTF' or version != 2 or declared != record['bytes']:
                raise ValueError('INVALID_GLB_MAGIC_VERSION_OR_LENGTH')
            offset = 12
            while offset < declared:
                raw_chunk = stream.read(8)
                if len(raw_chunk) != 8:
                    raise ValueError('TRUNCATED_CHUNK_HEADER')
                size, kind = struct.unpack('<II', raw_chunk)
                if size % 4 or offset + 8 + size > declared:
                    raise ValueError('INVALID_CHUNK_LENGTH_OR_PADDING')
                kind_name = 'JSON' if kind == 0x4e4f534a else 'BIN' if kind == 0x004e4942 else hex(kind)
                chunks.append({'type': kind_name, 'size': size})
                if len(chunks) == 1:
                    if kind_name != 'JSON' or size > 64 * 1024 * 1024:
                        raise ValueError('FIRST_CHUNK_MUST_BE_REASONABLE_JSON')
                    gltf = json.loads(stream.read(size).rstrip(b' \x00').decode('utf-8'))
                    if not isinstance(gltf, dict):
                        raise ValueError('JSON_ROOT_MUST_BE_OBJECT')
                else:
                    stream.seek(size, 1)
                offset += 8 + size
            if offset != declared:
                raise ValueError('CHUNKS_DO_NOT_COVER_DECLARED_LENGTH')
            if not chunks:
                raise ValueError('GLB_HAS_NO_JSON_CHUNK')
            if gltf.get('asset', {}).get('version') != '2.0':
                raise ValueError('NOT_GLTF_2_0_ASSET')
            if sum(c['type'] == 'BIN' for c in chunks) > 1:
                raise ValueError('MORE_THAN_ONE_BIN_CHUNK')
            arrays = {name: gltf.get(name, []) for name in (
                'scenes', 'nodes', 'meshes', 'materials', 'images', 'textures',
                'samplers', 'animations', 'skins', 'accessors', 'bufferViews', 'buffers',
            )}
            if any(not isinstance(value, list) for value in arrays.values()):
                raise ValueError('GLTF_COLLECTION_MUST_BE_ARRAY')
            def check_ref(value: Any, section: str, path: str) -> None:
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < len(arrays[section]):
                    errors.append(f'{path}:invalid_{section}_index={value}')
            for i, scene in enumerate(arrays['scenes']):
                for ref in scene.get('nodes', []):
                    check_ref(ref, 'nodes', f'scenes[{i}].nodes')
            if 'scene' in gltf:
                check_ref(gltf['scene'], 'scenes', 'scene')
            for i, node in enumerate(arrays['nodes']):
                for field in ('mesh', 'skin'):
                    if field in node:
                        check_ref(node[field], 'meshes' if field == 'mesh' else 'skins', f'nodes[{i}].{field}')
                for ref in node.get('children', []):
                    check_ref(ref, 'nodes', f'nodes[{i}].children')
            for i, mesh in enumerate(arrays['meshes']):
                for j, primitive in enumerate(mesh.get('primitives', [])):
                    for name, accessor in primitive.get('attributes', {}).items():
                        check_ref(accessor, 'accessors', f'meshes[{i}].primitives[{j}].{name}')
                    for field, section in (('indices', 'accessors'), ('material', 'materials')):
                        if field in primitive:
                            check_ref(primitive[field], section, f'meshes[{i}].primitives[{j}].{field}')
            for i, texture in enumerate(arrays['textures']):
                for field, section in (('source', 'images'), ('sampler', 'samplers')):
                    if field in texture:
                        check_ref(texture[field], section, f'textures[{i}].{field}')
            for i, image in enumerate(arrays['images']):
                if 'bufferView' in image:
                    check_ref(image['bufferView'], 'bufferViews', f'images[{i}].bufferView')
            for i, view in enumerate(arrays['bufferViews']):
                check_ref(view.get('buffer'), 'buffers', f'bufferViews[{i}].buffer')
            for i, accessor in enumerate(arrays['accessors']):
                if 'bufferView' in accessor:
                    check_ref(accessor['bufferView'], 'bufferViews', f'accessors[{i}].bufferView')
            if len(arrays['buffers']) == 1 and any(c['type'] == 'BIN' for c in chunks):
                length = arrays['buffers'][0].get('byteLength')
                actual = next(c['size'] for c in chunks if c['type'] == 'BIN')
                if not isinstance(length, int) or length > actual or actual - length > 3:
                    errors.append('BIN_CHUNK_LENGTH_MISMATCH')
            record['counts'] = {name: len(value) for name, value in arrays.items()}
            record['chunks'] = chunks
    except (ValueError, KeyError, UnicodeError, json.JSONDecodeError, OSError, TypeError, AttributeError) as exc:
        errors.append(f'{type(exc).__name__}:{exc}')
    record['errors'] = errors[:100]
    record['status'] = 'GLB_VALID_STRUCTURAL_ONLY' if not errors else 'GLB_INVALID_STRUCTURE'
    _print(record)
    return 0 if not errors else 3

def validate_batch(a: Any) -> int:
    """Validate an explicit list of staged candidates against real Etervale readers.

    This intentionally does not crawl output directories: only reviewed paths
    listed in a manifest are eligible for native parsing.
    """
    root = _game_root(a)
    manifest_file = pathlib.Path(a.manifest).expanduser().resolve(strict=True)
    manifest_staging = _which_candidate_root(manifest_file)
    if not manifest_file.is_file() or manifest_staging is None:
        raise ValueError('BATCH_MANIFEST_MUST_BE_UNDER_ASSET_TOOL_PT_BUILD')
    data = json.loads(manifest_file.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != 'PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1':
        raise ValueError('BAD_BATCH_MANIFEST_FORMAT')
    items = data.get('candidates')
    if not isinstance(items, list) or not 1 <= len(items) <= 500 or any(not isinstance(x, str) for x in items):
        raise ValueError('BATCH_MUST_LIST_1_TO_500_CANDIDATE_PATHS')
    if len(set(items)) != len(items):
        raise ValueError('DUPLICATE_BATCH_CANDIDATE')
    paths: list[pathlib.Path] = []
    for item in items:
        # Manifest relative paths are relative to the pt_build containing it.
        candidate = pathlib.Path(item).expanduser()
        candidate = candidate if candidate.is_absolute() else manifest_staging / candidate
        paths.append(_input_path(root, None, str(candidate), ASSET_TYPES))
    project = _csproj(root, 'inspect')
    results = [{'path': str(path), 'sha256': _hash_file(path), 'status': 'PENDING'} for path in paths]
    report: dict[str, Any] = {
        'format': 'PT_ASSET_ETERVALE_BATCH_VALIDATION_V1',
        'game_root': str(root), 'manifest': str(manifest_file),
        'candidates': results, 'count': len(results),
        'execute': bool(a.execute), 'build_requested': bool(a.build),
        'proof_level': 'CSHARP_READER_ACCEPTANCE_ONLY_NOT_RUNTIME_CERTIFICATION',
        'game_assets_modified': False,
    }
    if not a.execute:
        report['status'] = 'PLANNED_NOT_EXECUTED'
        _print(report)
        return 0
    failures = 0
    for index, path in enumerate(paths):
        result = _run_game_tool(root, project, [str(path)], build=bool(a.build) and index == 0)
        changed = _hash_file(path) != results[index]['sha256']
        results[index].update({'status': 'READER_ACCEPTED' if not result['exit_code'] and not changed else 'FAILED',
                               'source_unchanged': not changed, 'exit_code': result['exit_code'],
                               'steps': result['steps']})
        if results[index]['status'] != 'READER_ACCEPTED':
            failures += 1
        if a.build and index == 0 and result['exit_code']:
            # A build failure makes every subsequent run meaningless.
            for later in results[1:]:
                later['status'] = 'BLOCKED_BY_BUILD_FAILURE'
            failures += len(results) - 1
            break
    report['status'] = 'READER_ACCEPTED_ALL' if failures == 0 else 'FAILED_OR_BLOCKED'
    report['pass_count'] = sum(x['status'] == 'READER_ACCEPTED' for x in results)
    report['fail_or_block_count'] = failures
    report['report_file'] = _write_report('validation', report)
    _print(report)
    return 0 if failures == 0 else 3


def register_parser(subparsers: Any) -> None:
    family = subparsers.add_parser('etervale', help='unified Etervale project and native C# validation bridge')
    sp = family.add_subparsers(dest='etervale_command', required=True)
    x = sp.add_parser('status', help='inspect unified root without modifying Etervale')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.set_defaults(func=status)
    x = sp.add_parser('source-audit', help='C# source census independent from old C++ contracts')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.add_argument('--report', help='relative .json path under pt_build/etervale/reports')
    x.set_defaults(func=audit_source)
    x = sp.add_parser('validate', help='plan/run the real Etervale AssetDump reader on a game asset or staged candidate')
    x.add_argument('--repo-root', type=pathlib.Path)
    y = x.add_mutually_exclusive_group(required=True)
    y.add_argument('--asset', help='path relative to Etervale assets/')
    y.add_argument('--candidate', help='absolute path under Asset Tool pt_build/')
    x.add_argument('--full', action='store_true')
    x.add_argument('--execute', action='store_true', help='actually run the C# inspector')
    x.add_argument('--build', action='store_true', help='build the C# inspector first (requires --execute)')
    x.set_defaults(func=validate_asset)
    x = sp.add_parser('validate-batch', help='inspect up to 500 explicitly manifested staged SMD/SMB/INX/texture candidates')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.add_argument('--manifest', required=True, help='batch JSON under Asset Tool pt_build; candidates list')
    x.add_argument('--execute', action='store_true')
    x.add_argument('--build', action='store_true', help='build inspector once before validation')
    x.set_defaults(func=validate_batch)
    x = sp.add_parser('export-glb', help='plan/run the Etervale exporter; output under Asset Tool pt_build only')
    x.add_argument('--repo-root', type=pathlib.Path)
    y = x.add_mutually_exclusive_group(required=True)
    y.add_argument('--asset', help='path relative to Etervale assets/')
    y.add_argument('--candidate', help='absolute path under Asset Tool pt_build/')
    x.add_argument('--output', help='relative .glb path under pt_build/etervale')
    x.add_argument('--strict-textures', action='store_true',
                   help='fail verification if exporter used a texture fallback or could not report coverage')
    x.add_argument('--execute', action='store_true')
    x.add_argument('--build', action='store_true', help='build the exporter first (requires --execute)')
    x.set_defaults(func=export_glb)
    x = sp.add_parser('inspect-glb', help='validate GLB 2.0 chunk and reference structure in private staging')
    x.add_argument('--file', required=True, help='absolute path to a .glb under Asset Tool pt_build')
    x.set_defaults(func=inspect_glb)
    # P0/P1 integrations are individually installable after the P0 foundation.
    from .etervale_p0p1_plugins import register_extensions
    register_extensions(sp)
