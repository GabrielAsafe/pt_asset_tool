from __future__ import annotations

"""ControllerUser fixed-record inventory codec and the proven persistent delete.

Native reverse evidence from ControllerUser.exe shows a zero-run codec used to
expand item records to fixed structs before inspection/deletion.  The only
persistent item mutation promoted here is the operation proven in the native
handler: zero one selected record, rebuild the compressed persistence payload,
and rewrite the whole userdata/warehouse file.

Arbitrary Code/Head/CheckSum editing is deliberately NOT exposed: the legacy UI
contains those fields, but the reversed write path does not prove such a writer.
"""

from pathlib import Path
from typing import Any
import hashlib
import shutil

from .common import atomic_write_bytes, backup_file, dataserver_path, sha256_file

FORMAT = "PT_CONTROLLER_INVENTORY_V1"
DELETE_CONFIRM = "DELETE INVENTORY ITEM"
BATCH_DELETE_CONFIRM = "DELETE INVENTORY ITEMS"
SCOPE_CLEAR_CONFIRM = {
    "userdata": "CLEAR ALL USERDATA ITEMS",
    "warehouse": "CLEAR ALL WAREHOUSE ITEMS",
}

USERDATA_SIZE = 0x1B310
USER_ITEM_COUNT_OFFSET = 0x6E4
USER_ITEM_PAYLOAD_OFFSET = 0x6F0
USER_ITEM_STRUCT_SIZE = 0x224
USER_MAX_ITEM_RECORDS = 200
USER_HEAD_OFFSET = 0x14
USER_CHECKSUM_OFFSET = 0x20
USER_CODE_OFFSET = 0x28

WAREHOUSE_SIZE = 0x13500
WAREHOUSE_HEADER_SIZE = 0x30
WAREHOUSE_RECORD_SIZE = 0x314
WAREHOUSE_RECORD_COUNT = 100
WAREHOUSE_HEAD_OFFSET = 0x104
WAREHOUSE_CHECKSUM_OFFSET = 0x110
WAREHOUSE_CODE_OFFSET = 0x118


class ControllerInventoryError(ValueError):
    pass


def _u32(raw: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(raw):
        raise ControllerInventoryError(f"U32_OUT_OF_RANGE:{offset}")
    return int.from_bytes(raw[offset:offset + 4], "little", signed=False)


def _put_u32(buf: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset + 4 > len(buf):
        raise ControllerInventoryError(f"U32_OUT_OF_RANGE:{offset}")
    buf[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")


def legacy_zero_rle_decompress(blob: bytes, *, expected_size: int | None = None) -> bytes:
    """Decode ControllerUser's high-bit zero-run / low-bit literal codec.

    The first little-endian dword is the total compressed byte count INCLUDING
    that dword.  Tokens are 1..127.  0x80|n emits n zero bytes; n emits the next
    n literal bytes.
    """
    if len(blob) < 4:
        raise ControllerInventoryError("RLE_HEADER_TRUNCATED")
    total = _u32(blob, 0)
    if total < 4 or total > len(blob):
        raise ControllerInventoryError(f"RLE_LENGTH_INVALID:{total}:{len(blob)}")
    p = 4
    out = bytearray()
    while p < total:
        token = blob[p]
        p += 1
        count = token & 0x7F
        if count == 0:
            raise ControllerInventoryError("RLE_ZERO_LENGTH_TOKEN")
        if token & 0x80:
            out.extend(b"\x00" * count)
        else:
            if p + count > total:
                raise ControllerInventoryError("RLE_LITERAL_TRUNCATED")
            out.extend(blob[p:p + count])
            p += count
        if expected_size is not None and len(out) > expected_size:
            raise ControllerInventoryError("RLE_OUTPUT_EXCEEDS_EXPECTED_SIZE")
    if p != total:
        raise ControllerInventoryError("RLE_CURSOR_MISMATCH")
    if expected_size is not None and len(out) != expected_size:
        raise ControllerInventoryError(f"RLE_OUTPUT_SIZE:{len(out)}:{expected_size}")
    return bytes(out)


def legacy_zero_rle_compress(raw: bytes) -> bytes:
    """Encode the native codec deterministically.

    Native evidence treats a run of >=2 zero bytes as a zero-run.  Isolated zero
    bytes may remain in literal runs.  Both token types are capped at 127 bytes.
    """
    data = bytes(raw)
    body = bytearray()
    i = 0
    n = len(data)
    while i < n:
        if data[i] == 0 and i + 1 < n and data[i + 1] == 0:
            run = 2
            while i + run < n and data[i + run] == 0 and run < 127:
                run += 1
            body.append(0x80 | run)
            i += run
            continue

        start = i
        i += 1
        while i < n and i - start < 127:
            # Stop BEFORE a compressible zero run; a single zero remains literal.
            if data[i] == 0 and i + 1 < n and data[i + 1] == 0:
                break
            i += 1
        literal = data[start:i]
        if not literal:
            raise AssertionError("empty literal")
        body.append(len(literal))
        body.extend(literal)
    total = 4 + len(body)
    return total.to_bytes(4, "little") + bytes(body)


def _decode_user_records(raw: bytes) -> list[bytes]:
    if len(raw) != USERDATA_SIZE:
        raise ControllerInventoryError(f"USERDATA_SIZE:{len(raw)}:{USERDATA_SIZE}")
    count = _u32(raw, USER_ITEM_COUNT_OFFSET)
    if count > USER_MAX_ITEM_RECORDS:
        raise ControllerInventoryError(f"USER_ITEM_COUNT:{count}:{USER_MAX_ITEM_RECORDS}")
    records: list[bytes] = []
    p = USER_ITEM_PAYLOAD_OFFSET
    for index in range(count):
        if p + 4 > len(raw):
            raise ControllerInventoryError(f"USER_RECORD_HEADER_TRUNCATED:{index}")
        clen = _u32(raw, p)
        if clen < 4 or p + clen > len(raw):
            raise ControllerInventoryError(f"USER_RECORD_COMPRESSED_LENGTH:{index}:{clen}")
        records.append(legacy_zero_rle_decompress(raw[p:p + clen], expected_size=USER_ITEM_STRUCT_SIZE))
        p += clen
    return records


def _encode_user_records(original: bytes, records: list[bytes]) -> bytes:
    if len(original) != USERDATA_SIZE:
        raise ControllerInventoryError("USERDATA_SIZE_INVALID")
    payload = b"".join(legacy_zero_rle_compress(r) for r in records)
    capacity = USERDATA_SIZE - USER_ITEM_PAYLOAD_OFFSET
    if len(payload) > capacity:
        raise ControllerInventoryError(f"USER_PAYLOAD_TOO_LARGE:{len(payload)}:{capacity}")
    out = bytearray(original)
    # Preserve everything before the item payload; make the remaining fixed
    # area deterministic instead of leaving stale bytes after recompression.
    out[USER_ITEM_PAYLOAD_OFFSET:] = b"\x00" * capacity
    out[USER_ITEM_PAYLOAD_OFFSET:USER_ITEM_PAYLOAD_OFFSET + len(payload)] = payload
    _put_u32(out, USER_ITEM_COUNT_OFFSET, len(records))
    return bytes(out)


def _decode_warehouse_records(raw: bytes) -> list[bytes]:
    if len(raw) != WAREHOUSE_SIZE:
        raise ControllerInventoryError(f"WAREHOUSE_SIZE:{len(raw)}:{WAREHOUSE_SIZE}")
    blob = raw[WAREHOUSE_HEADER_SIZE:]
    expanded = legacy_zero_rle_decompress(
        blob,
        expected_size=WAREHOUSE_RECORD_COUNT * WAREHOUSE_RECORD_SIZE,
    )
    return [
        expanded[i * WAREHOUSE_RECORD_SIZE:(i + 1) * WAREHOUSE_RECORD_SIZE]
        for i in range(WAREHOUSE_RECORD_COUNT)
    ]


def _encode_warehouse_records(original: bytes, records: list[bytes]) -> bytes:
    if len(original) != WAREHOUSE_SIZE:
        raise ControllerInventoryError("WAREHOUSE_SIZE_INVALID")
    if len(records) != WAREHOUSE_RECORD_COUNT:
        raise ControllerInventoryError(f"WAREHOUSE_RECORD_COUNT:{len(records)}")
    expanded = b"".join(records)
    blob = legacy_zero_rle_compress(expanded)
    capacity = WAREHOUSE_SIZE - WAREHOUSE_HEADER_SIZE
    if len(blob) > capacity:
        raise ControllerInventoryError(f"WAREHOUSE_PAYLOAD_TOO_LARGE:{len(blob)}:{capacity}")
    out = bytearray(WAREHOUSE_SIZE)
    # Intentional correction over the native routine: preserve the real 0x30
    # byte warehouse header.  The reversed legacy function writes from a local
    # output buffer whose prefix is not demonstrably initialized from source.
    out[:WAREHOUSE_HEADER_SIZE] = original[:WAREHOUSE_HEADER_SIZE]
    out[WAREHOUSE_HEADER_SIZE:WAREHOUSE_HEADER_SIZE + len(blob)] = blob
    return bytes(out)


def _record_summary(record: bytes, *, code_offset: int, head_offset: int, checksum_offset: int, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "empty": not any(record),
        "code": _u32(record, code_offset),
        "head": _u32(record, head_offset),
        "checksum": _u32(record, checksum_offset),
        "sha256": hashlib.sha256(record).hexdigest(),
    }


def inspect_fixed_inventory(path: Path, *, store: str) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_bytes()
    kind = str(store).lower()
    if kind == "userdata":
        records = _decode_user_records(raw)
        rows = [_record_summary(r, code_offset=USER_CODE_OFFSET, head_offset=USER_HEAD_OFFSET, checksum_offset=USER_CHECKSUM_OFFSET, index=i) for i, r in enumerate(records)]
    elif kind == "warehouse":
        records = _decode_warehouse_records(raw)
        rows = [_record_summary(r, code_offset=WAREHOUSE_CODE_OFFSET, head_offset=WAREHOUSE_HEAD_OFFSET, checksum_offset=WAREHOUSE_CHECKSUM_OFFSET, index=i) for i, r in enumerate(records)]
    else:
        raise ControllerInventoryError(f"STORE_INVALID:{store}")
    return {
        "format": FORMAT,
        "status": "PASS",
        "store": kind,
        "path": str(p),
        "sha256": sha256_file(p),
        "record_count": len(rows),
        "nonempty_count": sum(0 if r["empty"] else 1 for r in rows),
        "records": rows,
        "write_capability": "DELETE_SELECTED_OR_REVIEWED_BATCH_RECORDS",
        "write_authorized": False,
        "provenance": "ControllerUser.exe native fixed-record decode/delete path",
    }


def _store_path(server_root: Path, store: str, key: str) -> Path:
    root = Path(server_root).resolve()
    kind = str(store).lower()
    if kind == "userdata":
        return dataserver_path(root, "userdata", key, ".dat")
    if kind == "warehouse":
        return dataserver_path(root, "warehouse", key, ".war")
    raise ControllerInventoryError(f"STORE_INVALID:{store}")


def plan_item_delete(server_root: Path, *, store: str, key: str, record_index: int) -> dict[str, Any]:
    path = _store_path(server_root, store, key)
    if not path.is_file():
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_DELETE", "reason": "STORE_FILE_NOT_FOUND", "path": str(path)}
    raw = path.read_bytes()
    kind = str(store).lower()
    if kind == "userdata":
        records = _decode_user_records(raw)
        code_offset, head_offset, checksum_offset = USER_CODE_OFFSET, USER_HEAD_OFFSET, USER_CHECKSUM_OFFSET
        encoder = _encode_user_records
    else:
        records = _decode_warehouse_records(raw)
        code_offset, head_offset, checksum_offset = WAREHOUSE_CODE_OFFSET, WAREHOUSE_HEAD_OFFSET, WAREHOUSE_CHECKSUM_OFFSET
        encoder = _encode_warehouse_records
    idx = int(record_index)
    if idx < 0 or idx >= len(records):
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_DELETE", "reason": "RECORD_INDEX_OUT_OF_RANGE", "record_index": idx, "record_count": len(records), "path": str(path)}
    selected = records[idx]
    if not any(selected):
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_DELETE", "reason": "RECORD_ALREADY_EMPTY", "record_index": idx, "path": str(path)}
    before = _record_summary(selected, code_offset=code_offset, head_offset=head_offset, checksum_offset=checksum_offset, index=idx)
    changed = list(records)
    changed[idx] = bytes(len(selected))
    new_raw = encoder(raw, changed)
    return {
        "format": FORMAT,
        "status": "READY",
        "operation": "INVENTORY_ITEM_DELETE",
        "server_root": str(Path(server_root).resolve()),
        "store": kind,
        "key": str(key),
        "path": str(path),
        "record_index": idx,
        "guard": {"code": before["code"], "head": before["head"], "checksum": before["checksum"], "record_sha256": before["sha256"]},
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "result_sha256": hashlib.sha256(new_raw).hexdigest(),
        "new_bytes": new_raw,
        "change": {"before": before, "after": {"index": idx, "empty": True}},
        "write_authorized": False,
        "required_confirmation": DELETE_CONFIRM,
        "safety": {
            "arbitrary_item_edit": False,
            "delete_only": True,
            "warehouse_header_preserved": kind == "warehouse",
        },
    }



def plan_item_batch_delete(server_root: Path, *, store: str, key: str, record_indices: list[int] | tuple[int, ...]) -> dict[str, Any]:
    """Plan a reviewed batch delete using the same proven native record delete.

    ControllerUser's AllDelete iterates a result table and invokes the same
    fixed-record delete worker for every row.  The Python port deliberately
    requires the operator to provide the concrete slot indices and rewrites the
    persistence file once, so every guard is evaluated against one source hash.
    """
    path = _store_path(server_root, store, key)
    if not path.is_file():
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_BATCH_DELETE", "reason": "STORE_FILE_NOT_FOUND", "path": str(path)}
    raw = path.read_bytes()
    kind = str(store).lower()
    if kind == "userdata":
        records = _decode_user_records(raw)
        code_offset, head_offset, checksum_offset = USER_CODE_OFFSET, USER_HEAD_OFFSET, USER_CHECKSUM_OFFSET
        encoder = _encode_user_records
    elif kind == "warehouse":
        records = _decode_warehouse_records(raw)
        code_offset, head_offset, checksum_offset = WAREHOUSE_CODE_OFFSET, WAREHOUSE_HEAD_OFFSET, WAREHOUSE_CHECKSUM_OFFSET
        encoder = _encode_warehouse_records
    else:
        raise ControllerInventoryError(f"STORE_INVALID:{store}")

    try:
        indices = sorted({int(x) for x in record_indices})
    except Exception as exc:
        raise ControllerInventoryError("RECORD_INDICES_INVALID") from exc
    if not indices:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_BATCH_DELETE", "reason": "NO_RECORD_INDICES", "path": str(path)}

    bad = [i for i in indices if i < 0 or i >= len(records)]
    if bad:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_BATCH_DELETE", "reason": "RECORD_INDEX_OUT_OF_RANGE", "invalid_indices": bad, "record_count": len(records), "path": str(path)}
    empty = [i for i in indices if not any(records[i])]
    if empty:
        return {"format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_ITEM_BATCH_DELETE", "reason": "RECORD_ALREADY_EMPTY", "empty_indices": empty, "path": str(path)}

    guards=[]
    changed=list(records)
    for idx in indices:
        row=_record_summary(records[idx], code_offset=code_offset, head_offset=head_offset, checksum_offset=checksum_offset, index=idx)
        guards.append({"index": idx, "code": row["code"], "head": row["head"], "checksum": row["checksum"], "record_sha256": row["sha256"]})
        changed[idx]=bytes(len(records[idx]))
    new_raw=encoder(raw, changed)
    return {
        "format": FORMAT,
        "status": "READY",
        "operation": "INVENTORY_ITEM_BATCH_DELETE",
        "server_root": str(Path(server_root).resolve()),
        "store": kind,
        "key": str(key),
        "path": str(path),
        "record_indices": indices,
        "guards": guards,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "result_sha256": hashlib.sha256(new_raw).hexdigest(),
        "new_bytes": new_raw,
        "changes": [{"before": {"index": g["index"], "code": g["code"], "head": g["head"], "checksum": g["checksum"], "sha256": g["record_sha256"]}, "after": {"index": g["index"], "empty": True}} for g in guards],
        "write_authorized": False,
        "required_confirmation": BATCH_DELETE_CONFIRM,
        "safety": {
            "arbitrary_item_edit": False,
            "delete_only": True,
            "explicit_slot_list_required": True,
            "single_rewrite": True,
            "warehouse_header_preserved": kind == "warehouse",
            "native_equivalence": "ControllerUser AllDelete iterates the proven fixed-record delete worker",
        },
    }



def _iter_scope_files(server_root: Path, store: str) -> list[Path]:
    root = Path(server_root).resolve() / "DataServer" / str(store).lower()
    if not root.is_dir():
        return []
    suffix = ".dat" if str(store).lower() == "userdata" else ".war" if str(store).lower() == "warehouse" else None
    if suffix is None:
        raise ControllerInventoryError(f"STORE_INVALID:{store}")
    out: list[Path] = []
    for bucket in range(256):
        d = root / str(bucket)
        if not d.is_dir():
            continue
        try:
            out.extend(sorted((x for x in d.iterdir() if x.is_file() and x.suffix.casefold() == suffix), key=lambda x: x.name.casefold()))
        except OSError:
            continue
    return out


def _clear_inventory_raw(raw: bytes, *, store: str) -> tuple[bytes, int, int]:
    kind = str(store).lower()
    if kind == "userdata":
        records = _decode_user_records(raw)
        encoder = _encode_user_records
    elif kind == "warehouse":
        records = _decode_warehouse_records(raw)
        encoder = _encode_warehouse_records
    else:
        raise ControllerInventoryError(f"STORE_INVALID:{store}")
    nonempty = sum(1 for r in records if any(r))
    cleared = [bytes(len(r)) for r in records]
    return encoder(raw, cleared), len(records), nonempty


def plan_inventory_scope_clear(server_root: Path, *, store: str) -> dict[str, Any]:
    """Plan ControllerUser's destructive WHItem/User Item scope clear safely.

    Native reverse proves that the WHItem and User Item buttons enumerate every
    bucket and rewrite each matching warehouse/userdata after zeroing all fixed
    item records.  The Python port keeps this capability, but never mutates while
    discovering targets: it records every source/result hash first and apply()
    performs a global drift preflight plus backups before the first write.
    """
    root = Path(server_root).resolve()
    kind = str(store).lower()
    if kind not in SCOPE_CLEAR_CONFIRM:
        raise ControllerInventoryError(f"STORE_INVALID:{store}")
    files = _iter_scope_files(root, kind)
    if not files:
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_SCOPE_CLEAR",
            "reason": "NO_STORE_FILES", "server_root": str(root), "store": kind,
        }
    targets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    total_records = total_nonempty = 0
    for path in files:
        try:
            raw = path.read_bytes()
            result, record_count, nonempty = _clear_inventory_raw(raw, store=kind)
            rel = path.relative_to(root).as_posix()
            targets.append({
                "relative_path": rel,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "result_sha256": hashlib.sha256(result).hexdigest(),
                "record_count": record_count,
                "nonempty_count": nonempty,
            })
            total_records += record_count
            total_nonempty += nonempty
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}:{exc}"})
    if errors:
        return {
            "format": FORMAT, "status": "BLOCKED", "operation": "INVENTORY_SCOPE_CLEAR",
            "reason": "SCOPE_PREFLIGHT_FAILED", "server_root": str(root), "store": kind,
            "scanned_file_count": len(files), "valid_target_count": len(targets), "errors": errors,
        }
    return {
        "format": FORMAT, "status": "READY", "operation": "INVENTORY_SCOPE_CLEAR",
        "server_root": str(root), "store": kind, "target_count": len(targets),
        "record_count": total_records, "nonempty_item_count": total_nonempty,
        "targets": targets, "write_authorized": False,
        "required_confirmation": SCOPE_CLEAR_CONFIRM[kind],
        "safety": {
            "mass_destructive": True,
            "discovery_is_read_only": True,
            "all_targets_preflighted_before_write": True,
            "all_targets_backed_up_before_write": True,
            "rollback_on_write_failure": True,
            "warehouse_header_preserved": kind == "warehouse",
            "native_equivalence": "ControllerUser WHItem/User Item enumerate 256 buckets and clear every matching persistence file",
        },
    }


def apply_inventory_scope_clear(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if str(plan.get("status") or "") != "READY" or plan.get("operation") != "INVENTORY_SCOPE_CLEAR":
        raise ControllerInventoryError("INVENTORY_SCOPE_CLEAR_PLAN_NOT_READY")
    kind = str(plan.get("store") or "").lower()
    required = SCOPE_CLEAR_CONFIRM.get(kind)
    if not required or confirmation != required:
        raise ControllerInventoryError(f"CONFIRMATION_REQUIRED:{required or 'UNKNOWN'}")
    server_root = Path(str(plan.get("server_root") or "")).resolve()
    targets = list(plan.get("targets") or [])
    if not targets:
        raise ControllerInventoryError("INVENTORY_SCOPE_CLEAR_TARGETS_EMPTY")

    # Global preflight: no write or backup happens until every source still
    # matches the reviewed plan and recomputes to the expected result hash.
    for target in targets:
        path = (server_root / str(target.get("relative_path") or "")).resolve()
        try:
            path.relative_to(server_root)
        except ValueError as exc:
            raise ControllerInventoryError("INVENTORY_SCOPE_PATH_ESCAPES_SERVER_ROOT") from exc
        if not path.is_file():
            raise FileNotFoundError(f"STORE_FILE_NOT_FOUND:{path}")
        if sha256_file(path) != target.get("source_sha256"):
            raise ControllerInventoryError(f"INVENTORY_SCOPE_SOURCE_DRIFTED:{target.get('relative_path')}")
        result, record_count, nonempty = _clear_inventory_raw(path.read_bytes(), store=kind)
        if hashlib.sha256(result).hexdigest() != target.get("result_sha256"):
            raise ControllerInventoryError(f"INVENTORY_SCOPE_RESULT_MISMATCH:{target.get('relative_path')}")
        if int(record_count) != int(target.get("record_count") or -1) or int(nonempty) != int(target.get("nonempty_count") or -1):
            raise ControllerInventoryError(f"INVENTORY_SCOPE_LAYOUT_DRIFTED:{target.get('relative_path')}")

    backup_base = Path(backup_root) / "inventory_scope_clear" / kind
    backups: dict[str, Path] = {}
    for target in targets:
        rel = Path(str(target["relative_path"]))
        src = server_root / rel
        dst = backup_base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha256_file(dst) != target.get("source_sha256"):
            raise ControllerInventoryError(f"INVENTORY_SCOPE_BACKUP_HASH_MISMATCH:{rel.as_posix()}")
        backups[rel.as_posix()] = dst

    written: list[Path] = []
    try:
        for target in targets:
            rel = Path(str(target["relative_path"]))
            path = server_root / rel
            result, _, _ = _clear_inventory_raw(path.read_bytes(), store=kind)
            atomic_write_bytes(path, result)
            # From this point onward the target has been mutated and therefore
            # must participate in rollback even if post-write verification fails.
            written.append(path)
            if sha256_file(path) != target.get("result_sha256"):
                raise ControllerInventoryError(f"INVENTORY_SCOPE_POST_WRITE_HASH_MISMATCH:{rel.as_posix()}")
    except Exception:
        for path in reversed(written):
            rel = path.relative_to(server_root).as_posix()
            backup = backups.get(rel)
            if backup and backup.is_file():
                atomic_write_bytes(path, backup.read_bytes())
        raise

    return {
        "format": FORMAT, "status": "PASS", "operation": "INVENTORY_SCOPE_CLEAR",
        "store": kind, "target_count": len(targets),
        "deleted_item_count": sum(int(x.get("nonempty_count") or 0) for x in targets),
        "backup_root": str(backup_base),
        "confirmation": required,
    }

def apply_item_batch_delete(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != BATCH_DELETE_CONFIRM:
        raise ControllerInventoryError(f"CONFIRMATION_REQUIRED:{BATCH_DELETE_CONFIRM}")
    if str(plan.get("status") or "") != "READY" or plan.get("operation") != "INVENTORY_ITEM_BATCH_DELETE":
        raise ControllerInventoryError("INVENTORY_BATCH_DELETE_PLAN_NOT_READY")
    path=Path(str(plan.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"STORE_FILE_NOT_FOUND:{path}")
    if sha256_file(path) != plan.get("source_sha256"):
        raise ControllerInventoryError("INVENTORY_SOURCE_DRIFTED")

    state=inspect_fixed_inventory(path, store=str(plan.get("store") or ""))
    rows={int(r["index"]): r for r in state["records"]}
    for guard in plan.get("guards") or []:
        idx=int(guard.get("index"))
        row=rows.get(idx)
        if row is None or row["empty"]:
            raise ControllerInventoryError(f"INVENTORY_RECORD_GUARD_MISMATCH:{idx}")
        if row["code"] != guard.get("code") or row["head"] != guard.get("head") or row["checksum"] != guard.get("checksum") or row["sha256"] != guard.get("record_sha256"):
            raise ControllerInventoryError(f"INVENTORY_RECORD_GUARD_MISMATCH:{idx}")

    backup=backup_file(path, Path(backup_root), label="inventory_item_batch_delete")
    new_raw=bytes(plan["new_bytes"])
    atomic_write_bytes(path, new_raw)
    actual=sha256_file(path)
    if actual != plan.get("result_sha256"):
        raise ControllerInventoryError("INVENTORY_POST_WRITE_HASH_MISMATCH")
    return {
        "format": FORMAT, "status": "PASS", "operation": "INVENTORY_ITEM_BATCH_DELETE",
        "path": str(path), "store": plan.get("store"), "record_indices": list(plan.get("record_indices") or []),
        "deleted_count": len(plan.get("record_indices") or []), "backup": str(backup) if backup else None,
        "sha256": actual, "deleted": True,
    }

def apply_item_delete(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != DELETE_CONFIRM:
        raise ControllerInventoryError(f"CONFIRMATION_REQUIRED:{DELETE_CONFIRM}")
    if str(plan.get("status") or "") != "READY" or plan.get("operation") != "INVENTORY_ITEM_DELETE":
        raise ControllerInventoryError("INVENTORY_DELETE_PLAN_NOT_READY")
    path = Path(str(plan.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"STORE_FILE_NOT_FOUND:{path}")
    if sha256_file(path) != plan.get("source_sha256"):
        raise ControllerInventoryError("INVENTORY_SOURCE_DRIFTED")

    # Re-inspect the selected fixed record as a second guard.  This mirrors the
    # native delete's Head/CheckSum validation and additionally pins the whole
    # record hash so a stale UI selection cannot delete a different item.
    state = inspect_fixed_inventory(path, store=str(plan.get("store") or ""))
    idx = int(plan.get("record_index"))
    row = state["records"][idx]
    guard = plan.get("guard") or {}
    if row["code"] != guard.get("code") or row["head"] != guard.get("head") or row["checksum"] != guard.get("checksum") or row["sha256"] != guard.get("record_sha256"):
        raise ControllerInventoryError("INVENTORY_RECORD_GUARD_MISMATCH")

    backup = backup_file(path, Path(backup_root), label="inventory_item_delete")
    new_raw = bytes(plan["new_bytes"])
    atomic_write_bytes(path, new_raw)
    actual = sha256_file(path)
    if actual != plan.get("result_sha256"):
        raise ControllerInventoryError("INVENTORY_POST_WRITE_HASH_MISMATCH")
    return {
        "format": FORMAT,
        "status": "PASS",
        "operation": "INVENTORY_ITEM_DELETE",
        "path": str(path),
        "store": plan.get("store"),
        "record_index": idx,
        "backup": str(backup) if backup else None,
        "sha256": actual,
        "deleted": True,
    }
