from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "docs"
MAP = DOCS / "engenharia" / "MAPA_MODULOS_SCRIPTS.md"
MANUAL = DOCS / "engenharia" / "MANUAL_DESENVOLVEDOR.md"
FORMATS = DOCS / "engenharia" / "REVERSE_ENGINEERING_FORMATOS.md"
SOURCE_API = DOCS / "en" / "engineering" / "SOURCE_API_REFERENCE.md"


def _text(path: Path) -> str:
    assert path.is_file(), path
    return path.read_text(encoding="utf-8")


def test_runtime_modules_are_documented():
    # SOURCE_API_REFERENCE is the exhaustive generated inventory.
    # MAPA_MODULOS_SCRIPTS remains the curated architectural map and is not
    # required to duplicate every implementation module basename.
    text = _text(SOURCE_API)
    missing = []
    for path in sorted((ROOT / "pt_asset_tool").glob("*.py")):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        rel = path.relative_to(ROOT.parent).as_posix()
        if f"## `{rel}`" not in text:
            missing.append(path.name)
    assert missing == []


def test_blender_helpers_are_documented():
    text = _text(MAP)
    missing = []
    for path in sorted((ROOT / "pt_asset_tool" / "blender").glob("*.py")):
        if f"`{path.name}`" not in text:
            missing.append(path.name)
    assert missing == []


def test_top_level_runtime_python_scripts_are_documented():
    text = _text(MAP)
    ignored = {"conftest.py"}
    missing = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name in ignored:
            continue
        if f"`{path.name}`" not in text:
            missing.append(path.name)
    assert missing == []


def test_reverse_manual_names_key_format_families():
    text = _text(MANUAL) + "\n" + _text(FORMATS)
    required = [
        "SMD Model data Ver 0.62",
        "SMD Stage data Ver 0.72",
        "MODERN_172",
        "LEGACY_120",
        "FULL18",
        "KEEP_00_16",
        "WORD16",
        "DWORD32",
        "Physique",
        "TexLink",
        "CANDIDATE_PT_BUILD_ONLY",
    ]
    missing = [x for x in required if x not in text]
    assert missing == []


def test_certified_writer_hashes_are_preserved_in_manual():
    text = _text(MANUAL)
    expected = {
        "rare_rigid_edit.py": "3ff2769bbc9762c04fb992fbad52ba7d60ae6a53f19c22d4f1d68e274697eec3",
        "rare_rigid_multivertex.py": "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991",
        "rare_rigid_multibone_bridge.py": "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0",
        "rare_rigid_normal_bridge.py": "2c0f75931e54a72cd87be2bc6694370f849c24c3f2b4b44afbdbc288dcaf622c",
    }
    for name, digest in expected.items():
        assert name in text
        assert digest in text


def test_exhaustive_source_api_reference_is_current():
    import runpy

    helper = DOCS / "validation" / "source_api_reference.py"
    api = runpy.run_path(str(helper))
    reference = DOCS / "en" / "engineering" / "SOURCE_API_REFERENCE.md"
    assert reference.read_text(encoding="utf-8") == api["render_reference"](ROOT.parent)


def test_exhaustive_reference_covers_all_maintained_python_implementation_files():
    text = (DOCS / "en" / "engineering" / "SOURCE_API_REFERENCE.md").read_text(encoding="utf-8")
    maintained = [p for p in sorted(ROOT.glob("*.py")) if p.name != "conftest.py"]
    maintained += sorted((ROOT / "pt_asset_tool").rglob("*.py"))
    maintained += sorted((DOCS / "validation").glob("*.py"))
    for path in maintained:
        rel = path.relative_to(ROOT.parent).as_posix()
        assert f"## `{rel}`" in text, rel
