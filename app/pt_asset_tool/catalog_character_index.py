from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import re
from collections import defaultdict
from typing import Any

FORMAT = "PT_CATALOG_CHARACTER_INDEX_V1"
PLAYABLE_CLASSES = (
    "Mechanician", "Fighter", "Pikeman", "Archer", "Knight",
    "Atalanta", "Priestess", "Magician", "Assassin", "Shaman",
)

# Source-backed class config families (same contract used by
# player_class_motion_contract.py/entity_catalog.py). These are stronger than
# clothing/texture filename folklore.
_CONFIG_PATTERNS = {
    "Mechanician": (re.compile(r"^a\d+$", re.I), re.compile(r"^ca\d+$", re.I)),
    "Fighter": (re.compile(r"^b\d+$", re.I), re.compile(r"^cb\d+$", re.I)),
    "Pikeman": (re.compile(r"^c\d+$", re.I), re.compile(r"^cc\d+$", re.I)),
    "Archer": (re.compile(r"^d\d+$", re.I), re.compile(r"^cd\d+$", re.I)),
    "Knight": (re.compile(r"^ma\d+$", re.I), re.compile(r"^cma\d+$", re.I)),
    "Atalanta": (re.compile(r"^mb\d+$", re.I), re.compile(r"^cmb\d+$", re.I)),
    "Priestess": (re.compile(r"^mc\d+$", re.I), re.compile(r"^cmc\d+$", re.I)),
    "Magician": (re.compile(r"^md\d+$", re.I), re.compile(r"^cmd\d+$", re.I)),
    "Assassin": (re.compile(r"^e\d+$", re.I), re.compile(r"^ce\d+$", re.I)),
    "Shaman": (re.compile(r"^me\d+$", re.I), re.compile(r"^cme\d+$", re.I)),
}

IMAGE_EXTS = {".bmp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".webp"}


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def class_from_config(path: str) -> str | None:
    stem = pathlib.PurePosixPath(_norm(path)).stem
    for class_name, patterns in _CONFIG_PATTERNS.items():
        if any(p.fullmatch(stem) for p in patterns):
            return class_name
    return None


def community_filename_hint(path: str) -> str | None:
    """Conservative tmABCD clothing hint; never used as sole authoritative owner.

    Community documentation maps t/m + body/head + class letter naming. We keep
    only the unambiguous classic class letters used by this project's ten-class
    source contract. The persisted dependency/config graph remains authoritative.
    """
    name = pathlib.PurePosixPath(_norm(path)).stem
    m = re.search(r"(?i)t[mf][bh]([abcde])", name)
    if not m:
        return None
    return {
        "a": "Mechanician", "b": "Fighter", "c": "Pikeman",
        "d": "Archer", "e": "Assassin",
    }.get(m.group(1).casefold())


def _stat_key(path: pathlib.Path | None) -> list[int]:
    if path is None:
        return [0, 0]
    try:
        st = path.stat()
        return [int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [0, 0]


def _load_inventory(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_graph(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_ref(ref: str, source: str, records: dict[str, dict[str, Any]]) -> str | None:
    raw = _norm(ref)
    if not raw:
        return None
    if raw.casefold() in records:
        return str(records[raw.casefold()].get("relative_path") or raw)
    parent = pathlib.PurePosixPath(source).parent
    candidates = [raw]
    if "/" not in raw:
        candidates.insert(0, (parent / raw).as_posix())
    if not pathlib.PurePosixPath(raw).suffix:
        for ext in (".bmp", ".tga", ".dds", ".png", ".smd", ".inx"):
            candidates.append(raw + ext)
            if "/" not in raw:
                candidates.append((parent / (raw + ext)).as_posix())
    for candidate in candidates:
        rec = records.get(candidate.casefold())
        if rec:
            return str(rec.get("relative_path") or candidate)
    return None


def build_character_index(inventory: dict[str, Any], pairing_path: pathlib.Path, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph or {}
    recs = [x for x in inventory.get("records") or [] if isinstance(x, dict)]
    records = {_norm(x.get("relative_path")).casefold(): x for x in recs if _norm(x.get("relative_path"))}

    evidence: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    model_owner: dict[str, set[str]] = defaultdict(set)

    try:
        with pairing_path.open("r", encoding="utf-8-sig", newline="") as fh:
            pairing = list(csv.DictReader(fh))
    except Exception:
        pairing = []

    # Source-proven config family -> physically paired SMD is authoritative.
    for row in pairing:
        model = _norm(row.get("model_smd"))
        inx = _norm(row.get("inx"))
        if not model or not inx:
            continue
        owner = class_from_config(inx)
        if not owner:
            continue
        model_owner[model.casefold()].add(owner)
        evidence[model.casefold()][owner].append(f"SOURCE_CONFIG_FAMILY:{inx}")

    # Propagate only through direct material texture references from an owned SMD.
    for model_key, owners in list(model_owner.items()):
        if len(owners) != 1:
            continue
        owner = next(iter(owners))
        rec = records.get(model_key) or {}
        model_rel = _norm(rec.get("relative_path")) or model_key
        for ref in rec.get("texture_refs") or []:
            target = _resolve_ref(str(ref), model_rel, records)
            if not target:
                continue
            evidence[target.casefold()][owner].append(f"SMD_MATERIAL_TEXLINK:{model_rel}")

    # Reuse enhancement dependency graph client_asset_reference edges. Restrict
    # propagation to image targets to avoid assigning shared skeleton/motion files
    # to a single class.
    owner_by_model = {k: next(iter(v)) for k, v in model_owner.items() if len(v) == 1}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict) or str(edge.get("relation") or "") != "client_asset_reference":
            continue
        src = str(edge.get("src") or "")
        dst = str(edge.get("dst") or "")
        if not src.casefold().startswith("client:") or not dst.casefold().startswith("client:"):
            continue
        src_rel = _norm(src.split(":", 1)[1])
        owner = owner_by_model.get(src_rel.casefold())
        if not owner:
            continue
        dst_rel = _norm(dst.split(":", 1)[1])
        if pathlib.PurePosixPath(dst_rel).suffix.casefold() not in IMAGE_EXTS:
            continue
        if dst_rel.casefold() in records:
            evidence[dst_rel.casefold()][owner].append(f"DEPENDENCY_GRAPH:{src_rel}")

    # Preserve filename convention only as a hint when stronger evidence is absent.
    hints: dict[str, str] = {}
    for rec in recs:
        rel = _norm(rec.get("relative_path"))
        if not rel or rel.casefold() in evidence:
            continue
        hint = community_filename_hint(rel)
        if hint:
            hints[rel.casefold()] = hint

    by_path: dict[str, dict[str, Any]] = {}
    for rec in recs:
        rel = _norm(rec.get("relative_path"))
        if not rel:
            continue
        per_owner = evidence.get(rel.casefold()) or {}
        owners = sorted(per_owner, key=str.casefold)
        if len(owners) == 1:
            owner = owners[0]
            by_path[rel.casefold()] = {
                "path": rel,
                "owner": owner,
                "candidates": owners,
                "status": "PROVEN",
                "evidence": sorted(set(per_owner[owner]), key=str.casefold),
                "filename_hint": hints.get(rel.casefold()),
            }
        elif len(owners) > 1:
            by_path[rel.casefold()] = {
                "path": rel,
                "owner": "",
                "candidates": owners,
                "status": "AMBIGUOUS",
                "evidence": sorted({e for rows in per_owner.values() for e in rows}, key=str.casefold),
                "filename_hint": hints.get(rel.casefold()),
            }
        elif rel.casefold() in hints:
            by_path[rel.casefold()] = {
                "path": rel,
                "owner": "",
                "candidates": [hints[rel.casefold()]],
                "status": "FILENAME_HINT_ONLY",
                "evidence": ["COMMUNITY_FILENAME_HINT"],
                "filename_hint": hints[rel.casefold()],
            }

    return {
        "format": FORMAT,
        "status": "PASS",
        "by_path": by_path,
        "classes": list(PLAYABLE_CLASSES),
        "proven_count": sum(1 for x in by_path.values() if x.get("status") == "PROVEN"),
        "ambiguous_count": sum(1 for x in by_path.values() if x.get("status") == "AMBIGUOUS"),
        "hint_only_count": sum(1 for x in by_path.values() if x.get("status") == "FILENAME_HINT_ONLY"),
        "sources": {"inventory": True, "pairing": bool(pairing), "dependency_graph": bool(graph.get("edges"))},
    }


def load_or_build_character_index(*, inventory_path: pathlib.Path, pairing_path: pathlib.Path, graph_path: pathlib.Path | None, cache_path: pathlib.Path) -> tuple[dict[str, Any], bool]:
    key = {
        "inventory": _stat_key(inventory_path),
        "pairing": _stat_key(pairing_path),
        "graph": _stat_key(graph_path),
    }
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cached = None
    if isinstance(cached, dict) and cached.get("format") == FORMAT and cached.get("cache_key") == key and isinstance(cached.get("index"), dict):
        return cached["index"], True
    index = build_character_index(_load_inventory(inventory_path), pairing_path, _load_graph(graph_path))
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"format": FORMAT, "cache_key": key, "index": index}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(tmp, cache_path)
    except Exception:
        pass
    return index, False
