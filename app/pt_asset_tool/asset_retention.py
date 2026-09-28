from __future__ import annotations

import csv
import json
import os
import pathlib
from collections import Counter, defaultdict, deque
from typing import Any, Iterable

from .ui_catalog import infer_physical_family, infer_semantics, infer_visibility_tier

FORMAT = "PT_ASSET_RETENTION_EVIDENCE_V2"
ENTITY_PREFIXES = ("char/monster/", "char/npc/")
GENERATED_PREFIXES = ("cooked/",)
ROOT_SOURCE_SAMPLE_LIMIT = 8
EDGE_SAMPLE_LIMIT = 8


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _walk(root: pathlib.Path) -> list[str]:
    rows: list[str] = []
    if not root.is_dir():
        return rows
    for base, dirs, files in os.walk(root):
        dirs.sort(key=str.casefold); files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(base) / name
            try:
                rows.append(p.relative_to(root).as_posix())
            except ValueError:
                pass
    return rows


def _display_graph_node(value: str) -> str:
    text = str(value or "")
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if prefix.casefold() in {"client", "server"}:
            return f"{prefix.casefold()}:{_norm(rest)}"
    return text


def _edge_detail(edge: dict[str, Any]) -> str:
    src = _display_graph_node(str(edge.get("src") or ""))
    dst = _display_graph_node(str(edge.get("dst") or ""))
    relation = str(edge.get("relation") or edge.get("type") or "EDGE")
    evidence = str(edge.get("evidence") or "")
    detail = f"{src} --{relation}--> {dst}"
    return f"{detail} [{evidence}]" if evidence else detail


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _entity_bundle_key(path: str) -> str:
    low = _norm(path).casefold()
    for prefix in ENTITY_PREFIXES:
        if not low.startswith(prefix):
            continue
        rest = low[len(prefix):]
        folder = rest.split("/", 1)[0]
        return prefix + folder if folder else ""
    return ""




def _catalog_entity_bundles(project: pathlib.Path) -> tuple[set[str], str]:
    path = project / "data" / "reference" / "entity_catalog" / "monster_npc_entities_v1.json"
    data = _load_json(path)
    bundles: set[str] = set()
    for row in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
        if not isinstance(row, dict):
            continue
        root = _norm(row.get("folder_root") or "").casefold().rstrip("/")
        if root.startswith(ENTITY_PREFIXES):
            bundles.add(root)
    return bundles, str(path)


def _ui_tree_summary_path(project: pathlib.Path) -> str:
    return str(project / "data" / "ui_catalog" / "ui_tree_summary_v1.json")

def _integrity_action(retention_state: str, cook: dict[str, Any], *, root_reachable: bool = False) -> str:
    """Combine retention and cooker evidence without changing retention authority."""
    status = str(cook.get("status") or "").casefold()
    protected = retention_state.startswith("PROTECTED_")
    orphan = retention_state == "ORPHAN_CANDIDATE"
    graph_unreachable = retention_state == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
    documented = str(cook.get("documented_outlier") or "").casefold() in {"1", "true", "yes"}
    if status == "error":
        if orphan and documented:
            return "INVALID_UNREACHABLE_QUARANTINE_REVIEW"
        if orphan:
            return "DECODE_FAILURE_UNREACHABLE_REVIEW"
        if graph_unreachable and documented:
            return "INVALID_GRAPH_LINKED_ROOT_UNREACHABLE_QUARANTINE_REVIEW"
        if graph_unreachable:
            return "DECODE_FAILURE_GRAPH_LINKED_ROOT_UNREACHABLE_REVIEW"
        if protected and documented:
            return "INVALID_REFERENCED_NEEDS_RECOVERY_OR_RUNTIME_PROOF"
        if protected:
            return "DECODE_FAILURE_REFERENCED_REVIEW"
        return "DECODE_FAILURE_REVIEW"
    if status == "skipped":
        return "VALID_DECODE_POLICY_SKIPPED"
    if status in {"cooked", "up-to-date", "would-cook"}:
        if graph_unreachable and not root_reachable:
            return "GRAPH_LINKED_ROOT_UNREACHABLE_REVIEW"
        return "COOK_EVIDENCE_OK"
    if graph_unreachable and not root_reachable:
        return "GRAPH_LINKED_ROOT_UNREACHABLE_REVIEW"
    return "NO_COOK_EVIDENCE"



def _root_unreachable_components(
    edges: list[dict[str, Any]],
    reachable_nodes: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Weak client-client components for graph-linked nodes not reached by roots."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    internal_in: dict[str, set[str]] = defaultdict(set)
    internal_out: dict[str, set[str]] = defaultdict(set)
    all_in: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    client_nodes: set[str] = set()
    for edge in edges:
        src = str(edge.get("src") or "").casefold()
        dst = str(edge.get("dst") or "").casefold()
        if src.startswith("client:"):
            client_nodes.add(src); all_out[src].append(edge)
        if dst.startswith("client:"):
            client_nodes.add(dst); all_in[dst].append(edge)
        if src.startswith("client:") and dst.startswith("client:"):
            adjacency[src].add(dst); adjacency[dst].add(src)
            internal_out[src].add(dst); internal_in[dst].add(src)
    candidates = {n for n in client_nodes if n not in reachable_nodes and (all_in.get(n) or all_out.get(n))}
    seen: set[str] = set()
    raw_components: list[list[str]] = []
    for start in sorted(candidates):
        if start in seen:
            continue
        q = deque([start]); seen.add(start); comp: list[str] = []
        while q:
            cur = q.popleft(); comp.append(cur)
            for nxt in sorted(adjacency.get(cur, set())):
                if nxt in candidates and nxt not in seen:
                    seen.add(nxt); q.append(nxt)
        raw_components.append(sorted(comp))
    raw_components.sort(key=lambda c: (-len(c), c[0] if c else ""))
    node_meta: dict[str, dict[str, Any]] = {}
    components: list[dict[str, Any]] = []
    for idx, nodes in enumerate(raw_components, 1):
        node_set = set(nodes)
        cid = f"URC-{idx:05d}"
        entries = sorted(n for n in nodes if not (internal_in.get(n, set()) & node_set))
        if not entries and nodes:
            entries = [nodes[0]]
        external_in = 0; external_out = 0
        for n in nodes:
            external_in += sum(1 for e in all_in.get(n, []) if str(e.get("src") or "").casefold() not in node_set)
            external_out += sum(1 for e in all_out.get(n, []) if str(e.get("dst") or "").casefold() not in node_set)
        paths = [_norm(n.split(":", 1)[1]) for n in nodes]
        entry_paths = [_norm(n.split(":", 1)[1]) for n in entries]
        row = {
            "component_id": cid,
            "state": "ROOT_UNREACHABLE_GRAPH_COMPONENT_REVIEW",
            "size": len(nodes),
            "entry_count": len(entries),
            "entry_nodes": entry_paths[:EDGE_SAMPLE_LIMIT],
            "external_incoming_edge_count": external_in,
            "external_outgoing_edge_count": external_out,
            "path_sample": paths[:20],
            "root_reachable": False,
            "deletion_authorized": False,
        }
        components.append(row)
        for n in nodes:
            node_meta[n] = row
    return node_meta, components

def audit_asset_retention(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    strong_paths: dict[str, Iterable[str]],
    review_paths: dict[str, Iterable[str]],
    manifest_exact: dict[str, Iterable[str]],
    source_literal_paths: Iterable[str],
    cooked_by_source: dict[str, dict[str, Any]] | None = None,
    graph_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Classify physical client files for retention without authorizing deletion.

    Policy is intentionally conservative. Strong roots protect their outbound
    transitive closure. A graph edge by itself is *not* runtime-root proof: generic
    files that are graph-linked but unreachable from a strong root are REVIEW, not
    PROTECTED. Monster/NPC folders keep the stricter historical rule: a linked
    bundle remains protected even when its graph component is not runtime-root
    reachable, because those actor bundles are intentionally fail-closed.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    graph_file = pathlib.Path(graph_path).resolve() if graph_path else project / "pt_build" / "enrichment_vendor" / "dependency_graph" / "graph.json"
    graph = _load_json(graph_file)
    edges = [x for x in graph.get("edges", []) if isinstance(x, dict)]

    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        src, dst = str(edge.get("src") or ""), str(edge.get("dst") or "")
        if src: outgoing[src.casefold()].append(edge)
        if dst: incoming[dst.casefold()].append(edge)

    strong = {str(k).casefold(): sorted(set(map(str, v))) for k, v in strong_paths.items()}
    review = {str(k).casefold(): sorted(set(map(str, v))) for k, v in review_paths.items()}
    manifests = {str(k).casefold(): sorted(set(map(str, v))) for k, v in manifest_exact.items()}
    source_literals = {str(x).casefold() for x in source_literal_paths}
    cooked = cooked_by_source or {}
    catalog_entity_bundles, entity_catalog_path = _catalog_entity_bundles(project)
    ui_tree_summary = _ui_tree_summary_path(project)

    # Reachability follows dependency direction only from strong physical client
    # roots produced by the General Census. Source literals, manifests and catalog
    # membership remain positive retention evidence, but they do not silently
    # become runtime roots because dead/optional source and historical package
    # manifests can retain stale paths.
    roots = [f"client:{k}".casefold() for k in strong]
    reachable_nodes: set[str] = set()
    root_distance: dict[str, int] = {}
    root_sources: dict[str, set[str]] = defaultdict(set)
    q = deque()
    for root in roots:
        root_distance[root] = 0
        root_path = _norm(root.split(":", 1)[1]).casefold() if root.startswith("client:") else root
        root_sources[root].add(root_path)
        q.append(root)
    while q:
        node = q.popleft().casefold()
        if node in reachable_nodes:
            continue
        reachable_nodes.add(node)
        for edge in outgoing.get(node, []):
            dst = str(edge.get("dst") or "").casefold()
            if not dst:
                continue
            candidate_distance = root_distance.get(node, 0) + 1
            previous_distance = root_distance.get(dst)
            if previous_distance is None or candidate_distance < previous_distance:
                root_distance[dst] = candidate_distance
                root_sources[dst] = set(list(sorted(root_sources.get(node, set())))[:ROOT_SOURCE_SAMPLE_LIMIT])
            elif candidate_distance == previous_distance:
                merged = set(root_sources.get(dst, set())) | set(root_sources.get(node, set()))
                root_sources[dst] = set(list(sorted(merged))[:ROOT_SOURCE_SAMPLE_LIMIT])
            if dst not in reachable_nodes:
                q.append(dst)

    graph_linked_paths: set[str] = set()
    transitive_paths: set[str] = set()
    for node in set(incoming) | set(outgoing):
        if node.startswith("client:"):
            graph_linked_paths.add(_norm(node.split(":", 1)[1]).casefold())
    for node in reachable_nodes:
        if node.startswith("client:"):
            transitive_paths.add(_norm(node.split(":", 1)[1]).casefold())

    component_by_node, root_unreachable_components = _root_unreachable_components(edges, reachable_nodes)

    root_reachable_entity_bundles = {
        b for p in (transitive_paths | set(strong))
        for b in [_entity_bundle_key(p)] if b
    }
    linked_entity_bundles = {
        b for p in graph_linked_paths
        for b in [_entity_bundle_key(p)] if b
    }

    rows: list[dict[str, Any]] = []
    for rel in _walk(client):
        path = _norm(rel); key = path.casefold()
        ext = pathlib.PurePosixPath(path).suffix.casefold()
        category, role = infer_semantics(path, ext)
        visibility = infer_visibility_tier(path, ext, category, role)
        physical_family = infer_physical_family(path, ext)
        node = f"client:{path}".casefold()
        in_edge_rows = incoming.get(node, [])
        out_edge_rows = outgoing.get(node, [])
        in_edges = len(in_edge_rows)
        out_edges = len(out_edge_rows)
        bundle = _entity_bundle_key(path)
        cook = cooked.get(key) or {}
        is_root = key in strong
        is_root_reachable = node in reachable_nodes
        distance = root_distance.get(node)
        nearest_roots = sorted(root_sources.get(node, set()))[:ROOT_SOURCE_SAMPLE_LIMIT]
        nearest_root_evidence: list[str] = []
        for root_key in nearest_roots:
            for item in strong.get(root_key, []):
                nearest_root_evidence.append(f"{root_key}:{item}")

        evidence: list[str] = []
        if key in strong: evidence.extend(f"STRONG:{x}" for x in strong[key])
        if key in transitive_paths: evidence.append("TRANSITIVE_DEPENDENCY_CLOSURE")
        if key in graph_linked_paths: evidence.append("CONTRACT_GRAPH_EDGE")
        if bundle and bundle in root_reachable_entity_bundles: evidence.append(f"ENTITY_BUNDLE_ROOT_REACHABLE:{bundle}")
        if bundle and bundle in linked_entity_bundles: evidence.append(f"ENTITY_BUNDLE_GRAPH_LINKED:{bundle}")
        if bundle and bundle in catalog_entity_bundles: evidence.append(f"ENTITY_CATALOG:{bundle}")
        if key in manifests: evidence.extend(f"MANIFEST:{x}" for x in manifests[key])
        if key in source_literals: evidence.append("CURRENT_SOURCE_LITERAL")
        if key in review: evidence.extend(f"REVIEW:{x}" for x in review[key])

        if any(key.startswith(prefix) for prefix in GENERATED_PREFIXES):
            state = "GENERATED_OUTPUT"
            reason = "COOKED_OR_GENERATED_TREE"
        elif visibility in {"NOISE", "OPERATIONAL", "INSTALLER_SYSTEM", "USER_DATA"}:
            state = "OUT_OF_SCOPE_NON_ASSET"
            reason = f"CATALOG_VISIBILITY_{visibility}"
        elif key in strong:
            state = "PROTECTED_REACHABLE_ROOT"
            reason = "STRONG_RUNTIME_REACHABILITY"
        elif key in transitive_paths:
            state = "PROTECTED_ROOT_REACHABLE"
            reason = "REACHABLE_FROM_STRONG_ROOT"
        elif bundle and bundle in root_reachable_entity_bundles:
            state = "PROTECTED_ENTITY_BUNDLE_ROOT_REACHABLE"
            reason = "MONSTER_OR_NPC_BUNDLE_HAS_ROOT_REACHABLE_MEMBER"
        elif bundle and bundle in linked_entity_bundles:
            state = "PROTECTED_ENTITY_BUNDLE_LINKED"
            reason = "MONSTER_OR_NPC_BUNDLE_HAS_GRAPH_LINKED_MEMBER_FAIL_CLOSED"
        elif bundle and bundle in catalog_entity_bundles:
            state = "PROTECTED_ENTITY_CATALOG"
            reason = "MONSTER_OR_NPC_BUNDLE_PRESENT_IN_CANONICAL_ENTITY_CATALOG"
        elif key in manifests:
            state = "PROTECTED_MANIFEST_EVIDENCE"
            reason = "CLIENT_MANIFEST_POSITIVE_EVIDENCE"
        elif key in source_literals:
            state = "PROTECTED_SOURCE_EVIDENCE"
            reason = "CURRENT_SOURCE_LITERAL"
        elif key in graph_linked_paths:
            state = "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
            reason = "CONTRACT_EDGE_EXISTS_BUT_NO_STRONG_ROOT_REACHES_COMPONENT"
        elif key in review:
            state = "REVIEW_EVIDENCE"
            reason = "NON_STRONG_SEMANTIC_EVIDENCE"
        elif visibility == "RUNTIME_SUPPORT":
            state = "REVIEW_UNCLASSIFIED_SUPPORT"
            reason = "RUNTIME_SUPPORT_WITH_ZERO_KNOWN_LINKAGE"
        else:
            state = "ORPHAN_CANDIDATE"
            reason = "ZERO_KNOWN_LINKAGE_OR_ROOT_EVIDENCE"

        component = component_by_node.get(node) or {}
        rows.append({
            "path": path,
            "state": state,
            "reason": reason,
            "extension": ext,
            "category": category,
            "role": role,
            "visibility_tier": visibility,
            "physical_family": physical_family,
            "incoming_edge_count": in_edges,
            "outgoing_edge_count": out_edges,
            "graph_linked": bool(in_edges or out_edges),
            "root_reachable": is_root_reachable,
            "root_distance": "" if distance is None else distance,
            "root_source_count": len(root_sources.get(node, set())),
            "root_sources": " | ".join(nearest_roots),
            "root_source_evidence": " | ".join(sorted(set(nearest_root_evidence))[:ROOT_SOURCE_SAMPLE_LIMIT]),
            "component_id": component.get("component_id") or "",
            "component_size": component.get("size") or "",
            "component_entry_count": component.get("entry_count") or "",
            "component_entry_nodes": " | ".join(component.get("entry_nodes") or []),
            "component_external_incoming_edge_count": component.get("external_incoming_edge_count") if component else "",
            "component_external_outgoing_edge_count": component.get("external_outgoing_edge_count") if component else "",
            "incoming_edge_sources": " | ".join(
                _display_graph_node(str(x.get("src") or "")) for x in in_edge_rows[:EDGE_SAMPLE_LIMIT]
            ),
            "outgoing_edge_targets": " | ".join(
                _display_graph_node(str(x.get("dst") or "")) for x in out_edge_rows[:EDGE_SAMPLE_LIMIT]
            ),
            "incoming_edge_details": " | ".join(_edge_detail(x) for x in in_edge_rows[:EDGE_SAMPLE_LIMIT]),
            "outgoing_edge_details": " | ".join(_edge_detail(x) for x in out_edge_rows[:EDGE_SAMPLE_LIMIT]),
            "entity_bundle": bundle,
            "evidence": " | ".join(sorted(set(evidence))),
            "cook_status": cook.get("status") or "",
            "cook_failure_class": cook.get("failure_class") or "",
            "cook_failure_stage": cook.get("failure_stage") or "",
            "cook_error": cook.get("error_message") or "",
            "cook_skip_class": cook.get("skip_class") or "",
            "cook_skip_reason": cook.get("skip_reason") or "",
            "cook_decode_mode": cook.get("legacy_decode_mode") or "",
            "cook_integrity_state": cook.get("asset_integrity_state") or "",
            "cook_documented_outlier": cook.get("documented_outlier") or "",
            "cook_asset_classification": cook.get("asset_classification") or "",
            "cook_policy": cook.get("cook_policy") or "",
            "cook_runtime_note": cook.get("runtime_note") or "",
            "integrity_action": _integrity_action(state, cook, root_reachable=is_root_reachable),
            "deletion_authorized": False,
        })

    rows.sort(key=lambda x: (x["state"], x["path"].casefold()))
    states = Counter(str(x["state"]) for x in rows)
    orphan_rows = [x for x in rows if x["state"] == "ORPHAN_CANDIDATE"]
    orphan_families = Counter(str(x.get("physical_family") or "UNKNOWN") for x in orphan_rows)
    orphan_exts = Counter(str(x.get("extension") or "<none>") for x in orphan_rows)
    integrity_actions = Counter(str(x.get("integrity_action") or "NO_COOK_EVIDENCE") for x in rows)
    root_reachable_rows = [x for x in rows if bool(x.get("root_reachable"))]
    graph_linked_unreachable_rows = [
        x for x in rows if bool(x.get("graph_linked")) and not bool(x.get("root_reachable"))
        and x.get("state") == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
    ]

    out_dir = project / "pt_build" / "asset_retention"
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv = out_dir / "assets.tsv"
    cols = [
        "path", "state", "reason", "extension", "category", "role", "visibility_tier", "physical_family", "incoming_edge_count",
        "outgoing_edge_count", "graph_linked", "root_reachable", "root_distance", "root_source_count", "root_sources",
        "root_source_evidence", "component_id", "component_size", "component_entry_count", "component_entry_nodes",
        "component_external_incoming_edge_count", "component_external_outgoing_edge_count",
        "incoming_edge_sources", "outgoing_edge_targets", "incoming_edge_details",
        "outgoing_edge_details", "entity_bundle", "evidence", "cook_status", "cook_failure_class",
        "cook_failure_stage", "cook_error", "cook_skip_class", "cook_skip_reason", "cook_decode_mode",
        "cook_integrity_state", "cook_documented_outlier", "cook_asset_classification", "cook_policy",
        "cook_runtime_note", "integrity_action", "deletion_authorized",
    ]
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    components_tsv = out_dir / "components.tsv"
    component_cols = [
        "component_id", "state", "size", "entry_count", "entry_nodes",
        "external_incoming_edge_count", "external_outgoing_edge_count", "root_reachable", "deletion_authorized",
    ]
    with components_tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=component_cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in root_unreachable_components:
            out = dict(row); out["entry_nodes"] = " | ".join(row.get("entry_nodes") or [])
            w.writerow(out)
    components_json = out_dir / "components.json"
    components_json.write_text(json.dumps({
        "format": "PT_ASSET_RETENTION_COMPONENTS_V1",
        "status": "PASS",
        "component_count": len(root_unreachable_components),
        "asset_count": sum(int(x.get("size") or 0) for x in root_unreachable_components),
        "policy": {
            "weak_client_client_components_only": True,
            "root_unreachable_only": True,
            "component_membership_is_review_not_delete_authority": True,
            "deletion_authorized": False,
        },
        "components": root_unreachable_components,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "format": FORMAT,
        "status": "PASS",
        "state": "REVIEW_REQUIRED" if orphan_rows else "NO_ORPHAN_CANDIDATES",
        "client_root": str(client),
        "dependency_graph": str(graph_file),
        "dependency_graph_present": graph_file.is_file(),
        "asset_count": len(rows),
        "state_counts": dict(sorted(states.items())),
        "orphan_candidate_count": len(orphan_rows),
        "orphan_candidate_family_counts": dict(sorted(orphan_families.items())),
        "orphan_candidate_extension_counts": dict(sorted(orphan_exts.items())),
        "integrity_action_counts": dict(sorted(integrity_actions.items())),
        "strong_root_count": len(strong),
        "transitive_client_path_count": len(transitive_paths),
        "root_reachable_client_path_count": len(root_reachable_rows),
        "graph_linked_client_path_count": len(graph_linked_paths),
        "graph_linked_root_unreachable_review_count": len(graph_linked_unreachable_rows),
        "root_unreachable_component_count": len(root_unreachable_components),
        "root_unreachable_component_asset_count": sum(int(x.get("size") or 0) for x in root_unreachable_components),
        "root_reachable_entity_bundle_count": len(root_reachable_entity_bundles),
        "linked_entity_bundle_count": len(linked_entity_bundles),
        "catalog_entity_bundle_count": len(catalog_entity_bundles),
        "entity_catalog": entity_catalog_path,
        "ui_tree_summary": ui_tree_summary,
        "manifest_protected_path_count": len(manifests),
        "source_literal_path_count": len(source_literals),
        "assets_tsv": str(tsv),
        "components_tsv": str(components_tsv),
        "components_report": str(components_json),
        "policy": {
            "delete_authorized": False,
            "quarantine_before_delete_required": True,
            "zero_source_grep_is_not_orphan_proof": True,
            "any_contract_graph_edge_protects_asset": False,
            "contract_graph_edge_alone_is_review_not_runtime_protection": True,
            "runtime_root_reachability_uses_strong_paths_only": True,
            "source_literals_are_not_implicitly_runtime_roots": True,
            "manifest_entries_are_not_implicitly_runtime_roots": True,
            "strong_roots_protect_transitive_dependencies": True,
            "monster_npc_bundle_guard_enabled": True,
            "monster_npc_graph_linked_bundle_remains_fail_closed": True,
            "monster_npc_catalog_membership_protects_bundle": True,
            "monster_npc_asset_removal_requires_zero_linkage": True,
            "manifest_presence_is_positive_evidence": True,
            "manifest_absence_is_not_negative_evidence": True,
            "cooked_failure_never_authorizes_source_removal": True,
            "non_asset_operational_system_user_data_are_out_of_scope": True,
            "unclassified_runtime_support_is_review_not_orphan": True,
            "cooker_integrity_evidence_does_not_override_reachability": True,
            "invalid_referenced_asset_requires_recovery_or_runtime_proof": True,
            "invalid_unreachable_asset_is_quarantine_review_not_delete": True,
            "graph_linked_root_unreachable_asset_is_review_not_delete": True,
        },
        "orphan_candidates": orphan_rows[:500],
    }
    report = out_dir / "result.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

def query_asset_retention(
    project_root: str | pathlib.Path,
    *,
    path: str = "",
    query: str = "",
    state: str = "",
    family: str = "",
    component: str = "",
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    """Read/filter the persisted retention audit for CLI/UI exploration.

    This is read-only. Querying an ORPHAN_CANDIDATE never upgrades it into an
    authorized delete decision; callers must preserve the report policy.
    """
    project = pathlib.Path(project_root).resolve()
    out_dir = project / "pt_build" / "asset_retention"
    report_path = out_dir / "result.json"
    rows_path = out_dir / "assets.tsv"
    if not report_path.is_file() or not rows_path.is_file():
        return {
            "status": "NOT_RUN", "rows": [], "total_rows": 0, "filtered_rows": 0,
            "deletion_authorized": False,
        }
    summary = _load_json(report_path)
    with rows_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    exact_path = _norm(path).casefold()
    q = str(query or "").casefold().strip()
    state_u = str(state or "").upper().strip()
    family_u = str(family or "").upper().strip()
    component_u = str(component or "").upper().strip()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if exact_path and _norm(row.get("path") or "").casefold() != exact_path:
            continue
        if state_u and str(row.get("state") or "").upper() != state_u:
            continue
        if family_u and str(row.get("physical_family") or "").upper() != family_u:
            continue
        if component_u and str(row.get("component_id") or "").upper() != component_u:
            continue
        if q:
            hay = " ".join(str(row.get(k) or "") for k in (
                "path", "state", "reason", "category", "role", "physical_family",
                "entity_bundle", "evidence", "cook_status", "cook_failure_class",
                "cook_failure_stage", "cook_error", "cook_skip_class", "cook_skip_reason",
                "cook_decode_mode", "cook_integrity_state", "cook_asset_classification",
                "cook_policy", "cook_runtime_note", "integrity_action", "root_sources",
                "root_source_evidence", "component_id", "component_size", "component_entry_nodes",
                "incoming_edge_sources", "outgoing_edge_targets",
                "incoming_edge_details", "outgoing_edge_details",
            )).casefold()
            if q not in hay:
                continue
        filtered.append(row)

    offset = max(0, int(offset))
    limit = max(1, min(1000, int(limit)))
    state_counts = Counter(str(x.get("state") or "UNKNOWN") for x in rows)
    family_counts = Counter(str(x.get("physical_family") or "UNKNOWN") for x in rows)
    return {
        "status": summary.get("status", "PASS"),
        "retention_state": summary.get("state"),
        "summary": {
            "asset_count": summary.get("asset_count", len(rows)),
            "orphan_candidate_count": summary.get("orphan_candidate_count", 0),
            "catalog_entity_bundle_count": summary.get("catalog_entity_bundle_count", 0),
            "linked_entity_bundle_count": summary.get("linked_entity_bundle_count", 0),
            "root_reachable_client_path_count": summary.get("root_reachable_client_path_count", 0),
            "graph_linked_root_unreachable_review_count": summary.get("graph_linked_root_unreachable_review_count", 0),
            "root_unreachable_component_count": summary.get("root_unreachable_component_count", 0),
            "dependency_graph_present": summary.get("dependency_graph_present", False),
            "state_counts": dict(sorted(state_counts.items())),
            "physical_family_counts": dict(sorted(family_counts.items())),
            "policy": summary.get("policy") or {},
        },
        "total_rows": len(rows),
        "filtered_rows": len(filtered),
        "offset": offset,
        "limit": limit,
        "rows": filtered[offset:offset + limit],
        "deletion_authorized": False,
    }

