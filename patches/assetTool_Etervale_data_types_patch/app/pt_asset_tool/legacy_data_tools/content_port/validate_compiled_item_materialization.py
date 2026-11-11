#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_item_profile_pack import parse_pack
from item_profile_policy import effective_profile_codes,load_open_item_documents

SHOP_KEYS = {"sell_weapon", "sell_defence", "sell_etc"}
DELLA_CODES = {"pl101", "pl102", "pl103", "ps101", "ps102", "ps103"}


def fail(message: str) -> None:
    raise SystemExit(f"RESULT=FAIL\nERROR={message}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Validate compiled OpenItem materialization and NPC-shop bridge"
    )
    ap.add_argument("--source-root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.source_root.resolve()

    reader = root / "Shared/formats/item_config/ItemDefinitionReader.inl"
    adapter = root / "Shared/content/v1/definition/legacy/CompiledDefinitionAdapter.inl"
    server_header = root / "SrcServer/src/core/data/legacy_loader/fileread.h"
    for path in (reader, adapter, server_header):
        if not path.is_file():
            fail(f"missing source file: {path}")

    reader_text = reader.read_text(encoding="utf-8", errors="replace")
    adapter_text = adapter.read_text(encoding="utf-8", errors="replace")
    server_text = server_header.read_text(encoding="utf-8", errors="replace")

    helper_signature = "inline void InitializeItemDefinitionImport(sDEF_ITEMINFO &definition)"
    helper_zero = "std::memset(&definition.Item, 0, sizeof(definition.Item));"
    helper_call = "InitializeItemDefinitionImport(staged);"
    server_zero = "ZeroMemory(&Item, sizeof(Item));"

    if helper_signature not in reader_text or helper_zero not in reader_text:
        fail("compiled item import does not explicitly zero sITEMINFO")
    if helper_call not in reader_text:
        fail("ReadItemDefinition does not use the legacy-equivalent item initializer")
    if helper_call not in adapter_text:
        fail("ApplyCompiledItemDefinition does not use the legacy-equivalent item initializer")
    if server_zero not in server_text:
        fail("server sDEF_ITEMINFO constructor still leaves Item uninitialized")

    content = root / "Content"
    profile_path = content / "canonical/item_profiles/server.items.json"
    pack_path = content / "packs/definitions_server.scfg"
    npc_root = content / "canonical/text/resources/Servidor/GameServer/NPC"
    if not profile_path.is_file() or not pack_path.is_file() or not npc_root.is_dir():
        fail("server profile/pack/NPC canonical data is incomplete")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    legacy_profile_codes = {str(code).casefold() for code in profile.get("codes", [])}
    canonical_documents = load_open_item_documents(content / "canonical/text")
    profile_codes = effective_profile_codes(canonical_documents, "server", legacy_profile_codes)
    rows = parse_pack(pack_path)
    non_unique_direct = {
        str(row["code"]).casefold()
        for row in rows
        if row.get("direct") and row.get("code") and (row.get("unique") in (None, 0))
    }

    shop_tokens: set[str] = set()
    unresolved_tokens: set[str] = set()
    npc_docs = 0
    shop_directives = 0
    for path in npc_root.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".json":
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "npc_definition":
            continue
        npc_docs += 1
        for directive in doc.get("semantic", {}).get("directives", []):
            if directive.get("key") not in SHOP_KEYS:
                continue
            shop_directives += 1
            for value in directive.get("values") or []:
                token = str(value).strip().casefold()
                if not token or token == "없음":
                    continue
                if token in profile_codes:
                    shop_tokens.add(token)
                else:
                    unresolved_tokens.add(token)

    missing_from_pack = sorted(shop_tokens - non_unique_direct)
    della_missing = sorted(DELLA_CODES - non_unique_direct)

    report_path = pack_path.with_suffix(pack_path.suffix + ".report.json")
    if not report_path.is_file():
        fail(f"missing compiler report: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    filtered_shop_tokens = {
        str(row.get("token", "")).strip().casefold()
        for row in report.get("filtered_shop_tokens", [])
        if str(row.get("token", "")).strip()
    }
    effective_unresolved = sorted(unresolved_tokens - filtered_shop_tokens)

    print(f"SOURCE_ROOT={root}")
    print("ITEM_IMPORT_ZERO_INIT=1")
    print("SERVER_ITEM_CTOR_ZERO_INIT=1")
    print(f"SERVER_PACK={pack_path}")
    print(f"SERVER_PACK_DIRECT_NON_UNIQUE_CODES={len(non_unique_direct)}")
    print(f"NPC_DOCUMENTS={npc_docs}")
    print(f"NPC_SHOP_DIRECTIVES={shop_directives}")
    print(f"NPC_SHOP_RESOLVED_CODES={len(shop_tokens)}")
    print(f"NPC_SHOP_RAW_UNRESOLVED_LEGACY_TOKENS={len(unresolved_tokens)}")
    print(f"NPC_SHOP_FILTERED_LEGACY_TOKENS={len(filtered_shop_tokens)}")
    print(f"NPC_SHOP_EFFECTIVE_UNRESOLVED_TOKENS={len(effective_unresolved)}")
    print(f"NPC_SHOP_CODES_MISSING_NON_UNIQUE_OPENITEM={len(missing_from_pack)}")
    print(f"DELLA_EXPECTED_CODES={len(DELLA_CODES)}")
    print(f"DELLA_MISSING_CODES={len(della_missing)}")

    if unresolved_tokens:
        print("NOTE=Raw canonical shop tokens absent from the effective server item profile are preserved for audit and filtered from compiled shop directives, matching the historical parser skip behavior.")
        for token in sorted(unresolved_tokens)[:20]:
            state = "FILTERED" if token in filtered_shop_tokens else "UNHANDLED"
            print(f"LEGACY_SHOP_TOKEN={token} STATE={state}")
    if effective_unresolved:
        for token in effective_unresolved:
            print(f"UNHANDLED_LEGACY_SHOP_TOKEN={token}")
        fail("one or more legacy NPC shop tokens remain effective after compilation")
    if missing_from_pack:
        for token in missing_from_pack[:50]:
            print(f"MISSING_SHOP_OPENITEM={token}")
        fail("one or more server-resolvable NPC shop codes have no normal OpenItem in definitions_server.scfg")
    if della_missing:
        fail("Vendedora Della shop items are not materializable from definitions_server.scfg")

    print("RESULT=PASS")


if __name__ == "__main__":
    main()
