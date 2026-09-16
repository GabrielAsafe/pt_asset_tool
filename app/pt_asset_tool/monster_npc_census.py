#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Iterable

VERSION = "1.0.0"
FORMAT = "PT_ASSET_MONSTER_NPC_CENSUS_V1"
DEFAULT_CENSUS_REL = pathlib.Path("pt_build/semantic_asset_census_current.json")
DEPS_EXT = {".smd", ".smb", ".inx", ".inf", ".bmp", ".tga", ".png", ".jpg", ".wav", ".ase"}
PRIMARY_EXT = {".smd", ".smb", ".inx", ".inf"}
TEXTURE_EXT = {".bmp", ".tga", ".png", ".jpg"}
AUDIO_EXT = {".wav"}

ASCII_RUN = re.compile(rb"[A-Za-z0-9_./\\:\- ()\[\]]{3,260}")
ASSET_REF = re.compile(r"(?i)(?:[A-Za-z0-9_./\\:\- ()\[\]]{1,240})\.(?:smd|smb|inx|inf|bmp|tga|png|jpg|wav|ase)")
UTF16_RUN = re.compile(rb"(?:[A-Za-z0-9_./\\:\- ()\[\]]\x00){3,260}")


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
                out[p.relative_to(root).as_posix()] = (int(st.st_size), int(st.st_mtime_ns))
            except OSError:
                pass
    return out


def normalize_path(s: str) -> str:
    s = s.replace("\\", "/").strip("\x00 \t\r\n\"")
    s = re.sub(r"^[A-Za-z]:/", "", s)
    s = s.lstrip("./")
    s = re.sub(r"/+", "/", s)
    return s


def build_index(client: pathlib.Path) -> tuple[dict[str, pathlib.Path], dict[str, list[pathlib.Path]]]:
    by_rel: dict[str, pathlib.Path] = {}
    by_base: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    for p in client.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(client).as_posix()
        by_rel.setdefault(rel.lower(), p)
        by_base[p.name.lower()].append(p)
    return by_rel, by_base


def detect_physical_family(p: pathlib.Path) -> str:
    ext = p.suffix.lower()
    try:
        with p.open("rb") as f:
            head = f.read(96)
    except OSError:
        return "UNREADABLE"
    if ext == ".smd":
        if head.startswith(b"SMD Model data Ver 0.62"):
            return "SMD_MODEL_062"
        if b"0.72" in head[:64]:
            return "SMD_STAGE_072_CANDIDATE"
        return "SMD_OTHER"
    if ext == ".smb":
        return "SMB_ANIMATION_CONTAINER"
    if ext == ".inx":
        return "INX_CONFIG"
    if ext == ".inf":
        return "INF_CONFIG"
    if ext in TEXTURE_EXT:
        return "TEXTURE"
    if ext in AUDIO_EXT:
        return "AUDIO"
    return "OTHER"


def extract_refs(p: pathlib.Path) -> list[str]:
    try:
        data = p.read_bytes()
    except OSError:
        return []
    # Configs are normally small. Cap pathological files to avoid accidental huge scans.
    if len(data) > 32 * 1024 * 1024:
        return []
    found: dict[str, str] = {}
    for m in ASCII_RUN.finditer(data):
        text = m.group(0).decode("latin-1", errors="ignore")
        for a in ASSET_REF.finditer(text):
            ref = normalize_path(a.group(0))
            if pathlib.PurePosixPath(ref).suffix.lower() in DEPS_EXT:
                found.setdefault(ref.lower(), ref)
    for m in UTF16_RUN.finditer(data):
        try:
            text = m.group(0).decode("utf-16le", errors="ignore")
        except Exception:
            continue
        for a in ASSET_REF.finditer(text):
            ref = normalize_path(a.group(0))
            if pathlib.PurePosixPath(ref).suffix.lower() in DEPS_EXT:
                found.setdefault(ref.lower(), ref)
    return sorted(found.values(), key=str.lower)


def resolve_ref(ref: str, by_rel: dict[str, pathlib.Path], by_base: dict[str, list[pathlib.Path]], client: pathlib.Path) -> dict[str, Any]:
    norm = normalize_path(ref)
    candidates = [norm]
    low = norm.lower()
    for marker in ("image/", "char/", "monster/", "npc/", "effect/"):
        i = low.find(marker)
        if i >= 0:
            candidates.append(norm[i:])
    if not low.startswith("image/"):
        candidates.append("image/" + norm)
    seen: set[str] = set()
    for c in candidates:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        p = by_rel.get(k)
        if p:
            return {"ref": ref, "status": "RESOLVED_PATH", "resolved": p.relative_to(client).as_posix()}
    base = pathlib.PurePosixPath(norm).name.lower()
    hits = by_base.get(base, [])
    if len(hits) == 1:
        return {"ref": ref, "status": "RESOLVED_UNIQUE_BASENAME", "resolved": hits[0].relative_to(client).as_posix()}
    if len(hits) > 1:
        return {"ref": ref, "status": "AMBIGUOUS_BASENAME", "candidates": [x.relative_to(client).as_posix() for x in hits[:20]], "candidate_count": len(hits)}
    return {"ref": ref, "status": "UNRESOLVED"}


def get_row_path(row: dict[str, Any]) -> str | None:
    for k in ("relative_path", "logical", "path", "asset"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return normalize_path(v)
    return None


def get_row_group(row: dict[str, Any]) -> str:
    for k in ("semantic_group", "group", "asset_group", "category"):
        v = row.get(k)
        if isinstance(v, str):
            return v.upper()
    role = str(row.get("role") or row.get("semantic_role") or "").upper()
    if "MONSTER" in role:
        return "MONSTER"
    if "NPC" in role:
        return "NPC"
    return "UNKNOWN"


def load_census_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows")
    if isinstance(rows, list):
        return [x for x in rows if isinstance(x, dict)]
    # Defensive fallback: find the largest list of dicts containing path-ish fields.
    best: list[dict[str, Any]] = []
    stack: list[Any] = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            ds = [x for x in cur if isinstance(x, dict) and get_row_path(x)]
            if len(ds) > len(best):
                best = ds
            stack.extend(cur)
    return best


def path_fallback_group(rel: str) -> str:
    low = "/" + rel.lower().strip("/") + "/"
    monster_markers = ("/monster/", "/monsters/", "/sinimage/monster", "/char/monster")
    npc_markers = ("/npc/", "/npcs/", "/sinimage/npc", "/char/npc")
    if any(x in low for x in monster_markers):
        return "MONSTER_PATH_CANDIDATE"
    if any(x in low for x in npc_markers):
        return "NPC_PATH_CANDIDATE"
    return ""


def stem_family(stem: str) -> str:
    s = stem.lower()
    # Remove common numeric/variant tails while keeping lexical identity.
    s = re.sub(r"(?:[_-]?(?:v|lv|ver)?\d+[a-z]?)$", "", s)
    s = re.sub(r"\d+$", "", s)
    return s or stem.lower()


def family_key(group: str, rel: str) -> str:
    p = pathlib.PurePosixPath(rel)
    parent = p.parent.as_posix().lower()
    return f"{group}|{parent}|{stem_family(p.stem)}"


def entity_directory(group: str, rel: str) -> tuple[str, str] | None:
    """Resolve a physical entity folder without claiming runtime identity.

    `char/npc/Ahin/*` -> ("Ahin", "char/npc/Ahin")
    `char/monster/Acero/*` -> ("Acero", "char/monster/Acero")
    """
    parts = pathlib.PurePosixPath(normalize_path(rel)).parts
    low = [x.lower() for x in parts]
    markers = [("char", "npc")] if group == "NPC" else [("char", "monster"), ("char", "monsters")]
    for marker in markers:
        n = len(marker)
        for i in range(0, len(parts) - n):
            if tuple(low[i:i+n]) == marker and i + n < len(parts):
                name = parts[i+n]
                root = "/".join(parts[:i+n+1])
                return name, root
    return None


def _representative_texture_score(entity_name: str, rel: str) -> tuple[int, str]:
    p = pathlib.PurePosixPath(rel)
    stem = p.stem.lower()
    name = entity_name.lower()
    score = 0
    if stem == name:
        score = 100
    elif stem in {f"{name}-up", f"{name}_up", f"{name}-body", f"{name}_body"}:
        score = 90
    elif stem.startswith(name):
        score = 80
    elif "body" in stem:
        score = 60
    elif "head" in stem or stem.endswith("h"):
        score = 50
    return score, rel.lower()


def build_entity_catalog(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for rec in selected:
        info = entity_directory(str(rec.get("semantic_group") or ""), str(rec.get("relative_path") or ""))
        if not info:
            continue
        name, root = info
        group = rec["semantic_group"]
        key = f"{group}|{root.lower()}"
        e = entities.setdefault(key, {
            "entity_key": key,
            "semantic_group": group,
            "display_name": name,
            "folder_root": root,
            "evidence": "PHYSICAL_ENTITY_DIRECTORY",
            "asset_count": 0,
            "model_paths": [],
            "config_paths": [],
            "skeleton_paths": [],
            "texture_paths": [],
            "audio_paths": [],
            "other_paths": [],
            "representative_preview": None,
            "representative_model": None,
            "runtime_status": "UNPROVEN",
            "writer_status": "UNAUTHORIZED",
        })
        rel = rec["relative_path"]
        ext = rec["extension"]
        e["asset_count"] += 1
        if ext == ".smd":
            e["model_paths"].append(rel)
        elif ext in {".inx", ".inf"}:
            e["config_paths"].append(rel)
        elif ext == ".smb":
            e["skeleton_paths"].append(rel)
        elif ext in TEXTURE_EXT:
            e["texture_paths"].append(rel)
        elif ext in AUDIO_EXT:
            e["audio_paths"].append(rel)
        else:
            e["other_paths"].append(rel)

    for e in entities.values():
        for key in ("model_paths", "config_paths", "skeleton_paths", "texture_paths", "audio_paths", "other_paths"):
            e[key] = sorted(set(e[key]), key=str.lower)
        if e["model_paths"]:
            exact = [x for x in e["model_paths"] if pathlib.PurePosixPath(x).stem.lower() == e["display_name"].lower()]
            e["representative_model"] = (exact or e["model_paths"])[0]
        if e["texture_paths"]:
            e["representative_preview"] = sorted(
                e["texture_paths"],
                key=lambda x: (-_representative_texture_score(e["display_name"], x)[0], _representative_texture_score(e["display_name"], x)[1]),
            )[0]
        e["has_model"] = bool(e["model_paths"])
        e["has_config"] = bool(e["config_paths"])
        e["has_skeleton"] = bool(e["skeleton_paths"])
        e["has_preview_candidate"] = bool(e["representative_preview"])
    return sorted(entities.values(), key=lambda x: (x["semantic_group"], x["display_name"].lower()))


def refresh_census(project: pathlib.Path, census: pathlib.Path, client: pathlib.Path) -> None:
    cmd = [sys.executable, str(project / "pt_asset.py"), "audit", "semantic-asset-census", "--client-root", str(client), "--output", str(census)]
    cp = subprocess.run(cmd, cwd=project, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"semantic census refresh failed rc={cp.returncode}")


def inventory(client: pathlib.Path, census_path: pathlib.Path, include_delta_candidates: bool = True) -> dict[str, Any]:
    before = snapshot(client)
    rows = load_census_rows(census_path)
    row_by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        rel = get_row_path(row)
        if rel:
            row_by_path.setdefault(rel.lower(), row)
    by_rel, by_base = build_index(client)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for k, row in row_by_path.items():
        group = get_row_group(row)
        role = str(row.get("role") or row.get("semantic_role") or "")
        if group not in {"MONSTER", "NPC"} and "MONSTER" not in role.upper() and "NPC" not in role.upper():
            continue
        p = by_rel.get(k)
        rel = get_row_path(row) or k
        rec = {
            "relative_path": rel,
            "semantic_group": "MONSTER" if group == "MONSTER" or "MONSTER" in role.upper() else "NPC",
            "evidence": "SEMANTIC_CENSUS",
            "exists": bool(p),
            "extension": pathlib.PurePosixPath(rel).suffix.lower(),
            "physical_family": detect_physical_family(p) if p else str(row.get("physical_family") or "MISSING"),
            "semantic_role": role,
        }
        selected.append(rec); seen.add(k)

    delta_candidates = 0
    if include_delta_candidates:
        for k, p in by_rel.items():
            if k in row_by_path or k in seen:
                continue
            rel = p.relative_to(client).as_posix()
            cand = path_fallback_group(rel)
            if not cand:
                continue
            delta_candidates += 1
            selected.append({
                "relative_path": rel,
                "semantic_group": "MONSTER" if cand.startswith("MONSTER") else "NPC",
                "evidence": cand,
                "exists": True,
                "extension": p.suffix.lower(),
                "physical_family": detect_physical_family(p),
                "semantic_role": "UNPROVEN_DELTA_CANDIDATE",
            })

    # Dependency pass only over configs to remain fast/evidence-based.
    asset_by_rel = {x["relative_path"].lower(): x for x in selected}
    dependency_edges: list[dict[str, Any]] = []
    for rec in selected:
        if rec["extension"] not in {".inx", ".inf"} or not rec["exists"]:
            continue
        p = by_rel.get(rec["relative_path"].lower())
        if not p:
            continue
        refs = extract_refs(p)
        resolved = [resolve_ref(r, by_rel, by_base, client) for r in refs]
        rec["dependency_ref_count"] = len(resolved)
        rec["dependency_resolved_count"] = sum(1 for x in resolved if x["status"].startswith("RESOLVED"))
        rec["dependency_unresolved_count"] = sum(1 for x in resolved if x["status"] == "UNRESOLVED")
        for rr in resolved:
            edge = {"source": rec["relative_path"], **rr}
            dependency_edges.append(edge)

    # Family aggregation.
    fams: dict[str, dict[str, Any]] = {}
    for rec in selected:
        key = family_key(rec["semantic_group"], rec["relative_path"])
        f = fams.setdefault(key, {
            "family_key": key,
            "semantic_group": rec["semantic_group"],
            "asset_count": 0,
            "model_count": 0,
            "skeleton_count": 0,
            "config_count": 0,
            "texture_count": 0,
            "audio_count": 0,
            "missing_count": 0,
            "evidence_counts": collections.Counter(),
            "physical_family_counts": collections.Counter(),
            "asset_sample": [],
        })
        f["asset_count"] += 1
        ext = rec["extension"]
        if ext == ".smd": f["model_count"] += 1
        elif ext == ".smb": f["skeleton_count"] += 1
        elif ext in {".inx", ".inf"}: f["config_count"] += 1
        elif ext in TEXTURE_EXT: f["texture_count"] += 1
        elif ext in AUDIO_EXT: f["audio_count"] += 1
        if not rec["exists"]: f["missing_count"] += 1
        f["evidence_counts"][rec["evidence"]] += 1
        f["physical_family_counts"][rec["physical_family"]] += 1
        if len(f["asset_sample"]) < 20: f["asset_sample"].append(rec["relative_path"])

    # Dependency evidence contributes to family score.
    edges_by_source: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for e in dependency_edges:
        edges_by_source[e["source"].lower()].append(e)
    for f in fams.values():
        sources = [x for x in f["asset_sample"] if pathlib.PurePosixPath(x).suffix.lower() in {".inx", ".inf"}]
        edges = [e for s in sources for e in edges_by_source.get(s.lower(), [])]
        total = len(edges); resolved_n = sum(1 for e in edges if str(e.get("status", "")).startswith("RESOLVED"))
        f["dependency_edge_count_sample"] = total
        f["dependency_resolution_ratio_sample"] = (resolved_n / total) if total else None
        f["binding_status"] = "UNPROVEN"
        f["preview_status"] = "MODEL_CANDIDATE" if f["model_count"] else "NO_MODEL_IN_FAMILY_CLUSTER"
        score = 0
        score += min(f["model_count"], 5) * 8
        score += min(f["config_count"], 5) * 4
        score += min(f["skeleton_count"], 3) * 6
        score += min(f["texture_count"], 10)
        if f["dependency_resolution_ratio_sample"] is not None:
            score += round(f["dependency_resolution_ratio_sample"] * 10)
        score -= min(f["missing_count"], 10) * 2
        f["research_priority_score"] = score
        f["evidence_counts"] = dict(f["evidence_counts"])
        f["physical_family_counts"] = dict(f["physical_family_counts"])

    families = sorted(fams.values(), key=lambda x: (-x["research_priority_score"], x["semantic_group"], x["family_key"]))
    entities = build_entity_catalog(selected)
    after = snapshot(client)
    if before != after:
        raise RuntimeError("CLIENT_CHANGED_DURING_MONSTER_NPC_READ_ONLY_CENSUS")

    census_paths = set(row_by_path)
    current_paths = set(by_rel)
    counts = collections.Counter(x["semantic_group"] for x in selected)
    physical = collections.Counter(x["physical_family"] for x in selected)
    ext_counts = collections.Counter(x["extension"] for x in selected)
    return {
        "format": FORMAT,
        "status": "PASS",
        "version": VERSION,
        "client_root": str(client),
        "client_read_only": True,
        "census_path": str(census_path),
        "census_row_count": len(rows),
        "current_client_file_count": len(current_paths),
        "census_unique_path_count": len(census_paths),
        "census_stale_by_path": bool(current_paths - census_paths),
        "census_stale_by_path_count": len(current_paths - census_paths),
        "current_paths_not_in_census_count": len(current_paths - census_paths),
        "semantic_counts": dict(counts),
        "extension_counts": dict(ext_counts),
        "physical_family_counts": dict(physical),
        "delta_path_candidate_count": delta_candidates,
        "asset_count": len(selected),
        "family_count": len(families),
        "entity_count": len(entities),
        "dependency_edge_count": len(dependency_edges),
        "assets": selected,
        "dependency_edges": dependency_edges,
        "families": families,
        "entities": entities,
        "monster_entities": [x for x in entities if x["semantic_group"] == "MONSTER"],
        "npc_entities": [x for x in entities if x["semantic_group"] == "NPC"],
        "priority_monster_families": [x for x in families if x["semantic_group"] == "MONSTER"][:50],
        "priority_npc_families": [x for x in families if x["semantic_group"] == "NPC"][:50],
        "policy": {
            "write": "integrated read-only catalog census; no client write and no writer authorization",
            "binding": "UNPROVEN until physical SMD/SMB/INX closure is independently validated",
            "preview": "MODEL_CANDIDATE is triage only; Blender preview/runtime compatibility is not claimed",
            "next": "use catalog/physical validators per representative family; runtime/binding remains unproven until separately validated",
        },
    }


def write_outputs(report: dict[str, Any], out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    asset_csv = out.with_name(out.stem + "_assets.csv")
    family_csv = out.with_name(out.stem + "_families.csv")
    entity_csv = out.with_name(out.stem + "_entities.csv")
    md = out.with_suffix(".md")
    with asset_csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["semantic_group", "relative_path", "evidence", "exists", "extension", "physical_family", "semantic_role", "dependency_ref_count", "dependency_resolved_count", "dependency_unresolved_count"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in report["assets"]:
            w.writerow({k: r.get(k, "") for k in fields})
    with family_csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["semantic_group", "family_key", "research_priority_score", "asset_count", "model_count", "skeleton_count", "config_count", "texture_count", "audio_count", "missing_count", "binding_status", "preview_status", "dependency_edge_count_sample", "dependency_resolution_ratio_sample"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in report["families"]:
            w.writerow({k: r.get(k, "") for k in fields})
    with entity_csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["semantic_group", "display_name", "folder_root", "asset_count", "has_model", "has_config", "has_skeleton", "representative_model", "representative_preview", "runtime_status", "writer_status"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in report["entities"]:
            w.writerow({k: r.get(k, "") for k in fields})
    lines = [
        "# PT Asset Tool — Monster/NPC Census", "",
        f"- status: {report['status']}",
        f"- client files: {report['current_client_file_count']}",
        f"- selected Monster/NPC assets: {report['asset_count']}",
        f"- families: {report['family_count']}",
        f"- physical entity folders: {report['entity_count']}",
        f"- dependency edges: {report['dependency_edge_count']}",
        f"- current paths not in census: {report['census_stale_by_path_count']}", "",
        "## Priority MONSTER families",
    ]
    for x in report["priority_monster_families"][:20]:
        lines.append(f"- score={x['research_priority_score']} models={x['model_count']} smb={x['skeleton_count']} cfg={x['config_count']} assets={x['asset_count']} — `{x['family_key']}`")
    lines += ["", "## Priority NPC families"]
    for x in report["priority_npc_families"][:20]:
        lines.append(f"- score={x['research_priority_score']} models={x['model_count']} smb={x['skeleton_count']} cfg={x['config_count']} assets={x['asset_count']} — `{x['family_key']}`")
    lines += ["", "## Physical entity directory catalog"]
    for x in report["entities"][:100]:
        lines.append(f"- {x['semantic_group']} `{x['display_name']}` — assets={x['asset_count']} model={bool(x['has_model'])} config={bool(x['has_config'])} skeleton={bool(x['has_skeleton'])} preview=`{x['representative_preview'] or '—'}`")
    lines += ["", "## Safety", "This integrated census is read-only. It does not authorize writers and does not claim binding/runtime from names alone."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Integrated read-only Monster/NPC catalog census")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--project", default=str(pathlib.Path.cwd()))
    ap.add_argument("--client-root", default=None)
    ap.add_argument("--census", default=None)
    ap.add_argument("--output", default="pt_build/monster_npc_census_v0120.json")
    ap.add_argument("--refresh-census", action="store_true")
    ap.add_argument("--no-delta-candidates", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print(VERSION); return 0
    project = pathlib.Path(a.project).expanduser().resolve()
    if a.client_root:
        client = pathlib.Path(a.client_root).expanduser().resolve()
    else:
        from .app_config import discover_client_root
        client = discover_client_root(project)
    census = pathlib.Path(a.census).expanduser() if a.census else (project / DEFAULT_CENSUS_REL)
    if not census.is_absolute(): census = (project / census).resolve()
    out = pathlib.Path(a.output).expanduser()
    if not out.is_absolute(): out = (project / out).resolve()
    if a.refresh_census:
        refresh_census(project, census, client)
    if not census.is_file():
        legacy = project / "pt_build/semantic_asset_census_v0900.json"
        if legacy.is_file():
            census = legacy
        else:
            # First-run UX: the semantic census is itself a read-only scan, so
            # create it automatically instead of making the user discover a
            # hidden prerequisite and rerun the command manually.
            refresh_census(project, census, client)
    try:
        report = inventory(client, census, include_delta_candidates=not a.no_delta_candidates)
        write_outputs(report, out)
        compact = {k: report[k] for k in ("format", "status", "version", "client_root", "client_read_only", "census_path", "census_row_count", "current_client_file_count", "census_stale_by_path_count", "current_paths_not_in_census_count", "semantic_counts", "extension_counts", "physical_family_counts", "delta_path_candidate_count", "asset_count", "family_count", "entity_count", "dependency_edge_count")}
        compact["priority_monster_families"] = report["priority_monster_families"][:12]
        compact["priority_npc_families"] = report["priority_npc_families"][:12]
        compact["policy"] = report["policy"]
        compact["entity_sample"] = report["entities"][:20]
        compact["outputs"] = {"json": str(out), "assets_csv": str(out.with_name(out.stem + "_assets.csv")), "families_csv": str(out.with_name(out.stem + "_families.csv")), "entities_csv": str(out.with_name(out.stem + "_entities.csv")), "markdown": str(out.with_suffix('.md'))}
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(f"monster_npc_census=PASS assets={report['asset_count']} families={report['family_count']} read_only=true integrated=true")
        return 0
    except Exception as exc:
        fail = {"format": FORMAT, "status": "FAIL", "version": VERSION, "error": f"{type(exc).__name__}:{exc}", "client_read_only": True, "main_tool_modified": True}
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
