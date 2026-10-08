from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Any

FORMAT = "PT_LEGACY_AUTHORING_NAME_CATALOG_V1"
CONTRACT_FILE = "priston_asset_name_map_v1.json"


def _contract_path() -> pathlib.Path:
    return pathlib.Path(__file__).with_name("contracts") / CONTRACT_FILE


def _norm_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _server_logical_path(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not text:
        return None
    low = text.casefold()
    if low.startswith("servidor/"):
        text = text[len("Servidor/") :]
    if text.casefold().startswith("server/"):
        text = text[len("server/") :]
    return text or None


def _spawn_logical_path(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not text:
        return None
    marker = "spawns/"
    pos = text.casefold().rfind(marker)
    if pos >= 0:
        text = text[pos + len(marker) :]
    if text.casefold().endswith(".json"):
        text = text[:-5]
    return _server_logical_path(text)


def _field_base_from_stage_asset(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return None
    base = pathlib.PurePosixPath(text).name
    return base or None


def _field_subtype_path(spm_path: str | None, suffix: str) -> str | None:
    if not spm_path:
        return None
    p = pathlib.PurePosixPath(spm_path)
    if p.suffix.casefold() != ".spm":
        return None
    return p.with_suffix(suffix).as_posix()


@lru_cache(maxsize=1)
def load_name_catalog() -> dict[str, Any]:
    path = _contract_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"metadata", "items", "mobs", "npcs", "maps", "spawn_stages", "ambiguous", "master_1x1"}
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"LEGACY_NAME_CATALOG_MISSING_KEYS:{','.join(missing)}")
    counts = data.get("metadata", {}).get("counts") or {}
    expected = {
        "items": len(data.get("items") or []),
        "mobs": len(data.get("mobs") or []),
        "npcs": len(data.get("npcs") or []),
        "maps": len(data.get("maps") or []),
        "spawn_stages": len(data.get("spawn_stages") or []),
        "ambiguous_visible_names": len(data.get("ambiguous") or []),
        "unique_1x1": len(data.get("master_1x1") or []),
    }
    for key, actual in expected.items():
        declared = counts.get(key)
        if declared is not None and int(declared) != int(actual):
            raise ValueError(f"LEGACY_NAME_CATALOG_COUNT_MISMATCH:{key}:{declared}:{actual}")
    return data


def _ambiguous_keys(data: dict[str, Any]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in data.get("ambiguous") or []:
        out.add((str(row.get("category") or "").casefold(), _norm_text(row.get("display_name"))))
    return out


def _semantic_item_rows(data: dict[str, Any], ambiguous: set[tuple[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in data.get("items") or []:
        code = str(row.get("code") or row.get("internal_name") or "").strip()
        canonical_id = str(row.get("canonical_id") or "").strip()
        display_name = str(row.get("display_name") or code or canonical_id).strip()
        logical = _server_logical_path(row.get("definition_file"))
        out.append({
            "category": "ITEM",
            "canonical_id": canonical_id,
            "display_name": display_name,
            "internal_name": str(row.get("internal_name") or code).strip(),
            "code": code,
            "logical_path": logical,
            "linked_asset": row.get("linked_asset"),
            "level": row.get("level"),
            "in_server_profile": row.get("in_server_profile"),
            "in_client_profile": row.get("in_client_profile"),
            "localization_quality": row.get("localization_quality"),
            "confidence": row.get("confidence"),
            "method": row.get("method"),
            "source": row.get("source"),
            "source_url": row.get("source_url"),
            "visible_name_ambiguous": ("item", _norm_text(display_name)) in ambiguous,
            "display": f"{display_name} — {code} — {canonical_id}",
        })
    return out


def _semantic_entity_rows(data: dict[str, Any], source_key: str, category: str, ambiguous: set[tuple[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ambiguous_category = "mob" if category == "MONSTER" else "npc"
    for row in data.get(source_key) or []:
        canonical_id = str(row.get("canonical_id") or "").strip()
        internal = str(row.get("internal_name") or "").strip()
        display_name = str(row.get("display_name") or internal or canonical_id).strip()
        out.append({
            "category": category,
            "canonical_id": canonical_id,
            "display_name": display_name,
            "internal_name": internal,
            "logical_path": _server_logical_path(row.get("definition_file")),
            "model_file": row.get("model_file"),
            "linked_asset": row.get("linked_asset"),
            "level": row.get("level"),
            "effect_sound": row.get("effect_sound"),
            "english_name": row.get("english_name"),
            "localization_quality": row.get("localization_quality"),
            "confidence": row.get("confidence"),
            "method": row.get("method"),
            "source": row.get("source"),
            "source_url": row.get("source_url"),
            "visible_name_ambiguous": (ambiguous_category, _norm_text(display_name)) in ambiguous,
            "display": f"{display_name} — {internal} — {canonical_id}",
        })
    return out


def _spawn_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in data.get("spawn_stages") or []:
        spm = _spawn_logical_path(row.get("spawn_file"))
        internal = str(row.get("internal_name") or "").strip()
        display_name = str(row.get("display_name") or internal).strip()
        out.append({
            "category": "STAGE_SPAWN",
            "canonical_id": str(row.get("canonical_id") or "").strip(),
            "display_name": display_name,
            "internal_name": internal,
            "logical_spm": spm,
            "logical_spp": _field_subtype_path(spm, ".spp"),
            "logical_spc": _field_subtype_path(spm, ".spc"),
            "actor_count": row.get("actor_count"),
            "boss_count": row.get("boss_count"),
            "sample_mobs": row.get("sample_mobs"),
            "sample_bosses": row.get("sample_bosses"),
            "confidence": row.get("confidence"),
            "method": row.get("method"),
            "source": row.get("source"),
            "source_url": row.get("source_url"),
            "display": f"{display_name} — {internal} — {spm or 'sem SPM'}",
        })
    return out


def _map_rows(data: dict[str, Any], spawns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_internal: dict[str, list[dict[str, Any]]] = {}
    for row in spawns:
        by_internal.setdefault(_norm_text(row.get("internal_name")), []).append(row)
    out: list[dict[str, Any]] = []
    linked_spawn_ids: set[str] = set()
    for row in data.get("maps") or []:
        internal = str(row.get("internal_name") or "").strip()
        display_name = str(row.get("display_name") or internal).strip()
        stage_base = _field_base_from_stage_asset(row.get("stage_asset"))
        probes = [_norm_text(internal), _norm_text(stage_base)]
        matches: list[dict[str, Any]] = []
        for probe in probes:
            if probe and by_internal.get(probe):
                matches = by_internal[probe]
                break
        spawn = matches[0] if len(matches) == 1 else None
        if spawn:
            linked_spawn_ids.add(str(spawn.get("canonical_id") or ""))
        spm = spawn.get("logical_spm") if spawn else None
        if not spm and stage_base:
            spm = f"GameServer/Field/{stage_base}.spm"
        canonical_id = str(row.get("canonical_id") or "").strip()
        out.append({
            "category": "MAP",
            "canonical_id": canonical_id,
            "display_name": display_name,
            "internal_name": internal,
            "field_code": row.get("field_code"),
            "stage_asset": row.get("stage_asset"),
            "map_image_id": row.get("map_image_id"),
            "limit_level": row.get("limit_level"),
            "logical_spm": spm,
            "logical_spp": _field_subtype_path(spm, ".spp"),
            "logical_spc": _field_subtype_path(spm, ".spc"),
            "spawn_canonical_id": spawn.get("canonical_id") if spawn else None,
            "spawn_actor_count": spawn.get("actor_count") if spawn else None,
            "spawn_boss_count": spawn.get("boss_count") if spawn else None,
            "confidence": row.get("confidence"),
            "method": row.get("method"),
            "source": row.get("source"),
            "source_url": row.get("source_url"),
            "display": f"{display_name} — field {row.get('field_code')} — {internal}",
        })
    # Auxiliary spawn files still need to be selectable when they do not map to a public field.
    for spawn in spawns:
        sid = str(spawn.get("canonical_id") or "")
        if sid and sid in linked_spawn_ids:
            continue
        out.append({
            **spawn,
            "category": "MAP_AUX_STAGE",
            "field_code": None,
            "stage_asset": None,
            "map_image_id": None,
            "limit_level": None,
            "spawn_canonical_id": sid or None,
            "spawn_actor_count": spawn.get("actor_count"),
            "spawn_boss_count": spawn.get("boss_count"),
            "display": f"{spawn.get('display_name')} — stage auxiliar — {spawn.get('internal_name')}",
        })
    return out


@lru_cache(maxsize=1)
def authoring_name_catalog() -> dict[str, Any]:
    data = load_name_catalog()
    ambiguous = _ambiguous_keys(data)
    items = _semantic_item_rows(data, ambiguous)
    mobs = _semantic_entity_rows(data, "mobs", "MONSTER", ambiguous)
    npcs = _semantic_entity_rows(data, "npcs", "NPC", ambiguous)
    spawn_stages = _spawn_rows(data)
    maps = _map_rows(data, spawn_stages)
    by_id: dict[str, dict[str, Any]] = {}
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in [*items, *mobs, *npcs, *maps, *spawn_stages]:
        cid = str(row.get("canonical_id") or "").strip()
        if cid:
            by_id[cid.casefold()] = row
        for key in ("logical_path", "logical_spm", "logical_spp", "logical_spc"):
            path = str(row.get(key) or "").strip()
            if path:
                by_path.setdefault(path.casefold(), []).append(row)
    meta = data.get("metadata") or {}
    return {
        "format": FORMAT,
        "status": "PASS",
        "title": meta.get("title"),
        "generated_from": meta.get("generated_from"),
        "methodology": meta.get("methodology") or [],
        "important_correction": meta.get("important_correction"),
        "counts": meta.get("counts") or {},
        "items": items,
        "mobs": mobs,
        "npcs": npcs,
        "maps": maps,
        "spawn_stages": spawn_stages,
        "ambiguous": data.get("ambiguous") or [],
        "_by_id": by_id,
        "_by_path": by_path,
    }


def public_authoring_name_catalog() -> dict[str, Any]:
    data = authoring_name_catalog()
    return {k: v for k, v in data.items() if not k.startswith("_")}


def lookup_semantic_ref(canonical_id: str | None) -> dict[str, Any] | None:
    key = str(canonical_id or "").strip().casefold()
    if not key:
        return None
    row = authoring_name_catalog()["_by_id"].get(key)
    return dict(row) if row else None


def semantic_matches_for_path(logical_path: str | None) -> list[dict[str, Any]]:
    key = str(logical_path or "").replace("\\", "/").strip().casefold()
    if not key:
        return []
    return [dict(x) for x in authoring_name_catalog()["_by_path"].get(key, [])]


def semantic_monster_matches_for_model(model_file: str | None) -> list[dict[str, Any]]:
    """Return reverse-engineered Monster semantic rows for an exact model path.

    This is migration/alias evidence only; callers must still confirm that the
    referenced canonical entity exists in the live canonical source.  Exact
    model matching is intentionally fail-closed when multiple semantic rows
    share the same model.
    """
    key = str(model_file or "").replace("/", "\\").strip().casefold()
    if not key:
        return []
    return [
        dict(row)
        for row in authoring_name_catalog()["mobs"]
        if str(row.get("model_file") or "").replace("/", "\\").strip().casefold() == key
    ]


def semantic_binding_for_spec(kind: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    ref = spec.get("semantic_ref")
    if not isinstance(ref, dict):
        return None
    canonical_id = str(ref.get("canonical_id") or "").strip()
    if not canonical_id:
        raise ValueError("LEGACY_AUTHORING_SEMANTIC_REF_ID_REQUIRED")
    row = lookup_semantic_ref(canonical_id)
    if row is None:
        raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_REF_UNKNOWN:{canonical_id}")
    kind = str(kind or "").upper()
    allowed = {
        "ITEM": {"ITEM"},
        "MONSTER": {"MONSTER"},
        "NPC": {"NPC"},
        "SPM": {"MAP", "MAP_AUX_STAGE", "STAGE_SPAWN"},
        "SPP": {"MAP", "MAP_AUX_STAGE", "STAGE_SPAWN"},
        "SPC": {"MAP", "MAP_AUX_STAGE", "STAGE_SPAWN"},
    }.get(kind, set())
    if str(row.get("category") or "") not in allowed:
        raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_KIND_MISMATCH:{kind}:{row.get('category')}:{canonical_id}")
    subtype_key = {"SPM": "logical_spm", "SPP": "logical_spp", "SPC": "logical_spc"}.get(kind, "logical_path")
    expected_path = str(row.get(subtype_key) or "").replace("\\", "/").strip()
    actual_path = str(spec.get("path") or spec.get("logical_path") or "").replace("\\", "/").strip()
    if expected_path and actual_path and expected_path.casefold() != actual_path.casefold():
        raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_PATH_MISMATCH:{canonical_id}:{expected_path}:{actual_path}")
    if kind == "ITEM":
        expected_code = str(row.get("code") or "").strip()
        fields = spec.get("fields") if isinstance(spec.get("fields"), dict) else ((spec.get("payload") or {}).get("fields") if isinstance(spec.get("payload"), dict) else {})
        actual_code = str((fields or {}).get("code") or "").strip()
        if expected_code and actual_code and expected_code.casefold() != actual_code.casefold():
            raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_ITEM_CODE_MISMATCH:{canonical_id}:{expected_code}:{actual_code}")
    return {
        "catalog_format": FORMAT,
        "canonical_id": canonical_id,
        "category": row.get("category"),
        "display_name": row.get("display_name"),
        "internal_name": row.get("internal_name"),
        "logical_path": expected_path or actual_path or None,
        "confidence": row.get("confidence"),
        "method": row.get("method"),
        "visible_name_ambiguous": bool(row.get("visible_name_ambiguous")),
    }


def _semantic_related_ref_is_bound(kind: str, role: str, row: dict[str, Any], spec: dict[str, Any]) -> bool:
    payload = spec.get("payload") if isinstance(spec.get("payload"), dict) else {}
    patch = spec.get("patch") if isinstance(spec.get("patch"), dict) else {}
    if kind == "MONSTER" and role == "ITEM_REFERENCE":
        drops = payload.get("drops") if isinstance(payload.get("drops"), list) else patch.get("drops")
        drops = drops if isinstance(drops, list) else []
        codes = {str(code).strip().casefold() for d in drops if isinstance(d, dict) for code in (d.get("items") or [])}
        return str(row.get("code") or "").strip().casefold() in codes
    if kind == "NPC" and role == "ITEM_REFERENCE":
        shops = payload.get("shops") if isinstance(payload.get("shops"), dict) else patch.get("shops")
        shops = shops if isinstance(shops, dict) else {}
        codes = {str(code).strip().casefold() for values in shops.values() if isinstance(values, list) for code in values}
        return str(row.get("code") or "").strip().casefold() in codes
    if kind == "SPM" and role == "ACTOR":
        names: list[str] = []
        actors = payload.get("actors") if isinstance(payload.get("actors"), list) else []
        names.extend(str(x.get("name") or "") for x in actors if isinstance(x, dict))
        for key in ("name", "master", "slave"):
            if patch.get(key):
                names.append(str(patch.get(key)))
        expected = {_norm_text(row.get("display_name")), _norm_text(row.get("internal_name"))}
        return any(_norm_text(name) in expected for name in names if name)
    if kind == "SPC" and role == "FIXED_NPC":
        records = payload.get("records") if isinstance(payload.get("records"), list) else []
        if isinstance(patch.get("record"), dict):
            records = [*records, patch["record"]]
        expected_path = str(row.get("logical_path") or "").replace("\\", "/").casefold()
        expected_names = {_norm_text(row.get("display_name")), _norm_text(row.get("internal_name"))}
        for record in records:
            if not isinstance(record, dict):
                continue
            server_npc = str(record.get("server_npc") or "").replace("\\", "/").casefold()
            if expected_path and server_npc == expected_path:
                return True
            if _norm_text(record.get("name")) in expected_names:
                return True
        return False
    return False


def semantic_related_bindings_for_spec(kind: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    refs = spec.get("semantic_related_refs") or []
    if not isinstance(refs, list):
        raise ValueError("LEGACY_AUTHORING_SEMANTIC_RELATED_REFS_MUST_BE_LIST")
    kind = str(kind or "").upper()
    allowed: dict[str, dict[str, set[str]]] = {
        "MONSTER": {"ITEM_REFERENCE": {"ITEM"}},
        "NPC": {"ITEM_REFERENCE": {"ITEM"}},
        "SPM": {"ACTOR": {"MONSTER"}},
        "SPC": {"FIXED_NPC": {"NPC"}},
    }
    rules = allowed.get(kind, {})
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError("LEGACY_AUTHORING_SEMANTIC_RELATED_REF_MUST_BE_OBJECT")
        role = str(ref.get("role") or "").strip().upper()
        canonical_id = str(ref.get("canonical_id") or "").strip()
        if not role or not canonical_id:
            raise ValueError("LEGACY_AUTHORING_SEMANTIC_RELATED_REF_FIELDS_REQUIRED")
        if role not in rules:
            raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_RELATED_ROLE_INVALID:{kind}:{role}")
        row = lookup_semantic_ref(canonical_id)
        if row is None:
            raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_REF_UNKNOWN:{canonical_id}")
        category = str(row.get("category") or "")
        if category not in rules[role]:
            raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_RELATED_KIND_MISMATCH:{kind}:{role}:{category}:{canonical_id}")
        if not _semantic_related_ref_is_bound(kind, role, row, spec):
            raise ValueError(f"LEGACY_AUTHORING_SEMANTIC_RELATED_REF_UNBOUND:{kind}:{role}:{canonical_id}")
        key = (role, canonical_id.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "catalog_format": FORMAT,
            "role": role,
            "canonical_id": canonical_id,
            "category": category,
            "display_name": row.get("display_name"),
            "internal_name": row.get("internal_name"),
            "runtime_code": row.get("code"),
            "logical_path": row.get("logical_path"),
            "model_file": row.get("model_file"),
            "confidence": row.get("confidence"),
            "visible_name_ambiguous": bool(row.get("visible_name_ambiguous")),
        })
    return out
