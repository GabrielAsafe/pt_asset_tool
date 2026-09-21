from __future__ import annotations

import hashlib
import json
import pathlib
import re
import struct
from dataclasses import dataclass
from typing import Any

from .asset_compiler import build_spc_record, CURRENT_NPC_OPCODE, LEGACY_NPC_OPCODE

FORMAT_INSPECT = "PT_ASSET_SERVER_FIELD_EDITOR_INSPECT_V1"
FORMAT_DRAFT = "PT_ASSET_SERVER_FIELD_EDITOR_DRAFT_V1"
SPP_RECORD_COUNT = 200
SPP_RECORD_SIZE = 12
SPP_FILE_SIZE = SPP_RECORD_COUNT * SPP_RECORD_SIZE
SPC_RECORD_COUNT = 100
SPC_RECORD_SIZE = 504
SPC_FILE_SIZE = SPC_RECORD_COUNT * SPC_RECORD_SIZE
SPC_ADD_NPC_CODE = CURRENT_NPC_OPCODE
SPC_LEGACY_ADD_NPC_CODE = LEGACY_NPC_OPCODE
SPC_KNOWN_ADD_NPC_CODES = {SPC_ADD_NPC_CODE, SPC_LEGACY_ADD_NPC_CODE}
SPM_ALIASES = {
    "ACTOR": ("*ACTOR", "*출연자"),
    "BOSS_ACTOR": ("*BOSS_ACTOR", "*출연자두목"),
    "MAX_ACTOR_POS": ("*MAX_ACTOR_POS", "*최대동시출현수"),
    "MAX_ACTOR": ("*MAX_ACTOR", "*출현수"),
    "DELAY": ("*DELAY", "*출현간격"),
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normal_rel(value: str) -> pathlib.PurePosixPath:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    rel = pathlib.PurePosixPath(text)
    if not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError("INVALID_FIELD_PATH")
    if rel.suffix.casefold() not in {".spm", ".spp", ".spc"}:
        raise ValueError("FIELD_EXTENSION_NOT_SUPPORTED")
    return rel


def _ci_resolve(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path:
    root = pathlib.Path(root).resolve()
    cur = root
    for part in rel.parts:
        exact = cur / part
        if exact.exists():
            cur = exact
            continue
        if not cur.is_dir():
            raise FileNotFoundError(rel.as_posix())
        matches = [p for p in cur.iterdir() if p.name.casefold() == part.casefold()]
        if len(matches) != 1:
            raise FileNotFoundError(rel.as_posix())
        cur = matches[0]
    resolved = cur.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("SERVER_PATH_ESCAPE")
    if not resolved.is_file():
        raise FileNotFoundError(rel.as_posix())
    return resolved


def _draft_dir(project_root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path:
    project = pathlib.Path(project_root).resolve()
    safe_parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", x) for x in rel.parts]
    out = project / "pt_build" / "server_field_editor" / pathlib.Path(*safe_parts[:-1]) / safe_parts[-1]
    out.mkdir(parents=True, exist_ok=True)
    return out


def _read_legacy_text(data: bytes) -> tuple[str, str, str]:
    for enc in ("utf-8-sig", "cp949", "cp1252", "latin1"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        newline = "\r\n" if b"\r\n" in data else ("\r" if b"\r" in data and b"\n" not in data else "\n")
        return text, enc, newline
    return data.decode("latin1"), "latin1", "\n"


def _clean_cstr(data: bytes) -> str:
    raw = data.split(b"\0", 1)[0]
    for enc in ("cp949", "utf-8", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace")


def _encode_fixed(text: str, size: int, encoding: str, field: str) -> bytes:
    try:
        raw = str(text).encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} cannot be encoded as {encoding}: {exc}") from exc
    if len(raw) >= size:
        raise ValueError(f"{field} too long: {len(raw)} bytes, max {size - 1}")
    return raw + b"\0" * (size - len(raw))


def _inspect_spm(data: bytes) -> dict[str, Any]:
    text, encoding, newline = _read_legacy_text(data)
    directives = {k: 0 for k in SPM_ALIASES}
    actors: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        upper = line.upper()
        for key, aliases in SPM_ALIASES.items():
            if any(upper.startswith(alias.upper()) for alias in aliases):
                directives[key] += 1
                break
        match = re.search(r'(?i)(?:\*ACTOR|\*출연자)\s+(?:"([^"]+)"|(\S+))\s+(-?\d+)', line)
        if match:
            actors.append({"name": match.group(1) or match.group(2), "weight": int(match.group(3))})
    return {
        "kind": "SPM_SPAWN_TEXT",
        "encoding": encoding,
        "newline": newline.replace("\r", "\\r").replace("\n", "\\n"),
        "text": text,
        "directives": directives,
        "actors": actors,
        "authoring": "STAGED_TEXT_PRESERVE_ENCODING",
    }


def _inspect_spp(data: bytes) -> dict[str, Any]:
    if len(data) != SPP_FILE_SIZE:
        return {
            "kind": "SPP_START_POINTS",
            "status": "REVIEW_LAYOUT",
            "size": len(data),
            "expected_size": SPP_FILE_SIZE,
            "authoring": "BLOCKED_NON_CANONICAL_LAYOUT",
            "records": [],
        }
    records = []
    for i in range(SPP_RECORD_COUNT):
        state, x, z = struct.unpack_from("<iii", data, i * SPP_RECORD_SIZE)
        records.append({"index": i, "state": state, "x": x, "z": z, "active": bool(state)})
    return {
        "kind": "SPP_START_POINTS",
        "status": "PASS",
        "size": len(data),
        "record_count": SPP_RECORD_COUNT,
        "active_count": sum(1 for r in records if r["active"]),
        "records": records,
        "authoring": "STAGED_RECORD_EDIT",
    }


def _parse_spc_record(record: bytes, index: int) -> dict[str, Any]:
    if len(record) != SPC_RECORD_SIZE:
        raise ValueError("SPC_RECORD_SIZE_INVALID")
    size, code_u32 = struct.unpack_from("<iI", record, 0)
    tail = struct.unpack_from("<I7i", record, 472)
    life = list(struct.unpack_from("<2h", record, 8 + 292))
    mana = list(struct.unpack_from("<2h", record, 8 + 296))
    code_kind = (
        "CURRENT_OP_CODE" if code_u32 == SPC_ADD_NPC_CODE else
        "LEGACY_SMTRANSCODE" if code_u32 == SPC_LEGACY_ADD_NPC_CODE else
        "OTHER_NONZERO" if code_u32 else "EMPTY"
    )
    return {
        "index": index,
        "packet_size": size,
        "code_u32": code_u32,
        "code_hex": f"0x{code_u32:08X}",
        "code_kind": code_kind,
        "runtime_active": code_u32 != 0,
        "standard_add_npc_code": code_u32 in SPC_KNOWN_ADD_NPC_CODES,
        "current_add_npc_code": code_u32 == SPC_ADD_NPC_CODE,
        "legacy_add_npc_code": code_u32 == SPC_LEGACY_ADD_NPC_CODE,
        "blank": not any(record),
        "name": _clean_cstr(record[8:40]),
        "model_ini": _clean_cstr(record[40:104]),
        "server_npc": _clean_cstr(record[104:164]),
        "inner_model_name_code2_u32": struct.unpack_from("<I", record, 164)[0],
        "inner_object_serial_u32": struct.unpack_from("<I", record, 168)[0],
        "inner_state": struct.unpack_from("<i", record, 176)[0],
        "life": life,
        "mana": mana,
        "object_serial_u32": tail[0],
        "x": tail[1], "y": tail[2], "z": tail[3],
        "ax": tail[4], "ay": tail[5], "az": tail[6], "state": tail[7],
    }


def _inspect_spc(data: bytes) -> dict[str, Any]:
    if len(data) != SPC_FILE_SIZE:
        return {
            "kind": "SPC_FIXED_CHARACTERS",
            "status": "REVIEW_LAYOUT",
            "size": len(data),
            "expected_size": SPC_FILE_SIZE,
            "authoring": "BLOCKED_NON_CANONICAL_LAYOUT",
            "records": [],
        }
    records = [_parse_spc_record(data[i * SPC_RECORD_SIZE:(i + 1) * SPC_RECORD_SIZE], i) for i in range(SPC_RECORD_COUNT)]
    return {
        "kind": "SPC_FIXED_CHARACTERS",
        "status": "PASS",
        "size": len(data),
        "record_count": SPC_RECORD_COUNT,
        "runtime_active_count": sum(1 for r in records if r["runtime_active"]),
        "standard_add_npc_count": sum(1 for r in records if r["standard_add_npc_code"]),
        "current_add_npc_count": sum(1 for r in records if r["current_add_npc_code"]),
        "legacy_add_npc_count": sum(1 for r in records if r["legacy_add_npc_code"]),
        "blank_slot_count": sum(1 for r in records if r["blank"]),
        "records": records,
        "authoring": "STAGED_NATIVE_RECORD_EDIT",
        "synthetic_from_zero_authoring": "SOURCE_PROVEN_WIN32_ABI",
        "source_current_opcode": f"0x{SPC_ADD_NPC_CODE:08X}",
        "legacy_compatible_opcode": f"0x{SPC_LEGACY_ADD_NPC_CODE:08X}",
    }


def inspect_field_metadata(project_root: pathlib.Path, server_root: pathlib.Path, rel: str) -> dict[str, Any]:
    relp = _normal_rel(rel)
    source = _ci_resolve(pathlib.Path(server_root), relp)
    data = source.read_bytes()
    ext = relp.suffix.casefold()
    if ext == ".spm":
        detail = _inspect_spm(data)
    elif ext == ".spp":
        detail = _inspect_spp(data)
    else:
        detail = _inspect_spc(data)
    out = _draft_dir(project_root, relp)
    manifests = sorted(out.glob("*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "format": FORMAT_INSPECT,
        "status": detail.get("status", "PASS"),
        "relative_path": relp.as_posix(),
        "source": str(source),
        "source_size": len(data),
        "source_sha256": _sha256_bytes(data),
        "type": ext[1:].upper(),
        "detail": detail,
        "latest_draft_manifest": str(manifests[0]) if manifests else None,
        "server_write_authorized": False,
        "client_write_authorized": False,
        "production_authorized": False,
    }


def _check_expected(data: bytes, expected_sha256: str | None) -> str:
    actual = _sha256_bytes(data)
    if expected_sha256 and str(expected_sha256).strip().lower() != actual:
        raise ValueError(f"SOURCE_SHA256_MISMATCH expected={expected_sha256} actual={actual}")
    return actual


def _write_draft(
    project_root: pathlib.Path,
    relp: pathlib.PurePosixPath,
    source: pathlib.Path,
    source_sha: str,
    data: bytes,
    operation: str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    out_dir = _draft_dir(project_root, relp)
    draft = out_dir / f"draft{relp.suffix.casefold()}"
    draft.write_bytes(data)
    manifest = {
        "format": FORMAT_DRAFT,
        "status": "PASS",
        "operation": operation,
        "relative_path": relp.as_posix(),
        "source": str(source),
        "source_sha256": source_sha,
        "source_size": source.stat().st_size,
        "draft": str(draft),
        "draft_sha256": _sha256_bytes(data),
        "draft_size": len(data),
        "changed": _sha256_bytes(data) != source_sha,
        "detail": detail,
        "scope": "PT_BUILD_STAGING_ONLY",
        "server_write_authorized": False,
        "client_write_authorized": False,
        "production_authorized": False,
    }
    manifest_path = out_dir / "draft.manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def stage_spm_text(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    rel: str,
    text: str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    relp = _normal_rel(rel)
    if relp.suffix.casefold() != ".spm":
        raise ValueError("SPM_PATH_REQUIRED")
    source = _ci_resolve(pathlib.Path(server_root), relp)
    source_data = source.read_bytes()
    source_sha = _check_expected(source_data, expected_sha256)
    _, encoding, newline = _read_legacy_text(source_data)
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", newline)
    try:
        draft_data = normalized.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"SPM_TEXT_NOT_ENCODABLE encoding={encoding}: {exc}") from exc
    return _write_draft(project_root, relp, source, source_sha, draft_data, "SPM_TEXT_REPLACE", {
        "encoding": encoding,
        "newline": newline.replace("\r", "\\r").replace("\n", "\\n"),
        "parsed": _inspect_spm(draft_data),
    })


def stage_spp_records(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    rel: str,
    edits: list[dict[str, Any]],
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    relp = _normal_rel(rel)
    if relp.suffix.casefold() != ".spp":
        raise ValueError("SPP_PATH_REQUIRED")
    source = _ci_resolve(pathlib.Path(server_root), relp)
    source_data = source.read_bytes()
    source_sha = _check_expected(source_data, expected_sha256)
    if len(source_data) != SPP_FILE_SIZE:
        raise ValueError(f"SPP_NON_CANONICAL_SIZE size={len(source_data)} expected={SPP_FILE_SIZE}")
    data = bytearray(source_data)
    applied = []
    seen = set()
    for raw in edits:
        index = int(raw["index"])
        if not 0 <= index < SPP_RECORD_COUNT:
            raise ValueError(f"SPP_INDEX_OUT_OF_RANGE index={index}")
        if index in seen:
            raise ValueError(f"SPP_DUPLICATE_INDEX index={index}")
        seen.add(index)
        before = struct.unpack_from("<iii", data, index * SPP_RECORD_SIZE)
        after = (int(raw["state"]), int(raw["x"]), int(raw["z"]))
        struct.pack_into("<iii", data, index * SPP_RECORD_SIZE, *after)
        applied.append({"index": index, "before": list(before), "after": list(after)})
    if not applied:
        raise ValueError("SPP_EDIT_REQUIRED")
    return _write_draft(project_root, relp, source, source_sha, bytes(data), "SPP_RECORD_EDIT", {
        "applied": applied,
        "record_count": SPP_RECORD_COUNT,
    })


def stage_spc_clone(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    rel: str,
    *,
    template_index: int | None = None,
    slot_index: int | None = None,
    record_name: str,
    model_ini: str,
    server_npc: str,
    x: int,
    y: int = 0,
    z: int = 0,
    ax: int = 0,
    ay: int = 0,
    az: int = 0,
    state: int = 0,
    expected_sha256: str | None = None,
    record_encoding: str = "cp949",
) -> dict[str, Any]:
    relp = _normal_rel(rel)
    if relp.suffix.casefold() != ".spc":
        raise ValueError("SPC_PATH_REQUIRED")
    source = _ci_resolve(pathlib.Path(server_root), relp)
    source_data = source.read_bytes()
    source_sha = _check_expected(source_data, expected_sha256)
    if len(source_data) != SPC_FILE_SIZE:
        raise ValueError(f"SPC_NON_CANONICAL_SIZE size={len(source_data)} expected={SPC_FILE_SIZE}")
    data = bytearray(source_data)
    records = [_parse_spc_record(source_data[i * SPC_RECORD_SIZE:(i + 1) * SPC_RECORD_SIZE], i) for i in range(SPC_RECORD_COUNT)]
    if template_index is None:
        template_index = next((r["index"] for r in records if r["standard_add_npc_code"]), None)
    if template_index is None or not 0 <= int(template_index) < SPC_RECORD_COUNT:
        raise ValueError("SPC_VALID_TEMPLATE_REQUIRED")
    template_index = int(template_index)
    if not records[template_index]["standard_add_npc_code"]:
        raise ValueError(f"SPC_TEMPLATE_NOT_STANDARD_ADD_NPC index={template_index}")
    if slot_index is None:
        slot_index = next((r["index"] for r in records if r["blank"]), None)
    if slot_index is None or not 0 <= int(slot_index) < SPC_RECORD_COUNT:
        raise ValueError("SPC_FREE_SLOT_REQUIRED")
    slot_index = int(slot_index)
    if records[slot_index]["runtime_active"]:
        raise ValueError(f"SPC_SLOT_ALREADY_ACTIVE index={slot_index}")

    rec = bytearray(source_data[template_index * SPC_RECORD_SIZE:(template_index + 1) * SPC_RECORD_SIZE])
    struct.pack_into("<iI", rec, 0, SPC_RECORD_SIZE, int(records[template_index]["code_u32"]))
    rec[8:40] = _encode_fixed(record_name, 32, record_encoding, "SPC name")
    rec[40:104] = _encode_fixed(str(model_ini).replace("/", "\\"), 64, "ascii", "SPC model path")
    rec[104:164] = _encode_fixed(str(server_npc).replace("/", "\\"), 60, "ascii", "SPC server NPC path")
    # donor-specific ModelNameCode2 / smCHAR_INFO object identity are not portable.
    struct.pack_into("<II", rec, 164, 0, 0)
    # Runtime OpenNpc() replaces packet object serial. Keep it zero in staged clone.
    struct.pack_into("<8i", rec, 472, 0, int(x), int(y), int(z), int(ax), int(ay), int(az), int(state))
    before = records[slot_index]
    data[slot_index * SPC_RECORD_SIZE:(slot_index + 1) * SPC_RECORD_SIZE] = rec
    after = _parse_spc_record(bytes(rec), slot_index)
    return _write_draft(project_root, relp, source, source_sha, bytes(data), "SPC_CLONE_PATCH", {
        "template_index": template_index,
        "slot_index": slot_index,
        "template_record": records[template_index],
        "replaced_slot_before": before,
        "new_record": after,
        "synthetic_from_zero_authoring": "SOURCE_PROVEN_WIN32_ABI_AVAILABLE",
    })


def stage_spc_native(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    rel: str,
    *,
    slot_index: int | None = None,
    record_name: str,
    model_ini: str,
    server_npc: str,
    x: int,
    y: int = 0,
    z: int = 0,
    ax: int = 0,
    ay: int = 0,
    az: int = 0,
    state: int = 0,
    expected_sha256: str | None = None,
    record_encoding: str = "cp949",
    code: str | int = "CURRENT",
) -> dict[str, Any]:
    """Insert one from-zero source-derived smTRNAS_PLAYERINFO into a fixed SPC.

    Unlike ``stage_spc_clone`` this does not inherit opaque bytes from a donor
    record.  Every emitted byte is explained by the Win32 ABI recovered from
    source. Existing SPC slots remain byte-identical.
    """
    relp = _normal_rel(rel)
    if relp.suffix.casefold() != ".spc":
        raise ValueError("SPC_PATH_REQUIRED")
    source = _ci_resolve(pathlib.Path(server_root), relp)
    source_data = source.read_bytes()
    source_sha = _check_expected(source_data, expected_sha256)
    if len(source_data) != SPC_FILE_SIZE:
        raise ValueError(f"SPC_NON_CANONICAL_SIZE size={len(source_data)} expected={SPC_FILE_SIZE}")
    records = [_parse_spc_record(source_data[i * SPC_RECORD_SIZE:(i + 1) * SPC_RECORD_SIZE], i) for i in range(SPC_RECORD_COUNT)]
    if slot_index is None:
        slot_index = next((r["index"] for r in records if r["blank"]), None)
    if slot_index is None or not 0 <= int(slot_index) < SPC_RECORD_COUNT:
        raise ValueError("SPC_FREE_SLOT_REQUIRED")
    slot_index = int(slot_index)
    if records[slot_index]["runtime_active"]:
        raise ValueError(f"SPC_SLOT_ALREADY_ACTIVE index={slot_index}")
    row = {
        "code": code, "name": record_name, "model_ini": model_ini, "server_npc": server_npc,
        "x": int(x), "y": int(y), "z": int(z), "ax": int(ax), "ay": int(ay), "az": int(az),
        "state": int(state),
    }
    record = build_spc_record(row, record_encoding=record_encoding)
    after_record = _parse_spc_record(record, slot_index)
    data = bytearray(source_data)
    data[slot_index * SPC_RECORD_SIZE:(slot_index + 1) * SPC_RECORD_SIZE] = record
    return _write_draft(project_root, relp, source, source_sha, bytes(data), "SPC_NATIVE_ABI_INSERT", {
        "slot_index": slot_index,
        "replaced_slot_before": records[slot_index],
        "new_record": after_record,
        "source_abi": "Win32 i686 smTRNAS_PLAYERINFO=504; smCHAR_INFO=464",
        "source_current_opcode": f"0x{SPC_ADD_NPC_CODE:08X}",
        "legacy_compatible_opcode": f"0x{SPC_LEGACY_ADD_NPC_CODE:08X}",
        "synthetic_from_zero_authoring": "SOURCE_PROVEN_WIN32_ABI",
        "donor_record_required": False,
    })
