import math
import random

from pt_asset_tool.affine_factor import det, max_abs_diff, mul, svd_affine_split


def _rz(a):
    c,s=math.cos(a),math.sin(a)
    return [[c,-s,0],[s,c,0],[0,0,1]]


def _rx(a):
    c,s=math.cos(a),math.sin(a)
    return [[1,0,0],[0,c,-s],[0,s,c]]


def _diag(v): return [[v[0],0,0],[0,v[1],0],[0,0,v[2]]]


def _rebuild(f):
    first=mul(f['first_rotation'],_diag(f['first_scale']))
    return mul(first,f['second_rotation'])


def test_affine_split_exact_for_shear_like_rotation_scale_rotation():
    m=mul(mul(_rz(0.43),_diag([1.4,0.7,1.1])),_rx(-0.61))
    f=svd_affine_split(m)
    assert det(f['first_rotation']) > 0.999999
    assert det(f['second_rotation']) > 0.999999
    assert max_abs_diff(m,_rebuild(f)) < 1e-7


def test_affine_split_handles_reflection_with_signed_scale():
    m=mul(mul(_rz(0.2),_diag([-1.2,0.8,1.05])),_rx(0.7))
    f=svd_affine_split(m)
    assert det(f['first_rotation']) > 0.999999
    assert det(f['second_rotation']) > 0.999999
    assert any(x < 0 for x in f['first_scale'])
    assert max_abs_diff(m,_rebuild(f)) < 1e-7


def test_affine_split_random_well_conditioned_cases():
    rnd=random.Random(7)
    for _ in range(100):
        a,b=rnd.uniform(-2,2),rnd.uniform(-2,2)
        sc=[rnd.uniform(0.35,2.2) for _ in range(3)]
        m=mul(mul(_rz(a),_diag(sc)),_rx(b))
        f=svd_affine_split(m)
        assert max_abs_diff(m,_rebuild(f)) < 2e-7


def test_affine_split_handles_rank_two_zero_scale():
    m=mul(mul(_rz(0.37),_diag([1.4,0.0,0.8])),_rx(-0.29))
    f=svd_affine_split(m)
    assert f['rank'] == 2
    assert f['zero_singular_axis_count'] == 1
    assert det(f['first_rotation']) > 0.999999
    assert det(f['second_rotation']) > 0.999999
    assert max_abs_diff(m,_rebuild(f)) < 2e-7


def test_affine_split_handles_rank_one_and_zero_matrix():
    m=mul(mul(_rz(-0.8),_diag([1.7,0.0,0.0])),_rx(0.41))
    f=svd_affine_split(m)
    assert f['rank'] == 1
    assert max_abs_diff(m,_rebuild(f)) < 2e-7
    z=[[0.0,0.0,0.0],[0.0,0.0,0.0],[0.0,0.0,0.0]]
    fz=svd_affine_split(z)
    assert fz['rank'] == 0
    assert max_abs_diff(z,_rebuild(fz)) == 0.0


def test_affine_split_handles_exact_rank_two_shear_rc2_regression():
    # Physical RC2 affine self-test regression: M^T M produces a tiny positive
    # eigenvalue although this matrix is exactly rank two.  The split must use
    # ||M v|| to classify the zero singular axis rather than normalizing the
    # numerical eigensolver residue.
    m = [[1.0, 0.20, 0.0], [0.0, 0.0, 0.0], [0.10, 0.0, 0.75]]
    f = svd_affine_split(m)
    assert f['rank'] == 2
    assert f['zero_singular_axis_count'] == 1
    assert det(f['first_rotation']) > 0.999999
    assert det(f['second_rotation']) > 0.999999
    assert max_abs_diff(m, _rebuild(f)) < 2e-7


def test_affine_split_rank_detection_ignores_eigenvalue_roundoff_residue():
    # Same null row with slightly different shear/scale to protect the general
    # numerical class, not only one literal fixture.
    m = [[0.8, -0.31, 0.0], [0.0, 0.0, 0.0], [0.07, 0.0, 1.25]]
    f = svd_affine_split(m)
    assert f['rank'] == 2
    assert f['zero_singular_axis_count'] == 1
    assert max_abs_diff(m, _rebuild(f)) < 2e-7
