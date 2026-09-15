from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import pathlib
import re
import shutil
import struct
import tempfile
from typing import Any

from .config import Settings
from .official_container_character_atlas import _guard_snapshot
from .official_container_entry_recovery import _verify_content_baseline
from .official_container_record_index import _lha_entries
from .official_payload_provenance_extraction import _scan_raw

FORMAT = "PT_UPDATE_TMP_LHA_FORENSICS_V1"
RELEASE = "0.10.2"
PRIOR_FORMAT = "PT_OFFICIAL_PAYLOAD_PROVENANCE_EXTRACTION_V1"
MODEL062 = b"SMD Model data Ver 0.62"
TARGET_RX = re.compile(rb"(?:6[Tt][Ff][Bb][Ff]|[Cc][Tt][Ff][Bb][Ff]|[Tt][Ff][Bb][Ff]|[Tt][Ff][Hh][Ff])[A-Za-z0-9_-]{1,32}\.(?:smd|smb|inx|inf)", re.I)
URL_RX = re.compile(rb"https?://[^\x00-\x20\x7f\"'<>]{4,300}", re.I)
UPW_RX = re.compile(rb"[A-Za-z0-9_./\\-]{1,220}\.upw", re.I)


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def _crc16_lha(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if (crc & 1) else 0)
    return crc & 0xFFFF


def _snapshot_file(path: pathlib.Path) -> tuple[int, int, str]:
    st = path.stat()
    return int(st.st_size), int(st.st_mtime_ns), _sha_file(path)


def _strict_prior(root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rp = root / "pt_build/official_payload_provenance_extraction_v01010.json"
    bp = root / "pt_build/summit_client_content_baseline_v0960.json"
    if not rp.is_file():
        raise FileNotFoundError(f"V01010_REPORT_MISSING:{rp}")
    if not bp.is_file():
        raise FileNotFoundError(f"V0960_BASELINE_MISSING:{bp}")
    r = json.loads(rp.read_text(encoding="utf-8"))
    if r.get("format") != PRIOR_FORMAT or r.get("status") != "PASS" or r.get("release_version") != "0.10.1":
        raise RuntimeError("V01010_STRICT_REPORT_MISMATCH")
    g = r.get("guards") or {}
    if not g.get("certified_writer_hashes_valid") or g.get("writer_modules_modified") or g.get("production_policies_modified"):
        raise RuntimeError("V01010_GUARD_STATE_INVALID")
    s = r.get("summary") or {}
    if int(s.get("strict_recovered_count") or 0) != 0:
        raise RuntimeError("V01010_ALREADY_RECOVERED_USE_DEPENDENCY_PATH")
    positives = (r.get("v100_provenance_reassessment") or {}).get("nonworkspace_positive_samples") or []
    if not any(pathlib.Path(str(x.get("path") or "")).name.lower() == "update.tmp" and int(x.get("strict_lha_record_count") or 0) > 0 for x in positives):
        raise RuntimeError("V01010_UPDATE_TMP_STRICT_LHA_EVIDENCE_MISSING")
    b = json.loads(bp.read_text(encoding="utf-8"))
    if b.get("format") != "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1" or b.get("status") != "PASS_READ_ONLY_WINDOW":
        raise RuntimeError("V0960_CONTENT_BASELINE_INVALID")
    return r, b


def _lha_crc16_at(mm: mmap.mmap, entry: dict[str, Any]) -> int | None:
    # Level-0/1 base headers place the file CRC16 immediately after the filename.
    pos = int(entry.get("filename_end") or 0)
    header_end = int(entry.get("base_header_end") or 0)
    if pos <= 0 or pos + 2 > header_end or pos + 2 > len(mm):
        return None
    return struct.unpack_from("<H", mm, pos)[0]


def _ascii_hits(data: bytes, rx: re.Pattern[bytes], limit: int = 100) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in rx.finditer(data):
        try:
            text = m.group(0).decode("latin-1", errors="replace")
        except Exception:
            continue
        out.append({"text": text, "offset": int(m.start())})
        if len(out) >= limit:
            break
    return out


def _inspect_payload_bytes(data: bytes, tmp_root: pathlib.Path, label: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "size": len(data),
        "sha256": _sha_bytes(data),
        "starts_model062": data.startswith(MODEL062),
        "model062_magic_count": data.count(MODEL062),
        "target_name_hits": _ascii_hits(data, TARGET_RX, 80),
        "upw_hits": _ascii_hits(data, UPW_RX, 80),
        "url_hits": _ascii_hits(data, URL_RX, 40),
    }
    tmp = tmp_root / f"{label}.bin"
    tmp.write_bytes(data)
    try:
        with tmp.open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                nested = _lha_entries(mm)
            finally:
                mm.close()
        row["nested_lha_entries"] = [
            {
                "method": e.get("method"), "level": e.get("level"), "filename": e.get("filename"),
                "compressed_size": e.get("compressed_size"), "original_size": e.get("original_size"),
                "checksum_ok": e.get("checksum_ok"), "payload_bounds_ok_level0": e.get("payload_bounds_ok_level0"),
                "header_start": e.get("header_start"), "base_header_end": e.get("base_header_end"),
            }
            for e in nested[:40]
        ]
    finally:
        tmp.unlink(missing_ok=True)
    return row


def _extract_lh0(mm: mmap.mmap, entry: dict[str, Any], staging: pathlib.Path, idx: int) -> dict[str, Any]:
    ds = int(entry["base_header_end"])
    comp = int(entry["compressed_size"])
    orig = int(entry["original_size"])
    data = bytes(mm[ds:ds + comp])
    header_crc = _lha_crc16_at(mm, entry)
    computed_crc = _crc16_lha(data)
    crc_ok = header_crc is not None and header_crc == computed_crc
    name = pathlib.PurePosixPath(str(entry.get("filename") or f"member_{idx}").replace("\\", "/")).name or f"member_{idx}.bin"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    dest = staging / f"member_{idx:02d}_{safe}"
    dest.write_bytes(data)
    return {
        "stored_member_path": str(dest),
        "stored_member_sha256": _sha_bytes(data),
        "stored_member_size": len(data),
        "size_closure": comp == orig == len(data),
        "header_crc16": header_crc,
        "computed_crc16": computed_crc,
        "crc16_ok": crc_ok,
    }


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

    path = (candidate.expanduser().resolve() if candidate else (settings.client_root / "update.tmp").resolve())
    if not path.is_file():
        raise FileNotFoundError(f"UPDATE_TMP_MISSING:{path}")
    try:
        path.relative_to(settings.client_root.resolve())
    except Exception:
        raise RuntimeError(f"CANDIDATE_NOT_INSIDE_SUMMIT_CLIENT:{path}")

    before = _snapshot_file(path)
    staging = root / "pt_build/update_tmp_lha_forensics_v01020"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    temp = root / "pt_build/.v01020_tmp"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            raw_entries = _lha_entries(mm)
            for i, e in enumerate(raw_entries):
                row = {
                    "index": i,
                    "header_start": int(e.get("header_start") or 0),
                    "base_header_end": int(e.get("base_header_end") or 0),
                    "header_size": int(e.get("header_size") or 0),
                    "method": str(e.get("method") or ""),
                    "level": int(e.get("level") or 0),
                    "filename": str(e.get("filename") or ""),
                    "compressed_size": int(e.get("compressed_size") or 0),
                    "original_size": int(e.get("original_size") or 0),
                    "header_checksum_ok": bool(e.get("checksum_ok")),
                    "payload_bounds_ok_level0": bool(e.get("payload_bounds_ok_level0")),
                    "file_crc16": _lha_crc16_at(mm, e),
                }
                strict = bool(row["header_checksum_ok"] and row["payload_bounds_ok_level0"])
                row["strict_level0_record"] = strict
                ds = row["base_header_end"]
                de = ds + row["compressed_size"]
                if 0 <= ds <= de <= len(mm):
                    comp_bytes = bytes(mm[ds:de])
                    row["compressed_payload_sha256"] = _sha_bytes(comp_bytes)
                    row["compressed_payload_head_hex"] = comp_bytes[:64].hex()
                    # Save compressed bytes for non-lh0 forensic decoding only; this is not an extracted asset claim.
                    cpath = staging / f"record_{i:02d}_{re.sub(r'[^A-Za-z0-9_.-]+','_',row['filename'] or 'unnamed')}.compressed.bin"
                    cpath.write_bytes(comp_bytes)
                    row["compressed_staging_path"] = str(cpath)
                if strict and row["method"] == "-lh0-":
                    ext = _extract_lh0(mm, e, staging, i)
                    row.update(ext)
                    data = pathlib.Path(ext["stored_member_path"]).read_bytes()
                    row["decoded_payload"] = _inspect_payload_bytes(data, temp, f"lh0_{i}")
                    # Reuse the strict target/model scanner on the decoded member. Recovered files, if any,
                    # are staging-only and still require its Model0.62 physical validation.
                    rr, scan = _scan_raw(pathlib.Path(ext["stored_member_path"]), staging / "strict_nested_recovery", f"record{i:02d}", temp)
                    row["decoded_strict_scan"] = scan
                    row["decoded_strict_recovered"] = rr
                entries.append(row)

            whole = bytes(mm[:])
        finally:
            mm.close()

    whole_inspect = {
        "target_name_hits": _ascii_hits(whole, TARGET_RX, 80),
        "upw_hits": _ascii_hits(whole, UPW_RX, 80),
        "url_hits": _ascii_hits(whole, URL_RX, 40),
        "model062_magic_count": whole.count(MODEL062),
    }
    strict_count = sum(1 for e in entries if e["strict_level0_record"])
    stored_count = sum(1 for e in entries if e.get("stored_member_path"))
    decoded_target_hits = sum(len((e.get("decoded_payload") or {}).get("target_name_hits") or []) for e in entries)
    decoded_model062 = sum(int((e.get("decoded_payload") or {}).get("model062_magic_count") or 0) for e in entries)
    recovered_nested = [r for e in entries for r in (e.get("decoded_strict_recovered") or [])]

    if recovered_nested:
        mode = "UPDATE_TMP_STRICT_NESTED_TFF_RECOVERED"
    elif stored_count and (decoded_target_hits or decoded_model062):
        mode = "UPDATE_TMP_LH0_PAYLOAD_RELEVANT_NEEDS_MAPPING"
    elif stored_count:
        mode = "UPDATE_TMP_LH0_DECODED_NOT_TFF"
    elif entries:
        methods = sorted({e["method"] for e in entries})
        mode = "UPDATE_TMP_COMPRESSED_LHA_DECODER_REQUIRED:" + ",".join(methods)
    else:
        mode = "UPDATE_TMP_NO_LHA_RECORD_FOUND"

    shutil.rmtree(temp, ignore_errors=True)
    after = _snapshot_file(path)
    guards_after = _guard_snapshot(root)
    ca = _verify_content_baseline(settings.client_root, baseline)
    if before != after:
        raise RuntimeError("UPDATE_TMP_CHANGED_DURING_FORENSICS")
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_V01020")
    if not ca["pass"]:
        raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_V01020")

    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "client_read_only": True,
        "prior_v0101_strict_pass": True,
        "candidate": {"path": str(path), "size": before[0], "sha256": before[2]},
        "lha_entries": entries,
        "whole_file_evidence": whole_inspect,
        "summary": {
            "lha_entry_count": len(entries),
            "strict_level0_record_count": strict_count,
            "stored_lh0_decoded_count": stored_count,
            "decoded_target_name_hit_count": decoded_target_hits,
            "decoded_model062_magic_count": decoded_model062,
            "strict_nested_tff_recovered_count": len(recovered_nested),
            "methods": sorted({e["method"] for e in entries}),
            "filenames": [e["filename"] for e in entries],
            "mode": mode,
        },
        "decision": {
            "transplant_write_authorized": False,
            "new_class_claimed": False,
            "runtime_renderer_claimed": False,
            "staging_bytes_are_forensic_only_unless_strict_nested_recovery": True,
            "next_on_pass": (
                "resolve dependencies and Blender preview for strict recovered TfF"
                if recovered_nested else
                "implement only the LHA method decoder reported here, then re-run strict nested validation"
                if entries and stored_count == 0 else
                "follow decoded payload structure/refs only if TfF or Model0.62 evidence exists; otherwise classify update.tmp as unrelated updater cache"
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
            "client_read_only": r["client_read_only"], "candidate": r["candidate"],
            "summary": s,
            "lha_entries": [
                {k: e.get(k) for k in (
                    "index", "method", "level", "filename", "compressed_size", "original_size",
                    "header_checksum_ok", "payload_bounds_ok_level0", "file_crc16", "crc16_ok",
                    "stored_member_path", "compressed_staging_path", "decoded_payload"
                ) if k in e}
                for e in r["lha_entries"][:12]
            ],
            "whole_file_evidence": r["whole_file_evidence"],
            "decision": r["decision"], "guards": r["guards"], "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(
            f"update_tmp_lha_forensics=PASS mode={s['mode']} entries={s['lha_entry_count']} "
            f"strict_l0={s['strict_level0_record_count']} lh0_decoded={s['stored_lh0_decoded_count']} "
            f"tff_hits={s['decoded_target_name_hit_count']} model062={s['decoded_model062_magic_count']} "
            f"recovered={s['strict_nested_tff_recovered_count']} read_only=true"
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
