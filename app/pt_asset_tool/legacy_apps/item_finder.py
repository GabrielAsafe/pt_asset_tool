from __future__ import annotations

import base64
import dataclasses
from pathlib import Path
from typing import Any, Iterable

from .common import sha256_file

FORMAT = "PT_LEGACY_ITEM_FINDER_V1"


class ParseError(ValueError):
    pass


def _u8(data: bytes, pos: int) -> int:
    if pos < 0 or pos >= len(data):
        raise ParseError(f"OUT_OF_RANGE:{pos}")
    return data[pos]


def _u32(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(data):
        raise ParseError(f"OUT_OF_RANGE_U32:{pos}")
    return int.from_bytes(data[pos:pos + 4], "little", signed=False)


def _ascii(data: bytes) -> str:
    # Gregoo.Hexadecimal.HexToASCII stops at the first NUL byte.
    out = bytearray()
    for b in data:
        if b == 0:
            break
        out.append(b)
    return out.decode("latin-1", errors="replace")


def _excluded(name: str, exclusive: str = "") -> bool:
    # Original behavior: when no explicit exclusion string is configured it
    # excludes names containing "potion" (case-insensitive).
    if exclusive:
        return exclusive.casefold() in name.casefold()
    return "potion" in name.casefold()


def serial_key(item_name: str, serial_a: int, serial_b: int) -> str:
    raw = f"{item_name}{serial_a}{serial_b}".encode("ascii", errors="replace")
    return base64.b64encode(raw).decode("ascii")


@dataclasses.dataclass(frozen=True)
class FoundItem:
    source: str
    item_name: str
    serial_a: int
    serial_b: int

    @property
    def key(self) -> str:
        return serial_key(self.item_name, self.serial_a, self.serial_b)


def parse_inventory_bytes(source_name: str, raw: bytes, *, exclusive: str = "") -> list[FoundItem]:
    """Faithful port of Gregoo.Inventory.Parse from Procura item pelo nome.exe.

    The legacy code parses a variable-length serialization embedded in userdata.
    It reads item_count at byte 1764, payload length at 1772 and payload at 1776.
    Invalid records are skipped exactly at the record boundary instead of making
    the scanner unsafe.
    """
    if len(raw) < 1776:
        return []
    try:
        item_count = _u32(raw, 1764)
        payload_len = _u32(raw, 1772)
    except ParseError:
        return []
    if item_count <= 0:
        return []
    payload = raw[1776:1776 + payload_len]
    record_pos = 0
    out: list[FoundItem] = []
    for _ in range(item_count):
        if record_pos + 4 > len(payload):
            break
        try:
            serial_a = 0
            serial_b = 0
            name = ""
            p = record_pos
            record_len = _u32(payload, p)
            if record_len <= 0:
                break
            record_pos += record_len
            p += 4

            flag = _u8(payload, p)
            if flag == 1:
                p += 2
            else:
                flag = 0
            if _u8(payload, p) != 132 - flag:
                continue
            p += 1
            n = _u8(payload, p)
            p += n + 1

            tag = _u8(payload, p)
            if tag not in (131, 130):
                continue
            p += 1
            n = _u8(payload, p)
            p += n + 1

            optional_130 = _u8(payload, p)
            if optional_130 == 130:
                p += 1
                n = _u8(payload, p)
                p += n + 1
            else:
                optional_130 = 0

            kind = _u8(payload, p)
            if optional_130 == 130:
                if kind != 135:
                    continue
            elif kind not in (138, 139):
                continue
            p += 1
            value_len = _u8(payload, p)
            p += 1
            serial_a = _u32(payload, p)
            p += value_len

            if kind == 138:
                if _u8(payload, p) != 131:
                    continue
                p += 1
                n = _u8(payload, p)
                p += 1
                look = p + n
                if _u8(payload, look) == 134:
                    serial_b = _u32(payload, p)
                    p += n
                else:
                    p -= 2
            elif kind == 135 and _u8(payload, p) == 132:
                p += 1
                n = _u8(payload, p)
                p += 1
                serial_b = _u32(payload, p)
                # This odd jump is what the IL does: advance by the decoded
                # 32-bit value, not by the preceding length byte.
                p += serial_b

            name_tag = _u8(payload, p)
            if name_tag == 134:
                p += 1
                n = _u8(payload, p)
                p += 1
                if n >= 3:
                    name = _ascii(payload[p + 3:p + n])
                p += n
            elif name_tag in (131, 130):
                p += 1
                n = _u8(payload, p)
                p += 1
                if name_tag == 130:
                    if n >= 3:
                        name = _ascii(payload[p + 3:p + n])
                else:
                    look = p + n
                    look_tag = _u8(payload, look)
                    if look_tag in (130, 133, 134):
                        p += 1
                        _inner_len = _u8(payload, p)
                        p += 1
                        serial_b = _u32(payload, p)
                        p = look + 1
                        n = _u8(payload, p)
                        p += 1
                        if n >= 3:
                            name = _ascii(payload[p + 3:p + n])
                    else:
                        serial_b = _u32(payload, p + 4)
                        if n >= 16:
                            name = _ascii(payload[p + 16:p + n])
                p += n
            else:
                continue

            if name and serial_a and serial_b and not _excluded(name, exclusive):
                out.append(FoundItem(source_name, name, serial_a, serial_b))
        except (ParseError, OverflowError):
            # The original parser simply abandons malformed item branches.  We
            # keep the record boundary already obtained at the top of the loop.
            continue
    return out


def _warehouse_parse_one(payload: bytes, p: int) -> tuple[int, str, int, int]:
    """Translate the successful branch of Gregoo.Warehouse.Parse.

    Returns (new_pos, item_name, serial_a, serial_b).  A ParseError signals that
    the caller must use the original sentinel-based resynchronisation logic.
    """
    serial_a = serial_b = 0

    n = _u8(payload, p); p += n + 1
    if _u8(payload, p) == 130:
        p += 1; n = _u8(payload, p); p += n + 1

    tag = _u8(payload, p)
    if not 142 <= tag <= 159: raise ParseError("WH_TAG_142_159")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 139: raise ParseError("WH_TAG_139")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 131: raise ParseError("WH_TAG_131_A")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 131: raise ParseError("WH_TAG_131_B")
    p += 1; n = _u8(payload, p); p += n + 1

    tag15 = _u8(payload, p)
    if not 183 <= tag15 <= 186: raise ParseError("WH_TAG_183_186")
    p += 1; n = _u8(payload, p); p += n + 1
    tag17 = _u8(payload, p)
    if tag17 not in (130, 131): raise ParseError("WH_TAG_130_131_A")
    p += 1; n = _u8(payload, p); p += n + 1

    tag19 = _u8(payload, p)
    if tag19 == 187:
        p += 1; n = _u8(payload, p); p += n + 1
    tag21 = _u8(payload, p)
    if tag21 != 191 and not (tag19 == 187 and tag21 == 131):
        raise ParseError("WH_TAG_191_OR_187_131")
    p += 1; n = _u8(payload, p); p += n + 1
    _ = _u8(payload, p)
    if tag19 == 187:
        p += 1; n = _u8(payload, p); p += n + 1

    tag24 = _u8(payload, p)
    if tag24 != 135 and not (tag19 == 187 and tag24 == 131):
        raise ParseError("WH_TAG_135")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 131: raise ParseError("WH_TAG_131_C")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 131: raise ParseError("WH_TAG_131_D")
    p += 1; n = _u8(payload, p); p += n + 1

    tag30 = _u8(payload, p)
    if tag30 not in (130, 131): raise ParseError("WH_TAG_130_131_B")
    p += 1; n = _u8(payload, p); p += n + 1
    if _u8(payload, p) != 131: raise ParseError("WH_TAG_131_E")
    p += 1; n = _u8(payload, p); p += n + 1
    tag34 = _u8(payload, p)
    if not 130 <= tag34 <= 144: raise ParseError("WH_TAG_130_144")
    p += 1; n = _u8(payload, p); p += n + 1

    tag36 = _u8(payload, p)
    if tag36 in (144, 140):
        p += 1; n = _u8(payload, p); p += n + 1
        _ = _u8(payload, p)
        p += 1; n = _u8(payload, p); p += n + 1

    tag39 = _u8(payload, p)
    if tag39 in (160, 138):
        p += 1
        value_len = _u8(payload, p); p += 1
        serial_a = _u32(payload, p)
        p += value_len
    else:
        p += 1
        n = _u8(payload, p); p += n + 1
        _tag39b = _u8(payload, p); p += 1
        value_len = _u8(payload, p); p += 1
        serial_a = _u32(payload, p)
        p += value_len

    tag42 = _u8(payload, p)
    if tag42 not in (131, 132): raise ParseError("WH_TAG_131_132")
    p += 1
    n = _u8(payload, p); p += 1
    # Original: HexSubstring(p + 4, 3) + "00", then little-endian decode.
    if p + 7 > len(payload): raise ParseError("WH_SERIAL_B_RANGE")
    serial_b = int.from_bytes(payload[p + 4:p + 7] + b"\0", "little")
    p += n

    if _u8(payload, p) == 131:
        p += 1; n = _u8(payload, p); p += n + 1

    name_tag = _u8(payload, p)
    if name_tag not in (130, 134): raise ParseError("WH_NAME_TAG")
    p += 1
    name_len = _u8(payload, p)
    if name_len <= 3:
        p += name_len + 1
        _name_tag2 = _u8(payload, p); p += 1
        name_len = _u8(payload, p)
    p += 1
    name = _ascii(payload[p + 3:p + name_len]) if name_len >= 3 else ""
    p += name_len
    return p, name, serial_a, serial_b


def parse_warehouse_bytes(source_name: str, raw: bytes, *, exclusive: str = "") -> list[FoundItem]:
    if len(raw) < 52:
        return []
    try:
        payload_len = _u32(raw, 48)
    except ParseError:
        return []
    payload = raw[48:48 + payload_len]
    p = 4
    try:
        if _u8(raw, p) == 255:
            return []
    except ParseError:
        return []
    out: list[FoundItem] = []
    while p < len(payload):
        try:
            new_p, name, serial_a, serial_b = _warehouse_parse_one(payload, p)
            p = new_p
            if name and serial_a and serial_b and not _excluded(name, exclusive):
                out.append(FoundItem(f"(WH){source_name}", name, serial_a, serial_b))
        except ParseError:
            pass

        # Exact recovery shape from IL_0548: sentinel 0xff walks toward EOF;
        # 0xa5 (165) marks a new record; otherwise skip a length-prefixed field.
        while p < len(payload):
            try:
                marker = _u8(payload, p)
                if marker == 255:
                    p += 1
                    continue
                if marker == 165:
                    p += 1
                    break
                p += 1
                n = _u8(payload, p)
                p += n + 1
            except ParseError:
                p = len(payload)
                break
    return out


def group_items(items: Iterable[FoundItem]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not item.item_name or not item.serial_a or not item.serial_b:
            continue
        row = grouped.setdefault(item.key, {
            "key": item.key,
            "item_name": item.item_name,
            "serial_a": item.serial_a,
            "serial_b": item.serial_b,
            "sources": [],
        })
        if item.source not in row["sources"]:
            row["sources"].append(item.source)
    return grouped


def scan_dataserver(server_root: Path, *, query: str = "", exclusive: str = "", include_warehouse: bool = True) -> dict[str, Any]:
    root = Path(server_root).resolve()
    userdata = root / "DataServer" / "userdata"
    warehouse = root / "DataServer" / "warehouse"
    found: list[FoundItem] = []
    files_scanned = 0
    parse_errors: list[dict[str, str]] = []
    for bucket in range(256):
        d = userdata / str(bucket)
        if d.is_dir():
            for path in d.glob("*.dat"):
                files_scanned += 1
                try:
                    found.extend(parse_inventory_bytes(path.stem, path.read_bytes(), exclusive=exclusive))
                except Exception as exc:
                    parse_errors.append({"path": str(path), "error": f"{type(exc).__name__}:{exc}"})
        if include_warehouse:
            w = warehouse / str(bucket)
            if w.is_dir():
                for path in w.glob("*.war"):
                    files_scanned += 1
                    try:
                        found.extend(parse_warehouse_bytes(path.stem, path.read_bytes(), exclusive=exclusive))
                    except Exception as exc:
                        parse_errors.append({"path": str(path), "error": f"{type(exc).__name__}:{exc}"})
    grouped = group_items(found)
    q = query.casefold().strip()
    rows = [row for row in grouped.values() if not q or q in row["item_name"].casefold() or q in " ".join(row["sources"]).casefold()]
    rows.sort(key=lambda x: (x["item_name"].casefold(), x["serial_a"], x["serial_b"]))
    duplicates = [r for r in rows if len(r["sources"]) > 1]
    return {
        "format": FORMAT,
        "status": "PASS",
        "server_root": str(root),
        "files_scanned": files_scanned,
        "unique_items": len(grouped),
        "matched_items": len(rows),
        "duplicate_items": len(duplicates),
        "rows": rows,
        "duplicates": duplicates,
        "parse_errors": parse_errors[:100],
        "write_authorized": False,
        "provenance": "Ported from Gregoo.Inventory.Parse/Warehouse.Parse/Dico.Add IL in Procura item pelo nome.exe",
    }


def inspect_file(path: Path, *, kind: str) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_bytes()
    items = parse_inventory_bytes(p.stem, raw) if kind == "userdata" else parse_warehouse_bytes(p.stem, raw)
    return {
        "format": FORMAT,
        "status": "PASS",
        "kind": kind,
        "path": str(p),
        "sha256": sha256_file(p),
        "items": [dataclasses.asdict(x) | {"key": x.key} for x in items],
    }
