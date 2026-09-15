from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import json
import math
import mmap
import os
import pathlib
import re
import struct
import zlib
from typing import Any

from .config import Settings
from .official_character_donor_census import _parse_donor_spec
from .official_container_character_atlas import _guard_snapshot, _normalize, _scan_refs
from .official_container_entry_recovery import _verify_content_baseline
from .official_container_record_index import _locate_ref_span, _lha_entries

FORMAT = "PT_OFFICIAL_UPDATE_MANIFEST_PACK_CORRELATION_V1"
RELEASE = "0.9.9"
PRIOR_FORMAT = "PT_OFFICIAL_CONTAINER_RECORD_INDEX_AUDIT_V1"
TARGET_PREFIX = "char/tmabcd/"
PACK_RE = re.compile(r"^(?:[cbfl]data\d*|[cbfl]data)$", re.I)
MODEL062 = b"SMD Model data Ver 0.62"
MAGICS = {
    "MODEL062": MODEL062,
    "PNG": b"\x89PNG\r\n\x1a\n",
    "ZIP": b"PK\x03\x04",
    "GZIP": b"\x1f\x8b\x08",
    "BMP": b"BM",
}


def _sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _strict_prior(root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = root / "pt_build" / "official_container_record_index_v0970.json"
    baseline_path = root / "pt_build" / "summit_client_content_baseline_v0960.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"V0970_REPORT_MISSING:{report_path}")
    if not baseline_path.is_file():
        raise FileNotFoundError(f"V0960_BASELINE_MISSING:{baseline_path}")
    d = json.loads(report_path.read_text(encoding="utf-8"))
    if d.get("format") != PRIOR_FORMAT or d.get("status") != "PASS" or d.get("release_version") != "0.9.7":
        raise RuntimeError("V0970_STRICT_REPORT_MISMATCH")
    s = d.get("summary") or {}
    if int(s.get("strict_lha_target_mapping_count") or 0) != 0:
        raise RuntimeError("V0970_LHA_MAPPING_EXISTS_USE_LHA_PATH")
    fams = s.get("complete_body_head_donor_only_families") or []
    if not any(str(x.get("family")) == "TfF" and int(x.get("body_count") or 0) > 0 and int(x.get("head_count") or 0) > 0 for x in fams):
        raise RuntimeError("V0970_TFF_COMPLETE_FAMILY_MISSING")
    g = d.get("guards") or {}
    if not g.get("certified_writer_hashes_valid") or g.get("writer_modules_modified") or g.get("production_policies_modified"):
        raise RuntimeError("V0970_GUARD_STATE_INVALID")
    b = json.loads(baseline_path.read_text(encoding="utf-8"))
    if b.get("format") != "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1" or b.get("status") != "PASS_READ_ONLY_WINDOW":
        raise RuntimeError("V0960_CONTENT_BASELINE_INVALID")
    return d, b


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _case_index(root: pathlib.Path) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix().replace("\\", "/").lower()] = p
    return out


def _canon_ref(s: str) -> str:
    x = _normalize(s).replace("\\", "/").lstrip("./")
    while x.lower().startswith("image/image/"):
        x = x[6:]
    return x


def _resolve_loose(ref: str, index: dict[str, pathlib.Path]) -> pathlib.Path | None:
    r = _canon_ref(ref).lower()
    variants = [r]
    if r.startswith("image/"):
        variants.append(r[6:])
    else:
        variants.append("image/" + r)
    for v in variants:
        if v in index:
            return index[v]
    return None


def _field_values(mm: mmap.mmap, start: int, end: int) -> dict[tuple[str, int], int]:
    out: dict[tuple[str, int], int] = {}
    aligned_end = (end + 3) & ~3
    for anchor_name, anchor, rels in (
        ("START", start, range(-64, 0, 4)),
        ("END_ALIGNED", aligned_end, range(0, 68, 4)),
    ):
        for rel in rels:
            pos = anchor + rel
            if 0 <= pos and pos + 4 <= len(mm):
                out[(anchor_name, rel)] = struct.unpack_from("<I", mm, pos)[0]
    return out


def _dos_datetime(ts: float) -> tuple[int, int]:
    dt = _dt.datetime.fromtimestamp(ts)
    y = min(max(dt.year, 1980), 2107)
    d = ((y - 1980) << 9) | (dt.month << 5) | dt.day
    t = (dt.hour << 11) | (dt.minute << 5) | (dt.second // 2)
    return ((d << 16) | t) & 0xFFFFFFFF, ((t << 16) | d) & 0xFFFFFFFF


def _crc32(p: pathlib.Path) -> int:
    c = 0
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            c = zlib.crc32(chunk, c)
    return c & 0xFFFFFFFF


def _calibrate_setfile(setfile: pathlib.Path, donor_root: pathlib.Path, max_crc: int = 320) -> dict[str, Any]:
    refs = _scan_refs(setfile)
    idx = _case_index(donor_root)
    resolved: list[dict[str, Any]] = []
    for r in refs:
        p = _resolve_loose(str(r.get("ref") or ""), idx)
        if p is None or p.resolve() == setfile.resolve():
            continue
        resolved.append({"refrow": r, "path": p})
    # Stable spread through the manifest rather than only the first files.
    if len(resolved) > 900:
        step = len(resolved) / 900.0
        resolved = [resolved[int(i * step)] for i in range(900)]

    agg: dict[tuple[str, int], dict[str, Any]] = {}
    examples: list[dict[str, Any]] = []
    crc_budget = max_crc
    with setfile.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for item in resolved:
                rr, p = item["refrow"], item["path"]
                start, end = _locate_ref_span(mm, rr)
                fields = _field_values(mm, start, end)
                st = p.stat()
                crc = _crc32(p) if crc_budget > 0 and st.st_size <= 8 * 1024 * 1024 else None
                if crc is not None:
                    crc_budget -= 1
                dos1, dos2 = _dos_datetime(st.st_mtime)
                for key, value in fields.items():
                    a = agg.setdefault(key, {
                        "anchor": key[0], "rel": key[1], "sample_count": 0,
                        "size_exact_count": 0, "crc32_tested_count": 0, "crc32_exact_count": 0,
                        "dos_datetime_exact_count": 0, "unix_mtime_near_count": 0,
                        "small_int_count": 0,
                    })
                    a["sample_count"] += 1
                    a["size_exact_count"] += int(value == st.st_size)
                    if crc is not None:
                        a["crc32_tested_count"] += 1
                        a["crc32_exact_count"] += int(value == crc)
                    a["dos_datetime_exact_count"] += int(value in (dos1, dos2))
                    a["unix_mtime_near_count"] += int(abs(int(value) - int(st.st_mtime)) <= 2)
                    a["small_int_count"] += int(value <= 64)
                if len(examples) < 20:
                    examples.append({
                        "ref": _canon_ref(str(rr.get("ref") or "")),
                        "loose_path": p.relative_to(donor_root).as_posix(),
                        "size": st.st_size,
                        "crc32": crc,
                        "span_start": start,
                    })
        finally:
            mm.close()
    rows = []
    for a in agg.values():
        n = max(1, int(a["sample_count"]))
        ct = max(1, int(a["crc32_tested_count"]))
        a["size_exact_ratio"] = a["size_exact_count"] / n
        a["crc32_exact_ratio"] = a["crc32_exact_count"] / ct if a["crc32_tested_count"] else 0.0
        a["dos_datetime_exact_ratio"] = a["dos_datetime_exact_count"] / n
        a["unix_mtime_near_ratio"] = a["unix_mtime_near_count"] / n
        a["small_int_ratio"] = a["small_int_count"] / n
        a["calibration_score"] = (
            a["crc32_exact_ratio"] * 12.0 + a["size_exact_ratio"] * 10.0
            + a["dos_datetime_exact_ratio"] * 7.0 + a["unix_mtime_near_ratio"] * 5.0
        )
        rows.append(a)
    rows.sort(key=lambda x: (-x["calibration_score"], -x["size_exact_ratio"], -x["crc32_exact_ratio"], x["anchor"], abs(x["rel"])))
    best_size = max(rows, key=lambda x: x["size_exact_ratio"], default=None)
    best_crc = max(rows, key=lambda x: x["crc32_exact_ratio"], default=None)
    return {
        "setfile_size": setfile.stat().st_size,
        "reference_count": len(refs),
        "loose_calibration_reference_count": len(resolved),
        "top_calibrated_fields": rows[:20],
        "best_size_field": best_size,
        "best_crc32_field": best_crc,
        "strong_size_field_proven": bool(best_size and best_size["sample_count"] >= 50 and best_size["size_exact_ratio"] >= 0.90),
        "strong_crc32_field_proven": bool(best_crc and best_crc["crc32_tested_count"] >= 30 and best_crc["crc32_exact_ratio"] >= 0.90),
        "examples": examples,
    }


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    c = collections.Counter(data)
    n = len(data)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def _count_find(mm: mmap.mmap, needle: bytes, cap: int = 5000) -> int:
    if not needle:
        return 0
    count = 0
    pos = 0
    while count < cap:
        pos = mm.find(needle, pos)
        if pos < 0:
            break
        count += 1
        pos += max(1, len(needle))
    return count


def _pack_files(root: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if PACK_RE.match(name):
            out.append(p)
    return sorted(out, key=lambda x: x.as_posix().lower())


def _probe_pack(p: pathlib.Path, root: pathlib.Path) -> dict[str, Any]:
    size = p.stat().st_size
    with p.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            head = bytes(mm[:64])
            sample = bytearray()
            win = min(65536, size)
            for off in sorted(set([0, max(0, size // 2 - win // 2), max(0, size - win)])):
                sample.extend(mm[off:off + win])
            magics = {k: _count_find(mm, v, cap=10000) for k, v in MAGICS.items()}
            lha_methods = 0
            for method in (b"-lh0-", b"-lh1-", b"-lh5-", b"-lh6-", b"-lh7-", b"-lhd-"):
                lha_methods += _count_find(mm, method, cap=10000)
            strict_lha_records = len(_lha_entries(mm))
            tmabcd_plain = _count_find(mm, b"char/tmABCD", cap=10000) + _count_find(mm, b"char\\tmABCD", cap=10000)
            return {
                "relative_path": p.relative_to(root).as_posix(),
                "size": size,
                "sha256": _sha(p),
                "head_hex": head.hex(),
                "head_ascii": ''.join(chr(b) if 32 <= b < 127 else '.' for b in head),
                "sample_entropy_bits_per_byte": round(_entropy(bytes(sample)), 6),
                "known_magic_counts": magics,
                "lha_method_marker_count": lha_methods,
                "strict_lha_record_count": strict_lha_records,
                "plaintext_tmabcd_count": tmabcd_plain,
            }
        finally:
            mm.close()


def _choose_signatures(root: pathlib.Path, refs: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    idx = _case_index(root)
    out = []
    seen: set[str] = set()
    for rr in refs:
        p = _resolve_loose(str(rr.get("ref") or ""), idx)
        if p is None or p.name.lower() == "setfile.lst":
            continue
        rel = p.relative_to(root).as_posix()
        if rel.lower() in seen:
            continue
        size = p.stat().st_size
        if not (96 <= size <= 2 * 1024 * 1024):
            continue
        data = p.read_bytes()
        candidates = [64, 128, size // 3, size // 2]
        sig = None
        sig_off = None
        for off in candidates:
            if 0 <= off <= size - 32:
                s = data[off:off + 32]
                if len(set(s)) >= 10 and s.count(0) < 20:
                    sig, sig_off = s, off
                    break
        if sig is None:
            continue
        seen.add(rel.lower())
        out.append({"relative_path": rel, "file_size": size, "signature_offset": sig_off, "signature_hex": sig.hex(), "_sig": sig})
        if len(out) >= limit:
            break
    return out


def _signature_hits(packs: list[pathlib.Path], root: pathlib.Path, signatures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = []
    for p in packs:
        with p.open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                for s in signatures:
                    pos = mm.find(s["_sig"])
                    if pos >= 0:
                        hits.append({
                            "source_loose_path": s["relative_path"],
                            "pack": p.relative_to(root).as_posix(),
                            "pack_offset": int(pos),
                            "signature_offset_in_source": s["signature_offset"],
                        })
            finally:
                mm.close()
    return hits


def _target_family_refs(setfile: pathlib.Path) -> list[str]:
    out = []
    for rr in _scan_refs(setfile):
        ref = _canon_ref(str(rr.get("ref") or ""))
        lo = ref.lower()
        base = pathlib.PurePosixPath(lo).name
        if lo.startswith(TARGET_PREFIX) and (base.startswith("tfbf") or base.startswith("tfhf") or base.startswith("ctfbf") or base.startswith("6tfbf")):
            out.append(ref)
    return sorted(set(out), key=str.lower)


def _scan_donor(name: str, root: pathlib.Path) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    before = _snapshot(root)
    setfile = root / "setfile.lst"
    if not setfile.is_file():
        raise FileNotFoundError(f"SETFILE_MISSING:{setfile}")
    refs = _scan_refs(setfile)
    calibration = _calibrate_setfile(setfile, root)
    packs = _pack_files(root)
    probes = [_probe_pack(p, root) for p in packs]
    signatures = _choose_signatures(root, refs)
    hits = _signature_hits(packs, root, signatures)
    after = _snapshot(root)
    target_refs = _target_family_refs(setfile)
    total_model_magic = sum(int(x["known_magic_counts"].get("MODEL062", 0)) for x in probes)
    total_lha = sum(int(x["lha_method_marker_count"]) for x in probes)
    total_strict_lha = sum(int(x["strict_lha_record_count"]) for x in probes)
    total_plain = sum(int(x["plaintext_tmabcd_count"]) for x in probes)
    local_payload_evidence = bool(total_model_magic or total_strict_lha or hits)
    return {
        "name": name,
        "root": str(root),
        "read_only": before == after,
        "setfile": {
            "relative_path": "setfile.lst",
            "sha256": _sha(setfile),
            "role": "UPDATER_FILE_MANIFEST_CANDIDATE",
            "calibration": calibration,
        },
        "local_pack_count": len(packs),
        "local_pack_probes": probes,
        "loose_signature_probe_count": len(signatures),
        "loose_signature_hits_in_packs": hits,
        "tff_manifest_reference_count": len(target_refs),
        "tff_manifest_reference_sample": target_refs[:120],
        "pack_evidence_summary": {
            "model062_magic_count": total_model_magic,
            "lha_method_marker_count": total_lha,
            "strict_lha_record_count": total_strict_lha,
            "plaintext_tmabcd_count": total_plain,
            "raw_loose_signature_hit_count": len(hits),
            "local_payload_evidence_for_manifest_assets": local_payload_evidence,
            "absence_claimed": False,
        },
    }


def _write_csv(path: pathlib.Path, donors: list[dict[str, Any]]) -> None:
    fields = ["donor", "pack", "size", "entropy", "model062_magic", "lha_markers", "plaintext_tmabcd"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for d in donors:
            for p in d["local_pack_probes"]:
                w.writerow({
                    "donor": d["name"], "pack": p["relative_path"], "size": p["size"],
                    "entropy": p["sample_entropy_bits_per_byte"],
                    "model062_magic": p["known_magic_counts"].get("MODEL062", 0),
                    "lha_markers": p["lha_method_marker_count"],
                    "plaintext_tmabcd": p["plaintext_tmabcd_count"],
                })


def run(root: pathlib.Path, output: pathlib.Path, donor_specs: list[str]) -> dict[str, Any]:
    root = root.resolve()
    settings = Settings.discover(root)
    prior, baseline_doc = _strict_prior(root)
    guards_before = _guard_snapshot(root)
    if not all(x["pass"] for x in guards_before["writers"].values()):
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    baseline = {"files": baseline_doc.get("files") or {}}
    client_before = _verify_content_baseline(settings.client_root, baseline)
    if not client_before["pass"]:
        raise RuntimeError("SUMMIT_CORPUS_NO_LONGER_MATCHES_V0960_BASELINE")

    donors = []
    for spec in donor_specs:
        name, droot = _parse_donor_spec(spec)
        donors.append(_scan_donor(name, droot))

    guards_after = _guard_snapshot(root)
    client_after = _verify_content_baseline(settings.client_root, baseline)
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_MANIFEST_PACK_AUDIT")
    if not client_after["pass"]:
        raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_MANIFEST_PACK_AUDIT")
    if not all(d["read_only"] for d in donors):
        raise RuntimeError("DONOR_CHANGED_DURING_MANIFEST_PACK_AUDIT")

    any_payload = any(d["pack_evidence_summary"]["local_payload_evidence_for_manifest_assets"] for d in donors)
    any_strong_size = any(d["setfile"]["calibration"]["strong_size_field_proven"] for d in donors)
    any_strong_crc = any(d["setfile"]["calibration"]["strong_crc32_field_proven"] for d in donors)
    output.parent.mkdir(parents=True, exist_ok=True)
    csvp = output.with_suffix(".csv")
    mdp = output.with_suffix(".md")
    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "client_and_donors_read_only": True,
        "prior_v097_strict_pass": True,
        "summit_v096_content_tree_sha256": (prior.get("summit_v096_content_tree_sha256") or (prior.get("guards") or {}).get("summit_v096_content_tree_sha256")),
        "research_target": "TfF complete donor-only body/head family from char/tmABCD",
        "donors": donors,
        "summary": {
            "donor_count": len(donors),
            "setfile_manifest_calibration_strong_size_field_any": any_strong_size,
            "setfile_manifest_calibration_strong_crc32_field_any": any_strong_crc,
            "local_payload_evidence_any": any_payload,
            "local_payload_absence_claimed": False,
            "tff_is_manifested_in_official_donors": all(d["tff_manifest_reference_count"] > 0 for d in donors),
        },
        "decision": {
            "setfile_treated_as_payload_container": False,
            "setfile_treated_as_updater_manifest_candidate": True,
            "cdata_bdata_payload_encoding_claimed": False,
            "transplant_write_authorized": False,
            "new_class_claimed": False,
            "next_on_pass": (
                "if local pack evidence exists, refine the exact pack/encoding relation using signature offsets/magics and build one read-only TfF extraction proof; "
                "if no local pack evidence exists, stop claiming the official local clients contain TfF payload bytes and seek the actual updater .upw/archive payload or another fully expanded official client"
            ),
        },
        "guards": {
            "certified_writer_hashes_valid": True,
            "writer_modules_modified": False,
            "production_policies_modified": False,
            "policy_sha256": guards_after["policies"],
            "summit_matches_v0960_baseline_before": client_before["pass"],
            "summit_matches_v0960_baseline_after": client_after["pass"],
        },
        "outputs": {"json": str(output), "csv": str(csvp), "markdown": str(mdp)},
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csvp, donors)
    lines = [
        "# Official Update Manifest + Local Pack Correlation V0.9.9", "",
        "Read-only. setfile.lst is analyzed as manifest metadata; cdata/bdata/fdata/ldata are probed independently for local payload evidence.", "",
        f"- donor count: {len(donors)}",
        f"- strong size field calibration: {any_strong_size}",
        f"- strong CRC field calibration: {any_strong_crc}",
        f"- local payload evidence any: {any_payload}",
        "- payload absence claimed: false", "",
    ]
    for d in donors:
        e = d["pack_evidence_summary"]
        lines += [f"## {d['name']}", f"- packs: {d['local_pack_count']}", f"- TfF manifest refs: {d['tff_manifest_reference_count']}", f"- Model0.62 magics in packs: {e['model062_magic_count']}", f"- strict LHA records in packs: {e['strict_lha_record_count']}", f"- raw loose signature hits: {e['raw_loose_signature_hit_count']}", ""]
    mdp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--donor", action="append", required=True)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.output)
    try:
        r = run(pathlib.Path(a.root), out, list(a.donor))
        compact = {
            "format": r["format"], "status": r["status"], "release_version": r["release_version"],
            "client_and_donors_read_only": r["client_and_donors_read_only"],
            "prior_v097_strict_pass": r["prior_v097_strict_pass"],
            "research_target": r["research_target"],
            "donors": [{
                "name": d["name"], "read_only": d["read_only"],
                "setfile_calibration": {
                    "reference_count": d["setfile"]["calibration"]["reference_count"],
                    "loose_calibration_reference_count": d["setfile"]["calibration"]["loose_calibration_reference_count"],
                    "strong_size_field_proven": d["setfile"]["calibration"]["strong_size_field_proven"],
                    "strong_crc32_field_proven": d["setfile"]["calibration"]["strong_crc32_field_proven"],
                    "top_calibrated_fields": d["setfile"]["calibration"]["top_calibrated_fields"][:8],
                },
                "local_pack_count": d["local_pack_count"],
                "local_pack_probes": d["local_pack_probes"],
                "loose_signature_probe_count": d["loose_signature_probe_count"],
                "loose_signature_hits_in_packs": d["loose_signature_hits_in_packs"][:30],
                "tff_manifest_reference_count": d["tff_manifest_reference_count"],
                "pack_evidence_summary": d["pack_evidence_summary"],
            } for d in r["donors"]],
            "summary": r["summary"], "decision": r["decision"], "guards": r["guards"], "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(
            "official_update_manifest_pack_correlation=PASS "
            f"local_payload_evidence={str(r['summary']['local_payload_evidence_any']).lower()} "
            f"tff_manifested={str(r['summary']['tff_is_manifested_in_official_donors']).lower()} read_only=true"
        )
        return 0
    except Exception as exc:
        fail = {
            "format": FORMAT, "status": "FAIL", "release_version": RELEASE,
            "error": f"{type(exc).__name__}:{exc}", "client_and_donors_read_only": True,
            "transplant_write_authorized": False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
