from __future__ import annotations

import collections
import json
import os
import pathlib
import re
from typing import Any, Callable

from .asset_contract_registry import source_registry
from .asset_compiler import _source_token
from .general_asset_census import _server_definition_names, _spm_actor_names
from .legacy_management_contracts import (
    classify_item_code,
    legacy_management_summary,
    verify_management_root,
)
from .item_runtime_catalog import lookup_item_runtime
from .server_bundle_census import _ci_resolve, _resolve_server_reference
from .server_item_census import _ITEM_CODE_RE, _decode, _zhoon_refs, audit_server_item_bundles

FORMAT = "PT_ASSET_LEGACY_MANAGEMENT_AUDIT_V1"


def _scan_definition_files(root: pathlib.Path | None, suffixes: set[str]) -> list[pathlib.Path]:
    if root is None:
        return []
    out: list[pathlib.Path] = []
    for walk_base, dirs, names in os.walk(root):
        dirs.sort(key=str.casefold)
        names.sort(key=str.casefold)
        for name in names:
            p = pathlib.Path(walk_base) / name
            if p.suffix.casefold() in suffixes:
                out.append(p)
    return out


def _item_tokens(text: str, known_catalog: set[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for m in _ITEM_CODE_RE.finditer(text):
        code = m.group(0).upper()
        if code in seen:
            continue
        seen.add(code)
        legacy = classify_item_code(code)
        source_known = code.casefold() in known_catalog
        # Fail closed: a regex-shaped token is not called an item unless either
        # the source catalogue or the historical PriTaTor taxonomy recognizes it.
        if not source_known and legacy.get("status") == "UNCLASSIFIED":
            continue
        rows.append({
            "code": code,
            "source_catalog_known": source_known,
            "legacy": legacy,
            "evidence": "SOURCE_CATALOG" if source_known else "LEGACY_PREFIX_ONLY",
        })
    return rows


def _monster_drop_tokens(text: str, known_catalog: set[str]) -> dict[str, Any]:
    """Return item codes found specifically in Monster drop directives.

    `_item_tokens()` intentionally scans the whole definition as broad closure
    evidence.  That count must not be presented to the user as "drop count".
    Here we narrow the scan to the source-backed FallItem/ExtraFallItem tokens
    so the UI can explain drops without conflating unrelated item references.
    """
    fall_item = _source_token("character_tokens", "FallItem")
    extra_fall_item = _source_token("character_tokens", "ExtraFallItem")
    directive_names = {fall_item: "FallItem", extra_fall_item: "ExtraFallItem"}
    rows: list[dict[str, Any]] = []
    directive_count = 0
    non_item_directive_count = 0
    seen: set[tuple[str, str]] = set()
    for original in text.splitlines():
        line = original.strip()
        if not line:
            continue
        head, _, tail = line.partition(" ")
        directive = directive_names.get(head)
        if directive is None:
            continue
        directive_count += 1
        refs = _item_tokens(tail, known_catalog)
        if not refs:
            non_item_directive_count += 1
        for ref in refs:
            key = (directive, str(ref.get("code") or "").upper())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"directive": directive, **ref})
    return {
        "directive_count": directive_count,
        "item_reference_count": len(rows),
        "non_item_directive_count": non_item_directive_count,
        "item_references": rows,
    }


def _tutorial_scan(tutorial_root: pathlib.Path | None, known_catalog: set[str]) -> dict[str, Any] | None:
    if tutorial_root is None:
        return None
    tutorial_root = pathlib.Path(tutorial_root).expanduser().resolve()
    if not tutorial_root.is_dir():
        return {"root": str(tutorial_root), "status": "NOT_FOUND", "files": []}
    files: list[dict[str, Any]] = []
    all_codes: set[str] = set()
    for p in sorted(tutorial_root.rglob("*"), key=lambda x: x.as_posix().casefold()):
        if not p.is_file() or p.suffix.casefold() != ".txt":
            continue
        raw = p.read_bytes()
        text, enc = _decode(raw)
        codes = _item_tokens(text, known_catalog)
        if codes:
            for row in codes:
                all_codes.add(str(row["code"]))
            files.append({
                "file": p.relative_to(tutorial_root).as_posix(),
                "encoding": enc,
                "item_codes": [x["code"] for x in codes],
                "item_code_count": len(codes),
            })
    return {
        "root": str(tutorial_root),
        "status": "PASS",
        "files_with_item_codes": len(files),
        "unique_item_codes": len(all_codes),
        "codes": sorted(all_codes),
        "files": files,
    }



class _CasefoldClientResolver:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root).resolve()
        self._cache: dict[pathlib.Path, dict[str, list[pathlib.Path]]] = {}

    def _children(self, directory: pathlib.Path) -> dict[str, list[pathlib.Path]]:
        cached = self._cache.get(directory)
        if cached is not None:
            return cached
        out: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
        try:
            for child in directory.iterdir():
                out[child.name.casefold()].append(child)
        except OSError:
            pass
        result = dict(out)
        self._cache[directory] = result
        return result

    def resolve(self, logical: str) -> dict[str, Any]:
        logical = str(logical or "").replace("\\", "/").lstrip("/")
        cur = self.root
        for part in pathlib.PurePosixPath(logical).parts:
            exact = cur / part
            if exact.exists():
                cur = exact
                continue
            candidates = self._children(cur).get(part.casefold(), [])
            if len(candidates) == 1:
                cur = candidates[0]
                continue
            if len(candidates) > 1:
                return {"logical": logical, "status": "AMBIGUOUS_CASE", "path": None, "candidates": [str(x) for x in candidates]}
            return {"logical": logical, "status": "MISSING", "path": None}
        return {"logical": logical, "status": "PRESENT", "path": str(cur), "is_file": cur.is_file()}


def _client_item_visual_closure(client_root: pathlib.Path | None, item_rows: list[dict[str, Any]], sample_limit: int) -> dict[str, Any] | None:
    if client_root is None:
        return None
    root = pathlib.Path(client_root).expanduser().resolve()
    if not root.is_dir():
        return {"root": str(root), "status": "NOT_FOUND"}
    resolver = _CasefoldClientResolver(root)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    counts: collections.Counter[str] = collections.Counter()
    for item in item_rows:
        code = str(item.get("code") or "").strip()
        if not code or code.casefold() in seen:
            continue
        seen.add(code.casefold())
        runtime = item.get("runtime_item_contract") or lookup_item_runtime(code)
        matches = runtime.get("matches") or []
        if not matches:
            counts["runtime_catalog_missing"] += 1
            rows.append({"code": code, "status": "RUNTIME_CATALOG_MISSING", "runtime": runtime})
            continue
        counts["runtime_catalog_present"] += 1
        closures: list[dict[str, Any]] = []
        for match in matches:
            expected = match.get("expected_client_paths") or {}
            icon = resolver.resolve(expected.get("inventory_icon")) if expected.get("inventory_icon") else None
            drop = resolver.resolve(expected.get("drop_model_ase")) if expected.get("drop_model_ase") else None
            for label, evidence in (("inventory_icon", icon), ("drop_model_ase", drop)):
                if evidence:
                    counts[f"{label}_{str(evidence.get('status')).lower()}"] += 1
            closures.append({
                "numeric_code_hex": match.get("numeric_code_hex"),
                "dorp_item": match.get("dorp_item"),
                "item_file_path": match.get("item_file_path"),
                "inventory_icon": icon,
                "drop_model_ase": drop,
            })
        status = "CLOSED" if closures and all(
            x.get(k, {}).get("status") == "PRESENT"
            for x in closures for k in ("inventory_icon", "drop_model_ase")
        ) else "REVIEW"
        counts[f"item_{status.lower()}"] += 1
        rows.append({"code": code, "status": status, "closures": closures})
    review = [x for x in rows if x.get("status") != "CLOSED"]
    return {
        "root": str(root),
        "status": "PASS",
        "item_code_count": len(rows),
        "closed_count": sum(1 for x in rows if x.get("status") == "CLOSED"),
        "review_count": len(review),
        "counts": dict(sorted(counts.items())),
        "review_sample": review[:sample_limit],
        "rows": rows,
        "source_basis": [
            "sITEM.ItemFilePath + sITEM.DorpItem inventory icon path",
            "sITEM.DorpItem DropItem ASE path",
        ],
        "write_authorized": False,
    }

def audit_legacy_management(
    project_root: pathlib.Path,
    *,
    server_root: pathlib.Path | None = None,
    client_root: pathlib.Path | None = None,
    management_root: pathlib.Path | None = None,
    tutorial_root: pathlib.Path | None = None,
    sample_limit: int = 80,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Cross-check legacy Management tooling against the current asset model.

    The legacy EXEs are never executed.  Evidence is static: known hashes,
    PriTaTor config, source-derived current contracts and live server files.
    Any inferred NPC shop/drop relation remains explicitly a candidate until its
    exact grammar is proven by source or roundtrip corpus evidence.
    """
    project_root = pathlib.Path(project_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    client = pathlib.Path(client_root).resolve() if client_root is not None else None
    report_dir = project_root / "pt_build" / "devtest" / "legacy_management"
    report_path = report_dir / "result.json"

    summary = legacy_management_summary()
    management = verify_management_root(pathlib.Path(management_root)) if management_root else None

    catalog = source_registry("item_catalog")
    known_catalog = {
        str(x.get("code") or "").casefold()
        for x in catalog.get("entries") or []
        if str(x.get("code") or "").strip()
    }
    tutorials = _tutorial_scan(pathlib.Path(tutorial_root) if tutorial_root else None, known_catalog)

    if server is None:
        result = {
            "format": FORMAT,
            "status": "PASS",
            "audit_completed": True,
            "server_root": None,
            "client_root": str(client) if client is not None else None,
            "management_verification": management,
            "tutorial_evidence": tutorials,
            "legacy_contract": summary,
            "server_evidence": None,
            "scope": {
                "mode": "CONTRACT_ONLY",
                "legacy_executables_executed": False,
                "production_writer_promoted": False,
            },
            "report": str(report_path),
        }
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    if progress:
        progress("OpenItem census")
    items = audit_server_item_bundles(project_root, server, sample_limit=sample_limit, progress_every=0)
    openitem_by_code: dict[str, list[str]] = collections.defaultdict(list)
    for row in items.get("rows") or []:
        code = str(row.get("code") or "").strip().upper()
        if code:
            openitem_by_code[code.casefold()].append(str(row.get("definition") or ""))

    monster_root = _ci_resolve(server, "GameServer/Monster", want_dir=True)
    npc_root = _ci_resolve(server, "GameServer/NPC", want_dir=True)
    monster_files = _scan_definition_files(monster_root, {".inf"})
    npc_files = _scan_definition_files(npc_root, {".npc", ".inf"})

    definition_rows: list[dict[str, Any]] = []
    definition_by_rel: dict[str, dict[str, Any]] = {}
    reason_counts: collections.Counter[str] = collections.Counter()
    ref_counts: collections.Counter[str] = collections.Counter()

    for kind, files in (("MONSTER", monster_files), ("NPC", npc_files)):
        for idx, p in enumerate(files, start=1):
            if progress and idx % 250 == 0:
                progress(f"{kind} definitions {idx}/{len(files)}")
            rel = p.relative_to(server).as_posix()
            try:
                text, enc = _decode(p.read_bytes())
                error = None
            except Exception as exc:
                text = ""
                enc = None
                error = f"{type(exc).__name__}:{exc}"
            refs = _item_tokens(text, known_catalog) if not error else []
            zrefs = _zhoon_refs(text) if not error else []
            drop_info = _monster_drop_tokens(text, known_catalog) if kind == "MONSTER" and not error else {
                "directive_count": 0, "item_reference_count": 0, "non_item_directive_count": 0, "item_references": []
            }
            for ref in refs:
                defs = openitem_by_code.get(str(ref["code"]).casefold(), [])
                ref["openitem_definitions"] = defs
                ref["openitem_definition_present"] = bool(defs)
                ref_counts["item_refs"] += 1
                if not defs:
                    reason_counts["ITEM_REFERENCE_WITHOUT_OPENITEM"] += 1
            reasons: list[str] = []
            if error:
                reasons.append("READ_OR_DECODE_ERROR")
            if kind == "MONSTER" and zrefs:
                # PriTaTor and tutorials explicitly treat monster .zhoon as a
                # companion.  Presence is checked without claiming semantics.
                for z in zrefs:
                    zp = _resolve_server_reference(server, p, z)
                    if zp is None:
                        reason_counts["MONSTER_ZHOON_REFERENCE_MISSING"] += 1
            row = {
                "kind": kind,
                "definition": rel,
                "encoding": enc,
                "item_references": refs,
                "item_reference_count": len(refs),
                "drop_directive_count": drop_info["directive_count"] if kind == "MONSTER" else None,
                "drop_item_reference_count": drop_info["item_reference_count"] if kind == "MONSTER" else None,
                "drop_non_item_directive_count": drop_info["non_item_directive_count"] if kind == "MONSTER" else None,
                "drop_item_references": drop_info["item_references"] if kind == "MONSTER" else [],
                "zhoon_references": zrefs,
                "reasons": reasons,
                "error": error,
            }
            definition_rows.append(row)
            definition_by_rel[rel.casefold()] = row

    # Reconstruct the PriTaTor map -> monster -> drop view using current SPM
    # parsing and current server definitions. This is read-only provenance.
    name_index = _server_definition_names(server)
    field_root = _ci_resolve(server, "GameServer/Field", want_dir=True)
    map_rows: list[dict[str, Any]] = []
    unresolved_actor_count = 0
    if field_root is not None:
        spm_files = _scan_definition_files(field_root, {".spm"})
        for idx, spm in enumerate(spm_files, start=1):
            if progress and idx % 100 == 0:
                progress(f"SPM maps {idx}/{len(spm_files)}")
            actors: list[dict[str, Any]] = []
            for actor_kind, actor_name in _spm_actor_names(spm):
                matches = [
                    rel for rel in name_index.get(actor_name.casefold(), [])
                    if rel.casefold().startswith("gameserver/monster/")
                ]
                drop_codes: set[str] = set()
                for rel in matches:
                    drow = definition_by_rel.get(rel.casefold())
                    for ref in (drow or {}).get("item_references") or []:
                        drop_codes.add(str(ref.get("code")))
                if not matches:
                    unresolved_actor_count += 1
                actors.append({
                    "kind": actor_kind,
                    "name": actor_name,
                    "monster_definitions": matches,
                    "item_codes": sorted(drop_codes),
                    "status": "RESOLVED" if len(matches) == 1 else ("AMBIGUOUS" if matches else "UNRESOLVED"),
                })
            map_rows.append({
                "spm": spm.relative_to(server).as_posix(),
                "actor_count": len(actors),
                "actors": actors,
                "item_codes": sorted({c for a in actors for c in a.get("item_codes") or []}),
            })

    monster_refs = [
        (row["definition"], ref)
        for row in definition_rows if row["kind"] == "MONSTER"
        for ref in row.get("item_references") or []
    ]
    npc_refs = [
        (row["definition"], ref)
        for row in definition_rows if row["kind"] == "NPC"
        for ref in row.get("item_references") or []
    ]
    missing_ref_rows = [
        {"definition": definition, **ref}
        for definition, ref in monster_refs + npc_refs
        if not ref.get("openitem_definition_present")
    ]
    legacy_only_rows = [
        {"definition": definition, **ref}
        for definition, ref in monster_refs + npc_refs
        if ref.get("evidence") == "LEGACY_PREFIX_ONLY"
    ]
    client_visual = _client_item_visual_closure(client, items.get("rows") or [], sample_limit)

    result = {
        "format": FORMAT,
        "status": "PASS",
        "audit_completed": True,
        "server_root": str(server),
        "client_root": str(client) if client is not None else None,
        "management_verification": management,
        "tutorial_evidence": tutorials,
        "legacy_contract": summary,
        "client_item_visual_evidence": client_visual,
        "server_evidence": {
            "openitem": {
                "definition_count": items.get("item_definition_count"),
                "unique_code_count": items.get("unique_code_count"),
                "review_count": items.get("review_count"),
            },
            "monster_definition_count": len(monster_files),
            "npc_definition_count": len(npc_files),
            "monster_item_reference_count": len(monster_refs),
            "npc_item_reference_candidate_count": len(npc_refs),
            "item_reference_without_openitem_count": len(missing_ref_rows),
            "legacy_prefix_only_reference_count": len(legacy_only_rows),
            "field_spm_count": len(map_rows),
            "unresolved_spm_actor_count": unresolved_actor_count,
            "reason_counts": dict(sorted(reason_counts.items())),
            "reference_counts": dict(sorted(ref_counts.items())),
            "missing_openitem_sample": missing_ref_rows[:sample_limit],
            "legacy_prefix_only_sample": legacy_only_rows[:sample_limit],
            "definitions": definition_rows,
            "maps": map_rows,
        },
        "scope": {
            "confirmed": [
                "PriTaTor historical item-prefix taxonomy",
                "PriTaTor paths for Monster/OpenItem/NPC/Field SPM",
                "monster drop/EXP/map workflow from static strings plus tutorial",
                "NPCManager SPC authoring workflow and fields",
                "map -> SPM actor -> Monster definition -> candidate item-code closure",
                "OpenItem presence for candidate drop/shop codes",
                "physical DorpItem icon/drop-model closure when client root is available",
            ],
            "candidate_only": [
                "item-shaped tokens in NPC definitions are shop references until exact NPC grammar is source/corpus-proven",
                "legacy-prefix-only item codes are not promoted to runtime catalog identity",
            ],
            "not_promoted": [
                "native ItemEditor internal format",
                "DataServer userdata/warehouse binary mutation",
                "ItemDistributor original binary queue format",
            ],
            "legacy_executables_executed": False,
            "server_write_authorized": False,
            "client_write_authorized": False,
        },
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
