from pathlib import Path

from pt_asset_tool.server_bundle_census import audit_server_entity_bundles


def _w(root: Path, rel: str, data: bytes):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p


def test_server_bundle_census_resolves_logical_ini_to_inx_across_roots(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _w(server, "GameServer/monster/Foo.inf", b'*model "char\\monster\\Foo\\Foo.ini"\n*link "name\\Foo.zhoon"\n')
    _w(server, "name/Foo.zhoon", b'*J_NAME "Foo"\n')
    _w(client, "char/monster/Foo/Foo.inx", b"inx")
    result = audit_server_entity_bundles(project, server, client, progress_every=1)
    assert result["status"] == "PASS"
    assert result["definition_count"] == 1
    assert result["resolved_visual_entry_count"] == 1
    row = result["rows"][0]
    assert row["logical_inx"].casefold() == "char/monster/foo/foo.inx"
    assert row["client_inx_exists"] is True
    assert row["zhoon"][0]["exists_server"] is True


def test_server_bundle_census_fails_closed_for_missing_dependencies(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _w(server, "GameServer/npc/N.npc", b'*model "char\\npc\\N\\N.ini"\n*link "name\\N.zhoon"\n')
    result = audit_server_entity_bundles(project, server, client)
    assert result["definition_count"] == 1
    assert result["unresolved_count"] == 1
    row = result["rows"][0]
    assert row["status"] == "BLOCKED_DEPENDENCY"
    assert "MODEL_INX_NOT_RESOLVED_CLIENT_OR_SERVER" in row["reasons"]
    assert "ZHOON_REFERENCE_MISSING" in row["reasons"]


def test_server_bundle_census_linux_case_and_definition_relative_zhoon(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _w(server, "gameserver/MONSTER/Foo.inf", b'*model "char\\monster\\Foo\\Foo.ini"\n*link "name\\Foo.zhoon"\n')
    _w(server, "gameserver/MONSTER/name/Foo.zhoon", b'*J_NAME "Foo"\n')
    _w(server, "CHAR/monster/Foo/Foo.inx", b"inx")
    result = audit_server_entity_bundles(project, server, client, progress_every=1)
    assert result["definition_count"] == 1
    assert result["resolved_visual_entry_count"] == 1
    row = result["rows"][0]
    assert row["server_inx_exists"] is True
    assert row["zhoon"][0]["exists_server"] is True


def test_server_bundle_census_accepts_unquoted_windows_path_reference(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _w(server, "GameServer/NPC/Foo.npc", b'*model char\\npc\\Foo\\Foo.ini\n')
    _w(client, "char/npc/Foo/Foo.inx", b"inx")
    result = audit_server_entity_bundles(project, server, client)
    assert result["definition_count"] == 1
    assert result["resolved_visual_entry_count"] == 1


def test_server_bundle_census_keeps_shared_name_name_zhoon_as_review_not_hard_blocker(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    server = tmp_path / "server"; server.mkdir()
    client = tmp_path / "client"; client.mkdir()
    _w(server, "GameServer/monster/Foo.inf", b'*model "char\\monster\\Foo\\Foo.ini"\n*link "Name\\Name.zhoon"\n')
    _w(client, "char/monster/Foo/Foo.inx", b"inx")
    result = audit_server_entity_bundles(project, server, client)
    row = result["rows"][0]
    assert row["status"] == "VISUAL_ENTRY_RESOLVED"
    assert "ZHOON_REFERENCE_MISSING" not in row["reasons"]
    assert "ZHOON_SHARED_DEFAULT_REVIEW" in row["reasons"]
    assert row["zhoon"][0]["shared_default_review"] is True
