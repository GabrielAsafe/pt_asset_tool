from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from .legacy_apps.reverse_manifest import reverse_status

FORMAT = "PT_LEGACY_MANAGEMENT_CONTRACT_RUNTIME_V1"


def _data_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "contracts" / "legacy_management_tools.json"


def load_legacy_management_contract() -> dict[str, Any]:
    data = json.loads(_data_path().read_text(encoding="utf-8"))
    if data.get("format") != "PT_LEGACY_MANAGEMENT_CONTRACT_V1":
        raise RuntimeError("LEGACY_MANAGEMENT_CONTRACT_FORMAT_INVALID")
    tools = list(data.get("tools") or [])
    if not tools:
        raise RuntimeError("LEGACY_MANAGEMENT_CONTRACT_TOOLS_EMPTY")
    return data


def parse_pritator_config(path: pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path)
    text = path.read_text(encoding="cp1252", errors="replace")
    sections: dict[str, dict[str, str]] = {}
    globals_: dict[str, str] = {}
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "<End>":
            section = None
            continue
        if line.endswith(":") and "=" not in line:
            section = line[:-1]
            sections.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        target = sections.setdefault(section, {}) if section else globals_
        target[key.strip()] = value.strip()
    return {"globals": globals_, "sections": sections}


def item_taxonomy_rows() -> list[dict[str, Any]]:
    return [dict(x) for x in load_legacy_management_contract().get("item_taxonomy") or []]


def classify_item_code(code: str) -> dict[str, Any]:
    raw = str(code or "").strip()
    upper = raw.upper()
    matches: list[dict[str, Any]] = []
    for row in item_taxonomy_rows():
        for prefix in row.get("prefixes") or []:
            p = str(prefix).upper()
            if upper.startswith(p):
                matches.append({**row, "matched_prefix": p, "matched_prefix_length": len(p)})
    if not matches:
        return {
            "code": raw,
            "status": "UNCLASSIFIED",
            "group": None,
            "category": None,
            "matched_prefix": None,
            "ambiguous": False,
        }
    longest = max(int(x["matched_prefix_length"]) for x in matches)
    best = [x for x in matches if int(x["matched_prefix_length"]) == longest]
    categories = {(str(x.get("group")), str(x.get("name"))) for x in best}
    chosen = best[0]
    return {
        "code": raw,
        "status": "LEGACY_PREFIX_CLASSIFIED" if len(categories) == 1 else "LEGACY_PREFIX_AMBIGUOUS",
        "group": chosen.get("group") if len(categories) == 1 else None,
        "category": chosen.get("name") if len(categories) == 1 else None,
        "matched_prefix": chosen.get("matched_prefix") if len(categories) == 1 else None,
        "ambiguous": len(categories) != 1,
        "candidates": [
            {"group": x.get("group"), "category": x.get("name"), "prefix": x.get("matched_prefix")}
            for x in best
        ],
    }


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_management_root(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).expanduser().resolve()
    contract = load_legacy_management_contract()
    rows: list[dict[str, Any]] = []
    expected_names: dict[str, dict[str, Any]] = {}
    for tool in contract.get("tools") or []:
        expected_names[str(tool["name"]).casefold()] = tool
        for alias in tool.get("aliases") or []:
            expected_names[str(alias).casefold()] = tool

    for name_cf, tool in sorted(expected_names.items()):
        expected_name = next((n for n in [tool.get("name"), *(tool.get("aliases") or [])] if str(n).casefold() == name_cf), str(tool.get("name")))
        path = root / expected_name
        if not path.is_file():
            rows.append({"file": expected_name, "status": "MISSING", "expected_sha256": tool.get("sha256")})
            continue
        actual = _sha256(path)
        rows.append({
            "file": expected_name,
            "status": "MATCH" if actual == tool.get("sha256") else "HASH_MISMATCH",
            "expected_sha256": tool.get("sha256"),
            "actual_sha256": actual,
            "size": path.stat().st_size,
        })

    config = root / "PriTaTor.Config.txt"
    config_row: dict[str, Any] = {"present": config.is_file()}
    if config.is_file():
        actual = _sha256(config)
        config_row.update({
            "sha256": actual,
            "expected_sha256": "a9303c85bfb7f38d2c9c4a145d64252feda7fc06b40d61db558a7e8e8b9cf287",
            "status": "MATCH" if actual == "a9303c85bfb7f38d2c9c4a145d64252feda7fc06b40d61db558a7e8e8b9cf287" else "HASH_MISMATCH",
            "parsed": parse_pritator_config(config),
        })
    return {
        "format": FORMAT,
        "status": "PASS",
        "root": str(root),
        "files": rows,
        "match_count": sum(1 for x in rows if x["status"] == "MATCH"),
        "missing_count": sum(1 for x in rows if x["status"] == "MISSING"),
        "mismatch_count": sum(1 for x in rows if x["status"] == "HASH_MISMATCH"),
        "pritator_config": config_row,
        "executed_legacy_binaries": False,
    }


def legacy_management_summary() -> dict[str, Any]:
    data = load_legacy_management_contract()
    return {
        "format": FORMAT,
        "status": "PASS",
        "evidence": data.get("evidence"),
        "tool_count": len(data.get("tools") or []),
        "tools": data.get("tools") or [],
        "item_taxonomy": data.get("item_taxonomy") or [],
        "workflows": data.get("workflows") or {},
        "safety": data.get("safety") or {},
        "operational_replacements": reverse_status(),
        "operational_status_source": "pt_asset_tool.legacy_apps.reverse_manifest",
        "historical_contract_role": "PROVENANCE_AND_INTERNAL_TAXONOMY_ONLY",
    }
