from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.server_environment_validation import run_server_environment_validation


def _write(root: Path, rel: str, data: bytes = b"x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_server_environment_auto_is_read_only_and_classifies_logitemdata(tmp_path):
    project = tmp_path / "app"
    client = tmp_path / "cliente"
    server = tmp_path / "Servidor"
    project.mkdir(); client.mkdir(); server.mkdir()
    # Required server gameplay/shared paths.
    _write(server, "GameServer/monster/Foo.inf", b"*name Foo\n")
    _write(server, "GameServer/npc/Bar.npc", b"*name Bar\n")
    _write(server, "GameServer/OpenItem/I.txt", b"NAME X\n")
    _write(server, "GameServer/Field/f.spm", b"*MAX_ACTOR 1\n")
    _write(server, "GameServer/Field/f.spp", b"\0" * 2400)
    _write(server, "GameServer/Field/f.spc", b"\0" * 50400)
    shared = _write(server, "char/monster/Foo/Foo.inx", b"shared")
    _write(server, "char/monster/Foo/Foo.smd", b"model")
    _write(server, "char/monster/Foo/Foo.smb", b"motion")
    _write(server, "Field/a.smd", b"stage")
    itm = _write(server, "LogItemData/158265217@8721833.itm", b"snapshot")
    _write(client, "char/monster/Foo/Foo.inx", b"shared")
    (server / "Configs").mkdir(exist_ok=True)
    (server / "DataServer").mkdir(exist_ok=True)
    (server / "PostBox").mkdir(exist_ok=True)
    (server / "FuncBox").mkdir(exist_ok=True)

    before = {shared: shared.read_bytes(), itm: itm.read_bytes()}
    settings = SimpleNamespace(project_root=project, client_root=client, server_root=server)
    result = run_server_environment_validation(settings)

    assert result["status"] == "PASS"
    assert result["server_environment_ready"] is True
    assert result["server_write_authorized"] is False
    assert result["persistence_write_authorized"] is False
    assert result["server_modified"] is False
    assert shared.read_bytes() == before[shared]
    assert itm.read_bytes() == before[itm]
    checks = {c["name"]: c for c in result["checks"]}
    assert checks["logitemdata_is_not_asset"]["status"] == "PASS"
    assert result["client_server_shared_samples"][0]["byte_identical"] is True


def test_server_environment_fails_without_server_root(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "cliente"; client.mkdir()
    settings = SimpleNamespace(project_root=project, client_root=client, server_root=None)
    result = run_server_environment_validation(settings)
    assert result["status"] == "FAIL"
    assert "server_root_configured" in result["required_failures"]
