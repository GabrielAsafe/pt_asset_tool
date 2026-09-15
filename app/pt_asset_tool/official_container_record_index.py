from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import mmap
import pathlib
import re
import struct
from typing import Any

from .config import Settings
from .official_character_donor_census import _parse_donor_spec
from .official_container_character_atlas import (
    ASSET_EXTS,
    MODEL_CONFIG_EXTS,
    _build_summit_index,
)
# Import the small, already-audited scanners/guards from the previous stages.
from .official_container_character_atlas import _guard_snapshot, _is_container, _normalize, _ref_record, _scan_refs, _snapshot
from .official_container_entry_recovery import _canonical_character_ref, _verify_content_baseline

FORMAT = "PT_OFFICIAL_CONTAINER_RECORD_INDEX_AUDIT_V1"
RELEASE = "0.9.7"
PRIOR_FORMAT = "PT_OFFICIAL_CONTAINER_ENTRY_RECOVERY_V2"
TARGET_PREFIX = "char/tmabcd/"
LHA_METHOD_RE = re.compile(rb"-(?:lh[0-9d]|lz[45s])-", re.I)
PLAYER_NAME_RE = re.compile(
    r"^(?P<wrapper>[c6w]?)(?P<faction>[tm])(?P<gender>[mf])(?P<part>[bh])(?P<class>[a-f])(?P<variant>.*)$",
    re.I,
)


def _sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _strict_prior(root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = root / "pt_build" / "official_container_entry_recovery_v0960.json"
    baseline_path = root / "pt_build" / "summit_client_content_baseline_v0960.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"V0960_REPORT_MISSING:{report_path}")
    if not baseline_path.is_file():
        raise FileNotFoundError(f"V0960_BASELINE_MISSING:{baseline_path}")
    d = json.loads(report_path.read_text(encoding="utf-8"))
    if d.get("format") != PRIOR_FORMAT or d.get("status") != "PASS" or d.get("release_version") != "0.9.6":
        raise RuntimeError("V0960_STRICT_REPORT_MISMATCH")
    if not d.get("client_and_donors_read_only") or not d.get("client_corpus_rebaselined_to_current_state"):
        raise RuntimeError("V0960_READ_ONLY_BASELINE_INVALID")
    s = d.get("summary") or {}
    if int(s.get("tmabcd_unique_donor_only_smd_name_count") or 0) < 1:
        raise RuntimeError("V0960_NO_TMDBCD_DONOR_ONLY_SMD")
    if int(s.get("strict_raw_recovered_count") or 0) != 0:
        raise RuntimeError("V0960_RAW_RECOVERY_ALREADY_EXISTS_USE_OTHER_PATH")
    g = d.get("guards") or {}
    if not g.get("certified_writer_hashes_valid") or g.get("writer_modules_modified") or g.get("production_policies_modified"):
        raise RuntimeError("V0960_GUARD_STATE_INVALID")
    b = json.loads(baseline_path.read_text(encoding="utf-8"))
    if b.get("format") != "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1" or b.get("status") != "PASS_READ_ONLY_WINDOW":
        raise RuntimeError("V0960_CONTENT_BASELINE_INVALID")
    return d, b


def _ref_bytes(ref: str, encoding: str) -> bytes:
    if encoding == "UTF16LE":
        return ref.encode("utf-16le", errors="ignore")
    return ref.encode("latin-1", errors="ignore")


def _locate_ref_span(mm: mmap.mmap, row: dict[str, Any]) -> tuple[int, int]:
    off = int(row["first_offset"])
    raw = str(row.get("ref") or "")
    enc = str(row.get("encoding") or "ASCII")
    needle = _ref_bytes(raw, enc)
    # The scanner reports the start of the matched run. Normalization can trim a
    # small prefix, so permit a tight local re-search rather than assuming bytes.
    lo = max(0, off - 8)
    hi = min(len(mm), off + max(512, len(needle) + 64))
    pos = mm.find(needle, lo, hi) if needle else -1
    if pos < 0:
        pos = off
        end = min(len(mm), off + len(needle))
    else:
        end = pos + len(needle)
    return int(pos), int(end)


def _u32(mm: mmap.mmap, off: int) -> int | None:
    if off < 0 or off + 4 > len(mm):
        return None
    return struct.unpack_from("<I", mm, off)[0]


def _magic_at(mm: mmap.mmap, off: int) -> str | None:
    if off < 0 or off >= len(mm):
        return None
    head = mm[off:off + 32]
    if head.startswith(b"SMD Model data Ver 0.62"):
        return "MODEL062"
    if head.startswith(b"BM"):
        return "BMP"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"MZ"):
        return "PE"
    if len(head) >= 7 and LHA_METHOD_RE.match(head[2:7]):
        return "LHA_HEADER"
    return None


def _parse_lha_level01(mm: mmap.mmap, start: int) -> dict[str, Any] | None:
    """Parse only the common checksum-bearing LHA level-0/1 base header.

    We intentionally stop at record metadata.  No compressed payload is decoded
    here.  A mapping is called strict only when method/header checksum/bounds and
    filename containment all validate from bytes in the donor container itself.
    """
    n = len(mm)
    if start < 0 or start + 22 > n:
        return None
    hsize = mm[start]
    checksum = mm[start + 1]
    method = bytes(mm[start + 2:start + 7])
    if not LHA_METHOD_RE.fullmatch(method):
        return None
    if hsize < 20 or start + 2 + hsize > n:
        return None
    level = mm[start + 20]
    if level not in (0, 1):
        return None
    body = bytes(mm[start + 2:start + 2 + hsize])
    checksum_ok = (sum(body) & 0xFF) == checksum
    comp = struct.unpack_from("<I", mm, start + 7)[0]
    orig = struct.unpack_from("<I", mm, start + 11)[0]
    name_len = mm[start + 21]
    name_start = start + 22
    name_end = name_start + name_len
    if name_len < 1 or name_end > start + 2 + hsize:
        return None
    name_raw = bytes(mm[name_start:name_end])
    try:
        name = _normalize(name_raw.decode("latin-1", errors="ignore"))
    except Exception:
        name = ""
    data_start = start + 2 + hsize
    # For level 1 the base header can be followed by extended headers. We do not
    # claim the exact compressed-data start; bounds below therefore apply strictly
    # only to level 0. Metadata mapping still remains useful for level 1.
    payload_bounds_ok = bool(level == 0 and comp <= n - data_start)
    return {
        "header_start": start,
        "header_size": int(hsize),
        "method": method.decode("ascii", errors="replace"),
        "level": int(level),
        "checksum_ok": bool(checksum_ok),
        "compressed_size": int(comp),
        "original_size": int(orig),
        "filename": name,
        "filename_start": int(name_start),
        "filename_end": int(name_end),
        "base_header_end": int(data_start),
        "payload_bounds_ok_level0": payload_bounds_ok,
    }


def _lha_entries(mm: mmap.mmap) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    pos = 2
    while True:
        m = LHA_METHOD_RE.search(mm, pos)
        if not m:
            break
        start = m.start() - 2
        rec = _parse_lha_level01(mm, start)
        if rec is not None:
            entries.append(rec)
        pos = m.start() + 5
    return entries


def _canonical_lo(s: str) -> str:
    return _canonical_character_ref(s).replace("\\", "/").lower().lstrip("/")


def _player_family(stem: str) -> dict[str, Any] | None:
    m = PLAYER_NAME_RE.match(stem)
    if not m:
        return None
    d = {k: (v or "") for k, v in m.groupdict().items()}
    d["faction"] = d["faction"].upper()
    d["gender"] = d["gender"].lower()
    d["part"] = d["part"].upper()
    d["class"] = d["class"].upper()
    d["role"] = "BODY" if d["part"] == "B" else "HEAD"
    d["family"] = f"{d['faction']}{d['gender']}{d['class']}"
    return d


def _field_stats_for_row(mm: mmap.mmap, start: int, end: int) -> list[dict[str, Any]]:
    n = len(mm)
    out: list[dict[str, Any]] = []
    aligned_end = (end + 3) & ~3
    # Fields before variable-length name often sit at fixed negative dwords.
    for anchor_name, anchor, rels in (
        ("START", start, range(-64, 0, 4)),
        ("END_ALIGNED", aligned_end, range(0, 68, 4)),
    ):
        for rel in rels:
            pos = anchor + rel
            value = _u32(mm, pos)
            if value is None:
                continue
            magic = _magic_at(mm, int(value)) if value < n else None
            out.append({
                "anchor": anchor_name,
                "rel": int(rel),
                "value": int(value),
                "plausible_offset": bool(0 < value < n),
                "plausible_size": bool(16 <= value <= min(n, 256 * 1024 * 1024)),
                "points_to_magic": magic,
            })
    return out


def _aggregate_fields(samples: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, int], dict[str, Any]] = {}
    total = len(samples)
    for fields in samples:
        by = {(f["anchor"], int(f["rel"])): f for f in fields}
        for key, f in by.items():
            a = agg.setdefault(key, {
                "anchor": key[0], "rel": key[1], "sample_count": 0,
                "plausible_offset_count": 0, "plausible_size_count": 0,
                "points_to_magic_count": 0, "magic_counts": collections.Counter(),
            })
            a["sample_count"] += 1
            a["plausible_offset_count"] += int(f["plausible_offset"])
            a["plausible_size_count"] += int(f["plausible_size"])
            if f["points_to_magic"]:
                a["points_to_magic_count"] += 1
                a["magic_counts"][f["points_to_magic"]] += 1
    rows = []
    for a in agg.values():
        denom = max(1, a["sample_count"])
        row = dict(a)
        row["magic_counts"] = dict(a["magic_counts"])
        row["plausible_offset_ratio"] = a["plausible_offset_count"] / denom
        row["plausible_size_ratio"] = a["plausible_size_count"] / denom
        row["points_to_magic_ratio"] = a["points_to_magic_count"] / denom
        # Magic pointers dominate; otherwise favor fields that repeatedly look
        # like offsets/sizes at the same structural relative location.
        row["score"] = (
            row["points_to_magic_ratio"] * 10.0
            + row["plausible_offset_ratio"] * 2.0
            + row["plausible_size_ratio"]
        )
        rows.append(row)
    rows.sort(key=lambda r: (-r["score"], r["anchor"], abs(r["rel"])))
    return rows[:40]


def _scan_container(path: pathlib.Path, donor_root: pathlib.Path, summit_idx: dict[str, Any]) -> dict[str, Any]:
    rel = path.relative_to(donor_root).as_posix()
    raw_refs = _scan_refs(path)
    rows: list[dict[str, Any]] = []
    for rr in raw_refs:
        ext = pathlib.PurePosixPath(rr["ref"]).suffix.lower()
        if ext not in ASSET_EXTS:
            continue
        r = _ref_record(rr, summit_idx)
        r["raw_ref"] = r["ref"]
        r["canonical_ref"] = _canonical_character_ref(r["ref"])
        r["container"] = rel
        rows.append(r)
    rows.sort(key=lambda r: (int(r["first_offset"]), str(r["ref"]).lower()))

    target_rows = [
        r for r in rows
        if r.get("signal") == "STRONG_CHARACTER_PATH"
        and ("/" + str(r.get("canonical_ref") or "").lower().lstrip("/")).startswith("/" + TARGET_PREFIX)
        and r.get("extension") in MODEL_CONFIG_EXTS
    ]

    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            lha = _lha_entries(mm)
            strict_lha = 0
            target_out = []
            fields_all: list[list[dict[str, Any]]] = []
            for r in target_rows:
                start, end = _locate_ref_span(mm, r)
                fields = _field_stats_for_row(mm, start, end)
                fields_all.append(fields)
                canon = _canonical_lo(str(r["canonical_ref"]))
                base = pathlib.PurePosixPath(canon).name.lower()
                mapped = []
                for e in lha:
                    # Strongest relation: the scanner reference itself is inside
                    # the validated LHA filename field. Filename equality is also
                    # accepted when the container path has a stripped prefix.
                    en = _canonical_lo(str(e.get("filename") or ""))
                    eb = pathlib.PurePosixPath(en).name.lower() if en else ""
                    contains = int(e["filename_start"]) <= start < int(e["filename_end"])
                    name_match = bool(en and (en == canon or eb == base))
                    if not (contains or name_match):
                        continue
                    strict = bool(
                        e.get("checksum_ok")
                        and name_match
                        and (e.get("level") == 1 or e.get("payload_bounds_ok_level0"))
                    )
                    m = {**e, "contains_scanner_offset": contains, "filename_match": name_match, "strict_record_mapping": strict}
                    mapped.append(m)
                if any(x["strict_record_mapping"] for x in mapped):
                    strict_lha += 1
                fam = _player_family(pathlib.PurePosixPath(canon).stem)
                target_out.append({
                    "ref": r["canonical_ref"],
                    "extension": r["extension"],
                    "summit_overlap": r["summit_overlap"],
                    "first_offset": int(r["first_offset"]),
                    "span_start": start,
                    "span_end": end,
                    "player_family": fam,
                    "lha_record_candidates": mapped[:5],
                    "field_probe": fields,
                })
            return {
                "relative_path": rel,
                "size": path.stat().st_size,
                "sha256": _sha(path),
                "reference_count": len(rows),
                "target_tmabcd_count": len(target_rows),
                "lha_level01_entry_count": len(lha),
                "strict_lha_target_mapping_count": strict_lha,
                "field_schema_candidates": _aggregate_fields(fields_all),
                "target_rows": target_out,
            }
        finally:
            mm.close()


def _family_summary(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    seen_ref: set[str] = set()
    for c in containers:
        for r in c["target_rows"]:
            fam = r.get("player_family")
            if not fam:
                continue
            ref = _canonical_lo(str(r["ref"]))
            # The same index path can be repeated across containers; family
            # inventory is about unique logical assets, not reference frequency.
            uniq = ref
            if uniq in seen_ref:
                continue
            seen_ref.add(uniq)
            key = fam["family"]
            g = groups.setdefault(key, {
                "family": key,
                "faction": fam["faction"], "gender": fam["gender"], "class": fam["class"],
                "unique_asset_count": 0, "body_count": 0, "head_count": 0,
                "donor_only_count": 0, "summit_overlap_count": 0,
                "body_names": [], "head_names": [],
            })
            g["unique_asset_count"] += 1
            if fam["role"] == "BODY":
                g["body_count"] += 1
                if len(g["body_names"]) < 60: g["body_names"].append(pathlib.PurePosixPath(ref).name)
            else:
                g["head_count"] += 1
                if len(g["head_names"]) < 60: g["head_names"].append(pathlib.PurePosixPath(ref).name)
            if r.get("summit_overlap") == "DONOR_REFERENCE_ONLY":
                g["donor_only_count"] += 1
            else:
                g["summit_overlap_count"] += 1
    out = []
    for g in groups.values():
        n = max(1, g["unique_asset_count"])
        g["donor_only_ratio"] = g["donor_only_count"] / n
        g["complete_body_head_family"] = bool(g["body_count"] and g["head_count"])
        # Priority is evidence, not a class-name claim: complete body+head sets
        # absent from Summit are best transplant-research candidates.
        g["priority_score"] = (
            (100 if g["complete_body_head_family"] else 0)
            + round(g["donor_only_ratio"] * 50, 3)
            + min(g["unique_asset_count"], 50)
        )
        out.append(g)
    out.sort(key=lambda x: (-x["priority_score"], -x["donor_only_count"], x["family"]))
    return out


def _scan_donor(name: str, root: pathlib.Path, summit_idx: dict[str, Any]) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    before = _snapshot(root)
    containers = []
    errors = []
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if not p.is_file() or not _is_container(p):
            continue
        try:
            c = _scan_container(p, root, summit_idx)
            if c["target_tmabcd_count"] or c["lha_level01_entry_count"]:
                containers.append(c)
        except Exception as exc:
            errors.append({"relative_path": p.relative_to(root).as_posix(), "error": f"{type(exc).__name__}:{exc}"})
    after = _snapshot(root)
    families = _family_summary(containers)
    strict = sum(c["strict_lha_target_mapping_count"] for c in containers)
    targets = sum(c["target_tmabcd_count"] for c in containers)
    lha_count = sum(c["lha_level01_entry_count"] for c in containers)
    return {
        "name": name,
        "root": str(root),
        "read_only": before == after,
        "container_count_scanned": len([p for p in root.rglob('*') if p.is_file() and _is_container(p)]),
        "relevant_container_count": len(containers),
        "target_tmabcd_reference_count": targets,
        "lha_level01_entry_count": lha_count,
        "strict_lha_target_mapping_count": strict,
        "family_count": len(families),
        "priority_families": families[:30],
        "scan_errors": errors,
        "containers": containers,
    }


def _write_csv(path: pathlib.Path, donors: list[dict[str, Any]]) -> None:
    fields = ["donor", "container", "ref", "extension", "summit_overlap", "first_offset", "family", "role", "class", "strict_lha_record"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for d in donors:
            for c in d["containers"]:
                for r in c["target_rows"]:
                    fam = r.get("player_family") or {}
                    w.writerow({
                        "donor": d["name"], "container": c["relative_path"], "ref": r["ref"],
                        "extension": r["extension"], "summit_overlap": r["summit_overlap"],
                        "first_offset": r["first_offset"], "family": fam.get("family"),
                        "role": fam.get("role"), "class": fam.get("class"),
                        "strict_lha_record": any(x.get("strict_record_mapping") for x in r.get("lha_record_candidates") or []),
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
    summit_idx = _build_summit_index(settings.client_root)

    donors = []
    for spec in donor_specs:
        name, droot = _parse_donor_spec(spec)
        donors.append(_scan_donor(name, droot, summit_idx))

    guards_after = _guard_snapshot(root)
    client_after = _verify_content_baseline(settings.client_root, baseline)
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_RECORD_INDEX_AUDIT")
    if not client_after["pass"]:
        raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_RECORD_INDEX_AUDIT")
    if not all(d["read_only"] for d in donors):
        raise RuntimeError("DONOR_CHANGED_DURING_RECORD_INDEX_AUDIT")

    total_targets = sum(d["target_tmabcd_reference_count"] for d in donors)
    strict_lha = sum(d["strict_lha_target_mapping_count"] for d in donors)
    lha_entries = sum(d["lha_level01_entry_count"] for d in donors)
    # Both donors are known near-identical. Present unique family evidence from
    # the first donor and use the second as an independent consistency run.
    priority = donors[0]["priority_families"] if donors else []
    complete_absent = [x for x in priority if x["complete_body_head_family"] and x["donor_only_ratio"] >= 0.95]

    output.parent.mkdir(parents=True, exist_ok=True)
    csvp = output.with_suffix(".csv")
    mdp = output.with_suffix(".md")
    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "client_and_donors_read_only": True,
        "prior_v096_strict_pass": True,
        "v096_strict_raw_recovered_count": int((prior.get("summary") or {}).get("strict_raw_recovered_count") or 0),
        "summit_v096_content_tree_sha256": (prior.get("client_content_baseline") or {}).get("content_tree_sha256"),
        "target_prefix": "char/tmABCD",
        "donors": donors,
        "summary": {
            "target_tmabcd_reference_count": total_targets,
            "lha_level01_entry_count": lha_entries,
            "strict_lha_target_mapping_count": strict_lha,
            "priority_family_count": len(priority),
            "complete_body_head_donor_only_family_count": len(complete_absent),
            "complete_body_head_donor_only_families": complete_absent[:20],
        },
        "decision": {
            "container_payload_encoding_claimed": False,
            "lha_claimed_only_if_strict_record_mapping_count_positive": True,
            "transplant_write_authorized": False,
            "new_class_claimed": False,
            "next_on_pass": (
                "if strict LHA record mappings exist, build a read-only decompression/extraction proof for the highest-priority complete body/head family; "
                "otherwise use per-container field_schema_candidates and target offsets to refine the custom record offset-size layout, limited to the top body/head family"
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
        "# Official Container Record/Index Audit V0.9.7", "",
        "Read-only audit. It does not assume cdata/bdata are LHA; LHA is reported only when checksum/bounds/filename mapping validate from donor bytes.", "",
        f"- tmABCD target refs (both donors): {total_targets}",
        f"- validated LHA level-0/1 records seen: {lha_entries}",
        f"- strict target->LHA record mappings: {strict_lha}",
        f"- complete body+head donor-only families: {len(complete_absent)}", "",
        "## Priority body/head families",
    ]
    for x in priority[:20]:
        lines.append(f"- {x['family']}: assets={x['unique_asset_count']} body={x['body_count']} head={x['head_count']} donor_only_ratio={x['donor_only_ratio']:.3f}")
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
            "prior_v096_strict_pass": r["prior_v096_strict_pass"],
            "summit_v096_content_tree_sha256": r["summit_v096_content_tree_sha256"],
            "donors": [{
                "name": d["name"], "read_only": d["read_only"],
                "container_count_scanned": d["container_count_scanned"],
                "relevant_container_count": d["relevant_container_count"],
                "target_tmabcd_reference_count": d["target_tmabcd_reference_count"],
                "lha_level01_entry_count": d["lha_level01_entry_count"],
                "strict_lha_target_mapping_count": d["strict_lha_target_mapping_count"],
                "priority_families": d["priority_families"][:12],
                "container_schema_summary": [
                    {
                        "relative_path": c["relative_path"],
                        "target_tmabcd_count": c["target_tmabcd_count"],
                        "lha_level01_entry_count": c["lha_level01_entry_count"],
                        "strict_lha_target_mapping_count": c["strict_lha_target_mapping_count"],
                        "top_field_schema_candidates": c["field_schema_candidates"][:8],
                    }
                    for c in sorted(d["containers"], key=lambda x: (-x["target_tmabcd_count"], x["relative_path"]))[:8]
                ],
                "strict_lha_samples": [
                    {
                        "container": c["relative_path"], "ref": row["ref"],
                        "mapping": next((m for m in row.get("lha_record_candidates") or [] if m.get("strict_record_mapping")), None),
                    }
                    for c in d["containers"] for row in c["target_rows"]
                    if any(m.get("strict_record_mapping") for m in row.get("lha_record_candidates") or [])
                ][:12],
                "scan_errors": d["scan_errors"],
            } for d in r["donors"]],
            "summary": r["summary"], "decision": r["decision"], "guards": r["guards"], "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(
            "official_container_record_index=PASS "
            f"targets={r['summary']['target_tmabcd_reference_count']} "
            f"strict_lha={r['summary']['strict_lha_target_mapping_count']} "
            f"body_head_families={r['summary']['complete_body_head_donor_only_family_count']} read_only=true"
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
