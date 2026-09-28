from __future__ import annotations

"""Source/server-backed selections for the Management Legacy UI.

The browser should not ask an operator to remember runtime item codes or type
existing DataServer identities blindly.  This module exposes read-only choices
from the sources the application already trusts:

* sITEM runtime catalogue -> authoritative item codes/visual identity
* GameServer/OpenItem     -> installed display name + concrete definition path
* DataServer/userdata     -> existing character identities
* DataServer/userinfo     -> existing account identities

No file is created or modified here.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from ..item_runtime_catalog import item_runtime_catalog
from ..legacy_authoring import _inspect_text_definition
from ..legacy_name_catalog import public_authoring_name_catalog

FORMAT = "PT_LEGACY_UI_SELECTIONS_V1"


def _first(parsed: dict[str, Any], field: str) -> str | None:
    rows = (parsed.get("recognized") or {}).get(field) or []
    if not rows or not rows[0]:
        return None
    value = str(rows[0][0]).strip()
    return value or None


def _openitem_root(server_root: Path) -> Path | None:
    candidates = [
        server_root / "GameServer" / "OpenItem",
        server_root / "gameserver" / "OpenItem",
        server_root / "GameServer" / "openitem",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    gs = next((p for p in server_root.iterdir() if p.is_dir() and p.name.casefold() == "gameserver"), None) if server_root.is_dir() else None
    if gs:
        return next((p for p in gs.iterdir() if p.is_dir() and p.name.casefold() == "openitem"), None)
    return None


def _identity_files(server_root: Path, store: str, suffix: str) -> list[str]:
    root = server_root / "DataServer" / store
    if not root.is_dir():
        # DataServer casing is fixed by the current server corpus, but tolerate
        # a case-only variation without guessing other layouts.
        ds = server_root / "DataServer"
        if not ds.is_dir() and server_root.is_dir():
            ds = next((p for p in server_root.iterdir() if p.is_dir() and p.name.casefold() == "dataserver"), ds)
        if ds.is_dir():
            root = next((p for p in ds.iterdir() if p.is_dir() and p.name.casefold() == store.casefold()), root)
    if not root.is_dir():
        return []
    out: set[str] = set()
    for bucket in root.iterdir():
        if not bucket.is_dir():
            continue
        try:
            files = bucket.iterdir()
        except OSError:
            continue
        for p in files:
            if p.is_file() and p.suffix.casefold() == suffix.casefold():
                name = p.stem.strip()
                if name:
                    out.add(name)
    return sorted(out, key=str.casefold)


@lru_cache(maxsize=8)
def _catalog_cached(server_root_text: str) -> dict[str, Any]:
    server_root = Path(server_root_text).expanduser().resolve()
    runtime = item_runtime_catalog()
    by_code: dict[str, dict[str, Any]] = {}
    for row in runtime.get("entries") or []:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        by_code[code.casefold()] = {
            "code": code,
            "name": None,
            "display": code,
            "runtime_verified": True,
            "openitem_present": False,
            "openitem_path": None,
            "dorp_item": row.get("dorp_item"),
            "item_file_path": row.get("item_file_path"),
            "numeric_code_hex": row.get("numeric_code_hex"),
        }

    openitem_root = _openitem_root(server_root)
    read_errors = 0
    openitem_count = 0
    if openitem_root is not None:
        files = sorted(
            (p for p in openitem_root.rglob("*.txt") if "name" not in {x.casefold() for x in p.relative_to(openitem_root).parts[:-1]}),
            key=lambda p: p.as_posix().casefold(),
        )
        for p in files:
            openitem_count += 1
            try:
                detail = _inspect_text_definition("ITEM", p.read_bytes())
            except Exception:
                read_errors += 1
                continue
            code = _first(detail, "code") or p.stem.strip()
            if not code:
                continue
            name = _first(detail, "name")
            key = code.casefold()
            row = by_code.setdefault(key, {
                "code": code,
                "name": None,
                "display": code,
                "runtime_verified": False,
                "openitem_present": False,
                "openitem_path": None,
                "dorp_item": None,
                "item_file_path": None,
                "numeric_code_hex": None,
            })
            row["name"] = name or row.get("name")
            row["openitem_present"] = True
            row["openitem_path"] = p.relative_to(server_root).as_posix()

    items = []
    for row in by_code.values():
        row = dict(row)
        suffix = str(row.get("name") or "").strip()
        if suffix:
            row["display"] = f"{row['code']} — {suffix}"
        elif row.get("openitem_present"):
            row["display"] = f"{row['code']} — OpenItem without Name"
        else:
            row["display"] = f"{row['code']} — without OpenItem"
        items.append(row)
    items.sort(key=lambda x: (str(x.get("name") or "").casefold(), str(x.get("code") or "").casefold()))

    semantic = public_authoring_name_catalog()
    semantic_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in semantic.get("items") or []:
        code = str(row.get("code") or "").strip().casefold()
        if code:
            semantic_by_code.setdefault(code, []).append(row)
    for row in items:
        variants = semantic_by_code.get(str(row.get("code") or "").casefold(), [])
        row["semantic_variant_count"] = len(variants)
        row["semantic_variants"] = [
            {
                "canonical_id": x.get("canonical_id"),
                "display_name": x.get("display_name"),
                "logical_path": x.get("logical_path"),
                "linked_asset": x.get("linked_asset"),
                "confidence": x.get("confidence"),
            }
            for x in variants
        ]
        if len(variants) == 1:
            row["semantic_canonical_id"] = variants[0].get("canonical_id")
            row["semantic_display_name"] = variants[0].get("display_name")
            if not row.get("name") and variants[0].get("display_name"):
                row["display"] = f"{row['code']} — {variants[0]['display_name']}"
        elif len(variants) > 1:
            row["semantic_canonical_id"] = None
            row["semantic_display_name"] = None
            row["display"] = f"{row['code']} — {len(variants)} mapped definitions"

    characters = _identity_files(server_root, "userdata", ".dat")
    accounts = _identity_files(server_root, "userinfo", ".dat")
    return {
        "format": FORMAT,
        "status": "PASS",
        "server_root": str(server_root),
        "semantic_catalog": {
            "format": semantic.get("format"),
            "title": semantic.get("title"),
            "generated_from": semantic.get("generated_from"),
            "counts": semantic.get("counts"),
            "important_correction": semantic.get("important_correction"),
        },
        "authoring_catalog": {
            "items": semantic.get("items") or [],
            "mobs": semantic.get("mobs") or [],
            "npcs": semantic.get("npcs") or [],
            "maps": semantic.get("maps") or [],
            "spawn_stages": semantic.get("spawn_stages") or [],
            "ambiguous": semantic.get("ambiguous") or [],
        },
        "items": items,
        "item_count": len(items),
        "runtime_item_count": sum(1 for x in items if x.get("runtime_verified")),
        "openitem_count": openitem_count,
        "openitem_read_errors": read_errors,
        "characters": characters,
        "character_count": len(characters),
        "accounts": accounts,
        "account_count": len(accounts),
        "read_only": True,
    }


def selection_catalog(server_root: Path, *, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        _catalog_cached.cache_clear()
    return _catalog_cached(str(Path(server_root).expanduser().resolve()))
