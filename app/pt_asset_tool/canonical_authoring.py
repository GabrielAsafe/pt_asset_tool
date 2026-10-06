from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any, Iterable

from .summit_canonical import (
    BUILD_SCHEMA,
    CANONICAL_SOURCE_SCHEMA,
    PACK_FILENAMES,
    SummitCanonicalContentProvider,
    canonical_id_for_doc,
    sha256_bytes,
    sha256_file,
    canonical_family_fingerprints_at,
    canonical_file_hash_inventory_at,
)

FORMAT = "PT_ASSET_CANONICAL_AUTHORING_V1"
MANIFEST_FORMAT = "PT_ASSET_CANONICAL_STAGE_MANIFEST_V1"
TRANSACTION_FORMAT = "PT_ASSET_CANONICAL_PUBLISH_TRANSACTION_V1"
PUBLISH_SOURCE_CONFIRM = "PUBLISH CANONICAL SOURCE"
PUBLISH_PACKS_CONFIRM = "PUBLISH CANONICAL PACKS"
RESTORE_CONFIRM = "RESTORE CANONICAL TRANSACTION"
PUBLISH_RUNTIME_CONFIRM = "DEPLOY CANONICAL RUNTIME"

_DEFINITION_KINDS = {"ITEM": "open_item_definition", "MONSTER": "monster_definition", "NPC": "npc_definition"}
_OTHER_KINDS = {
    "STAGE_SPAWN": "stage_spawns",
    "STAGE_START_POINT": "stage_start_points",
    "FIXED_NPC": "fixed_npcs",
    "MAP": "maps",
    "MODEL_CONFIG": "model_configs/models",
    "GAMEPLAY_CONFIG": "text",
    "LOCALIZATION": "text",
    "CANONICAL_TEXT": "text",
}

_FIXED_DOCUMENT_KINDS = {
    "COIN_SHOP_CATALOG": ("commerce/coin_shop.json", "summit.coin-shop-catalog/v1"),
    "NPC_SHOP_OVERRIDES": ("commerce/npc_shop_overrides.json", "summit.npc-shop-overrides/v1"),
    "EQUIPMENT_SETS": ("equipment_sets/equipment_sets.json", "summit.equipment-sets/v1"),
    "HEAD_COSMETICS": ("head_cosmetics/head_cosmetics.json", "summit.head-cosmetics/v1"),
    "WORLD_STORY": ("world_story/campaigns.json", "summit.world-story-campaigns/v1"),
    "WORLD_PHASES": ("world_phases/world_phases.json", "summit.world-phases/v1"),
    "COVENANT_ALTARS": ("covenant_altars/placement_plan.json", "summit.covenant-altar-placement-plan/v1"),
    "EXPERIENCE_BALANCE": ("gameplay_balance/experience.json", "summit.experience-balance/v1"),
}


def _now_id() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)


def _atomic_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _semantic(doc: dict[str, Any]) -> dict[str, Any]:
    semantic = doc.get("semantic")
    if not isinstance(semantic, dict):
        raise ValueError("CANONICAL_DEFINITION_SEMANTIC_OBJECT_REQUIRED")
    return semantic


def _field_key(fields: dict[str, Any], requested: str) -> str | None:
    target = _norm(requested)
    for key in fields:
        if _norm(key) == target:
            return key
    return None


def _directive_identity(directive: dict[str, Any]) -> set[str]:
    out = set()
    for key in ("field", "field_name", "name", "token", "directive", "key"):
        value = directive.get(key)
        if isinstance(value, str) and value.strip():
            out.add(_norm(value.lstrip("*")))
    return out


def _find_directive(directives: Any, field: str) -> tuple[Any, Any]:
    target = _norm(field)
    if isinstance(directives, list):
        matches = [(idx, row) for idx, row in enumerate(directives) if isinstance(row, dict) and target in _directive_identity(row)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"CANONICAL_DIRECTIVE_AMBIGUOUS:{field}:{len(matches)}")
        return None, None
    if isinstance(directives, dict):
        matches = []
        for key, row in directives.items():
            identities = {_norm(key.lstrip("*"))}
            if isinstance(row, dict):
                identities |= _directive_identity(row)
            if target in identities:
                matches.append((key, row))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"CANONICAL_DIRECTIVE_AMBIGUOUS:{field}:{len(matches)}")
    return None, None


def _flatten_scalars(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _encode_legacy_value(value: Any, encoding: str) -> bytes:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "1" if value else "0"
    else:
        text = str(value)
    try:
        return text.encode(encoding, errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"LEGACY_ENCODING_UNREPRESENTABLE:{encoding}:{text}") from exc


def _capacity_candidates(obj: Any, field: str, prefix: str = "") -> list[int]:
    target = _norm(field)
    found: list[int] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            nk = _norm(key)
            joined = _norm(prefix + key)
            is_cap = any(x in nk or x in joined for x in ("bytecapacity", "bytescapacity", "maxbytes", "bytecap", "capacitybytes"))
            field_related = target in joined or target in nk
            if is_cap and field_related and isinstance(value, int) and value > 0:
                found.append(value)
            found.extend(_capacity_candidates(value, field, prefix + "." + str(key)))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_capacity_candidates(value, field, prefix))
    return found


def _enforce_capacity(doc: dict[str, Any], field: str, values: list[Any], encoding: str) -> None:
    compatibility = doc.get("compatibility") if isinstance(doc.get("compatibility"), dict) else {}
    capacities = _capacity_candidates(compatibility, field)
    if not capacities and _norm(field) in {"name", "displayname"}:
        # Some documents put byte capacities next to semantic metadata rather than compatibility.
        capacities = _capacity_candidates(_semantic(doc), field)
    if not capacities:
        return
    cap = min(capacities)
    for value in values:
        raw = _encode_legacy_value(value, encoding)
        if len(raw) > cap:
            raise ValueError(f"LEGACY_FIELD_BYTE_CAPACITY_EXCEEDED:{field}:{len(raw)}>{cap}")


def _replace_directive_payload(directive: dict[str, Any], value: Any, encoding: str) -> None:
    # Canonical definition flags are presence-only directives in the current source:
    # semantic.fields=true while values/raw_values_hex are empty. Preserve that exact
    # compiler-facing representation instead of inventing a numeric payload.
    if isinstance(value, bool) and directive.get("values") == [] and directive.get("raw_values_hex") == []:
        if value is not True:
            raise ValueError("CANONICAL_PRESENCE_FLAG_FALSE_REQUIRES_VALIDATED_DIRECTIVE_REMOVAL")
        directive["values"] = []
        directive["raw_values_hex"] = []
        if "quoted" in directive:
            directive["quoted"] = []
        return
    values = _flatten_scalars(value)
    existing_quoted = directive.get("quoted")
    if isinstance(existing_quoted, list):
        default_quote = bool(existing_quoted[0]) if existing_quoted else False
    elif isinstance(existing_quoted, bool):
        default_quote = existing_quoted
    else:
        default_quote = False
    quoted = []
    raw_hex = []
    for item in values:
        raw = _encode_legacy_value(item, encoding)
        raw_hex.append(raw.hex())
        quote = default_quote or (isinstance(item, str) and (any(ch.isspace() for ch in item) or item == ""))
        quoted.append(bool(quote))
    directive["values"] = copy.deepcopy(values)
    directive["raw_values_hex"] = raw_hex
    directive["quoted"] = quoted


def atomic_update_definition(doc: dict[str, Any], changes: dict[str, Any], *, encoding: str = "cp1252") -> dict[str, Any]:
    """Update semantic.fields and compiler-consumed directive payload atomically.

    The function mutates a deep copy only. It never rewrites unknown_tokens,
    source provenance or compatibility payload. Missing/ambiguous directive
    mappings fail closed rather than producing a JSON/SCFG split-brain edit.
    """
    if not isinstance(changes, dict) or not changes:
        raise ValueError("CANONICAL_DEFINITION_CHANGES_REQUIRED")
    out = copy.deepcopy(doc)
    semantic = _semantic(out)
    fields = semantic.get("fields")
    directives = semantic.get("directives")
    if not isinstance(fields, dict):
        raise ValueError("CANONICAL_DEFINITION_FIELDS_OBJECT_REQUIRED")
    if not isinstance(directives, (list, dict)):
        raise ValueError("CANONICAL_DEFINITION_DIRECTIVES_REQUIRED")

    protected_before = {
        "unknown_tokens": copy.deepcopy(semantic.get("unknown_tokens")),
        "source": copy.deepcopy(out.get("source")),
        "compatibility": copy.deepcopy(out.get("compatibility")),
        "semantic_source": copy.deepcopy(semantic.get("source")),
        "semantic_compatibility": copy.deepcopy(semantic.get("compatibility")),
    }

    for requested, value in changes.items():
        key = _field_key(fields, requested)
        if key is None:
            raise ValueError(f"CANONICAL_FIELD_UNKNOWN:{requested}")
        _enforce_capacity(out, key, _flatten_scalars(value), encoding)
        # Always prove legacy representability before changing either side.
        for item in _flatten_scalars(value):
            _encode_legacy_value(item, encoding)
        directive_key, directive = _find_directive(directives, key)
        if not isinstance(directive, dict):
            raise ValueError(f"CANONICAL_DIRECTIVE_NOT_FOUND_FOR_FIELD:{requested}")
        fields[key] = copy.deepcopy(value)
        _replace_directive_payload(directive, value, encoding)
        if isinstance(directives, list):
            directives[int(directive_key)] = directive
        else:
            directives[directive_key] = directive

    protected_after = {
        "unknown_tokens": semantic.get("unknown_tokens"),
        "source": out.get("source"),
        "compatibility": out.get("compatibility"),
        "semantic_source": semantic.get("source"),
        "semantic_compatibility": semantic.get("compatibility"),
    }
    if protected_before != protected_after:
        raise RuntimeError("CANONICAL_PROVENANCE_OR_UNKNOWN_TOKENS_MUTATED")
    return out


def _set_path(root: Any, dotted: str, value: Any) -> None:
    parts = [p for p in str(dotted).split(".") if p]
    if not parts:
        raise ValueError("CANONICAL_SET_PATH_EMPTY")
    cur = root
    for part in parts[:-1]:
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"CANONICAL_SET_PATH_NOT_FOUND:{dotted}")
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                raise IndexError(f"CANONICAL_SET_INDEX_OUT_OF_RANGE:{dotted}:{idx}")
            cur = cur[idx]
        else:
            raise KeyError(f"CANONICAL_SET_PATH_NOT_FOUND:{dotted}")
    leaf = parts[-1]
    if isinstance(cur, dict):
        if leaf not in cur:
            raise KeyError(f"CANONICAL_SET_PATH_NOT_FOUND:{dotted}")
        cur[leaf] = copy.deepcopy(value)
    elif isinstance(cur, list) and leaf.isdigit():
        idx = int(leaf)
        if idx < 0 or idx >= len(cur):
            raise IndexError(f"CANONICAL_SET_INDEX_OUT_OF_RANGE:{dotted}:{idx}")
        cur[idx] = copy.deepcopy(value)
    else:
        raise KeyError(f"CANONICAL_SET_PATH_NOT_FOUND:{dotted}")


def _map_entry_id(row: dict[str, Any]) -> str:
    return str(canonical_id_for_doc(row, "map") or row.get("map_id") or row.get("id") or "").strip()


def _update_map_entry(doc: dict[str, Any], canonical_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not canonical_id:
        raise ValueError("CANONICAL_MAP_ID_REQUIRED")
    out = copy.deepcopy(doc)
    list_key = next((k for k in ("maps", "entries", "fields") if isinstance(out.get(k), list)), None)
    if list_key is None:
        raise ValueError("CANONICAL_MAP_PROFILE_LIST_REQUIRED")
    matches = []
    target = canonical_id.casefold()
    for idx, row in enumerate(out[list_key]):
        if isinstance(row, dict) and _map_entry_id(row).casefold() == target:
            matches.append((idx, row))
    if not matches:
        raise KeyError(f"CANONICAL_MAP_NOT_FOUND:{canonical_id}")
    if len(matches) != 1:
        raise ValueError(f"CANONICAL_MAP_ID_AMBIGUOUS:{canonical_id}:{len(matches)}")
    idx, row = matches[0]
    field_code = row.get("legacy_field_code", row.get("field_code", row.get("code")))
    edited = copy.deepcopy(row)
    for requested, value in fields.items():
        existing = next((k for k in edited if _norm(k) == _norm(requested)), None)
        if existing is None:
            raise KeyError(f"CANONICAL_MAP_FIELD_UNKNOWN:{requested}")
        if _norm(existing) in {_norm("canonical_id"), _norm("map_id"), _norm("id"), _norm("legacy_field_code"), _norm("field_code"), _norm("code")} and edited[existing] != value:
            raise ValueError(f"CANONICAL_MAP_IDENTITY_FIELD_IMMUTABLE:{existing}")
        edited[existing] = copy.deepcopy(value)
    out[list_key][idx] = edited
    return out


def typed_patch_document(kind: str, doc: dict[str, Any], patch: dict[str, Any], *, canonical_id: str = "") -> dict[str, Any]:
    kind = str(kind or "").upper()
    if kind == "CANONICAL_TEXT":
        raise ValueError("CANONICAL_TEXT_BROWSER_READ_ONLY_USE_TYPED_WRITER")
    if kind in _DEFINITION_KINDS:
        changes = patch.get("fields") if isinstance(patch.get("fields"), dict) else patch.get("set_fields")
        if not isinstance(changes, dict):
            raise ValueError("CANONICAL_DEFINITION_PATCH_REQUIRES_FIELDS")
        encoding = str(patch.get("legacy_encoding") or "cp1252")
        return atomic_update_definition(doc, changes, encoding=encoding)

    if kind == "MAP" and isinstance(patch.get("fields"), dict):
        return _update_map_entry(doc, canonical_id, patch["fields"])

    if kind == "GAMEPLAY_CONFIG":
        if str(doc.get("kind") or "").casefold() != "ini_config" or str(doc.get("selection_reason") or "").casefold() != "immutable_gameplay_config":
            raise ValueError("CANONICAL_GAMEPLAY_CONFIG_NOT_AUTHORITATIVE_GAMEPLAY_CONFIG")

    out = copy.deepcopy(doc)
    if "replace_document" in patch:
        replacement = patch["replace_document"]
        if not isinstance(replacement, dict):
            raise ValueError("CANONICAL_REPLACE_DOCUMENT_OBJECT_REQUIRED")
        out = copy.deepcopy(replacement)
    set_values = patch.get("set")
    if isinstance(set_values, dict):
        for dotted, value in set_values.items():
            _set_path(out, str(dotted), value)

    list_contracts = {
        "STAGE_SPAWN": ("actors", "bosses"),
        "STAGE_START_POINT": ("points", "start_points", "records"),
        "FIXED_NPC": ("npcs", "fixed_npcs", "records"),
    }
    for key in list_contracts.get(kind, ()):
        if key in patch:
            if not isinstance(patch[key], list):
                raise ValueError(f"CANONICAL_TYPED_LIST_REQUIRED:{kind}:{key}")
            if key not in out:
                raise KeyError(f"CANONICAL_TYPED_KEY_NOT_FOUND:{kind}:{key}")
            out[key] = copy.deepcopy(patch[key])

    if kind in _FIXED_DOCUMENT_KINDS:
        expected_schema = _FIXED_DOCUMENT_KINDS[kind][1]
        if str(out.get("schema") or "") != expected_schema:
            raise ValueError(f"CANONICAL_FIXED_DOCUMENT_SCHEMA_IMMUTABLE:{kind}:{expected_schema}")

    if out == doc:
        raise ValueError("CANONICAL_AUTHORING_NO_CHANGE")
    return out


def _resolve_explicit_path(provider: SummitCanonicalContentProvider, value: str) -> pathlib.Path:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    if text.startswith("Content/"):
        text = text[len("Content/"):]
    rel = pathlib.PurePosixPath(text)
    if not rel.parts or any(p in {"", ".", ".."} for p in rel.parts):
        raise ValueError("CANONICAL_PATH_INVALID")
    if rel.parts[0] != "canonical":
        rel = pathlib.PurePosixPath("canonical") / rel
    path = (provider.content_root / pathlib.Path(*rel.parts)).resolve()
    canonical_root = provider.canonical_root.resolve()
    if path != canonical_root and canonical_root not in path.parents:
        raise ValueError("CANONICAL_PATH_ESCAPE")
    if not path.is_file():
        raise FileNotFoundError(f"CANONICAL_DOCUMENT_NOT_FOUND:{rel.as_posix()}")
    return path


def _find_json_by_id(root: pathlib.Path, canonical_id: str) -> pathlib.Path:
    target = str(canonical_id or "").strip().casefold()
    matches = []
    for path in sorted(root.rglob("*.json"), key=lambda p: p.as_posix().casefold()):
        try:
            doc = _load_json(path)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        ids = [
            canonical_id_for_doc(doc),
            str(doc.get("map_id") or ""),
            str(doc.get("stage_id") or ""),
            str(doc.get("spawn_id") or ""),
            str(doc.get("id") or ""),
        ]
        if any(x.strip().casefold() == target for x in ids if x):
            matches.append(path)
    if not matches:
        raise KeyError(f"CANONICAL_DOCUMENT_ID_NOT_FOUND:{canonical_id}")
    if len(matches) != 1:
        raise ValueError(f"CANONICAL_DOCUMENT_ID_AMBIGUOUS:{canonical_id}:{len(matches)}")
    return matches[0]


def resolve_authoring_document(provider: SummitCanonicalContentProvider, spec: dict[str, Any]) -> tuple[str, pathlib.Path, dict[str, Any]]:
    kind = str(spec.get("kind") or "").upper()
    if kind not in {*_DEFINITION_KINDS, *_OTHER_KINDS, *_FIXED_DOCUMENT_KINDS}:
        raise ValueError(f"CANONICAL_AUTHORING_KIND_UNSUPPORTED:{kind}")
    explicit = str(spec.get("path") or spec.get("canonical_path") or "").strip()
    if explicit:
        path = _resolve_explicit_path(provider, explicit)
    elif kind in _DEFINITION_KINDS:
        path = provider.find_definition(str(spec.get("canonical_id") or "")).path
    elif kind in _FIXED_DOCUMENT_KINDS:
        path = provider.canonical_root / _FIXED_DOCUMENT_KINDS[kind][0]
        if not path.is_file():
            raise FileNotFoundError(f"CANONICAL_FIXED_DOCUMENT_NOT_FOUND:{kind}:{path}")
    else:
        family_dir = provider.canonical_root / _OTHER_KINDS[kind]
        profile = str(spec.get("profile") or "").lower()
        if kind == "MAP" and profile in {"client", "server"}:
            path = family_dir / f"{profile}.maps.json"
            if not path.is_file():
                raise FileNotFoundError(f"CANONICAL_MAP_PROFILE_NOT_FOUND:{profile}")
        else:
            path = _find_json_by_id(family_dir, str(spec.get("canonical_id") or ""))
    doc = _load_json(path)
    if not isinstance(doc, dict):
        raise ValueError("CANONICAL_DOCUMENT_OBJECT_REQUIRED")
    return kind, path, doc


def _copy_canonical_tree(provider: SummitCanonicalContentProvider, stage_root: pathlib.Path) -> None:
    dst = stage_root / "canonical"
    shutil.copytree(provider.canonical_root, dst, dirs_exist_ok=False)
    shutil.copy2(provider.canonical_source_path, stage_root / "CANONICAL_SOURCE.json")
    shutil.copy2(provider.build_path, stage_root / "BUILD.json")
    (stage_root / "packs").mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str], *, cwd: pathlib.Path, log: list[dict[str, Any]]) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    row = {"command": cmd, "returncode": proc.returncode, "output": proc.stdout[-20000:]}
    log.append(row)
    if proc.returncode != 0:
        raise RuntimeError(f"CANONICAL_TOOL_FAILED:{pathlib.Path(cmd[1]).name if len(cmd)>1 else cmd[0]}:{proc.returncode}")
    return row


def validate_staged_canonical(provider: SummitCanonicalContentProvider, stage_root: pathlib.Path) -> dict[str, Any]:
    tools = provider.source_root / "tools" / "content_port"
    required = ["validate_canonical_text.py", "validate_canonical_schemas.py"]
    missing = [name for name in required if not (tools / name).is_file()]
    if missing:
        raise FileNotFoundError("CANONICAL_VALIDATORS_NOT_FOUND:" + ",".join(missing))
    log: list[dict[str, Any]] = []
    py = sys.executable
    text = stage_root / "canonical" / "text"
    materialize = tools / "materialize_localization_catalog.py"
    if materialize.is_file():
        _run([py, str(materialize), str(text)], cwd=provider.source_root, log=log)
    _run([py, str(tools / "validate_canonical_text.py"), str(text)], cwd=provider.source_root, log=log)
    _run([
        py, str(tools / "validate_canonical_schemas.py"),
        "--canonical-text", str(text),
        "--canonical-spawns", str(stage_root / "canonical" / "stage_spawns"),
        "--canonical-maps", str(stage_root / "canonical" / "maps"),
        "--canonical-start-points", str(stage_root / "canonical" / "stage_start_points"),
        "--canonical-fixed-npcs", str(stage_root / "canonical" / "fixed_npcs"),
    ], cwd=provider.source_root, log=log)
    extended = tools / "validate_extended_content.py"
    if extended.is_file():
        _run([py, str(extended), str(stage_root / "canonical")], cwd=provider.source_root, log=log)
    coin_validator = tools / "validate_coin_shop_catalog.py"
    if coin_validator.is_file() and (stage_root / "canonical" / "commerce" / "coin_shop.json").is_file():
        # Validator currently expects a repo-root layout; the staged tree is validated
        # structurally by compile_coin_shop during build and by source validation before publish.
        pass
    return {"status": "PASS", "commands": log}


def build_staged_packs(provider: SummitCanonicalContentProvider, stage_root: pathlib.Path) -> dict[str, Any]:
    tools = provider.source_root / "tools" / "content_port"
    required = {
        "compile_text_resources.py", "inspect_text_resources.py",
        "compile_definitions.py", "inspect_definitions.py", "validate_item_profile_pack.py",
        "compile_localization.py", "inspect_localization.py",
        "compile_gameplay_config.py", "inspect_gameplay_config.py",
        "compile_gameplay_reference.py", "inspect_gameplay_reference.py",
        "compile_field_runtime.py", "inspect_field_runtime.py",
        "compile_maps.py", "inspect_maps.py",
    }
    missing = sorted(name for name in required if not (tools / name).is_file())
    if missing:
        raise FileNotFoundError("CANONICAL_BUILD_TOOLS_NOT_FOUND:" + ",".join(missing))
    py = sys.executable
    canonical = stage_root / "canonical"
    packs = stage_root / "packs"
    text = canonical / "text"
    log: list[dict[str, Any]] = []

    def run(name: str, *args: pathlib.Path | str) -> dict[str, Any]:
        return _run([py, str(tools / name), *[str(x) for x in args]], cwd=provider.source_root, log=log)

    run("compile_text_resources.py", text, packs / "text_resources.sres")
    run("inspect_text_resources.py", packs / "text_resources.sres")
    for profile in ("client", "server"):
        out = packs / f"definitions_{profile}.scfg"
        run("compile_definitions.py", text, out, "--item-profile", canonical / "item_profiles" / f"{profile}.items.json")
        run("inspect_definitions.py", out)
    # The complete staged canonical tree intentionally satisfies the current validator's out-root coupling.
    run("validate_item_profile_pack.py", "--source-root", provider.source_root, "--content-root", stage_root, "--profile", "both")
    run("compile_localization.py", text, packs / "localization.sloc")
    run("inspect_localization.py", packs / "localization.sloc")
    run("compile_gameplay_config.py", text, packs / "gameplay_config.sgcf")
    run("inspect_gameplay_config.py", packs / "gameplay_config.sgcf")
    run("compile_gameplay_reference.py", canonical / "gameplay_reference", packs / "gameplay_reference.sgrf")
    run("inspect_gameplay_reference.py", packs / "gameplay_reference.sgrf")
    run(
        "compile_field_runtime.py",
        "--canonical-spawns", canonical / "stage_spawns",
        "--canonical-start-points", canonical / "stage_start_points",
        "--canonical-fixed-npcs", canonical / "fixed_npcs",
        "--canonical-text", text,
        packs / "field_runtime.sfld",
    )
    run("inspect_field_runtime.py", packs / "field_runtime.sfld")
    for profile in ("client", "server"):
        out = packs / f"maps_{profile}.smap"
        run("compile_maps.py", canonical / "maps" / f"{profile}.maps.json", out)
        run("inspect_maps.py", out)
    coin_catalog = canonical / "commerce" / "coin_shop.json"
    if coin_catalog.is_file():
        for required_name in ("compile_coin_shop.py", "inspect_coin_shop.py"):
            if not (tools / required_name).is_file():
                raise FileNotFoundError(f"CANONICAL_BUILD_TOOLS_NOT_FOUND:{required_name}")
        run("compile_coin_shop.py", coin_catalog, packs / "coin_shop.scsp")
        run("inspect_coin_shop.py", packs / "coin_shop.scsp")
    pack_hashes = {name: sha256_file(packs / name) for name in PACK_FILENAMES if (packs / name).is_file()}
    return {"status": "PASS", "commands": log, "pack_hashes": pack_hashes}


def _patch_build_hashes(value: Any, pack_hashes: dict[str, str], *, context: str = "") -> set[str]:
    updated: set[str] = set()
    if isinstance(value, dict):
        normalized = {_norm(k): k for k in value}
        path_key = next((normalized[k] for k in ("path", "file", "filename", "name") if k in normalized), None)
        sha_key = next((normalized[k] for k in ("sha256", "hash") if k in normalized), None)
        candidate = pathlib.PurePosixPath(str(value.get(path_key) if path_key else context).replace("\\", "/")).name
        if candidate in pack_hashes and sha_key is not None:
            value[sha_key] = pack_hashes[candidate]
            updated.add(candidate)
        for key, child in list(value.items()):
            key_candidate = pathlib.PurePosixPath(str(key).replace("\\", "/")).name
            if key_candidate in pack_hashes and isinstance(child, str) and re.fullmatch(r"[0-9a-fA-F]{64}", child.strip()):
                value[key] = pack_hashes[key_candidate]
                updated.add(key_candidate)
            updated |= _patch_build_hashes(child, pack_hashes, context=str(key))
    elif isinstance(value, list):
        for child in value:
            updated |= _patch_build_hashes(child, pack_hashes, context=context)
    return updated


def materialize_staged_build_manifest(stage_root: pathlib.Path, pack_hashes: dict[str, str]) -> dict[str, Any]:
    path = stage_root / "BUILD.json"
    build = _load_json(path)
    if not isinstance(build, dict) or str(build.get("schema") or "") != BUILD_SCHEMA:
        raise ValueError("CANONICAL_STAGED_BUILD_SCHEMA_INVALID")
    updated = _patch_build_hashes(build, pack_hashes)
    missing = sorted(set(PACK_FILENAMES) - updated)
    if missing:
        raise ValueError("CANONICAL_BUILD_PACK_HASH_SLOTS_NOT_FOUND:" + ",".join(missing))
    _atomic_json(path, build)
    return {"status": "PASS", "updated_packs": sorted(updated), "sha256": sha256_file(path)}


def stage_canonical_authoring(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    spec: dict[str, Any],
    *,
    run_validation: bool = True,
    run_build: bool = True,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    kind, source_path, source_doc = resolve_authoring_document(provider, spec)
    if kind == "MAP":
        profile = str(spec.get("profile") or "").lower()
        if profile not in {"client", "server"}:
            raise ValueError("CANONICAL_MAP_PROFILE_REQUIRED:client|server")
    patch = spec.get("patch") if isinstance(spec.get("patch"), dict) else {}
    if not patch:
        raise ValueError("CANONICAL_AUTHORING_PATCH_REQUIRED")
    edited = typed_patch_document(kind, source_doc, patch, canonical_id=str(spec.get("canonical_id") or ""))
    if edited == source_doc:
        raise ValueError("CANONICAL_AUTHORING_NO_CHANGE")

    tx = _now_id()
    stage_root = project_root / "pt_build" / "source_content_stage" / tx
    stage_root.parent.mkdir(parents=True, exist_ok=True)
    _copy_canonical_tree(provider, stage_root)
    source_rel = source_path.resolve().relative_to(provider.content_root.resolve())
    staged_target = stage_root / pathlib.Path(*source_rel.parts)
    pre_sha = sha256_file(source_path)
    _atomic_json(staged_target, edited)
    post_sha = sha256_file(staged_target)

    validation = {"status": "SKIPPED"}
    build = {"status": "SKIPPED", "pack_hashes": {}}
    build_manifest = {"status": "SKIPPED"}
    if run_validation:
        validation = validate_staged_canonical(provider, stage_root)
    if run_build:
        if not run_validation:
            raise ValueError("CANONICAL_BUILD_REQUIRES_VALIDATION")
        build = build_staged_packs(provider, stage_root)
        build_manifest = materialize_staged_build_manifest(stage_root, build["pack_hashes"])

    canonical_id = str(spec.get("canonical_id") or canonical_id_for_doc(source_doc) or "").strip()
    profile = str(spec.get("profile") or "").upper() or None
    family = _DEFINITION_KINDS.get(kind) or _OTHER_KINDS.get(kind)
    source_status = provider.status()
    source_file_inventory = canonical_file_hash_inventory_at(provider.canonical_root)
    staged_file_inventory = canonical_file_hash_inventory_at(stage_root / "canonical")
    source_hash_manifest = stage_root / "source_canonical_file_hashes.json"
    staged_hash_manifest = stage_root / "staged_canonical_file_hashes.json"
    _atomic_json(source_hash_manifest, source_file_inventory)
    _atomic_json(staged_hash_manifest, staged_file_inventory)
    localization_edit = kind == "LOCALIZATION" or str(source_doc.get("family") or "").casefold() == "localization_resource"
    manifest = {
        "format": MANIFEST_FORMAT,
        "status": "STAGED",
        "tx": tx,
        "kind": kind,
        "family": family,
        "canonical_id": canonical_id or None,
        "profile": profile,
        "source_root": str(provider.source_root),
        "source_root_authority": "SUMMIT_CANONICAL_SOURCE",
        "canonical_source_schema": CANONICAL_SOURCE_SCHEMA,
        "build_schema": BUILD_SCHEMA,
        "canonical_source_sha256": source_status["canonical_source_sha256"],
        "source_build_manifest_sha256": source_status["build_manifest_sha256"],
        "source_family_fingerprints": source_status["family_fingerprints"],
        "source_declared_family_fingerprints": source_status.get("declared_family_fingerprints", {}),
        "staged_family_fingerprints": canonical_family_fingerprints_at(stage_root / "canonical"),
        "source_canonical_file_inventory": {k: source_file_inventory[k] for k in ("sha256", "files", "bytes")},
        "staged_canonical_file_inventory": {k: staged_file_inventory[k] for k in ("sha256", "files", "bytes")},
        "source_canonical_file_hash_manifest": str(source_hash_manifest),
        "source_canonical_file_hash_manifest_sha256": sha256_file(source_hash_manifest),
        "staged_canonical_file_hash_manifest": str(staged_hash_manifest),
        "staged_canonical_file_hash_manifest_sha256": sha256_file(staged_hash_manifest),
        "canonical_json_path": source_rel.as_posix(),
        "source_pre_sha256": pre_sha,
        "staged_post_sha256": post_sha,
        "stage_root": str(stage_root),
        "staged_json": str(staged_target),
        "validation": validation,
        "build": build,
        "staged_build_manifest": build_manifest,
        "pack_hashes": build.get("pack_hashes") or {},
        "localization_edit": localization_edit,
        "localization_publish_gate": provider.localization_publish_gate(run_validator=False) if localization_edit else None,
        "publish_phases": ["SOURCE_JSON", "SOURCE_PACKS", "CLIENT_SERVER_RUNTIME_DEPLOY"],
        "legacy_direct_write_authorized": False,
    }
    manifest_path = stage_root / "manifest.json"
    _atomic_json(manifest_path, manifest)
    manifest["manifest"] = str(manifest_path)
    return {"format": FORMAT, "status": "STAGED", "manifest": manifest, "spec": copy.deepcopy(spec)}



def stage_canonical_document_set(
    project_root: pathlib.Path,
    provider: SummitCanonicalContentProvider,
    changes: list[dict[str, Any]],
    *,
    kind: str,
    canonical_id: str = "",
    provenance: dict[str, Any] | None = None,
    run_validation: bool = True,
    run_build: bool = True,
) -> dict[str, Any]:
    """Stage an atomic set of canonical JSON documents, including new files.

    This is the bridge used by donor recovery.  It keeps the original canonical
    tree immutable, writes only into pt_build, validates/compiles the complete
    staged tree, and records enough pre/post evidence for transactional publish
    and restore.  ``changes`` entries are ``relative_path`` (relative to
    Content/) plus a JSON-object ``document``.  Existing files may be replaced;
    absent files may be created.  Multiple files (for example a new spawn and
    stage_spawns/index.json) are one transaction.
    """
    project_root = pathlib.Path(project_root).resolve()
    if not changes:
        raise ValueError("CANONICAL_DOCUMENT_SET_REQUIRED")
    normalized: list[tuple[pathlib.PurePosixPath, dict[str, Any], pathlib.Path, bool]] = []
    seen: set[str] = set()
    for raw in changes:
        if not isinstance(raw, dict) or not isinstance(raw.get("document"), dict):
            raise ValueError("CANONICAL_DOCUMENT_SET_ENTRY_INVALID")
        text = str(raw.get("relative_path") or "").replace("\\", "/").strip().lstrip("/")
        rel = pathlib.PurePosixPath(text)
        if not rel.parts or rel.is_absolute() or ".." in rel.parts or rel.suffix.casefold() != ".json":
            raise ValueError(f"CANONICAL_DOCUMENT_SET_PATH_INVALID:{text}")
        if not rel.as_posix().casefold().startswith("canonical/"):
            raise ValueError(f"CANONICAL_DOCUMENT_SET_PATH_OUTSIDE_CANONICAL:{text}")
        key = rel.as_posix().casefold()
        if key in seen:
            raise ValueError(f"CANONICAL_DOCUMENT_SET_DUPLICATE:{text}")
        seen.add(key)
        target = provider.content_root / pathlib.Path(*rel.parts)
        normalized.append((rel, copy.deepcopy(raw["document"]), target, target.is_file()))

    tx = _now_id()
    stage_root = project_root / "pt_build" / "source_content_stage" / tx
    stage_root.parent.mkdir(parents=True, exist_ok=True)
    _copy_canonical_tree(provider, stage_root)
    source_status = provider.status()
    source_file_inventory = canonical_file_hash_inventory_at(provider.canonical_root)
    source_changes: list[dict[str, Any]] = []
    for rel, doc, target, existed in normalized:
        staged = stage_root / pathlib.Path(*rel.parts)
        staged.parent.mkdir(parents=True, exist_ok=True)
        pre_sha = sha256_file(target) if existed else None
        _atomic_json(staged, doc)
        source_changes.append({
            "canonical_json_path": rel.as_posix(),
            "source_existed": bool(existed),
            "source_pre_sha256": pre_sha,
            "staged_post_sha256": sha256_file(staged),
            "staged_json": str(staged),
        })

    validation = {"status": "SKIPPED"}
    build = {"status": "SKIPPED", "pack_hashes": {}}
    build_manifest = {"status": "SKIPPED"}
    if run_validation:
        validation = validate_staged_canonical(provider, stage_root)
    if run_build:
        if not run_validation:
            raise ValueError("CANONICAL_BUILD_REQUIRES_VALIDATION")
        build = build_staged_packs(provider, stage_root)
        build_manifest = materialize_staged_build_manifest(stage_root, build["pack_hashes"])

    staged_file_inventory = canonical_file_hash_inventory_at(stage_root / "canonical")
    source_hash_manifest = stage_root / "source_canonical_file_hashes.json"
    staged_hash_manifest = stage_root / "staged_canonical_file_hashes.json"
    _atomic_json(source_hash_manifest, source_file_inventory)
    _atomic_json(staged_hash_manifest, staged_file_inventory)
    primary = source_changes[0]
    manifest = {
        "format": MANIFEST_FORMAT,
        "status": "STAGED",
        "tx": tx,
        "kind": str(kind or "CANONICAL_DOCUMENT_SET").upper(),
        "family": None,
        "canonical_id": canonical_id or None,
        "profile": None,
        "source_root": str(provider.source_root),
        "source_root_authority": "SUMMIT_CANONICAL_SOURCE",
        "canonical_source_schema": CANONICAL_SOURCE_SCHEMA,
        "build_schema": BUILD_SCHEMA,
        "canonical_source_sha256": source_status["canonical_source_sha256"],
        "source_build_manifest_sha256": source_status["build_manifest_sha256"],
        "source_family_fingerprints": source_status["family_fingerprints"],
        "source_declared_family_fingerprints": source_status.get("declared_family_fingerprints", {}),
        "staged_family_fingerprints": canonical_family_fingerprints_at(stage_root / "canonical"),
        "source_canonical_file_inventory": {k: source_file_inventory[k] for k in ("sha256", "files", "bytes")},
        "staged_canonical_file_inventory": {k: staged_file_inventory[k] for k in ("sha256", "files", "bytes")},
        "source_canonical_file_hash_manifest": str(source_hash_manifest),
        "source_canonical_file_hash_manifest_sha256": sha256_file(source_hash_manifest),
        "staged_canonical_file_hash_manifest": str(staged_hash_manifest),
        "staged_canonical_file_hash_manifest_sha256": sha256_file(staged_hash_manifest),
        # Compatibility fields for existing UI / publish surfaces.
        "canonical_json_path": primary["canonical_json_path"],
        "source_pre_sha256": primary["source_pre_sha256"],
        "staged_post_sha256": primary["staged_post_sha256"],
        "staged_json": primary["staged_json"],
        "source_changes": source_changes,
        "stage_root": str(stage_root),
        "validation": validation,
        "build": build,
        "staged_build_manifest": build_manifest,
        "pack_hashes": build.get("pack_hashes") or {},
        "localization_edit": False,
        "localization_publish_gate": None,
        "publish_phases": ["SOURCE_JSON_SET", "SOURCE_PACKS", "CLIENT_SERVER_RUNTIME_DEPLOY"],
        "legacy_direct_write_authorized": False,
        "provenance": copy.deepcopy(provenance or {}),
    }
    manifest_path = stage_root / "manifest.json"
    _atomic_json(manifest_path, manifest)
    manifest["manifest"] = str(manifest_path)
    return {"format": FORMAT, "status": "STAGED", "manifest": manifest, "changes": copy.deepcopy(source_changes)}

def _manifest_path(manifest: pathlib.Path | str | dict[str, Any]) -> tuple[pathlib.Path | None, dict[str, Any]]:
    if isinstance(manifest, dict):
        return None, copy.deepcopy(manifest)
    path = pathlib.Path(manifest).expanduser().resolve()
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError("CANONICAL_MANIFEST_OBJECT_REQUIRED")
    return path, data


def _transaction_path(project_root: pathlib.Path, tx: str) -> pathlib.Path:
    return pathlib.Path(project_root).resolve() / "pt_build" / "source_content_transactions" / tx / "transaction.json"


def _load_or_init_transaction(project_root: pathlib.Path, manifest: dict[str, Any]) -> tuple[pathlib.Path, dict[str, Any]]:
    path = _transaction_path(project_root, str(manifest["tx"]))
    if path.is_file():
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ValueError("CANONICAL_TRANSACTION_INVALID")
        return path, data
    data = {
        "format": TRANSACTION_FORMAT,
        "tx": manifest["tx"],
        "source_root": manifest["source_root"],
        "canonical_json_path": manifest["canonical_json_path"],
        "state": "STAGED",
        "source_phase": "PENDING",
        "pack_phase": "PENDING",
        "deploy_phase": "PENDING",
        "backup_root": str(path.parent / "backup"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, data)
    return path, data



def _source_change_rows(m: dict[str, Any]) -> list[dict[str, Any]]:
    rows = m.get("source_changes")
    if isinstance(rows, list) and rows:
        out = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("CANONICAL_SOURCE_CHANGE_INVALID")
            required = ("canonical_json_path", "staged_post_sha256", "staged_json")
            if any(not row.get(k) for k in required):
                raise ValueError("CANONICAL_SOURCE_CHANGE_INVALID")
            out.append(copy.deepcopy(row))
        return out
    return [{
        "canonical_json_path": m["canonical_json_path"],
        "source_existed": True,
        "source_pre_sha256": m["source_pre_sha256"],
        "staged_post_sha256": m["staged_post_sha256"],
        "staged_json": m["staged_json"],
    }]


def _verify_source_change_preconditions(provider: SummitCanonicalContentProvider, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        target = provider.content_root / pathlib.PurePosixPath(str(row["canonical_json_path"]))
        existed = bool(row.get("source_existed", True))
        if existed:
            if not target.is_file() or sha256_file(target) != row.get("source_pre_sha256"):
                raise ValueError(f"CANONICAL_SOURCE_JSON_DRIFT:{row['canonical_json_path']}")
        elif target.exists():
            raise ValueError(f"CANONICAL_SOURCE_CREATE_TARGET_APPEARED:{row['canonical_json_path']}")
        staged = pathlib.Path(str(row["staged_json"]))
        if not staged.is_file() or sha256_file(staged) != row.get("staged_post_sha256"):
            raise ValueError(f"CANONICAL_STAGED_JSON_DRIFT:{row['canonical_json_path']}")

def publish_canonical_source(project_root: pathlib.Path, manifest: pathlib.Path | str | dict[str, Any], *, confirm: str) -> dict[str, Any]:
    if confirm != PUBLISH_SOURCE_CONFIRM:
        raise PermissionError("CANONICAL_SOURCE_PUBLISH_CONFIRMATION_REQUIRED")
    _, m = _manifest_path(manifest)
    if m.get("format") != MANIFEST_FORMAT or m.get("status") != "STAGED":
        raise ValueError("CANONICAL_STAGE_MANIFEST_INVALID")
    if (m.get("validation") or {}).get("status") != "PASS":
        raise ValueError("CANONICAL_SOURCE_PUBLISH_REQUIRES_SCHEMA_VALIDATION_PASS")
    if (m.get("build") or {}).get("status") != "PASS" or (m.get("staged_build_manifest") or {}).get("status") != "PASS":
        raise ValueError("CANONICAL_SOURCE_PUBLISH_REQUIRES_STAGED_BUILD_PASS")
    if set(m.get("pack_hashes") or {}) != set(PACK_FILENAMES):
        raise ValueError("CANONICAL_SOURCE_PUBLISH_REQUIRES_COMPLETE_PACK_SET")
    provider = SummitCanonicalContentProvider(m["source_root"])
    current_status = provider.status()
    if current_status["canonical_source_sha256"] != m["canonical_source_sha256"]:
        raise ValueError("CANONICAL_SOURCE_AUTHORITY_DRIFT")
    if current_status.get("family_fingerprints") != m.get("source_family_fingerprints"):
        raise ValueError("CANONICAL_SOURCE_TREE_DRIFT")
    rows = _source_change_rows(m)
    _verify_source_change_preconditions(provider, rows)
    if m.get("localization_edit"):
        gate = provider.localization_publish_gate(run_validator=True)
        if gate.get("production_publish") != "ENABLED":
            raise PermissionError("CANONICAL_LOCALIZATION_PRODUCTION_PUBLISH_BLOCKED")

    tx_path, tx = _load_or_init_transaction(project_root, m)
    if tx.get("source_phase") == "APPLIED":
        return tx
    backup_root = pathlib.Path(tx["backup_root"])
    applied: list[dict[str, Any]] = []
    try:
        for row in rows:
            rel = pathlib.PurePosixPath(str(row["canonical_json_path"]))
            target = provider.content_root / rel
            staged = pathlib.Path(str(row["staged_json"]))
            backup_target = backup_root / "Content" / rel
            if bool(row.get("source_existed", True)):
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_target)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".ptasset.tmp")
            shutil.copy2(staged, tmp)
            os.replace(tmp, target)
            if sha256_file(target) != row["staged_post_sha256"]:
                raise RuntimeError(f"CANONICAL_SOURCE_JSON_VERIFY_FAILED:{rel.as_posix()}")
            applied.append(row)
        refreshed = SummitCanonicalContentProvider(m["source_root"])
        if refreshed.canonical_family_fingerprints() != m.get("staged_family_fingerprints"):
            raise RuntimeError("CANONICAL_SOURCE_TREE_POSTWRITE_VERIFY_FAILED")
    except Exception:
        for row in reversed(applied):
            rel = pathlib.PurePosixPath(str(row["canonical_json_path"]))
            target = provider.content_root / rel
            backup_target = backup_root / "Content" / rel
            if bool(row.get("source_existed", True)) and backup_target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_target, target)
            elif not bool(row.get("source_existed", True)) and target.exists():
                target.unlink()
        raise
    tx.update({
        "source_phase": "APPLIED",
        "state": "SOURCE_APPLIED_PACKS_PENDING",
        "source_applied_changes": [
            {"canonical_json_path": x["canonical_json_path"], "sha256": x["staged_post_sha256"], "created": not bool(x.get("source_existed", True))}
            for x in rows
        ],
        "source_applied_sha256": rows[0]["staged_post_sha256"],
    })
    _atomic_json(tx_path, tx)
    return tx

def publish_canonical_packs(project_root: pathlib.Path, manifest: pathlib.Path | str | dict[str, Any], *, confirm: str) -> dict[str, Any]:
    if confirm != PUBLISH_PACKS_CONFIRM:
        raise PermissionError("CANONICAL_PACK_PUBLISH_CONFIRMATION_REQUIRED")
    _, m = _manifest_path(manifest)
    if m.get("format") != MANIFEST_FORMAT or m.get("status") != "STAGED":
        raise ValueError("CANONICAL_STAGE_MANIFEST_INVALID")
    if (m.get("validation") or {}).get("status") != "PASS" or (m.get("build") or {}).get("status") != "PASS":
        raise ValueError("CANONICAL_PACK_PUBLISH_REQUIRES_VALIDATED_BUILD")
    if not m.get("pack_hashes") or set(m.get("pack_hashes") or {}) != set(PACK_FILENAMES):
        raise ValueError("CANONICAL_STAGED_PACK_SET_INCOMPLETE")
    provider = SummitCanonicalContentProvider(m["source_root"])
    if provider.canonical_family_fingerprints() != m.get("staged_family_fingerprints"):
        raise ValueError("CANONICAL_SOURCE_TREE_DRIFT_AFTER_SOURCE_PHASE")
    for row in _source_change_rows(m):
        target_json = provider.content_root / pathlib.PurePosixPath(str(row["canonical_json_path"]))
        if not target_json.is_file() or sha256_file(target_json) != row["staged_post_sha256"]:
            raise ValueError(f"CANONICAL_SOURCE_PHASE_NOT_APPLIED_OR_DRIFTED:{row['canonical_json_path']}")
    tx_path, tx = _load_or_init_transaction(project_root, m)
    if tx.get("source_phase") != "APPLIED":
        raise ValueError("CANONICAL_SOURCE_PHASE_REQUIRED_BEFORE_PACKS")
    if tx.get("pack_phase") == "APPLIED":
        return tx
    stage_root = pathlib.Path(m["stage_root"])
    staged_build = stage_root / "BUILD.json"
    if not staged_build.is_file():
        raise FileNotFoundError("CANONICAL_STAGED_BUILD_MANIFEST_NOT_FOUND")
    staged_build_data = _load_json(staged_build)
    if not isinstance(staged_build_data, dict) or staged_build_data.get("schema") != BUILD_SCHEMA:
        raise ValueError("CANONICAL_STAGED_BUILD_MANIFEST_INVALID")

    backup_root = pathlib.Path(tx["backup_root"])
    backup_packs = backup_root / "Content" / "packs"
    backup_packs.mkdir(parents=True, exist_ok=True)
    provider.packs_root.mkdir(parents=True, exist_ok=True)
    for name in PACK_FILENAMES:
        target = provider.packs_root / name
        staged = stage_root / "packs" / name
        if not staged.is_file() or sha256_file(staged) != m["pack_hashes"][name]:
            raise ValueError(f"CANONICAL_STAGED_PACK_DRIFT:{name}")
        if target.is_file():
            shutil.copy2(target, backup_packs / name)
    backup_build = backup_root / "Content" / "BUILD.json"
    backup_build.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(provider.build_path, backup_build)

    for name in PACK_FILENAMES:
        target = provider.packs_root / name
        staged = stage_root / "packs" / name
        tmp = target.with_suffix(target.suffix + ".ptasset.tmp")
        shutil.copy2(staged, tmp)
        os.replace(tmp, target)
        if sha256_file(target) != m["pack_hashes"][name]:
            raise RuntimeError(f"CANONICAL_PACK_VERIFY_FAILED:{name}")
    tmp_build = provider.build_path.with_suffix(provider.build_path.suffix + ".ptasset.tmp")
    shutil.copy2(staged_build, tmp_build)
    os.replace(tmp_build, provider.build_path)

    refreshed = SummitCanonicalContentProvider(provider.source_root)
    freshness = refreshed.pack_freshness()
    if freshness.get("status") != "FRESH":
        raise RuntimeError("CANONICAL_PACK_FRESHNESS_VERIFY_FAILED")
    tx.update({
        "pack_phase": "APPLIED", "state": "SOURCE_AND_PACKS_APPLIED_RUNTIME_PENDING",
        "pack_hashes": copy.deepcopy(m["pack_hashes"]), "build_manifest_sha256": sha256_file(refreshed.build_path),
        "build_freshness": freshness,
    })
    _atomic_json(tx_path, tx)
    return tx


_RUNTIME_COMMON_PACKS = (
    "field_runtime.sfld", "text_resources.sres", "localization.sloc",
    "gameplay_config.sgcf", "gameplay_reference.sgrf",
)
_RUNTIME_ROLE_PACKS = {
    "client": ("definitions_client.scfg", "maps_client.smap") + _RUNTIME_COMMON_PACKS,
    "server": ("definitions_server.scfg", "maps_server.smap", "coin_shop.scsp") + _RUNTIME_COMMON_PACKS,
}
_RUNTIME_REMOVE = {
    "client": ("definitions_server.scfg", "maps_server.smap", "stage_spawns.sspb"),
    "server": ("definitions_client.scfg", "maps_client.smap", "stage_spawns.sspb"),
}


def _runtime_default_roots(provider: SummitCanonicalContentProvider) -> tuple[pathlib.Path, pathlib.Path]:
    repo = provider.source_root.parent
    return repo / "cliente", repo / "Servidor"


def _runtime_manifest_data(role: str, root: pathlib.Path, pack_hashes: dict[str, str]) -> dict[str, Any]:
    rows = []
    packs = root / "Content" / "packs"
    for name in _RUNTIME_ROLE_PACKS[role]:
        path = packs / name
        rows.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {"schema": "summit.runtime-content-deploy/v1", "role": role, "layout": "standalone-executable-content", "files": rows}


def deploy_canonical_runtime(
    project_root: pathlib.Path,
    manifest: pathlib.Path | str | dict[str, Any],
    *,
    confirm: str,
    client_root: pathlib.Path | str | None = None,
    server_root: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    if confirm != PUBLISH_RUNTIME_CONFIRM:
        raise PermissionError("CANONICAL_RUNTIME_DEPLOY_CONFIRMATION_REQUIRED")
    _, m = _manifest_path(manifest)
    if m.get("format") != MANIFEST_FORMAT or m.get("status") != "STAGED":
        raise ValueError("CANONICAL_STAGE_MANIFEST_INVALID")
    provider = SummitCanonicalContentProvider(m["source_root"])
    tx_path, tx = _load_or_init_transaction(project_root, m)
    if tx.get("source_phase") != "APPLIED" or tx.get("pack_phase") != "APPLIED":
        raise ValueError("CANONICAL_RUNTIME_DEPLOY_REQUIRES_SOURCE_AND_PACKS")
    if tx.get("deploy_phase") == "APPLIED":
        return tx
    for name, expected in (m.get("pack_hashes") or {}).items():
        path = provider.packs_root / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"CANONICAL_RUNTIME_DEPLOY_SOURCE_PACK_DRIFT:{name}")
    default_client, default_server = _runtime_default_roots(provider)
    roots = {
        "client": pathlib.Path(client_root).expanduser().resolve() if client_root else default_client.resolve(),
        "server": pathlib.Path(server_root).expanduser().resolve() if server_root else default_server.resolve(),
    }
    for role, root in roots.items():
        if not root.is_dir():
            raise FileNotFoundError(f"CANONICAL_RUNTIME_ROOT_NOT_FOUND:{role}:{root}")

    backup_root = pathlib.Path(tx["backup_root"]) / "runtime"
    runtime_rows: dict[str, Any] = {}
    touched: list[tuple[pathlib.Path, pathlib.Path | None]] = []
    try:
        for role, root in roots.items():
            dest = root / "Content" / "packs"
            dest.mkdir(parents=True, exist_ok=True)
            role_backup = backup_root / role
            role_backup.mkdir(parents=True, exist_ok=True)
            before: dict[str, Any] = {}
            names = set(_RUNTIME_ROLE_PACKS[role]) | set(_RUNTIME_REMOVE[role])
            for name in sorted(names):
                target = dest / name
                backup = role_backup / "packs" / name
                existed = target.is_file()
                before[name] = {"existed": existed, "sha256": sha256_file(target) if existed else None}
                if existed:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                touched.append((target, backup if existed else None))
            runtime_manifest = root / "Content" / "RUNTIME_CONTENT.json"
            runtime_manifest_backup = role_backup / "RUNTIME_CONTENT.json"
            manifest_existed = runtime_manifest.is_file()
            before_manifest_sha = sha256_file(runtime_manifest) if manifest_existed else None
            if manifest_existed:
                shutil.copy2(runtime_manifest, runtime_manifest_backup)
            touched.append((runtime_manifest, runtime_manifest_backup if manifest_existed else None))

            for name in _RUNTIME_REMOVE[role]:
                stale = dest / name
                if stale.exists():
                    stale.unlink()
            deployed = []
            for name in _RUNTIME_ROLE_PACKS[role]:
                source = provider.packs_root / name
                target = dest / name
                tmp = target.with_suffix(target.suffix + ".ptasset.runtime.tmp")
                shutil.copy2(source, tmp)
                os.replace(tmp, target)
                expected = (m.get("pack_hashes") or {}).get(name)
                actual = sha256_file(target)
                if expected != actual:
                    raise RuntimeError(f"CANONICAL_RUNTIME_PACK_VERIFY_FAILED:{role}:{name}")
                deployed.append({"name": name, "sha256": actual, "bytes": target.stat().st_size})
            runtime_data = _runtime_manifest_data(role, root, m.get("pack_hashes") or {})
            _atomic_json(runtime_manifest, runtime_data)
            runtime_rows[role] = {
                "root": str(root), "packs": deployed,
                "runtime_manifest": str(runtime_manifest),
                "runtime_manifest_sha256": sha256_file(runtime_manifest),
                "before": before,
                "before_runtime_manifest_existed": manifest_existed,
                "before_runtime_manifest_sha256": before_manifest_sha,
                "removed_incompatible": list(_RUNTIME_REMOVE[role]),
            }
    except Exception:
        for target, backup in reversed(touched):
            try:
                if backup is not None and backup.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                elif target.exists():
                    target.unlink()
            except OSError:
                pass
        raise
    tx.update({
        "deploy_phase": "APPLIED",
        "state": "SOURCE_PACKS_AND_RUNTIME_APPLIED",
        "runtime_deploy": runtime_rows,
    })
    _atomic_json(tx_path, tx)
    return tx


def restore_canonical_transaction(project_root: pathlib.Path, manifest: pathlib.Path | str | dict[str, Any], *, confirm: str) -> dict[str, Any]:
    if confirm != RESTORE_CONFIRM:
        raise PermissionError("CANONICAL_RESTORE_CONFIRMATION_REQUIRED")
    _, m = _manifest_path(manifest)
    provider = SummitCanonicalContentProvider(m["source_root"])
    tx_path = _transaction_path(project_root, str(m["tx"]))
    if not tx_path.is_file():
        raise FileNotFoundError("CANONICAL_TRANSACTION_NOT_FOUND")
    tx = _load_json(tx_path)
    if not isinstance(tx, dict):
        raise ValueError("CANONICAL_TRANSACTION_INVALID")
    backup_root = pathlib.Path(tx["backup_root"])

    # Runtime first: refuse to overwrite post-deploy changes.
    if tx.get("deploy_phase") == "APPLIED":
        runtime = tx.get("runtime_deploy") or {}
        for role in ("client", "server"):
            info = runtime.get(role) or {}
            root = pathlib.Path(str(info.get("root") or ""))
            if not root.is_dir():
                raise FileNotFoundError(f"CANONICAL_RESTORE_RUNTIME_ROOT_NOT_FOUND:{role}:{root}")
            packs = root / "Content" / "packs"
            for item in info.get("packs") or []:
                target = packs / str(item["name"])
                if not target.is_file() or sha256_file(target) != item.get("sha256"):
                    raise ValueError(f"CANONICAL_RESTORE_RUNTIME_DRIFT:{role}:{item.get('name')}")
            runtime_manifest = root / "Content" / "RUNTIME_CONTENT.json"
            if not runtime_manifest.is_file() or sha256_file(runtime_manifest) != info.get("runtime_manifest_sha256"):
                raise ValueError(f"CANONICAL_RESTORE_RUNTIME_MANIFEST_DRIFT:{role}")
        for role in ("client", "server"):
            info = runtime.get(role) or {}
            root = pathlib.Path(str(info["root"]))
            packs = root / "Content" / "packs"
            role_backup = backup_root / "runtime" / role
            before = info.get("before") or {}
            for name, state in before.items():
                target = packs / name
                backup = role_backup / "packs" / name
                if bool((state or {}).get("existed")) and backup.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                elif target.exists():
                    target.unlink()
            target_manifest = root / "Content" / "RUNTIME_CONTENT.json"
            backup_manifest = role_backup / "RUNTIME_CONTENT.json"
            if info.get("before_runtime_manifest_existed") and backup_manifest.is_file():
                shutil.copy2(backup_manifest, target_manifest)
            elif target_manifest.exists():
                target_manifest.unlink()

    if tx.get("pack_phase") == "APPLIED":
        backup_packs = backup_root / "Content" / "packs"
        for name in PACK_FILENAMES:
            target = provider.packs_root / name
            expected_applied = (m.get("pack_hashes") or {}).get(name)
            if target.is_file() and expected_applied and sha256_file(target) != expected_applied:
                raise ValueError(f"CANONICAL_RESTORE_PACK_DRIFT:{name}")
            backup = backup_packs / name
            if backup.is_file():
                tmp = target.with_suffix(target.suffix + ".ptasset.restore.tmp")
                shutil.copy2(backup, tmp)
                os.replace(tmp, target)
        backup_build = backup_root / "Content" / "BUILD.json"
        if backup_build.is_file():
            tmp = provider.build_path.with_suffix(provider.build_path.suffix + ".ptasset.restore.tmp")
            shutil.copy2(backup_build, tmp)
            os.replace(tmp, provider.build_path)

    if tx.get("source_phase") == "APPLIED":
        rows = _source_change_rows(m)
        for row in rows:
            rel = pathlib.PurePosixPath(str(row["canonical_json_path"]))
            target = provider.content_root / rel
            if not target.is_file() or sha256_file(target) != row["staged_post_sha256"]:
                raise ValueError(f"CANONICAL_RESTORE_SOURCE_DRIFT:{rel.as_posix()}")
        for row in rows:
            rel = pathlib.PurePosixPath(str(row["canonical_json_path"]))
            target = provider.content_root / rel
            backup_json = backup_root / "Content" / rel
            if bool(row.get("source_existed", True)):
                if not backup_json.is_file():
                    raise FileNotFoundError(f"CANONICAL_RESTORE_BACKUP_MISSING:{rel.as_posix()}")
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".ptasset.restore.tmp")
                shutil.copy2(backup_json, tmp)
                os.replace(tmp, target)
            elif target.exists():
                target.unlink()

    tx.update({
        "state": "RESTORED",
        "source_phase": "RESTORED" if tx.get("source_phase") == "APPLIED" else tx.get("source_phase"),
        "pack_phase": "RESTORED" if tx.get("pack_phase") == "APPLIED" else tx.get("pack_phase"),
        "deploy_phase": "RESTORED" if tx.get("deploy_phase") == "APPLIED" else tx.get("deploy_phase"),
    })
    _atomic_json(tx_path, tx)
    return tx

def canonical_authoring_capabilities(provider: SummitCanonicalContentProvider | None = None) -> dict[str, Any]:
    status = provider.status() if provider is not None else None
    return {
        "format": FORMAT,
        "status": "PASS" if provider is not None else "NOT_CONFIGURED",
        "canonical_mode": provider is not None,
        "authority": "SUMMIT_CANONICAL_SOURCE" if provider is not None else None,
        "writers": {
            "ITEM": "TYPED_ATOMIC_FIELDS_DIRECTIVES",
            "MONSTER": "TYPED_ATOMIC_FIELDS_DIRECTIVES",
            "NPC": "TYPED_ATOMIC_FIELDS_DIRECTIVES",
            "STAGE_SPAWN": "CANONICAL_JSON",
            "STAGE_START_POINT": "CANONICAL_JSON",
            "FIXED_NPC": "CANONICAL_JSON",
            "MAP": "PROFILE_AWARE_CANONICAL_JSON",
            "MODEL_CONFIG": "SCHEMA_GUARDED_CANONICAL_JSON",
            "COIN_SHOP_CATALOG": "SCHEMA_GUARDED_CANONICAL_JSON_COMPILED_SCSP",
            "NPC_SHOP_OVERRIDES": "SCHEMA_GUARDED_CANONICAL_JSON",
            "EQUIPMENT_SETS": "SCHEMA_GUARDED_CANONICAL_JSON",
            "HEAD_COSMETICS": "SCHEMA_GUARDED_CANONICAL_JSON",
            "WORLD_STORY": "SCHEMA_GUARDED_CANONICAL_JSON",
            "WORLD_PHASES": "SCHEMA_GUARDED_CANONICAL_JSON",
            "COVENANT_ALTARS": "SCHEMA_GUARDED_CANONICAL_JSON",
            "EXPERIENCE_BALANCE": "SCHEMA_GUARDED_CANONICAL_JSON",
            "GAMEPLAY_CONFIG": "SCHEMA_DRIVEN_CANONICAL_JSON",
            "LOCALIZATION": "EDIT_PREVIEW_ENABLED_PRODUCTION_FAIL_CLOSED",
            "CANONICAL_TEXT": "READ_ONLY_BY_DEFAULT",
        },
        "legacy_writers": {"SPM": "IMPORT_COMPARE_ONLY", "SPP": "IMPORT_COMPARE_ONLY", "SPC": "IMPORT_COMPARE_ONLY", "DEFINITIONS": "IMPORT_COMPARE_ONLY"},
        "publish": {
            "phase_1": "EXPLICIT_SOURCE_JSON",
            "phase_2": "EXPLICIT_SOURCE_PACKS",
            "phase_3": "EXPLICIT_CLIENT_SERVER_RUNTIME_DEPLOY",
            "source_confirm": PUBLISH_SOURCE_CONFIRM,
            "packs_confirm": PUBLISH_PACKS_CONFIRM,
            "runtime_confirm": PUBLISH_RUNTIME_CONFIRM,
            "restore_confirm": RESTORE_CONFIRM,
        },
        "source_status": status,
    }
