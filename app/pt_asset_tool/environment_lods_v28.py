"""V28 prepared asset cache: source-hash locked, geometry-only, no game publication.

Pure standard-library module. All heavy mesh computation runs in a separate
Blender process launched from the project's *host* Python CLI, never in the
map's interactive Blender scene.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

from pt_asset_tool.environment_library_v26 import model_entries, prepare_model
from pt_asset_tool.lod_planning_v28_1 import MAX_PASSES, assess_lod

FORMAT = 'PT_ETERVALE_PREPARED_MODEL_V28'
RECIPE_VERSION = 1
# Polygon targets are intentionally conservative for repeated vegetation.
LOD_BUDGETS = {'LOD0': 120_000, 'LOD1': 35_000, 'LOD2': 7_000}
# Bounding the size of the worker's input is a safety check, not an in-game budget.
MAX_SOURCE_VERTICES = 8_000_000
MAX_SOURCE_FACES = 10_000_000
MAX_SCENE_INSTANCES = 100
ROOT_REL = Path('app/pt_build/etervale/environment_v28/prepared_models')
ZIP_CACHE_REL = Path('app/pt_build/etervale/environment_v26/asset_cache')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _key(source_digest: str) -> str:
    if len(source_digest) != 64 or any(c not in '0123456789abcdef' for c in source_digest):
        raise ValueError('V28_SHA_INVALIDO')
    return f'{source_digest}-r{RECIPE_VERSION}'


def prepared_dir(cache_root: Path, source_digest: str) -> Path:
    return cache_root / _key(source_digest)


def validate_prepared(cache_root: Path, source: Path, lod: str = 'LOD1') -> tuple[Path, dict]:
    """Reject incomplete/stale/tampered cache rather than silently loading it."""
    if lod not in LOD_BUDGETS:
        raise ValueError('V28_LOD_INVALIDO')
    source = Path(source)
    digest = sha256_file(source)
    cache_root = Path(cache_root)
    if cache_root.is_symlink():
        raise ValueError('V28_CACHE_ROOT_SYMLINK_PROIBIDO')
    root = prepared_dir(cache_root, digest)
    if root.is_symlink():
        raise ValueError('V28_CACHE_DIRETORIO_SYMLINK_PROIBIDO')
    marker = root / 'manifest.json'
    if not marker.is_file() or marker.is_symlink():
        raise FileNotFoundError(f'V28_MODELO_NAO_PREPARADO:{source.name}; usar --prepare-model')
    data = json.loads(marker.read_text(encoding='utf-8'))
    if (data.get('format') != FORMAT or data.get('recipe_version') != RECIPE_VERSION or
        data.get('source_sha256') != digest or data.get('source_name') != source.name or
        data.get('publish_enabled') is not False or data.get('game_assets_modified') is not False or
        set(data.get('levels', {})) != set(LOD_BUDGETS)):
        raise ValueError('V28_CACHE_INCOMPATIVEL_OU_INCOMPLETA')
    info = data['levels'][lod]
    expected_file = f'{lod}.blend'
    if info.get('file') != expected_file or info.get('budget_faces') != LOD_BUDGETS[lod]:
        raise ValueError('V28_CACHE_MANIFESTO_INVALIDO')
    filename = root / expected_file
    if not filename.is_file() or filename.is_symlink():
        raise ValueError('V28_CACHE_FICHEIRO_AUSENTE')
    if not isinstance(info.get('faces'), int) or info['faces'] <= 0 or info['faces'] > LOD_BUDGETS[lod] * 1.5:
        raise ValueError('V28_CACHE_LOD_EXCESSIVO')
    if not isinstance(info.get('vertices'), int) or info['vertices'] <= 0:
        raise ValueError('V28_CACHE_VERTICES_INVALIDOS')
    # Old V28 caches have no quality/passes; accept them if their face counts
    # still satisfy the original strict 150% safety ceiling.
    computed_quality = assess_lod(info['faces'], LOD_BUDGETS[lod])
    if info.get('quality', computed_quality) != computed_quality:
        raise ValueError('V28_CACHE_QUALITY_INCONSISTENTE')
    if 'passes' in info and (not isinstance(info['passes'], int) or
                             not 0 <= info['passes'] <= MAX_PASSES):
        raise ValueError('V28_CACHE_PASSAGENS_INVALIDAS')
    if sha256_file(filename) != info.get('sha256'):
        raise ValueError('V28_CACHE_SHA256_INVALIDO')
    return filename, data


def blender_command(command: str | None = None) -> list[str]:
    """Discover CLI outside Flatpak; allow explicit override without shell."""
    if command:
        args = shlex.split(command)
        if not args:
            raise ValueError('V28_COMANDO_BLENDER_VAZIO')
        return args
    if shutil.which('flatpak') is not None:
        info = subprocess.run(['flatpak', 'info', 'org.blender.Blender'],
                              capture_output=True, text=True, timeout=12, check=False)
        if info.returncode == 0:
            return ['flatpak', 'run', 'org.blender.Blender']
    if shutil.which('blender'):
        return ['blender']
    raise RuntimeError('V28_BLENDER_NAO_ENCONTRADO: usar --blender-command')


def _read_worker_report(path: Path) -> dict:
    result = json.loads(path.read_text(encoding='utf-8'))
    if result.get('format') != 'PT_ETERVALE_LOD_WORKER_V28' or set(result.get('levels', {})) != set(LOD_BUDGETS):
        raise ValueError('V28_WORKER_RELATORIO_INVALIDO')
    if not isinstance(result.get('source_vertices'), int) or result['source_vertices'] <= 0:
        raise ValueError('V28_WORKER_SEM_VERTICES')
    if not isinstance(result.get('source_faces'), int) or result['source_faces'] <= 0:
        raise ValueError('V28_WORKER_SEM_FACES')
    if not isinstance(result.get('height'), (float, int)) or not 0 < result['height'] < 1e8:
        raise ValueError('V28_WORKER_ALTURA_INVALIDA')
    for lod, budget in LOD_BUDGETS.items():
        record = result['levels'][lod]
        if (not isinstance(record.get('faces'), int) or not 0 < record['faces'] <= budget * 1.5 or
            not isinstance(record.get('vertices'), int) or record['vertices'] <= 0):
            raise ValueError(f'V28_WORKER_LOD_INVALIDO:{lod}')
        quality = assess_lod(record['faces'], budget)
        if quality == 'REJECT' or record.get('quality', quality) != quality:
            raise ValueError(f'V28_WORKER_QUALITY_INCONSISTENTE:{lod}')
        passes = record.get('passes', 0)  # V28 worker reports have no passes.
        if not isinstance(passes, int) or not 0 <= passes <= MAX_PASSES:
            raise ValueError(f'V28_WORKER_PASSAGENS_INVALIDAS:{lod}')
    return result


def build_manifest(*, source: Path, source_sha: str, worker_result: dict,
                   staged_dir: Path) -> dict:
    """Only build after worker returned bounded LODs and files actually exist."""
    levels: dict[str, Any] = {}
    for name, budget in LOD_BUDGETS.items():
        file = staged_dir / f'{name}.blend'
        if not file.is_file() or file.is_symlink() or not file.stat().st_size:
            raise ValueError(f'V28_LOD_AUSENTE:{name}')
        record = worker_result['levels'][name]
        levels[name] = {
            'file': f'{name}.blend', 'budget_faces': budget,
            'vertices': record['vertices'], 'faces': record['faces'],
            'quality': assess_lod(record['faces'], budget),
            'passes': record.get('passes', 0),
            'sha256': sha256_file(file),
        }
    return {
        'format': FORMAT, 'recipe_version': RECIPE_VERSION,
        'source_name': source.name, 'source_sha256': source_sha,
        'source_vertices': worker_result['source_vertices'],
        'source_faces': worker_result['source_faces'],
        'mesh_parts': worker_result['mesh_parts'],
        'height': worker_result['height'],
        'missing_textures': worker_result.get('missing_textures', []),
        'levels': levels,
        'publish_enabled': False, 'game_assets_modified': False,
        'source_modified': False, 'runtime_certified': False,
    }


def prepare_asset(*, name: str, project_root: Path, blender: str | None = None,
                  dry_run: bool = False, timeout_seconds: int = 1200) -> dict:
    """Prepare one whitelisted model: unpack read-only, run background Blender.

    Files are staged under pt_build and atomically committed only on complete
    success. Existing nonmatching cache entries are preserved and refused.
    """
    root = Path(project_root).resolve()
    library = root / 'AssetsForAutomaticSubstitution'
    choices = {e.name: e for e in model_entries(library)}
    if name not in choices:
        raise ValueError(f'V28_MODELO_NAO_E_ARVORE_NA_BIBLIOTECA:{name}')
    source = Path(choices[name].path)
    source_sha = sha256_file(source)
    cache_root = root / ROOT_REL
    destination = prepared_dir(cache_root, source_sha)
    if destination.is_dir():
        for lod in LOD_BUDGETS:
            validate_prepared(cache_root, source, lod)
        return {'status': 'JA_PREPARADO', 'name': name, 'path': str(destination)}
    if destination.exists() or destination.is_symlink():
        raise ValueError('V28_CACHE_EXISTENTE_INCOMPATIVEL_NAO_REESCRITO')
    if cache_root.is_symlink():
        raise ValueError('V28_CACHE_ROOT_SYMLINK_PROIBIDO')
    command = blender_command(blender)
    if dry_run:
        return {'status': 'DRY_RUN', 'name': name, 'blender_command': command,
                'cache_destination': str(destination)}
    unpacked = prepare_model(source, library, root / ZIP_CACHE_REL)
    cache_root.mkdir(parents=True, exist_ok=True)
    if cache_root.is_symlink():
        raise ValueError('V28_CACHE_ROOT_SYMLINK_PROIBIDO')
    staging = Path(tempfile.mkdtemp(prefix='.v28_prepare_', dir=cache_root))
    worker = root / 'app/pt_asset_tool/blender/environment_prepare_worker_v28.py'
    try:
        cmd = command + [
            '--background', '--factory-startup', '--threads', '2', '--python-exit-code', '13',
            '--python', str(worker), '--', '--input', str(unpacked),
            '--output', str(staging), '--result', str(staging/'worker_result.json'),
        ]
        print(f'PT_V28_WORKER=START source={name} background=true', flush=True)
        process = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, check=False, timeout=timeout_seconds)
        # Do not flood the terminal with Blender logs from dense meshes.
        if process.returncode != 0:
            tail = (process.stdout or '')[-6000:]
            raise RuntimeError(f'V28_BLENDER_WORKER_FAIL:rc={process.returncode}\n{tail}')
        worker_result = _read_worker_report(staging/'worker_result.json')
        manifest = build_manifest(source=source, source_sha=source_sha,
                                  worker_result=worker_result, staged_dir=staging)
        (staging/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False,
                                             indent=2, sort_keys=True) + '\n', encoding='utf-8')
        # Recheck user-owned source after the long-running background process.
        if sha256_file(source) != source_sha:
            raise ValueError('V28_SOURCE_CHANGED_DURING_PREPARATION')
        if destination.exists() or destination.is_symlink():
            raise ValueError('V28_CACHE_CRIADA_POR_OUTRO_PROCESSO')
        os.rename(staging, destination)  # same FS; never overwrite validated work
        return {'status':'PREPARADO', 'name':name, 'path':str(destination),
                'source_vertices':manifest['source_vertices'],
                'levels':manifest['levels'],
                'missing_textures':manifest['missing_textures']}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
