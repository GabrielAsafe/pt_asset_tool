"""Exact Stage072 texture-coordinate witness at Blender's persisted binary32 ABI.

The serialized smTEXLINK U/V data are IEEE-754 binary32. The Blender UV
attribute stores binary32, too. Importing V in the Blender orientation uses
1.0 - V, rounded to binary32 before it can be stored in the .blend. Comparing
that persisted binary32 value with a Python binary64 intermediate is not a
valid byte-transport check for UVs with a large integral/tiled component.
"""
from __future__ import annotations

import math
import struct


def binary32(value: float) -> float:
    """Round once to IEEE-754 single, exactly as a Blender Float2 UV stores it."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('NONFINITE_STAGE072_UV_REFUSED')
    try:
        encoded = struct.pack('<f', value)
    except OverflowError as exc:
        raise ValueError('STAGE072_UV_OUTSIDE_FLOAT32_RANGE') from exc
    rounded = struct.unpack('<f', encoded)[0]
    if not math.isfinite(rounded):
        raise ValueError('STAGE072_UV_OUTSIDE_FLOAT32_RANGE')
    return rounded


def expected_blender_uv(source_u: float, source_v: float) -> tuple[float, float]:
    """Source U stays binary32; source V is flipped then stored as binary32."""
    return binary32(source_u), binary32(1.0 - binary32(source_v))


def uv_transport_error(got: tuple[float, float], source_u: float, source_v: float) -> tuple[float, float]:
    """Return (binary32-expected error, naive float64 error) for diagnostics.

    A nonzero binary32-expected error remains a transport error; this method
    does not increase tolerance or discard mismatched UVs.
    """
    expected = expected_blender_uv(source_u, source_v)
    actual = (binary32(got[0]), binary32(got[1]))
    stored_error = max(abs(actual[j] - expected[j]) for j in range(2))
    old_python64 = (float(source_u), 1.0 - float(source_v))
    float64_error = max(abs(actual[j] - old_python64[j]) for j in range(2))
    return stored_error, float64_error
