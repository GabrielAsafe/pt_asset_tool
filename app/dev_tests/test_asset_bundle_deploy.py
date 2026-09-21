from __future__ import annotations

from pathlib import Path
import hashlib
import struct

import pytest

from pt_asset_tool.asset_bundle_deploy import (
    APPLY_CONFIRM,
    RESTORE_CONFIRM,
    asset_bundle_deploy_status,
    publish_asset_bundle,
    restore_asset_bundle,
)
from pt_asset_tool.asset_compiler import BUNDLE_RECIPE_FORMAT, compile_asset_bundle



def _minimal_model062(path: Path) -> Path:
    sh, si, so = 556, 40, 2236
    start = sh + si
    data = bytearray(start + so)
    data[:23] = b"SMD Model data Ver 0.62"
    struct.pack_into("<i", data, 24, 1)
    struct.pack_into("<i", data, 28, 0)
    struct.pack_into("<i", data, 32, start)
    struct.pack_into("<i", data, 36, start)
    data[sh:sh + 4] = b"obj\0"
    struct.pack_into("<i", data, sh + 32, so)
    struct.pack_into("<i", data, sh + 36, start)
    data[start + 172:start + 176] = b"obj\0"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _minimal_stage072(path: Path) -> Path:
    dfile, stage, group, mat = 556, 262260, 88, 320
    blob = group + mat
    data = bytearray(dfile + stage + blob)
    data[:23] = b"SMD Stage data Ver 0.72"
    struct.pack_into("<i", data, 24, 0)
    struct.pack_into("<i", data, 28, 1)
    struct.pack_into("<i", data, 32, dfile)
    struct.pack_into("<i", data, 36, dfile + blob)
    mat_start = dfile + stage
    struct.pack_into("<i", data, mat_start + 8, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path

def _roots(tmp_path: Path) -> tuple[Path, Path]:
    client = tmp_path / "client"
    server = tmp_path / "server"
    (client / "char/monster/test").mkdir(parents=True)
    (client / "char/monster/test/test.ini").write_text("*모양파일 test.smd\r\n", encoding="cp949")
    _minimal_model062(client / "char/monster/test/test.smd")
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text(
        '*ACTOR "Existing" 100\r\n*MAX_ACTOR 10\r\n', encoding="cp1252"
    )
    return client, server


def _monster_recipe() -> dict:
    return {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "deploy_monster",
        "bundle_type": "MONSTER",
        "payload": {
            "identity": {"id": "deploy_monster", "name": "Deploy Monster"},
            "model_file": "char/monster/test/test.ini",
            "definition": {
                "output": "GameServer/Monster/deploy_monster.inf",
                "fields": {
                    "level": 40,
                    "life": 5000,
                    "attack_damage": [20, 30],
                    "attack_speed": [1.0, 1.0],
                },
            },
            "placement": {
                "output": "GameServer/Field/Test.spm",
                "mode": "PATCH_EXISTING",
                "weight": 250,
            },
        },
    }


def test_asset_bundle_publish_restore_is_transactional(tmp_path: Path):
    client, server = _roots(tmp_path)
    original_spm = (server / "GameServer/Field/Test.spm").read_bytes()
    build = compile_asset_bundle(tmp_path, _monster_recipe(), client_root=client, server_root=server)

    tx = publish_asset_bundle(
        tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM
    )
    assert tx["state"] == "APPLIED_VERIFIED"
    assert tx["server_modified"] is True
    assert tx["client_modified"] is False
    definition = server / "GameServer/Monster/deploy_monster.inf"
    assert definition.is_file()
    assert b"Deploy Monster" in definition.read_bytes()
    assert b'Deploy Monster' in (server / "GameServer/Field/Test.spm").read_bytes()

    status = asset_bundle_deploy_status(tmp_path)
    assert status["can_restore"] is True
    assert status["can_publish"] is False

    restored = restore_asset_bundle(
        tmp_path, client, server, build["manifest"], confirm=RESTORE_CONFIRM
    )
    assert restored["state"] == "RESTORED_VERIFIED"
    assert not definition.exists()
    assert (server / "GameServer/Field/Test.spm").read_bytes() == original_spm


def test_asset_bundle_publish_blocks_target_drift_before_first_write(tmp_path: Path):
    client, server = _roots(tmp_path)
    build = compile_asset_bundle(tmp_path, _monster_recipe(), client_root=client, server_root=server)
    spm = server / "GameServer/Field/Test.spm"
    spm.write_bytes(spm.read_bytes() + b"# external change\r\n")

    with pytest.raises(ValueError, match="ASSET_BUNDLE_TARGET_DRIFT"):
        publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)
    assert not (server / "GameServer/Monster/deploy_monster.inf").exists()


def test_asset_bundle_restore_blocks_drift_without_partial_restore(tmp_path: Path):
    client, server = _roots(tmp_path)
    build = compile_asset_bundle(tmp_path, _monster_recipe(), client_root=client, server_root=server)
    publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)
    definition = server / "GameServer/Monster/deploy_monster.inf"
    definition.write_bytes(definition.read_bytes() + b"# external\r\n")
    published_spm = (server / "GameServer/Field/Test.spm").read_bytes()

    with pytest.raises(ValueError, match="ASSET_BUNDLE_RESTORE_DRIFT"):
        restore_asset_bundle(tmp_path, client, server, build["manifest"], confirm=RESTORE_CONFIRM)
    assert b"# external" in definition.read_bytes()
    assert (server / "GameServer/Field/Test.spm").read_bytes() == published_spm


def test_asset_bundle_deploy_blocks_unregistered_item_code_even_if_compiler_boundary_override(tmp_path: Path):
    client, server = _roots(tmp_path)
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "future_item",
        "bundle_type": "ITEM",
        "payload": {
            "identity": {"id": "future_item", "name": "Future Item"},
            "definition": {
                "output": "GameServer/OpenItem/future_item.txt",
                "allow_unknown_code": True,
                "fields": {"code": "ZZ999", "price": 1},
            },
        },
    }
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    with pytest.raises(ValueError, match="BUNDLE_DEPLOY_ITEM_CODE_NOT_SOURCE_VERIFIED"):
        publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)
    assert not (server / "GameServer/OpenItem/future_item.txt").exists()


def test_asset_bundle_deploy_blocks_operational_config_contract(tmp_path: Path):
    client, server = _roots(tmp_path)
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "operational",
        "bundle_type": "CUSTOM",
        "assets": [
            {
                "format": "PT_ASSET_RECIPE_V1",
                "id": "hotuk",
                "contract_id": "server.main_config",
                "target_side": "SERVER",
                "output": "Configs/hotuk.ini",
                "target_policy": "CREATE_NEW",
                "payload": {"directives": {"*SERVER_CODE": 7}},
            }
        ],
    }
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    with pytest.raises(ValueError, match="BUNDLE_DEPLOY_OPERATIONAL_CONTRACT_BLOCKED"):
        publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)


def test_graph_bound_verified_model_artifact_can_publish_with_generated_config_and_inx(tmp_path: Path):
    client = tmp_path / "client"
    server = tmp_path / "server"
    client.mkdir()
    (server / "GameServer/Field").mkdir(parents=True)
    (server / "GameServer/Field/Test.spm").write_text('*MAX_ACTOR 10\r\n', encoding="cp1252")
    artifact = _minimal_model062(tmp_path / "design_tool" / "new.smd")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "new_model_bundle",
        "bundle_type": "MONSTER",
        "assets": [
            {
                "format": "PT_ASSET_RECIPE_V1",
                "id": "mesh",
                "contract_id": "model.smd.062",
                "target_side": "CLIENT",
                "output": "char/monster/new/new.smd",
                "payload": {"source_path": str(artifact), "expected_sha256": artifact_sha},
            },
            {
                "format": "PT_ASSET_RECIPE_V1",
                "id": "config",
                "contract_id": "model.config.ini",
                "target_side": "CLIENT",
                "output": "char/monster/new/new.ini",
                "payload": {"model_file": "new.smd"},
            },
        ],
        "payload": {
            "identity": {"id": "new_model_bundle", "name": "New Model Bundle"},
            "model_file": "char/monster/new/new.ini",
            "definition": {"fields": {"level": 1, "life": 10, "attack_speed": [1.0, 1.0]}},
            "placement": {"output": "GameServer/Field/Test.spm", "mode": "PATCH_EXISTING"},
        },
    }
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    rows = {x["contract_id"]: x for x in build["assets"] if x.get("contract_id") in {"model.smd.062", "model.config.ini", "model.cache.inx"}}
    assert rows["model.smd.062"]["binding_evidence"]["role"] == "model_file"
    assert rows["model.config.ini"]["binding_evidence"]["role"] == "config"
    assert rows["model.cache.inx"]["binding_evidence"]["role"] == "derived_cache"

    tx = publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)
    assert tx["state"] == "APPLIED_VERIFIED"
    assert (client / "char/monster/new/new.smd").read_bytes() == artifact.read_bytes()
    assert (client / "char/monster/new/new.ini").is_file()
    assert (client / "char/monster/new/new.inx").stat().st_size == 95268

    restored = restore_asset_bundle(tmp_path, client, server, build["manifest"], confirm=RESTORE_CONFIRM)
    assert restored["state"] == "RESTORED_VERIFIED"
    assert not (client / "char/monster/new/new.smd").exists()
    assert not (client / "char/monster/new/new.ini").exists()
    assert not (client / "char/monster/new/new.inx").exists()


def test_field_bundle_verified_stage_is_graph_bound_and_transactional(tmp_path: Path):
    client = tmp_path / "client"; client.mkdir()
    server = tmp_path / "server"; server.mkdir()
    artifact = _minimal_stage072(tmp_path / "design_tool" / "NewField.smd")
    recipe = {
        "format": BUNDLE_RECIPE_FORMAT,
        "id": "new_field_visual",
        "bundle_type": "FIELD",
        "payload": {
            "stage_asset": {
                "output": "field/NewField/NewField.smd",
                "source_path": str(artifact),
                "expected_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        },
    }
    build = compile_asset_bundle(tmp_path, recipe, client_root=client, server_root=server)
    stage = next(x for x in build["assets"] if x.get("contract_id") == "stage.smd.072")
    assert stage["binding_evidence"]["graph"] == "FIELD_STAGE_CLOSURE"
    assert stage["binding_evidence"]["role"] == "stage_file"
    tx = publish_asset_bundle(tmp_path, client, server, build["manifest"], confirm=APPLY_CONFIRM)
    assert tx["client_modified"] is True and tx["server_modified"] is False
    deployed = client / "field/NewField/NewField.smd"
    assert deployed.read_bytes() == artifact.read_bytes()
    restore_asset_bundle(tmp_path, client, server, build["manifest"], confirm=RESTORE_CONFIRM)
    assert not deployed.exists()
