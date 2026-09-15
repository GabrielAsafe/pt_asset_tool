from pathlib import Path
from types import SimpleNamespace

import pt_asset_tool.rigid_semantic_devtest as mod


class Asset:
    family = "SMD_MODEL_062_RIGID_PHYSIQUE"
    primary_path = "char/a.smd"


class Registry:
    def resolve(self, path):
        return Asset()


class Resolver:
    def resolve(self, logical, required=False):
        return self.root / logical


def test_rigid_batch_timeout_is_recorded_and_batch_continues(monkeypatch, tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    source = client / "char/a.smd"; source.parent.mkdir(parents=True); source.write_bytes(b"src")
    resolver = Resolver(); resolver.root = client
    monkeypatch.setattr(mod, "_cfg_for", lambda asset, inx: {"motion_smb": "char/a.smb", "lod_groups": {"default": ["Obj"]}})
    calls = []
    def fake_run(*args, asset_path, **kwargs):
        calls.append(asset_path)
        if len(calls) == 1:
            raise TimeoutError("writer timeout")
        return {"status": "PASS", "asset": asset_path, "model_info_inx": kwargs["model_info_inx"], "source_sha256": mod.sha256_file(source)}
    monkeypatch.setattr(mod, "run_rigid_semantic_automated_devtest", fake_run)
    settings = SimpleNamespace(project_root=project)
    rows = [
        {"asset": "char/a.smd", "model_info_inx": "char/a.inx", "domain": "PLAYER"},
        {"asset": "char/a.smd", "model_info_inx": "char/b.inx", "domain": "PLAYER"},
    ]
    progress=[]
    result = mod.run_rigid_semantic_automated_devtest_batch(
        settings, Registry(), resolver, None, rows, operation_timeout_seconds=1, progress=progress.append, resume=False
    )
    assert result["status"] == "FAIL"
    assert len(result["failed_assets"]) == 1
    assert len(result["passed_assets"]) == 1
    assert "TimeoutError" in result["failed_assets"][0]["error"]
    assert any("BATCH 1/2 START" in x for x in progress)
    assert any("BATCH 2/2 DONE" in x for x in progress)
    assert not (project / "pt_build/devtest/rigid_semantic_auto/batch_progress.json").exists()
