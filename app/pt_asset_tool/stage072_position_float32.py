"""Exact Stage 0.72 position transport at Blender's binary32 storage boundary.

Stage vertices and lights store signed fixed-point coordinates; the importer
converts their coordinates from source units to world units by dividing by
256, then Blender persists IEEE754 single precision. The binary64 Python
intermediate cannot be required to survive this serialization unchanged.
"""
from __future__ import annotations

import math
import struct


def binary32_position(value: float) -> float:
    """Return the finite single-precision value Blender can actually store."""
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('STAGE072_POSITION_NOT_FINITE')
    try:
        rounded = struct.unpack('<f', struct.pack('<f', n))[0]
    except OverflowError as exc:
        raise ValueError('STAGE072_POSITION_OUTSIDE_BINARY32_RANGE') from exc
    if not math.isfinite(rounded):
        raise ValueError('STAGE072_POSITION_OUTSIDE_BINARY32_RANGE')
    return rounded


def expected_blender_position(source_raw_xyz: tuple[int, int, int]) -> tuple[float, float, float]:
    """Round source fixed/256 to binary32 at the Blender vertex/light ABI."""
    if len(source_raw_xyz) != 3:
        raise ValueError('STAGE072_POSITION_EXPECTED_3_COMPONENTS')
    return tuple(binary32_position(int(raw) / 256.0) for raw in source_raw_xyz)


def position_transport_error(
    stored_xyz: tuple[float, float, float], source_raw_xyz: tuple[int, int, int],
) -> tuple[float, float]:
    """(persisted error, Python64-intermediate delta), in source world units.

    A single binary32 ULP of geometric change must still produce a strictly
    nonzero persisted error. It is never acceptable to use an expanded world
    space tolerance here.
    """
    if len(stored_xyz) != 3 or len(source_raw_xyz) != 3:
        raise ValueError('STAGE072_POSITION_EXPECTED_3_COMPONENTS')
    actual = tuple(binary32_position(component) for component in stored_xyz)
    expected = expected_blender_position(source_raw_xyz)
    intermediate = tuple(int(raw) / 256.0 for raw in source_raw_xyz)
    persisted_error = max(abs(actual[i] - expected[i]) for i in range(3))
    intermediate_delta = max(abs(actual[i] - intermediate[i]) for i in range(3))
    return persisted_error, intermediate_delta
