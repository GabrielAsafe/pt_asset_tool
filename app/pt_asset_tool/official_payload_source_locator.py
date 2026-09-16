from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mmap
import os
import pathlib
import re
import tarfile
import zipfile
from typing import Any

from .config import Settings
from .official_character_donor_census import _parse_donor_spec
from .official_container_character_atlas import _guard_snapshot
from .official_container_entry_recovery import _verify_content_baseline
from .official_container_record_index import _lha_entries

FORMAT = "PT_OFFICIAL_PAYLOAD_SOURCE_LOCATOR_V1"
RELEASE = "0.10.0"
PRIOR_FORMAT = "PT_OFFICIAL_UPDATE_MANIFEST_PACK_CORRELATION_V1"
MODEL062 = b"SMD Model data Ver 0.62"
TARGET_PREFIXES = ("tfbf", "tfhf", "ctfbf", "6tfbf")
ARCHIVE_SUFFIXES = {".upw", ".zip", ".lha", ".lzh", ".rar", ".7z", ".cab", ".pak", ".pkg", ".gz", ".tgz", ".tar"}
UPDATER_NAMES = {"zupdate.exe", "game.exe", "update.exe", "updater.exe", "patcher.exe", "launcher.exe"}
URL_RE = re.compile(rb"https?://[^\x00-\x20\x7f\"'<>]{4,300}", re.I)
UPW_RE = re.compile(rb"[A-Za-z0-9_./\\-]{1,220}\.upw", re.I)
HOST_RE = re.compile(rb"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?::\d{2,5})?", re.I)


def _sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _strict_prior(root: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rp = root / "pt_build" / "official_update_manifest_pack_correlation_v0990.json"
    bp = root / "pt_build" / "summit_client_content_baseline_v0960.json"
    if not rp.is_file():
        raise FileNotFoundError(f"V0990_REPORT_MISSING:{rp}")
    if not bp.is_file():
        raise FileNotFoundError(f"V0960_BASELINE_MISSING:{bp}")
    d = json.loads(rp.read_text(encoding="utf-8"))
    if d.get("format") != PRIOR_FORMAT or d.get("status") != "PASS" or d.get("release_version") != "0.9.9":
        raise RuntimeError("V0990_STRICT_REPORT_MISMATCH")
    s = d.get("summary") or {}
    if not s.get("tff_is_manifested_in_official_donors"):
        raise RuntimeError("V0990_TFF_NOT_MANIFESTED")
    if s.get("local_payload_evidence_any"):
        raise RuntimeError("V0990_LOCAL_PAYLOAD_ALREADY_FOUND_USE_EXTRACTION_PATH")
    g = d.get("guards") or {}
    if not g.get("certified_writer_hashes_valid") or g.get("writer_modules_modified") or g.get("production_policies_modified"):
        raise RuntimeError("V0990_GUARD_STATE_INVALID")
    b = json.loads(bp.read_text(encoding="utf-8"))
    if b.get("format") != "PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1" or b.get("status") != "PASS_READ_ONLY_WINDOW":
        raise RuntimeError("V0960_CONTENT_BASELINE_INVALID")
    return d, b


def _target_names(prior: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for d in prior.get("donors") or []:
        for ref in d.get("tff_manifest_reference_sample") or []:
            base = pathlib.PurePosixPath(str(ref).replace("\\", "/")).name.lower()
            if base:
                names.add(base)
    # The compact V0.9.9 report may not store every reference. Pull stable family seeds.
    for i in range(1, 41):
        names.add(f"tfbf{i:02d}.smd")
        names.add(f"tfhf{i:02d}.smd")
    names.update({"tfbf01.smb", "tfh-f01.inx", "tfh-f01.inf"})
    return names


def _is_tff_name(name: str) -> bool:
    lo = name.lower()
    return lo.endswith((".smd", ".smb", ".inx", ".inf")) and lo.startswith(TARGET_PREFIXES)


def _iter_files(root: pathlib.Path):
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _classify_loose_hit(p: pathlib.Path, search_root: pathlib.Path) -> dict[str, Any]:
    data_head = b""
    try:
        with p.open("rb") as f:
            data_head = f.read(64)
    except OSError:
        pass
    return {
        "search_root": str(search_root),
        "path": str(p),
        "relative_path": p.relative_to(search_root).as_posix(),
        "basename": p.name,
        "size": p.stat().st_size,
        "sha256": _sha(p),
        "model062_header": data_head.startswith(MODEL062),
        "extension": p.suffix.lower(),
    }


def _scan_zip(p: pathlib.Path, target_names: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    hits: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                base = pathlib.PurePosixPath(info.filename.replace("\\", "/")).name.lower()
                if base in target_names or _is_tff_name(base):
                    hits.append({"member": info.filename, "size": info.file_size, "compressed_size": info.compress_size, "kind": "ZIP_MEMBER"})
    except Exception as exc:
        errors.append(f"ZIP:{type(exc).__name__}:{exc}")
    return hits, errors


def _scan_tar(p: pathlib.Path, target_names: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    hits: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        if tarfile.is_tarfile(p):
            with tarfile.open(p, "r:*") as t:
                for m in t.getmembers():
                    base = pathlib.PurePosixPath(m.name.replace("\\", "/")).name.lower()
                    if base in target_names or _is_tff_name(base):
                        hits.append({"member": m.name, "size": m.size, "kind": "TAR_MEMBER"})
    except Exception as exc:
        errors.append(f"TAR:{type(exc).__name__}:{exc}")
    return hits, errors


def _scan_binary_archive(p: pathlib.Path, target_names: set[str], max_name_hits: int = 200) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": str(p), "size": p.stat().st_size, "sha256": _sha(p),
        "extension": p.suffix.lower(), "target_name_hits": [], "model062_magic_count": 0,
        "strict_lha_record_count": 0, "archive_member_hits": [], "scan_errors": [],
    }
    # Detect by structure, not filename suffix: updater payloads may use custom extensions.
    try:
        is_zip = zipfile.is_zipfile(p)
    except Exception:
        is_zip = False
    if is_zip:
        h, e = _scan_zip(p, target_names); row["archive_member_hits"].extend(h); row["scan_errors"].extend(e)
    else:
        h, e = _scan_tar(p, target_names); row["archive_member_hits"].extend(h); row["scan_errors"].extend(e)
    # Raw string/magic/LHA scan. mmap avoids loading large archives.
    try:
        with p.open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                pos = 0
                while True:
                    pos = mm.find(MODEL062, pos)
                    if pos < 0: break
                    row["model062_magic_count"] += 1; pos += len(MODEL062)
                    if row["model062_magic_count"] >= 10000: break
                # Only search names we actually care about.
                for name in sorted(target_names):
                    if len(row["target_name_hits"]) >= max_name_hits: break
                    b = name.encode("ascii", "ignore")
                    pos = mm.find(b)
                    if pos >= 0:
                        row["target_name_hits"].append({"name": name, "offset": int(pos)})
                row["strict_lha_record_count"] = len(_lha_entries(mm))
            finally:
                mm.close()
    except Exception as exc:
        row["scan_errors"].append(f"RAW:{type(exc).__name__}:{exc}")
    return row


def _extract_ascii_candidates(p: pathlib.Path) -> dict[str, Any]:
    urls: set[str] = set(); upw: set[str] = set(); hosts: set[str] = set()
    try:
        data = p.read_bytes()
    except Exception as exc:
        return {"path": str(p), "urls": [], "upw_refs": [], "hosts": [], "error": f"{type(exc).__name__}:{exc}"}
    for rx, dst in ((URL_RE, urls), (UPW_RE, upw), (HOST_RE, hosts)):
        for m in rx.finditer(data):
            try:
                s = m.group(0).decode("latin-1", "replace").strip("\x00")
            except Exception:
                continue
            if len(s) <= 300:
                dst.add(s)
    # Filter host noise by requiring update-ish context where possible.
    useful_hosts = [h for h in hosts if any(k in h.lower() for k in ("priston", "patch", "update", "game", "server", "pt"))]
    return {"path": str(p), "sha256": _sha(p), "urls": sorted(urls)[:100], "upw_refs": sorted(upw)[:200], "hosts": sorted(useful_hosts)[:100]}


def _default_search_roots() -> list[pathlib.Path]:
    # The configured current client is appended inside run().  Additional
    # search roots are explicit external evidence and are never guessed from a
    # developer home directory.
    return []


def _dedupe_roots(roots: list[pathlib.Path]) -> list[pathlib.Path]:
    existing = []
    for r in roots:
        if r.is_dir():
            try: existing.append(r.resolve())
            except Exception: existing.append(r)
    # Broader roots first; nested roots then disappear deterministically.
    existing = sorted(set(existing), key=lambda x: (len(x.parts), str(x)))
    out: list[pathlib.Path] = []
    for r in existing:
        rs = str(r)
        if any(rs == str(x) or rs.startswith(str(x) + os.sep) for x in out):
            continue
        out.append(r)
    return out


def _scan_search_root(root: pathlib.Path, target_names: set[str]) -> dict[str, Any]:
    before = _snapshot(root)
    loose: list[dict[str, Any]] = []
    archives: list[pathlib.Path] = []
    updater_bins: list[pathlib.Path] = []
    file_count = 0
    for p in _iter_files(root) or []:
        file_count += 1
        lo = p.name.lower()
        if lo in target_names or _is_tff_name(lo):
            loose.append(_classify_loose_hit(p, root))
        if p.suffix.lower() in ARCHIVE_SUFFIXES or lo.endswith(".upw") or any(k in lo for k in ("patch", "update")) and p.stat().st_size > 32:
            archives.append(p)
        if lo in UPDATER_NAMES:
            updater_bins.append(p)
    # Cap archive raw scans by prioritizing upw/lha/zip, then update-ish names, then size.
    archives = sorted(set(archives), key=lambda p: (0 if p.suffix.lower() == ".upw" else 1 if p.suffix.lower() in {".lha", ".lzh", ".zip"} else 2, 0 if any(k in p.name.lower() for k in ("patch", "update")) else 1, p.stat().st_size, str(p)))[:300]
    archive_rows = [_scan_binary_archive(p, target_names) for p in archives]
    updater_rows = [_extract_ascii_candidates(p) for p in sorted(set(updater_bins))]
    after = _snapshot(root)
    return {
        "root": str(root), "read_only": before == after, "file_count": file_count,
        "exact_loose_target_hits": loose,
        "archive_candidate_count_scanned": len(archive_rows),
        "archive_candidates": archive_rows,
        "updater_binary_count": len(updater_rows),
        "updater_string_evidence": updater_rows,
    }


def _write_csv(path: pathlib.Path, scans: list[dict[str, Any]]) -> None:
    fields = ["search_root", "kind", "path", "basename_or_member", "size", "sha256_or_offset"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for s in scans:
            for h in s["exact_loose_target_hits"]:
                w.writerow({"search_root": s["root"], "kind": "LOOSE", "path": h["path"], "basename_or_member": h["basename"], "size": h["size"], "sha256_or_offset": h["sha256"]})
            for a in s["archive_candidates"]:
                for m in a["archive_member_hits"]:
                    w.writerow({"search_root": s["root"], "kind": m["kind"], "path": a["path"], "basename_or_member": m["member"], "size": m.get("size"), "sha256_or_offset": a["sha256"]})
                for n in a["target_name_hits"]:
                    w.writerow({"search_root": s["root"], "kind": "RAW_NAME", "path": a["path"], "basename_or_member": n["name"], "size": a["size"], "sha256_or_offset": n["offset"]})


def run(root: pathlib.Path, output: pathlib.Path, donor_specs: list[str], search_roots: list[pathlib.Path]) -> dict[str, Any]:
    root = root.resolve(); settings = Settings.discover(root)
    prior, baseline_doc = _strict_prior(root)
    guards_before = _guard_snapshot(root)
    if not all(x["pass"] for x in guards_before["writers"].values()): raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    baseline = {"files": baseline_doc.get("files") or {}}
    cb = _verify_content_baseline(settings.client_root, baseline)
    if not cb["pass"]: raise RuntimeError("SUMMIT_CORPUS_NO_LONGER_MATCHES_V0960_BASELINE")

    donor_snapshots = []
    for spec in donor_specs:
        n, dr = _parse_donor_spec(spec); donor_snapshots.append((n, dr, _snapshot(dr)))

    targets = _target_names(prior)
    # Always include the current Summit client corpus as a filename-level source candidate.
    effective_roots = list(search_roots) + [settings.client_root]
    scans = [_scan_search_root(r, targets) for r in _dedupe_roots(effective_roots)]

    guards_after = _guard_snapshot(root); ca = _verify_content_baseline(settings.client_root, baseline)
    if guards_after != guards_before: raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_PAYLOAD_SOURCE_LOCATOR")
    if not ca["pass"]: raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_PAYLOAD_SOURCE_LOCATOR")
    for n, dr, snap in donor_snapshots:
        if _snapshot(dr) != snap: raise RuntimeError(f"DONOR_CHANGED_DURING_PAYLOAD_SOURCE_LOCATOR:{n}")
    if not all(s["read_only"] for s in scans): raise RuntimeError("SEARCH_ROOT_CHANGED_DURING_PAYLOAD_SOURCE_LOCATOR")

    loose_hits = [h for s in scans for h in s["exact_loose_target_hits"]]
    archive_member_hits = [(a, m) for s in scans for a in s["archive_candidates"] for m in a["archive_member_hits"]]
    raw_name_hits = [(a, n) for s in scans for a in s["archive_candidates"] for n in a["target_name_hits"]]
    strict_lha = sum(int(a["strict_lha_record_count"]) for s in scans for a in s["archive_candidates"])
    model_magic = sum(int(a["model062_magic_count"]) for s in scans for a in s["archive_candidates"])
    urls = sorted({u for s in scans for e in s["updater_string_evidence"] for u in e.get("urls", [])})
    upw_refs = sorted({u for s in scans for e in s["updater_string_evidence"] for u in e.get("upw_refs", [])})
    hosts = sorted({u for s in scans for e in s["updater_string_evidence"] for u in e.get("hosts", [])})

    if loose_hits:
        mode = "LOOSE_TFF_PAYLOAD_FOUND"
    elif archive_member_hits or (strict_lha and raw_name_hits):
        mode = "ARCHIVE_TFF_PAYLOAD_SOURCE_FOUND"
    elif raw_name_hits or upw_refs or urls:
        mode = "UPDATER_OR_ARCHIVE_SOURCE_EVIDENCE_FOUND"
    else:
        mode = "TFF_PAYLOAD_SOURCE_NOT_LOCALIZED"

    output.parent.mkdir(parents=True, exist_ok=True); csvp = output.with_suffix(".csv"); mdp = output.with_suffix(".md")
    report = {
        "format": FORMAT, "status": "PASS", "release_version": RELEASE,
        "client_donors_and_search_roots_read_only": True, "prior_v099_strict_pass": True,
        "research_target": "locate real TfF body/head payload bytes or updater source evidence",
        "target_name_count": len(targets), "search_roots": scans,
        "summary": {
            "search_root_count": len(scans), "exact_loose_target_hit_count": len(loose_hits),
            "archive_member_target_hit_count": len(archive_member_hits), "archive_raw_target_name_hit_count": len(raw_name_hits),
            "strict_lha_record_count": strict_lha, "model062_magic_count_in_archive_candidates": model_magic,
            "updater_url_candidate_count": len(urls), "upw_reference_count": len(upw_refs), "updater_host_candidate_count": len(hosts),
            "mode": mode,
        },
        "updater_source_evidence": {"urls": urls[:200], "upw_refs": upw_refs[:300], "hosts": hosts[:200]},
        "decision": {
            "transplant_write_authorized": False, "new_class_claimed": False,
            "payload_absence_claimed": False,
            "next_on_pass": {
                "LOOSE_TFF_PAYLOAD_FOUND": "physically parse first real TfbF/TfhF pair, bind SMB/INX, and open read-only Blender candidate",
                "ARCHIVE_TFF_PAYLOAD_SOURCE_FOUND": "build strict read-only archive extraction for one TfbF/TfhF pair",
                "UPDATER_OR_ARCHIVE_SOURCE_EVIDENCE_FOUND": "resolve updater/archive source path and acquire or identify the exact TfF payload artifact before extraction",
                "TFF_PAYLOAD_SOURCE_NOT_LOCALIZED": "use updater endpoint/cache evidence or add a fully expanded official client/update archive; do not spend another pass assuming cdata contains TfF",
            }[mode],
        },
        "guards": {"certified_writer_hashes_valid": True, "writer_modules_modified": False, "production_policies_modified": False, "policy_sha256": guards_after["policies"], "summit_matches_v0960_baseline_before": cb["pass"], "summit_matches_v0960_baseline_after": ca["pass"]},
        "outputs": {"json": str(output), "csv": str(csvp), "markdown": str(mdp)},
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csvp, scans)
    mdp.write_text("\n".join([
        "# Official TfF Payload Source Locator V0.10.0", "", f"- mode: {mode}", f"- loose TfF hits: {len(loose_hits)}",
        f"- archive member hits: {len(archive_member_hits)}", f"- raw target-name hits in archives: {len(raw_name_hits)}",
        f"- strict LHA records: {strict_lha}", f"- updater URL candidates: {len(urls)}", f"- .upw references: {len(upw_refs)}", "", "Read-only. No transplant authorization is added."
    ]) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--donor", action="append", required=True); ap.add_argument("--search-root", action="append")
    a = ap.parse_args(argv); out = pathlib.Path(a.output)
    roots = [pathlib.Path(x) for x in (a.search_root or [])] or _default_search_roots()
    try:
        r = run(pathlib.Path(a.root), out, list(a.donor), roots)
        compact = {
            "format": r["format"], "status": r["status"], "release_version": r["release_version"],
            "client_donors_and_search_roots_read_only": r["client_donors_and_search_roots_read_only"], "prior_v099_strict_pass": r["prior_v099_strict_pass"],
            "research_target": r["research_target"], "summary": r["summary"], "updater_source_evidence": r["updater_source_evidence"],
            "search_roots": [{"root": s["root"], "read_only": s["read_only"], "file_count": s["file_count"], "exact_loose_target_hits": s["exact_loose_target_hits"][:50], "archive_candidate_count_scanned": s["archive_candidate_count_scanned"], "archive_positive_samples": [a for a in s["archive_candidates"] if a["archive_member_hits"] or a["target_name_hits"] or a["strict_lha_record_count"] or a["model062_magic_count"]][:30], "updater_string_evidence": [e for e in s["updater_string_evidence"] if e.get("urls") or e.get("upw_refs") or e.get("hosts")][:20]} for s in r["search_roots"]],
            "decision": r["decision"], "guards": r["guards"], "outputs": r["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print(f"official_payload_source_locator=PASS mode={r['summary']['mode']} loose={r['summary']['exact_loose_target_hit_count']} archive_members={r['summary']['archive_member_target_hit_count']} upw_refs={r['summary']['upw_reference_count']} read_only=true")
        return 0
    except Exception as exc:
        fail = {"format": FORMAT, "status": "FAIL", "release_version": RELEASE, "error": f"{type(exc).__name__}:{exc}", "client_donors_and_search_roots_read_only": True, "transplant_write_authorized": False}
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(fail, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"); print(json.dumps(fail, ensure_ascii=False, indent=2)); return 2

if __name__ == "__main__":
    raise SystemExit(main())
