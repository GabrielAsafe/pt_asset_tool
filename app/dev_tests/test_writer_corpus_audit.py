from pathlib import Path

import pytest

from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.writer_corpus_audit import (
    audit_inx_writer_corpus, audit_smb_writer_corpus,
    audit_inx_writer_edit_corpus, audit_smb_writer_edit_corpus,
    audit_motion_writer_semantic_edit_corpus,
)

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

requires_fixture = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")


@requires_fixture
def test_inx_writer_corpus_audit_is_read_only_and_passes_fixture_client():
    report = audit_inx_writer_corpus(CLIENT, sample_limit=10)
    assert report["status"] == "PASS"
    assert report["file_count"] > 0
    assert report["pass_count"] == report["file_count"]
    assert report["fail_count"] == 0
    assert report["client_modified"] is False
    assert report["production_authorized"] is False


@requires_fixture
def test_smb_writer_corpus_audit_separates_external_parent_from_layout_failure():
    report = audit_smb_writer_corpus(ROOT, CLIENT, sample_limit=10)
    assert report["status"] == "PASS"
    assert report["file_count"] > 0
    assert report["pass_count"] == report["file_count"]
    assert report["fail_count"] == 0
    assert report["client_modified"] is False
    assert report["production_authorized"] is False


def test_writer_corpus_prefix_cannot_escape_client_root():
    with pytest.raises(ValueError, match="unsafe corpus prefix"):
        audit_inx_writer_corpus(CLIENT, prefixes=["../outside"])


@requires_fixture
def test_inx_writer_edit_corpus_probe_uses_temp_outputs_only():
    report = audit_inx_writer_edit_corpus(CLIENT, sample_limit=10)
    assert report["status"] == "PASS"
    assert report["file_count"] > 0
    assert report["edited_file_count"] + report["no_editable_record_count"] == report["file_count"]
    assert report["fail_count"] == 0
    assert report["client_modified"] is False
    assert report["production_authorized"] is False


@requires_fixture
def test_smb_writer_edit_corpus_probe_separates_noneditable_files():
    report = audit_smb_writer_edit_corpus(ROOT, CLIENT, sample_limit=10)
    assert report["status"] == "PASS"
    assert report["file_count"] > 0
    assert report["edited_file_count"] + report["no_editable_key_file_count"] == report["file_count"]
    assert report["fail_count"] == 0
    assert report["client_modified"] is False
    assert report["production_authorized"] is False


@requires_fixture
def test_motion_writer_semantic_edit_corpus_proves_temp_edits_remain_source_evaluable():
    settings = Settings.discover(ROOT, CLIENT)
    resolver = ClientResolver(CLIENT)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    report = audit_motion_writer_semantic_edit_corpus(ROOT, registry, resolver, pair_limit=0, sample_limit=10)
    assert report["status"] == "PASS"
    assert report["audited_contexts"] == report["registry_motion_contexts"]
    assert report["corpus_complete"] is True
    assert report["selection_limited"] is False
    assert report["inx_semantic_edit_pass"] >= 1
    assert report["smb_semantic_edit_pass"] >= 1
    assert report["fail_count"] == 0
    assert report["visual_certification"] is False
    assert report["blender_pose_space_certification"] is False
    assert report["game_runtime_certification"] is False
    assert report["production_authorized"] is False
    assert report["client_modified"] is False


def test_motion_writer_semantic_edit_corpus_fails_closed_when_pair_limit_truncates_contexts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pt_asset_tool.writer_corpus_audit as mod

    inx1=tmp_path/'a.inx'; smb1=tmp_path/'a.smb'; inx2=tmp_path/'b.inx'; smb2=tmp_path/'b.smb'
    for p in (inx1,smb1,inx2,smb2): p.write_bytes(b'x')
    contexts=[
        {'motion_inx':'a.inx','motion_smb':'a.smb','inx_path':inx1,'smb_path':smb1,'assets':['char/A/A.smd']},
        {'motion_inx':'b.inx','motion_smb':'b.smb','inx_path':inx2,'smb_path':smb2,'assets':['char/B/B.smd']},
    ]
    monkeypatch.setattr(mod,'_registry_motion_contexts',lambda *a,**k:(contexts,[]))
    monkeypatch.setattr(mod,'_semantic_inx_edit',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr(mod,'_semantic_smb_edit',lambda *a,**k:{'status':'PASS'})
    reg=SimpleNamespace(assets=[
        SimpleNamespace(primary_path='char/A/A.smd',category='CHARACTER'),
        SimpleNamespace(primary_path='char/B/B.smd',category='CHARACTER'),
    ])
    report=audit_motion_writer_semantic_edit_corpus(tmp_path,reg,object(),pair_limit=1)
    assert report['status']=='FAIL'
    assert report['selection_limited'] is True
    assert report['corpus_complete'] is False
    assert report['audited_contexts']==1
    assert report['registry_motion_contexts']==2


def test_motion_writer_semantic_edit_checkpoint_resumes_only_sha_identical_completed_rows(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pt_asset_tool.writer_corpus_audit as mod

    inx = tmp_path / 'a.inx'; smb = tmp_path / 'a.smb'
    inx.write_bytes(b'inx-source'); smb.write_bytes(b'smb-source')
    contexts = [{
        'motion_inx':'char/A/A.inx','motion_smb':'char/A/A.smb',
        'inx_path':inx,'smb_path':smb,'assets':['char/A/A.smd'],
    }]
    monkeypatch.setattr(mod, '_registry_motion_contexts', lambda *a, **k: (contexts, []))
    calls = {'inx':0, 'smb':0}
    def fake_inx(*a, **k):
        calls['inx'] += 1
        return {'status':'PASS'}
    def fake_smb(*a, **k):
        calls['smb'] += 1
        return {'status':'PASS'}
    monkeypatch.setattr(mod, '_semantic_inx_edit', fake_inx)
    monkeypatch.setattr(mod, '_semantic_smb_edit', fake_smb)
    reg = SimpleNamespace(assets=[SimpleNamespace(primary_path='char/A/A.smd', category='CHARACTER')])
    checkpoint = tmp_path / 'checkpoint.jsonl'

    first = audit_motion_writer_semantic_edit_corpus(
        tmp_path, reg, object(), checkpoint_path=checkpoint, resume=False,
        operation_timeout_seconds=1,
    )
    assert first['status'] == 'PASS'
    assert calls == {'inx':1, 'smb':1}
    assert checkpoint.is_file()

    monkeypatch.setattr(mod, '_semantic_inx_edit', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must resume')))
    monkeypatch.setattr(mod, '_semantic_smb_edit', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must resume')))
    second = audit_motion_writer_semantic_edit_corpus(
        tmp_path, reg, object(), checkpoint_path=checkpoint, resume=True,
        operation_timeout_seconds=1,
    )
    assert second['status'] == 'PASS'
    assert second['resumed_contexts'] == 1
    assert second['audited_contexts'] == 1


def test_motion_writer_semantic_edit_timeout_fails_one_writer_and_continues(tmp_path, monkeypatch):
    import signal
    import time
    from types import SimpleNamespace
    import pt_asset_tool.writer_corpus_audit as mod

    if not hasattr(signal, 'SIGALRM') or not hasattr(signal, 'setitimer'):
        pytest.skip('POSIX semantic watchdog requires SIGALRM/setitimer')
    inx = tmp_path / 'slow.inx'; smb = tmp_path / 'slow.smb'
    inx.write_bytes(b'inx-source'); smb.write_bytes(b'smb-source')
    contexts = [{
        'motion_inx':'char/A/slow.inx','motion_smb':'char/A/slow.smb',
        'inx_path':inx,'smb_path':smb,'assets':['char/A/A.smd'],
    }]
    monkeypatch.setattr(mod, '_registry_motion_contexts', lambda *a, **k: (contexts, []))
    def slow_inx(*a, **k):
        time.sleep(0.25)
        return {'status':'PASS'}
    monkeypatch.setattr(mod, '_semantic_inx_edit', slow_inx)
    monkeypatch.setattr(mod, '_semantic_smb_edit', lambda *a, **k: {'status':'PASS'})
    reg = SimpleNamespace(assets=[SimpleNamespace(primary_path='char/A/A.smd', category='CHARACTER')])

    report = audit_motion_writer_semantic_edit_corpus(
        tmp_path, reg, object(), operation_timeout_seconds=0.05,
        checkpoint_path=tmp_path/'checkpoint.jsonl', resume=False,
    )
    assert report['status'] == 'FAIL'
    assert report['timeout_count'] == 1
    assert report['audited_contexts'] == 1
    assert report['rows'][0]['inx_edit']['reason'] == 'TIMEOUT'
    assert report['rows'][0]['smb_edit']['status'] == 'PASS'
    assert report['rows'][0]['source_integrity'] == 'PASS'
