"""Documented, non-destructive game-to-Blender view basis for Stage 0.72.

Priston Tale stage geometry is Y-up. Its legacy face winding corresponds to
Direct3D left-handed coordinates. Blender is Z-up/right-handed. Swapping Y/Z
has determinant -1 and reverses the *display* face normal sign without
changing vertex order, source UV loops, or the persisted Stage mesh.
"""
from __future__ import annotations

# Homogeneous transform: (game_x, game_y, game_z) -> (x, z, y).
GAME_TO_BLENDER_VIEW_MATRIX = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
VIEW_AXIS_PROFILE = 'GAME_Y_UP_LEFT_HANDED_TO_BLENDER_Z_UP_RIGHT_HANDED'


def to_blender_view_xyz(point):
    """Pure-Python witness for the coordinate basis, not a source writer."""
    x, y, z = point
    return (x, z, y)


def matrix3_determinant(matrix=GAME_TO_BLENDER_VIEW_MATRIX):
    a, b, c = (row[:3] for row in matrix[:3])
    return (a[0] * (b[1]*c[2] - b[2]*c[1])
            - a[1] * (b[0]*c[2] - b[2]*c[0])
            + a[2] * (b[0]*c[1] - b[1]*c[0]))
