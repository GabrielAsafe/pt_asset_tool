#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

AMANDA_CLASS = 1014
ENZO_CLASS = 1024
AMANDA_MODEL = r"char\npc\ji_woo\jiwoo.INI"
ENZO_MODEL = r"char\npc\Enzo\Enzo.ini"

AMANDA_PRIMARY = "npc.ji_woo"
AMANDA_ALIAS = "npc.amanda"
ENZO_ID = "npc.enzo_o_restaure"

AMANDA_PLACEMENT = {
    "slot": 20,
    "npc_id": AMANDA_PRIMARY,
    "x": -175442,
    "y": 52480,
    "z": -4438784,
    "ax": 0,
    "ay": 1000,
    "az": 0,
    "state": 0,
}
ENZO_PLACEMENT = {
    "slot": 21,
    "npc_id": ENZO_ID,
    "x": 268949,
    "y": 167424,
    "z": 19485184,
    "ax": 0,
    "ay": 1579,
    "az": 0,
    "state": 0,
}


def source_root(repo: Path) -> Path:
    repo = repo.resolve()
    if (repo / "SourceCode" / "Content" / "canonical").is_dir():
        return repo / "SourceCode"
    if (repo / "Content" / "canonical").is_dir():
        return repo
    raise SystemExit(f"cannot locate SourceCode/Content/canonical below {repo}")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_payload(doc: dict[str, Any], raw: bytes) -> None:
    doc.setdefault("compatibility", {})["encoding"] = "base64"
    doc["compatibility"]["legacy_payload_base64"] = base64.b64encode(raw).decode("ascii")
    source = doc.setdefault("source", {})
    source["legacy_size"] = len(raw)
    source["legacy_sha256"] = hashlib.sha256(raw).hexdigest()


def find_resource(resources: Path, canonical_id: str) -> Path:
    hits: list[Path] = []
    for path in resources.rglob("*.json"):
        if path.name.casefold() == "index.json":
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if doc.get("id") == canonical_id:
            hits.append(path)
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one {canonical_id}, found {len(hits)}: {hits}")
    return hits[0]


def find_directive(doc: dict[str, Any], key: str) -> dict[str, Any]:
    for directive in doc.get("semantic", {}).get("directives", []):
        if directive.get("key") == key:
            return directive
    raise SystemExit(f"{doc.get('id')}: missing directive {key}")


def patch_npc_definition(path: Path, *, class_id: int, model: str, apply: bool) -> list[str]:
    doc = load(path)
    changes: list[str] = []
    raw = base64.b64decode(doc["compatibility"]["legacy_payload_base64"], validate=True)

    fields = doc.setdefault("semantic", {}).setdefault("fields", {})

    class_directive = find_directive(doc, "class")
    old_class_raw = bytes.fromhex((class_directive.get("raw_values_hex") or [""])[0])
    wanted_class_raw = str(class_id).encode("ascii")
    if old_class_raw != wanted_class_raw:
        if old_class_raw and old_class_raw in raw:
            raw = raw.replace(old_class_raw, wanted_class_raw, 1)
        elif wanted_class_raw not in raw:
            raise SystemExit(f"{path}: could not locate class bytes {old_class_raw!r}")
        class_directive["values"] = [class_id]
        class_directive["raw_values_hex"] = [wanted_class_raw.hex()]
        changes.append(f"class -> {class_id}")
    if fields.get("class") != class_id:
        fields["class"] = class_id
        if f"class -> {class_id}" not in changes:
            changes.append(f"class semantic -> {class_id}")

    model_directive = find_directive(doc, "model_file")
    old_model_raw = bytes.fromhex((model_directive.get("raw_values_hex") or [""])[0])
    wanted_model_raw = model.encode("ascii")
    if old_model_raw != wanted_model_raw:
        if old_model_raw and old_model_raw in raw:
            raw = raw.replace(old_model_raw, wanted_model_raw, 1)
        elif wanted_model_raw not in raw:
            raise SystemExit(f"{path}: could not locate model bytes {old_model_raw!r}")
        model_directive["values"] = [model]
        model_directive["raw_values_hex"] = [wanted_model_raw.hex()]
        changes.append(f"model -> {model}")
    if fields.get("model_file") != model:
        fields["model_file"] = model
        if f"model -> {model}" not in changes:
            changes.append(f"model semantic -> {model}")

    if changes:
        set_payload(doc, raw)
        if apply:
            write_json(path, doc)
    return changes


def instructor_entries(source_doc: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in source_doc.get("semantic", {}).get("entries", []):
        row = dict(entry)
        if row.get("kind") == "name" or str(row.get("legacy_key", "")).casefold() == "j_name":
            row["text"] = "Instrutora Amanda"
        result.append(row)
    if not result:
        raise SystemExit("text.jiwoo has no localization entries")
    return result


def render_localization_payload(old_doc: dict[str, Any], entries: list[dict[str, Any]]) -> bytes:
    old_raw = base64.b64decode(old_doc["compatibility"]["legacy_payload_base64"], validate=True)
    first = old_raw.splitlines()[0] if old_raw.splitlines() else b"//canonical"
    lines: list[bytes] = [first, b"", b""]
    for entry in entries:
        key = str(entry.get("legacy_key") or ("J_Name" if entry.get("kind") == "name" else "J_Chat"))
        text = str(entry.get("text", "")).replace('"', "'")
        lines.append(("*" + key + '\t"' + text + '"').encode("cp1252", errors="strict"))
        lines.append(b"")
    return b"\r\n".join(lines) + b"\r\n"


def patch_localization(path: Path, entries: list[dict[str, Any]], apply: bool) -> bool:
    doc = load(path)
    current = doc.get("semantic", {}).get("entries", [])
    normalized_current = [(x.get("legacy_key"), x.get("kind"), x.get("text")) for x in current]
    normalized_target = [(x.get("legacy_key"), x.get("kind"), x.get("text")) for x in entries]
    target_raw = render_localization_payload(doc, entries)
    old_raw = base64.b64decode(doc["compatibility"]["legacy_payload_base64"], validate=True)
    changed = normalized_current != normalized_target or old_raw != target_raw
    if not changed:
        return False
    doc.setdefault("semantic", {})["entries"] = entries
    set_payload(doc, target_raw)
    if apply:
        write_json(path, doc)
    return True


def patch_name_only(path: Path, name: str, apply: bool) -> bool:
    doc = load(path)
    entries = [dict(x) for x in doc.get("semantic", {}).get("entries", [])]
    found = False
    for row in entries:
        if row.get("kind") == "name" or str(row.get("legacy_key", "")).casefold() == "j_name":
            row["text"] = name
            found = True
            break
    if not found:
        raise SystemExit(f"{path}: missing J_Name")
    return patch_localization(path, entries, apply)


def _looks_like_fixed_npc_doc(doc: dict[str, Any]) -> bool:
    schema = str(doc.get("schema", "")).casefold()
    if "fixed" in schema and "npc" in schema and isinstance(doc.get("npcs"), list):
        return True

    # REC175+/canonical layouts may evolve the schema name while preserving
    # the semantic contract: a map-scoped document containing NPC placements.
    if not isinstance(doc.get("npcs"), list):
        return False
    identity_keys = (
        "map_id",
        "canonical_id",
        "id",
        "logical_path",
        "map",
        "map_name",
        "internal_name",
        "field_id",
    )
    return any(isinstance(doc.get(key), (str, int)) for key in identity_keys)


def _discover_fixed_npc_candidates(fixed_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    seen: set[Path] = set()

    # Primary contract: everything below Content/canonical/fixed_npcs,
    # recursively. The new canonical layout is allowed to use subdirectories.
    for path in sorted(fixed_root.rglob("*.json"), key=lambda p: str(p).casefold()):
        if path.name.casefold() == "index.json":
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if _looks_like_fixed_npc_doc(doc):
            out.append((path, doc))
            seen.add(path.resolve())

    if out:
        return out

    # Compatibility discovery: if the family was moved by a later content
    # migration, scan the canonical tree by shape. We still only accept
    # map-scoped documents containing an `npcs` placement list.
    canonical_root = fixed_root.parent
    for path in sorted(canonical_root.rglob("*.json"), key=lambda p: str(p).casefold()):
        if path.name.casefold() == "index.json" or path.resolve() in seen:
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if _looks_like_fixed_npc_doc(doc):
            out.append((path, doc))
            seen.add(path.resolve())

    return out


def field_docs(fixed_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    docs = _discover_fixed_npc_candidates(fixed_root)
    print(f"FIXED_NPC_DOCUMENTS={len(docs)}")
    for path, doc in docs:
        identity = (
            doc.get("map_id")
            or doc.get("canonical_id")
            or doc.get("id")
            or doc.get("logical_path")
            or doc.get("map_name")
            or doc.get("internal_name")
            or ""
        )
        print(
            f"FIXED_NPC_DOC file={path.relative_to(fixed_root.parent)} "
            f"identity={identity} npcs={len(doc.get('npcs', []))}"
        )
    return docs


def _all_string_values(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                out.append(k)
            out.extend(_all_string_values(v))
    elif isinstance(value, list):
        for item in value:
            out.extend(_all_string_values(item))
    return out


def _norm_token(value: str) -> str:
    return (
        value.replace("\\", "/")
        .replace("_", "-")
        .casefold()
        .strip()
    )


def _doc_tokens(path: Path, doc: dict[str, Any]) -> set[str]:
    tokens: set[str] = {_norm_token(path.name), _norm_token(path.stem)}
    for value in _all_string_values(doc):
        norm = _norm_token(value)
        if not norm:
            continue
        tokens.add(norm)
        tokens.add(_norm_token(Path(norm).name))
        tokens.add(_norm_token(Path(norm).stem))
    return tokens


def _placement_ids(doc: dict[str, Any]) -> set[str]:
    return {
        str(row.get("npc_id", ""))
        for row in doc.get("npcs", [])
        if isinstance(row, dict)
    }


def find_field(
    docs: list[tuple[Path, dict[str, Any]]],
    *,
    label: str,
    canonical_aliases: set[str],
    preferred_existing_npc: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Resolve a canonical fixed-NPC map without requiring the retired .SPC path.

    Priority:
      1. canonical/map metadata and filename aliases;
      2. the historical NPC already placed on that map;
      3. legacy logical_path/name aliases as part of the same token scan.

    Ambiguity is fatal: this tool must never guess a map when editing placements.
    """
    wanted = {_norm_token(x) for x in canonical_aliases}
    scored: list[tuple[int, Path, dict[str, Any], list[str]]] = []

    for path, doc in docs:
        tokens = _doc_tokens(path, doc)
        reasons: list[str] = []
        score = 0

        exact = sorted(wanted & tokens)
        if exact:
            score += 100
            reasons.append("metadata=" + ",".join(exact[:4]))

        # Also accept an alias embedded in a structured identifier/path token,
        # e.g. "map.village-2" or "field/ricarten/village-2".
        embedded = sorted({
            alias
            for alias in wanted
            if any(
                token.endswith("/" + alias)
                or token.endswith("." + alias)
                or ("/" + alias + ".") in token
                or ("." + alias + ".") in token
                for token in tokens
            )
        })
        if embedded:
            score += 60
            reasons.append("embedded=" + ",".join(embedded[:4]))

        if preferred_existing_npc and preferred_existing_npc in _placement_ids(doc):
            score += 40
            reasons.append("existing_npc=" + preferred_existing_npc)

        if score:
            scored.append((score, path, doc, reasons))

    if not scored:
        inventory = []
        for path, doc in docs:
            inventory.append({
                "file": str(path),
                "schema": doc.get("schema"),
                "id": doc.get("id"),
                "map_id": doc.get("map_id"),
                "canonical_id": doc.get("canonical_id"),
                "logical_path": doc.get("logical_path"),
                "map_name": doc.get("map_name"),
                "internal_name": doc.get("internal_name"),
                "npc_ids": sorted(_placement_ids(doc)),
            })
        raise SystemExit(
            f"cannot resolve canonical fixed-NPC map for {label}; "
            f"aliases={sorted(canonical_aliases)} preferred_npc={preferred_existing_npc}; "
            f"discovered_fixed_npc_documents={len(docs)}; "
            f"inventory={json.dumps(inventory, ensure_ascii=False)}"
        )

    scored.sort(key=lambda x: (-x[0], x[1].name.casefold()))
    best_score = scored[0][0]
    best = [row for row in scored if row[0] == best_score]
    if len(best) != 1:
        detail = [
            {
                "score": score,
                "file": path.name,
                "id": doc.get("id"),
                "map_id": doc.get("map_id"),
                "logical_path": doc.get("logical_path"),
                "reasons": reasons,
            }
            for score, path, doc, reasons in best
        ]
        raise SystemExit(
            f"ambiguous canonical fixed-NPC map for {label}: "
            f"{json.dumps(detail, ensure_ascii=False)}"
        )

    score, path, doc, reasons = best[0]
    print(
        f"RESOLVED_MAP={label} file={path.name} score={score} "
        f"reasons={';'.join(reasons)}"
    )
    return path, doc


def remove_alias_everywhere(docs: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    changes: list[str] = []
    for _, doc in docs:
        rows = list(doc.get("npcs", []))
        kept = [r for r in rows if str(r.get("npc_id", "")) != AMANDA_ALIAS]
        if len(kept) != len(rows):
            removed = len(rows) - len(kept)
            doc["npcs"] = kept
            changes.append(f"{doc.get('logical_path')}: removed {removed} placement(s) of {AMANDA_ALIAS}")
    return changes


def ensure_slot(doc: dict[str, Any], placement: dict[str, Any]) -> tuple[bool, str]:
    rows = list(doc.get("npcs", []))
    slot = int(placement["slot"])
    hits = [r for r in rows if int(r.get("slot", -1)) == slot]
    if len(hits) > 1:
        raise SystemExit(f"{doc.get('logical_path')}: duplicate slot {slot}")
    if hits:
        current = str(hits[0].get("npc_id", ""))
        if current not in {AMANDA_PRIMARY, AMANDA_ALIAS, ENZO_ID}:
            raise SystemExit(f"{doc.get('logical_path')}: refusing to overwrite unexpected slot {slot}: {current}")
    before = json.dumps(rows, sort_keys=True)
    rows = [r for r in rows if int(r.get("slot", -1)) != slot]
    rows.append(dict(placement))
    rows.sort(key=lambda r: int(r.get("slot", 0)))
    doc["npcs"] = rows
    return before != json.dumps(rows, sort_keys=True), f"slot {slot} -> {placement['npc_id']}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Separate Instrutora Amanda from Enzo restorer in canonical content")
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = ap.parse_args()

    src = source_root(args.repo_root)
    canonical = src / "Content" / "canonical"
    resources = canonical / "text" / "resources"
    fixed_root = canonical / "fixed_npcs"
    if not resources.is_dir() or not fixed_root.is_dir():
        raise SystemExit("canonical text/fixed_npcs roots are missing")

    paths = {
        AMANDA_PRIMARY: find_resource(resources, AMANDA_PRIMARY),
        AMANDA_ALIAS: find_resource(resources, AMANDA_ALIAS),
        ENZO_ID: find_resource(resources, ENZO_ID),
        "text.jiwoo": find_resource(resources, "text.jiwoo"),
        "text.amanda": find_resource(resources, "text.amanda"),
        "text.enzo_o_restaure": find_resource(resources, "text.enzo_o_restaure"),
    }

    changes: list[str] = []

    for cid in (AMANDA_PRIMARY, AMANDA_ALIAS):
        for change in patch_npc_definition(paths[cid], class_id=AMANDA_CLASS, model=AMANDA_MODEL, apply=args.apply):
            changes.append(f"{cid}: {change}")

    for change in patch_npc_definition(paths[ENZO_ID], class_id=ENZO_CLASS, model=ENZO_MODEL, apply=args.apply):
        changes.append(f"{ENZO_ID}: {change}")

    jiwoo_doc = load(paths["text.jiwoo"])
    instructor = instructor_entries(jiwoo_doc)
    if patch_localization(paths["text.jiwoo"], instructor, args.apply):
        changes.append("text.jiwoo -> Instrutora Amanda")
    if patch_localization(paths["text.amanda"], instructor, args.apply):
        changes.append("text.amanda -> Instrutora Amanda/instructor dialogue")
    if patch_name_only(paths["text.enzo_o_restaure"], "Enzo, o Restaurador de Itens", args.apply):
        changes.append("text.enzo_o_restaure -> Enzo, o Restaurador de Itens")

    docs = field_docs(fixed_root)
    changes.extend(remove_alias_everywhere(docs))

    ric_path, ric = find_field(
        docs,
        label="Ricarten/village-2",
        canonical_aliases={
            "map.village_2",
            "map.village-2",
            "village_2",
            "village-2",
            "village-2.ase",
            "village-2.ase.spc",
            "ricarten",
        },
        preferred_existing_npc=AMANDA_PRIMARY,
    )
    pil_path, pil = find_field(
        docs,
        label="Pillai/pilai",
        canonical_aliases={
            "map.pilai",
            "map.pillai",
            "pilai",
            "pillai",
            "pilai.ase",
            "pilai.ase.spc",
            "pillai.ase",
            "pillai.ase.spc",
        },
        preferred_existing_npc=ENZO_ID,
    )

    changed, note = ensure_slot(ric, AMANDA_PLACEMENT)
    if changed:
        changes.append(f"{ric.get('logical_path')}: {note}")
    changed, note = ensure_slot(pil, ENZO_PLACEMENT)
    if changed:
        changes.append(f"{pil.get('logical_path')}: {note}")

    if args.apply:
        for path, doc in docs:
            write_json(path, doc)

    print(f"MODE={'APPLY' if args.apply else 'DRY_RUN'}")
    for item in changes:
        print(f"CHANGE={item}")
    print("AMANDA_ID=npc.ji_woo")
    print("AMANDA_CLASS=1014")
    print(r"AMANDA_MODEL=char\npc\ji_woo\jiwoo.INI")
    print("AMANDA_LOCATION=Ricarten/village-2 slot=20 x=-175442 y=52480 z=-4438784 ay=1000")
    print("ENZO_ID=npc.enzo_o_restaure")
    print("ENZO_CLASS=1024")
    print(r"ENZO_MODEL=char\npc\Enzo\Enzo.ini")
    print("ENZO_LOCATION=Pillai/pilai slot=21 x=268949 y=167424 z=19485184 ay=1579")
    print(f"CHANGES={len(changes)}")
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
