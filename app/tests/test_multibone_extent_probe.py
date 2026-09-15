from __future__ import annotations
import hashlib, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
PAYLOAD=ROOT/'payload'; sys.path.insert(0,str(PAYLOAD))
from pt_asset_tool import rare_rigid_multibone_extent_probe as m
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES


def sha(p:pathlib.Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()


def test_release_and_scope_are_audit_only():
    assert m.RELEASE_VERSION=='0.8.31'
    assert 'OUTWARD_EXTENT_PROBE' in m.FORMAT
    assert m.TARGET_KINDS==('maxX','maxZ','maxY','dBound','Bound')
    src=(PAYLOAD/'pt_asset_tool/rare_rigid_multibone_extent_probe.py').read_text(encoding='utf-8')
    assert "'multibone_outward_extent_write_authorized': False" in src
    assert "'extent_contraction_write_authorized': False" in src
    assert "load_and_validate_cross_policy(root)" in src


def test_monotonic_bounds_helper_and_cover():
    sb={'maxX':100,'maxZ':110,'maxY':120,'dBound':1000,'Bound':31}
    from pt_asset_tool.rare_rigid_extent_bridge import _expanded_bounds
    out=_expanded_bounds(sb,(150,0,0))
    assert out['maxX']==150 and out['maxZ']==110 and out['maxY']==120
    assert all(out[k]>=sb[k] for k in sb)
    assert m._bounds_cover_point(out,(150,0,0))


def test_requested_axis_candidates_begin_outside_stored_extent():
    sb={'maxX':100,'maxZ':200,'maxY':300,'dBound':10000,'Bound':100}
    old=(10,20,30)
    q=next(iter(m._requested_candidates(old,sb,'maxX')))
    assert abs(q[0])>sb['maxX'] and q[1:]==old[1:]


def test_wrapper_routes_v0831_probe():
    text=(PAYLOAD/'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-rigid-multibone-outward-extent-probe-workflow' in text
    assert 'rare_rigid_multibone_extent_probe' in text


def test_certified_writers_unchanged():
    for rel,expected in EXPECTED_WRITER_HASHES.items():
        assert sha(PAYLOAD/rel)==expected, rel


def test_no_certified_writer_contains_extent_probe_release_marker():
    for rel in EXPECTED_WRITER_HASHES:
        text=(PAYLOAD/rel).read_bytes()
        assert b'0.8.31' not in text
