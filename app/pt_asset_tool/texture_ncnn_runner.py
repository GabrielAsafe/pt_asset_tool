"""Isolated SHA-pinned NCNN/Vulkan 1x RGB inference for Material Lab.

The model is supplied by the user; nothing is downloaded or installed. This
runner must be invoked with a Python whose ABI matches the isolated NCNN wheel.
Never writes to the source texture or to the game client.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _publish_png(image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, suffix='.png', delete=False) as file:
            temporary = Path(file.name)
        image.save(temporary, format='PNG')
        os.replace(temporary, dest)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def infer(*, input_file: Path, output_file: Path, model_param: Path,
          model_bin: Path, expected_param_hash: str, expected_bin_hash: str,
          runtime_root: Path, gpu_id: int=0, tile: int=256, halo: int=24,
          cache_root: Path | None=None) -> dict:
    if input_file.expanduser().resolve() == output_file.expanduser().resolve():
        raise ValueError('INPUT_OUTPUT_MUST_BE_DIFFERENT')
    if not (32 <= tile <= 1024 and 0 <= halo < tile // 2):
        raise ValueError('INVALID_TILE_OR_HALO')
    if gpu_id < 0:
        raise ValueError('INVALID_GPU_ID')
    for path, wanted in ((model_param, expected_param_hash), (model_bin, expected_bin_hash)):
        if len(wanted) != 64 or any(c not in '0123456789abcdefABCDEF' for c in wanted):
            raise ValueError('MODEL_SHA256_REQUIRED')
        if not path.is_file() or sha256(path).lower() != wanted.lower():
            raise ValueError(f'MODEL_SHA256_MISMATCH: {path.name}')
    runtime_root = runtime_root.expanduser().resolve()
    if not runtime_root.is_dir():
        raise FileNotFoundError(f'NCNN_RUNTIME_MISSING: {runtime_root}')
    # Python ABI must match NCNN's CPython extension (3.11 on the user's setup).
    sys.path.insert(0, str(runtime_root))
    import numpy as np
    from PIL import Image
    import ncnn

    actual_module = Path(ncnn.__file__).resolve()
    if not actual_module.is_relative_to(runtime_root):
        raise RuntimeError('NCNN_IMPORTED_FROM_UNEXPECTED_RUNTIME')
    try:
        runtime_version = importlib.metadata.version('ncnn')
    except importlib.metadata.PackageNotFoundError:
        runtime_version = 'unidentified'

    count = ncnn.get_gpu_count()
    if gpu_id >= count:
        raise RuntimeError(f'NCNN_VULKAN_GPU_MISSING: selected {gpu_id}, count {count}')
    gpu_name = str(ncnn.get_gpu_info(gpu_id).device_name())
    if any(x in gpu_name.lower() for x in ('llvmpipe', 'lavapipe', 'softpipe', 'swiftshader')):
        raise RuntimeError(f'VULKAN_SOFTWARE_DEVICE_BLOCKED: {gpu_name}')

    with Image.open(input_file) as original:
        image = original.convert('RGB')
        image.load()
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError('INVALID_IMAGE_DIMENSIONS')
    array = np.asarray(image, dtype=np.uint8)
    # Reflect padding matches the validated 2048x2048 GPU pilot.
    pad_mode = 'reflect' if min(width, height) > 1 else 'edge'
    padded = np.pad(array, ((halo, halo), (halo, halo), (0, 0)), mode=pad_mode)
    composed = Image.new('RGB', (width, height))

    fingerprint = {'source_sha256': sha256(input_file),
                   'param_sha256': expected_param_hash.lower(),
                   'bin_sha256': expected_bin_hash.lower(),
                   'tile': tile, 'halo': halo, 'scale': 1,
                   'border_mode': pad_mode, 'runtime_version': runtime_version,
                   'runtime_path': str(actual_module), 'gpu_id': gpu_id}
    cache_dir = None
    if cache_root is not None:
        cache_root = cache_root.expanduser().resolve()
        cache_id = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode('utf-8')).hexdigest()
        cache_dir = cache_root / cache_id
        if not cache_dir.resolve().is_relative_to(cache_root):
            raise ValueError('CACHE_SYMLINK_OUTSIDE_ROOT_BLOCKED')
        cache_dir.mkdir(parents=True, exist_ok=True)

    net = ncnn.Net()
    net.opt.use_vulkan_compute = True
    net.set_vulkan_device(gpu_id)
    if net.load_param(str(model_param)) != 0:
        raise RuntimeError('NCNN_PARAM_LOAD_FAILED')
    if net.load_model(str(model_bin)) != 0:
        raise RuntimeError('NCNN_BIN_LOAD_FAILED')
    total = ((width + tile - 1) // tile) * ((height + tile - 1) // tile)
    count_done = 0
    reused = 0
    started = time.monotonic()
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            w, h = min(tile, width-x), min(tile, height-y)
            cached = cache_dir / f'tile_{y:05d}_{x:05d}.png' if cache_dir else None
            sidecar = cached.with_suffix('.sha256') if cached else None
            tile_image = None
            if cached and cached.is_file() and sidecar.is_file():
                try:
                    if sha256(cached) == sidecar.read_text(encoding='ascii').strip():
                        with Image.open(cached) as saved:
                            saved.load()
                            if saved.mode == 'RGB' and saved.size == (w, h):
                                tile_image = saved.copy()
                                reused += 1
                except (OSError, ValueError):
                    pass
            if tile_image is None:
                region = np.ascontiguousarray(padded[y:y+h+2*halo, x:x+w+2*halo], dtype=np.uint8)
                patch_h, patch_w = region.shape[:2]
                mat = ncnn.Mat.from_pixels(region, ncnn.Mat.PixelType.PIXEL_RGB, patch_w, patch_h)
                mat.substract_mean_normalize([], [1 / 255, 1 / 255, 1 / 255])
                extractor = net.create_extractor()
                if extractor.input('in0', mat) != 0:
                    raise RuntimeError(f'NCNN_INPUT_FAILED: {x},{y}')
                code, result_mat = extractor.extract('out0')
                if code != 0:
                    raise RuntimeError(f'NCNN_OUTPUT_FAILED: {x},{y}, error={code}')
                result = np.array(result_mat, copy=True)
                if result.shape != (3, patch_h, patch_w) or not np.isfinite(result).all():
                    raise RuntimeError(f'NCNN_1X_OUTPUT_SHAPE_OR_NAN: {x},{y} {result.shape}')
                del result_mat
                del mat
                extractor.clear()
                del extractor
                center = result[:, halo:halo+h, halo:halo+w]
                pixels = np.rint(np.clip(center.transpose(1, 2, 0), 0, 1) * 255).astype(np.uint8)
                tile_image = Image.fromarray(pixels)
                if cached:
                    _publish_png(tile_image, cached)
                    # On interruption, an absent or stale checksum forces a recalculation.
                    tmp_sidecar = None
                    try:
                        with tempfile.NamedTemporaryFile(mode='w', encoding='ascii',
                                                         dir=cache_dir, suffix='.sha256.tmp',
                                                         delete=False) as file:
                            tmp_sidecar = Path(file.name)
                            file.write(sha256(cached))
                        os.replace(tmp_sidecar, sidecar)
                    finally:
                        if tmp_sidecar:
                            tmp_sidecar.unlink(missing_ok=True)
            composed.paste(tile_image, (x, y))
            count_done += 1
            print(f'NCNN_TILE={count_done}/{total} reused={reused}', flush=True)
    net.clear()
    del net
    if composed.size != image.size:
        raise RuntimeError('AI_RESTORER_CHANGED_DIMENSIONS_UPSCALE_FORBIDDEN')
    _publish_png(composed, output_file)
    return {'backend': 'ncnn_vulkan', 'scale': 1, 'size': [width, height],
            'gpu': gpu_name, 'tiles': count_done, 'tiles_reused': reused,
            'runtime': runtime_version, 'elapsed_seconds': round(time.monotonic()-started, 3)}


def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description='SHA-pinned NCNN Vulkan 1x Material Lab runner')
    for name in ('input', 'output', 'model-param', 'model-bin', 'runtime-root'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--sha256-bin', required=True)
    parser.add_argument('--gpu-id', type=int, default=0)
    parser.add_argument('--tile', type=int, default=256)
    parser.add_argument('--halo', type=int, default=24)
    parser.add_argument('--cache-root', type=Path)
    args = parser.parse_args(argv)
    data = infer(input_file=args.input, output_file=args.output, model_param=args.model_param,
                 model_bin=args.model_bin, expected_param_hash=args.sha256,
                 expected_bin_hash=args.sha256_bin, runtime_root=args.runtime_root,
                 gpu_id=args.gpu_id, tile=args.tile, halo=args.halo, cache_root=args.cache_root)
    print(json.dumps(data, ensure_ascii=False), flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
