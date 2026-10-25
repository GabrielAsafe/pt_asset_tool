"""Optional isolated 1x ESRGAN/Spandrel image-to-image adapter.

No model weights are bundled. Never loads a .pth without caller-provided SHA256,
Torch >= 2.6 and a local Spandrel runtime. This module is a subprocess target:
resource-heavy third-party AI never runs in the GUI server process.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path


def infer(input_file: Path, output_file: Path, model: Path, expected_hash: str, *, tile: int = 256, halo: int = 24, device: str = "cpu") -> dict:
    import numpy as np
    from PIL import Image
    import torch
    from spandrel import ModelLoader
    from packaging.version import Version
    if Version(torch.__version__.split('+')[0]) < Version('2.6'):
        raise RuntimeError('torch>=2.6 required for safe weights-only .pth loading')
    if not model.is_file():
        raise FileNotFoundError(model)
    actual = hashlib.sha256(model.read_bytes()).hexdigest()
    if actual.lower() != expected_hash.lower() or len(expected_hash) != 64:
        raise ValueError('MODEL_SHA256_MISMATCH')
    if tile < 32 or tile > 2048 or not (0 <= halo < tile // 2):
        raise ValueError('INVALID_TILE_OR_HALO')
    # Spandrel determines architecture. Only run single-image RGB 1x models.
    descriptor = ModelLoader().load_from_file(str(model))
    if int(descriptor.scale) != 1:
        raise ValueError(f'MODEL_SCALE_MUST_BE_1X: {descriptor.scale}')
    descriptor = descriptor.to(device).eval()
    source = Image.open(input_file).convert('RGB')
    arr = np.asarray(source, dtype=np.float32) / 255.0
    dest = np.empty_like(arr)
    height, width = arr.shape[:2]
    with torch.inference_mode():
        for y in range(0, height, tile):
            for x in range(0, width, tile):
                x0, y0 = max(0, x - halo), max(0, y - halo)
                x1, y1 = min(width, x + tile + halo), min(height, y + tile + halo)
                chunk = np.ascontiguousarray(arr[y0:y1, x0:x1, :].transpose(2, 0, 1))
                tensor = torch.from_numpy(chunk).unsqueeze(0).to(device)
                pred = descriptor(tensor)
                if isinstance(pred, (list, tuple)):
                    pred = pred[0]
                out = pred.detach().clamp(0, 1).float().cpu().numpy()
                if out.shape != (1, 3, y1-y0, x1-x0):
                    raise RuntimeError(f'RESTORER_SHAPE_MISMATCH: {out.shape}')
                out = out[0].transpose(1, 2, 0)
                dest[y:min(y+tile,height), x:min(x+tile,width)] = out[y-y0:min(y+tile,height)-y0, x-x0:min(x+tile,width)-x0]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.uint8(np.rint(dest * 255)), 'RGB').save(output_file, format='PNG')
    return {'backend': 'spandrel', 'model_sha256': actual, 'scale': 1, 'size': list(source.size), 'tile': tile, 'halo': halo}


def main(argv=None):
    p = argparse.ArgumentParser(description='Run SHA-pinned, 1x ESRGAN / Spandrel RGB restoration')
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--model', required=True, type=Path)
    p.add_argument('--sha256', required=True)
    p.add_argument('--tile', type=int, default=256)
    p.add_argument('--halo', type=int, default=24)
    p.add_argument('--device', default='cpu', choices=('cpu','cuda','mps'))
    a=p.parse_args(argv)
    print(infer(a.input,a.output,a.model,a.sha256,tile=a.tile,halo=a.halo,device=a.device))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
