from __future__ import annotations

"""Reverse-engineering provenance for the historical Management utilities.

This module deliberately reports *capabilities*, not a promise that every old EXE
has been cloned instruction-for-instruction.  A capability is promoted to PORTED
only when the legacy behavior has enough static evidence to reproduce it and the
Python replacement is covered by tests.  Unsafe legacy behavior is documented and
corrected by default; an exact-legacy mode is exposed only where it is useful and
bounded.
"""

from dataclasses import dataclass, asdict
from typing import Any

ARCHIVE_NAME = "Management(2).zip"
ARCHIVE_SHA256 = "c129657b686abb95ecc1e81fc8050513963993ca0abb471efb8597068e7762d7"


@dataclass(frozen=True)
class LegacyApp:
    app_id: str
    aliases: tuple[str, ...]
    sha256: str
    runtime: str
    reverse_status: str
    python_status: str
    capabilities: tuple[str, ...]
    python_replacement: str | None
    corrections: tuple[str, ...] = ()
    remaining_gaps: tuple[str, ...] = ()
    alternate_hashes: tuple[str, ...] = ()


_APPS = (
    LegacyApp(
        "item_editor",
        ("Editor de Itens.exe", "Editor De Equipamentos.exe", "ItemEditor.exe"),
        "537a9d40f6d604fba9a60685799167d659367fb26a93846e9545b8d165a99c84",
        "native-packed",
        "FUNCTIONALLY_RECOVERED",
        "PORTED_BETTER",
        ("OpenItem create/edit", "item definition validation", "runtime-known item code authoring"),
        "pt_asset_tool.legacy_authoring",
        (
            "Uses transactional staged authoring instead of direct in-place editing.",
            "Registering a brand-new runtime sITEM code is a separate runtime/source capability and was not proven as behavior of the historical ItemEditor; create/edit therefore targets runtime-known codes.",
        ),
        (),
    ),
    LegacyApp(
        "monster_editor",
        ("Editor de Monstros.exe",),
        "439a8cd1b5df9621aa862af098c38733ccf531343430b32dc404c358abaf8d2d",
        "native",
        "FUNCTIONALLY_RECOVERED",
        "PORTED_BETTER",
        ("Monster INF create/edit", "drops/extra-drops", "stats and linked model fields"),
        "pt_asset_tool.legacy_authoring",
        ("Structured parser/writer and preflight validation replace direct legacy text mutation.",),
    ),
    LegacyApp(
        "npc_manager",
        ("NPCManager.exe",),
        "9a404b7745f7d27cdcbcfa2c93863ba5da6f40a25da5fe8bd9ef1f14d09bd9d8",
        ".NET",
        "REVERSED_LAYOUT_EXACT",
        "PORTED",
        ("SPC fixed NPC list", "100x504-byte record layout", "name/model/server path", "X/Y/Z/angle"),
        "pt_asset_tool.legacy_authoring",
        ("Writes are staged, hashed and deployable instead of immediately mutating a live server file.",),
    ),
    LegacyApp(
        "pritat_or",
        ("PriTaTor_1.8.857.exe",),
        "2ccd73fe0fee7f4aa65eaafae7a0d4921ec375211c1d0dd93342a7ddfc4b1869",
        ".NET",
        "REVERSED_HIGH",
        "PORTED_CORE_PLUS_BULK_EXP_GOLD",
        (
            "item search/edit", "monster EXP/level/gold/drop editing", "SPM map actors/bosses/spawn",
            "NPC/shop inspection", "backup/restore concepts", "bulk monster formulas", "item distribution helper",
        ),
        "pt_asset_tool.legacy_authoring + pt_asset_tool.legacy_apps",
        (
            "Historical taxonomy/config is internal rather than user-facing.",
            "Bulk operations are planned/validated before write.",
            "Direct raw Monster editor UI parity is intentionally replaced by structured authoring; Bulk EXP and Gold are Python-native preview→stage workflows.",
        ),
        (),
    ),
    LegacyApp(
        "item_distributor",
        ("ItemDistributor.exe",),
        "68cbe9fa73f9b57ee24dd4bddb624b7450b1adabe63a7b46c316ea5f37ca3982",
        ".NET",
        "REVERSED_EXACT",
        "PORTED",
        ("DataServer character existence check", "Postbox bucket", "Postbox queue read/write", "spec/message/quantity"),
        "pt_asset_tool.legacy_apps.item_distributor",
        (
            "Default mode appends and backs up instead of File.CreateText overwriting the whole queue.",
            "Quotes/newlines in message are rejected because the legacy line grammar has no escaping.",
        ),
    ),
    LegacyApp(
        "item_finder",
        ("Procura item pelo nome.exe",),
        "c6a7bb4f379b6ae571763fb2ecd6873923a1819d0b02fbc64736ce4a572e6a16",
        ".NET",
        "REVERSED_PARSER_HIGH",
        "PORTED_READ_ONLY",
        ("userdata inventory parser", "warehouse parser", "serial duplicate grouping", "256-bucket scan"),
        "pt_asset_tool.legacy_apps.item_finder",
        (
            "Scanner is read-only and bounds-checked; malformed records cannot mutate persistence files.",
            "Writer/mutation was not part of this EXE and is intentionally not added to the scanner.",
        ),
        (),
    ),
    LegacyApp(
        "sod_manager",
        ("ClanSoDManager.exe", "SoD Atualiza.exe"),
        "058575d1004afc07d1cc253c7a4fd462157e0f39f1d023bce99fbe16f50c3923",
        ".NET",
        "REVERSED_ALGORITHM_HIGH",
        "PORTED_SQLITE",
        ("SoD run aggregation", "clan score update", "top clan", "clan money access"),
        "pt_asset_tool.legacy_apps.sod_manager.SQLiteSodDataSource",
        (
            "Embedded SQL Server credentials are discarded.",
            "The active implementation uses local SQLite with parameterized values and no network dependency.",
            "Updates are dry-run plans until explicit confirmation.",
            "UI-only localization/default-setting differences between the two .NET builds are not product behavior.",
        ),
        (),
        ("c58cd3b2e9962f7b91181322a4ecf805de7f8f82ff3e7956f4b887cac01d5d9c",),
    ),
    LegacyApp(
        "account_controller",
        ("ControllerUser.exe", "Editor de conta.exe"),
        "8cab308f4fb89cc69dc0d2a7ff68b1cd471aa2f94358979ecad1fecc9586e199",
        "native",
        "REVERSED_LAYOUT_HIGH",
        "PORTED_SAFE_PLUS_EXPERT_ABI_AND_INVENTORY_ADMIN",
        ("userinfo/userdata/warehouse inspection", "character/account inventory inspection", "item serial duplicate search", "character/account rename", "account graph migration/restore", "level/XP writer with audited table", "safe primary stats", "source-backed expert smCHAR_INFO fields", "proven fixed-record inventory delete", "reviewed batch delete", "explicit userdata/warehouse scope clear"),
        "pt_asset_tool.legacy_apps.userdata_admin + pt_asset_tool.legacy_apps.controller_inventory",
        (
            "Proven identity/level operations, account-graph migration and fixed-record inventory delete/clear use transactional writers; arbitrary item field mutation is intentionally not invented.",
            "SumFile.dat, CompyItem.dat and per-target cp.dat are generated scratch/export artifacts from ControllerUser, not DataServer/runtime dependencies.",
            "The native Edit button uses Code/Head/CheckSum as search criteria; reverse evidence does not prove arbitrary persistent mutation of those identifiers, so Python exposes search/inspection/delete instead of a fabricated item editor.",
        ),
        (),
    ),
    LegacyApp(
        "rename",
        ("MudarNome.exe", "Mudar Nick Do Personagen.exe"),
        "0a9b9e989a46fcf062896148990d5ab548f6a829a13e1e7e65cdba009be56599",
        "native",
        "REVERSED_LAYOUT_EXACT",
        "PORTED_SAFE",
        ("DataServer bucket algorithm", "character/account rename filesystem graph", "userdata character/account fixed fields", "userinfo account and six character slots", "warehouse identity move"),
        "pt_asset_tool.legacy_apps.userdata_admin",
        ("Direct CopyFile/DeleteFile behavior is replaced by hash preflight, backups, atomic writes and post-write verification.",),
        (),
    ),
    LegacyApp(
        "level_editor",
        ("Level Editor.exe",),
        "2fe72bf09d788b5429caa402123699ca1fc950923d71bde49b100b69cc1084d0",
        "native-msvc",
        "REVERSED_WRITER_EXACT",
        "PORTED_WITH_AUDITED_GAME_TABLE",
        ("DataServer bucket", "userdata target discovery", "zero-based level field at 0xC8", "XP low dword at 0x14C", "XP high dword at 0x194", "level-to-XP lookup via XPHex.txt"),
        "pt_asset_tool.legacy_apps.userdata_admin",
        (
            "Corrects the native one-byte level write for indexes below 256 by writing the proven two-byte field, preventing stale high bytes.",
            "XP progression is game data, not executable behavior. The supplied serverfiles corpus contains XPHex variants; the Python port audits monotonicity and may auto-select a valid table instead of trusting a filename.",
        ),
        (),
    ),
    LegacyApp(
        "japaokiko",
        ("Editor Japaokiko.exe",),
        "aa9067ce6014e9e9c7336b6bc02a51c93f6d947ff8453828168f306eb6cf25a0",
        "native-delphi-vcl",
        "REVERSED_CAPABILITIES_HIGH",
        "PORTED_USEFUL_TASKS",
        (
            "server IP/DNS administration", "hotuk.ini settings", "clan NPC SPC control",
            "character/userdata editor", "SQL BPRank operations", "level/premium configuration",
        ),
        "pt_asset_tool.legacy_apps.server_admin + existing SPC/authoring modules",
        (
            "Network/IP/firewall administration is obsolete because the active stack is localhost + SQLite.",
            "BPRank database operations use local SQLite rather than SQL Server.",
            "Version-specific direct Server.exe patching for age/premium/max-level is retired rather than reproduced; no stable source/config equivalent was found in the supplied current runtime corpus.",
            "Hotuk/SPC/BPRank and source-backed character fields are first-party Python capabilities.",
        ),
        (),
    ),
    LegacyApp(
        "ptprotector",
        ("PTprotector.exe",),
        "df23d85fcd1791963ae08db0ed2fcff9f8276d28b4fb18b2b6220cef7a991dba",
        "native-vb6",
        "REVERSED_RULE_GRAMMAR_HIGH",
        "PORTED_DETECTION_AND_SQLITE_BLOCK",
        ("log/hotuk monitoring", "excluded account/IP lists", "error alias/library rules", "account block SQL workflow"),
        "pt_asset_tool.legacy_apps.protector",
        (
            "Default operation is read-only detection; SQLite blocking requires explicit confirmation and parameterized SQL.",
            "Exact VB6 UI/timing quirks are not treated as required product behavior.",
        ),
        (),
    ),
    LegacyApp(
        "server_firewall",
        ("Portas SQL.bat",),
        "text-script",
        "batch/cmd",
        "REVERSED_EXACT",
        "OBSOLETE_NOT_APPLICABLE",
        ("Windows firewall SQL/HTTP/SSL port openings",),
        "pt_asset_tool.legacy_apps.server_admin.local_runtime_policy",
        (
            "The active game runs on localhost and uses SQLite; no SQL listener or firewall rule is required.",
            "The legacy batch is retained as provenance only and has no apply path.",
        ),
    ),
    LegacyApp(
        "restarter_config",
        ("ConfigRestarter.ini",),
        "text-config",
        "ini",
        "CONFIG_ONLY",
        "PORTED_CONFIG",
        ("server executable name", "startup message"),
        "pt_asset_tool.legacy_apps.server_admin",
        ("No restarter executable was included in Management(2).zip; the Python supervisor implements the complete available INI contract (NomeEXE + Mensagem) with bounded Linux/Wine process control.",),
        (),
    ),
)


def apps() -> tuple[LegacyApp, ...]:
    return _APPS


def reverse_status() -> dict[str, Any]:
    rows = [asdict(x) for x in _APPS]
    unique_binary_hashes = sorted({h for x in _APPS for h in ((x.sha256,) + x.alternate_hashes) if len(h) == 64})
    remaining = [
        {"app_id": x.app_id, "gaps": list(x.remaining_gaps)}
        for x in _APPS if x.remaining_gaps
    ]
    return {
        "format": "PT_LEGACY_APPS_REVERSE_STATUS_V3",
        "archive": ARCHIVE_NAME,
        "archive_sha256": ARCHIVE_SHA256,
        "applications": rows,
        "visible_names": sum(len(x.aliases) for x in _APPS),
        "unique_binary_hashes": len(unique_binary_hashes),
        "coverage": {
            "management_unique_pe_expected": 13,
            "management_unique_pe_mapped": len(unique_binary_hashes),
            "management_unique_pe_unmapped": max(0, 13 - len(unique_binary_hashes)),
            "applications_with_remaining_operational_gaps": len(remaining),
            "remaining_operational_gaps": remaining,
            "definition": "Every supplied unique PE has an explicit Python replacement/retirement decision; corrected or obsolete Windows behavior is not counted as an operational gap.",
        },
        "policy": {
            "normal_ui": "Expose Python capabilities/tasks, not old EXE launch buttons.",
            "writes": "Promote only proven layouts/algorithms; otherwise inspect/plan-only.",
            "unsafe_legacy_behavior": "Correct by default and document legacy-exact behavior when bounded/useful.",
            "platform": "Fedora/Linux first; old Windows executables are provenance, not runtime dependencies.",
            "active_database": "SQLite local files; SQL Server/ODBC/network firewall setup is obsolete.",
        },
    }
