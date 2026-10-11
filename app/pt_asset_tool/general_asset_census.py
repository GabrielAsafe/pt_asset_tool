from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import time
import zipfile
from collections import Counter, defaultdict, deque
from typing import Any, Callable, Iterable

from .client_manifest_evidence import audit_client_manifests, parse_fixed_manifest
from .enrichment_vendor_adapter import build_dependency_graph
from .server_bundle_census import audit_server_entity_bundles, _decode_text, _norm_ref
from .server_field_census import audit_server_field_bundles
from .server_field_editor import _inspect_spc
from .server_item_census import audit_server_item_bundles
from .server_lifecycle import classify_server_path
from .player_class_motion_contract import parse_reference_class_configs
from .source_catalog import require_source_trees
from .source_evidence import scan_source_evidence
from .superset_aggregation import build_summit_superset, parse_labeled_roots
from .texture_overlay import face_texture_references_model062
from .monster_npc_census import extract_refs as extract_bundle_refs
from .ui_catalog import infer_physical_family
from .class_ui_alias_audit import audit_class_ui_aliases
from .cooked_texture_evidence import audit_cooked_texture_evidence, cooked_index
from .effect_runtime_coverage import audit_effect_runtime_coverage
from .summit_asset_migration_audit import audit_canonical_asset_relations
from .asset_retention import audit_asset_retention

FORMAT = "PT_ASSET_GENERAL_REACHABILITY_CENSUS_V1"
RECOVERY_ACTIONS = {"RECOVER", "RECOVER_DEDUPED", "RECOVER_PREFERRED_VARIANT"}
HARD_REVIEW_ACTIONS = {"TARGET_CASE_COLLISION", "DONOR_CASE_COLLISION", "SOURCE_FILE_MISSING"}


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _write_tsv(path: pathlib.Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _walk_index(root: pathlib.Path) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    if not root.is_dir():
        return out
    for base, dirs, files in os.walk(root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(base) / name
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            out.setdefault(_norm(rel).casefold(), p)
    return out


def _physical_rel(path: str | pathlib.Path, roots: list[tuple[str, pathlib.Path]]) -> tuple[str | None, str | None]:
    if not path:
        return None, None
    p = pathlib.Path(path)
    try:
        rp = p.resolve()
    except Exception:
        rp = p
    for label, root in roots:
        try:
            return label, rp.relative_to(root.resolve()).as_posix()
        except Exception:
            continue
    return None, None


def _server_definition_names(server_root: pathlib.Path) -> dict[str, list[str]]:
    """Index monster/NPC definition paths by runtime name and filename stem.

    Brazilian files commonly expose ``*J_NAME``. Filename stem is retained as
    secondary evidence only; ambiguous keys are never collapsed.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for base_rel, suffix in (("GameServer/Monster", ".inf"), ("GameServer/NPC", ".npc")):
        base = server_root / base_rel
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*"), key=lambda x: x.as_posix().casefold()):
            if not p.is_file() or p.suffix.casefold() != suffix:
                continue
            try:
                rel = p.relative_to(server_root).as_posix()
                text, _enc = _decode_text(p.read_bytes())
            except Exception:
                continue
            keys = {p.stem.casefold()}
            for line in text.splitlines():
                stripped = line.strip()
                up = stripped.upper()
                if up.startswith("*J_NAME") or stripped.startswith("*이름"):
                    token_len = len("*J_NAME") if up.startswith("*J_NAME") else len("*이름")
                    rest = stripped[token_len:].strip()
                    if rest.startswith('"') and '"' in rest[1:]:
                        name = rest.split('"', 2)[1]
                    else:
                        name = rest.split(None, 1)[0] if rest else ""
                    if name:
                        keys.add(name.casefold())
            for key in keys:
                if rel not in index[key]:
                    index[key].append(rel)
    return index


def _spm_actor_names(path: pathlib.Path) -> list[tuple[str, str]]:
    try:
        text, _enc = _decode_text(path.read_bytes())
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    aliases = {
        "*ACTOR": "ACTOR", "*출연자": "ACTOR",
        "*BOSS_ACTOR": "BOSS_ACTOR", "*출연자두목": "BOSS_ACTOR",
    }
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        first = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        kind = aliases.get(first.upper()) or aliases.get(first)
        if not kind:
            continue
        # Runtime parser accepts quoted names. Boss rows contain master + slave.
        values: list[str] = []
        cursor = rest.strip()
        while cursor and len(values) < (2 if kind == "BOSS_ACTOR" else 1):
            if cursor.startswith('"'):
                end = cursor.find('"', 1)
                if end < 0:
                    break
                values.append(cursor[1:end])
                cursor = cursor[end + 1:].strip()
            else:
                token, _, cursor = cursor.partition(" ")
                if token:
                    values.append(token)
                cursor = cursor.strip()
        out.extend((kind, v) for v in values if v)
    return out




def _spc_server_npc_rel(value: str) -> str:
    """Normalize an SPC server_npc field to a server-relative NPC definition.

    Canonical SPC records may store either a bare filename or a GameServer/NPC
    path.  This helper is evidence-only and never invents a definition outside
    the NPC namespace.
    """
    rel = _norm(value)
    if not rel:
        return ""
    low = rel.casefold()
    if low.startswith("gameserver/npc/"):
        return rel
    if low.startswith("npc/"):
        return "GameServer/" + rel
    if "/" not in rel:
        return f"GameServer/NPC/{rel}"
    return rel

def _load_player_graph(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {"nodes": [], "edges": []}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"nodes": [], "edges": []}
    except Exception:
        return {"nodes": [], "edges": []}


_BUNDLE_LEAF_EXTS = {
    ".smb", ".bmp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".gif",
    ".wav", ".ogg", ".mp3", ".mid", ".bgm", ".zhoon", ".zif",
}
_BUNDLE_ROOT_PREFIXES = (
    "char/", "field/", "image/", "effect/", "wav/", "weapons/",
    "cselect/", "startimage/", "res/", "game/",
)


def _field_source_stage_witness(row: dict[str, Any], source_literal_paths: set[str]) -> tuple[str | None, str]:
    """Return one current-source-proven physical stage candidate, if unique.

    Field companions are derived from a configured stage. Presence of an SPM/
    SPP/SPC bundle alone does not prove that the field is opened by the current
    runtime. Current-source stage literals are therefore used as the conservative
    runtime witness; .ASE logical names and sibling .SMD physical names are treated
    as the same loader family only when the directory+stem match exactly.
    """
    candidates = list(row.get("stage_candidates") or [])
    selected = _norm(row.get("selected_stage") or "")
    if selected and selected not in candidates:
        candidates.append(selected)
    hits: list[str] = []
    for raw in candidates:
        rel = _norm(raw)
        if not rel:
            continue
        pp = pathlib.PurePosixPath(rel)
        aliases = {rel.casefold()}
        if pp.suffix.casefold() in {".ase", ".smd"}:
            aliases.add(pp.with_suffix(".ase").as_posix().casefold())
            aliases.add(pp.with_suffix(".smd").as_posix().casefold())
        if aliases & source_literal_paths:
            hits.append(rel)
    unique = sorted({x.casefold(): x for x in hits}.values(), key=str.casefold)
    if len(unique) == 1:
        return unique[0], "CURRENT_SOURCE_FIELD_STAGE_LITERAL"
    if len(unique) > 1:
        return None, "AMBIGUOUS_CURRENT_SOURCE_FIELD_STAGE_LITERAL"
    return None, "NO_CURRENT_SOURCE_FIELD_STAGE_LITERAL"


def _bundle_ref_candidates(ref: str, parent_rel: str) -> list[str]:
    rel = _norm(ref)
    if not rel:
        return []
    low = rel.casefold()
    for marker in _BUNDLE_ROOT_PREFIXES:
        pos = low.find(marker)
        if pos > 0:
            rel = rel[pos:]
            low = rel.casefold()
            break
    out: list[str] = []
    if low.startswith(_BUNDLE_ROOT_PREFIXES):
        out.append(rel)
    else:
        parent = pathlib.PurePosixPath(_norm(parent_rel)).parent
        out.append((parent / pathlib.PurePosixPath(rel)).as_posix())
        if "/" in rel:
            out.append(rel)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in out:
        key = _norm(candidate).casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(_norm(candidate))
    return result


def _resolve_bundle_reference(
    ref: str,
    parent_rel: str,
    *,
    parent_ext: str,
    target_idx: dict[str, pathlib.Path],
    donor_idx: dict[str, pathlib.Path],
) -> dict[str, Any]:
    candidates = _bundle_ref_candidates(ref, parent_rel)
    for candidate in candidates:
        probe: list[tuple[str, str]] = []
        pp = pathlib.PurePosixPath(candidate)
        if parent_ext == ".inx" and pp.suffix.casefold() == ".ase":
            probe.append((pp.with_suffix(".smd").as_posix(), "INX_ASE_TO_SMD_RUNTIME_ALIAS"))
            probe.append((pp.with_suffix(".smb").as_posix(), "INX_ASE_TO_SMB_RUNTIME_ALIAS"))
        probe.append((candidate, "EXACT_OR_SAME_DIRECTORY_REFERENCE"))
        for logical, basis in probe:
            key = _norm(logical).casefold()
            if key in target_idx:
                return {
                    "status": "PRESENT_TARGET", "logical_path": _norm(logical),
                    "physical_path": str(target_idx[key]), "resolution_basis": basis,
                }
            if key in donor_idx:
                donor_basis = basis
                donor_relocation = None
                basis_fn = getattr(donor_idx, "resolution_basis", None)
                if callable(basis_fn):
                    override = str(basis_fn(key) or "")
                    if override:
                        donor_basis = override
                relocation_fn = getattr(donor_idx, "relocation_metadata", None)
                if callable(relocation_fn):
                    meta = relocation_fn(key)
                    if isinstance(meta, dict):
                        donor_relocation = dict(meta)
                out = {
                    "status": "RECOVER_SAME_DONOR", "logical_path": _norm(logical),
                    "physical_path": str(donor_idx[key]), "resolution_basis": donor_basis,
                }
                if donor_relocation is not None:
                    out["relocation"] = donor_relocation
                return out
    return {
        "status": "MISSING_SAME_LINEAGE", "logical_path": candidates[0] if candidates else _norm(ref),
        "physical_path": "", "resolution_basis": "NO_EXACT_OR_SAME_DIRECTORY_MATCH",
    }



def _face_texture_references_smd(path: pathlib.Path, project: pathlib.Path) -> dict[str, Any]:
    """Return face-used texture references for either supported SMD container.

    Character/NPC models use Model data Ver 0.62, while map geometry uses
    Stage data Ver 0.72.  The directed bundle closure must distinguish the two
    before choosing a parser; treating every .smd as Model0.62 makes valid map
    roots fail closed-bundle certification before any dependency is inspected.
    """
    try:
        with pathlib.Path(path).open("rb") as fh:
            header = fh.read(32)
    except Exception as exc:
        return {
            "status": "REVIEW",
            "semantics": "UNPROVEN_FACE_SCOPE",
            "model": str(path),
            "used_material_ids": [],
            "required_names": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    if header.startswith(b"SMD Stage data Ver 0.72"):
        try:
            from .stage072_corpus import parse_stage072

            parsed = parse_stage072(path)
            if parsed.get("full_parse") != "PASS":
                return {
                    "status": "REVIEW",
                    "semantics": "STAGE072_FACE_SCOPE_UNPROVEN",
                    "model": str(path),
                    "used_material_ids": [],
                    "required_names": [],
                    "error": "Stage0.72 parser did not pass structural gates",
                    "parser_checks": parsed.get("checks") or {},
                    "parser_errors": parsed.get("errors") or {},
                }

            face_counts = parsed.get("material_face_counts") or {}
            used_ids = sorted(
                int(mid) for mid, count in face_counts.items()
                if int(count or 0) > 0
            )
            used_set = set(used_ids)
            required: list[str] = []
            seen: set[str] = set()
            runtime_texture_exts = {".bmp", ".tga", ".jpg", ".jpeg", ".png", ".stg", ".sta"}
            for material in parsed.get("materials") or []:
                mid = int(material.get("id") or 0)
                if mid not in used_set:
                    continue
                for row in list(material.get("textures") or []) + list(material.get("anim_textures") or []):
                    logical = _norm(row.get("Name") or "")
                    if not logical:
                        continue
                    # Stage material records can contain short non-file tokens in
                    # serialized texture slots. The client texture loader only
                    # recognizes the standard raster extensions plus .stg/.sta
                    # aliases, so an extensionless token such as StarArena's
                    # literal ``w`` is not a physical runtime dependency. Keep
                    # supported file references fail-closed as before.
                    if pathlib.PurePosixPath(logical).suffix.casefold() not in runtime_texture_exts:
                        continue
                    key = logical.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    required.append(logical)
            return {
                "status": "PASS",
                "semantics": "STAGE072_FACE_REFERENCED_MATERIALS",
                "model": str(path),
                "used_material_ids": used_ids,
                "required_names": required,
                "full_parse": "PASS",
            }
        except Exception as exc:
            return {
                "status": "REVIEW",
                "semantics": "STAGE072_FACE_SCOPE_UNPROVEN",
                "model": str(path),
                "used_material_ids": [],
                "required_names": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

    return face_texture_references_model062(path, project)


def _assess_client_recovery_bundle(
    project: pathlib.Path,
    root_row: dict[str, Any],
    *,
    target_idx: dict[str, pathlib.Path],
    donor_roots: list[tuple[str, pathlib.Path]],
    donor_index_cache: dict[str, dict[str, pathlib.Path]],
    plan_by_key: dict[str, dict[str, str]],
    max_depth: int = 12,
) -> dict[str, Any]:
    root_rel = _norm(root_row.get("canonical_path") or root_row.get("path") or "")
    selected_path = pathlib.Path(str(root_row.get("selected_path") or ""))
    label, selected_rel = _physical_rel(str(selected_path), donor_roots)
    base = {
        "side": "CLIENT", "root_path": root_rel, "selected_source": root_row.get("selected_source") or "",
        "selected_path": str(selected_path) if str(selected_path) else "", "donor_label": label or "",
        "members": [], "issues": [],
    }
    if not root_rel or not selected_path.is_file() or not label:
        base.update({"status": "REVIEW", "reason": "SELECTED_DONOR_ROOT_NOT_RESOLVED", "member_count": 0, "recover_member_count": 0, "missing_count": 0, "review_count": 1})
        return base
    donor_root = dict(donor_roots)[label]
    donor_idx = donor_index_cache.get(label)
    if donor_idx is None:
        donor_idx = _walk_index(donor_root)
        donor_index_cache[label] = donor_idx
    queue: deque[tuple[str, pathlib.Path, int, str, str]] = deque(
        [(root_rel, selected_path, 0, "", "ROOT")]
    )
    visited: set[tuple[str, str]] = set()
    members: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    while queue:
        logical, physical, depth, parent, member_state = queue.popleft()
        vkey = (_norm(logical).casefold(), str(physical.resolve()).casefold())
        if vkey in visited:
            continue
        visited.add(vkey)
        ext = pathlib.PurePosixPath(logical).suffix.casefold()
        members.append({
            "logical_path": _norm(logical), "physical_path": str(physical),
            "state": member_state, "depth": depth, "parent": parent, "extension": ext,
        })
        if depth >= max_depth:
            issues.append({"kind": "MAX_DEPTH_REVIEW", "path": logical, "depth": depth})
            continue
        if ext in _BUNDLE_LEAF_EXTS:
            continue

        refs: list[str] = []
        if ext == ".smd":
            scope = _face_texture_references_smd(physical, project)
            if scope.get("status") != "PASS":
                issues.append({"kind": "SMD_FACE_SCOPE_REVIEW", "path": logical, "detail": scope})
                continue
            refs = [_norm(x) for x in scope.get("required_names") or [] if _norm(x)]
        elif ext == ".part":
            try:
                from pt_part_tool import analyze_bytes
                analysis = analyze_bytes(physical.read_bytes(), physical.name)
                refs = [_norm(r.get("normalized") or "") for r in analysis.references if _norm(r.get("normalized") or "")]
            except Exception as exc:
                issues.append({"kind": "PART_PARSE_REVIEW", "path": logical, "error": f"{type(exc).__name__}:{exc}"})
                continue
        elif ext in {".inx", ".ini", ".inf", ".ase", ".fnt", ".fx"}:
            try:
                refs = [_norm(x) for x in extract_bundle_refs(physical) if _norm(x)]
            except Exception as exc:
                issues.append({"kind": "REFERENCE_PARSE_REVIEW", "path": logical, "error": f"{type(exc).__name__}:{exc}"})
                continue
            if ext == ".inx" and not refs:
                issues.append({"kind": "INX_NO_DEPENDENCIES_EXTRACTED_REVIEW", "path": logical})
                continue
        else:
            issues.append({"kind": "UNSUPPORTED_BUNDLE_FORMAT_REVIEW", "path": logical, "extension": ext})
            continue

        for ref in refs:
            resolved = _resolve_bundle_reference(ref, logical, parent_ext=ext, target_idx=target_idx, donor_idx=donor_idx)
            dep = _norm(resolved.get("logical_path") or "")
            state = str(resolved.get("status") or "")
            member = {
                "logical_path": dep, "physical_path": resolved.get("physical_path") or "",
                "state": state, "depth": depth + 1, "parent": logical,
                "reference": ref, "resolution_basis": resolved.get("resolution_basis") or "",
                "extension": pathlib.PurePosixPath(dep).suffix.casefold(),
            }
            if isinstance(resolved.get("relocation"), dict):
                member["relocation"] = dict(resolved["relocation"])
            members.append(member)
            if state == "MISSING_SAME_LINEAGE":
                issues.append({"kind": "MISSING_SAME_LINEAGE_DEPENDENCY", "parent": logical, "reference": ref, "logical_path": dep})
                continue
            if state == "RECOVER_SAME_DONOR":
                prow = plan_by_key.get(dep.casefold()) or {}
                action = str(prow.get("action") or "")
                try:
                    distinct = int(prow.get("distinct_hash_count") or 0)
                except Exception:
                    distinct = 0
                if action not in RECOVERY_ACTIONS:
                    issues.append({"kind": "DEPENDENCY_NOT_RECOVERABLE_BY_SUPERSET", "logical_path": dep, "action": action})
                    continue
                if action == "RECOVER_PREFERRED_VARIANT" or distinct > 1:
                    issues.append({"kind": "DEPENDENCY_VARIANT_CONFLICT", "logical_path": dep, "action": action, "distinct_hash_count": distinct})
                    continue
            dep_physical = pathlib.Path(str(resolved.get("physical_path") or ""))
            if dep_physical.is_file():
                queue.append((dep, dep_physical, depth + 1, logical, state))

    compact: list[dict[str, Any]] = []
    seen_members: set[tuple[str, str, str]] = set()
    for m in members:
        key = (str(m.get("logical_path") or "").casefold(), str(m.get("state") or ""), str(m.get("physical_path") or "").casefold())
        if key in seen_members:
            continue
        seen_members.add(key)
        compact.append(m)
    missing = [x for x in issues if x.get("kind") == "MISSING_SAME_LINEAGE_DEPENDENCY"]
    review = [x for x in issues if x.get("kind") != "MISSING_SAME_LINEAGE_DEPENDENCY"]
    status = "INCOMPLETE" if missing else ("REVIEW" if review else "CLOSED")
    base.update({
        "status": status,
        "reason": "MISSING_DEPENDENCY" if missing else ("UNPROVEN_OR_CONFLICTING_DEPENDENCY" if review else "ALL_DEPENDENCIES_TARGET_OR_SAME_LINEAGE"),
        "members": compact, "issues": issues, "member_count": len(compact),
        "recover_member_count": sum(1 for x in compact if x.get("state") in {"ROOT", "RECOVER_SAME_DONOR"}),
        "missing_count": len(missing), "review_count": len(review), "selected_relative_path": selected_rel or "",
    })
    return base


def _assess_server_recovery_bundle(root_row: dict[str, Any], donor_roots: list[tuple[str, pathlib.Path]]) -> dict[str, Any]:
    root_rel = _norm(root_row.get("canonical_path") or root_row.get("path") or "")
    selected_path = pathlib.Path(str(root_row.get("selected_path") or ""))
    label, selected_rel = _physical_rel(str(selected_path), donor_roots)
    ext = pathlib.PurePosixPath(root_rel).suffix.casefold()
    if not root_rel or not selected_path.is_file() or not label:
        return {"side": "SERVER", "root_path": root_rel, "status": "REVIEW", "reason": "SELECTED_DONOR_ROOT_NOT_RESOLVED", "member_count": 0, "recover_member_count": 0, "missing_count": 0, "review_count": 1, "members": [], "issues": []}
    if ext == ".zhoon":
        try:
            text, encoding = _decode_text(selected_path.read_bytes())
            nonempty = bool(text.strip())
        except Exception as exc:
            return {"side": "SERVER", "root_path": root_rel, "status": "REVIEW", "reason": "ZHOON_DECODE_REVIEW", "member_count": 1, "recover_member_count": 1, "missing_count": 0, "review_count": 1, "members": [{"logical_path": root_rel, "physical_path": str(selected_path), "state": "ROOT", "extension": ext}], "issues": [{"kind": "ZHOON_DECODE_REVIEW", "error": f"{type(exc).__name__}:{exc}"}]}
        return {
            "side": "SERVER", "root_path": root_rel, "status": "CLOSED" if nonempty else "REVIEW",
            "reason": "LEAF_ZHOON_DECODED" if nonempty else "EMPTY_ZHOON_REVIEW",
            "selected_source": root_row.get("selected_source") or "", "donor_label": label,
            "selected_path": str(selected_path), "selected_relative_path": selected_rel or "", "encoding": encoding,
            "member_count": 1, "recover_member_count": 1, "missing_count": 0, "review_count": 0 if nonempty else 1,
            "members": [{"logical_path": root_rel, "physical_path": str(selected_path), "state": "ROOT", "extension": ext}],
            "issues": [] if nonempty else [{"kind": "EMPTY_ZHOON_REVIEW"}],
        }
    return {
        "side": "SERVER", "root_path": root_rel, "status": "REVIEW", "reason": "SERVER_BUNDLE_FORMAT_NOT_YET_CLOSED",
        "selected_source": root_row.get("selected_source") or "", "donor_label": label, "selected_path": str(selected_path),
        "selected_relative_path": selected_rel or "", "member_count": 1, "recover_member_count": 1, "missing_count": 0, "review_count": 1,
        "members": [{"logical_path": root_rel, "physical_path": str(selected_path), "state": "ROOT", "extension": ext}],
        "issues": [{"kind": "UNSUPPORTED_SERVER_BUNDLE_FORMAT_REVIEW", "extension": ext}],
    }



def _t5_effect_readiness(
    graph: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    recovery_bundles: list[dict[str, Any]],
    client_roots: list[tuple[str, pathlib.Path]],
) -> dict[str, Any]:
    """Summarize Tier-5 effect+audio asset readiness.

    Tier-5 gameplay/runtime functionality is not inferred here.  This slice has
    one deliberately narrower question: for T5 code that *currently calls* a
    particle or sound asset, is that physical asset present, safely recoverable
    as a CLOSED same-lineage bundle, or blocked?  Donor/reference presence alone
    never authorizes import.
    """
    nodes = {str(n.get("node_id") or ""): n for n in graph.get("nodes", []) if n.get("node_id")}
    graph_metadata = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    adj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        src = str(edge.get("source") or "")
        if src:
            adj[src].append(edge)
    candidates = {
        (str(r.get("side") or "").upper(), _norm(r.get("path") or "").casefold()): r
        for r in candidate_rows if _norm(r.get("path") or "")
    }
    bundle_by_key = {
        (str(b.get("side") or "").upper(), _norm(b.get("root_path") or "").casefold()): b
        for b in recovery_bundles if _norm(b.get("root_path") or "")
    }

    def asset_root(asset_node_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        node = nodes.get(asset_node_id) or {}
        attrs = node.get("attributes") or {}
        resolution = attrs.get("resolution") if isinstance(attrs.get("resolution"), dict) else {}
        physical = str(resolution.get("physical_path") or "")
        logical = _norm(attrs.get("logical_path") or "")
        _label, rel = _physical_rel(physical, client_roots) if physical else (None, None)
        root = _norm(rel or logical)
        return root, attrs, resolution

    def classify(item: dict[str, Any]) -> str:
        root = _norm(item.get("root_path") or "")
        resolution_status = str(item.get("resolution_status") or "")
        candidate = candidates.get(("CLIENT", root.casefold())) if root else None
        bundle = bundle_by_key.get(("CLIENT", root.casefold())) if root else None
        if resolution_status == "PRESENT_TARGET":
            state = "TARGET_PRESENT"
        elif candidate is not None:
            decision = str(candidate.get("decision") or "")
            bstatus = str((bundle or {}).get("status") or "")
            if decision == "RECOVERABLE_REACHABLE_CANDIDATE" and bstatus == "CLOSED":
                state = "RECOVERABLE_CLOSED"
            elif decision == "RECOVERABLE_REACHABLE_CANDIDATE" and bstatus == "REVIEW":
                state = "RECOVERABLE_REVIEW"
            elif decision == "RECOVERABLE_REACHABLE_CANDIDATE" and bstatus == "INCOMPLETE":
                state = "RECOVERABLE_INCOMPLETE"
            elif decision == "MISSING_REACHABLE_NO_DONOR":
                state = "MISSING_NO_DONOR"
            elif decision in {"REVIEW_REACHABLE_DONOR_CONFLICT", "REVIEW_HARD_CONFLICT"}:
                state = "CONFLICT"
            else:
                state = "REVIEW"
            item["candidate_decision"] = decision
            item["recovery_bundle_status"] = bstatus
        elif resolution_status == "RECOVERABLE_REFERENCE":
            state = "DONOR_PRESENT_NOT_RECOVERY_ROOT"
        elif resolution_status:
            state = resolution_status
        else:
            state = "UNRESOLVED"
        item["state"] = state
        return state

    skill_rows: list[dict[str, Any]] = []
    closed_roots: dict[str, dict[str, Any]] = {}
    scoped_import_roots: dict[str, dict[str, Any]] = {}
    all_runtime_roots: dict[str, dict[str, Any]] = {}
    effect_closed_roots: set[str] = set()
    audio_closed_roots: set[str] = set()

    for skill_id, skill_node in sorted(nodes.items(), key=lambda kv: kv[0].casefold()):
        if skill_node.get("node_type") != "SKILL":
            continue
        attrs = skill_node.get("attributes") or {}
        if int(attrs.get("tier") or 0) != 5:
            continue
        cls = str(attrs.get("class_name") or "")
        skill_name = str(skill_node.get("label") or attrs.get("skill_id") or skill_id)
        effect_bindings: list[dict[str, Any]] = []
        audio_bindings: list[dict[str, Any]] = []
        unresolved_audio: list[dict[str, Any]] = []
        reference_effect_tokens: list[str] = []
        current_effect_tokens: list[str] = []

        for edge in adj.get(skill_id, []):
            relation = str(edge.get("relation") or "")
            status = str(edge.get("status") or "")
            evidence = str(edge.get("evidence") or "")
            target = str(edge.get("target") or "")
            if relation == "USES_EFFECT_TOKEN":
                token_node = nodes.get(target) or {}
                token = str(token_node.get("label") or target.removeprefix("EFFECT_TOKEN:"))
                if status == "CURRENT_RUNTIME_TOKEN" or evidence.startswith("CURRENT_HANDLER:"):
                    current_effect_tokens.append(token)
                    for resolved_edge in adj.get(target, []):
                        if str(resolved_edge.get("relation") or "") != "RESOLVES_PARTICLE_SCRIPT":
                            continue
                        asset_id = str(resolved_edge.get("target") or "")
                        root, asset_attrs, resolution = asset_root(asset_id)
                        effect_bindings.append({
                            "asset_kind": "EFFECT",
                            "binding_kind": "EFFECT_TOKEN",
                            "token": token,
                            "asset_node": asset_id,
                            "logical_path": _norm(asset_attrs.get("logical_path") or ""),
                            "root_path": root,
                            "resolution_status": str(resolution.get("status") or resolved_edge.get("status") or ""),
                            "source_label": str(resolution.get("source_label") or ""),
                            "physical_path": str(resolution.get("physical_path") or ""),
                            "source_evidence": evidence,
                        })
                else:
                    reference_effect_tokens.append(token)
            elif relation == "REQUIRES_ASSET" and evidence.startswith("CURRENT_HANDLER:"):
                target_node = nodes.get(target) or {}
                target_attrs = target_node.get("attributes") or {}
                role = str(target_attrs.get("asset_role") or "")
                if role not in {"SKILL_PARTICLE", "SKILL_AUDIO"}:
                    continue
                root, asset_attrs, resolution = asset_root(target)
                item = {
                    "asset_kind": "AUDIO" if role == "SKILL_AUDIO" else "EFFECT",
                    "binding_kind": "AUDIO_CALL" if role == "SKILL_AUDIO" else "PARTICLE_LITERAL",
                    "token": "",
                    "asset_node": target,
                    "logical_path": _norm(asset_attrs.get("logical_path") or ""),
                    "root_path": root,
                    "resolution_status": str(resolution.get("status") or edge.get("status") or ""),
                    "source_label": str(resolution.get("source_label") or ""),
                    "physical_path": str(resolution.get("physical_path") or ""),
                    "source_evidence": evidence,
                }
                (audio_bindings if role == "SKILL_AUDIO" else effect_bindings).append(item)
            elif relation == "PLAYS_SOUND" and status == "CURRENT_RUNTIME_SYMBOL_UNRESOLVED":
                snd = nodes.get(target) or {}
                unresolved_audio.append({
                    "asset_kind": "AUDIO",
                    "binding_kind": "SOUND_SYMBOL",
                    "symbol": str(snd.get("label") or target.removeprefix("SOUND_SYMBOL:")),
                    "code": (snd.get("attributes") or {}).get("code"),
                    "state": "UNRESOLVED_SOUND_SYMBOL",
                    "source_evidence": evidence,
                })

        all_bindings = effect_bindings + audio_bindings
        binding_states: list[str] = []
        for item in all_bindings:
            state = classify(item)
            binding_states.append(state)
            root = _norm(item.get("root_path") or "")
            if root:
                key = root.casefold()
                all_runtime_roots[key] = {
                    "path": root, "state": state, "class": cls, "skill": skill_name,
                    "asset_kind": item.get("asset_kind"),
                }
                if state == "RECOVERABLE_CLOSED":
                    closed_roots[key] = {
                        "path": root, "class": cls, "skill": skill_name,
                        "asset_kind": item.get("asset_kind"),
                    }
                    if item.get("asset_kind") == "AUDIO":
                        audio_closed_roots.add(key)
                    else:
                        effect_closed_roots.add(key)

        runtime_case_count = int(attrs.get('current_runtime_case_count') or 0)
        alias_probe_count = int(attrs.get('current_skill_alias_probe_count') or 0)
        has_calls = bool(all_bindings or unresolved_audio)
        blocked_states = [x for x in binding_states if x not in {"TARGET_PRESENT", "RECOVERABLE_CLOSED"}]
        if unresolved_audio:
            blocked_states.extend(["UNRESOLVED_SOUND_SYMBOL"] * len(unresolved_audio))

        if not has_calls:
            overall = "NO_CURRENT_T5_ASSET_CALL_PROOF"
            diagnostic = "NO_EFFECT_OR_AUDIO_CALL_ATTRIBUTED_TO_SKILL"
        elif not blocked_states and binding_states and all(x == "TARGET_PRESENT" for x in binding_states):
            overall = "CURRENT_T5_ASSETS_TARGET_COMPLETE"
            diagnostic = "CURRENT_T5_ASSET_CALLS_BOUND"
        elif not blocked_states and any(x == "RECOVERABLE_CLOSED" for x in binding_states):
            overall = "CURRENT_T5_ASSETS_RECOVERABLE_CLOSED"
            diagnostic = "CURRENT_T5_ASSET_CALLS_BOUND"
            for item in all_bindings:
                if item.get("state") == "RECOVERABLE_CLOSED" and _norm(item.get("root_path") or ""):
                    key = _norm(item["root_path"]).casefold()
                    scoped_import_roots[key] = closed_roots[key]
        else:
            overall = "CURRENT_T5_ASSETS_BLOCKED"
            diagnostic = "CURRENT_T5_ASSET_CALL_BOUND_BUT_PHYSICAL_ASSET_BLOCKED"

        skill_rows.append({
            "class": cls,
            "skill_id": str(attrs.get("skill_id") or skill_id.rsplit(":", 1)[-1]),
            "skill_name": skill_name,
            "tier": 5,
            "status": overall,
            "current_effect_tokens": sorted(set(current_effect_tokens), key=str.casefold),
            "reference_effect_tokens": sorted(set(reference_effect_tokens), key=str.casefold),
            "current_effect_binding_count": len(effect_bindings),
            "current_audio_binding_count": len(audio_bindings),
            "current_audio_unresolved_count": len(unresolved_audio),
            "current_binding_count": len(all_bindings),
            "current_runtime_case_count": runtime_case_count,
            "current_skill_alias_probe_count": alias_probe_count,
            "current_runtime_case_evidence": attrs.get('current_runtime_case_evidence') or [],
            "current_skill_alias_probes": attrs.get('current_skill_alias_probes') or [],
            "diagnostic": diagnostic,
            "effect_bindings": effect_bindings,
            "audio_bindings": audio_bindings,
            "unresolved_audio_bindings": unresolved_audio,
            "bindings": all_bindings + unresolved_audio,
        })

    counts = Counter(str(x.get("status") or "UNKNOWN") for x in skill_rows)
    blocked = [x for x in skill_rows if x.get("status") == "CURRENT_T5_ASSETS_BLOCKED"]
    scope_basis_counts = Counter(
        str(ev.get("scope_basis") or "UNKNOWN")
        for row in skill_rows
        for ev in (row.get("current_runtime_case_evidence") or [])
    )
    client_audio_probes = [
        x for x in (graph_metadata.get("current_runtime_audio_call_probes") or [])
        if str(x.get("layer") or "") == "CLIENT_RUNTIME"
    ]
    client_effect_probes = [
        x for x in (graph_metadata.get("current_runtime_effect_call_probes") or [])
        if str(x.get("layer") or "") == "CLIENT_RUNTIME"
    ]
    audio_callee_counts = Counter(str(x.get("callee") or "UNKNOWN") for x in client_audio_probes)
    unresolved_audio_callee_counts = Counter(
        str(x.get("callee") or "UNKNOWN") for x in client_audio_probes
        if not bool(x.get("resolved_identity"))
    )
    effect_callee_counts = Counter(str(x.get("callee") or "UNKNOWN") for x in client_effect_probes)
    unresolved_effect_callee_counts = Counter(
        str(x.get("callee") or "UNKNOWN") for x in client_effect_probes
        if not bool(x.get("resolved_token"))
    )
    return {
        "format": "PT_ASSET_T5_ASSET_READINESS_V6",
        "status": "PASS",
        "tier": 5,
        "skill_count": len(skill_rows),
        "current_runtime_asset_skill_count": sum(1 for x in skill_rows if int(x.get("current_binding_count") or 0) or int(x.get("current_audio_unresolved_count") or 0)),
        "current_runtime_effect_skill_count": sum(1 for x in skill_rows if int(x.get("current_effect_binding_count") or 0) > 0),
        "current_runtime_audio_skill_count": sum(1 for x in skill_rows if int(x.get("current_audio_binding_count") or 0) > 0 or int(x.get("current_audio_unresolved_count") or 0) > 0),
        "current_runtime_skill_case_count": sum(1 for x in skill_rows if int(x.get('current_runtime_case_count') or 0) > 0),
        "current_skill_alias_probe_count": sum(1 for x in skill_rows if int(x.get('current_skill_alias_probe_count') or 0) > 0),
        "current_client_asset_call_probe_count": int(graph_metadata.get("current_client_asset_call_probe_count") or 0),
        "current_server_asset_call_probe_count": int(graph_metadata.get("current_server_asset_call_probe_count") or 0),
        "current_client_audio_call_probe_count": int(graph_metadata.get("current_client_audio_call_probe_count") or 0),
        "current_client_unresolved_audio_call_probe_count": int(graph_metadata.get("current_client_unresolved_audio_call_probe_count") or 0),
        "current_client_audio_call_callee_counts": dict(sorted(audio_callee_counts.items())),
        "current_client_unresolved_audio_call_callee_counts": dict(sorted(unresolved_audio_callee_counts.items())),
        "current_client_effect_call_probe_count": int(graph_metadata.get("current_client_effect_call_probe_count") or 0),
        "current_client_unresolved_effect_call_probe_count": int(graph_metadata.get("current_client_unresolved_effect_call_probe_count") or 0),
        "current_client_effect_call_callee_counts": dict(sorted(effect_callee_counts.items())),
        "current_client_unresolved_effect_call_callee_counts": dict(sorted(unresolved_effect_callee_counts.items())),
        "current_runtime_asset_call_probe_count": int(graph_metadata.get("current_runtime_asset_call_probe_count") or 0),
        "current_t5_asset_bridge_case_count": int(graph_metadata.get("current_t5_asset_bridge_case_count") or 0),
        "current_runtime_case_scope_basis_counts": dict(sorted(scope_basis_counts.items())),
        "no_current_asset_call_proof_count": sum(1 for x in skill_rows if x.get("status") == "NO_CURRENT_T5_ASSET_CALL_PROOF"),
        # Backward-compatible key retained for the existing UI/CLI surface.
        "no_current_runtime_effect_proof_count": sum(1 for x in skill_rows if int(x.get("current_effect_binding_count") or 0) == 0),
        "current_effect_blocked_skill_count": len(blocked),
        "current_asset_blocked_skill_count": len(blocked),
        "runtime_effect_root_count": sum(1 for x in all_runtime_roots.values() if x.get("asset_kind") == "EFFECT"),
        "runtime_audio_root_count": sum(1 for x in all_runtime_roots.values() if x.get("asset_kind") == "AUDIO"),
        "runtime_asset_root_count": len(all_runtime_roots),
        "recoverable_closed_root_count": len(closed_roots),
        "recoverable_closed_effect_root_count": len(effect_closed_roots),
        "recoverable_closed_audio_root_count": len(audio_closed_roots),
        "recoverable_closed_roots": [closed_roots[k] for k in sorted(closed_roots)],
        "scoped_import_root_count": len(scoped_import_roots),
        "scoped_import_roots": [scoped_import_roots[k] for k in sorted(scoped_import_roots)],
        "status_counts": dict(sorted(counts.items())),
        "scoped_import_ready": bool(scoped_import_roots),
        "policy": {
            "tier5_runtime_functionality_is_external_fact_not_reinferred": True,
            "current_asset_call_binding_required": True,
            "reference_only_binding_is_not_import_authorization": True,
            "donor_gap_is_not_import_authorization": True,
            "closed_same_lineage_bundle_required": True,
            "partial_skill_bundle_is_not_scoped_import_authorized": True,
            "legacy_oracle_is_not_runtime_authority": True,
            "unscoped_current_client_asset_call_may_bridge_only_by_unique_reference_identity_or_skill_name": True,
            "generic_audio_or_effect_call_is_diagnostic_only_until_asset_identity_resolves": True,
            "particle_preload_is_not_effect_activation": True,
            "client_write_authorized": False,
        },
        "rows": skill_rows,
    }


def _t5_reference_parity(
    graph: dict[str, Any],
    t5_readiness: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Diagnostic-only T5 reference parity matrix.

    This intentionally does *not* widen import authority.  It answers a
    different question from readiness: what effect/audio assets does the EU
    reference associate with each T5 skill, are those assets already in the
    Summit target, and are there donor-name hints worth reviewing when the
    current Summit source has no proven call-site binding yet?
    """
    nodes = {str(n.get("node_id") or ""): n for n in graph.get("nodes", []) if n.get("node_id")}
    adj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        src = str(edge.get("source") or "")
        if src:
            adj[src].append(edge)

    current_by_skill: dict[tuple[str, str], dict[str, Any]] = {}
    for row in t5_readiness.get("rows", []):
        key = (str(row.get("class") or ""), str(row.get("skill_name") or "").casefold())
        current_by_skill[key] = row

    def norm_alias(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).casefold())

    def reference_state(resolution: dict[str, Any], fallback: str) -> str:
        status = str(resolution.get("status") or fallback or "")
        if status == "PRESENT_TARGET":
            return "TARGET_PRESENT"
        if status == "RECOVERABLE_REFERENCE":
            return "DONOR_PRESENT_REFERENCE_ONLY"
        if status == "CONFLICT":
            return "DONOR_CONFLICT_REFERENCE_ONLY"
        if status in {"MISSING_UNKNOWN", ""}:
            return "MISSING_NO_DONOR_REFERENCE_ONLY"
        return status

    rows: list[dict[str, Any]] = []
    totals = Counter()
    for skill_id, skill_node in sorted(nodes.items(), key=lambda kv: kv[0].casefold()):
        if skill_node.get("node_type") != "SKILL":
            continue
        attrs = skill_node.get("attributes") or {}
        if int(attrs.get("tier") or 0) != 5:
            continue
        cls = str(attrs.get("class_name") or "")
        skill_name = str(skill_node.get("label") or attrs.get("skill_id") or skill_id)
        current = current_by_skill.get((cls, skill_name.casefold()), {})
        current_roots = {
            _norm(x.get("root_path") or x.get("logical_path") or "").casefold()
            for x in (current.get("bindings") or [])
            if _norm(x.get("root_path") or x.get("logical_path") or "")
        }

        reference_assets: list[dict[str, Any]] = []
        seen_assets: set[tuple[str, str]] = set()
        for edge in adj.get(skill_id, []):
            relation = str(edge.get("relation") or "")
            evidence = str(edge.get("evidence") or "")
            target = str(edge.get("target") or "")
            if relation == "REQUIRES_ASSET" and evidence.startswith("REFERENCE_HANDLER:"):
                node = nodes.get(target) or {}
                a = node.get("attributes") or {}
                role = str(a.get("asset_role") or "")
                if role not in {"SKILL_PARTICLE", "SKILL_AUDIO"}:
                    continue
                logical = _norm(a.get("logical_path") or "")
                resolution = a.get("resolution") if isinstance(a.get("resolution"), dict) else {}
                kind = "AUDIO" if role == "SKILL_AUDIO" else "EFFECT"
                key = (kind, logical.casefold())
                if logical and key not in seen_assets:
                    seen_assets.add(key)
                    state = reference_state(resolution, str(edge.get("status") or ""))
                    reference_assets.append({
                        "asset_kind": kind,
                        "binding_kind": "REFERENCE_HANDLER_ASSET",
                        "logical_path": logical,
                        "state": state,
                        "current_runtime_bound": logical.casefold() in current_roots,
                        "source_label": str(resolution.get("source_label") or ""),
                        "physical_path": str(resolution.get("physical_path") or ""),
                        "candidates": list(resolution.get("candidates") or []),
                        "evidence": evidence,
                    })
                    totals[state] += 1
            elif relation == "USES_EFFECT_TOKEN" and not evidence.startswith("CURRENT_HANDLER:"):
                token_node = nodes.get(target) or {}
                token = str(token_node.get("label") or target.removeprefix("EFFECT_TOKEN:"))
                for resolved_edge in adj.get(target, []):
                    if str(resolved_edge.get("relation") or "") != "RESOLVES_PARTICLE_SCRIPT":
                        continue
                    asset_id = str(resolved_edge.get("target") or "")
                    node = nodes.get(asset_id) or {}
                    a = node.get("attributes") or {}
                    logical = _norm(a.get("logical_path") or "")
                    resolution = a.get("resolution") if isinstance(a.get("resolution"), dict) else {}
                    key = ("EFFECT", logical.casefold())
                    if not logical or key in seen_assets:
                        continue
                    seen_assets.add(key)
                    state = reference_state(resolution, str(resolved_edge.get("status") or ""))
                    reference_assets.append({
                        "asset_kind": "EFFECT",
                        "binding_kind": "REFERENCE_EFFECT_TOKEN",
                        "token": token,
                        "logical_path": logical,
                        "state": state,
                        "current_runtime_bound": logical.casefold() in current_roots,
                        "source_label": str(resolution.get("source_label") or ""),
                        "physical_path": str(resolution.get("physical_path") or ""),
                        "candidates": list(resolution.get("candidates") or []),
                        "evidence": evidence,
                    })
                    totals[state] += 1

        # Diagnostic donor-name hints deliberately remain non-authorizing.  They
        # catch assets such as RisingSlash1.part that exist in donors but are not
        # connected by current runtime evidence or a parsed reference handler.
        alias = norm_alias(skill_name)
        donor_name_hints: list[dict[str, Any]] = []
        if len(alias) >= 6:
            for cand in candidate_rows:
                if str(cand.get("side") or "").upper() != "CLIENT":
                    continue
                if str(cand.get("category") or "").upper() not in {"EFFECT", "AUDIO"}:
                    continue
                path = _norm(cand.get("path") or "")
                if not path or alias not in norm_alias(pathlib.PurePosixPath(path).name):
                    continue
                donor_name_hints.append({
                    "path": path,
                    "decision": str(cand.get("decision") or ""),
                    "selected_source": str(cand.get("selected_source") or ""),
                    "selected_path": str(cand.get("selected_path") or ""),
                    "distinct_hash_count": int(cand.get("distinct_hash_count") or 0),
                    "variant_count": int(cand.get("variant_count") or 0),
                    "authorization": "DIAGNOSTIC_ONLY",
                })

        if reference_assets:
            totals["REFERENCE_ASSET_SKILL_COUNT"] += 1
        if donor_name_hints:
            totals["DONOR_NAME_HINT_SKILL_COUNT"] += 1
        rows.append({
            "class": cls,
            "skill_id": str(attrs.get("skill_id") or skill_id.rsplit(":", 1)[-1]),
            "skill_name": skill_name,
            "current_status": str(current.get("status") or "UNKNOWN"),
            "current_binding_count": int(current.get("current_binding_count") or 0),
            "reference_asset_count": len(reference_assets),
            "reference_assets": sorted(reference_assets, key=lambda x: (x["asset_kind"], x["logical_path"].casefold())),
            "donor_name_hint_count": len(donor_name_hints),
            "donor_name_hints": sorted(donor_name_hints, key=lambda x: x["path"].casefold()),
        })

    return {
        "format": "PT_ASSET_T5_REFERENCE_PARITY_V1",
        "status": "PASS",
        "tier": 5,
        "skill_count": len(rows),
        "reference_asset_skill_count": int(totals.get("REFERENCE_ASSET_SKILL_COUNT", 0)),
        "donor_name_hint_skill_count": int(totals.get("DONOR_NAME_HINT_SKILL_COUNT", 0)),
        "reference_target_present_count": int(totals.get("TARGET_PRESENT", 0)),
        "reference_missing_no_donor_count": int(totals.get("MISSING_NO_DONOR_REFERENCE_ONLY", 0)),
        "reference_donor_present_count": int(totals.get("DONOR_PRESENT_REFERENCE_ONLY", 0)),
        "reference_donor_conflict_count": int(totals.get("DONOR_CONFLICT_REFERENCE_ONLY", 0)),
        "policy": {
            "diagnostic_only": True,
            "reference_only_asset_is_not_import_authority": True,
            "donor_name_hint_is_not_import_authority": True,
            "current_runtime_binding_still_required_for_scoped_import": True,
            "client_write_authorized": False,
        },
        "rows": rows,
    }


def _t5_activation_readiness(
    graph: dict[str, Any],
    t5_readiness: dict[str, Any],
    reference_parity: dict[str, Any],
) -> dict[str, Any]:
    """Separate physical particle preload from proven T5 effect activation.

    ``LoadScript(...part)`` proves that a client attempts to preload a resource;
    it does not prove that a T5 skill ever starts that particle.  This report is
    diagnostic-only and exists specifically to prevent preload evidence from
    widening scoped import authority.
    """
    metadata = graph.get("metadata") or {}
    preload_rows = list(metadata.get("current_t5_particle_preload_hints") or [])
    preload_by_skill: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in preload_rows:
        key = (str(row.get("class") or ""), str(row.get("skill_name") or "").casefold())
        preload_by_skill[key].append(row)

    parity_by_skill: dict[tuple[str, str], dict[str, Any]] = {}
    for row in reference_parity.get("rows", []):
        parity_by_skill[(str(row.get("class") or ""), str(row.get("skill_name") or "").casefold())] = row

    def preload_state(row: dict[str, Any]) -> str:
        resolution = row.get("resolution") if isinstance(row.get("resolution"), dict) else {}
        status = str(resolution.get("status") or "")
        if status == "PRESENT_TARGET":
            return "TARGET_PRESENT"
        if status == "RECOVERABLE_REFERENCE":
            return "DONOR_PRESENT_PRELOAD_ONLY"
        if status == "CONFLICT":
            return "DONOR_CONFLICT_PRELOAD_ONLY"
        if status in {"", "MISSING_UNKNOWN"}:
            return "MISSING_NO_DONOR_PRELOAD_ONLY"
        return status

    rows: list[dict[str, Any]] = []
    counts = Counter()
    for current in t5_readiness.get("rows", []):
        cls = str(current.get("class") or "")
        skill_name = str(current.get("skill_name") or "")
        key = (cls, skill_name.casefold())
        preload_items: list[dict[str, Any]] = []
        for raw in preload_by_skill.get(key, []):
            resolution = raw.get("resolution") if isinstance(raw.get("resolution"), dict) else {}
            state = preload_state(raw)
            preload_items.append({
                "logical_path": str(raw.get("logical_path") or ""),
                "state": state,
                "source_file": str(raw.get("source_file") or ""),
                "source_line": int(raw.get("source_line") or 0),
                "function": str(raw.get("function") or ""),
                "scope_basis": str(raw.get("scope_basis") or ""),
                "source_label": str(resolution.get("source_label") or ""),
                "physical_path": str(resolution.get("physical_path") or ""),
                "candidates": list(resolution.get("candidates") or []),
                "authorization": "DIAGNOSTIC_ONLY_PRELOAD_IS_NOT_ACTIVATION",
            })

        parity = parity_by_skill.get(key, {})
        reference_assets = list(parity.get("reference_assets") or [])
        unbound_reference_assets = [x for x in reference_assets if not bool(x.get("current_runtime_bound"))]
        donor_hints = list(parity.get("donor_name_hints") or [])
        activation_effect_count = int(current.get("current_effect_binding_count") or 0)
        activation_audio_count = int(current.get("current_audio_binding_count") or 0)
        activation_unresolved_audio_count = int(current.get("current_audio_unresolved_count") or 0)
        activation_count = activation_effect_count + activation_audio_count

        if activation_count or activation_unresolved_audio_count:
            status = "ACTIVATION_EVIDENCE_PRESENT"
        elif preload_items:
            bad = [x for x in preload_items if x["state"] != "TARGET_PRESENT"]
            status = (
                "PRELOAD_ONLY_BLOCKED_NO_ACTIVATION_PROOF"
                if bad else "PRELOAD_ONLY_TARGET_PRESENT_NO_ACTIVATION_PROOF"
            )
        elif reference_assets:
            status = "REFERENCE_ONLY_NO_CURRENT_ACTIVATION_PROOF"
        elif donor_hints:
            status = "DONOR_HINT_ONLY_NO_CURRENT_ACTIVATION_PROOF"
        else:
            status = "NO_CURRENT_T5_ACTIVATION_PROOF"
        counts[status] += 1

        rows.append({
            "class": cls,
            "skill_id": str(current.get("skill_id") or ""),
            "skill_name": skill_name,
            "status": status,
            "activation_effect_binding_count": activation_effect_count,
            "activation_audio_binding_count": activation_audio_count,
            "activation_audio_unresolved_count": activation_unresolved_audio_count,
            "activation_bindings": list(current.get("bindings") or []),
            "preload_count": len(preload_items),
            "preloads": sorted(preload_items, key=lambda x: x["logical_path"].casefold()),
            "reference_unbound_asset_count": len(unbound_reference_assets),
            "reference_unbound_assets": unbound_reference_assets,
            "donor_name_hint_count": len(donor_hints),
            "donor_name_hints": donor_hints,
        })

    return {
        "format": "PT_ASSET_T5_ACTIVATION_READINESS_V1",
        "status": "PASS",
        "tier": 5,
        "skill_count": len(rows),
        "activation_effect_skill_count": sum(1 for x in rows if int(x.get("activation_effect_binding_count") or 0) > 0),
        "activation_audio_skill_count": sum(1 for x in rows if int(x.get("activation_audio_binding_count") or 0) > 0),
        "preload_skill_count": sum(1 for x in rows if int(x.get("preload_count") or 0) > 0),
        "preload_root_count": sum(int(x.get("preload_count") or 0) for x in rows),
        "preload_missing_or_conflict_count": sum(
            1 for x in rows for item in x.get("preloads", []) if item.get("state") != "TARGET_PRESENT"
        ),
        "reference_unbound_asset_count": sum(int(x.get("reference_unbound_asset_count") or 0) for x in rows),
        "status_counts": dict(sorted(counts.items())),
        "scoped_import_root_count": int(t5_readiness.get("scoped_import_root_count") or 0),
        "scoped_import_ready": bool(t5_readiness.get("scoped_import_ready")),
        "policy": {
            "particle_preload_is_not_effect_activation": True,
            "preload_evidence_never_authorizes_import": True,
            "reference_only_asset_is_not_activation_proof": True,
            "current_activation_binding_required_for_scoped_import": True,
            "client_write_authorized": False,
        },
        "rows": rows,
    }


def audit_general_asset_census(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    server_root: str | pathlib.Path,
    *,
    source_root: str | pathlib.Path | None,
    reference_source_root: str | pathlib.Path | None,
    donor_clients: Iterable[str],
    donor_servers: Iterable[str],
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Build a plan-only, fail-closed client/server reachability census.

    This is deliberately not an installer. Donor presence, manifest presence and
    raw binary-string references remain separate evidence classes. Only semantic
    runtime edges (class contracts, model resolution, particle registry, field
    bundles and face-used Model0.62 materials) can set ``required_by_reachable_root``.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve()
    out_dir = project / "pt_build" / "general_asset_census"
    out_dir.mkdir(parents=True, exist_ok=True)

    def p(msg: str) -> None:
        if progress:
            progress(msg)

    donor_client_roots = parse_labeled_roots(donor_clients)
    donor_server_roots = parse_labeled_roots(donor_servers)

    p("plan-only Summit superset")
    superset = build_summit_superset(
        project, client, server,
        source_root=source_root,
        reference_source_root=reference_source_root,
        donor_clients=donor_clients,
        donor_servers=donor_servers,
        materialize=False,
        progress=lambda m: p("superset: " + m),
    )

    p("full dependency graph (client scan enabled)")
    vendor = build_dependency_graph(
        project, client, server,
        skip_client_scan=False,
        progress=lambda m: p("graph: " + m),
    )
    p("server entity/field/item audits")
    entity_report = audit_server_entity_bundles(project, server, client, progress=lambda m: p("entities: " + m))
    field_report = audit_server_field_bundles(project, server, progress=lambda m: p("fields: " + m))
    item_report = audit_server_item_bundles(project, server, progress=lambda m: p("items: " + m))
    manifest_report = audit_client_manifests(project, client)
    p("cooked DDS evidence")
    cooked_report = audit_cooked_texture_evidence(project, client)
    cooked_by_source = cooked_index(cooked_report)
    p("class UI alias audit")
    class_ui_alias = audit_class_ui_aliases(project, client)

    p("current source literal evidence")
    current_tree, _reference_tree = require_source_trees(
        project,
        source_root=source_root,
        reference_source_root=reference_source_root,
        require_current=True,
        require_reference=True,
    )
    assert current_tree is not None
    source_ev = scan_source_evidence(current_tree)

    client_target = _walk_index(client)
    server_target = _walk_index(server)
    client_roots = [("SUMMIT_CLIENT", client), *donor_client_roots]
    server_roots = [("SUMMIT_SERVER", server), *donor_server_roots]

    client_superset_dir = project / "pt_build" / "aggregate" / "client_superset" / "all"
    server_superset_dir = project / "pt_build" / "aggregate" / "server_superset" / "all"
    client_plan = _read_tsv(client_superset_dir / "provenance.tsv")
    server_plan = _read_tsv(server_superset_dir / "provenance.tsv")
    client_plan_by_key = {_norm(r.get("canonical_path") or "").casefold(): r for r in client_plan if _norm(r.get("canonical_path") or "")}
    server_plan_by_key = {_norm(r.get("canonical_path") or "").casefold(): r for r in server_plan if _norm(r.get("canonical_path") or "")}

    strong_client: dict[str, set[str]] = defaultdict(set)
    review_client: dict[str, set[str]] = defaultdict(set)
    strong_server: dict[str, set[str]] = defaultdict(set)
    review_server: dict[str, set[str]] = defaultdict(set)
    diagnostics: list[dict[str, Any]] = []

    def known_client(path: str) -> bool:
        key = _norm(path).casefold()
        return key in client_target or key in client_plan_by_key

    def known_server(path: str) -> bool:
        key = _norm(path).casefold()
        return key in server_target or key in server_plan_by_key

    def mark_client(path: str, evidence: str, *, strong: bool = True) -> str:
        rel = _norm(path)
        if not rel:
            return rel
        key = rel.casefold()
        # Runtime model logical names in INF/NPC are frequently .ini aliases for
        # a physical .inx. Prefer the physical INX when it exists in target/donors.
        pp = pathlib.PurePosixPath(rel)
        if pp.suffix.casefold() == ".ini" and key.startswith("char/"):
            inx = pp.with_suffix(".inx").as_posix()
            if known_client(inx):
                review_client[key].add(evidence + ":LOGICAL_INI_ALIAS")
                rel, key = inx, inx.casefold()
                evidence = evidence + ":RUNTIME_INX_ALIAS"
        if pp.suffix.casefold() == ".ase":
            smd = pp.with_suffix(".smd").as_posix()
            if known_client(smd):
                review_client[key].add(evidence + ":ASE_FALLBACK_REFERENCE")
                rel, key = smd, smd.casefold()
                evidence = evidence + ":RUNTIME_SMD_PREFERENCE"
        (strong_client if strong else review_client)[key].add(evidence)
        return rel

    def mark_server(path: str, evidence: str, *, strong: bool = True) -> str:
        rel = _norm(path)
        if not rel:
            return rel
        (strong_server if strong else review_server)[rel.casefold()].add(evidence)
        return rel

    # ------------------------------------------------------------------
    # Summit canonical JSON is the preferred asset authority for paths already
    # migrated out of source. Explicit CLIENT runtime fields become strong roots;
    # report/provenance/server references remain review evidence only.
    p("Summit canonical asset relations")
    canonical_assets = audit_canonical_asset_relations(project, client, current_tree.root)
    for root_row in canonical_assets.get("strong_client_roots", []):
        rel = _norm(root_row.get("path") or "")
        for evidence in root_row.get("evidence", []) or ["SUMMIT_CANONICAL"]:
            if rel:
                mark_client(rel, str(evidence), strong=True)
    for review_row in canonical_assets.get("review_client_paths", []):
        rel = _norm(review_row.get("path") or "")
        for evidence in review_row.get("evidence", []) or ["SUMMIT_CANONICAL_REVIEW"]:
            if rel:
                mark_client(rel, str(evidence), strong=False)

    # ------------------------------------------------------------------
    # Legacy effect runtime loaders. Bare animation names such as Return1.ini
    # are resolved through Effect/AnimationData; exact Effect/... literals are
    # promoted only when passed to known effect loader APIs. This bridges the
    # dynamic name-based effect runtime into physical client paths without
    # treating arbitrary source literals as roots.
    # ------------------------------------------------------------------
    p("legacy effect runtime root coverage")
    effect_runtime = audit_effect_runtime_coverage(project, client, current_tree)
    for root_row in effect_runtime.get("roots", []):
        rel = _norm(root_row.get("path") or "")
        for evidence in root_row.get("evidence", []) or ["EFFECT_RUNTIME_LOADER"]:
            if rel:
                mark_client(rel, str(evidence), strong=True)
    for review_row in effect_runtime.get("review", []):
        for candidate in review_row.get("candidates", []) or []:
            rel = _norm(candidate)
            if rel:
                mark_client(rel, f"EFFECT_RUNTIME_AMBIGUOUS:{review_row.get('callee')}:{review_row.get('source_file')}:{review_row.get('source_line')}", strong=False)

    # ------------------------------------------------------------------
    # Current-source literals are useful evidence, but not automatically a
    # runtime root: dead/optional code can retain literals.
    # ------------------------------------------------------------------
    source_literal_paths: set[str] = set()
    for row in source_ev.get("literal_refs", []):
        value = _norm(row.get("value") or "")
        if not value:
            continue
        source_literal_paths.add(value.casefold())
        if known_client(value):
            mark_client(value, f"SOURCE_LITERAL:{row.get('source_file')}:{row.get('line')}", strong=False)

    field_witness_by_id: dict[int, tuple[str | None, str]] = {}
    field_runtime_witness_counts = Counter()
    for field_row in field_report.get("rows", []):
        witness, basis = _field_source_stage_witness(field_row, source_literal_paths)
        field_witness_by_id[id(field_row)] = (witness, basis)
        field_runtime_witness_counts[basis] += 1

    # ------------------------------------------------------------------
    # Player-class graph. The graph deliberately contains EU/reference contracts
    # as well as current-runtime evidence. Reference edges are useful for review,
    # but they must not turn donor-only class variants into runtime requirements.
    # Strong reachability therefore follows only classes enabled by MAX_JOBNUM and
    # only current-source/proven parser edges from those classes.
    # ------------------------------------------------------------------
    player_graph_path = project / "pt_build" / "asset_contracts" / "player_class_contract_graph.json"
    pg = _load_player_graph(player_graph_path)
    pnodes = {n.get("node_id"): n for n in pg.get("nodes", []) if n.get("node_id")}
    pedges = list(pg.get("edges", []))
    padj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in pedges:
        padj[str(e.get("source"))].append(e)
    active_classes = {
        nid for nid, n in pnodes.items()
        if n.get("node_type") == "PLAYER_CLASS"
        and str((n.get("attributes") or {}).get("status") or "") == "RUNTIME_JOB_ENABLED"
    }
    active_class_names = {x.split(":", 1)[1] for x in active_classes if ":" in x}
    try:
        current_class_configs = parse_reference_class_configs(current_tree, active_class_names)
    except Exception as exc:
        current_class_configs = []
        diagnostics.append({"kind": "CURRENT_CLASS_CONFIG_SCAN_REVIEW", "error": f"{type(exc).__name__}:{exc}"})
    current_class_paths = {
        _norm(x.get("logical_inx") or "").casefold()
        for x in current_class_configs
        if _norm(x.get("logical_inx") or "")
    }
    current_skill_nodes = {
        f"SKILL:{row.get('class')}:{'SKILLID_' + str(row.get('skill_name') or '')}"
        for row in source_ev.get("class_skill_mentions", [])
        if row.get("class") in active_class_names
        and row.get("layer") in {"CLIENT_RUNTIME", "SERVER_RUNTIME"}
        and row.get("skill_name")
    }
    for e in pedges:
        src = str(e.get("source") or "")
        ev = str(e.get("evidence") or "")
        status = str(e.get("status") or "")
        if src.startswith("SKILL:") and (
            ev.startswith("CURRENT_HANDLER:")
            or ev.startswith("CURRENT_SOURCE:")
            or status.startswith("CURRENT_RUNTIME")
        ):
            current_skill_nodes.add(src)

    allowed_player_relations = {
        "HAS_SKILL", "REQUIRES_ASSET", "USES_EFFECT_TOKEN", "RESOLVES_PARTICLE_SCRIPT",
        "TRANSITIVE_REFERENCE", "USES_CLASS_CONFIG", "LINKS_MOTION_ROOT", "PAIRS_MOTION_SMB",
        "REQUESTS_CLASS_MOTION_STATE", "RESOLVES_TO_CLASS_MOTION_STATE", "DECLARES_MOTION_STATE",
        "HAS_CLASS_AUDIO_FAMILY",
    }

    # Broad/reference traversal is kept as review evidence.
    reached_review: set[str] = set(active_classes)
    q = deque(sorted(active_classes))
    while q:
        src = q.popleft()
        for e in padj.get(src, []):
            if e.get("relation") not in allowed_player_relations:
                continue
            dst = str(e.get("target") or "")
            if dst and dst not in reached_review:
                reached_review.add(dst)
                q.append(dst)

    def _edge_current_runtime(src: str, e: dict[str, Any]) -> bool:
        relation = str(e.get("relation") or "")
        dst = str(e.get("target") or "")
        ev = str(e.get("evidence") or "")
        status = str(e.get("status") or "")
        if src.startswith("PLAYER_CLASS:"):
            if relation == "HAS_SKILL":
                return dst in current_skill_nodes
            if relation == "USES_CLASS_CONFIG":
                n = pnodes.get(dst) or {}
                logical = _norm((n.get("attributes") or {}).get("logical_path") or "")
                return logical.casefold() in current_class_paths
            return False
        if src.startswith("SKILL:"):
            return (
                ev.startswith("CURRENT_HANDLER:")
                or ev.startswith("CURRENT_SOURCE:")
                or status.startswith("CURRENT_RUNTIME")
            )
        if src.startswith("EFFECT_TOKEN:"):
            return relation == "RESOLVES_PARTICLE_SCRIPT"
        if src.startswith("ASSET:"):
            return relation in {"TRANSITIVE_REFERENCE", "LINKS_MOTION_ROOT", "PAIRS_MOTION_SMB", "DECLARES_MOTION_STATE"}
        if src.startswith("ANIMATION_TOKEN:"):
            return relation == "RESOLVES_TO_CLASS_MOTION_STATE"
        return False

    reached_strong: set[str] = set(active_classes)
    q = deque(sorted(active_classes))
    while q:
        src = q.popleft()
        for e in padj.get(src, []):
            if e.get("relation") not in allowed_player_relations or not _edge_current_runtime(src, e):
                continue
            dst = str(e.get("target") or "")
            if dst and dst not in reached_strong:
                reached_strong.add(dst)
                q.append(dst)

    def _player_asset_relations(n: dict[str, Any]) -> tuple[list[tuple[str, str]], str]:
        attrs = n.get("attributes") or {}
        resolution = attrs.get("resolution") if isinstance(attrs.get("resolution"), dict) else {}
        physical = str(resolution.get("physical_path") or "")
        logical = _norm(attrs.get("logical_path") or "")
        found: dict[str, tuple[str, str]] = {}
        if physical:
            label, rel = _physical_rel(physical, client_roots)
            if rel:
                found[rel.casefold()] = (label or "PHYSICAL", rel)
        for raw in resolution.get("candidates") or []:
            candidate = str(raw)
            if ":" in candidate and not candidate.startswith("/"):
                _prefix, maybe_path = candidate.split(":", 1)
                if maybe_path.startswith("/"):
                    candidate = maybe_path
            label, rel = _physical_rel(candidate, client_roots)
            if rel:
                found[rel.casefold()] = (label or "CANDIDATE", rel)
        return list(found.values()), logical

    for nid in reached_review:
        n = pnodes.get(nid) or {}
        if n.get("node_type") != "ASSET":
            continue
        rels, logical = _player_asset_relations(n)
        if rels:
            for label, rel in rels:
                mark_client(rel, f"PLAYER_CLASS_REFERENCE:{label}", strong=False)
        elif logical:
            mark_client(logical, "PLAYER_CLASS_REFERENCE:LOGICAL", strong=False)

    for nid in reached_strong:
        n = pnodes.get(nid) or {}
        if n.get("node_type") != "ASSET":
            continue
        rels, logical = _player_asset_relations(n)
        if len({rel.casefold() for _label, rel in rels}) == 1 and rels:
            label, rel = rels[0]
            mark_client(rel, f"PLAYER_CLASS_RUNTIME:{label}", strong=True)
        elif rels:
            # Multiple basename/path candidates are evidence, not equivalence.
            for label, rel in rels:
                mark_client(rel, f"PLAYER_CLASS_RUNTIME_AMBIGUOUS:{label}", strong=False)
            diagnostics.append({"kind": "PLAYER_CLASS_RUNTIME_PATH_AMBIGUOUS", "node": nid, "paths": [rel for _label, rel in rels]})
        elif logical and "/" in logical:
            mark_client(logical, "PLAYER_CLASS_RUNTIME:LOGICAL", strong=True)
        elif logical:
            # A bare basename cannot become a canonical recovery path without a
            # unique physical-relative resolution. Keep it visible as review.
            mark_client(logical, "PLAYER_CLASS_RUNTIME_BASENAME_REVIEW", strong=False)

    # ------------------------------------------------------------------
    # Field/entity runtime roots. Monster definitions are batch-loaded by the
    # server. NPC definitions are different: presence under GameServer/NPC is
    # inventory evidence, not by itself proof that the NPC is opened at runtime.
    # A canonical active SPC ADD_NPC record is a strong runtime witness only
    # when the owning field has a current-source configured-stage witness.
    # ------------------------------------------------------------------
    spc_runtime_counts = Counter()
    for field_row in field_report.get("rows", []):
        field_stage, field_basis = field_witness_by_id.get(
            id(field_row), (None, "NO_CURRENT_SOURCE_FIELD_STAGE_LITERAL")
        )
        field_runtime_proven = bool(field_stage)
        spc_rel = _norm(field_row.get("spc") or "")
        if not spc_rel:
            continue
        spc_path = server_target.get(spc_rel.casefold())
        if spc_path is None:
            continue
        try:
            detail = _inspect_spc(spc_path.read_bytes())
        except Exception as exc:
            diagnostics.append({"kind": "SPC_RUNTIME_PARSE_REVIEW", "path": spc_rel, "error": f"{type(exc).__name__}:{exc}"})
            spc_runtime_counts["PARSE_ERROR"] += 1
            continue
        if detail.get("status") != "PASS":
            diagnostics.append({"kind": "SPC_RUNTIME_LAYOUT_REVIEW", "path": spc_rel, "status": detail.get("status")})
            spc_runtime_counts["LAYOUT_REVIEW"] += 1
            continue
        for rec in detail.get("records") or []:
            if not rec.get("runtime_active"):
                continue
            idx = rec.get("index")
            model = _norm(rec.get("model_ini") or "")
            npc_def = _spc_server_npc_rel(rec.get("server_npc") or "")
            if rec.get("standard_add_npc_code"):
                spc_runtime_counts["STANDARD_ADD_NPC"] += 1
                if field_runtime_proven:
                    spc_runtime_counts["STANDARD_ADD_NPC_STRONG"] += 1
                    stage_ev = f":FIELD_STAGE:{field_stage}"
                    if model:
                        mark_client(model, f"SPC_ACTIVE_NPC_MODEL:{spc_rel}#{idx}{stage_ev}", strong=True)
                    if npc_def:
                        mark_server(npc_def, f"SPC_ACTIVE_NPC_DEF:{spc_rel}#{idx}{stage_ev}", strong=True)
                else:
                    spc_runtime_counts["STANDARD_ADD_NPC_REVIEW_ONLY"] += 1
                    if model:
                        mark_client(model, f"SPC_INSTALLED_FIELD_NPC_MODEL:{spc_rel}#{idx}:{field_basis}", strong=False)
                    if npc_def:
                        mark_server(npc_def, f"SPC_INSTALLED_FIELD_NPC_DEF:{spc_rel}#{idx}:{field_basis}", strong=False)
            else:
                # Unknown active record codes remain visible but cannot promote
                # recovery without a parser/runtime contract for that code.
                spc_runtime_counts["NONSTANDARD_ACTIVE_REVIEW"] += 1
                if model:
                    mark_client(model, f"SPC_NONSTANDARD_ACTIVE_MODEL:{spc_rel}#{idx}", strong=False)
                if npc_def:
                    mark_server(npc_def, f"SPC_NONSTANDARD_ACTIVE_NPC:{spc_rel}#{idx}", strong=False)

    # SPM actor roots resolve to monster/entity definitions when identity is
    # unique.  This happens before dependency promotion so a definition reached
    # by field metadata can carry its own model/ZHOON closure.
    entity_name_index = _server_definition_names(server)
    spm_actor_resolution = Counter()
    for field_row in field_report.get("rows", []):
        spm_rel = _norm(field_row.get("spm") or "")
        if not spm_rel:
            continue
        spm = server_target.get(spm_rel.casefold())
        if spm is None:
            continue
        field_stage, field_basis = field_witness_by_id.get(
            id(field_row), (None, "NO_CURRENT_SOURCE_FIELD_STAGE_LITERAL")
        )
        field_runtime_proven = bool(field_stage)
        mark_server(
            spm_rel,
            f"FIELD_SPM_RUNTIME_ROOT:FIELD_STAGE:{field_stage}" if field_runtime_proven else f"FIELD_SPM_INSTALLED_REVIEW:{field_basis}",
            strong=field_runtime_proven,
        )
        for kind, actor in _spm_actor_names(spm):
            defs = [
                x for x in entity_name_index.get(actor.casefold(), [])
                if x.casefold().startswith("gameserver/monster/")
            ]
            if len(defs) == 1:
                mark_server(defs[0], f"SPM_{kind}:{spm_rel}:{actor}", strong=field_runtime_proven)
                spm_actor_resolution["UNIQUE"] += 1
                spm_actor_resolution["UNIQUE_RUNTIME" if field_runtime_proven else "UNIQUE_REVIEW_ONLY"] += 1
            elif defs:
                spm_actor_resolution["AMBIGUOUS"] += 1
            else:
                spm_actor_resolution["UNRESOLVED"] += 1

    # Monster definitions are enumerated and decoded in InitMonster(), so their
    # bundle references are strong even when no SPM happens to spawn them. NPC
    # definitions are promoted only when another runtime root (currently SPC or
    # another semantic edge) reaches the definition.
    for row in entity_report.get("rows", []):
        definition = _norm(row.get("definition") or "")
        kind = str(row.get("kind") or "").upper()
        if definition and kind == "MONSTER":
            mark_server(definition, "SERVER_MONSTER_BATCH_LOAD", strong=True)

    for row in entity_report.get("rows", []):
        definition = _norm(row.get("definition") or "")
        def_key = definition.casefold()
        kind = str(row.get("kind") or "").upper()
        entity_strong = bool(definition and def_key in strong_server)
        if definition and not entity_strong:
            mark_server(definition, f"SERVER_{kind or 'ENTITY'}_DEFINITION_NOT_RUNTIME_PROVEN", strong=False)
        model = _norm(row.get("model_reference") or "")
        if model:
            mark_client(
                model,
                f"SERVER_ENTITY_MODEL:{row.get('definition')}",
                strong=entity_strong,
            )
        for zr in row.get("zhoon") or []:
            ref = _norm(zr.get("reference") or "")
            if not ref:
                continue
            resolved_rel = ""
            if zr.get("path"):
                _label, resolved_rel = _physical_rel(str(zr["path"]), server_roots)
            if resolved_rel:
                expected = resolved_rel
            else:
                try:
                    parent = pathlib.PurePosixPath(definition).parent
                    expected = (parent / pathlib.PurePosixPath(ref)).as_posix()
                except Exception:
                    expected = ref
            if zr.get("shared_default_review"):
                mark_server(expected, "ZHOON_SHARED_DEFAULT_REVIEW", strong=False)
            else:
                mark_server(
                    expected,
                    f"SERVER_ENTITY_ZHOON:{row.get('definition')}",
                    strong=entity_strong,
                )

    # ------------------------------------------------------------------
    # Field bundles. Presence is inventory evidence only. Stage/companions become
    # strong when a current-source stage witness activates the exact family.
    # ------------------------------------------------------------------
    for row in field_report.get("rows", []):
        field_stage, field_basis = field_witness_by_id.get(
            id(row), (None, "NO_CURRENT_SOURCE_FIELD_STAGE_LITERAL")
        )
        field_runtime_proven = bool(field_stage)
        selected_stage = _norm(row.get("selected_stage") or "")
        if field_runtime_proven and field_stage:
            mark_server(field_stage, f"FIELD_RUNTIME_STAGE:{row.get('basename')}:{field_basis}", strong=True)
        else:
            stage_candidates = list(row.get("stage_candidates") or [])
            if selected_stage and selected_stage not in stage_candidates:
                stage_candidates.append(selected_stage)
            for stage in stage_candidates:
                mark_server(_norm(stage), f"FIELD_INSTALLED_STAGE_REVIEW:{row.get('basename')}:{field_basis}", strong=False)
        by_ext = {
            ".spm": _norm(row.get("spm") or ""),
            ".spp": _norm(row.get("spp") or ""),
            ".spc": _norm(row.get("spc") or ""),
        }
        present = [x for x in by_ext.values() if x]
        for rel in present:
            mark_server(
                rel,
                f"FIELD_COMPANION_RUNTIME:{row.get('basename')}:FIELD_STAGE:{field_stage}" if field_runtime_proven else f"FIELD_COMPANION_INSTALLED_REVIEW:{row.get('basename')}:{field_basis}",
                strong=field_runtime_proven,
            )
        if present:
            sample = pathlib.PurePosixPath(present[0])
            parent = sample.parent
            # Remove only the outer companion extension, preserving a nested
            # logical stage suffix such as ``.ase``.
            base_prefix = sample.name[: -len(sample.suffix)] if sample.suffix else sample.name
            for ext, rel in by_ext.items():
                if rel:
                    continue
                expected = (parent / f"{base_prefix}{ext}").as_posix()
                mark_server(expected, f"FIELD_MISSING_COMPANION_REVIEW:{row.get('basename')}", strong=False)

    # Item definitions are parser-driven server roots. Their deeper client icon/
    # model expectations stay review until an item code/root proves reachability.
    for row in item_report.get("rows", []):
        definition = _norm(row.get("definition") or "")
        if definition:
            mark_server(definition, "SERVER_OPENITEM_DEFINITION", strong=True)

    # ------------------------------------------------------------------
    # Vendor graph semantic closure. Raw SMD client_asset_reference edges are
    # intentionally NOT strong; face-used material parsing below is authoritative.
    # ------------------------------------------------------------------
    graph_json = pathlib.Path(str(vendor.get("graph_dir") or "")) / "graph.json"
    vg = json.loads(graph_json.read_text(encoding="utf-8")) if graph_json.is_file() else {"nodes": [], "edges": []}
    vnodes = {str(n.get("id")): n for n in vg.get("nodes", [])}
    vedges_by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in vg.get("edges", []):
        vedges_by_src[str(e.get("src"))].append(e)
        if e.get("relation") == "server_character_model":
            dst = vnodes.get(str(e.get("dst"))) or {}
            path = _norm(dst.get("path") or "")
            evidence_def = _norm(e.get("evidence") or "")
            # Vendor graph scans every INF/NPC file. Monster definitions are
            # batch-loaded; NPC files need a runtime witness such as active SPC.
            strong_edge = bool(evidence_def and (evidence_def.casefold().startswith("gameserver/monster/") or evidence_def.casefold() in strong_server))
            if path:
                mark_client(
                    path,
                    f"SERVER_CHARACTER_MODEL:{e.get('evidence')}",
                    strong=strong_edge,
                )
        elif e.get("relation") == "fixed_character_binary_reference":
            dst = vnodes.get(str(e.get("dst"))) or {}
            path = _norm(dst.get("path") or "")
            if path:
                mark_client(path, f"SPC_BINARY_REFERENCE:{e.get('evidence')}", strong=False)

    # Repeatedly propagate strong client references through formats where the
    # existing graph extraction represents a parser/runtime relationship closely
    # enough. SMD is excluded here on purpose.
    propagating_exts = {".ini", ".inf", ".inx", ".ase", ".part", ".lua", ".msg", ".sin", ".fnt", ".fx"}
    changed = True
    while changed:
        changed = False
        current_keys = list(strong_client.keys())
        for key in current_keys:
            src_id = "client:" + key
            ext = pathlib.PurePosixPath(key).suffix.casefold()
            if ext not in propagating_exts:
                continue
            for e in vedges_by_src.get(src_id, []):
                if e.get("relation") != "client_asset_reference":
                    continue
                dst = vnodes.get(str(e.get("dst"))) or {}
                path = _norm(dst.get("path") or "")
                if not path:
                    continue
                # INX files retain historical/source ASE references. The runtime
                # prefers a physical sibling SMD when present; an ASE reference
                # without that sibling is review evidence until loader necessity
                # is proven, not a strong missing-runtime edge.
                if ext == ".inx" and pathlib.PurePosixPath(path).suffix.casefold() == ".ase":
                    smd = pathlib.PurePosixPath(path).with_suffix(".smd").as_posix()
                    if known_client(smd):
                        before = len(strong_client)
                        mark_client(path, f"{ext.upper()}_REFERENCE:{e.get('evidence')}", strong=True)
                        if len(strong_client) != before:
                            changed = True
                    else:
                        mark_client(path, f"INX_ASE_SOURCE_REFERENCE:{e.get('evidence')}", strong=False)
                    continue
                before = len(strong_client)
                mark_client(path, f"{ext.upper()}_REFERENCE:{e.get('evidence')}", strong=True)
                if len(strong_client) != before:
                    changed = True

    # ------------------------------------------------------------------
    # Model0.62 face-used texture closure. This is the only path by which raw
    # SMD material strings are promoted to strong texture reachability.
    # ------------------------------------------------------------------
    model_scope_failures = 0
    for key in list(strong_client.keys()):
        if pathlib.PurePosixPath(key).suffix.casefold() != ".smd":
            continue
        physical = client_target.get(key)
        if physical is None:
            prow = client_plan_by_key.get(key) or {}
            selected = str(prow.get("selected_path") or "")
            physical = pathlib.Path(selected) if selected and pathlib.Path(selected).is_file() else None
        if physical is None:
            continue
        scope = _face_texture_references_smd(physical, project)
        if scope.get("status") != "PASS":
            model_scope_failures += 1
            diagnostics.append({"kind": "MODEL_FACE_TEXTURE_SCOPE_REVIEW", "path": key, "detail": scope})
            continue
        for logical in scope.get("required_names") or []:
            logical = _norm(logical)
            if not logical:
                continue
            if "/" not in logical:
                review_client[logical.casefold()].add(f"MODEL_FACE_TEXTURE_UNQUALIFIED:{key}")
                continue
            mark_client(logical, f"MODEL_FACE_TEXTURE:{key}", strong=True)

    # ------------------------------------------------------------------
    # Manifest evidence (positive evidence only, never a root).
    # ------------------------------------------------------------------
    manifest_exact: dict[str, list[str]] = defaultdict(list)
    manifest_boundary: list[tuple[str, str]] = []
    for name in ("setfile.lst", "_update.inf"):
        mp = client / name
        if not mp.is_file():
            continue
        parsed = parse_fixed_manifest(mp)
        if parsed.get("status") != "PASS":
            continue
        for row in parsed.get("records", []):
            path = _norm(row.get("path") or "")
            if not path:
                continue
            if row.get("path_boundary_risk"):
                manifest_boundary.append((path.casefold(), name))
            else:
                manifest_exact[path.casefold()].append(name)

    # ------------------------------------------------------------------
    # Candidate rows from donor superset plans.
    # ------------------------------------------------------------------
    rows: list[dict[str, Any]] = []

    def candidate_row(side: str, r: dict[str, Any]) -> dict[str, Any]:
        path = _norm(r.get("canonical_path") or "")
        key = path.casefold()
        strong_map = strong_client if side == "CLIENT" else strong_server
        review_map = review_client if side == "CLIENT" else review_server
        action = str(r.get("action") or "")
        strong_ev = sorted(strong_map.get(key, set()))
        review_ev = sorted(review_map.get(key, set()))
        manifest_ev: list[str] = []
        source_ev_here: list[str] = []
        if side == "CLIENT":
            manifest_ev = [f"MANIFEST_EXACT:{x}" for x in manifest_exact.get(key, [])]
            for prefix, name in manifest_boundary:
                if key.startswith(prefix):
                    manifest_ev.append(f"MANIFEST_TRUNCATED_PREFIX:{name}")
            if key in source_literal_paths:
                source_ev_here.append("CURRENT_SOURCE_LITERAL")
        required = bool(strong_ev)
        distinct = int(r.get("distinct_hash_count") or 0) if str(r.get("distinct_hash_count") or "").isdigit() else 0
        if action == "KEEP_TARGET":
            decision = "PRESENT_TARGET"
        elif action == "EXCLUDE_NON_DEPLOYABLE":
            decision = "EXCLUDE_POLICY"
        elif action == "ARCHIVE_REFERENCE_ONLY":
            decision = "REVIEW_REFERENCE_ONLY"
        elif action in HARD_REVIEW_ACTIONS:
            decision = "REVIEW_HARD_CONFLICT"
        elif action in RECOVERY_ACTIONS and required:
            decision = "REVIEW_REACHABLE_DONOR_CONFLICT" if action == "RECOVER_PREFERRED_VARIANT" or distinct > 1 else "RECOVERABLE_REACHABLE_CANDIDATE"
        elif action in RECOVERY_ACTIONS and manifest_ev:
            decision = "REVIEW_MANIFEST_DONOR_GAP"
        elif action in RECOVERY_ACTIONS and source_ev_here:
            decision = "REVIEW_SOURCE_DONOR_GAP"
        elif action in RECOVERY_ACTIONS:
            decision = "DONOR_GAP_NOT_REACHED"
        else:
            decision = "REVIEW"
        ext = pathlib.PurePosixPath(path).suffix.casefold()
        return {
            "side": side,
            "path": path,
            "extension": ext,
            "physical_family": infer_physical_family(path, ext) if side == "CLIENT" else str(r.get("category") or "SERVER_DATA"),
            "category": r.get("category") or "",
            "deployability": r.get("deployability") or "",
            "donor_action": action,
            "decision": decision,
            "required_by_reachable_root": required,
            "reachability_evidence": " | ".join(strong_ev),
            "review_evidence": " | ".join(review_ev),
            "manifest_evidence": " | ".join(manifest_ev),
            "source_evidence": " | ".join(source_ev_here),
            "selected_source": r.get("selected_source") or "",
            "selected_path": r.get("selected_path") or "",
            "distinct_hash_count": r.get("distinct_hash_count") or "",
            "variant_count": r.get("variant_count") or 0,
            "reason": r.get("reason") or "",
        }

    # Keep only non-target rows in the explorer; target presence is summarized.
    for r in client_plan:
        row = candidate_row("CLIENT", r)
        if row["decision"] != "PRESENT_TARGET":
            rows.append(row)
    for r in server_plan:
        row = candidate_row("SERVER", r)
        if row["decision"] != "PRESENT_TARGET":
            rows.append(row)

    # Strong reachable paths absent from both target and donor superset are true
    # missing-unknown candidates and must remain visible as blockers/review.
    existing_row_keys = {(r["side"], r["path"].casefold()) for r in rows}
    for side, strong_map, target_idx, plan_idx in (
        ("CLIENT", strong_client, client_target, client_plan_by_key),
        ("SERVER", strong_server, server_target, server_plan_by_key),
    ):
        for key, evidence in strong_map.items():
            if key in target_idx or key in plan_idx or (side, key) in existing_row_keys:
                continue
            path = key
            ext = pathlib.PurePosixPath(path).suffix.casefold()
            rows.append({
                "side": side,
                "path": path,
                "extension": ext,
                "physical_family": infer_physical_family(path, ext) if side == "CLIENT" else classify_server_path(path).lifecycle,
                "category": "UNKNOWN" if side == "CLIENT" else classify_server_path(path).lifecycle,
                "deployability": "MISSING",
                "donor_action": "NO_DONOR_CANDIDATE",
                "decision": "MISSING_REACHABLE_NO_DONOR",
                "required_by_reachable_root": True,
                "reachability_evidence": " | ".join(sorted(evidence)),
                "review_evidence": "",
                "manifest_evidence": "",
                "source_evidence": "",
                "selected_source": "",
                "selected_path": "",
                "distinct_hash_count": "",
                "variant_count": 0,
                "reason": "REACHABLE_PATH_ABSENT_TARGET_AND_DONORS",
            })

    # Review-only semantic paths absent from both target and donors remain
    # visible without becoming blockers. This covers missing field companion
    # variants, unresolved INX->ASE source references and shared/default refs.
    existing_row_keys = {(r["side"], r["path"].casefold()) for r in rows}
    for side, review_map, target_idx, plan_idx in (
        ("CLIENT", review_client, client_target, client_plan_by_key),
        ("SERVER", review_server, server_target, server_plan_by_key),
    ):
        for key, evidence in review_map.items():
            if "/" not in key or key in target_idx or key in plan_idx or (side, key) in existing_row_keys:
                continue
            path = key
            ext = pathlib.PurePosixPath(path).suffix.casefold()
            family = infer_physical_family(path, ext) if side == "CLIENT" else classify_server_path(path).lifecycle
            rows.append({
                "side": side,
                "path": path,
                "extension": ext,
                "physical_family": family,
                "category": "REVIEW_REFERENCE" if side == "CLIENT" else family,
                "deployability": "REFERENCE_ONLY",
                "donor_action": "NO_DONOR_CANDIDATE",
                "decision": "REVIEW_REFERENCE_NO_DONOR",
                "required_by_reachable_root": False,
                "reachability_evidence": "",
                "review_evidence": " | ".join(sorted(evidence)),
                "manifest_evidence": "",
                "source_evidence": "",
                "selected_source": "",
                "selected_path": "",
                "distinct_hash_count": "",
                "variant_count": 0,
                "reason": "SEMANTIC_REFERENCE_NOT_STRONG_RUNTIME_REQUIREMENT",
            })
            existing_row_keys.add((side, key))

    # Manifest-only paths that are absent target/donors are evidence rows, not gaps
    # proven by runtime. Boundary/truncated records are intentionally excluded here.
    for key, names in manifest_exact.items():
        if key in client_target or key in client_plan_by_key or ("CLIENT", key) in existing_row_keys:
            continue
        ext = pathlib.PurePosixPath(key).suffix.casefold()
        rows.append({
            "side": "CLIENT", "path": key, "extension": ext,
            "physical_family": infer_physical_family(key, ext), "category": "MANIFEST_ONLY",
            "deployability": "REFERENCE_ONLY", "donor_action": "NO_DONOR_CANDIDATE",
            "decision": "REVIEW_MANIFEST_NO_DONOR", "required_by_reachable_root": False,
            "reachability_evidence": "", "review_evidence": "",
            "manifest_evidence": " | ".join(f"MANIFEST_EXACT:{x}" for x in names),
            "source_evidence": "CURRENT_SOURCE_LITERAL" if key in source_literal_paths else "",
            "selected_source": "", "selected_path": "", "distinct_hash_count": "", "variant_count": 0,
            "reason": "MANIFEST_POSITIVE_EVIDENCE_ONLY",
        })

    # Selected-donor bundle closure. A reachable donor root remains only a
    # recovery candidate until its dependencies are present in target or in the
    # same selected donor lineage. Cross-donor and generic-basename substitution
    # are intentionally forbidden here.
    recovery_bundles: list[dict[str, Any]] = []
    recovery_bundle_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    donor_index_cache: dict[str, dict[str, pathlib.Path]] = {}
    for row in rows:
        if row.get("decision") != "RECOVERABLE_REACHABLE_CANDIDATE":
            continue
        side = str(row.get("side") or "").upper()
        key = _norm(row.get("path") or "").casefold()
        if not key:
            continue
        if side == "CLIENT":
            plan_row = client_plan_by_key.get(key) or row
            bundle_row = _assess_client_recovery_bundle(
                project, plan_row,
                target_idx=client_target,
                donor_roots=donor_client_roots,
                donor_index_cache=donor_index_cache,
                plan_by_key=client_plan_by_key,
            )
        elif side == "SERVER":
            plan_row = server_plan_by_key.get(key) or row
            bundle_row = _assess_server_recovery_bundle(plan_row, donor_server_roots)
        else:
            continue
        recovery_bundles.append(bundle_row)
        recovery_bundle_by_key[(side, key)] = bundle_row

    for row in rows:
        key = (str(row.get("side") or "").upper(), _norm(row.get("path") or "").casefold())
        bundle_row = recovery_bundle_by_key.get(key)
        row["recovery_bundle_status"] = str(bundle_row.get("status") or "") if bundle_row else ""
        row["recovery_bundle_member_count"] = bundle_row.get("member_count", "") if bundle_row else ""
        row["recovery_bundle_missing_count"] = bundle_row.get("missing_count", "") if bundle_row else ""
        row["recovery_bundle_review_count"] = bundle_row.get("review_count", "") if bundle_row else ""

    recovery_bundle_report = out_dir / "recovery_bundles.json"
    recovery_bundle_status_counts = Counter(str(x.get("status") or "UNKNOWN") for x in recovery_bundles)
    recovery_bundle_report.write_text(
        json.dumps({
            "format": "PT_ASSET_GENERAL_RECOVERY_BUNDLES_V1",
            "status": "PASS",
            "root_count": len(recovery_bundles),
            "status_counts": dict(sorted(recovery_bundle_status_counts.items())),
            "policy": {
                "same_selected_donor_lineage_only": True,
                "generic_basename_equivalence_allowed": False,
                "cross_donor_dependency_substitution_allowed": False,
                "client_write_authorized": False,
                "server_write_authorized": False,
                "production_authorized": False,
            },
            "rows": recovery_bundles,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    t5_effect_report = out_dir / "t5_effect_readiness.json"
    t5_asset_report = out_dir / "t5_asset_readiness.json"
    t5_audio_diag_report = out_dir / "t5_audio_diagnostics.json"
    t5_reference_parity_report = out_dir / "t5_reference_parity.json"
    t5_activation_report = out_dir / "t5_activation_readiness.json"
    t5_effect = _t5_effect_readiness(pg, rows, recovery_bundles, client_roots)
    t5_reference_parity = _t5_reference_parity(pg, t5_effect, rows)
    t5_activation = _t5_activation_readiness(pg, t5_effect, t5_reference_parity)
    t5_payload = json.dumps(t5_effect, ensure_ascii=False, indent=2) + "\n"
    # PT_ASSET_RELEASE_1_0_FINALIZATION_V1:
    # t5_asset_readiness.json is canonical. The historical effect filename
    # remains a small compatibility descriptor instead of silently duplicating
    # the complete asset-readiness payload.
    t5_effect_compat = {
        "format": "PT_ASSET_T5_EFFECT_READINESS_COMPAT_V1",
        "status": str(t5_effect.get("status") or "UNKNOWN"),
        "deprecated_compatibility_alias": True,
        "canonical_report": "t5_asset_readiness.json",
        "canonical_format": str(t5_effect.get("format") or ""),
        "policy": {
            "effect_report_is_not_independent_recovery_authority": True,
            "use_t5_asset_readiness_for_full_payload": True,
            "client_write_authorized": False,
        },
    }
    t5_reference_parity_report.write_text(
        json.dumps(t5_reference_parity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    t5_activation_report.write_text(
        json.dumps(t5_activation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    pg_metadata = pg.get("metadata") or {}
    client_audio_probes = [
        x for x in (pg_metadata.get("current_runtime_audio_call_probes") or [])
        if str(x.get("layer") or "") == "CLIENT_RUNTIME"
    ]
    unresolved_client_audio = [x for x in client_audio_probes if not bool(x.get("resolved_identity"))]
    t5_audio_diag_report.write_text(
        json.dumps({
            "format": "PT_ASSET_T5_AUDIO_DIAGNOSTICS_V1",
            "status": "PASS",
            "policy": {
                "diagnostic_only": True,
                "reference_unique_sound_without_current_skill_context_is_not_binding": True,
                "client_write_authorized": False,
            },
            "client_audio_call_probe_count": len(client_audio_probes),
            "client_unresolved_audio_call_probe_count": len(unresolved_client_audio),
            "callee_counts": dict(sorted(Counter(str(x.get("callee") or "UNKNOWN") for x in client_audio_probes).items())),
            "unresolved_callee_counts": dict(sorted(Counter(str(x.get("callee") or "UNKNOWN") for x in unresolved_client_audio).items())),
            "client_audio_call_probes": client_audio_probes,
            "client_unresolved_audio_call_probes": unresolved_client_audio,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep the historical effect filename for compatibility without maintaining
    # two indistinguishable canonical payloads.
    t5_effect_report.write_text(json.dumps(t5_effect_compat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t5_asset_report.write_text(t5_payload, encoding="utf-8")

    rows.sort(key=lambda r: (r["decision"], r["side"], r["path"].casefold()))
    columns = [
        "side", "decision", "required_by_reachable_root", "path", "extension", "physical_family", "category",
        "deployability", "donor_action", "selected_source", "distinct_hash_count", "variant_count",
        "recovery_bundle_status", "recovery_bundle_member_count", "recovery_bundle_missing_count", "recovery_bundle_review_count",
        "reachability_evidence", "review_evidence", "manifest_evidence", "source_evidence", "reason", "selected_path",
    ]
    rows_tsv = out_dir / "candidates.tsv"
    _write_tsv(rows_tsv, rows, columns)

    decision_counts = Counter(str(r["decision"]) for r in rows)
    side_counts = Counter(str(r["side"]) for r in rows)
    family_counts = Counter(str(r["physical_family"]) for r in rows)
    reachable_candidates = [r for r in rows if r["decision"] == "RECOVERABLE_REACHABLE_CANDIDATE"]
    reachable_conflicts = [r for r in rows if r["decision"] == "REVIEW_REACHABLE_DONOR_CONFLICT"]
    reachable_hard_conflicts = [r for r in rows if r["decision"] == "REVIEW_HARD_CONFLICT" and r.get("required_by_reachable_root")]
    missing_reachable = [r for r in rows if r["decision"] == "MISSING_REACHABLE_NO_DONOR"]
    bundle_closed = [x for x in recovery_bundles if x.get("status") == "CLOSED"]
    bundle_review = [x for x in recovery_bundles if x.get("status") == "REVIEW"]
    bundle_incomplete = [x for x in recovery_bundles if x.get("status") == "INCOMPLETE"]
    bundle_not_closed = bundle_review + bundle_incomplete

    p("asset retention / orphan evidence")
    retention_report = audit_asset_retention(
        project, client,
        strong_paths=strong_client,
        review_paths=review_client,
        manifest_exact=manifest_exact,
        source_literal_paths=source_literal_paths,
        cooked_by_source=cooked_by_source,
        graph_path=pathlib.Path(str(vendor.get("graph_dir") or "")) / "graph.json",
    )

    result = {
        "format": FORMAT,
        "status": "PASS",
        "census_state": "REVIEW_REQUIRED" if reachable_conflicts or reachable_hard_conflicts or missing_reachable or bundle_not_closed or class_ui_alias.get("state") == "REVIEW_REQUIRED" else "PLAN_READY",
        "generated_at": time.time(),
        "client_root": str(client),
        "server_root": str(server),
        "source_root": str(current_tree.root),
        "reference_source_root": str(_reference_tree.root) if _reference_tree is not None else None,
        "donor_client_roots": [{"label": label, "root": str(root)} for label, root in donor_client_roots],
        "donor_server_roots": [{"label": label, "root": str(root)} for label, root in donor_server_roots],
        "candidate_count": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "side_counts": dict(sorted(side_counts.items())),
        "physical_family_counts": dict(sorted(family_counts.items())),
        "strong_client_path_count": len(strong_client),
        "strong_server_path_count": len(strong_server),
        "source_literal_path_count": len(source_literal_paths),
        "manifest_exact_path_count": len(manifest_exact),
        "manifest_boundary_path_count": len(manifest_boundary),
        "cooked_texture_state": cooked_report.get("state"),
        "cooked_texture_entry_count": cooked_report.get("entry_count", 0),
        "effect_runtime_root_count": effect_runtime.get("strong_root_count", 0),
        "effect_runtime_review_witness_count": effect_runtime.get("review_witness_count", 0),
        "summit_canonical_asset_root_count": canonical_assets.get("strong_client_root_count", 0),
        "summit_canonical_asset_review_count": canonical_assets.get("review_client_path_count", 0),
        "cooked_texture_failure_count": cooked_report.get("failure_count", 0),
        "cooked_texture_failure_class_counts": cooked_report.get("failure_class_counts", {}),
        "cooked_texture_documented_outlier_failure_count": cooked_report.get("documented_outlier_failure_count", 0),
        "cooked_texture_skip_count": cooked_report.get("skip_count", 0),
        "cooked_texture_skip_class_counts": cooked_report.get("skip_class_counts", {}),
        "cooked_texture_integrity_state_counts": cooked_report.get("asset_integrity_state_counts", {}),
        "asset_retention_state": retention_report.get("state"),
        "asset_retention_asset_count": retention_report.get("asset_count", 0),
        "asset_retention_orphan_candidate_count": retention_report.get("orphan_candidate_count", 0),
        "asset_retention_root_reachable_client_path_count": retention_report.get("root_reachable_client_path_count", 0),
        "asset_retention_graph_linked_root_unreachable_review_count": retention_report.get("graph_linked_root_unreachable_review_count", 0),
        "asset_retention_state_counts": retention_report.get("state_counts", {}),
        "asset_retention_integrity_action_counts": retention_report.get("integrity_action_counts", {}),
        "spm_actor_resolution_counts": dict(sorted(spm_actor_resolution.items())),
        "spc_runtime_counts": dict(sorted(spc_runtime_counts.items())),
        "field_runtime_witness_counts": dict(sorted(field_runtime_witness_counts.items())),
        "model_face_scope_failure_count": model_scope_failures,
        "recoverable_reachable_candidate_count": len(reachable_candidates),
        "reachable_donor_conflict_count": len(reachable_conflicts),
        "reachable_hard_conflict_count": len(reachable_hard_conflicts),
        "missing_reachable_no_donor_count": len(missing_reachable),
        "class_ui_alias_state": class_ui_alias.get("state"),
        "class_ui_alias_review_group_count": class_ui_alias.get("review_group_count", 0),
        "class_ui_alias_split_group_count": class_ui_alias.get("split_group_count", 0),
        "class_ui_alias_only_count": (class_ui_alias.get("counts") or {}).get("ALIAS_ONLY", 0),
        "class_ui_duplicate_identical_count": (class_ui_alias.get("counts") or {}).get("DUPLICATE_IDENTICAL", 0),
        "class_ui_duplicate_conflict_count": (class_ui_alias.get("counts") or {}).get("DUPLICATE_CONFLICT", 0),
        "class_ui_alias_report": class_ui_alias.get("report"),
        "recovery_bundle_root_count": len(recovery_bundles),
        "recovery_bundle_closed_root_count": len(bundle_closed),
        "recovery_bundle_review_root_count": len(bundle_review),
        "recovery_bundle_incomplete_root_count": len(bundle_incomplete),
        "t5_effect_skill_count": t5_effect.get("skill_count", 0),
        "t5_current_runtime_asset_skill_count": t5_effect.get("current_runtime_asset_skill_count", 0),
        "t5_current_runtime_effect_skill_count": t5_effect.get("current_runtime_effect_skill_count", 0),
        "t5_current_runtime_audio_skill_count": t5_effect.get("current_runtime_audio_skill_count", 0),
        "t5_current_runtime_skill_case_count": t5_effect.get("current_runtime_skill_case_count", 0),
        "t5_current_skill_alias_probe_count": t5_effect.get("current_skill_alias_probe_count", 0),
        "t5_current_client_asset_call_probe_count": t5_effect.get("current_client_asset_call_probe_count", 0),
        "t5_current_server_asset_call_probe_count": t5_effect.get("current_server_asset_call_probe_count", 0),
        "t5_current_client_audio_call_probe_count": t5_effect.get("current_client_audio_call_probe_count", 0),
        "t5_current_client_unresolved_audio_call_probe_count": t5_effect.get("current_client_unresolved_audio_call_probe_count", 0),
        "t5_current_client_effect_call_probe_count": t5_effect.get("current_client_effect_call_probe_count", 0),
        "t5_current_client_unresolved_effect_call_probe_count": t5_effect.get("current_client_unresolved_effect_call_probe_count", 0),
        "t5_current_runtime_asset_call_probe_count": t5_effect.get("current_runtime_asset_call_probe_count", 0),
        "t5_current_asset_bridge_case_count": t5_effect.get("current_t5_asset_bridge_case_count", 0),
        "t5_no_current_asset_call_proof_count": t5_effect.get("no_current_asset_call_proof_count", 0),
        "t5_no_current_runtime_effect_proof_count": t5_effect.get("no_current_runtime_effect_proof_count", 0),
        "t5_effect_recoverable_closed_root_count": t5_effect.get("recoverable_closed_effect_root_count", 0),
        "t5_audio_recoverable_closed_root_count": t5_effect.get("recoverable_closed_audio_root_count", 0),
        "t5_asset_recoverable_closed_root_count": t5_effect.get("recoverable_closed_root_count", 0),
        "t5_scoped_import_root_count": t5_effect.get("scoped_import_root_count", 0),
        "t5_effect_scoped_import_ready": bool(t5_effect.get("scoped_import_ready")),
        "t5_asset_scoped_import_ready": bool(t5_effect.get("scoped_import_ready")),
        "candidate_table": str(rows_tsv),
        "recovery_bundle_report": str(recovery_bundle_report),
        "t5_effect_report": str(t5_effect_report),
        "t5_asset_report": str(t5_asset_report),
        "t5_audio_diagnostics_report": str(t5_audio_diag_report),
        "t5_reference_parity_report": str(t5_reference_parity_report),
        "t5_activation_readiness_report": str(t5_activation_report),
        "t5_activation_effect_skill_count": t5_activation.get("activation_effect_skill_count", 0),
        "t5_activation_audio_skill_count": t5_activation.get("activation_audio_skill_count", 0),
        "t5_preload_skill_count": t5_activation.get("preload_skill_count", 0),
        "t5_preload_root_count": t5_activation.get("preload_root_count", 0),
        "components": {
            "summit_superset": superset,
            "vendor_graph": vendor,
            "client_manifests": manifest_report,
            "cooked_texture_evidence": cooked_report,
            "effect_runtime_coverage": effect_runtime,
            "asset_retention": retention_report,
            "class_ui_aliases": class_ui_alias,
            "server_entities_report": entity_report.get("report"),
            "server_fields_report": field_report.get("report"),
            "server_items_report": item_report.get("report"),
            "player_class_graph": str(player_graph_path),
            "recovery_bundles": str(recovery_bundle_report),
            "t5_effect_readiness": str(t5_effect_report),
            "t5_asset_readiness": str(t5_asset_report),
            "t5_audio_diagnostics": str(t5_audio_diag_report),
            "t5_reference_parity": str(t5_reference_parity_report),
            "t5_activation_readiness": str(t5_activation_report),
        },
        "policy": {
            "plan_only": True,
            "donor_gap_is_not_runtime_need": True,
            "manifest_presence_is_not_runtime_need": True,
            "asset_retention_delete_authorized": False,
            "known_effect_runtime_loader_can_promote_strong_root": True,
            "effect_bare_ini_prefers_animationdata_namespace": True,
            "ambiguous_effect_basename_is_review_not_root": True,
            "root_unreachable_component_is_review_not_delete_authority": True,
            "orphan_requires_zero_known_linkage": True,
            "monster_npc_bundle_guard_enabled": True,
            "monster_npc_catalog_guard_enabled": True,
            "cooked_failure_is_diagnostic_not_removal_authority": True,
            "same_basename_is_not_generic_equivalence": True,
            "raw_smd_string_reference_is_not_strong_reachability": True,
            "model062_face_used_materials_are_strong_reachability": True,
            "logical_ini_to_inx_runtime_alias": True,
            "ase_to_smd_runtime_preference_when_physical_smd_exists": True,
            "name_name_zhoon": "SHARED_DEFAULT_REVIEW_NOT_MULTIPLIED_AS_BLOCKERS",
            "player_reference_graph_is_review_only_without_current_runtime_witness": True,
            "field_missing_companion_is_review_not_blocker": True,
            "field_inventory_presence_is_not_runtime_root": True,
            "field_current_source_stage_witness_required_for_spc_spm_promotion": True,
            "spc_standard_add_npc_is_runtime_root_only_with_field_stage_witness": True,
            "npc_definition_presence_alone_is_not_runtime_root": True,
            "inx_ase_source_reference_is_review_without_runtime_smd_alias": True,
            "recoverable_root_requires_bundle_closure_before_staging": True,
            "recovery_bundle_same_selected_donor_lineage_only": True,
            "t5_asset_import_requires_current_asset_call_binding": True,
            "t5_reference_only_effect_or_audio_is_review_not_import_authority": True,
            "t5_partial_skill_asset_bundle_is_not_import_authority": True,
            "t5_reference_unique_sound_requires_current_skill_context": True,
            "t5_reference_parity_is_diagnostic_only": True,
            "t5_particle_preload_is_not_effect_activation": True,
            "t5_preload_evidence_never_authorizes_import": True,
            "client_write_authorized": False,
            "server_write_authorized": False,
            "production_authorized": False,
        },
        "diagnostics": diagnostics[:200],
    }
    report = out_dir / "result.json"
    bundle = out_dir / "reports_bundle.zip"
    result["report"] = str(report)
    result["reports_bundle"] = str(bundle)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Handoff bundle: reports/evidence only; no staged client/server assets.
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(report, arcname="general_asset_census/result.json")
        z.write(rows_tsv, arcname="general_asset_census/candidates.tsv")
        z.write(recovery_bundle_report, arcname="general_asset_census/recovery_bundles.json")
        z.write(t5_effect_report, arcname="general_asset_census/t5_effect_readiness.json")
        z.write(t5_asset_report, arcname="general_asset_census/t5_asset_readiness.json")
        z.write(t5_audio_diag_report, arcname="general_asset_census/t5_audio_diagnostics.json")
        z.write(t5_reference_parity_report, arcname="general_asset_census/t5_reference_parity.json")
        z.write(t5_activation_report, arcname="general_asset_census/t5_activation_readiness.json")
        class_ui_alias_report = project / "pt_build" / "class_ui_alias_audit" / "result.json"
        if class_ui_alias_report.is_file():
            z.write(class_ui_alias_report, arcname="general_asset_census/class_ui_alias_audit.json")
        for pth, arc in (
            (project / "pt_build" / "general_asset_census" / "manifest_evidence" / "result.json", "manifest_evidence/result.json"),
            (project / "pt_build" / "general_asset_census" / "manifest_evidence" / "manifest_paths.tsv", "manifest_evidence/manifest_paths.tsv"),
            (project / "pt_build" / "cooked_texture_evidence" / "result.json", "components/cooked_texture_evidence.json"),
            (project / "pt_build" / "cooked_texture_evidence" / "entries.tsv", "components/cooked_texture_entries.tsv"),
            (project / "pt_build" / "effect_runtime_coverage" / "result.json", "components/effect_runtime_coverage.json"),
            (project / "pt_build" / "summit_asset_migration" / "canonical_asset_relations.json", "components/summit_canonical_asset_relations.json"),
            (project / "pt_build" / "summit_asset_migration" / "canonical_asset_relations.tsv", "components/summit_canonical_asset_relations.tsv"),
            (project / "pt_build" / "asset_retention" / "result.json", "components/asset_retention.json"),
            (project / "pt_build" / "asset_retention" / "assets.tsv", "components/asset_retention_assets.tsv"),
            (project / "pt_build" / "asset_retention" / "components.json", "components/asset_retention_components.json"),
            (project / "pt_build" / "asset_retention" / "components.tsv", "components/asset_retention_components.tsv"),
            (project / "pt_build" / "devtest" / "server_bundle_census" / "result.json", "components/server_bundle_census.json"),
            (project / "pt_build" / "devtest" / "server_field_census" / "result.json", "components/server_field_census.json"),
            (project / "pt_build" / "devtest" / "server_item_census" / "result.json", "components/server_item_census.json"),
            (player_graph_path, "components/player_class_contract_graph.json"),
            (pathlib.Path(str(vendor.get("graph_dir") or "")) / "summary.json", "components/vendor_graph_summary.json"),
        ):
            if pth.is_file():
                z.write(pth, arcname=arc)
    return result


def query_general_asset_census(
    project_root: str | pathlib.Path,
    *,
    query: str = "",
    side: str = "",
    decision: str = "",
    family: str = "",
    component: str = "",
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    out_dir = project / "pt_build" / "general_asset_census"
    report_path = out_dir / "result.json"
    rows_path = out_dir / "candidates.tsv"
    if not report_path.is_file() or not rows_path.is_file():
        return {"status": "NOT_RUN", "rows": [], "total_rows": 0, "filtered_rows": 0}
    summary = json.loads(report_path.read_text(encoding="utf-8"))
    rows = _read_tsv(rows_path)
    q = query.casefold().strip()
    side_u = side.upper().strip()
    decision_u = decision.upper().strip()
    family_u = family.upper().strip()
    component_q = component.casefold().strip()
    filtered = []
    for row in rows:
        if side_u and str(row.get("side") or "").upper() != side_u:
            continue
        if decision_u and str(row.get("decision") or "").upper() != decision_u:
            continue
        if family_u and str(row.get("physical_family") or "").upper() != family_u:
            continue
        if component_q:
            component_value = str(row.get("component_id") or row.get("component") or "").casefold()
            if component_q not in component_value:
                continue
        if q:
            hay = " ".join(str(row.get(k) or "") for k in (
                "path", "decision", "category", "physical_family", "reachability_evidence",
                "review_evidence", "manifest_evidence", "source_evidence", "reason", "selected_source",
                "recovery_bundle_status",
            )).casefold()
            if q not in hay:
                continue
        filtered.append(row)
    offset = max(0, int(offset))
    limit = max(1, min(1000, int(limit)))
    return {
        "status": summary.get("status", "PASS"),
        "census_state": summary.get("census_state"),
        "summary": {k: v for k, v in summary.items() if k not in {"diagnostics", "components"}},
        "total_rows": len(rows),
        "filtered_rows": len(filtered),
        "offset": offset,
        "limit": limit,
        "rows": filtered[offset:offset + limit],
        "client_write_authorized": False,
        "server_write_authorized": False,
        "production_authorized": False,
    }
