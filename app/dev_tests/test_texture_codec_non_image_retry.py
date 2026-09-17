import importlib.util
import struct
from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool import texture_codec_devtest as devtest

ROOT = Path(__file__).resolve().parents[1]


def _load_tga_core():
    spec = importlib.util.spec_from_file_location("pt_tga_non_image_test", ROOT / "pt_protected_tga_v1.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _protected_html_prefix(tga):
    pseudo = b"\x00\x00DOCTYPE HTML PUB"
    assert len(pseudo) == 18
    return tga.protect_header(pseudo, "FULL18") + b"LIC \"-//W3C//DTD HTML 4.01 Transitional//EN\">"


def _protected_valid_tga(tga):
    header = bytearray(18)
    header[2] = 2
    struct.pack_into("<H", header, 12, 2)
    struct.pack_into("<H", header, 14, 1)
    header[16] = 24
    return tga.protect_header(bytes(header), "FULL18") + bytes(range(6))


def test_protected_prefix_html_is_target_content_invalid_not_codec_variant():
    tga = _load_tga_core()
    raw = _protected_html_prefix(tga)
    assert devtest._classify_non_image_target_payload(raw, tga) == "HTML_DOCUMENT_WITH_PROTECTED_PREFIX18"


def test_representative_tga_gate_retries_past_non_image_target(tmp_path, monkeypatch):
    tga = _load_tga_core()
    project = tmp_path / "app"
    project.mkdir()
    (project / "pt_protected_tga_v1.py").write_bytes((ROOT / "pt_protected_tga_v1.py").read_bytes())
    (project / "pt_character_texture_v1_4.py").write_bytes((ROOT / "pt_character_texture_v1_4.py").read_bytes())

    bad = tmp_path / "ch_tree1.tga"
    good = tmp_path / "valid_map.tga"
    bad.write_bytes(_protected_html_prefix(tga))
    good.write_bytes(_protected_valid_tga(tga))

    assets = [
        SimpleNamespace(
            family="TGA_NONSTANDARD_OR_PROTECTED",
            category="MAP_STAGE",
            primary_path="Field/Ricarten/ch_tree1.tga",
            size=bad.stat().st_size,
            asset_id="bad",
        ),
        SimpleNamespace(
            family="TGA_NONSTANDARD_OR_PROTECTED",
            category="MAP_STAGE",
            primary_path="Field/Test/valid_map.tga",
            size=good.stat().st_size + 1000,
            asset_id="good",
        ),
    ]

    class Registry:
        pass

    registry = Registry()
    registry.assets = assets

    class Resolver:
        def resolve(self, logical, required=True):
            return {
                "Field/Ricarten/ch_tree1.tga": bad,
                "Field/Test/valid_map.tga": good,
            }[str(logical)]

    monkeypatch.setattr(devtest, "SHIP_BMP_FILES", ())
    result = devtest.audit_proprietary_texture_codecs(project, registry, Resolver(), per_family=1)

    assert result["status"] == "PASS"
    assert result["failure_count"] == 0
    assert result["target_content_invalid_count"] == 1
    assert result["target_content_invalid"][0]["logical"] == "Field/Ricarten/ch_tree1.tga"
    assert result["target_content_invalid"][0]["classification"] == "HTML_DOCUMENT_WITH_PROTECTED_PREFIX18"
    assert [row["logical"] for row in result["rows"]] == ["Field/Test/valid_map.tga"]
    assert result["domain_summary"]["MAP"]["status"] == "PASS"


def test_representative_tga_gate_does_not_hide_unknown_codec_variant(tmp_path, monkeypatch):
    project = tmp_path / "app"
    project.mkdir()
    (project / "pt_protected_tga_v1.py").write_bytes((ROOT / "pt_protected_tga_v1.py").read_bytes())
    (project / "pt_character_texture_v1_4.py").write_bytes((ROOT / "pt_character_texture_v1_4.py").read_bytes())

    unknown = tmp_path / "unknown_map.tga"
    unknown.write_bytes(bytes.fromhex("0102030405060708090a0b0c0d0e0f101112") + b"not-an-image")

    asset = SimpleNamespace(
        family="TGA_NONSTANDARD_OR_PROTECTED",
        category="MAP_STAGE",
        primary_path="Field/Test/unknown_map.tga",
        size=unknown.stat().st_size,
        asset_id="unknown",
    )

    class Registry:
        assets = [asset]

    class Resolver:
        def resolve(self, logical, required=True):
            return unknown

    monkeypatch.setattr(devtest, "SHIP_BMP_FILES", ())
    result = devtest.audit_proprietary_texture_codecs(project, Registry(), Resolver(), per_family=1)

    assert result["status"] == "FAIL"
    assert result["failure_count"] == 1
    assert result["target_content_invalid_count"] == 0
    assert result["domain_summary"]["MAP"]["status"] == "FAIL"
