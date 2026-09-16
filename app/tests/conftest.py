from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "payload"

# These tests validate the historical/generated consolidated payload layout.  A
# source checkout intentionally does not ship app/payload; the tests remain in
# the repository and execute normally whenever that generated fixture exists.
PREBUILT_PAYLOAD_MODULES = {
    "test_consolidated_routes.py",
    "test_cross_object_interactive_candidate.py",
    "test_cross_object_live_writer_candidate.py",
    "test_cross_object_production_promotion.py",
    "test_cross_object_saved_blender_candidate.py",
    "test_desktop_portability.py",
    "test_interactive_candidate.py",
    "test_multibone_extent_interactive_candidate.py",
    "test_multibone_extent_live_writer_candidate.py",
    "test_multibone_extent_probe.py",
    "test_multibone_extent_production_promotion.py",
    "test_official_character_physical_compatibility.py",
    "test_official_container_entry_recovery.py",
    "test_official_container_record_index.py",
    "test_official_payload_source_locator.py",
    "test_official_update_manifest_pack_correlation.py",
    "test_production_promotion.py",
    "test_tree_compare.py",
    "test_ui_static.py",
    "test_update_tmp_lh5_decode.py",
    "test_update_tmp_lha_forensics.py",
}


def pytest_collection_modifyitems(items):
    if PAYLOAD.is_dir():
        return
    skip = pytest.mark.skip(reason="generated app/payload fixture is not present in a fresh source checkout")
    for item in items:
        path = Path(str(item.fspath))
        if path.name in PREBUILT_PAYLOAD_MODULES:
            item.add_marker(skip)
