from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import pathlib
import re
from typing import Any

from .config import Settings
from .semantic_census import classify_semantic, physical_probe, CERTIFIED_WRITERS, POLICY_FILES
from .utils import sha256_file

FORMAT = "PT_OFFICIAL_CHARACTER_DONOR_CENSUS_V1"
RELEASE = "0.9.1"
DIRECT_ASSET_EXTS = {".smd", ".smb", ".inx", ".inf", ".bmp", ".tga", ".png", ".jpg", ".wav"}
CHAR_EXTS = {".smd", ".smb", ".inx", ".inf"}
REF_RE = re.compile(rb"[A-Za-z0-9_ .:/\\-]{2,220}\.(?:smd|smb|inx|inf|bmp|tga|png|jpg|wav)", re.I)
CONTAINER_RE = re.compile(r"^(?:[bcfl]data\d+|setfile\.lst)$", re.I)
CONTAINER_EXTS = {".pkg", ".gpk", ".cab", ".part"}


def _sha(path: pathlib.Path) -> str:
    return sha256_file(path)


def _snapshot_stats(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if p.is_file():
            try:
                st = p.stat()
                out[p.relative_to(root).as_posix()] = (int(st.st_size), int(st.st_mtime_ns))
            except OSError:
                pass
    return out


def _writer_policy_snapshot(root: pathlib.Path) -> dict[str, Any]:
    writers = {}
    for rel, expected in CERTIFIED_WRITERS.items():
        p = root / rel
        actual = _sha(p) if p.is_file() else None
        writers[rel] = {"expected": expected, "actual": actual, "pass": actual == expected}
    policies = {}
    for rel in POLICY_FILES:
        p = root / rel
        policies[rel] = _sha(p) if p.is_file() else None
    return {"writers": writers, "policies": policies}


def _parse_donor_spec(spec: str) -> tuple[str, pathlib.Path]:
    if "=" in spec:
        name, raw = spec.split("=", 1)
        name = name.strip()
        raw = raw.strip()
        if not name or not raw:
            raise ValueError(f"BAD_DONOR_SPEC:{spec}")
        return name, pathlib.Path(raw).expanduser().resolve()
    p = pathlib.Path(spec).expanduser().resolve()
    return p.name, p


def _is_scan_container(path: pathlib.Path) -> bool:
    return bool(CONTAINER_RE.match(path.name)) or path.suffix.lower() in CONTAINER_EXTS or path.suffix.lower() == ".exe"


def _extract_refs(path: pathlib.Path, max_unique: int = 20000) -> list[str]:
    refs: set[str] = set()
    overlap = b""
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(2 * 1024 * 1024)
                if not chunk:
                    break
                data = overlap + chunk
                for m in REF_RE.finditer(data):
                    raw = m.group(0).strip(b"\x00 \t\r\n")
                    try:
                        s = raw.decode("latin-1", errors="ignore")
                    except Exception:
                        continue
                    s = s.replace("\\", "/")
                    # Trim obvious leading junk while retaining drive/path text when present.
                    s = re.sub(r"^[^A-Za-z0-9]+", "", s)
                    if s:
                        refs.add(s)
                    if len(refs) >= max_unique:
                        return sorted(refs, key=str.lower)
                overlap = data[-512:]
    except OSError:
        return []
    return sorted(refs, key=str.lower)


def _characterish_ref(ref: str) -> bool:
    lo = ref.lower()
    ext = pathlib.PurePosixPath(lo).suffix
    return ext in CHAR_EXTS or "/char/" in ("/" + lo) or lo.startswith("char/")


def _scan_donor(name: str, root: pathlib.Path) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    before = _snapshot_stats(root)
    rows: list[dict[str, Any]] = []
    containers: list[dict[str, Any]] = []
    embedded_refs: set[str] = set()
    embedded_char_refs: set[str] = set()
    errors: list[dict[str, str]] = []

    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        ext = p.suffix.lower()
        try:
            st = p.stat()
            if ext in DIRECT_ASSET_EXTS:
                probe = physical_probe(p, rel)
                sem = classify_semantic(rel, ext, None)
                row = {
                    "relative_path": rel,
                    "extension": ext,
                    "size": int(st.st_size),
                    "sha256": _sha(p),
                    **probe,
                    "semantic_group": sem.semantic_group,
                    "semantic_role": sem.semantic_role,
                    "confidence": sem.confidence,
                    "evidence": sem.evidence,
                }
                rows.append(row)
            if _is_scan_container(p):
                refs = _extract_refs(p)
                embedded_refs.update(refs)
                embedded_char_refs.update(r for r in refs if _characterish_ref(r))
                containers.append({
                    "relative_path": rel,
                    "size": int(st.st_size),
                    "sha256": _sha(p),
                    "embedded_asset_ref_count": len(refs),
                    "embedded_character_ref_count": sum(1 for r in refs if _characterish_ref(r)),
                    "embedded_character_ref_sample": [r for r in refs if _characterish_ref(r)][:80],
                })
        except Exception as exc:
            errors.append({"relative_path": rel, "error": f"{type(exc).__name__}:{exc}"})

    after = _snapshot_stats(root)
    direct_char = [r for r in rows if r["extension"] in CHAR_EXTS or r["semantic_group"] in {"PLAYER", "MONSTER", "NPC"}]
    direct_models = [r for r in rows if r["extension"] == ".smd"]
    return {
        "name": name,
        "root": str(root),
        "read_only": before == after,
        "file_count": len(before),
        "scan_errors": errors,
        "direct_asset_count": len(rows),
        "direct_character_candidate_count": len(direct_char),
        "direct_smd_count": sum(1 for r in rows if r["extension"] == ".smd"),
        "direct_smb_count": sum(1 for r in rows if r["extension"] == ".smb"),
        "direct_inx_count": sum(1 for r in rows if r["extension"] == ".inx"),
        "direct_inf_count": sum(1 for r in rows if r["extension"] == ".inf"),
        "container_count": len(containers),
        "embedded_asset_ref_count": len(embedded_refs),
        "embedded_character_ref_count": len(embedded_char_refs),
        "embedded_character_refs": sorted(embedded_char_refs, key=str.lower),
        "direct_character_candidates": direct_char,
        "direct_models": direct_models,
        "containers": containers,
        "rows": rows,
    }


def _compare_donors(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    amap = {r["relative_path"].lower(): r for r in a["rows"]}
    bmap = {r["relative_path"].lower(): r for r in b["rows"]}
    common = sorted(set(amap) & set(bmap))
    same = []
    changed = []
    for k in common:
        ar, br = amap[k], bmap[k]
        rec = {"relative_path": ar["relative_path"], "old_sha256": ar["sha256"], "new_sha256": br["sha256"], "extension": ar["extension"]}
        if ar["sha256"] == br["sha256"]:
            same.append(rec)
        else:
            changed.append(rec)
    ac = {r["relative_path"].lower(): r for r in a["containers"]}
    bc = {r["relative_path"].lower(): r for r in b["containers"]}
    cchanged = []
    for k in sorted(set(ac) & set(bc)):
        if ac[k]["sha256"] != bc[k]["sha256"]:
            cchanged.append({"relative_path": ac[k]["relative_path"], "old_sha256": ac[k]["sha256"], "new_sha256": bc[k]["sha256"], "old_size": ac[k]["size"], "new_size": bc[k]["size"]})
    arefs = set(a["embedded_character_refs"])
    brefs = set(b["embedded_character_refs"])
    return {
        "direct_common_path_count": len(common),
        "direct_same_hash_count": len(same),
        "direct_changed_hash_count": len(changed),
        "direct_only_first_count": len(set(amap)-set(bmap)),
        "direct_only_second_count": len(set(bmap)-set(amap)),
        "direct_changed": changed[:500],
        "changed_containers": cchanged,
        "embedded_character_refs_common_count": len(arefs & brefs),
        "embedded_character_refs_only_first": sorted(arefs-brefs, key=str.lower)[:1000],
        "embedded_character_refs_only_second": sorted(brefs-arefs, key=str.lower)[:1000],
    }


def _summit_overlap(settings: Settings, donor: dict[str, Any]) -> dict[str, Any]:
    summit = settings.client_root
    if not summit.is_dir():
        return {"available": False, "reason": "SUMMIT_CLIENT_MISSING"}
    exact_path = []
    basename_index: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    # Build only for character/config extensions to keep this audit targeted.
    for p in summit.rglob("*"):
        if p.is_file() and p.suffix.lower() in CHAR_EXTS:
            basename_index[p.name.lower()].append(p)
    basename_hits = []
    for r in donor["direct_character_candidates"]:
        rel = r["relative_path"]
        q = summit / rel
        if q.is_file():
            try:
                exact_path.append({
                    "donor_relative_path": rel,
                    "summit_relative_path": rel,
                    "same_sha256": _sha(q) == r["sha256"],
                    "summit_sha256": _sha(q),
                    "donor_sha256": r["sha256"],
                })
            except OSError:
                pass
        hits = basename_index.get(pathlib.PurePosixPath(rel).name.lower(), [])
        if hits:
            basename_hits.append({
                "donor_relative_path": rel,
                "summit_candidates": [p.relative_to(summit).as_posix() for p in hits[:30]],
                "candidate_count": len(hits),
            })
    refs = donor["embedded_character_refs"]
    ref_basenames = collections.Counter(pathlib.PurePosixPath(x).name.lower() for x in refs)
    embedded_name_hits = []
    for base, n in ref_basenames.items():
        hits = basename_index.get(base, [])
        if hits:
            embedded_name_hits.append({"basename": base, "donor_ref_count": n, "summit_candidates": [p.relative_to(summit).as_posix() for p in hits[:30]], "candidate_count": len(hits)})
    embedded_name_hits.sort(key=lambda x: (-x["donor_ref_count"], x["basename"]))
    return {
        "available": True,
        "summit_root": str(summit),
        "exact_relative_path_hits": exact_path,
        "direct_basename_hits": basename_hits,
        "embedded_character_basename_hits": embedded_name_hits[:1000],
    }


def _write_csv(path: pathlib.Path, donors: list[dict[str, Any]]) -> None:
    rows = []
    for d in donors:
        for r in d["direct_character_candidates"]:
            rows.append({"donor": d["name"], **{k: r.get(k) for k in ("relative_path","extension","size","sha256","physical_family","semantic_group","semantic_role","confidence")}})
    fields = ["donor","relative_path","extension","size","sha256","physical_family","semantic_group","semantic_role","confidence"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def _write_markdown(path: pathlib.Path, report: dict[str, Any]) -> None:
    lines = ["# Official Priston Tale Character Donor Census V0.9.1", "", "Read-only compatibility audit against the Summit Tale client.", ""]
    for d in report["donors"]:
        lines += [f"## {d['name']}", "", f"Root: `{d['root']}`", f"Files: **{d['file_count']}**", f"Direct SMD/SMB/INX/INF: **{d['direct_smd_count']} / {d['direct_smb_count']} / {d['direct_inx_count']} / {d['direct_inf_count']}**", f"Embedded character references: **{d['embedded_character_ref_count']}**", f"Read-only unchanged: **{d['read_only']}**", ""]
    lines += ["## Decision", "", report["decision"]["summary"], "", "- This audit does not write to either official client or the Summit client.", "- Direct SMD/INX/SMB assets can move to physical compatibility testing immediately.", "- If character assets are only referenced inside cdata/bdata/etc., unpacking/container recovery becomes the next milestone before transplant testing.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run(root: pathlib.Path, output: pathlib.Path, donor_specs: list[str]) -> dict[str, Any]:
    root = root.resolve()
    settings = Settings.discover(root)
    guards_before = _writer_policy_snapshot(root)
    if not all(v["pass"] for v in guards_before["writers"].values()):
        bad = [k for k,v in guards_before["writers"].items() if not v["pass"]]
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH:" + ",".join(bad))
    donors = []
    for spec in donor_specs:
        name, path = _parse_donor_spec(spec)
        donors.append(_scan_donor(name, path))
    comparisons = []
    if len(donors) >= 2:
        for i in range(len(donors)-1):
            for j in range(i+1, len(donors)):
                comparisons.append({"first": donors[i]["name"], "second": donors[j]["name"], **_compare_donors(donors[i], donors[j])})
    summit = {d["name"]: _summit_overlap(settings, d) for d in donors}
    guards_after = _writer_policy_snapshot(root)
    if guards_after != guards_before:
        raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_READ_ONLY_DONOR_AUDIT")
    if not all(d["read_only"] for d in donors):
        raise RuntimeError("DONOR_SOURCE_CHANGED_DURING_READ_ONLY_AUDIT")

    direct_total = sum(d["direct_smd_count"] + d["direct_smb_count"] + d["direct_inx_count"] + d["direct_inf_count"] for d in donors)
    refs_total = sum(d["embedded_character_ref_count"] for d in donors)
    if direct_total:
        mode = "DIRECT_CHARACTER_ASSETS_AVAILABLE"
        summary = "Direct character-format files were found in at least one official donor; next step is physical SMD/INX/SMB compatibility and transplant mapping."
    elif refs_total:
        mode = "CHARACTER_ASSETS_PACKED_OR_INDIRECTLY_REFERENCED"
        summary = "No direct character-format files were found, but the donor containers/executables reference character assets; next step is read-only container/index recovery before transplant testing."
    else:
        mode = "NO_CHARACTER_EVIDENCE_FOUND_YET"
        summary = "Neither direct character files nor embedded character references were found; inspect container formats and deeper package structure before claiming transplant compatibility."

    output.parent.mkdir(parents=True, exist_ok=True)
    csv_path = output.with_suffix(".csv")
    md_path = output.with_suffix(".md")
    report = {
        "format": FORMAT,
        "status": "PASS",
        "release_version": RELEASE,
        "summit_client_root": str(settings.client_root),
        "client_and_donors_read_only": True,
        "donors": donors,
        "comparisons": comparisons,
        "summit_overlap": summit,
        "decision": {
            "mode": mode,
            "summary": summary,
            "new_class_claimed": False,
            "transplant_write_authorized": False,
            "next_on_pass": "direct physical compatibility/transplant candidate if direct assets exist; otherwise recover official cdata/bdata container index/assets read-only",
        },
        "guards": {
            "certified_writer_hashes_valid": True,
            "writer_modules_modified": False,
            "production_policies_modified": False,
            "policy_sha256": guards_after["policies"],
        },
        "outputs": {"json": str(output), "csv": str(csv_path), "markdown": str(md_path)},
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(csv_path, donors)
    _write_markdown(md_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--donor", action="append", required=True)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.output)
    try:
        report = run(pathlib.Path(a.root), out, list(a.donor))
        compact = {
            "format": report["format"], "status": report["status"], "release_version": report["release_version"],
            "summit_client_root": report["summit_client_root"], "client_and_donors_read_only": report["client_and_donors_read_only"],
            "donors": [{k:d[k] for k in ("name","root","read_only","file_count","direct_character_candidate_count","direct_smd_count","direct_smb_count","direct_inx_count","direct_inf_count","container_count","embedded_character_ref_count")} for d in report["donors"]],
            "comparisons": report["comparisons"], "decision": report["decision"], "guards": report["guards"], "outputs": report["outputs"],
        }
        print(json.dumps(compact, ensure_ascii=False, indent=2))
        print("official_character_donor_census=PASS mode=" + report["decision"]["mode"] + " read_only=true")
        return 0
    except Exception as exc:
        fail = {"format": FORMAT, "status": "FAIL", "release_version": RELEASE, "error": f"{type(exc).__name__}:{exc}", "client_and_donors_read_only": True, "transplant_write_authorized": False}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(fail, ensure_ascii=False, indent=2))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
