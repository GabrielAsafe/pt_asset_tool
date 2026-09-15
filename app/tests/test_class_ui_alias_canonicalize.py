from __future__ import annotations

import pathlib

import pytest

from pt_asset_tool.class_ui_alias_canonicalize import canonicalize_class_ui_alias_only


def _write(root: pathlib.Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_mechanician_group_recovery_is_disabled_by_current_project_policy(tmp_path: pathlib.Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir()
    _write(client, "image/Sinimage/skill/Mechanician/Button/TM100 Rupture.bmp", b"current")
    _write(client, "image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp", b"legacy")

    with pytest.raises(ValueError, match="CLASS_UI_ALIAS_RECOVERY_DISABLED_BY_PROJECT_POLICY"):
        canonicalize_class_ui_alias_only(
            project,
            client,
            expected_group="MECHANICIAN_SKILL_UI",
            expected_paths=["image/Sinimage/skill/Mechanician/Button/TM10 Ex_shield.bmp"],
            apply=False,
        )


def test_mecha_is_never_used_as_automatic_write_source(tmp_path: pathlib.Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir()
    _write(client, "image/Sinimage/skill/Mecha/Button/LegacyOnly.bmp", b"legacy")

    with pytest.raises(ValueError, match="CLASS_UI_ALIAS_RECOVERY_DISABLED_BY_PROJECT_POLICY"):
        canonicalize_class_ui_alias_only(
            project,
            client,
            expected_group="MECHANICIAN_SKILL_UI",
            expected_paths=[],
            apply=True,
        )
    assert not (client / "image/Sinimage/skill/Mechanician/Button/LegacyOnly.bmp").exists()
