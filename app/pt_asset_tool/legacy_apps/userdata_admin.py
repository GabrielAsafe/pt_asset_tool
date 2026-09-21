from __future__ import annotations

"""Safe Python replacement for the proven parts of MudarNome/Level/ControllerUser.

Character/account rename is an exact-format port of MudarNome.exe's file graph,
but implemented transactionally.  Other persistence mutations remain read-only or
plan-only until their exact offsets are independently proven.
"""

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil
import struct
from typing import Any

from .common import atomic_write_bytes, backup_file, dataserver_path, legacy_bucket, sha256_file
from .item_finder import parse_inventory_bytes, parse_warehouse_bytes

FORMAT = "PT_LEGACY_USERDATA_ADMIN_V1"
USERDATA_SIZE = 0x1B310
USERINFO_SIZE = 0xF0
NAME_SIZE = 32
USERDATA_CHAR_OFFSET = 0x10
USERDATA_ACCOUNT_OFFSET = 0x2C0
USERINFO_ACCOUNT_OFFSET = 0x10
USERINFO_CHARACTERS_OFFSET = 0x30
USERINFO_CHARACTER_COUNT = 6
USERINFO_CHARACTER_STRIDE = 0x20
RENAME_CHARACTER_CONFIRM = "APPLY CHARACTER RENAME"
RENAME_ACCOUNT_CONFIRM = "APPLY ACCOUNT RENAME"
ACCOUNT_GRAPH_COPY_CONFIRM = "COPY ACCOUNT GRAPH"


def _decode_fixed(raw: bytes, offset: int, size: int = NAME_SIZE) -> str:
    return raw[offset:offset + size].split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _encode_fixed(value: str, size: int = NAME_SIZE) -> bytes:
    data = value.encode("latin-1")
    if not data or len(data) >= size:
        raise ValueError(f"LEGACY_NAME_LENGTH:1..{size-1}")
    return data + b"\0" * (size - len(data))


def _replace_fixed(raw: bytes, offset: int, value: str, size: int = NAME_SIZE) -> bytes:
    if offset < 0 or offset + size > len(raw):
        raise ValueError("FIXED_FIELD_OUT_OF_RANGE")
    out = bytearray(raw)
    out[offset:offset + size] = _encode_fixed(value, size)
    return bytes(out)


def _path(server_root: Path, store: str, key: str, suffix: str) -> Path:
    # The legacy executables use DataServer with exact bucket arithmetic.  The
    # project/server roots used by the tool are normalized around that layout.
    return dataserver_path(Path(server_root), store, key, suffix)


def _read_exact(path: Path, size: int, label: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{label}_NOT_FOUND:{path}")
    raw = path.read_bytes()
    if len(raw) != size:
        raise ValueError(f"{label}_SIZE:{len(raw)}!=0x{size:x}")
    return raw


def inspect_userdata(path: Path) -> dict[str, Any]:
    raw = _read_exact(Path(path), USERDATA_SIZE, "USERDATA")
    return {
        "format": FORMAT,
        "status": "PASS",
        "path": str(Path(path)),
        "sha256": sha256_file(Path(path)),
        "size": len(raw),
        "character": _decode_fixed(raw, USERDATA_CHAR_OFFSET),
        "account": _decode_fixed(raw, USERDATA_ACCOUNT_OFFSET),
        "items": [x.__dict__ | {"key": x.key} for x in parse_inventory_bytes(Path(path).stem, raw)],
        "write_authorized": False,
    }


def inspect_userinfo(path: Path) -> dict[str, Any]:
    raw = _read_exact(Path(path), USERINFO_SIZE, "USERINFO")
    chars = [
        _decode_fixed(raw, USERINFO_CHARACTERS_OFFSET + i * USERINFO_CHARACTER_STRIDE)
        for i in range(USERINFO_CHARACTER_COUNT)
    ]
    return {
        "format": FORMAT,
        "status": "PASS",
        "path": str(Path(path)),
        "sha256": sha256_file(Path(path)),
        "size": len(raw),
        "account": _decode_fixed(raw, USERINFO_ACCOUNT_OFFSET),
        "characters": [x for x in chars if x],
        "write_authorized": False,
    }


def inspect_account(server_root: Path, account: str) -> dict[str, Any]:
    userinfo = _path(server_root, "userinfo", account, ".dat")
    result = inspect_userinfo(userinfo)
    wh = _path(server_root, "warehouse", account, ".war")
    result["warehouse"] = {
        "path": str(wh),
        "exists": wh.is_file(),
        "sha256": sha256_file(wh) if wh.is_file() else None,
        "items": [x.__dict__ | {"key": x.key} for x in parse_warehouse_bytes(account, wh.read_bytes())] if wh.is_file() else [],
    }
    return result


def plan_character_rename(server_root: Path, old_name: str, new_name: str) -> dict[str, Any]:
    old_name = old_name.strip(); new_name = new_name.strip()
    _encode_fixed(old_name); _encode_fixed(new_name)
    root = Path(server_root).resolve()
    old_path = _path(root, "userdata", old_name, ".dat")
    new_path = _path(root, "userdata", new_name, ".dat")
    if new_path.exists():
        return {"format": FORMAT, "status": "BLOCKED", "reason": "DESTINATION_CHARACTER_EXISTS", "destination": str(new_path)}
    raw = _read_exact(old_path, USERDATA_SIZE, "SOURCE_USERDATA")
    embedded_name = _decode_fixed(raw, USERDATA_CHAR_OFFSET)
    account = _decode_fixed(raw, USERDATA_ACCOUNT_OFFSET)
    if not account:
        return {"format": FORMAT, "status": "BLOCKED", "reason": "USERDATA_ACCOUNT_REFERENCE_EMPTY", "source": str(old_path)}
    userinfo_path = _path(root, "userinfo", account, ".dat")
    userinfo = _read_exact(userinfo_path, USERINFO_SIZE, "ACCOUNT_USERINFO")
    slots = [_decode_fixed(userinfo, USERINFO_CHARACTERS_OFFSET + i * USERINFO_CHARACTER_STRIDE) for i in range(USERINFO_CHARACTER_COUNT)]
    matches = [i for i, name in enumerate(slots) if name == old_name]
    if len(matches) != 1:
        return {
            "format": FORMAT, "status": "BLOCKED", "reason": "USERINFO_CHARACTER_REFERENCE_NOT_UNIQUE",
            "account": account, "matches": matches, "characters": slots,
        }
    slot = matches[0]
    new_userdata = _replace_fixed(raw, USERDATA_CHAR_OFFSET, new_name)
    new_userinfo = _replace_fixed(userinfo, USERINFO_CHARACTERS_OFFSET + slot * USERINFO_CHARACTER_STRIDE, new_name)
    return {
        "format": FORMAT, "status": "READY", "operation": "RENAME_CHARACTER",
        "server_root": str(root), "old_name": old_name, "new_name": new_name,
        "source": str(old_path), "destination": str(new_path), "account": account,
        "userinfo": str(userinfo_path), "userinfo_slot": slot,
        "embedded_name_before": embedded_name,
        "source_sha256": sha256_file(old_path), "userinfo_sha256": sha256_file(userinfo_path),
        "new_userdata": new_userdata, "new_userinfo": new_userinfo,
        "legacy_evidence": {
            "MudarNome.character": "userdata +0x10 character; userdata +0x2c0 account; userinfo has 6 character slots at +0x30 + slot*0x20 (through +0xd0)",
            "file_sizes": {"userdata": USERDATA_SIZE, "userinfo": USERINFO_SIZE},
        },
        "write_authorized": False,
    }


def plan_account_rename(server_root: Path, old_account: str, new_account: str) -> dict[str, Any]:
    old_account = old_account.strip(); new_account = new_account.strip()
    _encode_fixed(old_account); _encode_fixed(new_account)
    root = Path(server_root).resolve()
    old_info = _path(root, "userinfo", old_account, ".dat")
    new_info = _path(root, "userinfo", new_account, ".dat")
    if new_info.exists():
        return {"format": FORMAT, "status": "BLOCKED", "reason": "DESTINATION_ACCOUNT_EXISTS", "destination": str(new_info)}
    userinfo = _read_exact(old_info, USERINFO_SIZE, "SOURCE_USERINFO")
    chars = [_decode_fixed(userinfo, USERINFO_CHARACTERS_OFFSET + i * USERINFO_CHARACTER_STRIDE) for i in range(USERINFO_CHARACTER_COUNT)]
    chars = [x for x in chars if x]
    character_changes = []
    for char in chars:
        p = _path(root, "userdata", char, ".dat")
        raw = _read_exact(p, USERDATA_SIZE, f"CHARACTER_USERDATA:{char}")
        embedded = _decode_fixed(raw, USERDATA_ACCOUNT_OFFSET)
        if embedded != old_account:
            return {
                "format": FORMAT, "status": "BLOCKED", "reason": "CHARACTER_ACCOUNT_REFERENCE_MISMATCH",
                "character": char, "embedded_account": embedded, "expected": old_account, "path": str(p),
            }
        character_changes.append({
            "character": char, "path": str(p), "sha256": sha256_file(p),
            "new_userdata": _replace_fixed(raw, USERDATA_ACCOUNT_OFFSET, new_account),
        })
    old_wh = _path(root, "warehouse", old_account, ".war")
    new_wh = _path(root, "warehouse", new_account, ".war")
    if new_wh.exists():
        return {"format": FORMAT, "status": "BLOCKED", "reason": "DESTINATION_WAREHOUSE_EXISTS", "destination": str(new_wh)}
    return {
        "format": FORMAT, "status": "READY", "operation": "RENAME_ACCOUNT",
        "server_root": str(root), "old_account": old_account, "new_account": new_account,
        "source_userinfo": str(old_info), "destination_userinfo": str(new_info),
        "userinfo_sha256": sha256_file(old_info),
        "new_userinfo": _replace_fixed(userinfo, USERINFO_ACCOUNT_OFFSET, new_account),
        "characters": character_changes,
        "source_warehouse": str(old_wh), "destination_warehouse": str(new_wh),
        "warehouse_sha256": sha256_file(old_wh) if old_wh.is_file() else None,
        "write_authorized": False,
    }


def plan_account_graph_copy(source_server_root: Path, destination_server_root: Path, account: str, *, allow_replace: bool = False) -> dict[str, Any]:
    """Plan a safe account graph copy between DataServer roots.

    ControllerUser's native ``Copy`` path uses a magic ``DataServer1`` staging
    root, parses one 0xF0 userinfo file to obtain six character names and copies
    the corresponding userdata files into ``DataServer\\userdata``.  The Python
    replacement makes both roots explicit and copies the complete useful graph:
    userinfo, optional warehouse and every referenced userdata.
    """
    account = str(account).strip()
    _encode_fixed(account)
    src_root = Path(source_server_root).expanduser().resolve()
    dst_root = Path(destination_server_root).expanduser().resolve()
    if src_root == dst_root:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_GRAPH_COPY", "reason": "SOURCE_EQUALS_DESTINATION", "source_server_root": str(src_root)}
    src_info = _path(src_root, "userinfo", account, ".dat")
    raw_info = _read_exact(src_info, USERINFO_SIZE, "SOURCE_USERINFO")
    embedded_account = _decode_fixed(raw_info, USERINFO_ACCOUNT_OFFSET)
    if embedded_account and embedded_account != account:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_GRAPH_COPY", "reason": "USERINFO_ACCOUNT_MISMATCH", "requested_account": account, "embedded_account": embedded_account, "path": str(src_info)}
    chars = [_decode_fixed(raw_info, USERINFO_CHARACTERS_OFFSET + i * USERINFO_CHARACTER_STRIDE) for i in range(USERINFO_CHARACTER_COUNT)]
    chars = [x for x in chars if x]
    targets: list[dict[str, Any]] = []

    def add(source: Path, destination: Path, role: str, *, required: bool = True) -> None:
        if not source.is_file():
            if required:
                raise FileNotFoundError(f"ACCOUNT_GRAPH_SOURCE_MISSING:{role}:{source}")
            return
        destination_exists = destination.is_file()
        targets.append({
            "role": role, "source": str(source), "destination": str(destination),
            "source_sha256": sha256_file(source),
            "destination_exists": destination_exists,
            "destination_sha256": sha256_file(destination) if destination_exists else None,
            "size": source.stat().st_size,
        })

    dst_info = _path(dst_root, "userinfo", account, ".dat")
    add(src_info, dst_info, "userinfo")
    src_wh = _path(src_root, "warehouse", account, ".war")
    dst_wh = _path(dst_root, "warehouse", account, ".war")
    add(src_wh, dst_wh, "warehouse", required=False)
    for char in chars:
        src_user = _path(src_root, "userdata", char, ".dat")
        raw = _read_exact(src_user, USERDATA_SIZE, f"SOURCE_USERDATA:{char}")
        embedded_char = _decode_fixed(raw, USERDATA_CHAR_OFFSET)
        embedded_acc = _decode_fixed(raw, USERDATA_ACCOUNT_OFFSET)
        if embedded_char and embedded_char != char:
            return {"format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_GRAPH_COPY", "reason": "USERDATA_CHARACTER_MISMATCH", "character": char, "embedded_character": embedded_char, "path": str(src_user)}
        if embedded_acc and embedded_acc != account:
            return {"format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_GRAPH_COPY", "reason": "USERDATA_ACCOUNT_MISMATCH", "character": char, "embedded_account": embedded_acc, "expected_account": account, "path": str(src_user)}
        add(src_user, _path(dst_root, "userdata", char, ".dat"), f"userdata:{char}")
    collisions = [t for t in targets if t["destination_exists"]]
    if collisions and not allow_replace:
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_GRAPH_COPY",
            "reason": "DESTINATION_GRAPH_EXISTS", "account": account,
            "source_server_root": str(src_root), "destination_server_root": str(dst_root),
            "characters": chars, "collisions": [{k:v for k,v in t.items() if k != "source_sha256"} for t in collisions],
            "hint": "Review destination identities first; set allow_replace only for an intentional migration/restore.",
        }
    return {
        "format": FORMAT, "status": "READY", "operation": "ACCOUNT_GRAPH_COPY",
        "server_root": str(dst_root), "source_server_root": str(src_root), "destination_server_root": str(dst_root),
        "account": account, "characters": chars, "target_count": len(targets), "targets": targets,
        "allow_replace": bool(allow_replace), "required_confirmation": ACCOUNT_GRAPH_COPY_CONFIRM,
        "legacy_evidence": {
            "ControllerUser.Copy": "parses 0xF0 userinfo into six 0x20 character slots and copies DataServer1/userdata/<bucket>/<name>.dat to DataServer/userdata/<bucket>/<name>.dat",
            "correction": "magic DataServer1 staging and mixed hard-coded paths are replaced by explicit source/destination roots and complete account graph copying",
        },
        "write_authorized": False,
    }


def apply_account_graph_copy(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != ACCOUNT_GRAPH_COPY_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{ACCOUNT_GRAPH_COPY_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "ACCOUNT_GRAPH_COPY":
        raise ValueError("ACCOUNT_GRAPH_COPY_PLAN_NOT_READY")
    from .common import atomic_write_bytes
    targets = list(plan.get("targets") or [])
    # Preflight the entire graph before creating a backup or changing one byte.
    for row in targets:
        src = Path(row["source"]); dst = Path(row["destination"])
        _verify_hash(src, row.get("source_sha256"))
        actual_dst = sha256_file(dst) if dst.is_file() else None
        if actual_dst != row.get("destination_sha256"):
            raise ValueError(f"ACCOUNT_GRAPH_DESTINATION_DRIFTED:{dst}")
        if dst.is_file() and not plan.get("allow_replace"):
            raise ValueError(f"ACCOUNT_GRAPH_DESTINATION_EXISTS:{dst}")
    backups: list[str] = []
    backup_by_destination: dict[Path, Path] = {}
    for row in targets:
        dst = Path(row["destination"])
        if dst.is_file():
            b = backup_file(dst, Path(backup_root), label="account_graph_copy")
            if b:
                backups.append(str(b))
                backup_by_destination[dst] = Path(b)
    written: list[Path] = []
    try:
        for row in targets:
            src = Path(row["source"]); dst = Path(row["destination"])
            atomic_write_bytes(dst, src.read_bytes())
            written.append(dst)
            if sha256_file(dst) != row["source_sha256"]:
                raise ValueError(f"ACCOUNT_GRAPH_POSTWRITE_HASH_MISMATCH:{dst}")
    except Exception:
        # Roll the destination graph back to its exact pre-write state. Existing
        # files are restored from their byte-for-byte backups; files that did not
        # exist before the operation are removed.  Rollback failures are surfaced
        # rather than hidden behind the original copy error.
        rollback_errors: list[str] = []
        for dst in reversed(written):
            try:
                backup = backup_by_destination.get(dst)
                if backup is not None and backup.is_file():
                    atomic_write_bytes(dst, backup.read_bytes())
                else:
                    dst.unlink(missing_ok=True)
            except Exception as exc:
                rollback_errors.append(f"{dst}:{type(exc).__name__}:{exc}")
        if rollback_errors:
            raise RuntimeError("ACCOUNT_GRAPH_ROLLBACK_FAILED:" + "|".join(rollback_errors))
        raise
    return {
        "format": FORMAT, "status": "PASS", "operation": "ACCOUNT_GRAPH_COPY",
        "account": plan.get("account"), "characters": list(plan.get("characters") or []),
        "source_server_root": plan.get("source_server_root"), "destination_server_root": plan.get("destination_server_root"),
        "written": [str(x) for x in written], "backups": backups,
    }


def _verify_hash(path: Path, expected: str | None) -> None:
    actual = sha256_file(path) if path.is_file() else None
    if actual != expected:
        raise ValueError(f"PERSISTENCE_FILE_DRIFTED:{path}:{expected}->{actual}")


def _backup_many(paths: list[Path], backup_root: Path, label: str) -> list[str]:
    out=[]
    for p in paths:
        b=backup_file(p, backup_root, label=label)
        if b: out.append(str(b))
    return out


def apply_character_rename(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != RENAME_CHARACTER_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{RENAME_CHARACTER_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "RENAME_CHARACTER":
        raise ValueError("CHARACTER_RENAME_PLAN_NOT_READY")
    src=Path(plan["source"]); dst=Path(plan["destination"]); info=Path(plan["userinfo"])
    if dst.exists(): raise ValueError("DESTINATION_CHARACTER_EXISTS")
    _verify_hash(src, plan["source_sha256"]); _verify_hash(info, plan["userinfo_sha256"])
    backups=_backup_many([src,info], Path(backup_root), "character_rename")
    # Preserve sources until every transformed destination/current file is durable.
    from .common import atomic_write_bytes
    atomic_write_bytes(dst, bytes(plan["new_userdata"]))
    try:
        atomic_write_bytes(info, bytes(plan["new_userinfo"]))
        src.unlink()
    except Exception:
        try: dst.unlink()
        except FileNotFoundError: pass
        raise
    return {"format":FORMAT,"status":"PASS","operation":"RENAME_CHARACTER","backups":backups,"source_removed":not src.exists(),"destination":str(dst),"destination_sha256":sha256_file(dst)}


def apply_account_rename(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != RENAME_ACCOUNT_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{RENAME_ACCOUNT_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "RENAME_ACCOUNT":
        raise ValueError("ACCOUNT_RENAME_PLAN_NOT_READY")
    old_info=Path(plan["source_userinfo"]); new_info=Path(plan["destination_userinfo"])
    if new_info.exists(): raise ValueError("DESTINATION_ACCOUNT_EXISTS")
    _verify_hash(old_info, plan["userinfo_sha256"])
    char_paths=[]
    for row in plan["characters"]:
        p=Path(row["path"]); _verify_hash(p,row["sha256"]); char_paths.append(p)
    old_wh=Path(plan["source_warehouse"]); new_wh=Path(plan["destination_warehouse"])
    _verify_hash(old_wh, plan.get("warehouse_sha256")) if plan.get("warehouse_sha256") else None
    if new_wh.exists(): raise ValueError("DESTINATION_WAREHOUSE_EXISTS")
    backups=_backup_many([old_info,*char_paths] + ([old_wh] if old_wh.is_file() else []), Path(backup_root), "account_rename")
    from .common import atomic_write_bytes
    # Write new files/current references before deleting any source.
    atomic_write_bytes(new_info, bytes(plan["new_userinfo"]))
    created=[new_info]
    try:
        for row in plan["characters"]:
            atomic_write_bytes(Path(row["path"]), bytes(row["new_userdata"]))
        if old_wh.is_file():
            new_wh.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(old_wh,new_wh); created.append(new_wh)
        old_info.unlink()
        if old_wh.is_file(): old_wh.unlink()
    except Exception:
        # The backups are the authoritative recovery point.  Remove only newly
        # created destination identity files; do not delete any source on error.
        for p in created:
            try: p.unlink()
            except FileNotFoundError: pass
        raise
    return {"format":FORMAT,"status":"PASS","operation":"RENAME_ACCOUNT","backups":backups,"source_userinfo_removed":not old_info.exists(),"destination_userinfo":str(new_info),"warehouse_moved":new_wh.is_file()}


def level_edit_capability(server_root: Path, character: str, *, xphen_path: Path | None = None) -> dict[str, Any]:
    """Report whether Level/XP editing can be planned for this server.

    Level Editor.exe proved the persistence offsets.  XP tables are server/game
    data rather than executable dependencies, so the Python port discovers and
    audits candidate XPHex tables instead of requiring one hard-coded filename.
    """
    path = _path(Path(server_root), "userdata", character, ".dat")
    discovery = None
    selected = Path(xphen_path) if xphen_path else None
    if selected is None:
        discovery = discover_xp_tables(Path(server_root), Path(server_root).parent)
        if discovery.get("recommended_path"):
            selected = Path(str(discovery["recommended_path"]))
    audit = audit_xphex(selected) if selected else None
    ready = bool(path.is_file() and audit and audit.get("write_usable"))
    reason = (
        "Character userdata and a monotonic XP table are available" if ready
        else "CHARACTER_USERDATA_NOT_FOUND" if not path.is_file()
        else str((audit or {}).get("reason") or "NO_VALID_XP_TABLE")
    )
    return {
        "format": FORMAT, "status": "READY" if ready else "BLOCKED",
        "operation": "LEVEL_EDIT", "character": character, "userdata_path": str(path),
        "userdata_exists": path.is_file(), "bucket": legacy_bucket(character),
        "xp_table_path": str(selected) if selected else None, "xp_table_audit": audit,
        "xp_table_discovery": discovery, "reason": reason, "write_authorized": False,
    }

LEVEL_INDEX_OFFSET = 0xC8
LEVEL_XP_LOW_OFFSET = 0x14C
LEVEL_XP_HIGH_OFFSET = 0x194
LEVEL_EDIT_CONFIRM = "APPLY CHARACTER LEVEL"


CHAR_INFO_OFFSET = 0x10
CHAR_INFO_CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "spc_win32_abi.json"


def _decode_abi_field(raw: bytes, offset: int, type_name: str, size: int) -> Any:
    chunk = raw[offset:offset + size]
    if len(chunk) != size:
        raise ValueError(f"ABI_FIELD_OUT_OF_RANGE:{offset}:{type_name}:{size}")
    if type_name.startswith("char["):
        return chunk.split(b"\0", 1)[0].decode("latin-1", errors="replace")
    m = re.fullmatch(r"(u?int)(8|16|32)(?:\[(\d+)\])?", type_name)
    if m:
        signed = m.group(1) == "int"
        width = int(m.group(2)) // 8
        count = int(m.group(3) or 1)
        vals = [int.from_bytes(chunk[i*width:(i+1)*width], "little", signed=signed) for i in range(count)]
        return vals[0] if count == 1 else vals
    m = re.fullmatch(r"float32(?:\[(\d+)\])?", type_name)
    if m:
        count = int(m.group(1) or 1)
        vals = list(struct.unpack("<" + "f" * count, chunk))
        return vals[0] if count == 1 else vals
    # Pointer-shaped source fields are serialized as 32-bit values in the Win32 ABI.
    if type_name in {"pointer", "ptr", "void*"}:
        return int.from_bytes(chunk, "little")
    return {"hex": chunk.hex(), "type": type_name}


def _char_info_schema() -> dict[str, Any]:
    data = json.loads(CHAR_INFO_CONTRACT.read_text(encoding="utf-8"))
    schema = (data.get("structs") or {}).get("smCHAR_INFO")
    if not isinstance(schema, dict) or int(schema.get("size") or 0) != 464:
        raise ValueError("SMCHAR_INFO_CONTRACT_INVALID")
    return schema


def inspect_character_info(server_root: Path, character: str) -> dict[str, Any]:
    """Decode the complete source-derived smCHAR_INFO embedded in userdata.

    ControllerUser/Level Editor reverse evidence places this structure at userdata
    +0x10.  The source-derived Win32 ABI independently places Level at +184, Exp
    at +316 and Exp_High at +388, producing absolute offsets 0xC8, 0x14C and
    0x194 observed in Level Editor.exe.  This cross-check is used as a guard.
    """
    path = _path(Path(server_root), "userdata", character, ".dat")
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    schema = _char_info_schema()
    fields: dict[str, Any] = {}
    offsets: dict[str, str] = {}
    for f in schema.get("fields") or []:
        name = str(f["name"]); rel = int(f["offset"]); size = int(f["size"]); typ = str(f["type"])
        absolute = CHAR_INFO_OFFSET + rel
        fields[name] = _decode_abi_field(raw, absolute, typ, size)
        offsets[name] = hex(absolute)
    expected = {"Level": LEVEL_INDEX_OFFSET, "Exp": LEVEL_XP_LOW_OFFSET, "Exp_High": LEVEL_XP_HIGH_OFFSET}
    actual = {k: CHAR_INFO_OFFSET + next(int(x["offset"]) for x in schema["fields"] if x["name"] == k) for k in expected}
    if actual != expected:
        raise RuntimeError(f"SMCHAR_INFO_REVERSE_CROSSCHECK_FAILED:{actual}!={expected}")
    return {
        "format": FORMAT, "status": "PASS", "operation": "CHARACTER_INFO_INSPECT",
        "character": character, "path": str(path), "sha256": sha256_file(path),
        "abi": "smCHAR_INFO Win32 source-derived", "struct_offset": hex(CHAR_INFO_OFFSET),
        "struct_size": int(schema["size"]), "fields": fields, "absolute_offsets": offsets,
        "reverse_crosscheck": {"Level": hex(LEVEL_INDEX_OFFSET), "Exp": hex(LEVEL_XP_LOW_OFFSET), "Exp_High": hex(LEVEL_XP_HIGH_OFFSET)},
        "write_authorized": False,
        "write_note": (
            "Read is fully source-backed. SumFile.dat, CompyItem.dat and *cp.dat seen in "
            "ControllerUser are generated scratch/export artifacts, not runtime dependencies. "
            "Item/serial mutations remain separately gated because their record/checksum semantics "
            "are more complex than direct smCHAR_INFO scalar fields."
        ),
    }


def controlleruser_reverse_artifacts() -> dict[str, Any]:
    """Explain ControllerUser scratch files recovered from the native binary.

    Static disassembly shows these paths being opened with GENERIC_WRITE and
    OPEN_ALWAYS after an input userdata/warehouse file is opened for reading.
    They are outputs/scratch artifacts of legacy scan/checksum tooling, not
    files that must exist in DataServer.
    """
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "CONTROLLERUSER_REVERSE_ARTIFACTS",
        "runtime_dependencies": [],
        "generated_legacy_artifacts": [
            {"name": "SumFile.dat", "role": "generated scan/checksum export", "required": False},
            {"name": "CompyItem.dat", "role": "generated comparison/item export", "required": False},
            {"name": "<target>cp.dat", "role": "generated per-target scratch/checksum copy", "required": False},
        ],
        "evidence": {
            "SumFile.dat": "ControllerUser CreateFileA: GENERIC_WRITE + OPEN_ALWAYS",
            "CompyItem.dat": "ControllerUser CreateFileA: GENERIC_WRITE + OPEN_ALWAYS",
            "cp.dat": "ControllerUser formats %s\\%scp.dat then opens it for GENERIC_WRITE + OPEN_ALWAYS",
        },
        "port_policy": "Do not require or recreate these files unless a specific compatibility export is requested.",
    }


def parse_xphex_text(text: str, *, allow_c_comments: bool = True) -> list[str]:
    """Parse an XP table used by the historical Level Editor.

    Accepted forms:
      * bare hexadecimal (``0000000003E8``),
      * C-style integer literals (``0x3E8,``),
      * blank/comment lines and block-commented future levels.

    Block-commented rows are deliberately ignored.  This is important for the
    supplied ``XPHex2.txt`` where levels after the active cap are kept inside a
    ``/* ... */`` block as reference data rather than live progression values.
    """
    rows: list[str] = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if allow_c_comments:
            # Strip block comments while preserving any prefix/suffix on a line.
            kept = ""
            i = 0
            while i < len(line):
                if in_block:
                    j = line.find("*/", i)
                    if j < 0:
                        i = len(line)
                        break
                    in_block = False
                    i = j + 2
                    continue
                j = line.find("/*", i)
                if j < 0:
                    kept += line[i:]
                    break
                kept += line[i:j]
                in_block = True
                i = j + 2
            line = kept.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        # Remove trailing // comments and normal C initializer punctuation.
        if "//" in line:
            line = line.split("//", 1)[0].strip()
        line = line.rstrip(",; ").strip()
        if not line:
            continue
        if line.lower().startswith("0x"):
            line = line[2:]
        line = line.replace(" ", "")
        if len(line) < 2 or len(line) > 16 or len(line) % 2:
            # C-style tables often use an odd number of hex digits.  Prefixing
            # one zero does not change the numeric value and yields whole bytes.
            if 1 <= len(line) <= 16 and len(line) % 2 == 1:
                line = "0" + line
            else:
                raise ValueError(f"XPHEX_LINE_LENGTH:{lineno}:expected_1_to_16_hex_digits")
        try:
            bytes.fromhex(line)
        except ValueError as exc:
            raise ValueError(f"XPHEX_LINE_NOT_HEX:{lineno}") from exc
        rows.append(line.upper())
    if in_block:
        raise ValueError("XPHEX_UNTERMINATED_BLOCK_COMMENT")
    if not rows:
        raise ValueError("XPHEX_EMPTY")
    return rows


def load_xphex(path: Path) -> list[str]:
    raw = Path(path).read_bytes()
    # The MSVC tool uses narrow std::ifstream. latin-1 preserves byte values
    # while accepting ordinary ASCII tables losslessly.
    return parse_xphex_text(raw.decode("latin-1"))


def audit_xphex(path: Path) -> dict[str, Any]:
    """Classify a candidate XP table before it is allowed to drive writes."""
    p = Path(path)
    result: dict[str, Any] = {
        "format": FORMAT,
        "operation": "XP_TABLE_AUDIT",
        "path": str(p),
        "exists": p.is_file(),
        "status": "BLOCKED",
        "write_usable": False,
    }
    if not p.is_file():
        result["reason"] = "XP_TABLE_NOT_FOUND"
        return result
    result["sha256"] = sha256_file(p)
    try:
        rows = load_xphex(p)
    except Exception as exc:
        result["reason"] = f"XP_TABLE_PARSE_FAILED:{type(exc).__name__}:{exc}"
        return result
    vals = [int(x, 16) for x in rows]
    nondecreasing = all(b >= a for a, b in zip(vals, vals[1:]))
    strictly_after_zero = all(b > a for a, b in zip(vals[1:], vals[2:])) if len(vals) > 2 else True
    result.update({
        "levels": len(rows),
        "first_value": vals[0],
        "last_value": vals[-1],
        "monotonic_nondecreasing": nondecreasing,
        "strictly_increasing_after_level_1": strictly_after_zero,
        "sample": [{"level": i + 1, "xp": vals[i], "hex": rows[i]} for i in range(min(5, len(rows)))],
    })
    if len(rows) < 2:
        result["reason"] = "XP_TABLE_TOO_SHORT"
        return result
    if not nondecreasing:
        result["reason"] = "XP_TABLE_NON_MONOTONIC: refusing to use as a level progression table"
        return result
    result["status"] = "PASS"
    result["write_usable"] = True
    result["reason"] = "Monotonic level-to-XP table"
    return result


def discover_xp_tables(*roots: Path) -> dict[str, Any]:
    """Discover and rank the server's historical XP tables.

    ``XPHex2.txt`` is preferred when it is valid because the supplied server
    corpus keeps its active progression there and block-comments future rows.
    ``XPHexOriginal.txt`` is treated as a valid historical fallback.  A file
    named exactly ``XPHex.txt`` is *not* trusted by name: it must pass the same
    monotonicity audit because corrupted/overwritten copies have existed.
    """
    names = ("XPHex2.txt", "XPHexOriginal.txt", "XPHex.txt")
    seen: set[Path] = set()
    audits: list[dict[str, Any]] = []
    for root in roots:
        r = Path(root).expanduser()
        candidates = [r / n for n in names]
        # Common project/server layouts: root, root/serverfiles, root/DataServer.
        candidates += [r / "serverfiles" / n for n in names]
        for p in candidates:
            try:
                key = p.resolve()
            except OSError:
                key = p.absolute()
            if key in seen:
                continue
            seen.add(key)
            if p.is_file():
                audits.append(audit_xphex(p))
    usable = [x for x in audits if x.get("write_usable")]
    preference = {"XPHex2.txt": 0, "XPHexOriginal.txt": 1, "XPHex.txt": 2}
    usable.sort(key=lambda x: (preference.get(Path(str(x["path"])).name, 99), -int(x.get("levels") or 0)))
    recommended = usable[0] if usable else None
    return {
        "format": FORMAT,
        "status": "PASS" if recommended else "BLOCKED",
        "operation": "XP_TABLE_DISCOVERY",
        "candidates": audits,
        "recommended_path": recommended.get("path") if recommended else None,
        "recommended_levels": recommended.get("levels") if recommended else None,
        "reason": (
            f"Recommended {Path(str(recommended['path'])).name}: valid monotonic active table"
            if recommended else "No monotonic XP table found; level writes remain blocked"
        ),
    }

def _xphex_to_userdata_bytes(hex_value: str) -> tuple[bytes, bytes]:
    """Encode a numeric XP value into the two 32-bit userdata fields.

    The legacy editor reconstructs little-endian bytes by reading pairs from the
    hexadecimal string right-to-left.  The Python port expresses the same ABI
    directly as a 64-bit integer, which also safely supports compact C literals
    such as ``0x5DC`` from XPHex2.txt.
    """
    value = hex_value.strip().removeprefix("0x").removeprefix("0X")
    try:
        number = int(value, 16)
    except ValueError as exc:
        raise ValueError("XPHEX_VALUE_NOT_HEX") from exc
    if number < 0 or number > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("XPHEX_VALUE_OUT_OF_UINT64_RANGE")
    raw = number.to_bytes(8, "little")
    return raw[:4], raw[4:]


def inspect_character_level(server_root: Path, character: str) -> dict[str, Any]:
    path = _path(Path(server_root), "userdata", character, ".dat")
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    level_index = int.from_bytes(raw[LEVEL_INDEX_OFFSET:LEVEL_INDEX_OFFSET + 2], "little")
    low = raw[LEVEL_XP_LOW_OFFSET:LEVEL_XP_LOW_OFFSET + 4]
    high = raw[LEVEL_XP_HIGH_OFFSET:LEVEL_XP_HIGH_OFFSET + 4]
    xp_bytes = low + high
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "LEVEL_INSPECT",
        "character": character,
        "path": str(path),
        "sha256": sha256_file(path),
        "level_index_zero_based": level_index,
        "level": level_index + 1,
        "xp_bytes_little_endian": xp_bytes.hex(),
        "xp_value": int.from_bytes(xp_bytes, "little"),
        "reverse_evidence": {
            "level_index_offset": hex(LEVEL_INDEX_OFFSET),
            "xp_low_offset": hex(LEVEL_XP_LOW_OFFSET),
            "xp_high_offset": hex(LEVEL_XP_HIGH_OFFSET),
            "legacy_ui_semantics": "GetDlgItemInt(level) -> level-1 -> vector index and userdata level index",
        },
    }


def plan_level_edit(server_root: Path, character: str, level: int, *, xphen_path: Path | None = None) -> dict[str, Any]:
    """Plan the exact Level Editor persistence mutation using an audited XP table.

    The executable logic and persistence offsets are recovered.  XPHex files are
    treated as server/game data and may be discovered automatically; filenames
    alone are never trusted, because only a monotonic table is allowed to drive a write.
    """
    level = int(level)
    if level < 1:
        raise ValueError("LEVEL_MUST_BE_AT_LEAST_1")
    table_discovery = None
    if xphen_path is None:
        table_discovery = discover_xp_tables(Path(server_root), Path(server_root).parent)
        selected = table_discovery.get("recommended_path")
        if not selected:
            return {
                "format": FORMAT, "status": "BLOCKED", "operation": "LEVEL_EDIT",
                "reason": "NO_VALID_XP_TABLE", "level": level,
                "xp_table_discovery": table_discovery,
            }
        xphen_path = Path(str(selected))
    xp_audit = audit_xphex(Path(xphen_path))
    if not xp_audit.get("write_usable"):
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "LEVEL_EDIT",
            "reason": str(xp_audit.get("reason") or "XP_TABLE_INVALID"),
            "level": level, "xp_table_audit": xp_audit,
        }
    rows = load_xphex(Path(xphen_path))
    if level > len(rows):
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "LEVEL_EDIT",
            "reason": "LEVEL_NOT_PRESENT_IN_XPHEX", "level": level, "xphex_levels": len(rows),
        }
    path = _path(Path(server_root), "userdata", character, ".dat")
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    before = inspect_character_level(server_root, character)
    hex_value = rows[level - 1]
    low, high = _xphex_to_userdata_bytes(hex_value)
    if len(high) > 4:
        raise ValueError("XPHEX_HIGH_PART_TOO_LARGE")
    out = bytearray(raw)
    # Legacy executable writes one byte when index<256, which can leave a stale
    # high byte when lowering a character from >=257.  Writing the proven 16-bit
    # little-endian field is the corrected behavior.
    out[LEVEL_INDEX_OFFSET:LEVEL_INDEX_OFFSET + 2] = (level - 1).to_bytes(2, "little")
    out[LEVEL_XP_LOW_OFFSET:LEVEL_XP_LOW_OFFSET + 4] = low.ljust(4, b"\0")
    out[LEVEL_XP_HIGH_OFFSET:LEVEL_XP_HIGH_OFFSET + 4] = high.ljust(4, b"\0")
    return {
        "format": FORMAT, "status": "READY", "operation": "LEVEL_EDIT",
        "server_root": str(Path(server_root).resolve()), "character": character,
        "path": str(path), "sha256_before": sha256_file(path),
        "level_before": before["level"], "level_after": level,
        "xp_before": before["xp_value"], "xp_after": int(hex_value, 16),
        "xphex_path": str(Path(xphen_path).resolve()), "xphex_sha256": sha256_file(Path(xphen_path)),
        "xphex_line": hex_value,
        "xp_table_audit": xp_audit,
        "xp_table_discovery": table_discovery,
        "new_userdata": bytes(out),
        "legacy_bug_corrected": (
            "Level Editor.exe writes only one byte of the zero-based level when it is below 256; "
            "the Python port writes the proven two-byte field so a previous high byte cannot survive."
        ),
        "write_authorized": False,
    }


def apply_level_edit(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != LEVEL_EDIT_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{LEVEL_EDIT_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "LEVEL_EDIT":
        raise ValueError("LEVEL_EDIT_PLAN_NOT_READY")
    path = Path(str(plan["path"]))
    _verify_hash(path, plan.get("sha256_before"))
    xphex = Path(str(plan["xphex_path"]))
    _verify_hash(xphex, plan.get("xphex_sha256"))
    backup = backup_file(path, Path(backup_root), label="level_edit")
    atomic_write_bytes(path, bytes(plan["new_userdata"]))
    after = inspect_character_level(Path(plan["server_root"]), str(plan["character"]))
    if after["level"] != int(plan["level_after"]) or after["xp_value"] != int(plan["xp_after"]):
        raise RuntimeError("LEVEL_EDIT_POST_WRITE_VERIFY_FAILED")
    return {
        "format": FORMAT, "status": "PASS", "operation": "LEVEL_EDIT",
        "path": str(path), "backup": str(backup) if backup else None,
        "sha256_after": sha256_file(path), "level": after["level"], "xp_value": after["xp_value"],
    }

# Fields that are meaningful persistence inputs and can be changed without inventing
# item serialization/checksum behavior.  Level/Exp are deliberately handled by the
# dedicated level workflow so the three coupled fields move together.
SAFE_CHARACTER_EDIT_FIELDS = {
    "Strength", "Spirit", "Talent", "Dexterity", "Health", "Money", "StatePoint",
}
CHARACTER_FIELDS_CONFIRM = "APPLY CHARACTER FIELDS"


def _abi_field_map() -> dict[str, dict[str, Any]]:
    schema = _char_info_schema()
    return {str(f["name"]): dict(f) for f in schema.get("fields") or []}


def _encode_abi_value(value: Any, type_name: str, size: int) -> bytes:
    m = re.fullmatch(r"(u?int)(8|16|32)(?:\[(\d+)\])?", type_name)
    if m:
        signed = m.group(1) == "int"
        width = int(m.group(2)) // 8
        count = int(m.group(3) or 1)
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) != count:
            raise ValueError(f"ABI_VALUE_COUNT:{type_name}:{len(values)}!={count}")
        out = bytearray()
        for item in values:
            try:
                out += int(item).to_bytes(width, "little", signed=signed)
            except OverflowError as exc:
                raise ValueError(f"ABI_VALUE_RANGE:{type_name}:{item}") from exc
        if len(out) != size:
            raise ValueError(f"ABI_ENCODE_SIZE:{type_name}:{len(out)}!={size}")
        return bytes(out)
    m = re.fullmatch(r"float32(?:\[(\d+)\])?", type_name)
    if m:
        count = int(m.group(1) or 1)
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) != count:
            raise ValueError(f"ABI_VALUE_COUNT:{type_name}:{len(values)}!={count}")
        out = struct.pack("<" + "f" * count, *[float(x) for x in values])
        if len(out) != size:
            raise ValueError(f"ABI_ENCODE_SIZE:{type_name}:{len(out)}!={size}")
        return out
    raise ValueError(f"ABI_WRITE_TYPE_NOT_SUPPORTED:{type_name}")


def character_edit_capabilities() -> dict[str, Any]:
    """Expose the safe default subset of the old character editors.

    Japaokiko/ControllerUser exposed many raw/derived values.  The Python port
    intentionally edits only primary persisted inputs by default.  Derived combat
    values remain inspectable but are not independently writable because the game
    may recalculate them from primary stats/equipment.
    """
    all_fields = _abi_field_map()
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "CHARACTER_EDIT_CAPABILITIES",
        "safe_edit_fields": sorted(SAFE_CHARACTER_EDIT_FIELDS),
        "dedicated_workflows": {
            "Level/Exp": "plan_level_edit/apply_level_edit",
            "character name": "plan_character_rename/apply_character_rename",
            "account": "plan_account_rename/apply_account_rename",
        },
        "readable_fields": sorted(all_fields),
        "item_serial_fields": "SEPARATE_VARIABLE_LENGTH_FORMAT",
        "legacy_scratch_files_required": False,
    }


def plan_character_fields_update(
    server_root: Path,
    character: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Plan safe scalar edits to source-backed smCHAR_INFO fields."""
    if not updates:
        raise ValueError("CHARACTER_FIELD_UPDATES_REQUIRED")
    unknown = sorted(set(updates) - SAFE_CHARACTER_EDIT_FIELDS)
    if unknown:
        raise ValueError(
            "CHARACTER_FIELDS_REQUIRE_DEDICATED_OR_EXPERT_WORKFLOW:" + ",".join(unknown)
        )
    path = _path(Path(server_root), "userdata", character, ".dat")
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    fields = _abi_field_map()
    out = bytearray(raw)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    offsets: dict[str, str] = {}
    for name, value in updates.items():
        f = fields[name]
        absolute = CHAR_INFO_OFFSET + int(f["offset"])
        size = int(f["size"])
        typ = str(f["type"])
        before[name] = _decode_abi_field(raw, absolute, typ, size)
        encoded = _encode_abi_value(value, typ, size)
        out[absolute:absolute + size] = encoded
        after[name] = _decode_abi_field(bytes(out), absolute, typ, size)
        offsets[name] = hex(absolute)
    return {
        "format": FORMAT,
        "status": "READY",
        "operation": "CHARACTER_FIELDS_UPDATE",
        "character": character,
        "path": str(path),
        "sha256_before": sha256_file(path),
        "updates": dict(updates),
        "before": before,
        "after": after,
        "absolute_offsets": offsets,
        "new_userdata": bytes(out),
        "safety": {
            "source_abi": "smCHAR_INFO Win32 source-derived",
            "scratch_dat_dependencies": False,
            "inventory_or_item_serials_modified": False,
            "level_exp_modified": False,
        },
        "write_authorized": False,
    }


def apply_character_fields_update(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != CHARACTER_FIELDS_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{CHARACTER_FIELDS_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "CHARACTER_FIELDS_UPDATE":
        raise ValueError("CHARACTER_FIELDS_PLAN_NOT_READY")
    path = Path(str(plan["path"]))
    _verify_hash(path, str(plan["sha256_before"]))
    backup = backup_file(path, Path(backup_root), label="character_fields")
    atomic_write_bytes(path, bytes(plan["new_userdata"]))
    # Verify only the bytes/fields changed; do not invoke path discovery with a
    # synthetic server root here.
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    field_map = _abi_field_map()
    verified: dict[str, Any] = {}
    for name, expected in dict(plan["after"]).items():
        f = field_map[name]
        absolute = CHAR_INFO_OFFSET + int(f["offset"])
        actual = _decode_abi_field(raw, absolute, str(f["type"]), int(f["size"]))
        if actual != expected:
            raise RuntimeError(f"CHARACTER_FIELD_POST_WRITE_VERIFY_FAILED:{name}:{expected}->{actual}")
        verified[name] = actual
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "CHARACTER_FIELDS_UPDATE",
        "character": plan.get("character"),
        "path": str(path),
        "backup": str(backup) if backup else None,
        "sha256_after": sha256_file(path),
        "verified": verified,
    }

# Expert replacement for the raw scalar section exposed by Japaokiko/ControllerUser.
# This is intentionally still schema-driven: no arbitrary offsets are accepted.
# Runtime pointers/login keys/temp scratch are excluded even though they exist in the
# Win32 struct, because writing them to persistence has no useful authoring meaning.
EXPERT_CHARACTER_EDIT_FIELDS = {
    "szModelName", "szModelName2", "ModelNameCode2", "dwObjectSerial",
    "ClassClan", "State", "SizeLevel", "dwCharSoundCode", "JOB_CODE",
    "Strength", "Spirit", "Talent", "Dexterity", "Health",
    "Accuracy", "Attack_Rating", "Attack_Damage", "Attack_Speed", "Shooting_Range",
    "Critical_Hit", "Defence", "Chance_Block", "Absorption", "Move_Speed", "Sight",
    "Weight", "Resistance", "Attack_Resistance", "Life", "Mana", "Stamina",
    "Life_Regen", "Mana_Regen", "Stamina_Regen", "Next_Exp", "Money", "Brood",
    "StatePoint", "bUpdateInfo", "ArrowPosi", "Potion_Space", "LifeFunction",
    "ManaFunction", "StaminaFunction", "DamageFunction", "RefomCode", "ChangeJob",
    "JobBitMask", "wPlayerKilling", "wPlayClass", "dwEventTime_T", "sEventParam",
    "sPresentItem", "GravityScroolCheck",
}
EXPERT_CHARACTER_FIELDS_CONFIRM = "APPLY EXPERT CHARACTER FIELDS"


def _encode_expert_abi_value(value: Any, type_name: str, size: int) -> bytes:
    if type_name.startswith("char["):
        if not isinstance(value, str):
            raise ValueError(f"ABI_STRING_REQUIRED:{type_name}")
        raw = value.encode("latin-1", errors="strict")
        if len(raw) >= size:
            raise ValueError(f"ABI_STRING_TOO_LONG:{len(raw)}>=${size}".replace("$", ""))
        return raw + b"\0" * (size - len(raw))
    return _encode_abi_value(value, type_name, size)


def expert_character_edit_capabilities() -> dict[str, Any]:
    fmap = _abi_field_map()
    blocked = sorted(set(fmap) - EXPERT_CHARACTER_EDIT_FIELDS - {"szName", "Level", "Exp", "Exp_High"})
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "EXPERT_CHARACTER_EDIT_CAPABILITIES",
        "editable_fields": sorted(EXPERT_CHARACTER_EDIT_FIELDS),
        "dedicated_fields": {
            "szName": "character rename workflow",
            "Level/Exp/Exp_High": "Level/XP workflow",
        },
        "blocked_fields": blocked,
        "blocked_reason": "Runtime pointers, login/security values and scratch/temp fields are not useful persistence authoring inputs.",
        "warning": "Derived combat fields are source-backed but may be recalculated by the game. Expert mode preserves legacy editor capability; prefer primary stats for normal use.",
        "arbitrary_offsets": False,
    }


def plan_character_expert_fields_update(server_root: Path, character: str, updates: dict[str, Any]) -> dict[str, Any]:
    if not updates:
        raise ValueError("EXPERT_CHARACTER_FIELD_UPDATES_REQUIRED")
    unknown = sorted(set(updates) - EXPERT_CHARACTER_EDIT_FIELDS)
    if unknown:
        raise ValueError("EXPERT_CHARACTER_FIELDS_BLOCKED_OR_UNKNOWN:" + ",".join(unknown))
    path = _path(Path(server_root), "userdata", character, ".dat")
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    fields = _abi_field_map()
    out = bytearray(raw)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    offsets: dict[str, str] = {}
    for name, value in updates.items():
        f = fields[name]
        absolute = CHAR_INFO_OFFSET + int(f["offset"])
        size = int(f["size"])
        typ = str(f["type"])
        before[name] = _decode_abi_field(raw, absolute, typ, size)
        encoded = _encode_expert_abi_value(value, typ, size)
        out[absolute:absolute + size] = encoded
        after[name] = _decode_abi_field(bytes(out), absolute, typ, size)
        offsets[name] = hex(absolute)
    return {
        "format": FORMAT,
        "status": "READY",
        "operation": "CHARACTER_EXPERT_FIELDS_UPDATE",
        "character": character,
        "path": str(path),
        "sha256_before": sha256_file(path),
        "updates": dict(updates),
        "before": before,
        "after": after,
        "absolute_offsets": offsets,
        "new_userdata": bytes(out),
        "safety": {
            "source_abi": "smCHAR_INFO Win32 source-derived",
            "arbitrary_offsets": False,
            "runtime_security_fields_modified": False,
            "inventory_or_item_serials_modified": False,
            "level_exp_modified": False,
            "derived_values_may_be_recalculated": True,
        },
        "write_authorized": False,
    }


def apply_character_expert_fields_update(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != EXPERT_CHARACTER_FIELDS_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{EXPERT_CHARACTER_FIELDS_CONFIRM}")
    if plan.get("status") != "READY" or plan.get("operation") != "CHARACTER_EXPERT_FIELDS_UPDATE":
        raise ValueError("EXPERT_CHARACTER_FIELDS_PLAN_NOT_READY")
    path = Path(str(plan["path"]))
    _verify_hash(path, str(plan["sha256_before"]))
    backup = backup_file(path, Path(backup_root), label="character_expert_fields")
    atomic_write_bytes(path, bytes(plan["new_userdata"]))
    raw = _read_exact(path, USERDATA_SIZE, "USERDATA")
    fmap = _abi_field_map()
    verified: dict[str, Any] = {}
    for name, expected in dict(plan["after"]).items():
        f = fmap[name]
        absolute = CHAR_INFO_OFFSET + int(f["offset"])
        actual = _decode_abi_field(raw, absolute, str(f["type"]), int(f["size"]))
        if actual != expected:
            raise RuntimeError(f"EXPERT_CHARACTER_FIELD_POST_WRITE_VERIFY_FAILED:{name}:{expected}->{actual}")
        verified[name] = actual
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "CHARACTER_EXPERT_FIELDS_UPDATE",
        "character": plan.get("character"),
        "path": str(path),
        "backup": str(backup) if backup else None,
        "sha256_after": sha256_file(path),
        "verified": verified,
    }
