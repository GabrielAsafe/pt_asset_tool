from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from collections import defaultdict
from typing import Any, Iterable

from .app_config import configured_contract_donor_clients, configured_contract_donor_servers
from .canonical_authoring import stage_canonical_document_set
from .general_asset_recovery import recover_closed_general_asset_bundles
from .summit_canonical import SummitCanonicalContentProvider, sha256_file

FORMAT = "PT_ASSET_DONOR_RECOVERY_EXPLORER_V1"

_DOMAIN_ROOTS = {
    "server": {
        "MAP_FIELD": ("GameServer/Field",),
        "MONSTER": ("GameServer/Monster",),
        "NPC": ("GameServer/NPC",),
        "ITEM": ("GameServer/OpenItem",),
    },
    "client": {
        "CHARACTER": ("char", "Char"),
        "EFFECT": ("Effect", "image/Sinimage/Effect", "image/SinImage/Effect", "game/scripts/particles"),
        "MAP_FIELD": ("Field", "field"),
        "ITEM": ("image/Sinimage/items", "image/SinImage/items"),
    },
}

_SERVER_DOMAIN_SIGNATURE_EXTENSIONS = {
    # Strong server-side definition signatures. Root inference is only a fast
    # path: recursive fallback still searches the configured donor root.
    "MAP_FIELD": {".spm", ".spp", ".spc"},
    "MONSTER": {".inf"},
    "NPC": {".npc"},
    "ITEM": {".txt"},
}

_SERVER_DOMAIN_ALLOWED_EXTENSIONS = {
    # Keep server semantic domains strict so client mirrors/geometry cannot be
    # promoted into server authoring candidates merely because they live under
    # the configured donor root.
    "MAP_FIELD": {".spm", ".spp", ".spc"},
    "MONSTER": {".inf"},
    "NPC": {".npc"},
    "ITEM": {".txt"},
}


def _field_entity_key_from_name(name: str) -> str:
    value = pathlib.PurePosixPath(_norm(name)).name
    low = value.casefold()
    for suffix in (".spm", ".spp", ".spc"):
        if low.endswith(suffix):
            value = value[:-len(suffix)]
            low = value.casefold()
            break
    for suffix in (".ase", ".smd", ".tga", ".bmp", ".dds", ".png", ".jpg", ".jpeg"):
        if low.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return value.casefold()


def _canonical_map_identity_index(source_root: pathlib.Path | None) -> dict[str, dict[str, Any]]:
    """Index canonical maps by exact stage basename.

    This is an identity/evidence index, not an alias table.  It deliberately
    refuses fuzzy matching: e.g. lostisland (field 37) and lost_temple (38)
    must never be treated as donor aliases for lost3 (51) merely because their
    names are similar.
    """
    if source_root is None:
        return {}
    path = pathlib.Path(source_root).resolve() / "Content" / "canonical" / "maps" / "server.maps.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("maps") or []:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "").replace("\\", "/")
        key = _field_entity_key_from_name(stage)
        if not key:
            continue
        identity = {
            "match_basis": "CANONICAL_STAGE_BASENAME_EXACT",
            "entity_key": key,
            "map_id": row.get("id"),
            "legacy_field_code": row.get("legacy_field_code"),
            "canonical_stage": stage,
            "map_image_id": row.get("map_image_id"),
        }
        previous = out.get(key)
        if previous is not None and previous != identity:
            raise ValueError(f"CANONICAL_MAP_STAGE_BASENAME_COLLISION:{key}")
        out[key] = identity
    return out


def _annotate_map_field_identity(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> None:
    if str(row.get("domain") or "").upper() != "MAP_FIELD":
        return
    key = str(row.get("entity_key") or "").casefold()
    identity = index.get(key)
    if identity is None:
        row["canonical_field_identity"] = {
            "match_basis": "NO_EXACT_CANONICAL_STAGE_IDENTITY",
            "entity_key": key,
        }
        row["spawn_recovery_certified"] = False
        return
    row["canonical_field_identity"] = copy.deepcopy(identity)
    row["spawn_recovery_certified"] = bool(
        str(row.get("side") or "").upper() == "SERVER"
        and str(row.get("field_kind") or "").upper() == "SPM"
    )


def _norm(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    rel = pathlib.PurePosixPath(_norm(value))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"DONOR_RELATIVE_PATH_INVALID:{value}")
    return rel


def _parse_specs(values: Iterable[str], side: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text or "=" not in text:
            continue
        label, root = text.split("=", 1)
        label = label.strip().upper()
        path = pathlib.Path(root.strip()).expanduser().resolve()
        rows.append({"label": label, "side": side, "root": path, "present": path.is_dir()})
    return rows


def donor_pairs(project_root: pathlib.Path) -> list[dict[str, Any]]:
    project = pathlib.Path(project_root).resolve()
    clients = _parse_specs(configured_contract_donor_clients(project), "client")
    servers = _parse_specs(configured_contract_donor_servers(project), "server")
    by: dict[str, dict[str, Any]] = {}
    for row in [*clients, *servers]:
        item = by.setdefault(row["label"], {"label": row["label"], "client": None, "server": None})
        # Same label across client/server is the intended logical pairing.
        item[row["side"]] = {"root": str(row["root"]), "present": bool(row["present"])}
    return [by[k] for k in sorted(by)]


def _ci_child(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path | None:
    cur = root
    for part in rel.parts:
        exact = cur / part
        if exact.exists():
            cur = exact
            continue
        if not cur.is_dir():
            return None
        matches = [p for p in cur.iterdir() if p.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        cur = matches[0]
    return cur


def _domain_root_candidates(root: pathlib.Path, side: str, domain: str) -> list[pathlib.PurePosixPath]:
    """Return layout candidates relative to a configured donor root.

    Donor server roots are heterogeneous in the real corpus: some point to the
    server root (containing GameServer/), while others already point to a
    game-server/GameServer directory (containing Field/, Monster/, ...).  The
    Explorer must accept both without changing the configured donor identity.
    """
    out: list[pathlib.PurePosixPath] = []
    seen: set[str] = set()
    for raw in _DOMAIN_ROOTS.get(side, {}).get(domain, ()):
        rel = pathlib.PurePosixPath(raw)
        candidates = [rel]
        if side == "server":
            parts = list(rel.parts)
            tail = pathlib.PurePosixPath(*parts[1:]) if parts and parts[0].casefold() == "gameserver" else rel
            candidates.extend([tail, pathlib.PurePosixPath("game-server") / rel, pathlib.PurePosixPath("game-server") / tail])
        for cand in candidates:
            key = cand.as_posix().casefold()
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def _signature_domain_roots(root: pathlib.Path, side: str, domain: str, *, max_depth: int = 8) -> list[pathlib.Path]:
    if side != "server" or not root.is_dir():
        return []
    extensions = _SERVER_DOMAIN_SIGNATURE_EXTENSIONS.get(domain, set())
    if not extensions:
        return []
    found: list[pathlib.Path] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        try:
            depth = len(here.relative_to(root).parts)
        except ValueError:
            continue
        if depth >= max_depth:
            dirnames[:] = []
        # Avoid caches/VCS/build metadata while still accepting arbitrary donor
        # layouts such as Files/Server/game-server/data/GameServer/Field.
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".cache"}]
        if any(pathlib.Path(name).suffix.casefold() in extensions for name in filenames):
            found.append(here.resolve())
    # If both an ancestor and descendant contain signature files, scan both:
    # each directory contributes its own field metadata and _scan_domain never
    # recursively starts from the configured donor root itself.
    return found


def _domain_roots(root: pathlib.Path, side: str, domain: str) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    seen: set[str] = set()
    direct: list[pathlib.Path] = []
    for rel in _domain_root_candidates(root, side, domain):
        p = _ci_child(root, rel)
        if p is not None and p.is_dir():
            direct.append(p.resolve())
    for p in [*direct, *_signature_domain_roots(root, side, domain)]:
        key = str(p.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            out.append(p.resolve())
    return out


def _scan_diagnostic(root: pathlib.Path, side: str, domain: str) -> dict[str, Any]:
    direct = []
    for rel in _domain_root_candidates(root, side, domain):
        p = _ci_child(root, rel)
        if p is not None and p.is_dir():
            direct.append(p.resolve())
    signature = _signature_domain_roots(root, side, domain)
    resolved = _domain_roots(root, side, domain)
    return {
        "configured_root": str(root.resolve()),
        "present": root.is_dir(),
        "candidate_layouts": [x.as_posix() for x in _domain_root_candidates(root, side, domain)],
        "direct_scan_roots": [str(x) for x in direct],
        "signature_scan_roots": [str(x) for x in signature],
        "resolved_scan_roots": [str(x) for x in resolved],
        "state": "READY" if resolved else "NO_DOMAIN_ROOT",
    }


def _domain_file_allowed(side: str, domain: str, path: pathlib.Path) -> bool:
    allowed = _SERVER_DOMAIN_ALLOWED_EXTENSIONS.get(domain) if side == "server" else None
    if allowed is not None:
        return path.suffix.casefold() in allowed
    return True


def _decode_legacy_definition(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp949", "cp1252"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin1", errors="replace"), "latin1"


def _definition_query_evidence(path: pathlib.Path, query: str, domain: str) -> dict[str, Any] | None:
    # Match semantic server definitions by path or legacy text payload.  Korean
    # CP949 display names routinely differ from the definition filename.
    q = str(query or "").strip()
    if not q:
        return {"match_basis": "NO_QUERY"}
    if q.casefold() in path.as_posix().casefold():
        return {"match_basis": "PATH_SUBSTRING"}
    if domain not in {"MONSTER", "NPC", "ITEM"}:
        return None
    try:
        data = path.read_bytes()[:2 * 1024 * 1024]
    except OSError:
        return None
    try:
        raw_q = q.encode("cp949")
    except UnicodeEncodeError:
        raw_q = b""
    if raw_q and raw_q in data:
        return {"match_basis": "LEGACY_CP949_BYTES_EXACT", "encoding": "cp949"}
    text, encoding = _decode_legacy_definition(data)
    if q.casefold() in text.casefold():
        return {"match_basis": "DEFINITION_TEXT_EXACT", "encoding": encoding}
    return None


def _definition_name_evidence(path: pathlib.Path, domain: str) -> dict[str, Any]:
    if domain not in {"MONSTER", "NPC", "ITEM"}:
        return {}
    try:
        data = path.read_bytes()[:2 * 1024 * 1024]
    except OSError:
        return {}
    text, encoding = _decode_legacy_definition(data)
    names: list[str] = []
    # Quoted name-like directives are display/search evidence only; canonical
    # import remains the authority for identity and writer semantics.
    for line in text.splitlines():
        if "name" not in line.casefold():
            continue
        m = re.search(r"[\"']([^\"'\r\n]{1,160})[\"']", line)
        if m:
            value = m.group(1).strip()
            if value and value not in names:
                names.append(value)
        if len(names) >= 8:
            break
    return {"definition_encoding": encoding, "definition_name_evidence": names}


def _classify_field_file(path: pathlib.Path) -> str:
    low = path.name.casefold()
    if low.endswith(".spm"):
        return "SPM"
    if low.endswith(".spp"):
        return "SPP"
    if low.endswith(".spc"):
        return "SPC"
    if low.endswith((".ase", ".smd", ".spc", ".spp", ".spm")):
        return "STAGE"
    return "OTHER"


def _entity_identity(relative_path: str, domain: str) -> tuple[str, str]:
    rel = pathlib.PurePosixPath(_norm(relative_path))
    parts = list(rel.parts)
    low = [x.casefold() for x in parts]
    domain = domain.upper()
    if domain == "MAP_FIELD":
        # A field is one logical entity across client stage/model/map/title assets
        # and server SPM/SPP/SPC companions.  Prefer the filename identity so
        # Field/Lost/lost3.smd and GameServer/Field/lost3.ASE.spm converge.
        name = rel.name
        low_name = name.casefold()
        for suffix in (".spm", ".spp", ".spc"):
            if low_name.endswith(suffix):
                name = name[:-len(suffix)]
                low_name = name.casefold()
                break
        for suffix in (".ase", ".smd", ".tga", ".bmp", ".dds", ".png", ".jpg", ".jpeg"):
            if low_name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        if rel.parent.name.casefold() == "title" and name.casefold().endswith("t") and len(name) > 1:
            name = name[:-1]
        return _field_entity_key_from_name(name), name
    if domain in {"MONSTER", "NPC", "ITEM"}:
        name = rel.stem
        return name.casefold(), name
    if domain == "CHARACTER":
        try:
            idx = low.index("char")
            tail = parts[idx + 1:]
        except ValueError:
            tail = parts
        if len(tail) >= 2:
            label = "/".join(tail[:2])
        elif tail:
            label = tail[0]
        else:
            label = rel.stem
        return label.casefold(), label
    if domain == "EFFECT":
        # Effects are often bundles: group by parent directory, falling back to file stem.
        parent = rel.parent.as_posix()
        label = parent if parent not in {".", ""} else rel.stem
        for prefix in ("Effect/", "effect/", "image/Sinimage/Effect/", "image/SinImage/Effect/"):
            if label.casefold().startswith(prefix.casefold()):
                label = label[len(prefix):]
                break
        return label.casefold(), label
    label = rel.stem
    return label.casefold(), label


def _node(root: pathlib.Path, path: pathlib.Path, *, donor: str, side: str, domain: str) -> dict[str, Any]:
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    entity_key, entity_label = _entity_identity(rel, domain)
    row = {
        "donor": donor,
        "side": side.upper(),
        "domain": domain,
        "entity_key": entity_key,
        "entity_label": entity_label,
        "relative_path": rel,
        "name": path.name,
        "extension": path.suffix,
        "bytes": path.stat().st_size,
        "field_kind": _classify_field_file(path) if domain == "MAP_FIELD" else None,
    }
    if side == "server" and domain in {"MONSTER", "NPC", "ITEM"}:
        row.update(_definition_name_evidence(path, domain))
    return row


def _comparison_tree(donors: list[dict[str, Any]], domains: list[str]) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {d: {} for d in domains}
    for donor in donors:
        for domain, payload in (donor.get("domains") or {}).items():
            if domain not in grouped:
                grouped[domain] = {}
            for row in payload.get("nodes") or []:
                key = str(row.get("entity_key") or row.get("relative_path") or "").casefold()
                entity = grouped[domain].setdefault(key, {
                    "entity_key": key,
                    "label": row.get("entity_label") or row.get("name") or key,
                    "variants": [],
                    "donor_labels": set(),
                    "has_target": False,
                })
                variant = copy.deepcopy(row)
                entity["variants"].append(variant)
                entity["donor_labels"].add(str(row.get("donor") or ""))
                if str(row.get("donor") or "").upper() == "SUMMIT":
                    entity["has_target"] = True
    result: dict[str, Any] = {}
    for domain, entities in grouped.items():
        rows = []
        for entity in entities.values():
            entity["donor_labels"] = sorted(entity["donor_labels"])
            entity["variants"].sort(key=lambda x: (str(x.get("donor") or "").casefold(), str(x.get("side") or ""), str(x.get("relative_path") or "").casefold()))
            entity["variant_count"] = len(entity["variants"])
            entity["donor_count"] = len(entity["donor_labels"])
            rows.append(entity)
        rows.sort(key=lambda x: str(x.get("label") or "").casefold())
        result[domain] = {"entity_count": len(rows), "entities": rows}
    return result


def _deep_signature_scan(
    root: pathlib.Path,
    side: str,
    domain: str,
    *,
    donor: str,
    query: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    """Last-resort read-only scan of the configured donor root.

    Root inference is intentionally an optimization, never an authority.  Real
    Priston donor trees can contain arbitrary wrapper directories or be rooted
    above/below the traditional GameServer directory.  If inferred roots yield
    no rows, walk the configured root itself and select files by a strong domain
    signature.  This is fail-closed: only extensions explicitly allowed for the
    server domain are admitted, and symlinked files are not followed outside the
    configured donor tree.
    """
    allowed = _SERVER_DOMAIN_ALLOWED_EXTENSIONS.get(domain) if side == "server" else None
    meta = {
        "used": bool(allowed),
        "configured_root": str(root.resolve()),
        "directories_scanned": 0,
        "signature_files_seen": 0,
        "query_matches": 0,
        "truncated": False,
    }
    if not allowed or not root.is_dir():
        return [], False, meta
    q = query.casefold().strip()
    root_resolved = root.resolve()
    rows: list[dict[str, Any]] = []
    skip_dirs = {".git", "__pycache__", ".cache", "node_modules"}
    for dirpath, dirnames, filenames in os.walk(root_resolved, followlinks=False):
        meta["directories_scanned"] += 1
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        here = pathlib.Path(dirpath)
        for name in filenames:
            path = here / name
            if path.suffix.casefold() not in allowed:
                continue
            meta["signature_files_seen"] += 1
            if path.is_symlink():
                continue
            try:
                rel_text = path.relative_to(root_resolved).as_posix()
            except ValueError:
                continue
            evidence = _definition_query_evidence(path, query, domain) if q else {"match_basis": "NO_QUERY"}
            if q and evidence is None:
                continue
            row = _node(root_resolved, path, donor=donor, side=side, domain=domain)
            if evidence:
                row["query_match"] = evidence
            rows.append(row)
            meta["query_matches"] += 1
            if len(rows) >= limit:
                meta["truncated"] = True
                return rows, True, meta
    return rows, False, meta


def _scan_domain(
    root: pathlib.Path,
    side: str,
    domain: str,
    *,
    donor: str,
    query: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    q = query.casefold().strip()
    rows: list[dict[str, Any]] = []
    truncated = False
    seen: set[str] = set()
    for base in _domain_roots(root, side, domain):
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if not _domain_file_allowed(side, domain, path):
                continue
            resolved = path.resolve()
            try:
                rel_text = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            evidence = _definition_query_evidence(path, query, domain) if q else {"match_basis": "NO_QUERY"}
            if q and evidence is None:
                continue
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            row = _node(root, path, donor=donor, side=side, domain=domain)
            if evidence:
                row["query_match"] = evidence
            rows.append(row)
            if len(rows) >= limit:
                truncated = True
                return rows, truncated, {"used": False}

    # Inferred scan roots are only a fast path.  If they produced no matching
    # rows, do one exhaustive signature scan of the configured server donor.
    # This is what makes layouts such as wrapper/.../game-server/... recoverable
    # without baking every historical directory convention into the Explorer.
    if not rows and side == "server" and domain in _SERVER_DOMAIN_SIGNATURE_EXTENSIONS:
        fallback_rows, fallback_truncated, meta = _deep_signature_scan(
            root, side, domain, donor=donor, query=query, limit=limit
        )
        return fallback_rows, fallback_truncated, meta
    return rows, truncated, {"used": False}


def _closed_recovery_map(project: pathlib.Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    path = project / "pt_build" / "general_asset_census" / "recovery_bundles.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in data.get("rows") or []:
        if not isinstance(row, dict) or str(row.get("status") or "").upper() != "CLOSED":
            continue
        side = str(row.get("side") or "").upper()
        root = _norm(row.get("root_path") or "").casefold()
        donor = str(row.get("donor_label") or row.get("selected_source") or "").upper()
        if side and root and donor:
            out[(side, root, donor)] = row
    return out

def build_donor_explorer(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    source_root: pathlib.Path | None = None,
    domain: str = "",
    query: str = "",
    donor: str = "",
    limit: int = 1500,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    domains = [domain.upper()] if domain else ["MAP_FIELD", "MONSTER", "NPC", "ITEM", "CHARACTER", "EFFECT"]
    recovery_map = _closed_recovery_map(project)
    canonical_map_index = _canonical_map_identity_index(source_root)
    logical: list[dict[str, Any]] = [{
        "label": "SUMMIT",
        "client": {"root": str(pathlib.Path(client_root).resolve()), "present": pathlib.Path(client_root).is_dir()},
        "server": {"root": str(pathlib.Path(server_root).resolve()), "present": pathlib.Path(server_root).is_dir()},
        "target": True,
    }]
    logical.extend({**x, "target": False} for x in donor_pairs(project))
    wanted = donor.strip().upper()
    if wanted:
        logical = [x for x in logical if x["label"] == wanted]
    out_donors = []
    remaining = max(1, int(limit))
    for item in logical:
        out = {"label": item["label"], "target": bool(item.get("target")), "client": item.get("client"), "server": item.get("server"), "domains": {}}
        out["scan_diagnostics"] = {}
        for dom in domains:
            dom_rows: list[dict[str, Any]] = []
            truncated = False
            out["scan_diagnostics"][dom] = {}
            for side in ("client", "server"):
                info = item.get(side)
                if not info:
                    out["scan_diagnostics"][dom][side.upper()] = {"state": "UNCONFIGURED"}
                    continue
                root = pathlib.Path(str(info["root"]))
                out["scan_diagnostics"][dom][side.upper()] = _scan_diagnostic(root, side, dom)
                if not info.get("present") or remaining <= 0:
                    continue
                rows, hit_limit, fallback_meta = _scan_domain(root, side, dom, donor=item["label"], query=query, limit=remaining)
                if fallback_meta.get("used"):
                    diag = out["scan_diagnostics"][dom][side.upper()]
                    diag["fallback_recursive_scan"] = fallback_meta
                    if rows:
                        diag["state"] = "READY_FALLBACK_RECURSIVE"
                    elif int(fallback_meta.get("signature_files_seen") or 0) == 0:
                        diag["state"] = "NO_SIGNATURE_FILES_ANYWHERE"
                    elif query:
                        diag["state"] = "SIGNATURE_FILES_PRESENT_NO_QUERY_MATCH"
                    else:
                        diag["state"] = "NO_DOMAIN_ROWS"
                for row in rows:
                    if dom == "MAP_FIELD":
                        _annotate_map_field_identity(row, canonical_map_index)
                    key = (str(row["side"]).upper(), _norm(row["relative_path"]).casefold(), str(item["label"]).upper())
                    bundle = recovery_map.get(key)
                    if bundle is not None:
                        row["closed_recovery_bundle"] = {
                            "status": "CLOSED", "side": bundle.get("side"), "root_path": bundle.get("root_path"),
                            "donor_label": bundle.get("donor_label") or bundle.get("selected_source"),
                            "member_count": len(bundle.get("members") or []),
                        }
                dom_rows.extend(rows)
                remaining -= len(rows)
                truncated = truncated or hit_limit or remaining <= 0
            if dom_rows or not query:
                out["domains"][dom] = {"count": len(dom_rows), "truncated": truncated, "nodes": dom_rows}
        out_donors.append(out)
        if remaining <= 0:
            break
    query_key = _field_entity_key_from_name(query) if domain.upper() == "MAP_FIELD" and query else ""
    query_identity = copy.deepcopy(canonical_map_index.get(query_key)) if query_key else None
    return {
        "format": FORMAT,
        "status": "PASS",
        "query": query,
        "domain": domain.upper() or None,
        "limit": int(limit),
        "donors": out_donors,
        "entity_tree": _comparison_tree(out_donors, domains),
        "map_field_query_identity": query_identity,
        "policy": {
            "same_label_client_server_is_one_logical_donor": True,
            "read_only_tree": True,
            "recovery_requires_explicit_staging": True,
            "canonical_domains_use_semantic_import_not_blind_copy": True,
            "map_field_spawn_recovery_requires_exact_canonical_stage_identity": True,
            "fuzzy_map_name_similarity_never_certifies_spawn_recovery": True,
        },
    }




def _fold_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _iter_server_domain_files(root: pathlib.Path, domain: str) -> Iterable[pathlib.Path]:
    """Yield unique server-domain files independent of historical layout."""
    allowed = _SERVER_DOMAIN_ALLOWED_EXTENSIONS.get(domain, set())
    if not allowed or not root.is_dir():
        return
    seen: set[str] = set()
    for base in _domain_roots(root, "server", domain):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in allowed:
                continue
            key = str(path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            yield path.resolve()
    # Complete the evidence search from the configured donor root. A direct
    # root may exist while another wrapper subtree contains the needed entry.
    for dirpath, dirnames, filenames in os.walk(root.resolve(), followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".cache", "node_modules"}]
        here = pathlib.Path(dirpath)
        for name in filenames:
            path = here / name
            if path.suffix.casefold() not in allowed or path.is_symlink():
                continue
            key = str(path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            yield path.resolve()


def _monster_dependency_candidates(project_root: pathlib.Path, unresolved: list[dict[str, Any]], *, preferred_donor: str = "", max_per_name: int = 12) -> list[dict[str, Any]]:
    pairs = donor_pairs(project_root)
    pref = preferred_donor.strip().upper()
    out: list[dict[str, Any]] = []
    donor_files: dict[str, tuple[pathlib.Path, list[pathlib.Path]]] = {}
    for donor in pairs:
        info = donor.get("server")
        if not info or not info.get("present"):
            continue
        root = pathlib.Path(str(info["root"])).resolve()
        donor_files[donor["label"]] = (root, list(_iter_server_domain_files(root, "MONSTER")))

    for dep in unresolved:
        name = str(dep.get("name") or "").strip()
        folded = _fold_identity(name)
        tokens = [x for x in folded.split() if len(x) >= 3]
        hex_value = str(dep.get("legacy_name_bytes_hex") or "").strip()
        try:
            legacy_bytes = bytes.fromhex(hex_value) if hex_value else name.encode("cp949")
        except (ValueError, UnicodeEncodeError):
            legacy_bytes = b""
        matches: list[dict[str, Any]] = []
        for label, (root, paths) in donor_files.items():
            for path in paths:
                try:
                    data = path.read_bytes()[:2 * 1024 * 1024]
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                candidate = _fold_identity(path.stem)
                basis = ""
                score = 0
                encoding = ""
                if legacy_bytes and legacy_bytes in data:
                    basis = "LEGACY_NAME_BYTES_EXACT"
                    score = 300
                    encoding = "cp949-bytes"
                else:
                    text, encoding = _decode_legacy_definition(data)
                    if name and name.casefold() in text.casefold():
                        basis = "DEFINITION_TEXT_EXACT"
                        score = 240
                    else:
                        exactish = bool(folded) and (folded in candidate or candidate in folded)
                        token_hit = bool(tokens) and all(t in candidate for t in tokens)
                        if exactish or token_hit:
                            basis = "FILENAME_HINT_ONLY"
                            score = 80 + (40 if exactish else 0) + sum(len(t) for t in tokens if t in candidate)
                if not basis:
                    continue
                if label == pref:
                    score += 100
                matches.append({
                    "donor_label": label,
                    "relative_path": rel,
                    "score": score,
                    "match_basis": basis,
                    "definition_encoding": encoding,
                    "action": "MONSTER",
                })
        matches.sort(key=lambda x: (-int(x["score"]), str(x["donor_label"]), str(x["relative_path"]).casefold()))
        out.append({**dep, "candidates": matches[:max_per_name]})
    return out


def _selected_donor_root(project_root: pathlib.Path, label: str, side: str) -> pathlib.Path:
    wanted = str(label or "").strip().upper()
    side = side.lower()
    if side not in {"client", "server"}:
        raise ValueError("DONOR_SIDE_INVALID")
    for row in donor_pairs(project_root):
        if row["label"] == wanted:
            info = row.get(side)
            if not info or not info.get("present"):
                raise FileNotFoundError(f"DONOR_ROOT_NOT_AVAILABLE:{wanted}:{side}")
            return pathlib.Path(str(info["root"])).resolve()
    raise KeyError(f"DONOR_LABEL_NOT_CONFIGURED:{wanted}")


def _resolve_donor_file(root: pathlib.Path, relative_path: str) -> tuple[pathlib.Path, pathlib.PurePosixPath]:
    rel = _safe_rel(relative_path)
    path = _ci_child(root, rel)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"DONOR_FILE_NOT_FOUND:{root}:{rel.as_posix()}")
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError("DONOR_FILE_OUTSIDE_ROOT")
    return resolved, pathlib.PurePosixPath(resolved.relative_to(root.resolve()).as_posix())


def _server_logical_path(rel: pathlib.PurePosixPath) -> pathlib.PurePosixPath:
    parts = list(rel.parts)
    lower = [x.casefold() for x in parts]
    if "gameserver" in lower:
        idx = lower.index("gameserver")
        return pathlib.PurePosixPath(*parts[idx:])
    if "game-server" in lower:
        idx = lower.index("game-server") + 1
        tail = parts[idx:]
        if tail and tail[0].casefold() == "gameserver":
            return pathlib.PurePosixPath(*tail)
        if tail and tail[0].casefold() in {"field", "monster", "npc", "openitem"}:
            return pathlib.PurePosixPath("GameServer", *tail)
    if parts and parts[0].casefold() in {"field", "monster", "npc", "openitem"}:
        return pathlib.PurePosixPath("GameServer", *parts)
    for marker in ("field", "monster", "npc", "openitem"):
        if marker in lower:
            idx = lower.index(marker)
            return pathlib.PurePosixPath("GameServer", *parts[idx:])
    raise ValueError(f"DONOR_SERVER_LOGICAL_PATH_UNRECOGNIZED:{rel.as_posix()}")


def _run_tool(cmd: list[str], cwd: pathlib.Path) -> dict[str, Any]:
    cp = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"DONOR_CANONICAL_TOOL_FAILED:{pathlib.Path(cmd[1]).name}:{cp.returncode}:{cp.stdout[-4000:]}")
    return {"command": cmd, "returncode": cp.returncode, "output": cp.stdout[-12000:]}


def _import_workspace(project_root: pathlib.Path, donor_label: str, source: pathlib.Path) -> pathlib.Path:
    token = hashlib.sha256((donor_label + "|" + str(source) + "|" + sha256_file(source)).encode("utf-8")).hexdigest()[:16]
    root = pathlib.Path(project_root).resolve() / "pt_build" / "donor_recovery_explorer" / token
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _merge_index(index_doc: dict[str, Any], entry: dict[str, Any], *, path_key: str = "logical_path") -> dict[str, Any]:
    out = copy.deepcopy(index_doc)
    docs = out.get("documents")
    if not isinstance(docs, list):
        raise ValueError("CANONICAL_INDEX_DOCUMENTS_REQUIRED")
    key = str(entry.get(path_key) or "").replace("\\", "/").casefold()
    entry_id = str(entry.get("id") or "").strip()
    matches = [i for i, row in enumerate(docs) if isinstance(row, dict) and str(row.get(path_key) or "").replace("\\", "/").casefold() == key]
    if len(matches) > 1:
        raise ValueError(f"CANONICAL_INDEX_DUPLICATE_RUNTIME_PATH:{entry.get(path_key)}")
    id_matches = [
        i for i, row in enumerate(docs)
        if isinstance(row, dict) and entry_id and str(row.get("id") or "").strip() == entry_id
    ]
    if len(id_matches) > 1:
        raise ValueError(f"CANONICAL_INDEX_DUPLICATE_ID:{entry_id}")
    if matches:
        old = docs[matches[0]]
        if str(old.get("id") or "") != entry_id:
            raise ValueError(f"CANONICAL_INDEX_ID_CONFLICT:{old.get('id')}:{entry_id}")
        if id_matches and id_matches[0] != matches[0]:
            raise ValueError(f"CANONICAL_INDEX_ID_RELOCATED:{entry_id}:{old.get(path_key)}:{entry.get(path_key)}")
        docs[matches[0]] = copy.deepcopy(entry)
    else:
        if id_matches:
            previous = docs[id_matches[0]]
            raise ValueError(f"CANONICAL_INDEX_ID_RELOCATED:{entry_id}:{previous.get(path_key)}:{entry.get(path_key)}")
        docs.append(copy.deepcopy(entry))
    docs.sort(key=lambda x: str(x.get(path_key) or x.get("legacy_path") or "").casefold())
    return out


def stage_spawn_from_donor(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    *,
    donor_label: str,
    relative_path: str,
    run_validation: bool = True,
    run_build: bool = True,
    preview_only: bool = False,
) -> dict[str, Any]:
    donor_root = _selected_donor_root(project_root, donor_label, "server")
    source, rel = _resolve_donor_file(donor_root, relative_path)
    if source.suffix.casefold() != ".spm":
        raise ValueError("DONOR_STAGE_SPAWN_REQUIRES_SPM")
    logical = _server_logical_path(rel)
    if "field" not in [x.casefold() for x in logical.parts]:
        raise ValueError("DONOR_STAGE_SPAWN_OUTSIDE_GAMESERVER_FIELD")
    identity_index = _canonical_map_identity_index(provider.source_root)
    field_key = _field_entity_key_from_name(logical.name)
    identity = identity_index.get(field_key)
    if identity is None:
        raise ValueError(f"DONOR_STAGE_SPAWN_IDENTITY_NOT_CERTIFIED:{logical.as_posix()}")
    tools = provider.source_root / "tools" / "content_port"
    required = [tools / "import_corpus.py", tools / "canonicalize_stage_spawns.py"]
    if any(not x.is_file() for x in required):
        raise FileNotFoundError("DONOR_STAGE_SPAWN_IMPORT_TOOLS_NOT_FOUND")
    work = _import_workspace(project_root, donor_label, source)
    corpus = work / "corpus"
    corpus_file = corpus / "Servidor" / pathlib.Path(*logical.parts)
    corpus_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, corpus_file)
    shadow = work / "shadow"
    canonical_out = work / "canonical_stage_spawns"
    logs = [
        _run_tool([sys.executable, str(tools / "import_corpus.py"), "--corpus", str(corpus), "--source-root", str(provider.source_root), "--out", str(shadow)], provider.source_root),
        _run_tool([sys.executable, str(tools / "canonicalize_stage_spawns.py"), "--shadow", str(shadow), "--canonical-text", str(provider.canonical_root / "text"), "--out", str(canonical_out)], provider.source_root),
    ]
    idx = json.loads((canonical_out / "index.json").read_text(encoding="utf-8"))
    docs = [x for x in idx.get("documents", []) if isinstance(x, dict)]
    if len(docs) != 1:
        raise ValueError(f"DONOR_STAGE_SPAWN_IMPORT_EXPECTED_ONE:{len(docs)}")
    entry = docs[0]
    doc_path = canonical_out / pathlib.PurePosixPath(str(entry["json_path"]))
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    unresolved = []
    for actor in doc.get("actors") or []:
        if not actor.get("monster_id"):
            unresolved.append({"role": "actor", "name": actor.get("legacy_name"), "legacy_name_bytes_hex": actor.get("legacy_name_bytes_hex"), "resolution": actor.get("resolution")})
    for boss in doc.get("bosses") or []:
        if not boss.get("master_monster_id"):
            unresolved.append({"role": "boss_master", "name": boss.get("master_legacy_name"), "legacy_name_bytes_hex": boss.get("master_legacy_name_bytes_hex"), "resolution": boss.get("master_resolution")})
        if not boss.get("slave_monster_id"):
            unresolved.append({"role": "boss_slave", "name": boss.get("slave_legacy_name"), "legacy_name_bytes_hex": boss.get("slave_legacy_name_bytes_hex"), "resolution": boss.get("slave_resolution")})
    if unresolved:
        return {
            "format": FORMAT,
            "status": "BLOCKED_DEPENDENCIES",
            "action": "STAGE_SPAWN",
            "donor_label": donor_label.upper(),
            "donor_relative_path": rel.as_posix(),
            "donor_sha256": sha256_file(source),
            "logical_path": logical.as_posix(),
            "dependency_gate": {
                "status": "BLOCKED",
                "unresolved": _monster_dependency_candidates(project_root, unresolved, preferred_donor=donor_label),
                "actor_count": len(doc.get("actors") or []),
                "boss_count": len(doc.get("bosses") or []),
                "requirement": "IMPORT_OR_RECONCILE_EVERY_MONSTER_DEPENDENCY_THEN_RETRY_SPAWN",
            },
            "converted_preview": doc,
            "converter_logs": logs,
        }

    if preview_only:
        return {
            "format": FORMAT,
            "status": "READY_FOR_STAGE",
            "action": "STAGE_SPAWN",
            "donor_label": donor_label.upper(),
            "donor_relative_path": rel.as_posix(),
            "donor_sha256": sha256_file(source),
            "logical_path": logical.as_posix(),
            "canonical_map_identity": identity,
            "dependency_gate": {
                "status": "PASS", "unresolved": [],
                "actor_count": len(doc.get("actors") or []),
                "boss_count": len(doc.get("bosses") or []),
            },
            "converted_preview": doc,
            "converter_logs": logs,
        }

    target_rel = pathlib.PurePosixPath("canonical/stage_spawns") / pathlib.PurePosixPath(str(entry["json_path"]))
    index_path = provider.canonical_root / "stage_spawns" / "index.json"
    current_index = json.loads(index_path.read_text(encoding="utf-8"))
    merged_index = _merge_index(current_index, entry, path_key="logical_path")
    result = stage_canonical_document_set(
        project_root, provider,
        [
            {"relative_path": target_rel.as_posix(), "document": doc},
            {"relative_path": "canonical/stage_spawns/index.json", "document": merged_index},
        ],
        kind="STAGE_SPAWN",
        canonical_id=str(doc.get("id") or ""),
        provenance={
            "origin": "DONOR_STAGE_SPAWN",
            "donor_label": donor_label.upper(),
            "donor_side": "SERVER",
            "donor_root": str(donor_root),
            "canonical_map_identity": identity,
            "donor_relative_path": rel.as_posix(),
            "donor_sha256": sha256_file(source),
            "logical_path": logical.as_posix(),
            "converter_logs": logs,
        },
        run_validation=run_validation,
        run_build=run_build,
    )
    result["canonical_id"] = str(doc.get("id") or "")
    result["canonical_path"] = target_rel.as_posix()
    result["dependency_gate"] = {"status": "PASS", "unresolved": [], "actor_count": len(doc.get("actors") or []), "boss_count": len(doc.get("bosses") or [])}
    return result


def _prepare_definition_import(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    *,
    donor_label: str,
    relative_path: str,
    kind: str,
) -> dict[str, Any]:
    kind = kind.upper()
    expected_kind = {"MONSTER": "monster_definition", "NPC": "npc_definition", "ITEM": "open_item_definition"}.get(kind)
    if expected_kind is None:
        raise ValueError("DONOR_DEFINITION_KIND_UNSUPPORTED")
    donor_root = _selected_donor_root(project_root, donor_label, "server")
    source, rel = _resolve_donor_file(donor_root, relative_path)
    logical = _server_logical_path(rel)
    tools = provider.source_root / "tools" / "content_port"
    required = [tools / "import_corpus.py", tools / "canonicalize_text_content.py"]
    if any(not x.is_file() for x in required):
        raise FileNotFoundError("DONOR_DEFINITION_IMPORT_TOOLS_NOT_FOUND")
    work = _import_workspace(project_root, donor_label, source)
    corpus = work / "corpus"
    corpus_file = corpus / "Servidor" / pathlib.Path(*logical.parts)
    corpus_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, corpus_file)
    shadow = work / "shadow"
    canonical_out = work / "canonical_text"
    logs = [
        _run_tool([sys.executable, str(tools / "import_corpus.py"), "--corpus", str(corpus), "--source-root", str(provider.source_root), "--out", str(shadow)], provider.source_root),
        _run_tool([sys.executable, str(tools / "canonicalize_text_content.py"), "--shadow", str(shadow), "--corpus", str(corpus), "--out", str(canonical_out)], provider.source_root),
    ]
    idx = json.loads((canonical_out / "index.json").read_text(encoding="utf-8"))
    entries = [x for x in idx.get("documents", []) if isinstance(x, dict) and x.get("kind") == expected_kind]
    if len(entries) != 1:
        raise ValueError(f"DONOR_DEFINITION_IMPORT_EXPECTED_ONE:{expected_kind}:{len(entries)}")
    entry = entries[0]
    doc = json.loads((canonical_out / pathlib.PurePosixPath(str(entry["json_path"]))).read_text(encoding="utf-8"))
    target_rel = pathlib.PurePosixPath("canonical/text") / pathlib.PurePosixPath(str(entry["json_path"]))
    return {
        "kind": kind, "entry": entry, "document": doc, "target_rel": target_rel,
        "donor_root": donor_root, "source": source, "relative_path": rel, "logical_path": logical, "converter_logs": logs,
    }


def stage_definition_from_donor(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    *,
    donor_label: str,
    relative_path: str,
    kind: str,
    replace_existing: bool = False,
    run_validation: bool = True,
    run_build: bool = True,
) -> dict[str, Any]:
    prepared = _prepare_definition_import(
        project_root, provider, donor_label=donor_label, relative_path=relative_path, kind=kind
    )
    kind = prepared["kind"]
    entry = prepared["entry"]
    doc = prepared["document"]
    target_rel = prepared["target_rel"]
    donor_root = prepared["donor_root"]
    source = prepared["source"]
    rel = prepared["relative_path"]
    logical = prepared["logical_path"]
    logs = prepared["converter_logs"]
    target = provider.content_root / pathlib.Path(*target_rel.parts)
    if target.is_file():
        current = json.loads(target.read_text(encoding="utf-8"))
        if current == doc:
            return {"format": FORMAT, "status": "ALREADY_CANONICAL", "canonical_id": doc.get("id"), "canonical_path": target_rel.as_posix()}
        if not replace_existing:
            raise ValueError(f"DONOR_DEFINITION_CANONICAL_CONFLICT:{doc.get('id')}:{target_rel.as_posix()}")
    index_path = provider.canonical_root / "text" / "index.json"
    current_index = json.loads(index_path.read_text(encoding="utf-8"))
    merged_index = _merge_index(current_index, entry, path_key="legacy_path")
    result = stage_canonical_document_set(
        project_root, provider,
        [
            {"relative_path": target_rel.as_posix(), "document": doc},
            {"relative_path": "canonical/text/index.json", "document": merged_index},
        ],
        kind=kind,
        canonical_id=str(doc.get("id") or ""),
        provenance={
            "origin": "DONOR_DEFINITION",
            "donor_label": donor_label.upper(), "donor_side": "SERVER", "donor_root": str(donor_root),
            "donor_relative_path": rel.as_posix(), "donor_sha256": sha256_file(source), "logical_path": logical.as_posix(),
            "converter_logs": logs,
        },
        run_validation=run_validation,
        run_build=run_build,
    )
    result["canonical_id"] = str(doc.get("id") or "")
    result["canonical_path"] = target_rel.as_posix()
    return result


def stage_unique_spawn_dependencies_from_donor(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    *,
    donor_label: str,
    relative_path: str,
    run_validation: bool = True,
    run_build: bool = True,
) -> dict[str, Any]:
    preview = stage_spawn_from_donor(
        project_root, provider, donor_label=donor_label, relative_path=relative_path,
        run_validation=False, run_build=False, preview_only=True,
    )
    gate = preview.get("dependency_gate") or {}
    unresolved = gate.get("unresolved") or []
    if not unresolved:
        return {
            "format": FORMAT, "status": "NO_DEPENDENCIES_TO_IMPORT",
            "spawn": {k: preview.get(k) for k in ("donor_label", "donor_relative_path", "logical_path")},
            "requirement": "RETRY_STAGE_SPAWN",
        }

    auto: dict[tuple[str, str], dict[str, Any]] = {}
    ambiguous: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous_keys: set[tuple[str, str]] = set()
    unique_dependencies: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    preferred = donor_label.strip().upper()
    for dep in unresolved:
        all_exact = [c for c in (dep.get("candidates") or []) if c.get("match_basis") == "LEGACY_NAME_BYTES_EXACT"]
        # Preserve lineage: automatic recovery may only pull definitions from the same
        # logical donor as the selected SPM. Other donors remain review evidence.
        exact = [c for c in all_exact if str(c.get("donor_label") or "").upper() == preferred]
        uniq = {(preferred, str(c.get("relative_path") or "")): c for c in exact}
        exact = list(uniq.values())
        if len(exact) == 1:
            cand = exact[0]
            key = (preferred, str(cand["relative_path"]))
            auto[key] = cand
            unique_dependencies[key].append({
                "role": dep.get("role"), "name": dep.get("name"),
                "legacy_name_bytes_hex": dep.get("legacy_name_bytes_hex"), "candidate": cand,
            })
        elif len(exact) > 1:
            for cand in exact:
                ambiguous_keys.add((preferred, str(cand["relative_path"])))
            ambiguous.append({
                "role": dep.get("role"), "name": dep.get("name"),
                "legacy_name_bytes_hex": dep.get("legacy_name_bytes_hex"), "candidates": exact,
                "other_donor_exact_candidates": [c for c in all_exact if c not in exact],
                "requirement": "SELECT_ONE_EXACT_DEFINITION_EXPLICITLY",
            })
        else:
            missing.append({
                "role": dep.get("role"), "name": dep.get("name"),
                "legacy_name_bytes_hex": dep.get("legacy_name_bytes_hex"),
                "candidates": dep.get("candidates") or [],
                "requirement": "NO_UNIQUE_EXACT_DEFINITION_IN_SELECTED_DONOR",
            })

    # If a physical definition participates in any ambiguous dependency, do not
    # auto-stage it merely because another role happened to make it unique.
    withheld: list[dict[str, Any]] = []
    for key in ambiguous_keys:
        auto.pop(key, None)
        for dep in unique_dependencies.get(key, []):
            withheld.append({**dep, "requirement": "CANDIDATE_ALSO_PARTICIPATES_IN_AMBIGUOUS_DEPENDENCY"})
    selected = sorted(auto.values(), key=lambda c: (str(c["donor_label"]), str(c["relative_path"]).casefold()))
    if not selected:
        return {
            "format": FORMAT, "status": "REVIEW_REQUIRED", "action": "STAGE_SPAWN_DEPENDENCIES",
            "spawn": {k: preview.get(k) for k in ("donor_label", "donor_relative_path", "logical_path")},
            "auto_stageable": [], "ambiguous": ambiguous, "withheld_due_to_ambiguity": withheld, "missing": missing,
            "policy": {"auto_requires_unique_legacy_name_bytes_exact": True, "fuzzy_candidates_never_auto_staged": True},
        }

    current_index_path = provider.canonical_root / "text" / "index.json"
    merged_index = json.loads(current_index_path.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    converter_logs: list[dict[str, Any]] = []
    for cand in selected:
        prepared = _prepare_definition_import(
            project_root, provider, donor_label=str(cand["donor_label"]), relative_path=str(cand["relative_path"]), kind="MONSTER"
        )
        entry = prepared["entry"]; doc = prepared["document"]; target_rel = prepared["target_rel"]
        target = provider.content_root / pathlib.Path(*target_rel.parts)
        if target.is_file():
            current = json.loads(target.read_text(encoding="utf-8"))
            if current == doc:
                already.append({"canonical_id": doc.get("id"), "canonical_path": target_rel.as_posix(), **cand})
                continue
            conflicts.append({"canonical_id": doc.get("id"), "canonical_path": target_rel.as_posix(), **cand})
            continue
        try:
            merged_index = _merge_index(merged_index, entry, path_key="legacy_path")
        except (ValueError, KeyError) as exc:
            conflicts.append({"canonical_id": doc.get("id"), "canonical_path": target_rel.as_posix(), "error": str(exc), **cand})
            continue
        changes.append({"relative_path": target_rel.as_posix(), "document": doc})
        imported.append({"canonical_id": doc.get("id"), "canonical_path": target_rel.as_posix(), **cand})
        converter_logs.extend(prepared["converter_logs"])

    if conflicts:
        return {
            "format": FORMAT, "status": "BLOCKED_CANONICAL_CONFLICTS", "action": "STAGE_SPAWN_DEPENDENCIES",
            "spawn": {k: preview.get(k) for k in ("donor_label", "donor_relative_path", "logical_path")},
            "auto_stageable": selected, "imported_preview": imported, "already_canonical": already,
            "ambiguous": ambiguous, "withheld_due_to_ambiguity": withheld, "missing": missing, "conflicts": conflicts,
            "policy": {"partial_stage_on_conflict": False},
        }
    if not changes:
        return {
            "format": FORMAT, "status": "REVIEW_REQUIRED" if (ambiguous or missing) else "ALREADY_CANONICAL",
            "action": "STAGE_SPAWN_DEPENDENCIES",
            "spawn": {k: preview.get(k) for k in ("donor_label", "donor_relative_path", "logical_path")},
            "auto_stageable": selected, "already_canonical": already, "ambiguous": ambiguous, "withheld_due_to_ambiguity": withheld, "missing": missing,
        }

    changes.append({"relative_path": "canonical/text/index.json", "document": merged_index})
    result = stage_canonical_document_set(
        project_root, provider, changes, kind="MONSTER_DEPENDENCY_SET",
        canonical_id=str(preview.get("converted_preview", {}).get("id") or ""),
        provenance={
            "origin": "DONOR_SPAWN_DEPENDENCY_BATCH", "spawn_donor_label": donor_label.upper(),
            "spawn_donor_relative_path": preview.get("donor_relative_path"),
            "spawn_donor_sha256": preview.get("donor_sha256"), "logical_path": preview.get("logical_path"),
            "auto_selected_basis": "LEGACY_NAME_BYTES_EXACT_UNIQUE", "imported": imported,
            "already_canonical": already, "ambiguous": ambiguous, "missing": missing, "converter_logs": converter_logs,
        },
        run_validation=run_validation, run_build=run_build,
    )
    result["dependency_batch"] = {
        "auto_staged": imported, "already_canonical": already, "ambiguous": ambiguous, "withheld_due_to_ambiguity": withheld, "missing": missing,
        "remaining_review_count": len(ambiguous) + len(withheld) + len(missing),
        "requirement": "PUBLISH_THIS_CANONICAL_TRANSACTION_THEN_REVIEW_AMBIGUITIES_AND_RETRY_SPAWN",
    }
    return result


PHYSICAL_APPLY_CONFIRM = "APPLY CLOSED DONOR BUNDLE"
PHYSICAL_RESTORE_CONFIRM = "RESTORE CLOSED DONOR BUNDLE"
PHYSICAL_TRANSACTION_FORMAT = "PT_ASSET_DONOR_PHYSICAL_RECOVERY_TRANSACTION_V1"


def _closed_bundle_selection(project_root: pathlib.Path, *, donor_label: str, expected_side: str, expected_root: str) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    key = (str(expected_side or "").upper(), _norm(expected_root).casefold(), str(donor_label or "").upper())
    bundle = _closed_recovery_map(project).get(key)
    if bundle is None:
        raise ValueError(f"DONOR_CLOSED_BUNDLE_SELECTION_NOT_FOUND:{key[0]}:{expected_root}:{key[2]}")
    return bundle


def _write_physical_transaction(project_root: pathlib.Path, result: dict[str, Any], *, donor_label: str) -> pathlib.Path:
    tx = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    root = pathlib.Path(project_root).resolve() / "pt_build" / "donor_recovery_explorer" / "physical_transactions" / tx
    root.mkdir(parents=True, exist_ok=False)
    files = []
    for row in result.get("transactions") or []:
        if not row.get("written"):
            continue
        files.append({
            "side": row.get("side"),
            "relative_path": row.get("relative_path"),
            "target_path": row.get("target_path"),
            "sha256": row.get("sha256"),
            "size": row.get("size"),
            "donor_label": row.get("donor_label"),
            "source_path": row.get("source_path"),
        })
    if not files:
        raise RuntimeError("DONOR_PHYSICAL_TRANSACTION_HAS_NO_WRITTEN_FILES")
    manifest = {
        "format": PHYSICAL_TRANSACTION_FORMAT,
        "tx": tx,
        "state": "APPLIED_VERIFIED",
        "created_at": time.time(),
        "donor_label": donor_label.upper(),
        "client_root": result.get("client_root"),
        "server_root": result.get("server_root"),
        "scope_roots": result.get("scope_roots") or [],
        "files": files,
        "policy": {
            "create_only": True,
            "restore_requires_unchanged_hashes": True,
            "canonical_domains_not_authorized": True,
        },
    }
    path = root / "transaction.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def apply_physical_closed_bundle(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    source_root: pathlib.Path | str | None,
    reference_source_root: pathlib.Path | str | None,
    donor_label: str,
    expected_side: str,
    expected_root: str,
    confirm: str,
) -> dict[str, Any]:
    if str(confirm or "") != PHYSICAL_APPLY_CONFIRM:
        raise PermissionError(f"DONOR_PHYSICAL_CONFIRMATION_REQUIRED:{PHYSICAL_APPLY_CONFIRM}")
    _closed_bundle_selection(project_root, donor_label=donor_label, expected_side=expected_side, expected_root=expected_root)
    project = pathlib.Path(project_root).resolve()
    result = recover_closed_general_asset_bundles(
        project, pathlib.Path(client_root), pathlib.Path(server_root),
        source_root=source_root, reference_source_root=reference_source_root,
        donor_clients=configured_contract_donor_clients(project),
        donor_servers=configured_contract_donor_servers(project),
        expected_roots=[f"{expected_side.upper()}:{_norm(expected_root)}"],
        apply=True,
    )
    if result.get("status") != "PASS" or result.get("state") != "APPLIED_VERIFIED":
        return {"format": FORMAT, "status": "FAIL", "recovery": result}
    tx_path = _write_physical_transaction(project, result, donor_label=donor_label)
    return {
        "format": FORMAT, "status": "APPLIED_VERIFIED",
        "transaction": str(tx_path), "recovery": result,
        "restore_confirmation": PHYSICAL_RESTORE_CONFIRM,
    }


def restore_physical_recovery(
    project_root: pathlib.Path, client_root: pathlib.Path, server_root: pathlib.Path,
    *, transaction: pathlib.Path | str, confirm: str,
) -> dict[str, Any]:
    if str(confirm or "") != PHYSICAL_RESTORE_CONFIRM:
        raise PermissionError(f"DONOR_PHYSICAL_RESTORE_CONFIRMATION_REQUIRED:{PHYSICAL_RESTORE_CONFIRM}")
    project = pathlib.Path(project_root).resolve()
    tx_path = pathlib.Path(transaction).expanduser().resolve()
    allowed = project / "pt_build" / "donor_recovery_explorer" / "physical_transactions"
    try:
        tx_path.relative_to(allowed.resolve())
    except Exception as exc:
        raise ValueError("DONOR_PHYSICAL_TRANSACTION_OUTSIDE_PROJECT") from exc
    data = json.loads(tx_path.read_text(encoding="utf-8"))
    if data.get("format") != PHYSICAL_TRANSACTION_FORMAT:
        raise ValueError("DONOR_PHYSICAL_TRANSACTION_FORMAT_INVALID")
    if data.get("state") != "APPLIED_VERIFIED":
        raise ValueError(f"DONOR_PHYSICAL_TRANSACTION_NOT_APPLIED:{data.get('state')}")
    roots = {"CLIENT": pathlib.Path(client_root).resolve(), "SERVER": pathlib.Path(server_root).resolve()}
    if str(roots["CLIENT"]) != str(pathlib.Path(str(data.get("client_root"))).resolve()) or str(roots["SERVER"]) != str(pathlib.Path(str(data.get("server_root"))).resolve()):
        raise ValueError("DONOR_PHYSICAL_RUNTIME_ROOT_DRIFT")
    files = data.get("files") or []
    targets: list[pathlib.Path] = []
    for row in files:
        side = str(row.get("side") or "").upper(); root = roots.get(side)
        if root is None:
            raise ValueError(f"DONOR_PHYSICAL_SIDE_INVALID:{side}")
        target = pathlib.Path(str(row.get("target_path") or "")).resolve()
        try:
            target.relative_to(root)
        except Exception as exc:
            raise ValueError(f"DONOR_PHYSICAL_RESTORE_TARGET_OUTSIDE_ROOT:{target}") from exc
        if not target.is_file():
            raise FileNotFoundError(f"DONOR_PHYSICAL_RESTORE_TARGET_MISSING:{target}")
        if target.stat().st_size != int(row.get("size") or -1) or sha256_file(target) != str(row.get("sha256") or ""):
            raise ValueError(f"DONOR_PHYSICAL_RESTORE_TARGET_DRIFT:{target}")
        targets.append(target)
    parents = []
    for target in targets:
        parents.append(target.parent)
        target.unlink()
    # Remove only directories made empty by deleting these create-only files.
    for parent in sorted(set(parents), key=lambda x: len(x.parts), reverse=True):
        cursor = parent
        root = roots["CLIENT"] if roots["CLIENT"] in cursor.parents or cursor == roots["CLIENT"] else roots["SERVER"]
        while cursor != root:
            try:
                cursor.rmdir()
            except OSError:
                break
            cursor = cursor.parent
    data["state"] = "RESTORED"
    data["restored_at"] = time.time()
    tmp = tx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(tx_path)
    return {"format": FORMAT, "status": "RESTORED", "transaction": str(tx_path), "removed_files": len(targets)}


def stage_physical_closed_bundle(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    source_root: pathlib.Path | str | None,
    reference_source_root: pathlib.Path | str | None,
    donor_label: str,
    expected_side: str,
    expected_root: str,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    _closed_bundle_selection(project, donor_label=donor_label, expected_side=expected_side, expected_root=expected_root)
    return recover_closed_general_asset_bundles(
        project, pathlib.Path(client_root), pathlib.Path(server_root),
        source_root=source_root,
        reference_source_root=reference_source_root,
        donor_clients=configured_contract_donor_clients(project),
        donor_servers=configured_contract_donor_servers(project),
        expected_roots=[f"{expected_side.upper()}:{_norm(expected_root)}"],
        apply=False,
    )
