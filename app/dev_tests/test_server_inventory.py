from pathlib import Path

from pt_asset_tool.server_inventory import audit_server_inventory


def _w(root: Path, rel: str):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")


def test_server_inventory_counts_assets_and_excludes_state(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    _w(server, "GameServer/monster/Foo.inf")
    _w(server, "char/monster/Foo/Foo.smd")
    _w(server, "LogItemData/1@2.itm")
    _w(server, "DataServer/userdata/a.dat")
    rows=[]
    result = audit_server_inventory(project, server, progress_every=1, progress=rows.append)
    assert result["status"] == "PASS"
    assert result["total_files"] == 4
    assert result["asset_candidate_files"] == 2
    assert result["hard_excluded_files"] == 2
    assert result["lifecycle_counts"]["LOG_FORENSICS_EXCLUDED"] == 1
    assert result["lifecycle_counts"]["PERSISTENCE_BLOCKED"] == 1
    assert rows
