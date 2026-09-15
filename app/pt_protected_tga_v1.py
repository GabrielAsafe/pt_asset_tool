#!/usr/bin/env python3
"""Summit/Priston protected TGA header adapter V2.

The protected family keeps TGA payload/container bytes intact and transforms
only its 18-byte header by byte-wise addition modulo 256.

Physically proven protected containers:
  * TGA 2.0 footer-backed type 2 and type 10 images;
  * TGA 2.0 type 2 with a 495-byte Extension Area;
  * old/TGA1-style type 2 with no TRUEVISION-XFILE footer, but only when the
    uncompressed payload size closes exactly.

Protected RLE (type 10) without a footer is accepted only when the packet
stream itself proves exact image closure: every packet is structurally complete,
the decoded pixel count equals width*height, and no trailing bytes remain.
This module never modifies an input file; build preserves the proprietary header
and every non-pixel suffix byte-for-byte.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, struct
from pathlib import Path

TOOL = "PT_PROTECTED_TGA_V2"
KEY = bytes.fromhex("47380409101924314051647990a9c4e10021")
FOOTER_SIG = b"TRUEVISION-XFILE.\x00"
FOOTER_SIZE = 26
EXTENSION_AREA_SIZE = 495


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def header_fields(h: bytes):
    if len(h) != 18:
        raise ValueError("TGA header must be 18 bytes")
    return {
        "id_length": h[0],
        "color_map_type": h[1],
        "image_type": h[2],
        "color_map_first": struct.unpack_from("<H", h, 3)[0],
        "color_map_length": struct.unpack_from("<H", h, 5)[0],
        "color_map_depth": h[7],
        "x_origin": struct.unpack_from("<H", h, 8)[0],
        "y_origin": struct.unpack_from("<H", h, 10)[0],
        "width": struct.unpack_from("<H", h, 12)[0],
        "height": struct.unpack_from("<H", h, 14)[0],
        "pixel_depth": h[16],
        "descriptor": h[17],
    }


def plausible(fields: dict) -> bool:
    return (
        fields["id_length"] <= 255
        and fields["color_map_type"] == 0
        and fields["image_type"] in (2, 10)
        and 0 < fields["width"] <= 8192
        and 0 < fields["height"] <= 8192
        and fields["pixel_depth"] in (24, 32)
    )


def has_footer(data: bytes) -> bool:
    return len(data) >= FOOTER_SIZE and data[-18:] == FOOTER_SIG


def _footer_layout(data: bytes) -> dict:
    out = {
        "footer_tga20": has_footer(data),
        "footer_offset": None,
        "extension_offset": 0,
        "developer_offset": 0,
        "extension_size": None,
    }
    if not out["footer_tga20"]:
        return out
    footer = len(data) - FOOTER_SIZE
    out["footer_offset"] = footer
    out["extension_offset"] = struct.unpack_from("<I", data, footer)[0]
    out["developer_offset"] = struct.unpack_from("<I", data, footer + 4)[0]
    ext = int(out["extension_offset"] or 0)
    if ext and 0 <= ext <= footer - 2:
        declared = struct.unpack_from("<H", data, ext)[0]
        out["extension_size"] = declared
    return out


def _payload_layout(data: bytes, fields: dict) -> dict:
    payload_start = 18 + int(fields["id_length"])
    if payload_start > len(data):
        raise ValueError("TGA id/payload start outside file")
    layout = _footer_layout(data)
    if layout["footer_tga20"]:
        footer = int(layout["footer_offset"])
        boundaries = [footer]
        for key in ("extension_offset", "developer_offset"):
            off = int(layout[key] or 0)
            if payload_start <= off < footer:
                boundaries.append(off)
        payload_end = min(boundaries)
    else:
        payload_end = len(data)
    if payload_end < payload_start:
        raise ValueError("TGA payload boundary precedes payload start")
    return {
        **layout,
        "payload_start": payload_start,
        "payload_end": payload_end,
        "payload_bytes": payload_end - payload_start,
        "suffix_bytes": len(data) - payload_end,
    }


def decode_candidate(raw: bytes, mode: str) -> bytes:
    if len(raw) != 18:
        raise ValueError("raw header must be 18 bytes")
    out = bytearray(18)
    if mode == "FULL18":
        for i in range(18):
            out[i] = (raw[i] - KEY[i]) & 0xFF
    elif mode == "KEEP_00_16":
        out[0:2] = raw[0:2]
        for i in range(2, 18):
            out[i] = (raw[i] - KEY[i]) & 0xFF
    else:
        raise ValueError(mode)
    return bytes(out)


def protect_header(std: bytes, mode: str) -> bytes:
    if len(std) != 18:
        raise ValueError("standard header must be 18 bytes")
    out = bytearray(18)
    if mode == "FULL18":
        for i in range(18):
            out[i] = (std[i] + KEY[i]) & 0xFF
    elif mode == "KEEP_00_16":
        out[0:2] = std[0:2]
        for i in range(2, 18):
            out[i] = (std[i] + KEY[i]) & 0xFF
    else:
        raise ValueError(mode)
    return bytes(out)


def _validate_rle_payload(data: bytes, fields: dict, payload_start: int, payload_end: int) -> dict:
    """Validate TGA RLE packet closure without decoding the image.

    Every packet contributes exactly (header & 0x7f)+1 pixels.  Run packets
    carry one pixel; raw packets carry N pixels.  The validator is deliberately
    strict: it rejects truncation, pixel overrun/underrun and trailing bytes.
    """
    pixel_bytes = int(fields["pixel_depth"]) // 8
    if pixel_bytes <= 0:
        raise ValueError("invalid TGA RLE pixel depth")
    expected_pixels = int(fields["width"]) * int(fields["height"])
    pos = int(payload_start)
    pixels = 0
    packets = 0
    first_pixel_offset = None
    while pos < int(payload_end):
        header = data[pos]
        pos += 1
        count = (header & 0x7F) + 1
        if pixels + count > expected_pixels:
            raise ValueError(
                f"TGA RLE pixel overrun: decoded={pixels + count} expected={expected_pixels}"
            )
        body = pixel_bytes if (header & 0x80) else count * pixel_bytes
        if pos + body > int(payload_end):
            raise ValueError("TGA RLE packet truncated")
        if first_pixel_offset is None:
            first_pixel_offset = pos
        pos += body
        pixels += count
        packets += 1
    if pos != int(payload_end):
        raise ValueError("TGA RLE payload has trailing bytes")
    if pixels != expected_pixels:
        raise ValueError(f"TGA RLE pixel count mismatch: decoded={pixels} expected={expected_pixels}")
    if first_pixel_offset is None:
        raise ValueError("empty TGA RLE payload")
    return {
        "rle_valid": True,
        "rle_packet_count": packets,
        "rle_decoded_pixel_count": pixels,
        "rle_first_pixel_offset": first_pixel_offset,
    }


def editable_payload_witness_offset(data: bytes, info: dict) -> int:
    """Return a byte that can be mutated without changing container structure."""
    fields = info.get("fields") or {}
    if int(fields.get("image_type") or 0) == 10:
        off = info.get("rle_first_pixel_offset")
        if off is None:
            layout = _payload_layout(data, fields)
            off = _validate_rle_payload(
                data, fields, int(layout["payload_start"]), int(layout["payload_end"])
            )["rle_first_pixel_offset"]
        return int(off)
    return int(info.get("payload_start") or (18 + int(fields.get("id_length") or 0)))


def _validate_container(data: bytes, fields: dict, *, protected: bool) -> dict:
    layout = _payload_layout(data, fields)
    expected = None
    if fields["image_type"] == 2:
        expected = fields["width"] * fields["height"] * (fields["pixel_depth"] // 8)
        if layout["payload_bytes"] != expected:
            raise ValueError(
                f"uncompressed payload size mismatch: actual={layout['payload_bytes']} expected={expected}"
            )
    elif fields["image_type"] == 10:
        # PT_RC6_12_TGA1_RLE_EXACT_CLOSURE: legacy protected TGA1 containers
        # need no footer when the packet stream itself proves an exact image
        # boundary.  This is a structural proof, not a heuristic decoder.
        rle = _validate_rle_payload(
            data, fields, int(layout["payload_start"]), int(layout["payload_end"])
        )
        layout.update(rle)

    container_variant = "TGA1_STYLE_NO_FOOTER_EXACT_PAYLOAD" if not layout["footer_tga20"] else "TGA20_FOOTER"
    if fields["image_type"] == 10 and not layout["footer_tga20"]:
        container_variant = "TGA1_RLE_NO_FOOTER_EXACT_CLOSURE"
    ext = int(layout["extension_offset"] or 0)
    dev = int(layout["developer_offset"] or 0)
    footer = int(layout["footer_offset"] or 0)
    if layout["footer_tga20"] and ext:
        declared_ext = int(layout["extension_size"] or 0)
        # RC6.13 physical proof: one protected type-10 asset carries the exact
        # standard 495-byte TGA2 Extension Area, but its 16-bit size field is
        # off by one (494).  This is accepted only when the physical boundary
        # itself proves the full 495-byte area: no developer section and the
        # TRUEVISION footer begins exactly at ext+495.  Any other 494 remains
        # rejected.  RLE closure was already proven above before this branch.
        ext494_physical495 = (
            declared_ext == 494
            and fields["image_type"] == 10
            and dev == 0
            and footer - ext == EXTENSION_AREA_SIZE
        )
        if declared_ext != EXTENSION_AREA_SIZE and not ext494_physical495:
            raise ValueError(f"unsupported TGA2 extension area size: {layout['extension_size']}")
        if fields["image_type"] == 2 and ext != layout["payload_start"] + int(expected or 0):
            raise ValueError("TGA2 extension area does not follow exact type-2 pixel payload")
        ext_end = ext + EXTENSION_AREA_SIZE
        if ext_end > footer:
            raise ValueError("TGA2 extension area overlaps footer")
        if dev:
            if not (ext_end <= dev <= footer):
                raise ValueError("TGA2 developer area offset is inconsistent")
        elif ext_end != footer:
            raise ValueError("unexpected bytes between TGA2 extension area and footer")
        container_variant = (
            "TGA20_EXTENSION_AREA_495_DECLARED_494_OFF_BY_ONE"
            if ext494_physical495 else "TGA20_EXTENSION_AREA_495"
        )
        layout["extension_size_effective"] = EXTENSION_AREA_SIZE
        layout["extension_size_policy"] = (
            "DECLARED_494_PHYSICAL_495_EXACT_BOUNDARY"
            if ext494_physical495 else "DECLARED_495_STANDARD"
        )
    elif layout["footer_tga20"] and dev and not ext:
        if dev != layout["payload_end"]:
            raise ValueError("TGA2 developer area offset is inconsistent")
        container_variant = "TGA20_DEVELOPER_AREA"

    return {
        **layout,
        "expected_uncompressed_payload": expected,
        "container_variant": container_variant,
        "footer_size": FOOTER_SIZE if layout["footer_tga20"] else 0,
    }


def inspect_bytes(data: bytes):
    if len(data) < 18:
        raise ValueError("TGA too small")
    raw = data[:18]
    direct = header_fields(raw)
    if plausible(direct):
        layout = _validate_container(data, direct, protected=False)
        return {
            "format": "TGA_STANDARD",
            "protected": False,
            "protection_mode": None,
            "decoded_header": raw,
            "fields": direct,
            "footer_tga20": layout["footer_tga20"],
            **layout,
        }

    candidates = []
    for mode in ("FULL18", "KEEP_00_16"):
        dec = decode_candidate(raw, mode)
        f = header_fields(dec)
        if plausible(f):
            try:
                layout = _validate_container(data, f, protected=True)
            except ValueError:
                continue
            candidates.append((mode, dec, f, layout))
    if len(candidates) != 1:
        raise ValueError(
            f"protected TGA header/container unresolved/ambiguous: candidates={[x[0] for x in candidates]} raw={raw.hex()}"
        )
    mode, dec, fields, layout = candidates[0]
    return {
        "format": f"TGA_PRISTON_HEADER18_{mode}",
        "protected": True,
        "protection_mode": mode,
        "decoded_header": dec,
        "fields": fields,
        "protected_header_hex": raw.hex(),
        "decoded_header_hex": dec.hex(),
        **layout,
    }


def decode_bytes(data: bytes):
    info = inspect_bytes(data)
    if not info["protected"]:
        return data, info
    out = info["decoded_header"] + data[18:]
    check = inspect_bytes(out)
    if check["protected"]:
        raise RuntimeError("decoded output still detected as protected")
    return out, info


def build_bytes(baseline: bytes, edited_standard: bytes):
    binfo = inspect_bytes(baseline)
    if not binfo["protected"]:
        raise ValueError("baseline must be protected TGA")
    einfo = inspect_bytes(edited_standard)
    if einfo["protected"]:
        raise ValueError("edited file must be standard TGA")

    keys = ("id_length", "color_map_type", "image_type", "width", "height", "pixel_depth", "descriptor")
    diffs = {k: (binfo["fields"][k], einfo["fields"][k]) for k in keys if binfo["fields"][k] != einfo["fields"][k]}
    if diffs:
        raise ValueError(f"edited TGA structure differs from baseline: {diffs}")
    if len(edited_standard) != len(baseline):
        raise ValueError(f"edited TGA size differs from baseline: {len(edited_standard)} != {len(baseline)}")
    for key in ("payload_start", "payload_end", "container_variant", "footer_tga20"):
        if binfo.get(key) != einfo.get(key):
            raise ValueError(f"edited TGA container differs from baseline at {key}: {binfo.get(key)} != {einfo.get(key)}")

    p0 = int(binfo["payload_start"])
    p1 = int(binfo["payload_end"])
    # Preserve proprietary header, ID bytes and every suffix byte (extension,
    # developer area, footer) exactly.  Only the physically delimited pixel/RLE
    # payload may differ.
    out = baseline[:18] + edited_standard[18:p1] + baseline[p1:]
    if len(out) != len(baseline):
        raise RuntimeError("TGA rebuild size drift")
    if out[:18] != baseline[:18] or out[p1:] != baseline[p1:]:
        raise RuntimeError("non-payload TGA bytes changed unexpectedly")
    if out[18:p0] != baseline[18:p0]:
        raise RuntimeError("TGA ID bytes changed unexpectedly")
    return out, binfo, einfo


def cmd_inspect(a):
    p = Path(a.input).expanduser().resolve()
    data = p.read_bytes(); info = inspect_bytes(data)
    f = info["fields"]
    print(TOOL); print("action=inspect")
    print(f"input={p}"); print(f"sha256={sha(data)}")
    print(f"format={info['format']}")
    print(f"dimensions={f['width']}x{f['height']}")
    print(f"image_type={f['image_type']}"); print(f"pixel_depth={f['pixel_depth']}")
    print(f"descriptor={f['descriptor']}"); print(f"footer_tga20={info['footer_tga20']}")
    print(f"container_variant={info.get('container_variant')}")
    if info.get("protected_header_hex"): print(f"protected_header_hex={info['protected_header_hex']}")
    print("client_modified=False"); print("tga_inspect_check=PASS")


def cmd_decode(a):
    p = Path(a.input).expanduser().resolve(); outp = Path(a.out).expanduser().resolve()
    data = p.read_bytes(); out, info = decode_bytes(data)
    outp.parent.mkdir(parents=True, exist_ok=True); outp.write_bytes(out)
    print(TOOL); print("action=decode")
    print(f"input_sha256={sha(data)}"); print(f"output_sha256={sha(out)}")
    print(f"output={outp}"); print(f"format={info['format']}")
    print("client_modified=False"); print("tga_decode_check=PASS")


def cmd_build(a):
    bp=Path(a.baseline).expanduser().resolve(); ep=Path(a.edited).expanduser().resolve(); op=Path(a.out).expanduser().resolve()
    base=bp.read_bytes(); edited=ep.read_bytes(); out,bi,ei=build_bytes(base,edited)
    op.parent.mkdir(parents=True, exist_ok=True); op.write_bytes(out)
    print(TOOL); print("action=build")
    print(f"baseline_sha256={sha(base)}"); print(f"edited_sha256={sha(edited)}"); print(f"output_sha256={sha(out)}")
    print(f"byte_identical_to_baseline={out == base}"); print(f"output={op}")
    print("client_modified=False"); print("tga_build_check=PASS")


def cmd_audit_csv(a):
    p=Path(a.csv).expanduser().resolve(); total=good=bad=0; modes={}; types={}; dims={}; bad_rows=[]
    with p.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            count=int(row["file_count"]); total+=count
            h16=bytes.fromhex(row["head16"])
            matches=[]
            for mode in ("FULL18","KEEP_00_16"):
                dec=bytearray(16)
                if mode=="FULL18":
                    for i in range(16): dec[i]=(h16[i]-KEY[i])&0xff
                else:
                    dec[:2]=h16[:2]
                    for i in range(2,16): dec[i]=(h16[i]-KEY[i])&0xff
                image_type=dec[2]; w=int.from_bytes(dec[12:14],"little"); h=int.from_bytes(dec[14:16],"little")
                if dec[0]==0 and dec[1]==0 and image_type in (2,10) and 0<w<=8192 and 0<h<=8192:
                    matches.append((mode,image_type,w,h))
            if len(matches)==1:
                good+=count; mode,it,w,h=matches[0]; modes[mode]=modes.get(mode,0)+count; types[it]=types.get(it,0)+count; dims[f"{w}x{h}"]=dims.get(f"{w}x{h}",0)+count
            else:
                bad+=count; bad_rows.append({"count":count,"head16":row["head16"],"matches":matches})
    report={"tool":TOOL,"input":str(p),"total_files":total,"decoded_plausible":good,"unresolved":bad,"coverage_percent":round(good/total*100,6) if total else 0,"modes":modes,"image_types":types,"dimensions":dict(sorted(dims.items(), key=lambda kv:-kv[1])),"unresolved_rows":bad_rows,"client_modified":False,"tga_signature_audit_check":"PASS"}
    if a.report:
        rp=Path(a.report).expanduser().resolve(); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(TOOL); print("action=audit-signature-csv"); print(f"total_files={total}"); print(f"decoded_plausible={good}"); print(f"unresolved={bad}"); print(f"coverage_percent={report['coverage_percent']}"); print(f"modes={modes}"); print(f"image_types={types}"); print("client_modified=False"); print("tga_signature_audit_check=PASS")


def main():
    ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest="cmd",required=True)
    p=sp.add_parser("inspect"); p.add_argument("input"); p.set_defaults(fn=cmd_inspect)
    p=sp.add_parser("decode"); p.add_argument("input"); p.add_argument("--out",required=True); p.set_defaults(fn=cmd_decode)
    p=sp.add_parser("build"); p.add_argument("--baseline",required=True); p.add_argument("--edited",required=True); p.add_argument("--out",required=True); p.set_defaults(fn=cmd_build)
    p=sp.add_parser("audit-signature-csv"); p.add_argument("csv"); p.add_argument("--report"); p.set_defaults(fn=cmd_audit_csv)
    a=ap.parse_args(); a.fn(a)

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"tga_core_check=FAIL: {type(exc).__name__}: {exc}")
        raise
