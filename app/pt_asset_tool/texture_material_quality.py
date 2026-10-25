"""Conservative offline image quality witnesses for staged PT textures.

Metrics are diagnostic, not automatic artistic approval or shader certification.
Large textures are sampled to avoid excessive memory use in batch jobs.
"""
from __future__ import annotations

from PIL import Image, ImageChops
import numpy as np


def _sample(image: Image.Image, limit: int = 768) -> Image.Image:
    if max(image.size) <= limit:
        return image.convert('RGB')
    copy = image.convert('RGB')
    copy.thumbnail((limit, limit), Image.Resampling.NEAREST)
    return copy


def _borders(image: Image.Image) -> dict:
    rgb=image.convert('RGB')
    w,h=rgb.size
    if w < 2 or h < 2:
        return {'horizontal': None, 'vertical': None}
    l=np.asarray(rgb.crop((0,0,1,h)),dtype=np.int16)
    r=np.asarray(rgb.crop((w-1,0,w,h)),dtype=np.int16)
    top=np.asarray(rgb.crop((0,0,w,1)),dtype=np.int16)
    bottom=np.asarray(rgb.crop((0,h-1,w,h)),dtype=np.int16)
    return {'horizontal':round(float(np.mean(np.abs(l-r))),3),
            'vertical':round(float(np.mean(np.abs(top-bottom))),3)}


def assess(before: Image.Image, after: Image.Image) -> dict:
    if before.size != after.size:
        raise ValueError('QUALITY_CHECK_REQUIRES_IDENTICAL_DIMENSIONS')
    b = np.asarray(_sample(before), dtype=np.int16)
    a = np.asarray(_sample(after), dtype=np.int16)
    d = np.abs(a-b)
    changed = d.max(axis=2)>0
    before_edges,after_edges=_borders(before),_borders(after)
    alpha_preserved = (ImageChops.difference(before.getchannel('A'),after.getchannel('A')).getbbox() is None
                       if 'A' in before.getbands() and 'A' in after.getbands()
                       else ('A' not in before.getbands() and 'A' not in after.getbands()))
    return {
        'sampled_resolution': [int(b.shape[1]),int(b.shape[0])],
        'pixel_change_percent':round(float(np.mean(changed)*100),3),
        'rgb_mean_absolute_error_255':round(float(np.mean(d)),3),
        'rgb_max_absolute_error_255':int(np.max(d)),
        'alpha_identical':bool(alpha_preserved),
        'source_border_difference_255':before_edges,
        'candidate_border_difference_255':after_edges,
        'border_difference_delta_255':{
            k: round(after_edges[k]-before_edges[k],3) if before_edges[k] is not None else None
            for k in ('horizontal','vertical')},
        'note':'Metrics sampled up to 768px; edge differences from full border. Diagnostic only; not proof of texture seams.'}


def difference_preview(before: Image.Image, after: Image.Image) -> Image.Image:
    """Bounded-memory visual change map (not a full-res processed texture)."""
    if before.size!=after.size:
        raise ValueError('DIFF_REQUIRES_IDENTICAL_DIMENSIONS')
    b=np.asarray(_sample(before), dtype=np.int16)
    a=np.asarray(_sample(after), dtype=np.int16)
    magnitude=np.clip(np.max(np.abs(a-b),axis=2).astype(np.float32)*4,0,255).astype(np.uint8)
    out=np.zeros((*magnitude.shape,3),dtype=np.uint8)
    out[:,:,0]=magnitude
    out[:,:,1]=magnitude//3
    return Image.fromarray(out)
