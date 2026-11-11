#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path
from typing import Any

AMANDA_PRIMARY = "npc.ji_woo"
AMANDA_ALIAS = "npc.amanda"
ENZO_ID = "npc.enzo_o_restaure"

HEADER = struct.Struct("<4sHH10I32s")
RECORD = struct.Struct("<5I")
DIRECTIVE = struct.Struct("<3I")


def source_root(repo: Path) -> Path:
    repo = repo.resolve()
    if (repo / "SourceCode" / "Content" / "canonical").is_dir():
        return repo / "SourceCode"
    if (repo / "Content" / "canonical").is_dir():
        return repo
    raise SystemExit(f"cannot locate SourceCode/Content/canonical below {repo}")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_resource(resources: Path, canonical_id: str) -> dict[str, Any]:
    hits = []
    for path in resources.rglob("*.json"):
        if path.name.casefold() == "index.json":
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if doc.get("id") == canonical_id:
            hits.append((path, doc))
    if len(hits) != 1:
        raise RuntimeError(f"expected one {canonical_id}, found {len(hits)}")
    return hits[0][1]


def name_of(doc: dict[str, Any]) -> str:
    for row in doc.get("semantic", {}).get("entries", []):
        if row.get("kind") == "name" or str(row.get("legacy_key", "")).casefold() == "j_name":
            return str(row.get("text", ""))
    return ""


def _map_identity(path: Path, doc: dict[str, Any]) -> str:
    for key in ("map_id", "canonical_id", "id", "logical_path"):
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value
    return path.stem


def _looks_like_fixed_npc_doc(doc: dict[str, Any]) -> bool:
    schema = str(doc.get("schema", "")).casefold()
    if "fixed" in schema and "npc" in schema and isinstance(doc.get("npcs"), list):
        return True
    if not isinstance(doc.get("npcs"), list):
        return False
    return any(
        isinstance(doc.get(key), (str, int))
        for key in (
            "map_id",
            "canonical_id",
            "id",
            "logical_path",
            "map",
            "map_name",
            "internal_name",
            "field_id",
        )
    )


def _fixed_docs(fixed: Path) -> list[tuple[Path, dict[str, Any]]]:
    docs = []
    for path in sorted(fixed.rglob("*.json"), key=lambda p: str(p).casefold()):
        if path.name.casefold() == "index.json":
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if _looks_like_fixed_npc_doc(doc):
            docs.append((path, doc))
    if docs:
        return docs

    # Family may have moved under canonical after the legacy-structure cleanup.
    for path in sorted(fixed.parent.rglob("*.json"), key=lambda p: str(p).casefold()):
        if path.name.casefold() == "index.json":
            continue
        try:
            doc = load(path)
        except Exception:
            continue
        if _looks_like_fixed_npc_doc(doc):
            docs.append((path, doc))
    return docs


def placements(fixed: Path, npc_id: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path, doc in _fixed_docs(fixed):
        identity = _map_identity(path, doc)
        for row in doc.get("npcs", []):
            if row.get("npc_id") == npc_id:
                out.append((identity, row))
    return out


def scfg_record_values(pack: Path, wanted_id: str) -> list[bytes] | None:
    data = pack.read_bytes()
    if len(data) < HEADER.size:
        return None
    h = HEADER.unpack_from(data)
    magic, version, _flags, rc, ro, rs, dc, do, ds, so, ss, _r0, _r1, _digest = h
    if magic != b"SCFG" or version != 1:
        return None

    def s(off: int) -> bytes:
        if off >= ss:
            raise ValueError("bad string offset")
        start = so + off
        end = data.find(b"\0", start, so + ss)
        if end < 0:
            raise ValueError("unterminated string")
        return data[start:end]

    for i in range(rc):
        _path_off, id_off, _kind, start, count = RECORD.unpack_from(data, ro + i * rs)
        if s(id_off).decode("utf-8") != wanted_id:
            continue
        values = []
        for j in range(start, start + count):
            _cmd_off, value_off, _flags = DIRECTIVE.unpack_from(data, do + j * ds)
            values.append(s(value_off))
        return values
    return None


def emit(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{label}={'PASS' if ok else 'FAIL'}{(' ' + detail) if detail else ''}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Static gameplay closure checks for Amanda/Enzo, Quest Codex and Mix")
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    args = ap.parse_args()
    src = source_root(args.repo_root)
    canonical = src / "Content" / "canonical"
    resources = canonical / "text" / "resources"
    fixed = canonical / "fixed_npcs"

    ok = True
    amanda = find_resource(resources, AMANDA_PRIMARY)
    alias = find_resource(resources, AMANDA_ALIAS)
    enzo = find_resource(resources, ENZO_ID)
    t_jiwoo = find_resource(resources, "text.jiwoo")
    t_amanda = find_resource(resources, "text.amanda")
    t_enzo = find_resource(resources, "text.enzo_o_restaure")

    af = amanda.get("semantic", {}).get("fields", {})
    aaf = alias.get("semantic", {}).get("fields", {})
    ef = enzo.get("semantic", {}).get("fields", {})

    ok &= emit("AMANDA_PRIMARY_CLASS", af.get("class") == 1014, str(af.get("class")))
    ok &= emit("AMANDA_ALIAS_CLASS", aaf.get("class") == 1014, str(aaf.get("class")))
    ok &= emit("ENZO_RESTORER_CLASS", ef.get("class") == 1024, str(ef.get("class")))
    ok &= emit("AMANDA_PRIMARY_MODEL", str(af.get("model_file", "")).casefold() == r"char\npc\ji_woo\jiwoo.ini".casefold())
    ok &= emit("AMANDA_ALIAS_MODEL", str(aaf.get("model_file", "")).casefold() == r"char\npc\ji_woo\jiwoo.ini".casefold())
    ok &= emit("ENZO_MODEL", str(ef.get("model_file", "")).casefold() == r"char\npc\enzo\enzo.ini".casefold())
    ok &= emit("AMANDA_PRIMARY_NAME", name_of(t_jiwoo) == "Instrutora Amanda", name_of(t_jiwoo))
    ok &= emit("AMANDA_ALIAS_NAME", name_of(t_amanda) == "Instrutora Amanda", name_of(t_amanda))
    ok &= emit("ENZO_NAME", name_of(t_enzo) == "Enzo, o Restaurador de Itens", name_of(t_enzo))

    pa = placements(fixed, AMANDA_PRIMARY)
    palias = placements(fixed, AMANDA_ALIAS)
    pe = placements(fixed, ENZO_ID)

    good_a = any(
        int(row.get("slot", -1)) == 20
        and int(row.get("x", 0)) == -175442
        and int(row.get("y", 0)) == 52480
        and int(row.get("z", 0)) == -4438784
        and int(row.get("ay", 0)) == 1000
        for _map_identity_value, row in pa
    )
    good_e = any(
        int(row.get("slot", -1)) == 21
        and int(row.get("x", 0)) == 268949
        and int(row.get("y", 0)) == 167424
        and int(row.get("z", 0)) == 19485184
        and int(row.get("ay", 0)) == 1579
        for _map_identity_value, row in pe
    )
    ok &= emit("AMANDA_RICARTEN_SLOT20", good_a, f"placements={len(pa)}")
    ok &= emit("ENZO_PILLAI_SLOT21", good_e, f"placements={len(pe)}")
    ok &= emit("AMANDA_LEGACY_ALIAS_NOT_PLACED", len(palias) == 0, f"placements={len(palias)}")

    # Compiled definitions pack, when already built.
    pack_candidates = [
        src / "Content" / "packs" / "definitions_server.scfg",
        src.parent / "Servidor" / "Content" / "packs" / "definitions_server.scfg",
    ]
    pack = next((p for p in pack_candidates if p.is_file()), None)
    if pack:
        av = scfg_record_values(pack, AMANDA_PRIMARY) or []
        ev = scfg_record_values(pack, ENZO_ID) or []
        ok &= emit("PACK_AMANDA_CLASS", b"1014" in av)
        ok &= emit("PACK_AMANDA_MODEL", any(b"ji_woo" in x.lower() for x in av))
        ok &= emit("PACK_AMANDA_NAME", any(b"Instrutora Amanda" in x for x in av))
        ok &= emit("PACK_ENZO_CLASS", b"1024" in ev)
        ok &= emit("PACK_ENZO_MODEL", any(b"enzo" in x.lower() for x in ev))
        ok &= emit("PACK_ENZO_NAME", any(b"Enzo, o Restaurador de Itens" in x for x in ev))
    else:
        print("DEFINITIONS_PACK=PENDING build definitions_server.scfg to validate compiled output")

    # Gameplay reference catalog, when integrated.
    # index.json is a manifest of canonical documents; counts live in the
    # referenced quest/mix documents, not in the index itself.
    ref_root = canonical / "gameplay_reference"
    ref_index = ref_root / "index.json"
    if ref_index.is_file():
        ref = load(ref_index)

        quest_rel = ref.get("quest_catalog")
        binding_rel = ref.get("quest_runtime_bindings")
        mix_rel = ref.get("mix_catalog")

        quest_doc = load(ref_root / str(quest_rel)) if quest_rel else {}
        binding_doc = load(ref_root / str(binding_rel)) if binding_rel else {}
        mix_doc = load(ref_root / str(mix_rel)) if mix_rel else {}

        quest_keys = (
            "progression_quests",
            "daily_quests",
            "aline_daily_quests",
            "weekly_quests",
        )
        q_count = sum(
            len(quest_doc.get(key, []) or [])
            for key in quest_keys
            if isinstance(quest_doc.get(key, []) or [], list)
        )
        bindings = binding_doc.get("bindings", []) or []
        supported_count = sum(
            1 for row in bindings
            if isinstance(row, dict) and bool(row.get("supported", False))
        )
        recipes = mix_doc.get("recipes", []) or []
        m_count = len(recipes) if isinstance(recipes, list) else 0

        ok &= emit("QUEST_CODEX_CATALOG", q_count == 88, f"quests={q_count}")
        ok &= emit("QUEST_RUNTIME_BINDINGS", supported_count == 13, f"supported={supported_count}")
        ok &= emit("MIX_GUIDE_CATALOG", m_count == 127, f"recipes={m_count}")

        # Cross-check the exact artefact emitted by compile_gameplay_reference.py
        # when available. This proves that canonical counts reached the runtime
        # pack build, independently from the catalog source files above.
        report_candidates = [
            src / "Content" / "packs" / "gameplay_reference.sgrf.report.json",
            src.parent / "cliente" / "Content" / "packs" / "gameplay_reference.sgrf.report.json",
            src.parent / "Servidor" / "Content" / "packs" / "gameplay_reference.sgrf.report.json",
        ]
        report_path = next((x for x in report_candidates if x.is_file()), None)
        if report_path:
            report = load(report_path)
            pack_ok = (
                report.get("format") == "SGRF"
                and int(report.get("version", 0)) == 2
                and int(report.get("quests", -1)) == q_count
                and int(report.get("supported_quests", -1)) == supported_count
                and int(report.get("mix_recipes", -1)) == m_count
            )
            ok &= emit(
                "GAMEPLAY_REFERENCE_PACK_REPORT",
                pack_ok,
                (
                    f"version={report.get('version')} "
                    f"quests={report.get('quests')} "
                    f"supported={report.get('supported_quests')} "
                    f"mix_recipes={report.get('mix_recipes')}"
                ),
            )
        else:
            print("GAMEPLAY_REFERENCE_PACK_REPORT=PENDING report file absent")

        print("QUEST_CODEX_RUNTIME_UI=PENDING requires in-game Codex open/detail test")
        print("MIX_GUIDE_RUNTIME_UI=PENDING requires in-game Mix NPC/open/search test")
    else:
        print("QUEST_CODEX_CATALOG=PENDING gameplay_reference/index.json absent")
        print("QUEST_RUNTIME_BINDINGS=PENDING gameplay_reference/index.json absent")
        print("MIX_GUIDE_CATALOG=PENDING gameplay_reference/index.json absent")
        print("GAMEPLAY_REFERENCE_PACK_REPORT=PENDING gameplay_reference/index.json absent")
        print("QUEST_CODEX_RUNTIME_UI=PENDING")
        print("MIX_GUIDE_RUNTIME_UI=PENDING")

    # Source contracts.
    source_text = ""
    for base in (src / "Shared", src / "SrcGame", src / "SrcServer"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix.casefold() not in {".cpp", ".h", ".inl"}:
                continue
            try:
                source_text += "\n" + path.read_text(encoding="latin1", errors="ignore")
            except OSError:
                pass

    has_1014 = re.search(r"\b1014\b", source_text) is not None
    has_1024 = re.search(r"\b1024\b", source_text) is not None
    has_restorer = "cRestaure" in source_text or "Restaure.Open" in source_text
    emit("CLIENT_CLASS_1014_PRESENT", has_1014)
    emit("CLIENT_CLASS_1024_RESTORER_PRESENT", has_1024 and has_restorer)

    capacity10 = "QUEST_FULL_ENTRY_MAX" in source_text or re.search(r"MonsterNames\s*\[\s*10\s*\]", source_text) is not None
    emit("QUEST_CAPACITY_10", capacity10)

    tcoin = "AddPlayerCoin" in source_text and "TCoin" in source_text
    emit("QUEST_TCOIN_GRANT", tcoin)

    tier_ids = all(x in source_text for x in ("10010", "10011", "10012", "10013"))
    emit("TIER5_IMPLEMENTATION_IDS", tier_ids)
    print("TIER5_RUNTIME_VALIDATION=PENDING requires end-to-end gameplay test")
    print("CLIENT_WINE_CRASH_ROOT_CAUSE=PENDING requires reproducible stack/device-reset trace")

    print(f"GAMEPLAY_CLOSURE_STATIC={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
