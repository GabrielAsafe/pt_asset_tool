from pathlib import Path
import json
from types import SimpleNamespace
from pt_asset_tool import etervale_writer_cert as mod


def test_stage_real_writer_emits_native_stage(tmp_path):
    dest, report = mod.generate('stage', tmp_path, None, tmp_path/'staging')
    assert dest.is_file() and dest.read_bytes().startswith(b'SMD Stage data')
    assert report['self_roundtrip'] == 'PASS'


def test_model_real_writer_emits_native_model(tmp_path):
    dest, report = mod.generate('model', tmp_path, None, tmp_path/'staging')
    assert dest.is_file() and dest.read_bytes().startswith(b'SMD Model data Ver 0.62')
    assert report['self_roundtrip'] == 'PASS'


def test_stage_disallows_source(tmp_path):
    import pytest
    with pytest.raises(ValueError, match='NO_SOURCE'):
        mod.generate('stage', tmp_path, 'do-not-use.smd', tmp_path/'staging')


def test_writer_plan_never_touches_game_assets(tmp_path, monkeypatch, capsys):
    game=tmp_path/'game'; (game/'assets').mkdir(parents=True)
    work=tmp_path/'pt_build'/'etervale'
    monkeypatch.setattr(mod.bridge,'_game_root',lambda a:game)
    monkeypatch.setattr(mod.bridge,'_work_root',lambda:work)
    monkeypatch.setattr(mod.bridge,'_csproj',lambda *a:tmp_path/'assetdump.csproj')
    monkeypatch.setattr(mod.bridge,'_write_report',lambda sub,d:'not-written-test-only')
    assert mod.run(SimpleNamespace(mode='stage',source=None,build=False,execute=False))==0
    record=json.loads(capsys.readouterr().out)
    assert record['reader_status']=='NOT_RUN' and record['runtime_status']=='NOT_CERTIFIED'
    assert len(list((game/'assets').rglob('*')))==0
