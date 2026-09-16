from __future__ import annotations

import csv
import json
import pathlib
import struct

from pt_asset_tool.app_config import config_path, save_client_root
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.registry_bootstrap import build_runtime_registry, ensure_runtime_registry


def _model062(path: pathlib.Path, *, node: str = "Body01") -> None:
    header = 556
    info = 40
    obj = 2236
    start = header + info
    data = bytearray(start + obj)
    data[: len(b"SMD Model data Ver 0.62")] = b"SMD Model data Ver 0.62"
    struct.pack_into("<i", data, 24, 1)
    struct.pack_into("<i", data, 28, 0)
    struct.pack_into("<i", data, 32, start)
    struct.pack_into("<i", data, 36, start)
    name = node.encode("latin1")[:31]
    data[header:header + len(name)] = name
    struct.pack_into("<i", data, header + 32, obj)
    struct.pack_into("<i", data, header + 36, start)
    data[start + 172:start + 172 + len(name)] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _inx(path: pathlib.Path) -> None:
    data = bytearray(67084)
    data[0:64] = b"char/test/body.ASE\0".ljust(64, b"\0")
    data[64:128] = b"char/test/body.ASE\0".ljust(64, b"\0")
    for off, name in ((0x0C0, b"Body01"), (0x104, b"Body01")):
        struct.pack_into("<i", data, off, 1)
        data[off + 4:off + 4 + len(name)] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_fresh_registry_is_built_from_current_client(tmp_path: pathlib.Path):
    project = tmp_path / "tool" / "app"
    client = tmp_path / "client"
    project.mkdir(parents=True)
    _model062(client / "char/test/body.smd")
    _inx(client / "char/test/body.inx")
    (client / "char/test/body.smb").write_bytes(b"SMD Model data Ver 0.62")

    state = project / "pt_build/state/asset_registry"
    report = build_runtime_registry(client, state / "asset_inventory.json", state / "inx_physical_pairing.csv")
    assert report["status"] == "PASS"
    assert report["record_count"] == 3
    inv = json.loads((state / "asset_inventory.json").read_text(encoding="utf-8"))
    assert inv["canonical_client_root"] == str(client.resolve())
    model = next(x for x in inv["records"] if x["relative_path"] == "char/test/body.smd")
    assert model["compatibility_family"] == "SMD_MODEL_062_STATIC"
    assert model["name_shape"] == "Body#"
    assert model["object_count"] == 1

    with (state / "inx_physical_pairing.csv").open(newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    assert len(pairs) == 1
    assert pairs[0]["model_smd"] == "char/test/body.smd"
    assert pairs[0]["motion_smb"] == "char/test/body.smb"
    assert pairs[0]["model_resolved"] == "True"
    assert pairs[0]["motion_resolved"] == "True"

    reg = AssetRegistry(state / "asset_inventory.json", state / "inx_physical_pairing.csv")
    asset = reg.resolve("char/test/body.smd")
    assert asset.family == "SMD_MODEL_062_STATIC"


def test_settings_first_use_generates_state_and_keeps_config_out_of_package(tmp_path: pathlib.Path):
    project = tmp_path / "tool" / "app"
    client = tmp_path / "client"
    project.mkdir(parents=True)
    (client / "image").mkdir(parents=True)
    (client / "image/x.bmp").write_bytes(b"BM" + b"\0" * 62)

    cfg = save_client_root(project, client)
    assert cfg == project / "pt_build/state/pt_asset_app_config.json"
    assert config_path(project) == cfg
    settings = Settings.discover(project)
    assert settings.inventory.is_file()
    assert settings.pairing.is_file()
    assert settings.inventory.is_relative_to(project / "pt_build")
    assert not (project / "pt_asset_app_config.json").exists()


def test_runtime_registry_rebuilds_when_client_tree_changes(tmp_path: pathlib.Path):
    client = tmp_path / "client"
    state = tmp_path / "state"
    (client / "image").mkdir(parents=True)
    first = client / "image/a.bmp"
    first.write_bytes(b"BM" + b"\0" * 62)

    inv = state / "asset_inventory.json"
    pair = state / "inx_physical_pairing.csv"
    built = ensure_runtime_registry(client, inv, pair)
    assert built["status"] == "PASS"
    assert built["record_count"] == 1

    ready = ensure_runtime_registry(client, inv, pair)
    assert ready["status"] == "READY"
    assert ready["record_count"] == 1

    second = client / "image/b.bmp"
    second.write_bytes(b"BM" + b"\1" * 62)
    rebuilt = ensure_runtime_registry(client, inv, pair)
    assert rebuilt["status"] == "PASS"
    assert rebuilt["record_count"] == 2
    data = json.loads(inv.read_text(encoding="utf-8"))
    assert {row["relative_path"] for row in data["records"]} == {"image/a.bmp", "image/b.bmp"}
