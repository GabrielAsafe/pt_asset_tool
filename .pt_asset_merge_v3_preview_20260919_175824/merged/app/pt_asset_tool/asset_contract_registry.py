from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable

REGISTRY_FORMAT = "PT_ASSET_CONTRACT_REGISTRY_V1"
CATALOG_VERSION = "V4"

# Implementation state is intentionally separate from source-derived capability.
# The source can prove that a format is authorable before this Python tool has a
# certified from-zero compiler for it.
_IMPLEMENTATION: dict[str, dict[str, Any]] = {
    "texture.standard": {"state": "TOOLCHAIN_READY", "adapter": "texture/image pipeline"},
    "texture.alias.stg_sta": {"state": "VALIDATOR_READY", "adapter": "asset compiler alias validator"},
    "texture.protected.bmp14": {"state": "CORPUS_CERT_REQUIRED", "adapter": None},
    "texture.protected.tga18": {"state": "CORPUS_CERT_REQUIRED", "adapter": None},
    "material.embedded": {"state": "COMPILER_READY_EMBEDDED_V1", "adapter": "material_group_compiler"},
    "model.ase": {"state": "TOOLCHAIN_READY", "adapter": "ASE importer/compiler"},
    "model.smd.062": {"state": "COMPILER_READY_STATIC_V1", "adapter": "asset_compiler:model062_static + verified import"},
    "model.smb.bone": {"state": "COMPILER_READY_SKELETON_V1", "adapter": "asset_compiler:model062_skeleton + verified import"},
    "stage.smd.072": {"state": "COMPILER_READY_STAGE_V1", "adapter": "asset_compiler:stage072 native + verified import"},
    "model.config.ini": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "model.cache.inx": {"state": "COMPILER_READY_DERIVED", "adapter": "asset_compiler:model_cache_inx"},
    "character.monster.inf": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "character.npc.npc": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "character.player.visual": {"state": "CODE_BOUNDARY", "adapter": "bundle planner"},
    "item.definition.txt": {"state": "COMPILER_READY_WITH_CODE_ID_BOUNDARY", "adapter": "asset_compiler:text"},
    "item.visual.bundle": {"state": "CODE_BOUNDARY", "adapter": "bundle planner"},
    "field.spawn.spm": {"state": "COMPILER_READY", "adapter": "asset_compiler:spm"},
    "field.startpoints.spp": {"state": "COMPILER_READY", "adapter": "asset_compiler:spp"},
    "field.fixed_npc.spc": {"state": "COMPILER_READY", "adapter": "asset_compiler:spc_win32"},
    "field.bundle": {"state": "BUNDLE_READY_WITH_CODE_ID_BOUNDARY", "adapter": "bundle planner"},
    "effect.animation.ini": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "effect.lua.dsl": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "effect.particle.part": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "effect.particle.luac": {"state": "FORMAT_IMPL_MISSING", "adapter": None},
    "audio.wav": {"state": "TOOLCHAIN_READY", "adapter": "file/image/audio bundle pipeline"},
    "audio.bgm": {"state": "CODE_BOUNDARY", "adapter": "bundle planner"},
    "ui.help.sin": {"state": "COMPILER_READY", "adapter": "asset_compiler:sin"},
    "ui.quest.msg": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "ui.clan.msg": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "event.bellatra.ini": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "ui.fontimagepos.dat": {"state": "COMPILER_READY", "adapter": "asset_compiler:font_image_pos"},
    "event.bellatra.dat": {"state": "COMPILER_READY", "adapter": "asset_compiler:bellatra_dat"},
    "ui.map.stageinfo.dat": {"state": "COMPILER_READY_DERIVED", "adapter": "asset_compiler:stage_info_dat"},
    "font.resource": {"state": "TOOLCHAIN_READY", "adapter": "file bundle pipeline"},
    "server.main_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "server.skill_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "database.migrations.sql": {"state": "OPERATIONAL_ONLY", "adapter": None},
    "runtime.clan.rep": {"state": "NOT_ASSET", "adapter": None},
    "runtime.registry.rgx": {"state": "NOT_ASSET", "adapter": None},
    "runtime.persistence.legacy": {"state": "NOT_ASSET", "adapter": None},
    "runtime.cpitem.dat": {"state": "NOT_ASSET", "adapter": None},
    "runtime.blesscastle.dat": {"state": "NOT_ASSET", "adapter": None},
    "security.remote.yul": {"state": "NOT_ASSET", "adapter": None},
    "presentation.opening_field.txt": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "render.sky.profile.txt": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "ui.pet_messages.txt": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "ui.party_quest_text.txt": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "server.present_postbox.dat": {"state": "COMPILER_READY", "adapter": "asset_compiler:text"},
    "audio.character_sound_bundle": {"state": "CODE_BOUNDARY", "adapter": "bundle planner"},
    "quest.existing_content_bundle": {"state": "CODE_BOUNDARY", "adapter": "bundle planner"},
    "ui.tony.ini": {"state": "DORMANT", "adapter": None},
    "font.bitmap_legacy.dat": {"state": "DORMANT", "adapter": None},
    "diagnostic.assa_loading.txt": {"state": "NOT_ASSET", "adapter": None},
    "ui.autohelp.bundle": {"state": "COMPILER_READY", "adapter": "asset_compiler:text/bundle"},
    "client.game_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "font.runtime_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "server.systems_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "server.exp_manager_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "security.cracker_config": {"state": "OPERATIONAL_SECURITY_ONLY", "adapter": None},
    "client.opening_settings": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
    "voice.launcher_config": {"state": "COMPILER_READY", "adapter": "asset_compiler:ini/text"},
}


@dataclass(frozen=True)
class AssetContract:
    data: dict[str, Any]

    @property
    def contract_id(self) -> str:
        return str(self.data["id"])

    @property
    def implementation(self) -> dict[str, Any]:
        return dict(_IMPLEMENTATION.get(self.contract_id, {"state": "UNMAPPED", "adapter": None}))

    def public(self) -> dict[str, Any]:
        row = dict(self.data)
        row["implementation"] = self.implementation
        return row


def _data_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "contracts"


def _load_json(name: str) -> dict[str, Any]:
    path = _data_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog() -> dict[str, Any]:
    data = _load_json("catalog_v4.json")
    if data.get("contract_count") != len(data.get("contracts") or []):
        raise RuntimeError("ASSET_CONTRACT_CATALOG_COUNT_MISMATCH")
    ids = [str(row.get("id") or "") for row in data.get("contracts") or []]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise RuntimeError("ASSET_CONTRACT_CATALOG_ID_INVALID")
    return data


def iter_contracts() -> Iterable[AssetContract]:
    for row in load_catalog().get("contracts") or []:
        yield AssetContract(dict(row))


def get_contract(contract_id: str) -> AssetContract:
    cid = str(contract_id or "").strip()
    for contract in iter_contracts():
        if contract.contract_id == cid:
            return contract
    raise KeyError(cid)


def schema_for_contract(contract_id: str) -> dict[str, Any] | None:
    mapping = {
        "field.fixed_npc.spc": "spc_win32_abi.json",
        "field.startpoints.spp": "spp_win32_abi.json",
        "ui.fontimagepos.dat": "font_image_pos.json",
        "ui.map.stageinfo.dat": "stage_info_dat.json",
        "event.bellatra.dat": "bellatra_dat.json",
        "model.smd.062": "smd_model_062.json",
        "stage.smd.072": "smd_stage_072.json",
        "material.embedded": "material_group_win32.json",
    }
    name = mapping.get(str(contract_id))
    return _load_json(name) if name else None


def registry_summary(*, query: str = "", capability: str = "", implementation: str = "") -> dict[str, Any]:
    q = str(query or "").strip().casefold()
    cap = str(capability or "").strip().upper()
    impl = str(implementation or "").strip().upper()
    rows = []
    counts: dict[str, int] = {}
    source_cap_counts: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    for contract in iter_contracts():
        row = contract.public()
        state = str(row["implementation"].get("state") or "UNMAPPED")
        source_cap = str(row.get("capability") or "UNKNOWN")
        if q:
            hay = " ".join(str(row.get(k) or "") for k in ("id", "family", "extensions", "runtime", "capability", "authoring", "constraints", "code_boundaries")).casefold()
            if q not in hay:
                continue
        if cap and source_cap.upper() != cap:
            continue
        if impl and state.upper() != impl:
            continue
        rows.append(row)
        counts[state] = counts.get(state, 0) + 1
        source_cap_counts[source_cap] = source_cap_counts.get(source_cap, 0) + 1
        for side in str(row.get("runtime") or "").split(";"):
            side = side.strip().upper()
            if side:
                runtime_counts[side] = runtime_counts.get(side, 0) + 1
    all_rows = list(iter_contracts())
    all_impl_counts: dict[str, int] = {}
    for c in all_rows:
        state = str(c.implementation.get("state") or "UNMAPPED")
        all_impl_counts[state] = all_impl_counts.get(state, 0) + 1
    ready_states = {
        "COMPILER_READY", "COMPILER_READY_DERIVED", "COMPILER_READY_WITH_CODE_ID_BOUNDARY",
        "COMPILER_READY_STATIC_V1", "COMPILER_READY_SKELETON_V1", "COMPILER_READY_STAGE_V1",
        "COMPILER_READY_EMBEDDED_V1", "TOOLCHAIN_READY", "BUNDLE_READY_WITH_CODE_ID_BOUNDARY",
        "VALIDATOR_READY",
    }
    return {
        "format": REGISTRY_FORMAT,
        "status": "PASS",
        "catalog_version": CATALOG_VERSION,
        "contract_count": len(all_rows),
        "filtered_count": len(rows),
        "ready_or_integrated_count": sum(n for state, n in all_impl_counts.items() if state in ready_states),
        "implementation_counts": dict(sorted(all_impl_counts.items())),
        "filtered_implementation_counts": dict(sorted(counts.items())),
        "filtered_source_capability_counts": dict(sorted(source_cap_counts.items())),
        "filtered_runtime_counts": dict(sorted(runtime_counts.items())),
        "rows": rows,
        "source_archive_sha256": load_catalog().get("source_archive_sha256"),
        "target_abi": load_catalog().get("target_abi"),
        "source_modified": False,
        "client_modified": False,
        "server_modified": False,
    }


def source_registry(name: str) -> dict[str, Any]:
    allowed = {
        "skill_config": "skill_config_registry.json",
        "server_main_config": "server_main_config_directives.json",
        "operational_ini": "operational_ini_keys.json",
        "code_boundaries": "code_boundaries.json",
        "character_tokens": "character_config_tokens.json",
        "item_tokens": "item_definition_tokens.json",
        "item_catalog": "item_catalog.json",
        "model_motion_skills": "model_motion_skill_catalog.json",
    }
    key = str(name or "").strip().lower()
    if key not in allowed:
        raise KeyError(key)
    return _load_json(allowed[key])

def match_contracts_for_path(path: str) -> list[dict[str, Any]]:
    """Return source-contract candidates for a logical asset path.

    This is design-tool routing evidence, never dependency/binding evidence. Exact
    source-proven path conventions are preferred; extension-only matches are
    explicitly labelled as candidates so they cannot silently become relations.
    """
    logical = str(path or "").replace("\\", "/").strip("/")
    low = logical.casefold()
    name = pathlib.PurePosixPath(logical).name.casefold()
    suffix = pathlib.PurePosixPath(logical).suffix.casefold()
    exact: list[str] = []
    if low.startswith("gameserver/field/") and suffix in {".spm", ".spp", ".spc"}:
        exact.append({".spm": "field.spawn.spm", ".spp": "field.startpoints.spp", ".spc": "field.fixed_npc.spc"}[suffix])
    if low.startswith("gameserver/monster/") and suffix == ".inf": exact.append("character.monster.inf")
    if low.startswith("gameserver/npc/") and suffix in {".npc", ".inf"}: exact.append("character.npc.npc")
    if "gameserver/openitem/" in low and suffix == ".txt": exact.append("item.definition.txt")
    if name == "fontimagepos.dat": exact.append("ui.fontimagepos.dat")
    if name == "stageinfo.dat": exact.append("ui.map.stageinfo.dat")
    if name == "bellatra.dat": exact.append("event.bellatra.dat")
    if name == "present.dat": exact.append("server.present_postbox.dat")
    if name == "settings.ini": exact.append("client.opening_settings")
    if name == "luncher.ini": exact.append("voice.launcher_config")
    if name == "hotuk.ini": exact.append("server.main_config")
    if name == "game.ini": exact.append("client.game_config")
    if suffix == ".sin": exact.append("ui.help.sin")
    if suffix == ".part": exact.append("effect.particle.part")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cid in exact:
        if cid in seen: continue
        seen.add(cid)
        try: c = get_contract(cid).public()
        except KeyError: continue
        rows.append({"match": "EXACT_PATH_CONVENTION", "contract": c})
    for c in iter_contracts():
        if c.contract_id in seen: continue
        exts = {x.strip().casefold() for x in str(c.data.get("extensions") or "").split(";") if x.strip().startswith(".")}
        if suffix and suffix in exts:
            rows.append({"match": "EXTENSION_CANDIDATE", "contract": c.public()})
    return rows
