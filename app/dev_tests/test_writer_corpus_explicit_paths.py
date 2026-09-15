from __future__ import annotations

from pathlib import Path
import pytest

from pt_asset_tool.writer_corpus_audit import _explicit_files
from pt_asset_tool import writer_corpus_audit as corpus


def test_explicit_files_select_only_requested_logical_paths(tmp_path: Path):
    root=tmp_path/'client'
    (root/'char').mkdir(parents=True)
    (root/'effect').mkdir(parents=True)
    (root/'char'/'a.inx').write_bytes(b'a')
    (root/'effect'/'e.inx').write_bytes(b'e')
    (root/'effect'/'e.smb').write_bytes(b's')
    rows=_explicit_files(root,'.inx',['effect/e.inx','effect/e.smb','effect/e.inx'])
    assert rows == [(root/'effect'/'e.inx').resolve()]


def test_explicit_files_reject_path_escape(tmp_path: Path):
    root=tmp_path/'client'; root.mkdir()
    with pytest.raises(ValueError, match='unsafe logical corpus path'):
        _explicit_files(root,'.inx',['../escape.inx'])


def test_explicit_inx_audit_fails_when_inventory_expected_file_is_missing(tmp_path: Path, monkeypatch):
    root=tmp_path/'client'; root.mkdir()
    monkeypatch.setattr(corpus,'validate_noop_roundtrip',lambda p:{'status':'PASS','layout':'X'})
    report=corpus.audit_inx_writer_corpus(root,logical_paths=['effect/missing.inx'])
    assert report['status']=='FAIL'
    assert report['requested_file_count']==1
    assert report['missing_requested_files']==['effect/missing.inx']


def test_explicit_inx_audit_passes_only_when_requested_file_is_present(tmp_path: Path, monkeypatch):
    root=tmp_path/'client'; (root/'effect').mkdir(parents=True)
    (root/'effect'/'e.inx').write_bytes(b'x')
    monkeypatch.setattr(corpus,'validate_noop_roundtrip',lambda p:{'status':'PASS','layout':'X'})
    report=corpus.audit_inx_writer_corpus(root,logical_paths=['effect/e.inx'])
    assert report['status']=='PASS'
    assert report['file_count']==1
    assert report['missing_requested_files']==[]
