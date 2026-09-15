from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "docs"
MAP = DOCS / "MAPA_MODULOS_SCRIPTS.md"
MANUAL = DOCS / "MANUAL_DESENVOLVEDOR.md"
FORMATS = DOCS / "REVERSE_ENGINEERING_FORMATOS.md"


def _text(path: Path) -> str:
    assert path.is_file(), path
    return path.read_text(encoding="utf-8")


def test_runtime_modules_are_documented():
    text = _text(MAP)
    missing = []
    for path in sorted((ROOT / "pt_asset_tool").glob("*.py")):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        if f"`{path.name}`" not in text:
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
        "rare_rigid_edit.py": "229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42",
        "rare_rigid_multivertex.py": "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991",
        "rare_rigid_multibone_bridge.py": "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0",
        "rare_rigid_normal_bridge.py": "67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96",
    }
    for name, digest in expected.items():
        assert name in text
        assert digest in text
