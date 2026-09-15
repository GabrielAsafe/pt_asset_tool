from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import json
import mmap
import pathlib
import shutil
import struct
from typing import Any

from .config import Settings
from .official_character_donor_census import _parse_donor_spec
from .official_container_character_atlas import (
    ASSET_EXTS,
    MODEL_CONFIG_EXTS,
    _build_summit_index,
    _guard_snapshot,
    _is_container,
    _normalize,
    _ref_record,
    _scan_refs,
    _snapshot,
)
from .rare_rigid_geometry import _parse_skeleton_tms
from .semantic_census import physical_probe
from .rare_rigid_context import parse_model062_physique_context
from .utils import sha256_file

FORMAT = "PT_OFFICIAL_CONTAINER_ENTRY_RECOVERY_V2"
RELEASE = "0.9.6"
PRIOR_FORMAT = "PT_OFFICIAL_CONTAINER_CHARACTER_REFERENCE_ATLAS_V1"
MODEL_HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO = 556, 40, 2236
MAX_PAIR_GAP = 8192
NEIGHBORHOOD_RADIUS = 8192
TARGET_PREFIX = "char/tmabcd/"


def _sha(p: pathlib.Path) -> str:
    return sha256_file(p)


def _strict_prior(root: pathlib.Path) -> dict[str, Any]:
    p = root / "pt_build" / "official_container_character_atlas_v0940.json"
    if not p.is_file():
        raise FileNotFoundError(f"V0940_REPORT_MISSING:{p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("format") != PRIOR_FORMAT or d.get("status") != "PASS" or d.get("release_version") != "0.9.4":
        raise RuntimeError("V0940_STRICT_REPORT_MISMATCH")
    if not d.get("client_and_donors_read_only"):
        raise RuntimeError("V0940_NOT_READ_ONLY")
    summary = d.get("summary") or {}
    if int(summary.get("strong_character_reference_count") or 0) < 1:
        raise RuntimeError("V0940_NO_STRONG_CHARACTER_REFS")
    if int(summary.get("strong_character_donor_only_count") or 0) < 1:
        raise RuntimeError("V0940_NO_DONOR_ONLY_CHARACTER_REFS")
    guards = d.get("guards") or {}
    if not guards.get("certified_writer_hashes_valid") or guards.get("writer_modules_modified") or guards.get("production_policies_modified"):
        raise RuntimeError("V0940_GUARD_STATE_INVALID")
    return d



def _content_baseline(root: pathlib.Path) -> dict[str, Any]:
    """Capture one strong content baseline of the current client corpus.

    The full SHA-256 pass happens once before recovery.  The end-of-run guard
    uses path/size/mtime/ctime deltas to decide which files need re-hashing.
    This accepts a deliberately enriched corpus that existed before the audit,
    while still failing closed on byte/path changes during the audit window.
    """
    files: dict[str, dict[str, Any]] = {}
    total = 0
    tree = hashlib.sha256()
    for fp in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if not fp.is_file():
            continue
        rel = fp.relative_to(root).as_posix()
        st = fp.stat()
        digest = _sha(fp)
        rec = {
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
            "ctime_ns": int(st.st_ctime_ns),
            "sha256": digest,
        }
        files[rel] = rec
        total += int(st.st_size)
        tree.update(rel.encode("utf-8", errors="surrogateescape"))
        tree.update(b"\0")
        tree.update(str(int(st.st_size)).encode("ascii"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\n")
    return {
        "file_count": len(files),
        "total_bytes": total,
        "content_tree_sha256": tree.hexdigest(),
        "files": files,
    }


def _verify_content_baseline(root: pathlib.Path, baseline: dict[str, Any]) -> dict[str, Any]:
    before = baseline.get("files") or {}
    now_meta: dict[str, dict[str, int]] = {}
    for fp in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if not fp.is_file():
            continue
        rel = fp.relative_to(root).as_posix()
        st = fp.stat()
        now_meta[rel] = {
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
            "ctime_ns": int(st.st_ctime_ns),
        }
    before_paths = set(before)
    after_paths = set(now_meta)
    added = sorted(after_paths - before_paths, key=str.lower)
    deleted = sorted(before_paths - after_paths, key=str.lower)
    metadata_only: list[str] = []
    content_changed: list[dict[str, Any]] = []
    rehashed = 0
    for rel in sorted(before_paths & after_paths, key=str.lower):
        b = before[rel]
        a = now_meta[rel]
        metadata_changed = (
            int(b.get("size", -1)) != a["size"]
            or int(b.get("mtime_ns", -1)) != a["mtime_ns"]
            or int(b.get("ctime_ns", -1)) != a["ctime_ns"]
        )
        if not metadata_changed:
            continue
        fp = root / pathlib.PurePosixPath(rel)
        current_sha = _sha(fp)
        rehashed += 1
        if current_sha == str(b.get("sha256")):
            metadata_only.append(rel)
        else:
            content_changed.append({
                "relative_path": rel,
                "before_sha256": b.get("sha256"),
                "after_sha256": current_sha,
                "before_size": b.get("size"),
                "after_size": a["size"],
            })
    ok = not added and not deleted and not content_changed
    return {
        "pass": ok,
        "added_during_audit": added,
        "deleted_during_audit": deleted,
        "content_changed_during_audit": content_changed,
        "metadata_only_changes": metadata_only,
        "metadata_changed_rehashed_count": rehashed,
    }


def _compare_v090_paths(root: pathlib.Path, baseline: dict[str, Any]) -> dict[str, Any]:
    p = root / "pt_build" / "semantic_asset_census_v0900.json"
    if not p.is_file():
        return {"available": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows = d.get("rows") or []
        old = {str(r.get("relative_path")) for r in rows if r.get("relative_path")}
        cur = set((baseline.get("files") or {}).keys())
        added = sorted(cur - old, key=str.lower)
        missing = sorted(old - cur, key=str.lower)
        return {
            "available": True,
            "v090_file_count": len(old),
            "current_file_count": len(cur),
            "path_additions_since_v090": len(added),
            "path_missing_since_v090": len(missing),
            "added_sample": added[:80],
            "missing_sample": missing[:80],
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}:{exc}"}


def _prior_v095_failure(root: pathlib.Path) -> dict[str, Any]:
    p = root / "pt_build" / "official_container_entry_recovery_v0950.json"
    if not p.is_file():
        return {"available": False, "understood": False}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        err = str(d.get("error") or "")
        return {
            "available": True,
            "understood": d.get("status") == "FAIL" and "SUMMIT_CLIENT_CHANGED_DURING_READ_ONLY_ENTRY_RECOVERY" in err,
            "status": d.get("status"),
            "error": err,
        }
    except Exception as exc:
        return {"available": True, "understood": False, "error": f"{type(exc).__name__}:{exc}"}

def _all_header_offsets(mm: mmap.mmap) -> list[int]:
    out: list[int] = []
    pos = 0
    while True:
        pos = mm.find(MODEL_HEADER, pos)
        if pos < 0:
            break
        out.append(pos)
        pos += 1
    return out


def _i32(mm: mmap.mmap, off: int) -> int:
    return struct.unpack_from("<i", mm, off)[0]


def _infer_model062_length(mm: mmap.mmap, base: int) -> tuple[int | None, str | None]:
    """Infer exact standalone Model0.62 length from its own serialized object table.

    This is deliberately strict.  We do not guess a trailing size from neighboring
    records.  Every object table entry must resolve inside the same candidate blob,
    and material/object offsets must be internally ordered.
    """
    n = len(mm)
    if base < 0 or base + SH > n or mm[base:base + len(MODEL_HEADER)] != MODEL_HEADER:
        return None, "HEADER_MISMATCH"
    try:
        obj_count = _i32(mm, base + 24)
        mat_count = _i32(mm, base + 28)
        mat_file = _i32(mm, base + 32)
        first_obj = _i32(mm, base + 36)
    except Exception:
        return None, "HEADER_TRUNCATED"
    if not (1 <= obj_count <= 1024):
        return None, f"OBJECT_COUNT_INVALID:{obj_count}"
    if mat_count < 0 or mat_count > 4096:
        return None, f"MATERIAL_COUNT_INVALID:{mat_count}"
    info_end = SH + obj_count * SI
    if base + info_end > n:
        return None, "OBJECT_INFO_TABLE_TRUNCATED"
    if not (SH <= mat_file <= first_obj):
        return None, f"MATERIAL_OFFSETS_INVALID:{mat_file}:{first_obj}"
    max_end = first_obj
    starts: list[int] = []
    for i in range(obj_count):
        io = base + SH + i * SI
        try:
            length = _i32(mm, io + 32)
            start = _i32(mm, io + 36)
        except Exception:
            return None, f"OBJECT_INFO_TRUNCATED:{i}"
        if length < SO:
            return None, f"OBJECT_LENGTH_INVALID:{i}:{length}"
        if start < first_obj:
            return None, f"OBJECT_START_BEFORE_FIRST:{i}:{start}:{first_obj}"
        end = start + length
        if end <= start or base + end > n:
            return None, f"OBJECT_BOUNDS_INVALID:{i}:{start}:{length}"
        starts.append(start)
        max_end = max(max_end, end)
    if not starts or min(starts) != first_obj:
        return None, f"FIRST_OBJECT_MISMATCH:{min(starts) if starts else None}:{first_obj}"
    if max_end <= first_obj:
        return None, "EMPTY_OBJECT_REGION"
    return int(max_end), None




def _canonical_character_ref(ref: str) -> str:
    s = _normalize(ref).replace("\\", "/").lstrip("/")
    lo = s.lower()
    for marker in ("char/", "character/", "player/"):
        i = lo.find(marker)
        if i >= 0:
            return s[i:]
    return s

def _safe_rel_from_ref(ref: str) -> pathlib.PurePosixPath:
    s = _normalize(ref).replace("\\", "/").lstrip("/")
    parts = [x for x in pathlib.PurePosixPath(s).parts if x not in ("", ".", "..")]
    if not parts:
        raise ValueError("EMPTY_REF_PATH")
    return pathlib.PurePosixPath(*parts)


def _validate_carved(path: pathlib.Path, ext: str) -> tuple[bool, str, dict[str, Any]]:
    meta: dict[str, Any] = {}
    try:
        probe = physical_probe(path, path.name)
        meta["physical_family"] = probe.get("physical_family")
        if probe.get("physical_family") != "SMD_MODEL_062":
            return False, f"PHYSICAL_FAMILY:{probe.get('physical_family')}", meta
        if ext == ".smb":
            bones = _parse_skeleton_tms(path)
            meta["skeleton_bone_count"] = len(bones)
            return True, "SMB_SKELETON_PARSE_PASS", meta
        parsed = parse_model062_physique_context(path)
        meta["object_count"] = int(parsed.get("object_count") or 0)
        meta["bind_bone_count"] = int(parsed.get("bind_bone_count") or 0)
        meta["physique_mode"] = parsed.get("physique_mode")
        if meta["bind_bone_count"] < 1:
            return False, "SMD_NO_PHYSIQUE_BIND_BONES", meta
        return True, "SMD_RIGID_PHYSIQUE_PARSE_PASS", meta
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}", meta


def _prefix_family_key(ref: str) -> str:
    p = pathlib.PurePosixPath(_normalize(ref))
    stem = p.stem
    # Keep a conservative lexical family. No runtime role is claimed.
    prefix = ""
    for ch in stem:
        if ch.isalpha() or ch in "_-":
            prefix += ch
        else:
            break
    return prefix.lower() or stem.lower()


def _neighborhood(rows: list[dict[str, Any]], idx: int) -> list[dict[str, Any]]:
    center = int(rows[idx]["first_offset"])
    out = []
    lo = max(0, idx - 20)
    hi = min(len(rows), idx + 21)
    for j in range(lo, hi):
        r = rows[j]
        delta = int(r["first_offset"]) - center
        if abs(delta) <= NEIGHBORHOOD_RADIUS:
            out.append({
                "delta": delta,
                "ref": r["ref"],
                "encoding": r["encoding"],
                "extension": r.get("extension"),
                "signal": r.get("signal"),
                "summit_overlap": r.get("summit_overlap"),
            })
    return out


def _scan_one_container(
    donor_name: str,
    donor_root: pathlib.Path,
    path: pathlib.Path,
    summit_idx: dict[str, Any],
    recovery_root: pathlib.Path,
) -> dict[str, Any]:
    rel = path.relative_to(donor_root).as_posix()
    raw_refs = _scan_refs(path)
    rows = []
    for rr in raw_refs:
        ext = pathlib.PurePosixPath(rr["ref"]).suffix.lower()
        if ext not in ASSET_EXTS:
            continue
        r = _ref_record(rr, summit_idx)
        r["raw_ref"] = r["ref"]
        r["canonical_ref"] = _canonical_character_ref(r["ref"])
        r["container"] = rel
        rows.append(r)
    rows.sort(key=lambda r: (int(r["first_offset"]), r["ref"].lower()))
    target_indices = [
        i for i, r in enumerate(rows)
        if r.get("signal") == "STRONG_CHARACTER_PATH"
        and r.get("summit_overlap") == "DONOR_REFERENCE_ONLY"
        and ("/" + str(r.get("canonical_ref") or "").lower().lstrip("/")).startswith("/" + TARGET_PREFIX)
        and r.get("extension") in MODEL_CONFIG_EXTS
    ]
    target_rows = []
    recovered = []
    header_count = 0
    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            headers = _all_header_offsets(mm)
            header_count = len(headers)
            model_ref_indices = [
                i for i, r in enumerate(rows)
                if r.get("extension") in {".smd", ".smb"}
            ]
            model_ref_offsets = [int(rows[i]["first_offset"]) for i in model_ref_indices]
            for i in target_indices:
                r = rows[i]
                rec = {
                    "container": rel,
                    "ref": r["canonical_ref"],
                    "raw_ref": r["raw_ref"],
                    "first_offset": int(r["first_offset"]),
                    "extension": r["extension"],
                    "family_key": _prefix_family_key(r["canonical_ref"]),
                    "summit_overlap": r["summit_overlap"],
                    "neighborhood": _neighborhood(rows, i),
                    "raw_carve_attempted": False,
                    "raw_carve_status": "NOT_MODEL_CONTAINER_ENTRY",
                }
                ext = r["extension"]
                if ext in {".smd", ".smb"}:
                    rec["raw_carve_attempted"] = True
                    roff = int(r["first_offset"])
                    hidx = bisect.bisect_right(headers, roff)
                    if hidx >= len(headers):
                        rec["raw_carve_status"] = "NO_MODEL_HEADER_AFTER_REFERENCE"
                    else:
                        hoff = headers[hidx]
                        gap = hoff - roff
                        rec["candidate_header_offset"] = hoff
                        rec["reference_to_header_gap"] = gap
                        if gap <= 0 or gap > MAX_PAIR_GAP:
                            rec["raw_carve_status"] = "HEADER_NOT_ADJACENT"
                        else:
                            # Require this ref to be the nearest preceding model ref.
                            mpos = bisect.bisect_right(model_ref_offsets, hoff) - 1
                            nearest_idx = model_ref_indices[mpos] if mpos >= 0 else None
                            if nearest_idx != i:
                                rec["raw_carve_status"] = "NOT_NEAREST_PRECEDING_MODEL_REF"
                            else:
                                length, err = _infer_model062_length(mm, hoff)
                                if length is None:
                                    rec["raw_carve_status"] = "STRUCTURAL_LENGTH_FAIL"
                                    rec["raw_carve_error"] = err
                                else:
                                    rec["candidate_model_length"] = length
                                    out_rel = _safe_rel_from_ref(r["canonical_ref"])
                                    out_path = recovery_root / donor_name / pathlib.Path(*out_rel.parts)
                                    out_path.parent.mkdir(parents=True, exist_ok=True)
                                    blob = mm[hoff:hoff + length]
                                    tmp = out_path.with_name(out_path.stem + ".candidate" + out_path.suffix)
                                    tmp.write_bytes(blob)
                                    ok, why, meta = _validate_carved(tmp, ext)
                                    rec["raw_carve_validation"] = why
                                    rec["raw_carve_validation_meta"] = meta
                                    if ok:
                                        tmp.replace(out_path)
                                        rec["raw_carve_status"] = "RECOVERED_STRICT"
                                        rec["recovered_path"] = str(out_path)
                                        rec["recovered_sha256"] = _sha(out_path)
                                        rec["recovered_size"] = out_path.stat().st_size
                                        recovered.append(rec)
                                    else:
                                        tmp.unlink(missing_ok=True)
                                        rec["raw_carve_status"] = "STRICT_VALIDATION_FAIL"
                target_rows.append(rec)
        finally:
            mm.close()
    return {
        "relative_path": rel,
        "size": path.stat().st_size,
        "sha256": _sha(path),
        "reference_count": len(rows),
        "model_header_count": header_count,
        "target_tmabcd_model_config_count": len(target_rows),
        "strict_recovered_count": len(recovered),
        "target_rows": target_rows,
    }


def _scan_donor(
    name: str,
    root: pathlib.Path,
    summit_idx: dict[str, Any],
    recovery_root: pathlib.Path,
) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    before = _snapshot(root)
    containers = []
    errors = []
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if not p.is_file() or not _is_container(p):
            continue
        try:
            containers.append(_scan_one_container(name, root, p, summit_idx, recovery_root))
        except Exception as exc:
            errors.append({"relative_path": p.relative_to(root).as_posix(), "error": f"{type(exc).__name__}:{exc}"})
    after = _snapshot(root)
    rows = [r for c in containers for r in c["target_rows"]]
    recovered = [r for r in rows if r.get("raw_carve_status") == "RECOVERED_STRICT"]
    ext_counts = collections.Counter(r["extension"] for r in rows)
    family_counts = collections.Counter(r["family_key"] for r in rows if r["extension"] in MODEL_CONFIG_EXTS)
    model_names = sorted({pathlib.PurePosixPath(r["ref"]).name for r in rows if r["extension"] == ".smd"}, key=str.lower)
    config_names = sorted({pathlib.PurePosixPath(r["ref"]).name for r in rows if r["extension"] in {".inx", ".inf", ".smb"}}, key=str.lower)
    return {
        "name": name,
        "root": str(root),
        "read_only": before == after,
        "container_count": len(containers),
        "scan_errors": errors,
        "tmabcd_donor_only_model_config_count": len(rows),
        "tmabcd_extension_counts": dict(ext_counts),
        "tmabcd_family_key_counts_top": dict(family_counts.most_common(50)),
        "tmabcd_donor_only_smd_names": model_names,
        "tmabcd_donor_only_config_names": config_names,
        "strict_recovered_count": len(recovered),
        "strict_recovered": recovered,
        "containers": containers,
    }


def _write_csv(path: pathlib.Path, donors: list[dict[str, Any]]) -> None:
    fields = [
        "donor", "container", "ref", "first_offset", "extension", "family_key",
        "raw_carve_status", "candidate_header_offset", "reference_to_header_gap",
        "candidate_model_length", "recovered_path", "recovered_sha256", "recovered_size",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for d in donors:
            for c in d["containers"]:
                for r in c["target_rows"]:
                    row = {k: r.get(k, "") for k in fields}
                    row["donor"] = d["name"]
                    w.writerow(row)


def _dedupe_cross_donor(donors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ref: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for d in donors:
        for r in d["strict_recovered"]:
            by_ref[str(r["ref"]).lower()].append({"donor": d["name"], **r})
    out = []
    for ref, rows in sorted(by_ref.items()):
        hashes = sorted({r.get("recovered_sha256") for r in rows if r.get("recovered_sha256")})
        out.append({
            "ref": rows[0]["ref"],
            "donor_count": len(rows),
            "hashes": hashes,
            "byte_identical_across_donors": len(rows) >= 2 and len(hashes) == 1,
            "rows": rows,
        })
    return out


def run(root: pathlib.Path, output: pathlib.Path, donor_specs: list[str]) -> dict[str, Any]:
    root = root.resolve()
    settings = Settings.discover(root)
    prior = _strict_prior(root)
    guards_before = _guard_snapshot(root)
    if not all(x["pass"] for x in guards_before["writers"].values()):
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    # V0.9.6 accepts the intentionally enriched corpus as it exists before this
    # audit.  It captures content hashes once, then distinguishes metadata-only
    # churn from actual byte/path changes during the read-only recovery window.
    client_baseline = _content_baseline(settings.client_root)
    corpus_delta_from_v090 = _compare_v090_paths(root, client_baseline)
    prior_v095 = _prior_v095_failure(root)
    baseline_path = root / "pt_build" / "summit_client_content_baseline_v0960.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_doc = {
        "format": "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1",
        "status": "CAPTURED_PRE_RECOVERY",
        "release_version": RELEASE,
        "client_root": str(settings.client_root),
        "file_count": client_baseline["file_count"],
        "total_bytes": client_baseline["total_bytes"],
        "content_tree_sha256": client_baseline["content_tree_sha256"],
        "files": client_baseline["files"],
    }
    baseline_path.write_text(json.dumps(baseline_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summit_idx = _build_summit_index(settings.client_root)
    recovery_root = root / "pt_build" / "official_container_entry_recovery_v0960"
    if recovery_root.exists():
        shutil.rmtree(recovery_root)
    recovery_root.mkdir(parents=True, exist_ok=True)

    donors = []
    for spec in donor_specs:
        name, droot = _parse_donor_spec(spec)
        donors.append(_scan_donor(name, droot, summit_idx, recovery_root))

    guards_after = _guard_snapshot(root)
    client_window = _verify_content_baseline(settings.client_root, client_baseline)
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_READ_ONLY_ENTRY_RECOVERY")
    if not client_window["pass"]:
        detail = {
            "added": client_window["added_during_audit"][:20],
            "deleted": client_window["deleted_during_audit"][:20],
            "content_changed": client_window["content_changed_during_audit"][:20],
        }
        raise RuntimeError("SUMMIT_CLIENT_CONTENT_CHANGED_DURING_READ_ONLY_ENTRY_RECOVERY:" + json.dumps(detail, ensure_ascii=False, separators=(",", ":")))
    if not all(d["read_only"] for d in donors):
        raise RuntimeError("DONOR_CHANGED_DURING_READ_ONLY_ENTRY_RECOVERY")
    baseline_doc["status"] = "PASS_READ_ONLY_WINDOW"
    baseline_doc["read_only_window_verification"] = client_window
    baseline_path.write_text(json.dumps(baseline_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total_targets = sum(d["tmabcd_donor_only_model_config_count"] for d in donors)
    total_recovered = sum(d["strict_recovered_count"] for d in donors)
    cross = _dedupe_cross_donor(donors)
    cross_identical = sum(1 for x in cross if x["byte_identical_across_donors"])
    smd_union = sorted({n for d in donors for n in d["tmabcd_donor_only_smd_names"]}, key=str.lower)
    cfg_union = sorted({n for d in donors for n in d["tmabcd_donor_only_config_names"]}, key=str.lower)

    output.parent.mkdir(parents=True, exist_ok=True)
    csvp = output.with_suffix(".csv")
    mdp = output.with_suffix(".md")
    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "client_and_donors_read_only": True,
        "prior_v094_strict_pass": True,
        "prior_v095_failure": prior_v095,
        "client_corpus_rebaselined_to_current_state": True,
        "client_content_baseline": {
            "path": str(baseline_path),
            "file_count": client_baseline["file_count"],
            "total_bytes": client_baseline["total_bytes"],
            "content_tree_sha256": client_baseline["content_tree_sha256"],
        },
        "corpus_delta_from_v090": corpus_delta_from_v090,
        "client_read_only_window": client_window,
        "prior_v094_strong_character_reference_count": int((prior.get("summary") or {}).get("strong_character_reference_count") or 0),
        "target_prefix": "char/tmABCD",
        "donors": donors,
        "summary": {
            "tmabcd_donor_only_model_config_count": total_targets,
            "tmabcd_unique_donor_only_smd_name_count": len(smd_union),
            "tmabcd_unique_donor_only_config_name_count": len(cfg_union),
            "strict_raw_recovered_count": total_recovered,
            "cross_donor_recovered_ref_count": len(cross),
            "cross_donor_byte_identical_count": cross_identical,
            "tmabcd_donor_only_smd_names": smd_union[:500],
            "tmabcd_donor_only_config_names": cfg_union[:500],
        },
        "cross_donor_recovery": cross,
        "decision": {
            "transplant_write_authorized": False,
            "new_class_claimed": False,
            "recovered_files_are_read_only_donor_copies_in_pt_build_only": True,
            "next_on_pass": (
                "if strict raw Model0.62 recovery exists, identify body/head family by INX/SMB/reference neighborhoods and open recovered candidate in Blender; "
                "otherwise use recorded container offsets/neighborhoods to recover the package record index/offset-size structure before any extraction claim"
            ),
        },
        "guards": {
            "certified_writer_hashes_valid": True,
            "writer_modules_modified": False,
            "production_policies_modified": False,
            "policy_sha256": guards_after["policies"],
        },
        "outputs": {
            "json": str(output),
            "csv": str(csvp),
            "markdown": str(mdp),
            "recovery_root": str(recovery_root),
            "client_content_baseline": str(baseline_path),
        },
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csvp, donors)
    lines = [
        "# Official Container Entry Recovery V0.9.6",
        "",
        "Read-only physical recovery attempt focused on donor-only `char/tmABCD` model/config references, with a content-hash baseline of the enriched Summit corpus.",
        "No donor or Summit file is modified; any strictly validated carved copies are written only under `pt_build`.",
        "",
        f"- Summit current corpus files: {client_baseline['file_count']}",
        f"- Summit content-tree SHA-256: {client_baseline['content_tree_sha256']}",
        f"- Metadata-only changes during audit: {len(client_window['metadata_only_changes'])}",
        f"- Target model/config refs: {total_targets}",
        f"- Unique donor-only SMD names: {len(smd_union)}",
        f"- Strict raw recovered Model0.62 entries: {total_recovered}",
        f"- Byte-identical recovered across both donors: {cross_identical}",
        "",
        "## First donor-only SMD names",
    ] + [f"- {x}" for x in smd_union[:100]]
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
            "format": r["format"],
            "status": r["status"],
            "release_version": r["release_version"],
            "client_and_donors_read_only": r["client_and_donors_read_only"],
            "prior_v094_strict_pass": r["prior_v094_strict_pass"],
            "prior_v095_failure": r["prior_v095_failure"],
            "client_corpus_rebaselined_to_current_state": r["client_corpus_rebaselined_to_current_state"],
            "client_content_baseline": r["client_content_baseline"],
            "corpus_delta_from_v090": r["corpus_delta_from_v090"],
            "client_read_only_window": r["client_read_only_window"],
            "target_prefix": r["target_prefix"],
            "donors": [
                {
                    "name": d["name"],
                    "read_only": d["read_only"],
                    "container_count": d["container_count"],
                    "tmabcd_donor_only_model_config_count": d["tmabcd_donor_only_model_config_count"],
                    "tmabcd_extension_counts": d["tmabcd_extension_counts"],
                    "tmabcd_family_key_counts_top": d["tmabcd_family_key_counts_top"],
                    "strict_recovered_count": d["strict_recovered_count"],
                    "tmabcd_donor_only_smd_names": d["tmabcd_donor_only_smd_names"][:80],
                    "tmabcd_donor_only_config_names": d["tmabcd_donor_only_config_names"][:80],
                    "scan_errors": d["scan_errors"],
                }
                for d in r["donors"]
            ],
            "summary": r["summary"],
            "decision": r["decision"],
            "guards": r["guards"],
            "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(
            "official_container_entry_recovery=PASS "
            f"targets={r['summary']['tmabcd_donor_only_model_config_count']} "
            f"recovered={r['summary']['strict_raw_recovered_count']} read_only=true"
        )
        return 0
    except Exception as exc:
        fail = {
            "format": FORMAT,
            "status": "FAIL",
            "release_version": RELEASE,
            "error": f"{type(exc).__name__}:{exc}",
            "client_and_donors_read_only": True,
            "transplant_write_authorized": False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
