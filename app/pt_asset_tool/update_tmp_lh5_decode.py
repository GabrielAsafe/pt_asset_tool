from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import mmap
import pathlib
import re
import shutil
import struct
from typing import Any

from .config import Settings
from .official_container_character_atlas import _guard_snapshot
from .official_container_entry_recovery import _verify_content_baseline
from .official_container_record_index import _lha_entries
from .update_tmp_lha_forensics import _crc16_lha, _sha_file, _snapshot_file, _inspect_payload_bytes

FORMAT = "PT_UPDATE_TMP_LH5_DECODE_V2"
RELEASE = "0.10.4"
PRIOR_FORMAT = "PT_UPDATE_TMP_LHA_FORENSICS_V1"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _strict_prior(root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rp = root / "pt_build/update_tmp_lha_forensics_v01020.json"
    bp = root / "pt_build/summit_client_content_baseline_v0960.json"
    if not rp.is_file():
        raise FileNotFoundError(f"V01020_REPORT_MISSING:{rp}")
    if not bp.is_file():
        raise FileNotFoundError(f"V0960_BASELINE_MISSING:{bp}")
    r = json.loads(rp.read_text(encoding="utf-8"))
    if r.get("format") != PRIOR_FORMAT or r.get("status") != "PASS" or r.get("release_version") != "0.10.2":
        raise RuntimeError("V01020_STRICT_REPORT_MISMATCH")
    g = r.get("guards") or {}
    if not g.get("certified_writer_hashes_valid") or g.get("writer_modules_modified") or g.get("production_policies_modified"):
        raise RuntimeError("V01020_GUARD_STATE_INVALID")
    s = r.get("summary") or {}
    methods = list(s.get("methods") or [])
    if methods != ["-lh5-"] or not str(s.get("mode") or "").startswith("UPDATE_TMP_COMPRESSED_LHA_DECODER_REQUIRED:-lh5-"):
        raise RuntimeError(f"V01020_NOT_EXACT_LH5_DECODER_CASE:{methods}:{s.get('mode')}")
    if int(s.get("lha_entry_count") or 0) != 1 or int(s.get("strict_level0_record_count") or 0) != 1:
        raise RuntimeError("V01020_EXPECTED_ONE_STRICT_LEVEL0_RECORD")
    b = json.loads(bp.read_text(encoding="utf-8"))
    if b.get("format") != "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1" or b.get("status") != "PASS_READ_ONLY_WINDOW":
        raise RuntimeError("V0960_CONTENT_BASELINE_INVALID")
    return r, b


def _load_libarchive() -> tuple[Any, str]:
    names = []
    found = ctypes.util.find_library("archive")
    if found:
        names.append(found)
    names += ["libarchive.so.13", "libarchive.so", "/usr/lib64/libarchive.so.13", "/usr/lib64/libarchive.so"]
    last: Exception | None = None
    lib = None
    chosen = ""
    for name in names:
        try:
            lib = ctypes.CDLL(name)
            chosen = name
            break
        except Exception as exc:  # pragma: no cover - host dependent
            last = exc
    if lib is None:
        raise RuntimeError(f"LIBARCHIVE_NOT_AVAILABLE:{last}")

    lib.archive_read_new.restype = ctypes.c_void_p
    lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
    lib.archive_read_support_filter_all.restype = ctypes.c_int
    # Prefer the narrow LHA support function when available.
    if hasattr(lib, "archive_read_support_format_lha"):
        lib.archive_read_support_format_lha.argtypes = [ctypes.c_void_p]
        lib.archive_read_support_format_lha.restype = ctypes.c_int
    lib.archive_read_support_format_all.argtypes = [ctypes.c_void_p]
    lib.archive_read_support_format_all.restype = ctypes.c_int
    lib.archive_read_open_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.archive_read_open_memory.restype = ctypes.c_int
    lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    lib.archive_read_next_header.restype = ctypes.c_int
    lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
    lib.archive_entry_pathname.restype = ctypes.c_char_p
    lib.archive_entry_size.argtypes = [ctypes.c_void_p]
    lib.archive_entry_size.restype = ctypes.c_longlong
    lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.archive_read_data.restype = ctypes.c_ssize_t
    lib.archive_read_free.argtypes = [ctypes.c_void_p]
    lib.archive_read_free.restype = ctypes.c_int
    lib.archive_error_string.argtypes = [ctypes.c_void_p]
    lib.archive_error_string.restype = ctypes.c_char_p
    if hasattr(lib, "archive_version_string"):
        lib.archive_version_string.restype = ctypes.c_char_p
    return lib, chosen


def _err(lib: Any, archive: int) -> str:
    try:
        p = lib.archive_error_string(archive)
        return p.decode("utf-8", errors="replace") if p else ""
    except Exception:
        return ""


def _decode_lha_archive_bytes(raw: bytes, expected_entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lib, lib_name = _load_libarchive()
    archive = lib.archive_read_new()
    if not archive:
        raise RuntimeError("LIBARCHIVE_READ_NEW_FAILED")
    buf = ctypes.create_string_buffer(raw)
    decoded: list[dict[str, Any]] = []
    try:
        if lib.archive_read_support_filter_all(archive) < 0:
            raise RuntimeError(f"LIBARCHIVE_FILTER_SUPPORT_FAILED:{_err(lib, archive)}")
        if hasattr(lib, "archive_read_support_format_lha"):
            if lib.archive_read_support_format_lha(archive) < 0:
                raise RuntimeError(f"LIBARCHIVE_LHA_SUPPORT_FAILED:{_err(lib, archive)}")
        else:
            if lib.archive_read_support_format_all(archive) < 0:
                raise RuntimeError(f"LIBARCHIVE_FORMAT_SUPPORT_FAILED:{_err(lib, archive)}")
        rc = lib.archive_read_open_memory(archive, buf, len(raw))
        if rc < 0:
            raise RuntimeError(f"LIBARCHIVE_OPEN_MEMORY_FAILED:{rc}:{_err(lib, archive)}")
        while True:
            ent = ctypes.c_void_p()
            rc = lib.archive_read_next_header(archive, ctypes.byref(ent))
            if rc == 1:  # ARCHIVE_EOF
                break
            if rc < 0:
                raise RuntimeError(f"LIBARCHIVE_NEXT_HEADER_FAILED:{rc}:{_err(lib, archive)}")
            name_b = lib.archive_entry_pathname(ent)
            name = name_b.decode("utf-8", errors="replace") if name_b else ""
            declared = int(lib.archive_entry_size(ent))
            if declared < 0 or declared > 512 * 1024 * 1024:
                raise RuntimeError(f"LIBARCHIVE_ENTRY_SIZE_UNSAFE:{name}:{declared}")
            chunks: list[bytes] = []
            got = 0
            block_size = 1024 * 1024
            while got < declared:
                want = min(block_size, declared - got)
                out = ctypes.create_string_buffer(max(1, want))
                n = int(lib.archive_read_data(archive, out, want))
                if n < 0:
                    raise RuntimeError(f"LIBARCHIVE_READ_DATA_FAILED:{name}:{n}:{_err(lib, archive)}")
                if n == 0:
                    break
                chunks.append(out.raw[:n])
                got += n
            data = b"".join(chunks)
            decoded.append({"filename": name, "declared_size": declared, "decoded_size": len(data), "data": data})
    finally:
        lib.archive_read_free(archive)

    # Strictly pair by sequence + filename against our independent LHA parser.
    if len(decoded) != len(expected_entries):
        raise RuntimeError(f"LIBARCHIVE_ENTRY_COUNT_MISMATCH:{len(decoded)}:{len(expected_entries)}")
    for i, (d, e) in enumerate(zip(decoded, expected_entries)):
        expected_name = str(e.get("filename") or "").replace("\\", "/")
        got_name = str(d.get("filename") or "").replace("\\", "/")
        if got_name.lower() != expected_name.lower():
            raise RuntimeError(f"LIBARCHIVE_FILENAME_MISMATCH:{i}:{got_name}:{expected_name}")
        if int(d["declared_size"]) != int(e.get("original_size") or 0):
            raise RuntimeError(f"LIBARCHIVE_DECLARED_SIZE_MISMATCH:{i}")
        if int(d["decoded_size"]) != int(e.get("original_size") or 0):
            raise RuntimeError(f"LIBARCHIVE_DECODED_SIZE_MISMATCH:{i}:{d['decoded_size']}:{e.get('original_size')}")
    version = ""
    if hasattr(lib, "archive_version_string"):
        try:
            p = lib.archive_version_string()
            version = p.decode("utf-8", errors="replace") if p else ""
        except Exception:
            pass
    return decoded, {"library": lib_name, "version": version, "decoder_role": "decompression_only; LHA header/bounds/size/CRC are independently revalidated"}


def _strict_lh5_level0_entry(e: dict[str, Any]) -> bool:
    """Accept a genuine level-0 LH5 entry without treating numeric zero as missing."""
    level = e.get("level")
    level_i = int(level) if level is not None else -1
    return (
        e.get("method") == "-lh5-"
        and level_i == 0
        and bool(e.get("checksum_ok"))
        and bool(e.get("payload_bounds_ok_level0"))
    )


def _png_info(data: bytes) -> dict[str, Any]:
    row = {"png_magic_ok": data.startswith(PNG_MAGIC), "ihdr_ok": False, "width": None, "height": None}
    if len(data) >= 24 and data.startswith(PNG_MAGIC) and data[12:16] == b"IHDR":
        row["ihdr_ok"] = True
        row["width"] = struct.unpack_from(">I", data, 16)[0]
        row["height"] = struct.unpack_from(">I", data, 20)[0]
    return row


def run(root: pathlib.Path, output: pathlib.Path, candidate: pathlib.Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    settings = Settings.discover(root)
    prior, baseline_doc = _strict_prior(root)
    guards_before = _guard_snapshot(root)
    if not all(v["pass"] for v in guards_before["writers"].values()):
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    baseline = {"files": baseline_doc.get("files") or {}}
    cb = _verify_content_baseline(settings.client_root, baseline)
    if not cb["pass"]:
        raise RuntimeError("SUMMIT_CORPUS_NO_LONGER_MATCHES_V0960_BASELINE")

    prior_candidate = prior.get("candidate") or {}
    path = (candidate.expanduser().resolve() if candidate else pathlib.Path(str(prior_candidate.get("path") or settings.client_root / "update.tmp")).resolve())
    if not path.is_file():
        raise FileNotFoundError(f"UPDATE_TMP_MISSING:{path}")
    try:
        path.relative_to(settings.client_root.resolve())
    except Exception:
        raise RuntimeError(f"CANDIDATE_NOT_INSIDE_SUMMIT_CLIENT:{path}")
    before = _snapshot_file(path)
    if str(prior_candidate.get("sha256") or "") and before[2] != str(prior_candidate.get("sha256")):
        raise RuntimeError("UPDATE_TMP_HASH_NO_LONGER_MATCHES_V01020")

    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            entries = _lha_entries(mm)
            raw = bytes(mm[:])
        finally:
            mm.close()
    if len(entries) != 1:
        raise RuntimeError(f"EXPECTED_ONE_LHA_ENTRY:{len(entries)}")
    e = entries[0]
    if not _strict_lh5_level0_entry(e):
        raise RuntimeError(f"STRICT_LH5_LEVEL0_RECORD_INVALID:{e.get('method')}:{e.get('level')}:{e.get('checksum_ok')}:{e.get('payload_bounds_ok_level0')}")

    decoded, decoder = _decode_lha_archive_bytes(raw, entries)
    staging = root / "pt_build/update_tmp_lh5_decode_v01040"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for i, (d, entry) in enumerate(zip(decoded, entries)):
        data = d.pop("data")
        # Locate independent file CRC16 from the level-0 header.
        name_end = int(entry.get("filename_end") or 0)
        base_end = int(entry.get("base_header_end") or 0)
        header_crc16 = struct.unpack_from("<H", raw, name_end)[0] if name_end > 0 and name_end + 2 <= base_end else None
        computed_crc16 = _crc16_lha(data)
        crc_ok = header_crc16 is not None and header_crc16 == computed_crc16
        if not crc_ok:
            raise RuntimeError(f"LH5_DECODED_CRC16_MISMATCH:{i}:{header_crc16}:{computed_crc16}")
        if len(data) != int(entry.get("original_size") or 0):
            raise RuntimeError(f"LH5_ORIGINAL_SIZE_MISMATCH:{i}")
        name = pathlib.PurePosixPath(str(entry.get("filename") or f"member_{i}").replace("\\", "/")).name
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name) or f"member_{i}.bin"
        dest = staging / f"decoded_{i:02d}_{safe}"
        dest.write_bytes(data)
        inspect = _inspect_payload_bytes(data, staging, f"inspect_{i}")
        row = {
            **d,
            "method": entry.get("method"),
            "level": entry.get("level"),
            "header_checksum_ok": bool(entry.get("checksum_ok")),
            "payload_bounds_ok_level0": bool(entry.get("payload_bounds_ok_level0")),
            "compressed_size": int(entry.get("compressed_size") or 0),
            "original_size": int(entry.get("original_size") or 0),
            "header_crc16": header_crc16,
            "computed_crc16": computed_crc16,
            "crc16_ok": crc_ok,
            "decoded_sha256": hashlib.sha256(data).hexdigest(),
            "decoded_staging_path": str(dest),
            "png": _png_info(data),
            "payload_evidence": inspect,
        }
        rows.append(row)

    tff_hits = sum(len((r.get("payload_evidence") or {}).get("target_name_hits") or []) for r in rows)
    model_hits = sum(int((r.get("payload_evidence") or {}).get("model062_magic_count") or 0) for r in rows)
    all_png = bool(rows) and all((r.get("png") or {}).get("png_magic_ok") and (r.get("png") or {}).get("ihdr_ok") for r in rows)
    unrelated_warning = bool(rows) and all("warning/lowhpwarning.png" in str(r.get("filename") or "").replace("\\", "/").lower() for r in rows)
    if tff_hits or model_hits:
        mode = "UPDATE_TMP_LH5_DECODED_RELEVANT_EVIDENCE_FOUND"
    elif all_png and unrelated_warning:
        mode = "UPDATE_TMP_CONFIRMED_UNRELATED_UI_PATCH"
    else:
        mode = "UPDATE_TMP_LH5_DECODED_NO_TFF_EVIDENCE"

    after = _snapshot_file(path)
    guards_after = _guard_snapshot(root)
    ca = _verify_content_baseline(settings.client_root, baseline)
    if before != after:
        raise RuntimeError("UPDATE_TMP_CHANGED_DURING_LH5_DECODE")
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_V01040")
    if not ca["pass"]:
        raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_V01040")

    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "client_read_only": True,
        "prior_v0102_strict_pass": True,
        "candidate": {"path": str(path), "size": before[0], "sha256": before[2]},
        "decoder": decoder,
        "decoded_entries": rows,
        "summary": {
            "decoded_entry_count": len(rows),
            "strict_crc16_pass_count": sum(1 for r in rows if r.get("crc16_ok")),
            "png_valid_count": sum(1 for r in rows if (r.get("png") or {}).get("png_magic_ok") and (r.get("png") or {}).get("ihdr_ok")),
            "tff_target_hit_count": tff_hits,
            "model062_magic_count": model_hits,
            "mode": mode,
        },
        "decision": {
            "transplant_write_authorized": False,
            "new_class_claimed": False,
            "runtime_renderer_claimed": False,
            "decoded_files_are_forensic_staging_only": True,
            "update_tmp_relevant_to_tff": bool(tff_hits or model_hits),
            "next_on_pass": (
                "follow decoded TfF/Model0.62 evidence" if tff_hits or model_hits else
                "close update.tmp as unrelated UI patch; retain LH5 decoder for future official patch/archive payloads and require an external authoritative TfF source"
            ),
        },
        "guards": {
            "certified_writer_hashes_valid": True,
            "writer_modules_modified": False,
            "production_policies_modified": False,
            "policy_sha256": guards_after["policies"],
            "summit_matches_v0960_baseline_before": cb["pass"],
            "summit_matches_v0960_baseline_after": ca["pass"],
        },
        "outputs": {"json": str(output), "staging_root": str(staging)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--candidate")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.output)
    try:
        r = run(pathlib.Path(a.root), out, pathlib.Path(a.candidate) if a.candidate else None)
        s = r["summary"]
        compact = {
            "format": r["format"], "status": r["status"], "release_version": r["release_version"],
            "client_read_only": r["client_read_only"], "candidate": r["candidate"], "decoder": r["decoder"],
            "summary": s,
            "decoded_entries": [
                {k: row.get(k) for k in (
                    "filename", "method", "level", "compressed_size", "original_size", "decoded_size",
                    "header_checksum_ok", "payload_bounds_ok_level0", "header_crc16", "computed_crc16", "crc16_ok",
                    "decoded_sha256", "decoded_staging_path", "png", "payload_evidence"
                )}
                for row in r["decoded_entries"]
            ],
            "decision": r["decision"], "guards": r["guards"], "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(
            f"update_tmp_lh5_decode=PASS mode={s['mode']} entries={s['decoded_entry_count']} "
            f"crc16={s['strict_crc16_pass_count']} png={s['png_valid_count']} "
            f"tff_hits={s['tff_target_hit_count']} model062={s['model062_magic_count']} read_only=true"
        )
        return 0
    except Exception as exc:
        fail = {"format": FORMAT, "status": "FAIL", "release_version": RELEASE, "error": f"{type(exc).__name__}:{exc}", "transplant_write_authorized": False}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
