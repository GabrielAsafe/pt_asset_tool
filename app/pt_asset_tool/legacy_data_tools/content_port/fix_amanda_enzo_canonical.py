#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

KNOWN_IDS = {"npc.ji_woo", "npc.amanda", "npc.enzo_o_restaure"}
AMANDA_PLACEMENT = {
    "slot": 20,
    "npc_id": "npc.ji_woo",
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
    "npc_id": "npc.enzo_o_restaure",
    "x": 268949,
    "y": 167424,
    "z": 19485184,
    "ax": 0,
    "ay": 1579,
    "az": 0,
    "state": 0,
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_payload(doc: dict[str, Any], raw: bytes) -> None:
    doc.setdefault("compatibility", {})["legacy_payload_base64"] = base64.b64encode(raw).decode("ascii")
    source = doc.setdefault("source", {})
    source["legacy_size"] = len(raw)
    source["legacy_sha256"] = hashlib.sha256(raw).hexdigest()


def find_resource(root: Path, canonical_id: str) -> Path:
    hits: list[Path] = []
    for path in root.rglob("*.json"):
        try:
            doc = load(path)
        except Exception:
            continue
        if doc.get("id") == canonical_id:
            hits.append(path)
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one {canonical_id}, found {len(hits)}: {hits}")
    return hits[0]


def patch_model(path: Path, new_model: str, apply: bool) -> bool:
    doc = load(path)
    current = str(doc.get("semantic", {}).get("fields", {}).get("model_file", ""))
    if current == new_model:
        return False
    raw = base64.b64decode(doc["compatibility"]["legacy_payload_base64"], validate=True)
    old_bytes = current.encode("ascii")
    new_bytes = new_model.encode("ascii")
    if old_bytes not in raw:
        raise SystemExit(f"{path}: current model bytes not found in compatibility payload: {current!r}")
    raw = raw.replace(old_bytes, new_bytes, 1)
    doc["semantic"]["fields"]["model_file"] = new_model
    found = False
    for directive in doc["semantic"].get("directives", []):
        if directive.get("key") == "model_file":
            directive["values"] = [new_model]
            directive["raw_values_hex"] = [new_bytes.hex()]
            found = True
            break
    if not found:
        raise SystemExit(f"{path}: model_file directive not found")
    save_payload(doc, raw)
    if apply:
        write_json(path, doc)
    return True


def patch_name(path: Path, new_name: str, apply: bool) -> bool:
    doc = load(path)
    entries = doc.get("semantic", {}).get("entries", [])
    entry = next((x for x in entries if x.get("kind") == "name" or str(x.get("legacy_key", "")).casefold() == "j_name"), None)
    if not entry:
        raise SystemExit(f"{path}: name entry not found")
    current = str(entry.get("text", ""))
    if current == new_name:
        return False
    raw = base64.b64decode(doc["compatibility"]["legacy_payload_base64"], validate=True)
    old = current.encode("cp1252")
    new = new_name.encode("cp1252")
    quoted_old = b'"' + old + b'"'
    if quoted_old not in raw:
        raise SystemExit(f"{path}: current J_Name bytes not found in compatibility payload: {current!r}")
    raw = raw.replace(quoted_old, b'"' + new + b'"', 1)
    entry["text"] = new_name
    save_payload(doc, raw)
    if apply:
        write_json(path, doc)
    return True


def field_docs(fixed_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for path in sorted(fixed_root.glob("*.json"), key=lambda p: p.name.casefold()):
        if path.name.casefold() == "index.json":
            continue
        doc = load(path)
        if doc.get("schema") == "summit.fixed-npcs/v1":
            out.append((path, doc))
    return out


def find_field(docs: list[tuple[Path, dict[str, Any]]], names: set[str]) -> tuple[Path, dict[str, Any]]:
    hits = []
    for path, doc in docs:
        base = Path(str(doc.get("logical_path", "")).replace("\\", "/")).name.casefold()
        if base in names:
            hits.append((path, doc))
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one fixed-NPC field {sorted(names)}, found {len(hits)}")
    return hits[0]


def ensure_slot(doc: dict[str, Any], placement: dict[str, Any], *, remove_if: set[str] | None = None) -> tuple[bool, list[str]]:
    rows = list(doc.get("npcs", []))
    slot = int(placement["slot"])
    notes: list[str] = []
    existing = [r for r in rows if int(r.get("slot", -1)) == slot]
    if len(existing) > 1:
        raise SystemExit(f'{doc.get("logical_path")}: duplicate slot {slot}')
    if existing:
        current_id = str(existing[0].get("npc_id", ""))
        if current_id not in KNOWN_IDS:
            raise SystemExit(f'{doc.get("logical_path")}: refusing to overwrite unexpected slot {slot}: {current_id}')
    before = json.dumps(rows, sort_keys=True)
    rows = [r for r in rows if int(r.get("slot", -1)) != slot]
    rows.append(dict(placement))
    rows.sort(key=lambda r: int(r.get("slot", 0)))
    doc["npcs"] = rows
    after = json.dumps(rows, sort_keys=True)
    if existing:
        notes.append(f"slot {slot}: {existing[0].get('npc_id')} -> {placement['npc_id']}")
    else:
        notes.append(f"slot {slot}: added {placement['npc_id']}")
    return before != after, notes


def remove_slot_alias(doc: dict[str, Any], slot: int, npc_id: str) -> tuple[bool, str | None]:
    rows = list(doc.get("npcs", []))
    hits = [r for r in rows if int(r.get("slot", -1)) == slot]
    if not hits:
        return False, None
    if len(hits) > 1:
        raise SystemExit(f'{doc.get("logical_path")}: duplicate slot {slot}')
    current = str(hits[0].get("npc_id", ""))
    if current == npc_id:
        doc["npcs"] = [r for r in rows if int(r.get("slot", -1)) != slot]
        return True, f"slot {slot}: removed legacy alias {npc_id}"
    if current in KNOWN_IDS:
        return False, f"slot {slot}: kept {current}"
    raise SystemExit(f'{doc.get("logical_path")}: refusing to remove unexpected slot {slot}: {current}')


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore Amanda and Enzo canonical identities/placements")
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = ap.parse_args()

    repo = args.repo_root.resolve()
    canonical = repo / "SourceCode" / "Content" / "canonical"
    text_root = canonical / "text" / "resources" / "Servidor" / "GameServer" / "NPC"
    fixed_root = canonical / "fixed_npcs"
    if not text_root.is_dir() or not fixed_root.is_dir():
        raise SystemExit(f"canonical roots missing: text={text_root} fixed={fixed_root}")

    ji = find_resource(text_root, "npc.ji_woo")
    ji_name = find_resource(text_root, "text.jiwoo")
    enzo_name = find_resource(text_root, "text.enzo_o_restaure")

    text_changes = []
    if patch_model(ji, r"char\npc\ji_woo\jiwoo.INI", args.apply):
        text_changes.append("npc.ji_woo model -> Amanda/jiwoo")
    if patch_name(ji_name, "Amanda", args.apply):
        text_changes.append("text.jiwoo name -> Amanda")
    if patch_name(enzo_name, "Enzo, o Restaurador de Itens", args.apply):
        text_changes.append("text.enzo_o_restaure name -> Enzo, o Restaurador de Itens")

    docs = field_docs(fixed_root)
    ric_path, ric = find_field(docs, {"village-2.ase.spc"})
    pil_path, pil = find_field(docs, {"pilai.ase.spc", "pillai.ase.spc"})

    fixed_changes = []
    changed, notes = ensure_slot(ric, AMANDA_PLACEMENT)
    if changed:
        fixed_changes += [f"{ric.get('logical_path')}: {x}" for x in notes]
    removed, note = remove_slot_alias(pil, 20, "npc.amanda")
    if removed and note:
        fixed_changes.append(f"{pil.get('logical_path')}: {note}")
    changed, notes = ensure_slot(pil, ENZO_PLACEMENT)
    if changed:
        fixed_changes += [f"{pil.get('logical_path')}: {x}" for x in notes]

    if args.apply:
        if fixed_changes:
            write_json(ric_path, ric)
            write_json(pil_path, pil)

    # Audit remaining placements without silently deleting unknown intentional uses.
    remaining: dict[str, list[str]] = {key: [] for key in KNOWN_IDS}
    effective_docs = []
    for path, doc in docs:
        if path == ric_path:
            doc = ric
        elif path == pil_path:
            doc = pil
        effective_docs.append(doc)
    for doc in effective_docs:
        for row in doc.get("npcs", []):
            npc_id = str(row.get("npc_id", ""))
            if npc_id in remaining:
                remaining[npc_id].append(f"{doc.get('logical_path')}#{row.get('slot')}")

    print(f"MODE={'APPLY' if args.apply else 'DRY_RUN'}")
    for item in text_changes:
        print(f"TEXT_CHANGE={item}")
    for item in fixed_changes:
        print(f"FIXED_CHANGE={item}")
    print("TARGET_AMANDA=Ricarten/village-2 slot=20 npc.ji_woo x=-175442 y=52480 z=-4438784 ay=1000")
    print("TARGET_ENZO=Pillai/pilai slot=21 npc.enzo_o_restaure x=268949 y=167424 z=19485184 ay=1579")
    for npc_id in sorted(remaining):
        print(f"PLACEMENTS {npc_id}={remaining[npc_id]}")
    print(f"CHANGES={len(text_changes) + len(fixed_changes)}")
    print("RESULT=PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
