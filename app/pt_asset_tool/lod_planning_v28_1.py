"""V28.1 pure LOD policy: progressive per-mesh decimation with measured budgets.

No bpy import here. The worker uses this policy for Blender geometry while
unit tests exercise it independently. Budgets are preview-only, never runtime.
"""
from __future__ import annotations

MAX_PASSES = 7
MIN_REDUCIBLE_FACES = 12
SAFE_OVERSHOOT = 1.5


def choose_collapse_ratio(current_faces: int, budget: int, pass_number: int) -> float:
    """Return a conservative, adaptive modifier ratio for the next pass.

    Blender's collapse ratio applies to individual mesh parts (often counting
    triangles), not to the aggregate output polygon count. Therefore the next
    iteration must use the measured result, not the original source total.
    """
    if not isinstance(current_faces, int) or current_faces <= 0:
        raise ValueError('V28_FACES_INVALIDAS')
    if not isinstance(budget, int) or budget <= 0:
        raise ValueError('V28_ORCAMENTO_INVALIDO')
    if not isinstance(pass_number, int) or pass_number < 0:
        raise ValueError('V28_PASSAGEM_INVALIDA')
    if current_faces <= budget:
        return 1.0
    # Slight headroom avoids oscillating at the face budget. More aggressive
    # retries compensate for non-collapsible foliage islands, but never delete
    # objects or individual texture cards solely to hit the target.
    headroom = max(.68, .88 - .035 * pass_number)
    return max(.00005, min(.96, budget / current_faces * headroom))


def assess_lod(actual_faces: int, budget: int) -> str:
    if not isinstance(actual_faces, int) or actual_faces <= 0:
        return 'REJECT'
    if not isinstance(budget, int) or budget <= 0:
        raise ValueError('V28_ORCAMENTO_INVALIDO')
    if actual_faces <= budget:
        return 'WITHIN_BUDGET'
    if actual_faces <= int(budget * SAFE_OVERSHOOT):
        return 'OVER_TARGET_REVIEW'  # bounded previews; never runtime certified
    return 'REJECT'
