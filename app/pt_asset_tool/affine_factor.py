from __future__ import annotations

"""Small dependency-free 3x3 SVD for exact affine animation splitting.

Blender pose channels persist only location/rotation/diagonal-scale.  A legacy
Priston local basis can contain shear, which cannot be represented by one pose
bone.  Any nonsingular 3x3 linear transform can however be factored as

    M = U * diag(s) * V^T

where U and V are proper rotations after moving any reflection into one signed
scale component.  Two coincident bones can therefore preserve the full affine
basis using ordinary persistent TRS animation channels.

The implementation uses a Jacobi eigensolver for M^T M and intentionally has
no NumPy dependency so it can run inside Blender's bundled Python.
"""

import math
from typing import Iterable


def _m3(rows: Iterable[Iterable[float]]) -> list[list[float]]:
    out = [[float(x) for x in row] for row in rows]
    if len(out) != 3 or any(len(row) != 3 for row in out):
        raise ValueError("expected 3x3 matrix")
    if not all(math.isfinite(x) for row in out for x in row):
        raise ValueError("matrix contains non-finite values")
    return out


def transpose(a: list[list[float]]) -> list[list[float]]:
    return [[a[j][i] for j in range(3)] for i in range(3)]


def mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def det(a: list[list[float]]) -> float:
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def max_abs_diff(a: list[list[float]], b: list[list[float]]) -> float:
    return max(abs(a[i][j] - b[i][j]) for i in range(3) for j in range(3))


def _jacobi_symmetric(a0: list[list[float]], *, tolerance: float = 1e-14, max_iter: int = 64):
    a = _m3(a0)
    # Force tiny numerical asymmetry away; M^T M should be symmetric.
    for i in range(3):
        for j in range(i + 1, 3):
            v = 0.5 * (a[i][j] + a[j][i])
            a[i][j] = a[j][i] = v
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(max_iter):
        p, q = max(((0, 1), (0, 2), (1, 2)), key=lambda ij: abs(a[ij[0]][ij[1]]))
        apq = a[p][q]
        if abs(apq) <= tolerance:
            break
        app, aqq = a[p][p], a[q][q]
        phi = 0.5 * math.atan2(2.0 * apq, aqq - app)
        c, s = math.cos(phi), math.sin(phi)

        for k in range(3):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c * akp - s * akq
            a[k][q] = a[q][k] = s * akp + c * akq
        a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0

        for k in range(3):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p] = c * vkp - s * vkq
            v[k][q] = s * vkp + c * vkq
    else:
        raise RuntimeError("Jacobi symmetric eigensolver did not converge")
    return [a[i][i] for i in range(3)], v


def _dot(a: list[float], b: list[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: list[float], *, epsilon: float) -> list[float]:
    n = _norm(a)
    if n <= epsilon:
        raise ValueError("cannot normalize near-zero vector")
    return [x / n for x in a]


def _orthogonalize(vec: list[float], basis: list[list[float]]) -> list[float]:
    out = [float(x) for x in vec]
    for b in basis:
        d = _dot(out, b)
        out = [out[i] - d * b[i] for i in range(3)]
    return out


def _complete_orthonormal_columns(columns: list[list[float] | None], *, epsilon: float) -> list[list[float]]:
    """Fill missing 3-D orthonormal columns deterministically.

    Rank-deficient affine bases are legitimate in legacy content (for example a
    zero scale on one axis).  SVD leaves the corresponding U column undefined.
    Because its singular value is zero, *any* orthonormal completion preserves
    the matrix.  Prefer canonical axes with the largest remaining projection so
    the result is deterministic and numerically stable.
    """
    out: list[list[float] | None] = [None if c is None else list(c) for c in columns]
    fixed: list[list[float]] = []
    # First clean the already-defined columns in index order.
    for i, col in enumerate(out):
        if col is None:
            continue
        cleaned = _orthogonalize(col, fixed)
        cleaned = _normalize(cleaned, epsilon=epsilon)
        out[i] = cleaned
        fixed.append(cleaned)

    axes = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
    for i, col in enumerate(out):
        if col is not None:
            continue
        candidates = []
        for axis_index, axis in enumerate(axes):
            projected = _orthogonalize(list(axis), fixed)
            candidates.append((_norm(projected), -axis_index, projected))
        magnitude, _neg_axis, best = max(candidates, key=lambda row: (row[0], row[1]))
        if magnitude <= epsilon:
            # This can only happen because of severe numerical damage; fail
            # closed rather than inventing a non-orthogonal factor.
            raise ValueError("failed to complete orthonormal basis")
        best = _normalize(best, epsilon=epsilon)
        out[i] = best
        fixed.append(best)

    return [list(c) for c in out if c is not None]


def _flip_column(matrix: list[list[float]], col: int) -> None:
    for r in range(3):
        matrix[r][col] *= -1.0


def svd_affine_split(rows: Iterable[Iterable[float]], *, singular_epsilon: float = 1e-10) -> dict:
    """Factor any finite 3x3 affine basis into two Blender-TRS factors.

    The returned factors satisfy::

        M = first_rotation * diag(first_scale) * second_rotation

    where both rotations have determinant +1.  Unlike the first implementation,
    rank-deficient bases are supported: zero singular axes are completed with a
    deterministic orthonormal basis and therefore remain exactly zero after the
    split.  This matters for legacy zero-scale animation keys.
    """
    m = _m3(rows)
    mtm = mul(transpose(m), m)
    eig, v = _jacobi_symmetric(mtm)

    # Columns of V are eigenvectors.  Keep a deterministic descending singular
    # value order; ties use the original Jacobi column number.
    order = sorted(range(3), key=lambda i: (-max(0.0, eig[i]), i))
    v = [[v[r][i] for i in order] for r in range(3)]

    # Do not trust sqrt(eigenvalue) alone to decide whether a singular axis is
    # non-zero.  For an exactly rank-deficient matrix the Jacobi solve of
    # M^T M can leave a tiny positive eigenvalue (for example ~2.6e-19),
    # producing a nominal sigma around 5e-10 even though M @ v is zero to
    # machine precision.  Normalizing that vector is undefined and was the
    # RC2 Blender self-test failure.  The defining singular value is ||M v||,
    # which is both cheaper to validate here and numerically robust for zero
    # axes.  Keep the eigensolver only for V/order.
    mv_cols: list[list[float]] = []
    singular: list[float] = []
    for col in range(3):
        vec = [v[r][col] for r in range(3)]
        mv = [sum(m[r][k] * vec[k] for k in range(3)) for r in range(3)]
        mv_cols.append(mv)
        singular.append(_norm(mv))

    max_sigma = max(singular) if singular else 0.0
    zero_threshold = max(float(singular_epsilon), max_sigma * 1e-12)
    rank = sum(1 for x in singular if x > zero_threshold)

    # U_i = M V_i / ||M V_i|| for non-zero singular values.  Zero singular
    # columns are mathematically free and are filled deterministically below.
    u_cols: list[list[float] | None] = [None, None, None]
    for col in range(3):
        sigma = singular[col]
        if sigma <= zero_threshold:
            continue
        mv = mv_cols[col]
        u_cols[col] = [x / sigma for x in mv]

    completed = _complete_orthonormal_columns(u_cols, epsilon=max(1e-14, zero_threshold * 1e-3))
    # _complete_orthonormal_columns returns values in column-index order.
    u = [[completed[c][r] for c in range(3)] for r in range(3)]

    # Make both factors proper rotations.  For rank-deficient matrices a zero
    # singular axis can absorb a column sign change for free.  Otherwise move
    # the reflection into a signed singular value.
    zero_cols = [i for i, x in enumerate(singular) if x <= zero_threshold]
    if det(u) < 0.0:
        k = zero_cols[-1] if zero_cols else 2
        _flip_column(u, k)
        if not zero_cols:
            singular[k] *= -1.0
    if det(v) < 0.0:
        k = zero_cols[-1] if zero_cols else 2
        _flip_column(v, k)
        if not zero_cols:
            singular[k] *= -1.0

    vt = transpose(v)
    first = [[u[r][c] * singular[c] for c in range(3)] for r in range(3)]
    rebuilt = mul(first, vt)
    residual = max_abs_diff(m, rebuilt)
    scale = max(1.0, max(abs(x) for row in m for x in row))
    if residual > 5e-7 * scale:
        raise RuntimeError(f"affine split reconstruction residual too large: {residual} scale={scale}")
    return {
        "first_rotation": u,
        "first_scale": singular,
        "second_rotation": vt,
        "singular_values_abs": [abs(float(x)) for x in singular],
        "rank": rank,
        "zero_singular_axis_count": 3 - rank,
        "reconstruction_error": residual,
        "source_determinant": det(m),
        "first_rotation_determinant": det(u),
        "second_rotation_determinant": det(vt),
    }
