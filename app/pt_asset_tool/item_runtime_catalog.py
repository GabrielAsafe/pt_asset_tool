from __future__ import annotations

from typing import Any

from .asset_contract_registry import source_registry

FORMAT = "PT_SOURCE_ITEM_RUNTIME_CATALOG_V2"

# item_catalog.json preserves the historical extraction field names for
# compatibility.  The recovered C++ sITEM constructor proves the exact source
# semantics below.  Do not mutate the V1 contract: normalize it here instead.
_V1_TO_SITEM = {
    "item_position": "class_value",
    "last_category": "dorp_item",
    "class_flags": "set_model_posi",
    "class_id": "sound_index",
    "kind_id": "weapon_class",
}


def normalize_item_catalog_entry(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("code") or "")
    dorp_item = str(row.get("last_category") or "")
    item_file_path = str(row.get("item_file_path") or "")
    normalized = {
        "index": int(row.get("index") or 0),
        "numeric_code": int(row.get("numeric_code") or 0),
        "numeric_code_hex": str(row.get("numeric_code_hex") or ""),
        "item_name_index": str(row.get("item_name_index") or ""),
        # In the recovered sITEM constructor this source field is LastCategory;
        # in this client it is the runtime item identity string (WA121, etc.).
        "code": code,
        "source_member_for_code": "LastCategory",
        "width": int(row.get("width") or 0),
        "height": int(row.get("height") or 0),
        "item_file_path": item_file_path,
        "class_value": int(row.get("item_position") or 0),
        "dorp_item": dorp_item,
        "set_model_posi": int(row.get("class_flags") or 0),
        "sound_index": int(row.get("class_id") or 0),
        "weapon_class": int(row.get("kind_id") or 0),
        "expected_client_paths": {
            "inventory_icon": f"image/Sinimage/Items/{item_file_path}/it{dorp_item}.bmp" if item_file_path and dorp_item else None,
            "drop_model_ase": f"image/Sinimage/Items/DropItem/it{dorp_item}.ASE" if dorp_item else None,
        },
    }
    normalized["source_semantics"] = {
        "constructor": "sITEM(CODE, ItemNameIndex, LastCategory, w, h, ItemFilePath, Class, DorpItem, SetModelPosi, SoundIndex, WeaponClass)",
        "compatibility_aliases": dict(_V1_TO_SITEM),
        "writer_authorized": False,
    }
    return normalized


def item_runtime_catalog() -> dict[str, Any]:
    source = source_registry("item_catalog")
    entries = [normalize_item_catalog_entry(x) for x in source.get("entries") or []]
    return {
        "format": FORMAT,
        "status": "PASS",
        "source": source.get("source"),
        "source_note": source.get("source_note"),
        "record_count": len(entries),
        "entries": entries,
        "compatibility": {
            "source_contract": "item_catalog.json / PT_SOURCE_ITEM_CATALOG_V1",
            "v1_field_names_preserved": True,
            "semantic_adapter_only": True,
        },
    }


def lookup_item_runtime(code: str) -> dict[str, Any]:
    wanted = str(code or "").strip().casefold()
    matches = [x for x in item_runtime_catalog()["entries"] if str(x.get("code") or "").casefold() == wanted]
    return {
        "format": "PT_SOURCE_ITEM_RUNTIME_LOOKUP_V1",
        "status": "SOURCE_VERIFIED" if matches else "NOT_IN_RUNTIME_CATALOG",
        "code": str(code or "").strip(),
        "match_count": len(matches),
        "matches": matches,
        "writer_authorized": False,
    }
