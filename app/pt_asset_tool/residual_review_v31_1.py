"""V31.1 helpers: bounded click snapping and conservative mask deltas.

Pure-python routines intentionally independent of Blender. Nothing writes game files.
"""
from __future__ import annotations
import math

MAX_SNAP_PX = 20


def click_offsets(radius: int):
    """Small, ordered pixel sampling stencil. Centre ray always has priority.

    Offset rings favour closer clicks, so a tiny leaf is easier to select but
    an unrelated distant material is not silently selected.
    """
    if type(radius) is not int or not 0 <= radius <= MAX_SNAP_PX:
        raise ValueError('V31_1_SNAP_PX_INVALIDO')
    offsets = [(0, 0)]
    for distance in (max(1, round(radius / 2)), radius):
        if distance <= 0:
            continue
        points = [(distance, 0), (-distance, 0), (0, distance), (0, -distance),
                  (distance, distance), (-distance, distance),
                  (distance, -distance), (-distance, -distance)]
        for p in points:
            if p not in offsets:
                offsets.append(p)
    return offsets if radius else [(0, 0)]


def additions(current_mask, selected, face_count: int):
    """Validate incremental masked faces without touching the original Stage."""
    if type(face_count) is not int or face_count < 1:
        raise ValueError('V31_1_FACE_COUNT_INVALIDO')
    current = set(current_mask)
    fresh = set(selected)
    if (not fresh or any(type(i) is not int or i < 0 or i >= face_count for i in current | fresh)):
        raise ValueError('V31_1_FACE_INDEX_INVALIDO')
    if fresh & current:
        raise ValueError('V31_1_FACE_JA_MASCARADA')
    return sorted(fresh)
