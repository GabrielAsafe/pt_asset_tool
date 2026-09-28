from __future__ import annotations

import json

from pt_asset_tool.cooked_texture_evidence import audit_cooked_texture_evidence, cooked_index


def test_cooked_v2_failures_are_preserved_as_evidence(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); (client / "cooked").mkdir(parents=True)
    src_ok = client / "game" / "UI" / "bg.jpg"; src_ok.parent.mkdir(parents=True); src_ok.write_bytes(b"jpg")
    src_bad = client / "Field" / "Iron" / "bad.tga"; src_bad.parent.mkdir(parents=True); src_bad.write_bytes(b"G8legacy")
    cooked_ok = client / "cooked" / "game" / "UI" / "bg.dds"; cooked_ok.parent.mkdir(parents=True); cooked_ok.write_bytes(b"DDS ")
    manifest = {
        "format": "SUMMIT_TEXTURE_COOK_MANIFEST_V2", "version": 2,
        "entries": [
            {"source": "game/UI/bg.jpg", "cooked": "game/UI/bg.dds", "status": "up-to-date"},
            {"source": "Field/Iron/bad.tga", "cooked": "Field/Iron/bad.dds", "status": "error",
             "failure_stage": "decode", "failure_class": "IMPLAUSIBLE_IMAGE_DIMENSIONS",
             "error_type": "DecompressionBombError", "error_message": "too large", "source_sha256": "abc"},
        ],
    }
    (client / "cooked" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = audit_cooked_texture_evidence(project, client)
    assert result["status"] == "PASS"
    assert result["state"] == "REVIEW_REQUIRED"
    assert result["failure_count"] == 1
    assert result["failure_class_counts"] == {"IMPLAUSIBLE_IMAGE_DIMENSIONS": 1}
    idx = cooked_index(result)
    assert idx["field/iron/bad.tga"]["failure_stage"] == "decode"
    assert idx["game/ui/bg.jpg"]["cooked_exists"] == "True"
    assert result["policy"]["failed_cook_does_not_make_source_removable"] is True


def test_legacy_v1_manifest_remains_readable(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); (client / "cooked").mkdir(parents=True)
    (client / "foo.png").write_bytes(b"x")
    (client / "cooked" / "foo.dds").write_bytes(b"DDS ")
    (client / "cooked" / "manifest.json").write_text(json.dumps({
        "version": 1, "entries": [{"source": "foo.png", "cooked": "foo.dds", "status": "cooked"}]
    }), encoding="utf-8")
    result = audit_cooked_texture_evidence(project, client)
    assert result["status"] == "PASS"
    assert result["manifest_format"] == "LEGACY_V1"
    assert result["failure_count"] == 0


def test_v23_skip_and_outlier_integrity_metadata_are_imported(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); (client / "cooked").mkdir(parents=True)
    (client / "Field" / "Iron").mkdir(parents=True)
    (client / "Field" / "Iron" / "i05.TGA").write_bytes(b"tga")
    (client / "Effect" / "sky").mkdir(parents=True)
    (client / "Effect" / "sky" / "s.bmp").write_bytes(b"bad")
    manifest = {
        "format": "SUMMIT_TEXTURE_COOK_MANIFEST_V2", "version": 2, "metadata_revision": 3,
        "entries": [
            {"source": "Field/Iron/i05.TGA", "cooked": "Field/Iron/i05.dds", "status": "skipped",
             "skip_reason": "below-runtime-dxt-threshold", "skip_class": "VALID_DECODE_POLICY_THRESHOLD",
             "legacy_decode_mode": "TGA_DIMENSIONS_12_15", "asset_integrity_state": "VALID_IMAGE_POLICY_SKIPPED"},
            {"source": "Effect/sky/s.bmp", "cooked": "Effect/sky/s.dds", "status": "error",
             "failure_stage": "decode", "failure_class": "TRUNCATED_INPUT", "documented_outlier": True,
             "asset_classification": "INVALID_HISTORICAL_ASSET_UNSUPPORTED", "cook_policy": "DO_NOT_FORCE_DDS",
             "asset_integrity_state": "KNOWN_INVALID_OR_NON_IMAGE", "outlier_reason": "INVALID_HISTORICAL_ASSET_UNSUPPORTED"},
        ],
    }
    (client / "cooked" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = audit_cooked_texture_evidence(project, client)
    assert result["skip_count"] == 1
    assert result["skip_class_counts"] == {"VALID_DECODE_POLICY_THRESHOLD": 1}
    assert result["documented_outlier_failure_count"] == 1
    idx = cooked_index(result)
    assert idx["field/iron/i05.tga"]["legacy_decode_mode"] == "TGA_DIMENSIONS_12_15"
    assert idx["effect/sky/s.bmp"]["asset_integrity_state"] == "KNOWN_INVALID_OR_NON_IMAGE"
    assert idx["effect/sky/s.bmp"]["deletion_authorized"] == "False"
