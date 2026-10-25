"""Offline-only material map authoring and indicative parallax visualization.

A diffuse texture does not encode physical height. Inference by luminance is a
review-required approximation. Generated maps are NOT wired into PT shaders.
"""
from __future__ import annotations

from PIL import Image, ImageFilter
import numpy as np


def height_from_diffuse(image: Image.Image, *, blur: float = 1.0, contrast: float = 1.0) -> Image.Image:
    if blur < 0 or blur > 20 or not (0.1 <= contrast <= 4):
        raise ValueError('INVALID_HEIGHT_SETTINGS')
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32)
    gray = np.clip(rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), 0, 255)
    adjusted = np.clip((gray - 127.5) * contrast + 127.5, 0, 255).astype('uint8')
    h = Image.fromarray(adjusted)
    return h.filter(ImageFilter.GaussianBlur(blur)) if blur > 0 else h


def normals_from_height(height: Image.Image, *, strength: float = 2, wrap: bool = True, convention: str = 'directx') -> Image.Image:
    if not (0 < strength <= 20) or convention not in {'directx', 'opengl'}:
        raise ValueError('INVALID_NORMAL_SETTINGS')
    a = np.asarray(height.convert('L'), dtype=np.float32) / 255.0
    p = np.pad(a, 1, mode='wrap' if wrap else 'edge')
    # Conventional 3x3 Sobel finite-difference gradients, normalized by eight.
    dx = (p[:-2,2:] + 2*p[1:-1,2:] + p[2:,2:] - p[:-2,:-2] - 2*p[1:-1,:-2] - p[2:,:-2]) / 8
    dy = (p[2:,:-2] + 2*p[2:,1:-1] + p[2:,2:] - p[:-2,:-2] - 2*p[:-2,1:-1] - p[:-2,2:]) / 8
    nx, ny, nz = -dx*strength, -dy*strength, np.ones_like(dx)
    if convention == 'directx':
        ny = -ny
    length = np.sqrt(nx*nx + ny*ny + nz*nz)
    arr = np.stack((nx/length, ny/length, nz/length), axis=-1)
    return Image.fromarray(np.uint8(np.rint(np.clip((arr+1)*127.5,0,255))))


def renormalize_normals(image: Image.Image, *, invert_green: bool = False) -> Image.Image:
    a = (np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0)*2-1
    if invert_green:
        a[:,:,1] = -a[:,:,1]
    norm = np.linalg.norm(a, axis=2, keepdims=True)
    a = np.where(norm < 0.0001, np.array([0.,0.,1.]), a / np.maximum(norm,0.0001))
    return Image.fromarray(np.uint8(np.rint(np.clip((a+1)*127.5,0,255))))


def parallax_demo(image: Image.Image, height: Image.Image, *, max_shift: int = 12) -> Image.Image:
    """Simple oblique offset preview ONLY; not occlusion mapping or true 3D."""
    if not (0 <= max_shift <= 64):
        raise ValueError('INVALID_DEMO_SHIFT')
    src = np.asarray(image.convert('RGB'))
    h = np.asarray(height.convert('L'))
    ys, xs = np.indices(h.shape)
    shifted_x = np.clip(xs + np.rint((h.astype(np.float32)/255.0 - 0.5) * max_shift).astype(np.int32),0,h.shape[1]-1)
    return Image.fromarray(src[ys,shifted_x])
