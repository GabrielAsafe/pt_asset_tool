from __future__ import annotations

import hashlib
import json
import math
import pathlib
import re
import struct
import time
from typing import Any, Callable

from .asset_contract_registry import get_contract, schema_for_contract, source_registry
from .model_cache_compiler import compile_model_cache
from .model062_static_compiler import compile_static_model062
from .model062_skeleton_compiler import compile_skeleton_model062
from .stage072_compiler import compile_stage072
from .legacy_management_contracts import classify_item_code
from .item_runtime_catalog import lookup_item_runtime

RECIPE_FORMAT = "PT_ASSET_RECIPE_V1"
PLAN_FORMAT = "PT_ASSET_COMPILER_PLAN_V1"
BUILD_FORMAT = "PT_ASSET_COMPILER_BUILD_V1"
BUNDLE_RECIPE_FORMAT = "PT_ASSET_BUNDLE_RECIPE_V1"
BUNDLE_PLAN_FORMAT = "PT_ASSET_BUNDLE_PLAN_V1"
BUNDLE_BUILD_FORMAT = "PT_ASSET_BUNDLE_BUILD_V1"
CURRENT_NPC_OPCODE = 0x70000000
LEGACY_NPC_OPCODE = 0x48470070
SPP_RECORD_COUNT = 200
SPP_RECORD_SIZE = 12
SPC_RECORD_COUNT = 100
SPC_RECORD_SIZE = 504

_TEXT_CONTRACTS = {
    "model.config.ini",
    "model.cache.inx",
    "effect.animation.ini",
    "effect.lua.dsl",
    "effect.particle.part",
    "ui.quest.msg",
    "ui.clan.msg",
    "event.bellatra.ini",
    "presentation.opening_field.txt",
    "render.sky.profile.txt",
    "ui.pet_messages.txt",
    "ui.party_quest_text.txt",
    "server.present_postbox.dat",
    "ui.autohelp.bundle",
    "client.opening_settings",
    "voice.launcher_config",
}
_SOURCE_STRUCTURED_TEXT_CONTRACTS = {"character.monster.inf", "character.npc.npc", "item.definition.txt"}
_OPERATIONAL_INI_CONTRACTS = {
    "client.game_config",
    "font.runtime_config",
    "server.systems_config",
    "server.exp_manager_config",
}
_CODE_BOUNDARY_CONTRACTS = {
    "character.player.visual",
    "item.definition.txt",
    "item.visual.bundle",
    "field.bundle",
    "audio.bgm",
    "audio.character_sound_bundle",
    "quest.existing_content_bundle",
}
_DIRECT_COMPILERS = {
    "model.smd.062",
    "model.smb.bone",
    "stage.smd.072",
    "texture.standard",
    "audio.wav",
    "field.spawn.spm",
    "field.startpoints.spp",
    "field.fixed_npc.spc",
    "ui.help.sin",
    "ui.fontimagepos.dat",
    "ui.map.stageinfo.dat",
    "event.bellatra.dat",
    "server.main_config",
    "server.skill_config",
    *_OPERATIONAL_INI_CONTRACTS,
    *_TEXT_CONTRACTS,
    *_SOURCE_STRUCTURED_TEXT_CONTRACTS,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    text = str(value or "").strip().replace("\\", "/").lstrip("/")
    rel = pathlib.PurePosixPath(text)
    if not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"INVALID_LOGICAL_PATH:{value}")
    return rel


def _safe_id(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return out[:100] or "asset"


def _runtime_sides(runtime: str) -> set[str]:
    return {x.strip().upper() for x in str(runtime or "").split(";") if x.strip()}


def _infer_side(contract: dict[str, Any], requested: str | None) -> str:
    side = str(requested or "").strip().upper()
    sides = _runtime_sides(str(contract.get("runtime") or "")) & {"CLIENT", "SERVER"}
    if side:
        if side not in {"CLIENT", "SERVER"}:
            raise ValueError("TARGET_SIDE_MUST_BE_CLIENT_OR_SERVER")
        if sides and side not in sides:
            raise ValueError(f"TARGET_SIDE_NOT_CONSUMED_BY_CONTRACT:{side}")
        return side
    if len(sides) == 1:
        return next(iter(sides))
    raise ValueError("TARGET_SIDE_REQUIRED_FOR_SHARED_CONTRACT")


def _allowed_suffixes(contract: dict[str, Any]) -> set[str]:
    values = []
    for raw in str(contract.get("extensions") or "").split(";"):
        raw = raw.strip().lower()
        if raw.startswith("."):
            values.append(raw)
    return set(values)


def _payload_text(payload: dict[str, Any]) -> str:
    if "text" in payload:
        return str(payload.get("text") or "")
    if isinstance(payload.get("lines"), list):
        return "\n".join(str(x) for x in payload["lines"])
    if isinstance(payload.get("sections"), dict):
        lines: list[str] = []
        for section, values in payload["sections"].items():
            if lines:
                lines.append("")
            lines.append(f"[{section}]")
            if not isinstance(values, dict):
                raise ValueError(f"INI_SECTION_MUST_BE_OBJECT:{section}")
            for key, value in values.items():
                lines.append(f"{key}={value}")
        return "\n".join(lines)
    raise ValueError("TEXT_PAYLOAD_REQUIRES_text_lines_OR_sections")


def _encode_text(text: str, payload: dict[str, Any], *, force_crlf: bool = False) -> tuple[bytes, dict[str, Any]]:
    encoding = str(payload.get("encoding") or "cp1252").strip().lower()
    if encoding not in {"cp1252", "cp949", "latin1", "utf-8", "utf-8-sig"}:
        raise ValueError(f"TEXT_ENCODING_NOT_ALLOWED:{encoding}")
    newline_name = "crlf" if force_crlf else str(payload.get("newline") or "crlf").strip().lower()
    if newline_name not in {"crlf", "lf"}:
        raise ValueError("TEXT_NEWLINE_MUST_BE_crlf_OR_lf")
    newline = "\r\n" if newline_name == "crlf" else "\n"
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    try:
        data = normalized.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"TEXT_NOT_ENCODABLE:{encoding}:{exc}") from exc
    return data, {"encoding": encoding, "newline": newline_name, "line_count": normalized.count(newline) + (1 if normalized else 0)}


def _compile_text(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    data, meta = _encode_text(_payload_text(payload), payload)
    max_bytes = int(payload.get("max_bytes") or 4 * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(f"TEXT_OUTPUT_TOO_LARGE:{len(data)}>{max_bytes}")
    meta.update({"writer": "TEXT", "size": len(data)})
    return data, meta


_MODEL_CONFIG_TOKENS = {
    "motion_file": "*동작파일",
    "motion_source": "*동작모음",
    "model_file": "*모양파일",
    "model_name": "*모양이름",
    "link_file": "*파일연결",
    "sub_motion_file": "*보조동작파일",
    "lod_high": "*정밀모양",
    "lod_default": "*보통모양",
    "lod_low": "*저질모양",
    "talk_link_file": "*표정파일연결",
    "talk_motion_file": "*표정파일",
    "talk_motion_source": "*표정모음",
}


def _quote_cfg(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("MODEL_CONFIG_EMPTY_VALUE")
    if '"' in text or "\r" in text or "\n" in text:
        raise ValueError("MODEL_CONFIG_VALUE_CONTAINS_FORBIDDEN_CHAR")
    return f'"{text}"' if any(ch.isspace() for ch in text) else text


def _model_config_path_value(value: Any, label: str) -> str:
    text = str(value or "").strip().replace("/", "\\")
    if not text:
        raise ValueError(f"MODEL_CONFIG_{label}_REQUIRED")
    raw = text.encode("cp949")
    if len(raw) >= 64:
        raise ValueError(f"MODEL_CONFIG_{label}_LOCAL_VALUE_EXCEEDS_63_BYTES")
    return text


def _model_motion_line(row: dict[str, Any], *, talk: bool = False) -> str:
    if not isinstance(row, dict):
        raise ValueError("MODEL_CONFIG_MOTION_OBJECT_REQUIRED")
    token = str(row.get("token") or "").strip()
    required_word = "표정" if talk else "동작"
    if not token.startswith("*") or required_word not in token:
        raise ValueError(f"MODEL_CONFIG_MOTION_TOKEN_INVALID:{token}")
    try:
        token.encode("cp949")
    except UnicodeEncodeError as exc:
        raise ValueError(f"MODEL_CONFIG_MOTION_TOKEN_NOT_CP949:{token}") from exc
    start = int(row.get("start"))
    end = int(row.get("end"))
    if start < 0 or end <= start:
        raise ValueError(f"MODEL_CONFIG_MOTION_FRAME_RANGE_INVALID:{token}:{start}:{end}")
    events = list(row.get("events") or [])
    if len(events) > 4:
        raise ValueError(f"MODEL_CONFIG_MOTION_EVENT_LIMIT_4:{token}")
    parts = [token, str(start), str(end)]
    for value in events:
        frame = int(value)
        if frame < start or frame > end:
            raise ValueError(f"MODEL_CONFIG_MOTION_EVENT_OUT_OF_RANGE:{token}:{frame}")
        parts.append(str(frame))
    repeat = bool(row.get("repeat", False))
    key = str(row.get("key") or "").strip()
    rate = row.get("rate")
    if key and (len(key) != 1 or not (32 <= ord(key) <= 0x7F)):
        raise ValueError(f"MODEL_CONFIG_MOTION_KEY_ASCII_ONE_CHAR_REQUIRED:{token}")
    if repeat:
        parts.append("반복")
    elif key:
        parts.append(key)
    elif rate is not None:
        # SetIniMotionInfo consumes one non-numeric token before it reads the
        # optional rate.  Do not invent a key or change repeat semantics.
        raise ValueError(f"MODEL_CONFIG_MOTION_RATE_REQUIRES_REPEAT_OR_KEY:{token}")
    if rate is not None:
        rate_i = int(rate)
        if not 0 <= rate_i <= 100:
            raise ValueError(f"MODEL_CONFIG_MOTION_RATE_OUT_OF_RANGE:{token}:{rate_i}")
        parts.append(f"({rate_i})")
    return " ".join(parts)


def _compile_model_config(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    lines: list[str] = []
    refs: list[dict[str, str]] = []

    def add_path(field: str, token_key: str, *, required: bool = False) -> None:
        value = payload.get(field)
        if value in {None, ""}:
            if required:
                raise ValueError(f"MODEL_CONFIG_{field.upper()}_REQUIRED")
            return
        clean = _model_config_path_value(value, field.upper())
        lines.append(f"{_MODEL_CONFIG_TOKENS[token_key]} {_quote_cfg(clean)}")
        refs.append({"role": field, "value": clean.replace("\\", "/")})

    add_path("motion_file", "motion_file")
    motion_sources = payload.get("motion_sources") or []
    if not isinstance(motion_sources, list) or len(motion_sources) > 128:
        raise ValueError("MODEL_CONFIG_MOTION_SOURCE_LIMIT_128")
    clean_motion_sources: list[str] = []
    for value in motion_sources:
        clean = _model_config_path_value(value, "MOTION_SOURCE")
        clean_motion_sources.append(clean)
        refs.append({"role": "motion_source", "value": clean.replace("\\", "/")})
    add_path("model_file", "model_file")
    if payload.get("model_name") not in {None, ""}:
        value = str(payload.get("model_name") or "").strip()
        if len(value.encode("cp949")) >= 64:
            raise ValueError("MODEL_CONFIG_MODEL_NAME_EXCEEDS_63_BYTES")
        lines.append(f"{_MODEL_CONFIG_TOKENS['model_name']} {_quote_cfg(value)}")
    add_path("link_file", "link_file")
    add_path("sub_motion_file", "sub_motion_file")

    lod = payload.get("lod") or {}
    if not isinstance(lod, dict):
        raise ValueError("MODEL_CONFIG_LOD_OBJECT_REQUIRED")
    for key, token_key in (("high", "lod_high"), ("default", "lod_default"), ("low", "lod_low")):
        values = lod.get(key) or []
        if not isinstance(values, list) or len(values) > 4:
            raise ValueError(f"MODEL_CONFIG_LOD_{key.upper()}_LIMIT_4")
        if values:
            encoded = []
            for value in values:
                name = str(value or "").strip()
                if not name or len(name.encode("cp949")) >= 16:
                    raise ValueError(f"MODEL_CONFIG_LOD_{key.upper()}_NAME_EXCEEDS_15_BYTES")
                encoded.append(_quote_cfg(name))
            lines.append(f"{_MODEL_CONFIG_TOKENS[token_key]} " + " ".join(encoded))

    motions = payload.get("motions") or []
    if not isinstance(motions, list) or len(motions) > 502:
        raise ValueError("MODEL_CONFIG_MOTION_LIMIT_502_AFTER_RESERVED_10")
    explicit_frames = any(isinstance(row, dict) and row.get("motion_frame") is not None for row in motions)
    emitted_sources = 0
    if not explicit_frames:
        for clean in clean_motion_sources:
            lines.append(f"{_MODEL_CONFIG_TOKENS['motion_source']} {_quote_cfg(clean)}")
        emitted_sources = len(clean_motion_sources)
    for row in motions:
        if not isinstance(row, dict):
            raise ValueError("MODEL_CONFIG_MOTION_OBJECT_REQUIRED")
        if explicit_frames:
            desired = int(row.get("motion_frame") if row.get("motion_frame") is not None else emitted_sources)
            if desired < emitted_sources:
                raise ValueError("MODEL_CONFIG_MOTION_FRAME_ORDER_MUST_BE_NONDECREASING")
            if desired > len(clean_motion_sources):
                raise ValueError(f"MODEL_CONFIG_MOTION_FRAME_EXCEEDS_SOURCE_COUNT:{desired}>{len(clean_motion_sources)}")
            while emitted_sources < desired:
                clean = clean_motion_sources[emitted_sources]
                lines.append(f"{_MODEL_CONFIG_TOKENS['motion_source']} {_quote_cfg(clean)}")
                emitted_sources += 1
        lines.append(_model_motion_line(row, talk=False))
        equipped = row.get("equipped_weapons")
        if equipped is not None:
            if not isinstance(equipped, list) or len(equipped) > 104:
                raise ValueError("MODEL_CONFIG_EQUIPPED_WEAPON_LIMIT_104")
            values = [str(x).strip() for x in equipped if str(x).strip()]
            if values:
                lines.append("*EQUIPPED_WEAPON " + " ".join(values))
        jobs = row.get("applicable_jobs")
        if jobs is not None:
            if not isinstance(jobs, list):
                raise ValueError("MODEL_CONFIG_APPLICABLE_JOBS_LIST_REQUIRED")
            values = [str(x).strip() for x in jobs if str(x).strip()]
            if values:
                lines.append("*APPLICABLE_JOB " + " ".join(values))
        location = row.get("location")
        if location is not None:
            if isinstance(location, str):
                location = [location]
            if not isinstance(location, list) or len(location) > 2:
                raise ValueError("MODEL_CONFIG_LOCATION_MAX_2")
            values = [str(x).strip().upper() for x in location if str(x).strip()]
            if any(x not in {"TOWN", "FIELD"} for x in values):
                raise ValueError("MODEL_CONFIG_LOCATION_TOWN_OR_FIELD_ONLY")
            if values:
                lines.append("*LOCATION " + " ".join(values))
        skills = row.get("applicable_skills")
        if skills is not None:
            if not isinstance(skills, list) or len(skills) > 7:
                raise ValueError("MODEL_CONFIG_APPLICABLE_SKILL_LIMIT_7")
            values = [str(x).strip() for x in skills if str(x).strip()]
            if values:
                lines.append("*APPLICABLE_SKILL " + " ".join(values))
    while emitted_sources < len(clean_motion_sources):
        clean = clean_motion_sources[emitted_sources]
        lines.append(f"{_MODEL_CONFIG_TOKENS['motion_source']} {_quote_cfg(clean)}")
        emitted_sources += 1

    add_path("talk_link_file", "talk_link_file")
    add_path("talk_motion_file", "talk_motion_file")
    talk_sources = payload.get("talk_motion_sources") or []
    if not isinstance(talk_sources, list) or len(talk_sources) > 128:
        raise ValueError("MODEL_CONFIG_TALK_MOTION_SOURCE_LIMIT_128")
    for value in talk_sources:
        clean = _model_config_path_value(value, "TALK_MOTION_SOURCE")
        lines.append(f"{_MODEL_CONFIG_TOKENS['talk_motion_source']} {_quote_cfg(clean)}")
        refs.append({"role": "talk_motion_source", "value": clean.replace("\\", "/")})
    for row in payload.get("talk_motions") or []:
        lines.append(_model_motion_line(row, talk=True))

    if not payload.get("model_file") and not payload.get("link_file"):
        raise ValueError("MODEL_CONFIG_REQUIRES_MODEL_FILE_OR_LINK_FILE")
    data, meta = _encode_text("\n".join(lines) + "\n", {"encoding": "cp949", "newline": "crlf"})
    if any(len(line.encode("cp949")) >= 512 for line in lines):
        raise ValueError("MODEL_CONFIG_LINE_EXCEEDS_SOURCE_511_BYTE_BUFFER")
    meta.update({
        "writer": "MODEL_CONFIG_SOURCE_EXACT",
        "source_parser": "AddModelDecode",
        "reference_count": len(refs),
        "references": refs,
        "motion_count": len(payload.get("motions") or []),
        "talk_motion_count": len(payload.get("talk_motions") or []),
        "runtime_cache_extension": ".inx",
        "runtime_cache_is_derived": True,
        "size": len(data),
    })
    return data, meta


def _decode_model_config(data: bytes) -> tuple[str, str]:
    for encoding in ("cp949", "cp1252", "latin1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("MODEL_CONFIG_ENCODING_UNRESOLVED")


def _model_config_first_value(rest: str) -> str | None:
    text = str(rest or "").strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 0 else None
    return text.split(None, 1)[0]


def _parse_model_config_refs(data: bytes) -> dict[str, Any]:
    text, encoding = _decode_model_config(data)
    reverse = {value: key for key, value in _MODEL_CONFIG_TOKENS.items()}
    refs: list[dict[str, str]] = []
    model_file = None
    link_file = None
    motion_file = None
    talk_motion_file = None
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        parts = stripped.split(None, 1)
        token = parts[0]
        role = reverse.get(token)
        if role is None or role.startswith("lod_") or role == "model_name":
            continue
        value = _model_config_first_value(parts[1] if len(parts) > 1 else "")
        if not value:
            continue
        value = value.replace("\\", "/")
        canonical_role = {"motion_source": "motion_source", "talk_motion_source": "talk_motion_source"}.get(role, role)
        refs.append({"role": canonical_role, "value": value, "line": line_no})
        if role == "model_file": model_file = value
        elif role == "link_file": link_file = value
        elif role == "motion_file": motion_file = value
        elif role == "talk_motion_file": talk_motion_file = value
    return {
        "encoding": encoding, "refs": refs, "model_file": model_file, "link_file": link_file,
        "motion_file": motion_file, "talk_motion_file": talk_motion_file,
        "motion_sources": [x["value"] for x in refs if x["role"] == "motion_source"],
        "talk_motion_sources": [x["value"] for x in refs if x["role"] == "talk_motion_source"],
    }



def _compile_operational_ini(contract_id: str, payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("OPERATIONAL_INI_REQUIRES_STRUCTURED_sections")
    registry = source_registry("operational_ini")
    rows = [x for x in registry.get("entries") or [] if str(x.get("contract_id")) == contract_id]
    allowed = {(str(x.get("section") or ""), str(x.get("key") or "")): x for x in rows}
    if not allowed:
        raise ValueError(f"OPERATIONAL_INI_SOURCE_REGISTRY_MISSING:{contract_id}")
    seen: set[tuple[str, str]] = set()
    unknown: list[str] = []
    out_sections: dict[str, dict[str, Any]] = {}
    for section, values in sections.items():
        if not isinstance(values, dict):
            raise ValueError(f"INI_SECTION_MUST_BE_OBJECT:{section}")
        out_values: dict[str, Any] = {}
        for key, value in values.items():
            spec = allowed.get((str(section), str(key)))
            if spec is None:
                unknown.append(f"{section}.{key}")
                continue
            kind = str(spec.get("type") or "string")
            if kind in {"int", "int/bool"}:
                if isinstance(value, bool): value = int(value)
                try: value = int(value)
                except Exception as exc: raise ValueError(f"INI_VALUE_MUST_BE_INT:{section}.{key}") from exc
            elif kind in {"string", "secret-string"} or kind.startswith("string<="):
                value = str(value)
                if kind.startswith("string<="):
                    limit = int(kind.split("<=", 1)[1])
                    if len(value.encode(str(payload.get("encoding") or "cp1252"))) > limit:
                        raise ValueError(f"INI_STRING_TOO_LONG:{section}.{key}:{limit}")
            out_values[str(key)] = value
            seen.add((str(section), str(key)))
        out_sections[str(section)] = out_values
    if unknown and not bool(payload.get("allow_unknown_keys", False)):
        raise ValueError("INI_UNKNOWN_SOURCE_KEYS:" + ",".join(sorted(unknown)))
    data, meta = _encode_text(_payload_text({"sections": out_sections}), payload)
    meta.update({
        "writer": "SOURCE_REGISTRY_INI",
        "contract_id": contract_id,
        "source_known_key_count": len(allowed),
        "authored_key_count": len(seen),
        "unknown_keys": unknown,
        "strict_source_keys": not bool(payload.get("allow_unknown_keys", False)),
    })
    return data, meta


def _server_directive_values(value: Any) -> list[Any]:
    if value is None: return []
    if isinstance(value, (list, tuple)): return list(value)
    return [value]


def _compile_server_main_config(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    directives = payload.get("directives")
    if not isinstance(directives, (dict, list)):
        raise ValueError("SERVER_MAIN_CONFIG_REQUIRES_STRUCTURED_directives")
    registry = source_registry("server_main_config")
    entries = list(registry.get("entries") or [])
    known = {str(x.get("directive") or "").upper(): x for x in entries if str(x.get("directive") or "").startswith("*")}
    rows: list[tuple[str, list[Any]]] = []
    if isinstance(directives, dict):
        rows = [(str(k), _server_directive_values(v)) for k, v in directives.items()]
    else:
        for idx, row in enumerate(directives):
            if not isinstance(row, dict) or not row.get("name"):
                raise ValueError(f"SERVER_DIRECTIVE_OBJECT_REQUIRED:{idx}")
            rows.append((str(row["name"]), _server_directive_values(row.get("values", row.get("value")))))
    lines: list[str] = []
    used: list[str] = []
    for raw_name, values in rows:
        name = raw_name.upper()
        spec = known.get(name)
        if spec is None:
            raise ValueError(f"SERVER_DIRECTIVE_NOT_IN_ACTIVE_SOURCE:{raw_name}")
        shape = str(spec.get("value_shape") or "")
        if shape == "flag/no-argument":
            if values: raise ValueError(f"SERVER_DIRECTIVE_TAKES_NO_VALUE:{raw_name}")
        elif shape == "integer":
            if len(values) != 1: raise ValueError(f"SERVER_DIRECTIVE_REQUIRES_ONE_INTEGER:{raw_name}")
            values = [int(values[0])]
        elif shape == "string":
            if len(values) != 1: raise ValueError(f"SERVER_DIRECTIVE_REQUIRES_ONE_STRING:{raw_name}")
            values = [str(values[0])]
        elif shape.startswith("tokens:"):
            count = int(shape.split(":", 1)[1])
            if len(values) != count: raise ValueError(f"SERVER_DIRECTIVE_REQUIRES_{count}_TOKENS:{raw_name}")
        elif shape.startswith("token-list<="):
            limit = int(shape.split("<=", 1)[1])
            if not 1 <= len(values) <= limit: raise ValueError(f"SERVER_DIRECTIVE_TOKEN_LIST_RANGE:{raw_name}:1..{limit}")
        line = raw_name if not values else raw_name + " " + " ".join(str(v) for v in values)
        lines.append(line); used.append(name)
    data, meta = _encode_text("\n".join(lines) + ("\n" if lines else ""), payload)
    meta.update({"writer": "SERVER_MAIN_CONFIG_SOURCE_DIRECTIVES", "authored_directive_count": len(lines), "source_active_directive_count": len(known), "directives": used})
    return data, meta


def _compile_skill_config(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    filename = pathlib.PurePosixPath(str(payload.get("file") or "")).name
    values = payload.get("values")
    if not filename or not isinstance(values, dict):
        raise ValueError("SKILL_CONFIG_REQUIRES_file_AND_values")
    registry = source_registry("skill_config")
    entries = [x for x in registry.get("entries") or [] if str(x.get("file") or "").casefold() == filename.casefold()]
    if not entries:
        raise ValueError(f"SKILL_CONFIG_FILE_NOT_CONSUMED_BY_SOURCE:{filename}")
    specs = {str(x.get("key")): x for x in entries}
    unknown = sorted(set(map(str, values)) - set(specs))
    if unknown:
        raise ValueError("SKILL_CONFIG_UNKNOWN_KEYS:" + ",".join(unknown))
    lines: list[str] = []
    for key, value in values.items():
        spec = specs[str(key)]
        typ = str(spec.get("type") or "")
        if not isinstance(value, (list, tuple)) or len(value) != 10:
            raise ValueError(f"SKILL_CONFIG_REQUIRES_10_LEVELS:{key}")
        if typ == "int[10]":
            vals = [str(int(x)) for x in value]
        elif typ == "float[10]":
            vals = [format(float(x), ".9g") for x in value]
        elif typ == "int[10][2]":
            pairs = []
            for idx, pair in enumerate(value):
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError(f"SKILL_CONFIG_PAIR_REQUIRED:{key}:{idx}")
                pairs.append(f"({int(pair[0])},{int(pair[1])})")
            vals = pairs
        else:
            raise ValueError(f"SKILL_CONFIG_TYPE_UNSUPPORTED:{key}:{typ}")
        line = f"{key} = " + ", ".join(vals) + ";"
        # Runtime fgets(line,255,...) requires the complete logical line to fit.
        encoding = str(payload.get("encoding") or "cp1252")
        if len((line + "\r\n").encode(encoding)) > 254:
            raise ValueError(f"SKILL_CONFIG_LINE_EXCEEDS_255_BUFFER:{key}")
        lines.append(line)
    data, meta = _encode_text("\n".join(lines) + ("\n" if lines else ""), payload)
    meta.update({
        "writer": "SKILL_CONFIG_SOURCE_REGISTRY",
        "file": filename,
        "authored_key_count": len(lines),
        "source_known_key_count": len(specs),
        "source_reader_contracts": {k: specs[k].get("type") for k in values},
    })
    return data, meta



def _source_token(registry_name: str, name: str) -> str:
    registry = source_registry(registry_name)
    entries = registry.get("entries") or {}
    row = entries.get(name) if isinstance(entries, dict) else None
    if not isinstance(row, dict) or not row.get("token"):
        raise ValueError(f"SOURCE_TOKEN_NOT_FOUND:{registry_name}:{name}")
    return str(row["token"])


def _quote_legacy_value(value: Any) -> str:
    text = str(value)
    if any(ch in text for ch in "\r\n\x00"):
        raise ValueError("LEGACY_VALUE_CONTAINS_CONTROL_CHARACTER")
    if '"' in text:
        raise ValueError("LEGACY_VALUE_CONTAINS_QUOTE")
    return f'"{text}"' if any(ch.isspace() for ch in text) or not text else text


def _legacy_line(token: str, values: list[Any] | tuple[Any, ...] | Any = ()) -> str:
    if not isinstance(values, (list, tuple)):
        values = [values]
    if not values:
        return token
    return token + " " + " ".join(_quote_legacy_value(v) for v in values)


def _validate_legacy_lines(lines: list[str], *, encoding: str = "cp949", buffer_bytes: int = 256) -> None:
    for idx, line in enumerate(lines, 1):
        size = len((line + "\r\n").encode(encoding))
        if size >= buffer_bytes:
            raise ValueError(f"LEGACY_CONFIG_LINE_TOO_LONG:{idx}:{size}>={buffer_bytes}")


_CHARACTER_CORE_FIELDS: dict[str, tuple[str, str]] = {
    "name": ("Name", "string"),
    "model_file": ("ModelFile", "string"),
    "state": ("State", "state"),
    "size": ("Size", "string"),
    "sound": ("Sound", "string"),
    "effect_sound": ("EffectSound", "string"),
    "level": ("Level", "int"),
    "boss": ("Boss", "flag"),
    "class": ("Class", "int"),
    "model_scale": ("ModelScale", "float"),
    "move_speed": ("MoveSpeed", "float"),
    "attack_damage": ("AttackDamage", "int2"),
    "attack_speed": ("AttackSpeed", "float2"),
    "attack_range": ("AttackRange", "int"),
    "attack_rating": ("AttackRating", "int"),
    "defence": ("Defence", "int"),
    "absorption": ("Absorption", "int"),
    "block": ("Block", "int"),
    "life": ("Life", "int"),
    "bionic": ("Bionic", "int"),
    "water": ("Water", "int"),
    "lightning": ("Lightning", "int"),
    "ice": ("Ice", "int"),
    "wind": ("Wind", "int"),
    "earth": ("Earth", "int"),
    "fire": ("Fire", "int"),
    "poison": ("Poison", "float"),
    "sight": ("Sight", "int"),
    "arrow_correction": ("ArrowCorrection", "int1or2"),
}

_CHARACTER_MONSTER_FIELDS: dict[str, tuple[str, str]] = {
    "event_model": ("EventModel", "string"),
    "skill_damage": ("SkillDamage", "int2"),
    "skill_distance": ("SkillDistance", "int"),
    "skill_range": ("SkillRange", "int"),
    "skill_rating": ("SkillRating", "int"),
    "skill_curse": ("SkillCurse", "int"),
    "move_type": ("MoveType", "int"),
    "move_range": ("MoveRange", "float"),
    "active_hour": ("ActiveHour", "active_hour"),
    "generate_group": ("GenerateGroup", "int2"),
    "iq": ("IQ", "int"),
    "class_code": ("ClassCode", "int"),
    "stun_percent": ("StunPercent", "int"),
    "nature": ("Nature", "nature"),
    "event_code": ("EventCode", "int"),
    "event_info": ("EventInfo", "int"),
    "event_item": ("EventItem", "string"),
    "special_attack_rate": ("SpecialAttackRate", "int"),
    "undead": ("Undead", "present_bool"),
    "monster_race": ("MonsterRace", "race"),
    "experience": ("Experience", "int"),
    "potion_count": ("PotionCount", "int"),
    "potion_percent": ("PotionPercent", "int"),
    "all_see_item": ("AllSeeItem", "flag"),
    "fall_item_max": ("FallItemMax", "int"),
}

_CHARACTER_NPC_FIELDS: dict[str, tuple[str, str]] = {
    "skill_master": ("SkillMaster", "flag"),
    "skill_change_job": ("SkillChangeJob", "optional_int_flag"),
    "event_npc": ("EventNpc", "optional_int_flag"),
    "warehouse": ("Warehouse", "flag"),
    "item_mix": ("ItemMix", "flag"),
    "smelting": ("Smelting", "flag"),
    "manufacture": ("Manufacture", "flag"),
    "refining": ("Refining", "flag"),
    "item_aging": ("ItemAging", "flag"),
    "mixture_reset": ("MixtureReset", "flag"),
    "collect_money": ("CollectMoney", "flag"),
    "event_gift": ("EventGift", "flag"),
    "clan_npc": ("ClanNpc", "flag"),
    "gift_express": ("GiftExpress", "flag"),
    "wing_quest": ("WingQuest", "optional_int_flag"),
    "quest_event": ("QuestEvent", "optional_int_flag"),
    "star_point": ("StarPoint", "optional_int_flag"),
    "give_money": ("GiveMoney", "flag"),
    "teleport": ("Teleport", "optional_int_flag"),
    "bless_castle": ("BlessCastle", "optional_int_flag"),
    "polling": ("Polling", "optional_int_flag"),
    "media_title": ("MediaTitle", "string"),
    "media_path": ("MediaPath", "string"),
    "open_count": ("OpenCount", "int2"),
    "quest_code": ("QuestCode", "int2"),
    "clan_custom": ("ClanCustom", "flag"),
    "npc_info": ("NpcInfo", "flag"),
    "rank": ("Rank", "flag"),
    "battle_pass": ("BattlePass", "flag"),
    "skin_change": ("SkinChange", "flag"),
    "shop": ("Shop", "flag"),
    "time_shop": ("TimeShop", "flag"),
    "ranking": ("Ranking", "flag"),
}


def _typed_values(kind: str, value: Any) -> list[Any] | None:
    if kind == "flag":
        return [] if bool(value) else None
    if kind == "optional_int_flag":
        if value is False or value is None:
            return None
        return [] if value is True else [int(value)]
    if kind == "string": return [str(value)]
    if kind == "int": return [int(value)]
    if kind == "float": return [format(float(value), ".9g")]
    if kind in {"int2", "float2", "int1or2"}:
        if not isinstance(value, (list, tuple)):
            value = [value]
        expected = 2 if kind != "int1or2" else None
        if expected and len(value) != expected:
            raise ValueError(f"CHARACTER_FIELD_REQUIRES_{expected}_VALUES")
        if kind == "int1or2" and not 1 <= len(value) <= 2:
            raise ValueError("CHARACTER_FIELD_REQUIRES_1_OR_2_VALUES")
        if kind.startswith("int"):
            return [int(x) for x in value]
        return [format(float(x), ".9g") for x in value]
    if kind == "state":
        enemy = bool(value) if isinstance(value, bool) else str(value).casefold() in {"enemy", "hostile", "1", "true"}
        return [_source_token("character_tokens", "Enemy") if enemy else "0"]
    if kind == "active_hour":
        key = str(value).casefold()
        if key not in {"day", "night"}: raise ValueError("ACTIVE_HOUR_MUST_BE_day_OR_night")
        return [_source_token("character_tokens", "Day" if key == "day" else "Night")]
    if kind == "nature":
        key = str(value).casefold()
        if key not in {"natural", "good", "evil"}: raise ValueError("NATURE_MUST_BE_natural_good_OR_evil")
        return [] if key == "natural" else [key]
    if kind == "present_bool":
        return [_source_token("character_tokens", "Present") if bool(value) else "0"]
    if kind == "race":
        key = str(value).casefold()
        mapping = {"undead":"RaceUndead", "mutant":"RaceMutant", "demon":"RaceDemon", "mechanic":"RaceMechanic"}
        if key not in mapping: raise ValueError("MONSTER_RACE_INVALID")
        return [_source_token("character_tokens", mapping[key])]
    raise ValueError(f"CHARACTER_FIELD_TYPE_UNSUPPORTED:{kind}")


def _compile_character_definition(contract_id: str, payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("CHARACTER_DEFINITION_REQUIRES_STRUCTURED_fields")
    if not str(fields.get("name") or "").strip(): raise ValueError("CHARACTER_NAME_REQUIRED")
    if not str(fields.get("model_file") or "").strip(): raise ValueError("CHARACTER_MODEL_FILE_REQUIRED")
    lines: list[str] = []
    authored: list[str] = []
    allowed = dict(_CHARACTER_CORE_FIELDS)
    if contract_id == "character.monster.inf": allowed.update(_CHARACTER_MONSTER_FIELDS)
    if contract_id == "character.npc.npc": allowed.update(_CHARACTER_NPC_FIELDS)
    unknown = sorted(set(map(str, fields)) - set(allowed))
    if unknown: raise ValueError("CHARACTER_UNKNOWN_FIELDS:" + ",".join(unknown))
    for field, value in fields.items():
        token_name, kind = allowed[str(field)]
        vals = _typed_values(kind, value)
        if vals is None: continue
        lines.append(_legacy_line(_source_token("character_tokens", token_name), vals))
        authored.append(str(field))
    # The runtime accepts repeated dialog directives.
    dialogs = payload.get("dialogs") or []
    if isinstance(dialogs, str): dialogs = [dialogs]
    if not isinstance(dialogs, list): raise ValueError("CHARACTER_DIALOGS_MUST_BE_LIST")
    for value in dialogs:
        lines.append(_legacy_line(_source_token("character_tokens", "Dialog"), [str(value)]))
    # NPC shop inventories are source-limited to 32 items per category.
    shops = payload.get("shops") or {}
    if not isinstance(shops, dict): raise ValueError("CHARACTER_SHOPS_MUST_BE_OBJECT")
    shop_map = {"weapon":"SellWeapon", "defence":"SellDefence", "etc":"SellEtc"}
    for key, values in shops.items():
        if key not in shop_map: raise ValueError(f"NPC_SHOP_CATEGORY_INVALID:{key}")
        if not isinstance(values, list) or len(values) > 32: raise ValueError(f"NPC_SHOP_ITEMS_RANGE:{key}:0..32")
        if values: lines.append(_legacy_line(_source_token("character_tokens", shop_map[key]), [str(x) for x in values]))
    # Monster drop syntax is kept structured so percentages and code lists are unambiguous.
    drops = payload.get("drops") or []
    if not isinstance(drops, list): raise ValueError("CHARACTER_DROPS_MUST_BE_LIST")
    for idx, drop in enumerate(drops):
        if not isinstance(drop, dict): raise ValueError(f"MONSTER_DROP_OBJECT_REQUIRED:{idx}")
        pct = int(drop.get("percentage", 0))
        if "money" in drop:
            pair = drop["money"]
            if not isinstance(pair, (list, tuple)) or len(pair) not in {1, 2}: raise ValueError(f"MONSTER_DROP_MONEY_VALUES_REQUIRED:{idx}:1..2")
            vals = [pct, _source_token("character_tokens", "Money"), *[int(x) for x in pair]]
        elif bool(drop.get("none")):
            vals = [pct, _source_token("character_tokens", "NoItem")]
        else:
            items = drop.get("items") or []
            if not isinstance(items, list) or not 1 <= len(items) <= 32: raise ValueError(f"MONSTER_DROP_ITEMS_RANGE:{idx}:1..32")
            vals = [pct, *map(str, items)]
        lines.append(_legacy_line(_source_token("character_tokens", "FallItem"), vals))
    extras = payload.get("extra_drops") or []
    if not isinstance(extras, list): raise ValueError("CHARACTER_EXTRA_DROPS_MUST_BE_LIST")
    for idx, drop in enumerate(extras):
        if not isinstance(drop, dict) or not drop.get("item"): raise ValueError(f"MONSTER_EXTRA_DROP_INVALID:{idx}")
        lines.append(_legacy_line(_source_token("character_tokens", "ExtraFallItem"), [int(drop.get("percentage", 0)), str(drop["item"])]))
    linked = payload.get("linked_file")
    if linked:
        lines.append(_legacy_line(_source_token("character_tokens", "LinkedFile"), [str(linked)]))
    _validate_legacy_lines(lines, encoding="cp949")
    data, meta = _encode_text("\n".join(lines) + "\n", {**payload, "encoding":"cp949", "newline":"crlf"})
    meta.update({
        "writer":"CHARACTER_CONFIG_SOURCE_SCHEMA",
        "contract_id":contract_id,
        "authored_fields":authored,
        "dialog_count":len(dialogs),
        "drop_count":len(drops),
        "extra_drop_count":len(extras),
        "encoding_contract":"CP949",
        "attack_speed_two_value_contract": "attack_speed" not in fields or len(fields.get("attack_speed") if isinstance(fields.get("attack_speed"), (list,tuple)) else []) == 2,
    })
    return data, meta


_ITEM_FIELD_SPECS: dict[str, tuple[str, str]] = {
    "name": ("Name", "string"), "code": ("Code", "string"), "unique": ("Unique", "optional_int_flag"),
    "display_effect": ("DisplayEffect", "int"), "durability": ("Durability", "int2"), "weight": ("Weight", "int"), "price": ("Price", "int"),
    "bionic": ("Bionic", "int2"), "earth": ("Earth", "int2"), "fire": ("Fire", "int2"), "ice": ("Ice", "int2"), "lightning": ("Lightning", "int2"), "poison": ("Poison", "int2"), "water": ("Water", "int2"), "wind": ("Wind", "int2"),
    "attack_damage": ("AttackDamage", "int4"), "shooting_range": ("ShootingRange", "int"), "attack_speed": ("AttackSpeed", "int"), "attack_rating": ("AttackRating", "int2"), "critical": ("Critical", "int"),
    "absorb": ("Absorb", "float2"), "defence": ("Defence", "int2"), "block": ("Block", "float2"), "move_speed": ("MoveSpeed", "float2"), "potion_space": ("PotionSpace", "int"), "magic_mastery": ("MagicMastery", "float"),
    "mana_regen": ("ManaRegen", "float2"), "life_regen": ("LifeRegen", "float2"), "stamina_regen": ("StaminaRegen", "float2"),
    "mana_add": ("ManaAdd", "int2"), "life_add": ("LifeAdd", "int2"), "stamina_add": ("StaminaAdd", "int2"),
    "level": ("Level", "int"), "strength": ("Strength", "int"), "spirit": ("Spirit", "int"), "talent": ("Talent", "int"), "dexterity": ("Dexterity", "int"), "health": ("Health", "int"),
    "stamina": ("Stamina", "int2"), "mana": ("Mana", "int2"), "life": ("Life", "int2"), "generation_limit": ("GenerationLimit", "int"),
}


def _item_values(kind: str, value: Any) -> list[Any] | None:
    if kind in {"string","int","float","optional_int_flag"}: return _typed_values(kind,value)
    if kind in {"int2","float2"}:
        if not isinstance(value,(list,tuple)) or len(value)!=2: raise ValueError(f"ITEM_FIELD_REQUIRES_2_VALUES:{kind}")
        return [int(x) for x in value] if kind=="int2" else [format(float(x),".9g") for x in value]
    if kind == "int4":
        if not isinstance(value,(list,tuple)) or len(value)!=4: raise ValueError("ITEM_FIELD_REQUIRES_4_VALUES")
        return [int(x) for x in value]
    raise ValueError(f"ITEM_FIELD_TYPE_UNSUPPORTED:{kind}")


def _compile_item_definition(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    fields=payload.get("fields")
    if not isinstance(fields,dict): raise ValueError("ITEM_DEFINITION_REQUIRES_STRUCTURED_fields")
    for required in ("name","code"):
        if not str(fields.get(required) or "").strip(): raise ValueError(f"ITEM_{required.upper()}_REQUIRED")
    code_text=str(fields.get("code") or "").strip()
    catalog=source_registry("item_catalog")
    matches=[x for x in catalog.get("entries") or [] if str(x.get("code") or "").casefold()==code_text.casefold()]
    allow_unknown=bool(payload.get("allow_unknown_code",False))
    if not matches and not allow_unknown:
        raise ValueError(f"ITEM_CODE_NOT_IN_RUNTIME_TABLE:{code_text}")
    code_status="SOURCE_VERIFIED" if matches else "CODE_BOUNDARY_UNREGISTERED"
    numeric_codes=sorted({str(x.get("numeric_code_hex") or "") for x in matches if x.get("numeric_code_hex")})
    if len(numeric_codes)>1:
        code_status="SOURCE_AMBIGUOUS_MULTIPLE_NUMERIC_CODES"
    unknown=sorted(set(map(str,fields))-set(_ITEM_FIELD_SPECS))
    if unknown: raise ValueError("ITEM_UNKNOWN_FIELDS:"+",".join(unknown))
    lines=[]
    for field,value in fields.items():
        token_name,kind=_ITEM_FIELD_SPECS[str(field)]
        vals=_item_values(kind,value)
        if vals is not None: lines.append(_legacy_line(_source_token("item_tokens",token_name),vals))
    unique_color=payload.get("unique_color")
    if unique_color is not None:
        if not isinstance(unique_color,(list,tuple)) or len(unique_color) not in {5,6}: raise ValueError("ITEM_UNIQUE_COLOR_REQUIRES_5_OR_6_VALUES")
        vals=[int(x) if i<5 else format(float(x),".9g") for i,x in enumerate(unique_color)]
        lines.append(_legacy_line(_source_token("item_tokens","UniqueColor"),vals))
    jobs=payload.get("jobs") or []
    if isinstance(jobs,str): jobs=[jobs]
    if jobs: lines.append(_legacy_line(_source_token("item_tokens","Job"),[str(x) for x in jobs]))
    random_jobs=payload.get("random_jobs") or []
    if isinstance(random_jobs,str): random_jobs=[random_jobs]
    if random_jobs: lines.append(_legacy_line(_source_token("item_tokens","JobRandom"),[str(x) for x in random_jobs]))
    linked=payload.get("linked_file")
    if linked: lines.append(_legacy_line(_source_token("item_tokens","LinkedFile"),[str(linked)]))
    _validate_legacy_lines(lines,encoding="cp949",buffer_bytes=512)
    data,meta=_encode_text("\n".join(lines)+"\n",{**payload,"encoding":"cp949","newline":"crlf"})
    legacy_category = classify_item_code(code_text)
    runtime_visual = lookup_item_runtime(code_text)
    meta.update({"writer":"ITEM_DEFINITION_SOURCE_SCHEMA","authored_fields":list(fields),"job_count":len(jobs),"random_job_count":len(random_jobs),"code_identity_boundary":code_status!="SOURCE_VERIFIED","code_identity_status":code_status,"runtime_catalog_match_count":len(matches),"runtime_numeric_codes":numeric_codes,"runtime_catalog_record_count":int(catalog.get("record_count") or 0),"encoding_contract":"CP949","legacy_management_category":legacy_category,"runtime_item_contract":runtime_visual})
    return data,meta


def _compile_sin(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    text = _payload_text(payload)
    # Runtime uses a zeroed 80*128 byte read buffer and a CRLF splitter that
    # writes into 128-byte line slots without an explicit bounds check.
    # Keep one byte free for the zero sentinel and each logical line <=127 bytes.
    data, meta = _encode_text(text, payload, force_crlf=True)
    if len(data) > 10239:
        raise ValueError(f"SIN_FILE_EXCEEDS_SAFE_RUNTIME_BUFFER:{len(data)}>10239")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if len(lines) > 80:
        raise ValueError(f"SIN_LINE_COUNT_EXCEEDS_RENDERED_RUNTIME_LIMIT:{len(lines)}>80")
    encoding = meta["encoding"]
    for idx, line in enumerate(lines):
        try:
            encoded = line.encode(encoding)
        except UnicodeEncodeError as exc:
            raise ValueError(f"SIN_LINE_NOT_ENCODABLE:{idx}:{exc}") from exc
        if len(encoded) > 127:
            raise ValueError(f"SIN_LINE_TOO_LONG:{idx}:{len(encoded)}>127")
    meta.update({"writer": "SIN_HELP_TEXT", "safe_runtime_buffer": True, "max_runtime_read_bytes": 10240, "max_line_bytes": 127})
    return data, meta


def _actor_name(value: Any, encoding: str) -> str:
    name = str(value or "").strip()
    if not name or any(c in name for c in "\r\n\0"):
        raise ValueError("SPM_ACTOR_NAME_INVALID")
    if len(name.encode(encoding)) >= 64:
        raise ValueError("SPM_ACTOR_NAME_EXCEEDS_63_BYTES")
    return name


def _compile_spm(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    encoding = str(payload.get("encoding") or "cp1252").strip().lower()
    if encoding not in {"cp1252", "cp949", "latin1", "utf-8"}:
        raise ValueError("SPM_ENCODING_NOT_ALLOWED")
    actors = payload.get("actors") or []
    bosses = payload.get("boss_actors") or []
    if not isinstance(actors, list) or not isinstance(bosses, list):
        raise ValueError("SPM_ACTORS_MUST_BE_LISTS")
    if len(actors) > 50:
        raise ValueError("SPM_ACTOR_COUNT_EXCEEDS_50")
    if len(bosses) > 16:
        raise ValueError("SPM_BOSS_ACTOR_COUNT_EXCEEDS_16")
    lines: list[str] = []
    total_weight = 0
    for row in actors:
        if not isinstance(row, dict):
            raise ValueError("SPM_ACTOR_ROW_MUST_BE_OBJECT")
        name = _actor_name(row.get("name"), encoding)
        weight = int(row.get("weight") or 0)
        if weight < 0:
            raise ValueError(f"SPM_ACTOR_WEIGHT_NEGATIVE:{name}")
        total_weight += weight
        lines.append(f'*ACTOR "{name}" {weight}')
    for row in bosses:
        if not isinstance(row, dict):
            raise ValueError("SPM_BOSS_ROW_MUST_BE_OBJECT")
        master = _actor_name(row.get("master"), encoding)
        slave = _actor_name(row.get("slave"), encoding)
        slave_count = int(row.get("slave_count") or 0)
        if slave_count < 0:
            raise ValueError("SPM_BOSS_SLAVE_COUNT_NEGATIVE")
        hours = [int(x) for x in (row.get("hours") or [])]
        if any(not 0 <= x <= 255 for x in hours):
            raise ValueError("SPM_BOSS_HOUR_OUT_OF_BYTE_RANGE")
        tail = "".join(f" {x}" for x in hours)
        lines.append(f'*BOSS_ACTOR "{master}" "{slave}" {slave_count}{tail}')
    if "max_actor_pos" in payload:
        lines.append(f"*MAX_ACTOR_POS {int(payload['max_actor_pos'])}")
    if "delay_shift" in payload or "delay_seconds" in payload:
        shift = int(payload.get("delay_shift") or 0)
        if not 0 <= shift < 31:
            raise ValueError("SPM_DELAY_SHIFT_OUT_OF_RANGE_0_30")
        if "delay_seconds" in payload:
            sec = int(payload.get("delay_seconds") or 0)
            if sec < 0 or sec > 0xFFFFFFFF // 1000:
                raise ValueError("SPM_DELAY_SECONDS_OUT_OF_RANGE")
            lines.append(f"*DELAY {shift} {sec}")
        else:
            lines.append(f"*DELAY {shift}")
    if "max_actor" in payload:
        lines.append(f"*MAX_ACTOR {int(payload['max_actor'])}")
    if not lines:
        raise ValueError("SPM_REQUIRES_AT_LEAST_ONE_DIRECTIVE")
    text = "\r\n".join(lines) + "\r\n"
    data = text.encode(encoding)
    for idx, line in enumerate(lines):
        if len((line + "\r\n").encode(encoding)) > 255:
            raise ValueError(f"SPM_LINE_EXCEEDS_FGETS_BUFFER:{idx}")
    return data, {
        "writer": "SPM_STRUCTURED",
        "encoding": encoding,
        "actor_count": len(actors),
        "boss_actor_count": len(bosses),
        "actor_weight_total": total_weight,
        "source_limits": {"actors": 50, "boss_actors": 16, "line_buffer": 256},
    }


def _compile_spp(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    records = payload.get("records") or []
    if not isinstance(records, list):
        raise ValueError("SPP_records_MUST_BE_LIST")
    data = bytearray(SPP_RECORD_COUNT * SPP_RECORD_SIZE)
    used: set[int] = set()
    for ordinal, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError("SPP_RECORD_MUST_BE_OBJECT")
        index = int(row.get("index", ordinal))
        if not 0 <= index < SPP_RECORD_COUNT:
            raise ValueError(f"SPP_INDEX_OUT_OF_RANGE:{index}")
        if index in used:
            raise ValueError(f"SPP_DUPLICATE_INDEX:{index}")
        used.add(index)
        state = int(row.get("state", 1))
        x = int(row.get("x", 0)); z = int(row.get("z", 0))
        struct.pack_into("<iii", data, index * SPP_RECORD_SIZE, state, x, z)
    return bytes(data), {
        "writer": "SPP_WIN32_ABI",
        "record_count": SPP_RECORD_COUNT,
        "authored_record_count": len(used),
        "file_size": len(data),
        "schema": "field.startpoints.spp",
    }


def _cstr(value: Any, size: int, encoding: str, field: str) -> bytes:
    text = str(value or "")
    if "\0" in text or any(c in text for c in "\r\n"):
        raise ValueError(f"{field}_INVALID_TEXT")
    try:
        raw = text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field}_NOT_ENCODABLE:{encoding}:{exc}") from exc
    if len(raw) >= size:
        raise ValueError(f"{field}_EXCEEDS_{size-1}_BYTES")
    return raw + (b"\0" * (size - len(raw)))


def _pack_spc_char_info(record: bytearray, base: int, row: dict[str, Any], encoding: str) -> None:
    # Offsets are the source-derived Win32 smCHAR_INFO ABI, not donor guesses.
    record[base + 0:base + 32] = _cstr(row.get("name"), 32, encoding, "SPC_name")
    record[base + 32:base + 96] = _cstr(str(row.get("model_ini") or "").replace("/", "\\"), 64, "ascii", "SPC_model_ini")
    record[base + 96:base + 156] = _cstr(str(row.get("server_npc") or "").replace("/", "\\"), 60, "ascii", "SPC_server_npc")
    # pointer/runtime identity fields must never contain process addresses in a disk asset.
    struct.pack_into("<II", record, base + 156, int(row.get("model_name_code2") or 0) & 0xFFFFFFFF, 0)
    # Current SendAdd_Npc explicitly forces State=0 before persistence.
    struct.pack_into("<i", record, base + 168, 0)
    # Preserve source builder's safe initial health/mana defaults. smCharDecode(server_npc)
    # overwrites config-owned values when OpenNpc loads the persisted record.
    life = row.get("life") or [100, 100]
    mana = row.get("mana") or [100, 0]
    stamina = row.get("stamina") or [0, 0]
    for value, label in ((life, "life"), (mana, "mana"), (stamina, "stamina")):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"SPC_{label}_MUST_BE_PAIR")
        if any(not -32768 <= int(x) <= 32767 for x in value):
            raise ValueError(f"SPC_{label}_OUT_OF_INT16_RANGE")
    struct.pack_into("<2h", record, base + 292, *map(int, life))
    struct.pack_into("<2h", record, base + 296, *map(int, mana))
    struct.pack_into("<2h", record, base + 300, *map(int, stamina))
    # A small allowlist of scalar fields may be authored explicitly. Everything else
    # remains canonical zero and is populated from the NPC config at OpenNpc time.
    scalar_i32 = {
        "class_clan": 164, "size_level": 172, "level": 184, "strength": 188,
        "spirit": 192, "talent": 196, "dexterity": 200, "health": 204,
        "accuracy": 208, "attack_rating": 212, "attack_speed": 224,
        "shooting_range": 228, "critical_hit": 232, "defence": 236,
        "chance_block": 240, "absorption": 244, "move_speed": 248,
        "sight": 252, "exp": 316, "next_exp": 320, "money": 324,
    }
    for key, off in scalar_i32.items():
        if key in row:
            struct.pack_into("<i", record, base + off, int(row[key]))
    scalar_u32 = {"char_sound_code": 176, "job_code": 180, "brood": 332}
    for key, off in scalar_u32.items():
        if key in row:
            value = int(row[key])
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"SPC_{key}_OUT_OF_UINT32_RANGE")
            struct.pack_into("<I", record, base + off, value)
    if "attack_damage" in row:
        pair = row["attack_damage"]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("SPC_attack_damage_MUST_BE_PAIR")
        struct.pack_into("<2i", record, base + 216, *map(int, pair))


def build_spc_record(row: dict[str, Any], *, record_encoding: str = "cp949") -> bytes:
    """Build one source-derived Win32 smTRNAS_PLAYERINFO disk record.

    The record is deterministic and contains no runtime pointer/object identity.
    It is suitable for insertion into one of the 100 fixed SPC slots.
    """
    if not isinstance(row, dict):
        raise ValueError("SPC_RECORD_MUST_BE_OBJECT")
    encoding = str(record_encoding or "cp949").strip().lower()
    if encoding not in {"cp949", "cp1252", "latin1", "utf-8"}:
        raise ValueError("SPC_RECORD_ENCODING_NOT_ALLOWED")
    rec = bytearray(SPC_RECORD_SIZE)
    code_value = row.get("code", "CURRENT")
    if isinstance(code_value, str):
        cv = code_value.strip().upper()
        if cv == "CURRENT": code = CURRENT_NPC_OPCODE
        elif cv == "LEGACY": code = LEGACY_NPC_OPCODE
        else: code = int(code_value, 0)
    else:
        code = int(code_value)
    if code == 0:
        raise ValueError("SPC_AUTHORED_RECORD_CODE_MUST_BE_NONZERO")
    if not 0 <= (code & 0xFFFFFFFF) <= 0xFFFFFFFF:
        raise ValueError("SPC_CODE_OUT_OF_32BIT_RANGE")
    struct.pack_into("<iI", rec, 0, SPC_RECORD_SIZE, code & 0xFFFFFFFF)
    _pack_spc_char_info(rec, 8, row, encoding)
    struct.pack_into(
        "<I7i", rec, 472,
        0,
        int(row.get("x", 0)), int(row.get("y", 0)), int(row.get("z", 0)),
        int(row.get("ax", 0)), int(row.get("ay", 0)), int(row.get("az", 0)),
        int(row.get("state", 0)),
    )
    return bytes(rec)


def _compile_spc(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    records = payload.get("records") or []
    if not isinstance(records, list):
        raise ValueError("SPC_records_MUST_BE_LIST")
    encoding = str(payload.get("record_encoding") or "cp949").strip().lower()
    if encoding not in {"cp949", "cp1252", "latin1", "utf-8"}:
        raise ValueError("SPC_RECORD_ENCODING_NOT_ALLOWED")
    data = bytearray(SPC_RECORD_COUNT * SPC_RECORD_SIZE)
    used: set[int] = set()
    current = 0; legacy = 0
    for ordinal, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError("SPC_RECORD_MUST_BE_OBJECT")
        index = int(row.get("index", ordinal))
        if not 0 <= index < SPC_RECORD_COUNT:
            raise ValueError(f"SPC_INDEX_OUT_OF_RANGE:{index}")
        if index in used:
            raise ValueError(f"SPC_DUPLICATE_INDEX:{index}")
        used.add(index)
        rec = build_spc_record(row, record_encoding=encoding)
        code = struct.unpack_from("<I", rec, 4)[0]
        data[index * SPC_RECORD_SIZE:(index + 1) * SPC_RECORD_SIZE] = rec
        current += int(code == CURRENT_NPC_OPCODE); legacy += int(code == LEGACY_NPC_OPCODE)
    return bytes(data), {
        "writer": "SPC_WIN32_ABI_FROM_ZERO",
        "record_count": SPC_RECORD_COUNT,
        "authored_record_count": len(used),
        "current_opcode_count": current,
        "legacy_opcode_count": legacy,
        "current_opcode": f"0x{CURRENT_NPC_OPCODE:08X}",
        "legacy_opcode": f"0x{LEGACY_NPC_OPCODE:08X}",
        "file_size": len(data),
        "source_runtime_behavior": "OpenNpc reloads server_npc from smCharInfo.szModelName2 and assigns runtime object serial",
        "pointer_policy": "lpMonInfo_and_runtime_serial_zero",
    }


def _pad_list(values: Any, count: int, default: Any, label: str) -> list[Any]:
    rows = list(values or [])
    if len(rows) > count:
        raise ValueError(f"{label}_EXCEEDS_{count}")
    return rows + [default for _ in range(count - len(rows))]


def _compile_font_image_pos(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    records = payload.get("records") or []
    if not isinstance(records, list) or len(records) != 136:
        raise ValueError("FONT_IMAGE_POS_REQUIRES_EXACTLY_136_RECORDS")
    out = bytearray()
    for idx, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"FONT_IMAGE_POS_RECORD_OBJECT_REQUIRED:{idx}")
        vals = [float(row.get(k, 0.0)) for k in ("fTexSt_x", "fTexSt_y", "fTexEnd_x", "fTexEnd_y")]
        if not all(math.isfinite(x) for x in vals):
            raise ValueError(f"FONT_IMAGE_POS_FLOAT_NONFINITE:{idx}")
        if bool(payload.get("enforce_uv_0_1", True)) and any(x < 0.0 or x > 1.0 for x in vals):
            raise ValueError(f"FONT_IMAGE_POS_UV_OUT_OF_RANGE:{idx}")
        out += struct.pack("<ii4f", int(row.get("IsCh", 0)), int(row.get("iWidehPixel", 0)), *vals)
    if len(out) != 3264:
        raise AssertionError("FONT_IMAGE_POS_SIZE_DRIFT")
    return bytes(out), {"writer": "FONT_IMAGE_POS_WIN32_ABI", "record_count": 136, "file_size": len(out)}


def _compile_stage_info(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    records = payload.get("records") or []
    if not isinstance(records, list) or len(records) != 256:
        raise ValueError("STAGE_INFO_REQUIRES_EXACTLY_256_RECORDS")
    out = bytearray()
    for idx, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"STAGE_INFO_RECORD_OBJECT_REQUIRED:{idx}")
        rect = row.get("rect") or [0, 0, 0, 0]
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError(f"STAGE_INFO_RECT_REQUIRES_4_INTS:{idx}")
        width = int(row.get("width", int(rect[2]) - int(rect[0])))
        height = int(row.get("height", int(rect[3]) - int(rect[1])))
        ratio = float(row.get("ratio", max(width, height) / 320.0 if max(width, height) else 0.0))
        if not math.isfinite(ratio):
            raise ValueError(f"STAGE_INFO_RATIO_NONFINITE:{idx}")
        out += struct.pack("<6if", *map(int, rect), width, height, ratio)
    if len(out) != 7168:
        raise AssertionError("STAGE_INFO_SIZE_DRIFT")
    return bytes(out), {"writer": "STAGE_INFO_WIN32_ABI", "record_count": 256, "file_size": len(out), "derived_cache": True}


def _pair_array(values: Any, count: int, label: str) -> list[tuple[int, int]]:
    rows = _pad_list(values, count, [0, 0], label)
    out=[]
    for idx,row in enumerate(rows):
        if not isinstance(row,(list,tuple)) or len(row)!=2:
            raise ValueError(f"{label}_PAIR_REQUIRED:{idx}")
        out.append((int(row[0]),int(row[1])))
    return out


def _triple_array(values: Any, count: int, label: str) -> list[tuple[int, int, int]]:
    rows = _pad_list(values, count, [0, 0, 0], label)
    out=[]
    for idx,row in enumerate(rows):
        if not isinstance(row,(list,tuple)) or len(row)!=3:
            raise ValueError(f"{label}_TRIPLE_REQUIRED:{idx}")
        out.append((int(row[0]),int(row[1]),int(row[2])))
    return out


def _compile_bellatra(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    mins = payload.get("min_effects") or []
    fonts = payload.get("font_effects") or []
    if not isinstance(mins,list) or not isinstance(fonts,list):
        raise ValueError("BELLATRA_EFFECT_LISTS_REQUIRED")
    if len(mins)>50 or len(fonts)>40:
        raise ValueError("BELLATRA_RECORD_LIMIT_EXCEEDED")
    min_rows = list(mins) + [{} for _ in range(50-len(mins))]
    font_rows = list(fonts) + [{} for _ in range(40-len(fonts))]
    out=bytearray()
    for idx,row in enumerate(min_rows):
        if not isinstance(row,dict): raise ValueError(f"BELLATRA_MIN_OBJECT_REQUIRED:{idx}")
        max_frame=int(row.get("MaxFrameNum", row.get("max_frame_num",0)))
        if not 0<=max_frame<=40: raise ValueError(f"BELLATRA_MAX_FRAME_OUT_OF_RANGE:{idx}")
        frame=_pad_list(row.get("FrameMatBuff",row.get("frame_mat",[])),40,0,"BELLATRA_FrameMatBuff")
        delay=_pad_list(row.get("DelayTime",row.get("delay",[])),40,0,"BELLATRA_DelayTime")
        pos=_pair_array(row.get("PosMove",row.get("pos_move",[])),40,"BELLATRA_PosMove")
        scale=_pair_array(row.get("ScaleNum",row.get("scale",[])),40,"BELLATRA_ScaleNum")
        rot=_triple_array(row.get("Rot3d",row.get("rot3d",[])),40,"BELLATRA_Rot3d")
        blend=_pad_list(row.get("BlendNum",row.get("blend",[])),40,0,"BELLATRA_BlendNum")
        if any(not 0<=int(x)<=255 for x in blend): raise ValueError(f"BELLATRA_BLEND_OUT_OF_RANGE:{idx}")
        out += struct.pack("<ii",int(row.get("eBL_ImageType",row.get("image_type",0))),max_frame)
        out += struct.pack("<40i",*map(int,frame)); out += struct.pack("<40i",*map(int,delay))
        out += b"".join(struct.pack("<2i",*x) for x in pos)
        out += b"".join(struct.pack("<2i",*x) for x in scale)
        out += b"".join(struct.pack("<3i",*x) for x in rot)
        out += bytes(map(int,blend))
    for idx,row in enumerate(font_rows):
        if not isinstance(row,dict): raise ValueError(f"BELLATRA_FONT_OBJECT_REQUIRED:{idx}")
        count=int(row.get("Max_MinEffect_Info",row.get("max_min_effect_info",0)))
        if not 0<=count<=20: raise ValueError(f"BELLATRA_MIN_EFFECT_COUNT_OUT_OF_RANGE:{idx}")
        info=_pad_list(row.get("MinEffect_InfoBuff",row.get("min_effect_info",[])),20,0,"BELLATRA_MinEffect_InfoBuff")
        pri=_pad_list(row.get("eMinEffect_PriorityBuff",row.get("priority",[])),20,0,"BELLATRA_Priority")
        pos=_pair_array(row.get("Pos",row.get("pos",[])),20,"BELLATRA_Pos")
        size=_pair_array(row.get("Size",row.get("size",[])),20,"BELLATRA_Size")
        out += struct.pack("<ii",int(row.get("eBL_Type",row.get("type",0))),count)
        out += struct.pack("<20i",*map(int,info)); out += struct.pack("<20i",*map(int,pri))
        out += b"".join(struct.pack("<2i",*x) for x in pos)
        out += b"".join(struct.pack("<2i",*x) for x in size)
    if len(out)!=93920: raise AssertionError(f"BELLATRA_SIZE_DRIFT:{len(out)}")
    return bytes(out), {"writer":"BELLATRA_WIN32_ABI","min_effect_records":50,"font_effect_records":40,"file_size":len(out)}



def _compile_verified_artifact(contract_id: str, payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    source = pathlib.Path(str(payload.get("source_path") or "")).expanduser().resolve()
    expected = str(payload.get("expected_sha256") or "").strip().lower()
    if not source.is_file():
        raise FileNotFoundError(f"ARTIFACT_SOURCE_NOT_FOUND:{source}")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("ARTIFACT_EXPECTED_SHA256_REQUIRED")
    data = source.read_bytes()
    actual = _sha(data)
    if actual != expected:
        raise ValueError(f"ARTIFACT_SOURCE_SHA256_DRIFT:{expected}:{actual}")
    max_bytes = int(payload.get("max_bytes") or 512 * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(f"ARTIFACT_SOURCE_TOO_LARGE:{len(data)}>{max_bytes}")

    validation: dict[str, Any] = {"status": "PASS"}
    if contract_id in {"model.smd.062", "model.smb.bone"}:
        from .static_roundtrip import _parse as parse_model062
        parsed = parse_model062(data)
        if contract_id == "model.smb.bone" and int(parsed.get("mat_count") or 0) != 0:
            raise ValueError("SMB_MATERIAL_COUNT_MUST_BE_ZERO")
        validation.update({
            "format": "SMD_MODEL_062",
            "object_count": int(parsed.get("n") or 0),
            "material_count": int(parsed.get("mat_count") or 0),
            "physique_object_count": sum(1 for row in (parsed.get("object_list") or []) if row.get("phys")),
        })
    elif contract_id == "stage.smd.072":
        from .stage072_corpus import parse_stage072
        parsed = parse_stage072(source, include_payload=False)
        if parsed.get("full_parse") != "PASS":
            raise ValueError(f"STAGE072_STRUCTURAL_PARSE_NOT_PASS:{parsed.get('errors')}")
        used_materials = {int(k) for k, v in (parsed.get("material_face_counts") or {}).items() if int(v or 0) > 0}
        required_textures: list[str] = []
        seen_textures: set[str] = set()
        for mat in parsed.get("materials") or []:
            if int(mat.get("id") or 0) not in used_materials:
                continue
            for tex in list(mat.get("textures") or []) + list(mat.get("anim_textures") or []):
                name = str(tex.get("Name") or "").strip().replace("\\", "/").lstrip("/")
                if name and name.casefold() not in seen_textures:
                    seen_textures.add(name.casefold()); required_textures.append(name)
        validation.update({
            "format": "SMD_STAGE_072", "counts": parsed.get("counts"), "full_parse": parsed.get("full_parse"),
            "used_material_ids": sorted(used_materials), "required_textures": required_textures,
        })
    elif contract_id == "texture.standard":
        try:
            from PIL import Image
            with Image.open(source) as im:
                im.verify()
            with Image.open(source) as im:
                validation.update({"format": str(im.format or ""), "width": int(im.width), "height": int(im.height), "mode": str(im.mode)})
        except Exception as exc:
            raise ValueError(f"STANDARD_TEXTURE_DECODE_FAILED:{type(exc).__name__}:{exc}") from exc
    elif contract_id == "audio.wav":
        import wave
        try:
            with wave.open(str(source), "rb") as wav:
                validation.update({
                    "format": "WAV", "channels": wav.getnchannels(), "sample_width": wav.getsampwidth(),
                    "sample_rate": wav.getframerate(), "frame_count": wav.getnframes(),
                })
        except Exception as exc:
            raise ValueError(f"WAV_PARSE_FAILED:{type(exc).__name__}:{exc}") from exc
    else:
        raise KeyError(contract_id)
    return data, {
        "writer": "VERIFIED_ARTIFACT_IMPORT",
        "contract_id": contract_id,
        "source_path": str(source),
        "source_sha256": actual,
        "source_size": len(data),
        "structural_validation": validation,
        "source_artifact_verified": True,
    }


def _compile_model062_contract(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(payload.get("mesh"), dict) or isinstance(payload.get("objects"), list):
        return compile_static_model062(payload)
    return _compile_verified_artifact("model.smd.062", payload)


def _compile_model062_skeleton_contract(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(payload.get("skeleton"), dict) or isinstance(payload.get("bones"), list):
        return compile_skeleton_model062(payload)
    return _compile_verified_artifact("model.smb.bone", payload)


def _compile_stage072_contract(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(payload.get("stage"), dict) or isinstance(payload.get("vertices"), list) or isinstance(payload.get("faces"), list):
        return compile_stage072(payload)
    return _compile_verified_artifact("stage.smd.072", payload)


def _compile_model_cache_recipe(payload: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    source_output = str(payload.get("source_config_output") or "").strip().replace("\\", "/")
    source_payload = payload.get("source_config_payload")
    if not source_output or not isinstance(source_payload, dict):
        raise ValueError("MODEL_CACHE_REQUIRES_source_config_output_AND_source_config_payload")
    expected = pathlib.PurePosixPath(source_output).with_suffix(".inx").as_posix()
    requested = str(payload.get("logical_cache") or expected).strip().replace("\\", "/")
    if requested.casefold() != expected.casefold():
        raise ValueError(f"MODEL_CACHE_OUTPUT_MUST_MATCH_CONFIG:{requested}:{expected}")
    config_bytes, config_meta = _compile_model_config(dict(source_payload))
    data, meta = compile_model_cache(
        source_output,
        config_bytes,
        item_catalog=source_registry("item_catalog"),
        skill_catalog=source_registry("model_motion_skills"),
        checksum_path_policy=str(payload.get("checksum_path_policy") or "WIN32_CANONICAL"),
    )
    meta["source_config_writer"] = config_meta.get("writer")
    return data, meta

def _compiler_for(contract_id: str) -> Callable[[dict[str, Any]], tuple[bytes, dict[str, Any]]]:
    if contract_id == "model.smd.062": return _compile_model062_contract
    if contract_id == "model.smb.bone": return _compile_model062_skeleton_contract
    if contract_id == "stage.smd.072": return _compile_stage072_contract
    if contract_id in {"texture.standard", "audio.wav"}:
        return lambda payload: _compile_verified_artifact(contract_id, payload)
    if contract_id == "model.config.ini": return _compile_model_config
    if contract_id == "model.cache.inx": return _compile_model_cache_recipe
    if contract_id == "server.main_config": return _compile_server_main_config
    if contract_id == "server.skill_config": return _compile_skill_config
    if contract_id in _OPERATIONAL_INI_CONTRACTS: return lambda payload: _compile_operational_ini(contract_id, payload)
    if contract_id in {"character.monster.inf", "character.npc.npc"}: return lambda payload: _compile_character_definition(contract_id, payload)
    if contract_id == "item.definition.txt": return _compile_item_definition
    if contract_id in _TEXT_CONTRACTS: return _compile_text
    if contract_id == "field.spawn.spm": return _compile_spm
    if contract_id == "field.startpoints.spp": return _compile_spp
    if contract_id == "field.fixed_npc.spc": return _compile_spc
    if contract_id == "ui.help.sin": return _compile_sin
    if contract_id == "ui.fontimagepos.dat": return _compile_font_image_pos
    if contract_id == "ui.map.stageinfo.dat": return _compile_stage_info
    if contract_id == "event.bellatra.dat": return _compile_bellatra
    raise KeyError(contract_id)


def _recipe_obj(recipe: dict[str, Any] | str | pathlib.Path) -> dict[str, Any]:
    if isinstance(recipe, dict): return dict(recipe)
    path=pathlib.Path(recipe).expanduser().resolve()
    obj=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj,dict): raise ValueError("ASSET_RECIPE_ROOT_MUST_BE_OBJECT")
    return obj


def plan_asset_recipe(recipe: dict[str, Any] | str | pathlib.Path) -> dict[str, Any]:
    obj=_recipe_obj(recipe)
    errors=[]; warnings=[]
    if str(obj.get("format") or RECIPE_FORMAT) != RECIPE_FORMAT:
        errors.append("RECIPE_FORMAT_INVALID")
    cid=str(obj.get("contract_id") or "").strip()
    try:
        contract=get_contract(cid).public()
    except KeyError:
        contract=None; errors.append("CONTRACT_NOT_FOUND")
    rel=None; side=None
    if contract is not None:
        try: rel=_safe_rel(str(obj.get("output") or ""))
        except Exception as exc: errors.append(str(exc))
        try: side=_infer_side(contract,obj.get("target_side"))
        except Exception as exc: errors.append(str(exc))
        if rel is not None:
            suffixes=_allowed_suffixes(contract)
            if suffixes and rel.suffix.casefold() not in suffixes:
                errors.append(f"OUTPUT_SUFFIX_MISMATCH:{rel.suffix}:{','.join(sorted(suffixes))}")
            if cid in {"model.smd.062", "model.smb.bone", "stage.smd.072", "texture.standard", "audio.wav"} and isinstance(obj.get("payload"), dict):
                src = pathlib.Path(str((obj.get("payload") or {}).get("source_path") or ""))
                if src.suffix and src.suffix.casefold() != rel.suffix.casefold():
                    errors.append(f"ARTIFACT_SOURCE_OUTPUT_SUFFIX_MISMATCH:{src.suffix}:{rel.suffix}")
        if cid not in _DIRECT_COMPILERS:
            errors.append("DIRECT_COMPILER_NOT_IMPLEMENTED")
        source_cap=str(contract.get("capability") or "")
        if source_cap in {"RUNTIME_STATE_NOT_ASSET","RUNTIME_DIAGNOSTIC_NOT_ASSET","DORMANT_SOURCE_CONTRACT"}:
            errors.append(f"CONTRACT_NOT_AUTHORABLE:{source_cap}")
        if cid in _CODE_BOUNDARY_CONTRACTS:
            warnings.append("CODE_ID_BOUNDARY_PRESENT")
    payload=obj.get("payload")
    if not isinstance(payload,dict): errors.append("PAYLOAD_OBJECT_REQUIRED")
    # Compile in-memory during plan. This turns plan into a real contract validator.
    preview=None
    if not errors and contract is not None:
        try:
            data,meta=_compiler_for(cid)(payload)
            preview={"size":len(data),"sha256":_sha(data),"writer":meta}
            if str(meta.get("code_identity_status") or "").startswith("CODE_BOUNDARY"):
                warnings.append("CODE_ID_BOUNDARY_UNREGISTERED")
            if str(meta.get("code_identity_status") or "").startswith("SOURCE_AMBIGUOUS"):
                warnings.append("SOURCE_ITEM_CODE_AMBIGUOUS")
        except Exception as exc:
            errors.append(f"PAYLOAD_INVALID:{type(exc).__name__}:{exc}")
    return {
        "format": PLAN_FORMAT,
        "status": "READY" if not errors else "BLOCKED",
        "contract_id": cid,
        "contract": contract,
        "target_side": side,
        "output": rel.as_posix() if rel else None,
        "preview": preview,
        "schema": schema_for_contract(cid) if contract is not None else None,
        "warnings": warnings,
        "errors": errors,
        "target_write_authorized": False,
    }


def compile_asset_recipe(project_root: pathlib.Path | str, recipe: dict[str, Any] | str | pathlib.Path) -> dict[str, Any]:
    project_root=pathlib.Path(project_root).resolve()
    obj=_recipe_obj(recipe)
    plan=plan_asset_recipe(obj)
    if plan["status"] != "READY":
        raise ValueError("ASSET_RECIPE_BLOCKED:"+"|".join(plan["errors"]))
    cid=str(plan["contract_id"]); side=str(plan["target_side"]); rel=_safe_rel(str(plan["output"])); payload=dict(obj["payload"])
    data,writer=_compiler_for(cid)(payload)
    recipe_id=str(obj.get("id") or rel.stem or cid)
    digest=hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()[:10]
    stamp=time.strftime("%Y%m%d_%H%M%S")
    run_id=f"{stamp}_{_safe_id(recipe_id)}_{digest}"
    root=project_root/"pt_build"/"asset_compiler"/"runs"/run_id
    output=root/"overlay"/side.lower()/pathlib.Path(*rel.parts)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(data)
    recipe_path=root/"recipe.json"; manifest_path=root/"manifest.json"
    root.mkdir(parents=True,exist_ok=True)
    recipe_path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest={
        "format":BUILD_FORMAT,"status":"PASS","run_id":run_id,"contract_id":cid,
        "contract":plan["contract"],"target_side":side,"logical_output":rel.as_posix(),
        "output":str(output),"output_size":len(data),"output_sha256":_sha(data),"writer":writer,
        "recipe":str(recipe_path),"schema":plan.get("schema"),"warnings":plan.get("warnings") or [],
        "scope":"PT_BUILD_ASSET_COMPILER_OVERLAY_ONLY","client_modified":False,"server_modified":False,
        "target_write_authorized":False,
    }
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest["manifest"]=str(manifest_path)
    # Rewrite once with self path included.
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest



# ---- Typed multi-asset bundles -------------------------------------------------

def _resolve_root_file(root: pathlib.Path | str | None, logical: str) -> pathlib.Path | None:
    if root is None:
        return None
    root = pathlib.Path(root).resolve()
    rel = _safe_rel(logical)
    cur = root
    for part in rel.parts:
        direct = cur / part
        if direct.exists():
            cur = direct
            continue
        if not cur.is_dir():
            return None
        matches = [x for x in cur.iterdir() if x.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        cur = matches[0]
    try:
        cur.resolve().relative_to(root)
    except Exception:
        return None
    return cur.resolve() if cur.is_file() else None


def _decode_legacy_text(data: bytes) -> tuple[str, str]:
    for enc in ("cp949", "cp1252", "latin1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise ValueError("LEGACY_TEXT_ENCODING_UNRESOLVED")


def _patch_existing_spm(server_root: pathlib.Path | str | None, logical: str, *, actor_name: str, weight: int) -> tuple[bytes, dict[str, Any]]:
    source = _resolve_root_file(server_root, logical)
    if source is None:
        raise ValueError(f"SPM_PATCH_SOURCE_NOT_FOUND:{logical}")
    raw = source.read_bytes()
    text, encoding = _decode_legacy_text(raw)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    normal_actor_heads = {"*ACTOR", "*출연자"}
    boss_actor_heads = {"*BOSS_ACTOR", "*출연자두목"}

    def _head(line: str) -> str:
        return (line.strip().split(None, 1)[0].upper() if line.strip() else "")

    normal_actor_lines = [x for x in lines if _head(x) in normal_actor_heads]
    boss_actor_lines = [x for x in lines if _head(x) in boss_actor_heads]
    # Source arrays are independent: 50 normal actors and 16 boss actors.
    if len(normal_actor_lines) >= 50:
        raise ValueError("SPM_ACTOR_LIMIT_REACHED:50")

    def _directive_actor_name(line: str) -> str | None:
        stripped = line.strip()
        if _head(line) not in normal_actor_heads:
            return None
        tail = stripped.split(None, 1)[1] if len(stripped.split(None, 1)) > 1 else ""
        m = re.match(r'^["\']([^"\']+)["\']', tail)
        if m:
            return m.group(1).strip()
        parts = tail.split()
        return parts[0].strip() if parts else None

    for line in normal_actor_lines:
        existing = _directive_actor_name(line)
        if existing and existing.casefold() == actor_name.strip().casefold():
            raise ValueError("SPM_ACTOR_ALREADY_PRESENT")
    actor_name = _actor_name(actor_name, encoding)
    weight = int(weight)
    if weight <= 0:
        raise ValueError("SPM_ACTOR_WEIGHT_MUST_BE_POSITIVE")
    insert_at = -1
    for i, line in enumerate(lines):
        if _head(line) in normal_actor_heads | boss_actor_heads:
            insert_at = i
    lines.insert(insert_at + 1 if insert_at >= 0 else len(lines), f'*ACTOR "{actor_name}" {weight}')
    out_text = newline.join(lines) + (newline if text.endswith(("\n", "\r")) else "")
    data = out_text.encode(encoding)
    return data, {
        "writer":"SPM_PATCH_EXISTING_SOURCE_PRESERVING", "encoding":encoding,
        "source":str(source), "actor_name":actor_name, "actor_weight":weight,
        "preexisting_actor_directive_count":len(normal_actor_lines),
        "preexisting_boss_actor_directive_count":len(boss_actor_lines),
        "result_size":len(data), "source_sha256":_sha(raw),
    }


def _patch_existing_spc(server_root: pathlib.Path | str | None, logical: str, row: dict[str, Any], *, slot_index: int | None = None, record_encoding: str = "cp949") -> tuple[bytes, dict[str, Any]]:
    source = _resolve_root_file(server_root, logical)
    if source is None:
        raise ValueError(f"SPC_PATCH_SOURCE_NOT_FOUND:{logical}")
    raw = source.read_bytes()
    if len(raw) != SPC_RECORD_COUNT * SPC_RECORD_SIZE:
        raise ValueError(f"SPC_PATCH_SOURCE_SIZE_INVALID:{len(raw)}")
    data = bytearray(raw)
    used=[]; free=[]
    for idx in range(SPC_RECORD_COUNT):
        base=idx*SPC_RECORD_SIZE
        code=struct.unpack_from("<I", data, base+4)[0]
        (used if code else free).append(idx)
    if slot_index is None:
        if not free:
            raise ValueError("SPC_NO_FREE_SLOT")
        slot=free[0]
    else:
        slot=int(slot_index)
        if not 0 <= slot < SPC_RECORD_COUNT:
            raise ValueError(f"SPC_INDEX_OUT_OF_RANGE:{slot}")
        if slot not in free:
            raise ValueError(f"SPC_SLOT_NOT_FREE:{slot}")
    rec=build_spc_record({**row, "index":slot}, record_encoding=record_encoding)
    data[slot*SPC_RECORD_SIZE:(slot+1)*SPC_RECORD_SIZE]=rec
    return bytes(data), {
        "writer":"SPC_PATCH_EXISTING_WIN32_ABI", "source":str(source),
        "slot_index":slot, "preexisting_used_slots":len(used), "remaining_free_slots":len(free)-1,
        "record_encoding":record_encoding, "file_size":len(data), "source_sha256":_sha(raw),
    }


def _bundle_asset_recipe(bundle_id: str, ordinal: int, contract_id: str, side: str, output: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "format":RECIPE_FORMAT, "id":f"{bundle_id}_{ordinal:02d}",
        "contract_id":contract_id, "target_side":side, "output":output, "payload":payload,
    }


def _bundle_children(obj: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    bundle_id=_safe_id(str(obj.get("id") or "bundle"))
    kind=str(obj.get("bundle_type") or obj.get("kind") or "CUSTOM").strip().upper()
    payload=obj.get("payload") if isinstance(obj.get("payload"),dict) else {}
    children: list[dict[str, Any]]=[]
    patch_ops: list[dict[str, Any]]=[]
    warnings: list[str]=[]
    errors: list[str]=[]

    generic=obj.get("assets")
    if generic is not None:
        if not isinstance(generic,list):
            errors.append("BUNDLE_assets_MUST_BE_LIST")
        else:
            for idx,row in enumerate(generic):
                if not isinstance(row,dict):
                    errors.append(f"BUNDLE_ASSET_OBJECT_REQUIRED:{idx}"); continue
                child=dict(row); child.setdefault("format",RECIPE_FORMAT); child.setdefault("id",f"{bundle_id}_{idx:02d}")
                children.append(child)

    # High-level visual package shorthand.  The user describes one visual unit;
    # the compiler expands it into typed source-proven contracts before closure.
    visual = payload.get("visual") if isinstance(payload.get("visual"), dict) else None
    if visual:
        def artifact_from_visual(key: str, contract_id: str) -> str | None:
            spec = visual.get(key)
            if spec is None:
                return None
            if not isinstance(spec, dict):
                errors.append(f"BUNDLE_VISUAL_{key.upper()}_OBJECT_REQUIRED")
                return None
            output = str(spec.get("output") or "").strip().replace("\\", "/")
            if not output:
                errors.append(f"BUNDLE_VISUAL_{key.upper()}_OUTPUT_REQUIRED")
                return None
            apayload = {k: v for k, v in spec.items() if k not in {"output", "target_policy"}}
            child = _bundle_asset_recipe(bundle_id, len(children), contract_id, "CLIENT", output, apayload)
            if spec.get("target_policy"):
                child["target_policy"] = str(spec["target_policy"])
            children.append(child)
            return output

        model_output = artifact_from_visual("model", "model.smd.062")
        skeleton_output = artifact_from_visual("skeleton", "model.smb.bone")
        textures = visual.get("textures") or []
        if not isinstance(textures, list):
            errors.append("BUNDLE_VISUAL_TEXTURES_LIST_REQUIRED")
        else:
            for tidx, spec in enumerate(textures):
                if not isinstance(spec, dict):
                    errors.append(f"BUNDLE_VISUAL_TEXTURE_OBJECT_REQUIRED:{tidx}")
                    continue
                output = str(spec.get("output") or "").strip().replace("\\", "/")
                if not output:
                    errors.append(f"BUNDLE_VISUAL_TEXTURE_OUTPUT_REQUIRED:{tidx}")
                    continue
                tpay = {k: v for k, v in spec.items() if k not in {"output", "target_policy"}}
                child = _bundle_asset_recipe(bundle_id, len(children), "texture.standard", "CLIENT", output, tpay)
                if spec.get("target_policy"):
                    child["target_policy"] = str(spec["target_policy"])
                children.append(child)

        config_spec = visual.get("config")
        visual_config_output = None
        if config_spec is not None:
            if not isinstance(config_spec, dict):
                errors.append("BUNDLE_VISUAL_CONFIG_OBJECT_REQUIRED")
            else:
                visual_config_output = str(config_spec.get("output") or "").strip().replace("\\", "/")
                if not visual_config_output:
                    if model_output:
                        visual_config_output = pathlib.PurePosixPath(model_output).with_suffix(".ini").as_posix()
                    else:
                        errors.append("BUNDLE_VISUAL_CONFIG_OUTPUT_REQUIRED_WITHOUT_MODEL")
                if visual_config_output:
                    cpay = dict(config_spec.get("payload") or {}) if isinstance(config_spec.get("payload"), dict) else {
                        k: v for k, v in config_spec.items() if k not in {"output", "target_policy", "payload"}
                    }
                    cfg_parent = pathlib.PurePosixPath(visual_config_output).parent
                    def relative_ref(target: str) -> str:
                        import posixpath
                        return posixpath.relpath(pathlib.PurePosixPath(target).as_posix(), cfg_parent.as_posix() or ".")
                    if model_output:
                        derived = relative_ref(model_output)
                        if cpay.get("model_file") not in {None, "", derived}:
                            errors.append("BUNDLE_VISUAL_CONFIG_MODEL_MISMATCH")
                        cpay["model_file"] = derived
                    if skeleton_output:
                        derived = relative_ref(skeleton_output)
                        if cpay.get("motion_file") not in {None, "", derived}:
                            errors.append("BUNDLE_VISUAL_CONFIG_SKELETON_MISMATCH")
                        cpay["motion_file"] = derived
                    child = _bundle_asset_recipe(bundle_id, len(children), "model.config.ini", "CLIENT", visual_config_output, cpay)
                    if config_spec.get("target_policy"):
                        child["target_policy"] = str(config_spec["target_policy"])
                    children.append(child)
                    existing_model_file = str(payload.get("model_file") or "").strip().replace("\\", "/")
                    if existing_model_file and existing_model_file.casefold() != visual_config_output.casefold():
                        errors.append("BUNDLE_VISUAL_TOPLEVEL_MODEL_CONFIG_MISMATCH")
                    elif not existing_model_file:
                        payload = dict(payload)
                        payload["model_file"] = visual_config_output

    identity=payload.get("identity") if isinstance(payload.get("identity"),dict) else {}
    name=str(identity.get("name") or payload.get("name") or "").strip()
    entity_id=_safe_id(str(identity.get("id") or payload.get("id") or bundle_id))
    model_file=str(payload.get("model_file") or "").strip().replace("\\","/")

    if kind in {"MONSTER","NPC"}:
        if not name: errors.append("BUNDLE_CHARACTER_NAME_REQUIRED")
        if not model_file: errors.append("BUNDLE_CHARACTER_MODEL_FILE_REQUIRED")
        definition=payload.get("definition") if isinstance(payload.get("definition"),dict) else {}
        output=str(definition.get("output") or (f"GameServer/Monster/{entity_id}.inf" if kind=="MONSTER" else f"GameServer/NPC/{entity_id}.npc"))
        fields=dict(definition.get("fields") or {})
        for key,expected in (("name",name),("model_file",model_file)):
            if fields.get(key) not in {None,"",expected}: errors.append(f"BUNDLE_DEFINITION_{key.upper()}_MISMATCH")
            fields[key]=expected
        def_payload={k:v for k,v in definition.items() if k not in {"output","fields"}}; def_payload["fields"]=fields
        children.append(_bundle_asset_recipe(bundle_id,len(children),"character.monster.inf" if kind=="MONSTER" else "character.npc.npc","SERVER",output,def_payload))
        placement=payload.get("placement") if isinstance(payload.get("placement"),dict) else {}
        placement_output=str(placement.get("output") or "").strip()
        if not placement_output:
            errors.append("BUNDLE_PLACEMENT_OUTPUT_REQUIRED")
        elif kind=="MONSTER":
            mode=str(placement.get("mode") or "PATCH_EXISTING").upper()
            if mode=="PATCH_EXISTING":
                patch_ops.append({"kind":"SPM_ADD_ACTOR","side":"SERVER","output":placement_output,"actor_name":name,"weight":int(placement.get("weight") or 100)})
            elif mode=="NEW_FILE":
                spm_payload=dict(placement.get("payload") or {})
                actors=list(spm_payload.get("actors") or []); actors.append({"name":name,"weight":int(placement.get("weight") or 100)}); spm_payload["actors"]=actors
                children.append(_bundle_asset_recipe(bundle_id,len(children),"field.spawn.spm","SERVER",placement_output,spm_payload))
            else: errors.append("BUNDLE_MONSTER_PLACEMENT_MODE_INVALID")
        else:
            mode=str(placement.get("mode") or "PATCH_EXISTING").upper()
            row={
                "name":name, "model_ini":model_file, "server_npc":output,
                "x":int(placement.get("x") or 0), "y":int(placement.get("y") or 0), "z":int(placement.get("z") or 0),
                "ax":int(placement.get("ax") or 0), "ay":int(placement.get("ay") or 0), "az":int(placement.get("az") or 0),
                "state":int(placement.get("state") or 0),
            }
            if mode=="PATCH_EXISTING":
                patch_ops.append({"kind":"SPC_ADD_NPC","side":"SERVER","output":placement_output,"row":row,"slot_index":placement.get("slot_index"),"record_encoding":str(placement.get("record_encoding") or "cp949")})
            elif mode=="NEW_FILE":
                if placement.get("slot_index") is not None: row["index"]=int(placement["slot_index"])
                children.append(_bundle_asset_recipe(bundle_id,len(children),"field.fixed_npc.spc","SERVER",placement_output,{"records":[row],"record_encoding":str(placement.get("record_encoding") or "cp949")}))
            else: errors.append("BUNDLE_NPC_PLACEMENT_MODE_INVALID")
    elif kind=="ITEM":
        definition=payload.get("definition") if isinstance(payload.get("definition"),dict) else {}
        fields=dict(definition.get("fields") or {})
        if name and fields.get("name") in {None,""}: fields["name"]=name
        output=str(definition.get("output") or f"GameServer/OpenItem/{entity_id}.txt")
        def_payload={k:v for k,v in definition.items() if k not in {"output","fields"}}; def_payload["fields"]=fields
        children.append(_bundle_asset_recipe(bundle_id,len(children),"item.definition.txt","SERVER",output,def_payload))
        code_text = str(fields.get("code") or "").strip()
        legacy_category = classify_item_code(code_text) if code_text else None
        if legacy_category and legacy_category.get("status") == "LEGACY_PREFIX_CLASSIFIED":
            warnings.append(f"LEGACY_ITEM_CATEGORY:{legacy_category.get('group')}:{legacy_category.get('category')}")
        elif code_text:
            warnings.append("LEGACY_ITEM_CATEGORY_UNCLASSIFIED_OR_AMBIGUOUS")
        warnings.append("ITEM_CODE_MUST_EXIST_IN_RUNTIME_TABLE")
    elif kind=="FIELD":
        outputs=payload.get("outputs") if isinstance(payload.get("outputs"),dict) else {}
        stage_asset = payload.get("stage_asset") if isinstance(payload.get("stage_asset"), dict) else None
        if stage_asset:
            stage_output = str(stage_asset.get("output") or payload.get("stage_file") or "").strip()
            if not stage_output:
                errors.append("BUNDLE_FIELD_STAGE_OUTPUT_REQUIRED")
            else:
                stage_payload = {k: v for k, v in stage_asset.items() if k not in {"output", "target_policy"}}
                child = _bundle_asset_recipe(bundle_id,len(children),"stage.smd.072","CLIENT",stage_output,stage_payload)
                if stage_asset.get("target_policy"): child["target_policy"] = str(stage_asset["target_policy"])
                children.append(child)
        if "spm" in outputs:
            children.append(_bundle_asset_recipe(bundle_id,len(children),"field.spawn.spm","SERVER",str(outputs["spm"]),dict(payload.get("spm") or {})))
        if "spp" in outputs:
            children.append(_bundle_asset_recipe(bundle_id,len(children),"field.startpoints.spp","SERVER",str(outputs["spp"]),dict(payload.get("spp") or {})))
        if "spc" in outputs:
            children.append(_bundle_asset_recipe(bundle_id,len(children),"field.fixed_npc.spc","SERVER",str(outputs["spc"]),dict(payload.get("spc") or {})))
        stage_info = payload.get("stage_info") if isinstance(payload.get("stage_info"), dict) else None
        if stage_info:
            info_output = str(stage_info.get("output") or "game/StageInfo.dat").strip()
            info_payload = {k: v for k, v in stage_info.items() if k not in {"output", "target_policy"}}
            child = _bundle_asset_recipe(bundle_id,len(children),"ui.map.stageinfo.dat","CLIENT",info_output,info_payload)
            if stage_info.get("target_policy"): child["target_policy"] = str(stage_info["target_policy"])
            children.append(child)
        if not any(k in outputs for k in ("spm","spp","spc")) and not stage_asset:
            errors.append("BUNDLE_FIELD_REQUIRES_STAGE_OR_SERVER_OUTPUT")
        warnings.append("FIELD_RUNTIME_ID_CODE_BOUNDARY_MAY_APPLY")
    elif kind not in {"CUSTOM"}:
        errors.append(f"BUNDLE_TYPE_UNSUPPORTED:{kind}")

    # A model config and its INX cache are one authoring contract.  The source
    # writes the cache deterministically from smMODELINFO; emit it automatically
    # unless the recipe explicitly opts out or already supplied the exact path.
    existing_client_outputs = {
        _safe_rel(str(row.get("output") or "")).as_posix().casefold()
        for row in children
        if str(row.get("target_side") or "").upper() == "CLIENT" and str(row.get("output") or "").strip()
    }
    derived_cache_children: list[dict[str, Any]] = []
    for row in list(children):
        if str(row.get("contract_id") or "") != "model.config.ini" or str(row.get("target_side") or "").upper() != "CLIENT":
            continue
        source_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if source_payload.get("emit_cache") is False:
            warnings.append(f"MODEL_INX_EXPLICITLY_DISABLED:{row.get('output')}")
            continue
        source_output = _safe_rel(str(row.get("output") or "")).as_posix()
        cache_output = pathlib.PurePosixPath(source_output).with_suffix(".inx").as_posix()
        if cache_output.casefold() in existing_client_outputs:
            continue
        cache_payload = {
            "source_config_output": source_output,
            "source_config_payload": {k: v for k, v in source_payload.items() if k != "emit_cache"},
            "logical_cache": cache_output,
        }
        cache_child = _bundle_asset_recipe(bundle_id, len(children) + len(derived_cache_children), "model.cache.inx", "CLIENT", cache_output, cache_payload)
        cache_child["target_policy"] = "AUTO"
        cache_child["derived_from"] = source_output
        derived_cache_children.append(cache_child)
        existing_client_outputs.add(cache_output.casefold())
    children.extend(derived_cache_children)

    # Ensure no two generated assets target the same side/path.
    keys=[]
    for child in children:
        try: keys.append((str(child.get("target_side") or "").upper(),_safe_rel(str(child.get("output") or "")).as_posix().casefold()))
        except Exception: pass
    for op in patch_ops:
        try: keys.append((str(op.get("side") or "").upper(),_safe_rel(str(op.get("output") or "")).as_posix().casefold()))
        except Exception: pass
    if len(keys)!=len(set(keys)): errors.append("BUNDLE_DUPLICATE_OUTPUT_PATH")
    return children,patch_ops,warnings,errors


def _bundle_client_generated(children: list[dict[str, Any]]) -> dict[str, tuple[bytes, dict[str, Any], dict[str, Any]]]:
    out: dict[str, tuple[bytes, dict[str, Any], dict[str, Any]]] = {}
    for child in children:
        if str(child.get("target_side") or "").upper() != "CLIENT":
            continue
        try:
            logical = _safe_rel(str(child.get("output") or "")).as_posix()
            cid = str(child.get("contract_id") or "")
            data, writer = _compiler_for(cid)(dict(child.get("payload") or {}))
            out[logical.casefold()] = (data, writer, child)
        except Exception:
            # The child plan will carry the authoritative compiler error.
            continue
    return out


def _join_model_config_ref(config_logical: str, value: str) -> str:
    ref = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not ref:
        raise ValueError("MODEL_CONFIG_REFERENCE_EMPTY")
    parent = pathlib.PurePosixPath(config_logical).parent
    return _safe_rel((parent / pathlib.PurePosixPath(ref)).as_posix()).as_posix()


def _bundle_read_client_file(
    logical: str,
    generated: dict[str, tuple[bytes, dict[str, Any], dict[str, Any]]],
    client_root: pathlib.Path | str | None,
) -> tuple[bytes, str, dict[str, Any] | None] | None:
    key = _safe_rel(logical).as_posix().casefold()
    if key in generated:
        data, _writer, child = generated[key]
        return data, "BUNDLE_GENERATED", child
    hit = _resolve_root_file(client_root, logical)
    if hit is not None:
        return hit.read_bytes(), "LIVE_CLIENT_READ_ONLY", None
    return None



def _model062_face_texture_refs(data: bytes) -> dict[str, Any]:
    """Decode face-used material texture names from a Model 0.62 payload.

    This is intentionally byte-local and source-derived: it does not consult the
    registry or guess by basename.  Only materials referenced by serialized faces
    contribute runtime texture dependencies.
    """
    header = b"SMD Model data Ver 0.62"
    if len(data) < 556 or not data.startswith(header):
        raise ValueError("MODEL062_HEADER_INVALID")
    obj_count = struct.unpack_from("<i", data, 24)[0]
    mat_count = struct.unpack_from("<i", data, 28)[0]
    mat_point = struct.unpack_from("<i", data, 32)[0]
    first_obj = struct.unpack_from("<i", data, 36)[0]
    if not 0 <= obj_count <= 4096 or not 0 <= mat_count <= 5000:
        raise ValueError("MODEL062_COUNT_OUT_OF_RANGE")
    if not 556 <= mat_point <= first_obj <= len(data):
        raise ValueError("MODEL062_MATERIAL_REGION_INVALID")

    used: set[int] = set()
    for i in range(obj_count):
        info = 556 + i * 40
        if info + 40 > len(data):
            raise ValueError("MODEL062_OBJECT_INFO_TRUNCATED")
        start = struct.unpack_from("<i", data, info + 36)[0]
        if start < 0 or start + 2236 > len(data):
            raise ValueError("MODEL062_OBJECT_START_INVALID")
        nv = struct.unpack_from("<i", data, start + 84)[0]
        nf = struct.unpack_from("<i", data, start + 88)[0]
        if nv < 0 or nf < 0:
            raise ValueError("MODEL062_NEGATIVE_GEOMETRY_COUNT")
        face_off = start + 2236 + nv * 24
        if face_off + nf * 36 > len(data):
            raise ValueError("MODEL062_FACE_ARRAY_TRUNCATED")
        for fi in range(nf):
            used.add(struct.unpack_from("<H", data, face_off + fi * 36 + 6)[0])

    if not used:
        return {"status": "PASS", "used_material_ids": [], "required_names": []}
    if mat_count == 0:
        raise ValueError("MODEL062_FACE_REFERENCES_MISSING_MATERIAL_TABLE")
    if max(used) >= mat_count:
        raise ValueError(f"MODEL062_FACE_MATERIAL_ID_OOB:{max(used)}>={mat_count}")
    if mat_point + 88 > first_obj:
        raise ValueError("MODEL062_MATERIAL_GROUP_TRUNCATED")
    group_count = struct.unpack_from("<i", data, mat_point + 8)[0]
    if group_count != mat_count:
        raise ValueError(f"MODEL062_MATERIAL_COUNT_MISMATCH:{group_count}:{mat_count}")

    cursor = mat_point + 88
    materials: dict[int, list[str]] = {}
    for mid in range(mat_count):
        if cursor + 320 > first_obj:
            raise ValueError(f"MODEL062_MATERIAL_TRUNCATED:{mid}")
        raw = data[cursor:cursor + 320]
        cursor += 320
        in_use = struct.unpack_from("<i", raw, 0)[0]
        tc = struct.unpack_from("<i", raw, 4)[0]
        ac = struct.unpack_from("<i", raw, 304)[0]
        if not 0 <= tc <= 8 or not 0 <= ac <= 32:
            raise ValueError(f"MODEL062_MATERIAL_TEXTURE_COUNT_INVALID:{mid}:{tc}:{ac}")
        names: list[str] = []
        if in_use:
            if cursor + 4 > first_obj:
                raise ValueError(f"MODEL062_MATERIAL_STRING_LENGTH_MISSING:{mid}")
            strlen = struct.unpack_from("<i", data, cursor)[0]
            cursor += 4
            if strlen < 0 or cursor + strlen > first_obj:
                raise ValueError(f"MODEL062_MATERIAL_STRING_BLOCK_INVALID:{mid}:{strlen}")
            block = data[cursor:cursor + strlen]
            cursor += strlen
            expected = 2 * (tc + ac)
            pos = 0
            strings: list[str] = []
            for idx in range(expected):
                end = block.find(b"\0", pos)
                if end < 0:
                    # Historical serializer can leave only the final NameA
                    # length-delimited. Never relax a primary runtime Name.
                    if idx == expected - 1 and pos < len(block):
                        end = len(block)
                    else:
                        raise ValueError(f"MODEL062_MATERIAL_STRING_UNTERMINATED:{mid}:{idx}")
                strings.append(block[pos:end].decode("latin1", "replace"))
                pos = min(end + 1, len(block))
            for i in range(0, len(strings), 2):
                name = strings[i].strip().replace("\\", "/").lstrip("/")
                if name:
                    names.append(name)
        materials[mid] = names
    if cursor != first_obj:
        trailing = data[cursor:first_obj]
        if any(trailing):
            raise ValueError(f"MODEL062_MATERIAL_REGION_TRAILING_BYTES:{len(trailing)}")

    required: list[str] = []
    seen: set[str] = set()
    for mid in sorted(used):
        for name in materials.get(mid, []):
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                required.append(name)
    return {"status": "PASS", "used_material_ids": sorted(used), "required_names": required}

def _model_visual_closure(
    model_file: str,
    children: list[dict[str, Any]],
    client_root: pathlib.Path | str | None,
) -> dict[str, Any]:
    generated = _bundle_client_generated(children)
    root_logical = _safe_rel(model_file).as_posix()
    direct = _bundle_read_client_file(root_logical, generated, client_root)
    if direct is None:
        return {"status": "BLOCKED", "reason": "MODEL_FILE_NOT_FOUND_IN_CLIENT_OR_BUNDLE", "path": root_logical}

    closure: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    warnings: list[str] = []
    visited: set[str] = set()
    inspected_models: set[str] = set()
    inspected_textures: set[str] = set()
    model_payload_count = 0
    required_bones: set[str] = set()
    available_bones: set[str] = set()

    def inspect_model_payload(logical: str, hit: tuple[bytes, str, dict[str, Any] | None], role: str) -> None:
        """Close dependencies carried by a physical SMD/SMB payload.

        Model0.62 material texture names are runtime dependencies. We resolve the
        serialized path exactly against bundle/client roots; no basename guessing
        is allowed. SMB carries no material table in the supported bone-only form.
        """
        nonlocal model_payload_count
        key = logical.casefold()
        if key in inspected_models:
            return
        inspected_models.add(key)
        data, source_kind, child = hit
        suffix = pathlib.PurePosixPath(logical).suffix.casefold()
        contract_id = str((child or {}).get("contract_id") or "") or None
        closure.append({
            "role": role, "path": logical, "status": "PASS", "source": source_kind,
            "contract_id": contract_id,
        })
        if suffix in {".smd", ".smb"}:
            model_payload_count += 1
            try:
                from .static_roundtrip import _parse as parse_model062
                pattern = parse_model062(data)
                if suffix == ".smb":
                    for obj in pattern.get("object_list") or []:
                        bone_name = str(obj.get("name") or "").strip()
                        if bone_name:
                            available_bones.add(bone_name.casefold())
                    closure.append({
                        "role": "skeleton_bones", "path": logical, "status": "PASS", "source": source_kind,
                        "bone_count": len(pattern.get("object_list") or []),
                    })
                else:
                    for obj in pattern.get("object_list") or []:
                        for bone_name in obj.get("physique_names") or []:
                            bone_name = str(bone_name or "").strip()
                            if bone_name:
                                required_bones.add(bone_name.casefold())
                    if required_bones:
                        closure.append({
                            "role": "physique_bindings", "path": logical, "status": "PASS", "source": source_kind,
                            "required_bone_count": len(required_bones),
                        })
            except Exception as exc:
                missing.append({
                    "role": "model_structure", "path": logical,
                    "reason": f"MODEL062_STRUCTURE_PARSE_FAILED:{type(exc).__name__}:{exc}",
                })
                return
        if suffix != ".smd":
            return
        # A .smd may also be Stage 0.72. Monster/NPC model configs require Model
        # 0.62, so reject any other SMD family here rather than accepting by suffix.
        try:
            refs = _model062_face_texture_refs(data)
        except Exception as exc:
            missing.append({
                "role": "model_materials", "path": logical,
                "reason": f"MODEL062_MATERIAL_PARSE_FAILED:{type(exc).__name__}:{exc}",
            })
            return
        closure.append({
            "role": "model_materials", "path": logical, "status": "PASS", "source": source_kind,
            "used_material_ids": refs.get("used_material_ids") or [],
            "required_texture_count": len(refs.get("required_names") or []),
        })
        for texture in refs.get("required_names") or []:
            try:
                tex_logical = _safe_rel(str(texture)).as_posix()
            except Exception as exc:
                missing.append({"role": "model_texture", "path": str(texture), "reason": f"MODEL_TEXTURE_PATH_INVALID:{exc}"})
                continue
            tkey = tex_logical.casefold()
            if tkey in inspected_textures:
                continue
            inspected_textures.add(tkey)
            tex_hit = _bundle_read_client_file(tex_logical, generated, client_root)
            if tex_hit is None:
                missing.append({"role": "model_texture", "path": tex_logical, "reason": "MODEL_TEXTURE_DEPENDENCY_NOT_FOUND"})
                continue
            tex_child = tex_hit[2]
            closure.append({
                "role": "model_texture", "path": tex_logical, "status": "PASS", "source": tex_hit[1],
                "contract_id": str((tex_child or {}).get("contract_id") or "") or None,
            })

    suffix = pathlib.PurePosixPath(root_logical).suffix.casefold()
    if suffix in {".smd", ".smb"}:
        inspect_model_payload(root_logical, direct, "direct_model")
        unresolved_bones = sorted(required_bones - available_bones)
        if unresolved_bones:
            missing.append({"role": "physique_skeleton", "path": root_logical, "reason": "MODEL_PHYSIQUE_BONES_UNRESOLVED", "bones": unresolved_bones})
        if missing:
            return {
                "status": "BLOCKED", "reason": "MODEL_PACKAGE_CLOSURE_INCOMPLETE", "path": root_logical,
                "closure": closure, "missing": missing, "warnings": sorted(set(warnings)),
            }
        return {
            "status": "PASS", "source": direct[1], "path": root_logical,
            "closure": closure, "missing": [], "warnings": [], "derived_cache": None,
        }
    if suffix == ".ase":
        # ASE is an authoring input, not the runtime format. Keep legacy direct
        # recognition read-only but do not make it deploy-authoritative.
        return {
            "status": "PASS", "source": direct[1], "path": root_logical,
            "closure": [{"role": "authoring_source", "path": root_logical, "status": "PASS", "source": direct[1]}],
            "warnings": ["ASE_AUTHORING_SOURCE_REQUIRES_RUNTIME_COMPILED_ARTIFACT"], "derived_cache": None,
        }
    if suffix not in {".ini", ".inf"}:
        return {"status": "BLOCKED", "reason": "MODEL_REFERENCE_SUFFIX_UNSUPPORTED", "path": root_logical}

    def visit(config_logical: str, depth: int) -> None:
        if depth > 8:
            missing.append({"role": "link_file", "path": config_logical, "reason": "MODEL_CONFIG_LINK_DEPTH_EXCEEDED"})
            return
        key = config_logical.casefold()
        if key in visited:
            return
        visited.add(key)
        hit = _bundle_read_client_file(config_logical, generated, client_root)
        if hit is None:
            missing.append({"role": "config", "path": config_logical, "reason": "MODEL_CONFIG_NOT_FOUND"})
            return
        data, source_kind, child = hit
        try:
            parsed = _parse_model_config_refs(data)
        except Exception as exc:
            missing.append({"role": "config", "path": config_logical, "reason": f"MODEL_CONFIG_PARSE_FAILED:{type(exc).__name__}:{exc}"})
            return
        closure.append({
            "role": "config", "path": config_logical, "status": "PASS", "source": source_kind,
            "encoding": parsed["encoding"], "contract_id": str((child or {}).get("contract_id") or "") or None,
        })

        cache_logical = pathlib.PurePosixPath(config_logical).with_suffix(".inx").as_posix()
        cache_generated = cache_logical.casefold() in generated
        cache_live = _resolve_root_file(client_root, cache_logical) if client_root is not None else None
        if source_kind == "BUNDLE_GENERATED" and cache_live is not None and not cache_generated:
            missing.append({"role": "derived_cache", "path": cache_logical, "reason": "MODEL_CONFIG_STALE_INX_COLLISION"})
        elif source_kind == "BUNDLE_GENERATED" and not cache_generated:
            warnings.append(f"MODEL_INX_RUNTIME_DERIVED:{cache_logical}")
        cache_child = generated.get(cache_logical.casefold(), (None, None, None))[2] if cache_generated else None
        closure.append({
            "role": "derived_cache", "path": cache_logical,
            "status": "PASS" if cache_generated or cache_live is not None else "RUNTIME_DERIVED",
            "source": "BUNDLE_GENERATED" if cache_generated else ("LIVE_CLIENT_READ_ONLY" if cache_live is not None else "RUNTIME_COMPILER"),
            "contract_id": str((cache_child or {}).get("contract_id") or "") or None,
        })

        for ref in parsed["refs"]:
            role = str(ref["role"])
            try:
                logical = _join_model_config_ref(config_logical, str(ref["value"]))
            except Exception as exc:
                missing.append({"role": role, "path": str(ref.get("value") or ""), "reason": f"MODEL_CONFIG_REFERENCE_INVALID:{exc}"})
                continue
            try:
                byte_len = len(logical.replace("/", "\\").encode("cp949"))
            except UnicodeEncodeError:
                byte_len = 10_000
            if byte_len >= 64:
                missing.append({"role": role, "path": logical, "reason": "MODEL_RUNTIME_PATH_EXCEEDS_63_BYTES"})
                continue
            ref_hit = _bundle_read_client_file(logical, generated, client_root)
            if ref_hit is None:
                missing.append({"role": role, "path": logical, "reason": "MODEL_DEPENDENCY_NOT_FOUND"})
                continue
            ref_suffix = pathlib.PurePosixPath(logical).suffix.casefold()
            if role in {"model_file", "motion_file", "aux_motion_file"} and ref_suffix in {".smd", ".smb"}:
                inspect_model_payload(logical, ref_hit, role)
            else:
                closure.append({
                    "role": role, "path": logical, "status": "PASS", "source": ref_hit[1],
                    "contract_id": str((ref_hit[2] or {}).get("contract_id") or "") or None,
                })
            if role in {"link_file", "talk_link_file"} and ref_suffix in {".ini", ".inf"}:
                visit(logical, depth + 1)

    visit(root_logical, 0)
    if model_payload_count == 0:
        missing.append({"role": "model_file", "path": root_logical, "reason": "MODEL_CONFIG_CHAIN_HAS_NO_MODEL_PAYLOAD"})
    unresolved_bones = sorted(required_bones - available_bones)
    if unresolved_bones:
        missing.append({"role": "physique_skeleton", "path": root_logical, "reason": "MODEL_PHYSIQUE_BONES_UNRESOLVED", "bones": unresolved_bones})
    elif required_bones:
        closure.append({
            "role": "physique_skeleton", "path": root_logical, "status": "PASS",
            "required_bone_count": len(required_bones), "resolved_bone_count": len(required_bones),
        })
    if missing:
        return {
            "status": "BLOCKED", "reason": "MODEL_PACKAGE_CLOSURE_INCOMPLETE", "path": root_logical,
            "closure": closure, "missing": missing, "warnings": sorted(set(warnings)),
        }
    return {
        "status": "PASS", "source": direct[1], "path": root_logical,
        "closure": closure, "missing": [], "warnings": sorted(set(warnings)),
        "derived_cache": "RUNTIME_DERIVED" if warnings else "RESOLVED",
    }


def _field_stage_closure(
    obj: dict[str, Any], children: list[dict[str, Any]], client_root: pathlib.Path | str | None,
) -> dict[str, Any] | None:
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    stage_asset = payload.get("stage_asset") if isinstance(payload.get("stage_asset"), dict) else None
    stage_file = str(payload.get("stage_file") or ((stage_asset or {}).get("output") if stage_asset else "") or "").strip().replace("\\", "/")
    if not stage_file:
        return None
    logical = _safe_rel(stage_file).as_posix()
    generated = _bundle_client_generated(children)
    hit = _bundle_read_client_file(logical, generated, client_root)
    if hit is None:
        return {"status": "BLOCKED", "reason": "FIELD_STAGE_NOT_FOUND", "path": logical, "closure": [], "missing": [{"role": "stage_file", "path": logical, "reason": "FIELD_STAGE_NOT_FOUND"}]}
    data, source_kind, child = hit
    closure = [{
        "role": "stage_file", "path": logical, "status": "PASS", "source": source_kind,
        "contract_id": str((child or {}).get("contract_id") or "") or None,
    }]
    missing: list[dict[str, Any]] = []
    required: list[str] = []
    if source_kind == "BUNDLE_GENERATED":
        compiled = generated.get(logical.casefold())
        writer = compiled[1] if compiled else {}
        structural = writer.get("structural_validation") if isinstance(writer, dict) and isinstance(writer.get("structural_validation"), dict) else {}
        if str((child or {}).get("contract_id") or "") != "stage.smd.072" or structural.get("status") != "PASS" or structural.get("full_parse") != "PASS":
            missing.append({"role": "stage_file", "path": logical, "reason": "FIELD_STAGE_NOT_VERIFIED_STAGE072"})
        required = [str(x) for x in structural.get("required_textures") or [] if str(x).strip()]
    else:
        # Live stage is read-only dependency evidence. Parse it with the same
        # source-derived Stage0.72 parser to discover material textures.
        source_path = _resolve_root_file(client_root, logical) if client_root is not None else None
        if source_path is None:
            missing.append({"role": "stage_file", "path": logical, "reason": "FIELD_STAGE_LIVE_RESOLVE_FAILED"})
        else:
            try:
                from .stage072_corpus import parse_stage072
                parsed = parse_stage072(source_path, include_payload=False)
                if parsed.get("full_parse") != "PASS":
                    raise ValueError("STAGE072_FULL_PARSE_NOT_PASS")
                used = {int(k) for k, v in (parsed.get("material_face_counts") or {}).items() if int(v or 0) > 0}
                seen: set[str] = set()
                for mat in parsed.get("materials") or []:
                    if int(mat.get("id") or 0) not in used:
                        continue
                    for tex in list(mat.get("textures") or []) + list(mat.get("anim_textures") or []):
                        name = str(tex.get("Name") or "").strip().replace("\\", "/").lstrip("/")
                        if name and name.casefold() not in seen:
                            seen.add(name.casefold()); required.append(name)
            except Exception as exc:
                missing.append({"role": "stage_materials", "path": logical, "reason": f"FIELD_STAGE_PARSE_FAILED:{type(exc).__name__}:{exc}"})
    seen_tex: set[str] = set()
    for texture in required:
        try:
            tex_logical = _safe_rel(texture).as_posix()
        except Exception as exc:
            missing.append({"role": "stage_texture", "path": texture, "reason": f"FIELD_TEXTURE_PATH_INVALID:{exc}"})
            continue
        if tex_logical.casefold() in seen_tex:
            continue
        seen_tex.add(tex_logical.casefold())
        tex_hit = _bundle_read_client_file(tex_logical, generated, client_root)
        if tex_hit is None:
            missing.append({"role": "stage_texture", "path": tex_logical, "reason": "FIELD_TEXTURE_DEPENDENCY_NOT_FOUND"})
            continue
        closure.append({
            "role": "stage_texture", "path": tex_logical, "status": "PASS", "source": tex_hit[1],
            "contract_id": str((tex_hit[2] or {}).get("contract_id") or "") or None,
        })
    if missing:
        return {"status": "BLOCKED", "reason": "FIELD_STAGE_CLOSURE_INCOMPLETE", "path": logical, "closure": closure, "missing": missing, "warnings": []}
    return {"status": "PASS", "path": logical, "source": source_kind, "closure": closure, "missing": [], "warnings": []}

def _bundle_visual_check(obj: dict[str, Any], children: list[dict[str, Any]], client_root: pathlib.Path | str | None) -> dict[str, Any] | None:
    payload=obj.get("payload") if isinstance(obj.get("payload"),dict) else {}
    kind=str(obj.get("bundle_type") or obj.get("kind") or "CUSTOM").strip().upper()
    if kind in {"MONSTER","NPC"}:
        model_file=str(payload.get("model_file") or "").strip().replace("\\","/")
        if not model_file:
            configs = [
                str(row.get("output") or "").strip().replace("\\", "/")
                for row in children
                if str(row.get("target_side") or "").upper() == "CLIENT"
                and str(row.get("contract_id") or "") == "model.config.ini"
            ]
            configs = [x for x in configs if x]
            if len(configs) == 1:
                model_file = configs[0]
            elif len(configs) > 1:
                return {"status":"BLOCKED","reason":"MODEL_FILE_AMBIGUOUS_FROM_VISUAL_PACKAGE","candidates":configs}
        if not model_file: return {"status":"BLOCKED","reason":"MODEL_FILE_REQUIRED"}
        return _model_visual_closure(model_file, children, client_root)
    if kind == "FIELD":
        return _field_stage_closure(obj, children, client_root)
    return None


def _plan_patch_op(op: dict[str, Any], *, server_root: pathlib.Path | str | None) -> tuple[dict[str, Any], bytes | None]:
    try:
        logical=_safe_rel(str(op.get("output") or "")).as_posix()
        kind=str(op.get("kind") or "")
        if kind=="SPM_ADD_ACTOR":
            data,meta=_patch_existing_spm(server_root,logical,actor_name=str(op.get("actor_name") or ""),weight=int(op.get("weight") or 100))
        elif kind=="SPC_ADD_NPC":
            data,meta=_patch_existing_spc(server_root,logical,dict(op.get("row") or {}),slot_index=op.get("slot_index"),record_encoding=str(op.get("record_encoding") or "cp949"))
        else:
            raise ValueError(f"BUNDLE_PATCH_KIND_UNSUPPORTED:{kind}")
        return {"status":"READY","kind":kind,"target_side":"SERVER","output":logical,"preview":{"size":len(data),"sha256":_sha(data),"writer":meta},"errors":[]},data
    except Exception as exc:
        return {"status":"BLOCKED","kind":str(op.get("kind") or ""),"target_side":"SERVER","output":str(op.get("output") or ""),"preview":None,"errors":[f"{type(exc).__name__}:{exc}"]},None


def _bundle_target_evidence(child: dict[str, Any], *, client_root: pathlib.Path | str | None, server_root: pathlib.Path | str | None) -> dict[str, Any]:
    side=str(child.get("target_side") or "").upper()
    logical=_safe_rel(str(child.get("output") or "")).as_posix()
    policy=str(child.get("target_policy") or "CREATE_NEW").upper()
    if policy not in {"CREATE_NEW","REPLACE_EXISTING","AUTO"}:
        raise ValueError(f"BUNDLE_TARGET_POLICY_INVALID:{policy}")
    root=client_root if side=="CLIENT" else server_root
    hit=_resolve_root_file(root,logical) if root is not None else None
    resolved_policy = ("REPLACE_EXISTING" if hit is not None else "CREATE_NEW") if policy == "AUTO" else policy
    if resolved_policy=="CREATE_NEW" and hit is not None:
        raise ValueError(f"BUNDLE_TARGET_ALREADY_EXISTS:{side}:{logical}")
    if resolved_policy=="REPLACE_EXISTING" and hit is None:
        raise ValueError(f"BUNDLE_REPLACE_TARGET_NOT_FOUND:{side}:{logical}")
    return {"policy":resolved_policy,"requested_policy":policy,"exists":hit is not None,"path":str(hit) if hit else None,"sha256":_sha(hit.read_bytes()) if hit else None}


def plan_asset_bundle(recipe: dict[str, Any] | str | pathlib.Path, *, client_root: pathlib.Path | str | None = None, server_root: pathlib.Path | str | None = None) -> dict[str, Any]:
    obj=_recipe_obj(recipe)
    errors=[]; warnings=[]
    if str(obj.get("format") or "") != BUNDLE_RECIPE_FORMAT: errors.append("BUNDLE_RECIPE_FORMAT_INVALID")
    children,patch_ops,exp_warnings,exp_errors=_bundle_children(obj)
    warnings.extend(exp_warnings); errors.extend(exp_errors)
    child_plans=[]
    compiled: list[bytes | None]=[]
    for child in children:
        p=plan_asset_recipe(child)
        try:
            p["target_evidence"]=_bundle_target_evidence(child,client_root=client_root,server_root=server_root)
        except Exception as exc:
            p["status"]="BLOCKED"; p.setdefault("errors",[]).append(f"{type(exc).__name__}:{exc}")
        child_plans.append(p)
        if p.get("status")!="READY": errors.extend([f"CHILD:{child.get('id')}:{x}" for x in p.get("errors") or []]); compiled.append(None)
        else:
            try: compiled.append(_compiler_for(str(child["contract_id"]))(dict(child["payload"]))[0])
            except Exception: compiled.append(None)
    patch_plans=[]
    for op in patch_ops:
        p,data=_plan_patch_op(op,server_root=server_root); patch_plans.append(p); compiled.append(data)
        if p.get("status")!="READY": errors.extend([f"PATCH:{op.get('kind')}:{x}" for x in p.get("errors") or []])
    visual=_bundle_visual_check(obj,children,client_root)
    if visual:
        warnings.extend(str(x) for x in (visual.get("warnings") or []))
        if visual.get("status")!="PASS": errors.append(str(visual.get("reason") or "VISUAL_PACKAGE_UNRESOLVED"))
    all_outputs=[(str(x.get("target_side") or ""),str(x.get("output") or "")) for x in child_plans]+[(str(x.get("target_side") or ""),str(x.get("output") or "")) for x in patch_plans]
    return {
        "format":BUNDLE_PLAN_FORMAT,"status":"READY" if not errors else "BLOCKED",
        "bundle_id":_safe_id(str(obj.get("id") or "bundle")),"bundle_type":str(obj.get("bundle_type") or obj.get("kind") or "CUSTOM").upper(),
        "asset_count":len(child_plans)+len(patch_plans),"children":child_plans,"patches":patch_plans,
        "visual_dependency":visual,"outputs":all_outputs,"warnings":warnings,"errors":errors,
        "scope":"PT_BUILD_BUNDLE_PLAN_ONLY","target_write_authorized":False,
    }



def _bundle_binding_evidence(plan: dict[str, Any], side: str, logical: str, contract_id: str | None) -> dict[str, Any] | None:
    """Return compiler-owned graph evidence that a non-fixed-path asset belongs to the bundle."""
    if str(side).upper() != "CLIENT":
        return None
    visual = plan.get("visual_dependency") if isinstance(plan.get("visual_dependency"), dict) else None
    if not visual or visual.get("status") != "PASS":
        return None
    target = _safe_rel(logical).as_posix().casefold()
    rows = [
        row for row in (visual.get("closure") or [])
        if isinstance(row, dict)
        and str(row.get("status") or "") == "PASS"
        and str(row.get("path") or "").replace("\\", "/").strip("/").casefold() == target
    ]
    if not rows:
        return None
    # Prefer a row that already carries the same compiler contract id. Some live
    # dependencies have no child/contract id and therefore remain read-only evidence.
    selected = next((r for r in rows if str(r.get("contract_id") or "") == str(contract_id or "")), rows[0])
    role = str(selected.get("role") or "")
    graph = "FIELD_STAGE_CLOSURE" if role in {"stage_file", "stage_texture"} else "MODEL_VISUAL_CLOSURE"
    return {
        "status": "SOURCE_GRAPH_BOUND",
        "graph": graph,
        "role": role,
        "path": _safe_rel(logical).as_posix(),
        "contract_id": contract_id,
        "closure_source": str(selected.get("source") or ""),
    }

def compile_asset_bundle(project_root: pathlib.Path | str, recipe: dict[str, Any] | str | pathlib.Path, *, client_root: pathlib.Path | str | None = None, server_root: pathlib.Path | str | None = None) -> dict[str, Any]:
    project_root=pathlib.Path(project_root).resolve(); obj=_recipe_obj(recipe)
    plan=plan_asset_bundle(obj,client_root=client_root,server_root=server_root)
    if plan.get("status")!="READY": raise ValueError("ASSET_BUNDLE_BLOCKED:"+"|".join(plan.get("errors") or []))
    children,patch_ops,_,_=_bundle_children(obj)
    entries=[]
    for child in children:
        cid=str(child["contract_id"]); side=str(child["target_side"]).upper(); rel=_safe_rel(str(child["output"])); data,writer=_compiler_for(cid)(dict(child["payload"]))
        target_evidence=_bundle_target_evidence(child,client_root=client_root,server_root=server_root)
        binding_evidence = _bundle_binding_evidence(plan, side, rel.as_posix(), cid)
        entries.append({"kind":"ASSET","contract_id":cid,"side":side,"rel":rel,"data":data,"writer":writer,"target_evidence":target_evidence,"binding_evidence":binding_evidence})
    for op in patch_ops:
        p,data=_plan_patch_op(op,server_root=server_root)
        if p.get("status")!="READY" or data is None: raise ValueError("BUNDLE_PATCH_REVALIDATION_FAILED:"+"|".join(p.get("errors") or []))
        entries.append({"kind":str(op["kind"]),"contract_id":None,"side":"SERVER","rel":_safe_rel(str(op["output"])),"data":data,"writer":p["preview"]["writer"],"target_evidence":{"policy":"PATCH_EXISTING","exists":True,"path":p["preview"]["writer"].get("source"),"sha256":p["preview"]["writer"].get("source_sha256")}})
    digest=hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()[:10]
    stamp=time.strftime("%Y%m%d_%H%M%S"); bundle_id=_safe_id(str(obj.get("id") or "bundle")); run_id=f"{stamp}_{bundle_id}_{digest}"
    root=project_root/"pt_build"/"asset_compiler"/"bundles"/run_id; overlay=root/"overlay"; root.mkdir(parents=True,exist_ok=True)
    written=[]
    for entry in entries:
        target=overlay/entry["side"].lower()/pathlib.Path(*entry["rel"].parts); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(entry["data"])
        written.append({"kind":entry["kind"],"contract_id":entry["contract_id"],"target_side":entry["side"],"logical_output":entry["rel"].as_posix(),"output":str(target),"size":len(entry["data"]),"sha256":_sha(entry["data"]),"writer":entry["writer"],"target_evidence":entry.get("target_evidence"),"binding_evidence":entry.get("binding_evidence")})
    recipe_path=root/"recipe.json"; manifest_path=root/"manifest.json"
    recipe_path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest={"format":BUNDLE_BUILD_FORMAT,"status":"PASS","run_id":run_id,"bundle_id":bundle_id,"bundle_type":plan["bundle_type"],"asset_count":len(written),"assets":written,"overlay_root":str(overlay),"recipe":str(recipe_path),"warnings":plan.get("warnings") or [],"scope":"PT_BUILD_ASSET_COMPILER_BUNDLE_OVERLAY_ONLY","client_modified":False,"server_modified":False,"target_write_authorized":False}
    manifest["manifest"]=str(manifest_path); manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest


def plan_compiler_input(recipe: dict[str, Any] | str | pathlib.Path, *, client_root: pathlib.Path | str | None = None, server_root: pathlib.Path | str | None = None) -> dict[str, Any]:
    obj=_recipe_obj(recipe)
    if str(obj.get("format") or "") == BUNDLE_RECIPE_FORMAT:
        return plan_asset_bundle(obj,client_root=client_root,server_root=server_root)
    return plan_asset_recipe(obj)


def compile_compiler_input(project_root: pathlib.Path | str, recipe: dict[str, Any] | str | pathlib.Path, *, client_root: pathlib.Path | str | None = None, server_root: pathlib.Path | str | None = None) -> dict[str, Any]:
    obj=_recipe_obj(recipe)
    if str(obj.get("format") or "") == BUNDLE_RECIPE_FORMAT:
        return compile_asset_bundle(project_root,obj,client_root=client_root,server_root=server_root)
    return compile_asset_recipe(project_root,obj)

def compiler_capabilities() -> dict[str, Any]:
    rows=[]
    for cid in sorted(_DIRECT_COMPILERS):
        try: c=get_contract(cid).public()
        except KeyError: continue
        rows.append({"contract_id":cid,"family":c.get("family"),"runtime":c.get("runtime"),"source_capability":c.get("capability"),"implementation":c.get("implementation")})
    return {"format":"PT_ASSET_COMPILER_CAPABILITIES_V2","status":"PASS","direct_compiler_count":len(rows),"contracts":rows,"bundle_recipe_format":BUNDLE_RECIPE_FORMAT,"bundle_types":["MONSTER","NPC","ITEM","FIELD","CUSTOM"],"target_write_authorized":False}
