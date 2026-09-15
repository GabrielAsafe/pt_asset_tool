from __future__ import annotations
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
sys.path.insert(0, str(PAYLOAD))
from pt_asset_tool import rare_rigid_multivertex as mv
from pt_asset_tool import rare_rigid_large_saved_blender_candidate as c
from pt_asset_tool.certification import CertificationRegistry


def test_candidate_widening_is_process_local(monkeypatch):
    seen = []
    def fake(prepared, skeleton, *, changes):
        seen.append(mv.MAX_TRANSACTION_VERTICES)
        return {'ok': True}
    monkeypatch.setattr(mv, 'plan_requested_at_dragon_transaction', fake)
    old = mv.MAX_TRANSACTION_VERTICES
    assert old == 4
    assert c._candidate_plan(pathlib.Path('a'), pathlib.Path('b'), [{}]) == {'ok': True}
    assert seen == [8]
    assert mv.MAX_TRANSACTION_VERTICES == 4


def test_policy_constants():
    assert c.PROBE_COUNTS == (5, 6, 7, 8)
    assert c.PROBE_MAX == 8
    assert c.RELEASE_VERSION == '0.8.16'
    assert c.FORMAT == 'PT_RARE_RIGID_LARGE_SAVED_BLENDER_CANDIDATE_AUDIT_V2'
    assert len(c.EXPECTED_WRITER_HASHES) == 4


def test_classify_v0815_preview_side_effect(tmp_path):
    cert = CertificationRegistry(tmp_path / 'real_cert')
    row = cert.add(
        asset_id='X', asset_path=c.TARGET,
        family='MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT',
        test='RARE_RIGID_BLENDER_PREVIEW', layer='AUTOMATIC', result='PASS',
    )
    prior = {'certification_count_before': 0, 'certification_count_after': 1}
    got = c._classify_v0815_side_effect(cert, prior)
    assert got['certification_id'] == row['certification_id']
    assert got['classified_as'] == 'EXPECTED_PREVIEW_CERTIFICATION_FROM_WORKSPACE_PREPARATION'


def test_isolated_cert_registry_hash_stable_without_new_records(tmp_path):
    cert = CertificationRegistry(tmp_path / 'isolated')
    cert.add(
        asset_id='X', asset_path=c.TARGET,
        family='MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT',
        test='RARE_RIGID_BLENDER_PREVIEW', layer='AUTOMATIC', result='PASS',
    )
    before_count = len(cert.records())
    before_sha = c._cert_file_sha(cert)
    assert before_count == 1
    assert before_sha is not None
    assert len(cert.records()) == before_count
    assert c._cert_file_sha(cert) == before_sha
