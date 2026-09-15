from __future__ import annotations

from pathlib import Path

from pt_asset_tool.class_ui_alias_audit import audit_class_ui_aliases


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def test_mechanician_is_current_canonical_and_mecha_is_ignored_legacy(tmp_path: Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir()

    _write(client / "image/Sinimage/skill/Mechanician/Button/TM100 Rupture.bmp", b"t5")
    _write(client / "image/Sinimage/skill/Mechanician/Button/TM10 Ex_shield.bmp", b"current")
    _write(client / "image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp", b"legacy-different")
    _write(client / "image/Sinimage/skill/Mecha/Button/OldOnly.bmp", b"legacy-only")
    _write(client / "wav/Effects/player/Mechanician/damage 1.wav", b"wav")

    result = audit_class_ui_aliases(project, client)
    assert result["status"] == "PASS"
    assert result["state"] == "CANONICAL"
    assert result["split_group_count"] == 0
    assert result["counts"]["CANONICAL_ONLY"] == 2
    assert result["counts"]["ALIAS_ONLY"] == 0
    assert result["counts"]["DUPLICATE_CONFLICT"] == 0
    assert result["ignored_legacy_file_count"] == 2
    group = result["groups"][0]
    assert group["canonical_root"] == "image/Sinimage/skill/Mechanician"
    assert group["alias_roots"] == ()
    assert group["ignored_legacy_roots"][0]["root"] == "image/Sinimage/skill/Mecha"
    assert group["recovery_enabled"] is False
    assert result["policy"]["mechanician_skill_ui_is_canonical"] is True
    assert result["policy"]["historical_mecha_is_ignored"] is True
    assert result["policy"]["ignored_legacy_roots_are_not_write_sources"] is True
    assert result["policy"]["player_audio_mechanician_is_not_an_alias"] is True


def test_missing_mechanician_canonical_root_requires_review_even_if_mecha_exists(tmp_path: Path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    project.mkdir()
    _write(client / "image/Sinimage/skill/Mecha/Button/TM10 Ex_shield.bmp", b"legacy")

    result = audit_class_ui_aliases(project, client)
    assert result["state"] == "REVIEW_REQUIRED"
    assert result["groups"][0]["canonical_root_present"] is False
    assert result["ignored_legacy_file_count"] == 1
    assert result["counts"]["ALIAS_ONLY"] == 0
