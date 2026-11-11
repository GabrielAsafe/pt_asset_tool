#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELD_EXTS = {".spm", ".spp", ".spc"}
STALE_RUNTIME_PACKS = {
    "stage_spawns.sspb",
    "stage_spawns.sspb.report.json",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def iter_json(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.json"), key=lambda x: x.as_posix().casefold()):
        if p.name == "index.json":
            continue
        yield p

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot parse JSON {path}: {exc}") from exc

def canonical_text_legacy_paths(repo: Path) -> set[str]:
    root = repo / "SourceCode" / "Content" / "canonical" / "text" / "resources"
    out: set[str] = set()
    for p in iter_json(root):
        doc = load_json(p)
        legacy = ((doc.get("source") or {}).get("legacy_path") or "").strip()
        if not legacy:
            continue
        legacy = legacy.replace("\\", "/").lstrip("/")
        if legacy.startswith("Servidor/") or legacy.startswith("cliente/"):
            out.add(legacy)
    return out

def canonical_spawn_legacy_paths(repo: Path) -> set[str]:
    root = repo / "SourceCode" / "Content" / "canonical" / "stage_spawns"
    out: set[str] = set()
    for p in iter_json(root):
        doc = load_json(p)
        legacy = ((doc.get("legacy_source") or {}).get("path") or "").strip()
        if legacy:
            legacy = legacy.replace("\\", "/").lstrip("/")
            if legacy.startswith("Servidor/") or legacy.startswith("cliente/"):
                out.add(legacy)
    return out

def logical_field_paths(repo: Path, family: str, ext: str) -> set[str]:
    root = repo / "SourceCode" / "Content" / "canonical" / family
    out: set[str] = set()
    for p in iter_json(root):
        doc = load_json(p)
        logical = str(doc.get("logical_path") or "").replace("\\", "/").lstrip("/")
        if logical.casefold().endswith(ext):
            # Imported from the server legacy tree. Also consider a client copy
            # if one exists; only existing paths are moved.
            if logical.casefold().startswith("gameserver/"):
                out.add("Servidor/" + logical)
                out.add("cliente/" + logical)
    return out

def candidate_paths(repo: Path) -> set[str]:
    out = set()
    out |= canonical_text_legacy_paths(repo)
    out |= canonical_spawn_legacy_paths(repo)
    out |= logical_field_paths(repo, "stage_start_points", ".spp")
    out |= logical_field_paths(repo, "fixed_npcs", ".spc")

    # Catch any remaining legacy Field triplet in either runtime tree.
    for role in ("Servidor", "cliente"):
        field = repo / role / "GameServer" / "Field"
        if field.is_dir():
            for p in field.rglob("*"):
                if p.is_file() and p.suffix.casefold() in FIELD_EXTS:
                    out.add(p.relative_to(repo).as_posix())

    # The old standalone spawn pack is superseded by field_runtime.sfld.
    for role in ("Servidor", "cliente"):
        for name in STALE_RUNTIME_PACKS:
            out.add(f"{role}/Content/packs/{name}")

    # Old map compiler/deploy layouts used a lowercase content/maps tree.
    # Modern runtime resolution is authoritative at Content/packs.
    out.add("cliente/content/maps/maps_client.smap")
    out.add("Servidor/content/maps/maps_server.smap")

    return out

def validate_pack_presence(repo: Path) -> None:
    required = {
        "Servidor": [
            "definitions_server.scfg",
            "field_runtime.sfld",
            "text_resources.sres",
            "gameplay_config.sgcf",
            "maps_server.smap",
        ],
        "cliente": [
            "definitions_client.scfg",
            "field_runtime.sfld",
            "text_resources.sres",
            "gameplay_config.sgcf",
            "maps_client.smap",
        ],
    }
    missing = []
    for role, packs in required.items():
        for name in packs:
            p = repo / role / "Content" / "packs" / name
            if not p.is_file():
                missing.append(str(p))
    if missing:
        raise SystemExit("required runtime packs missing:\n  " + "\n  ".join(missing))

    # Every deployed pack must match the SourceCode build before legacy
    # files are moved away. This avoids accidentally testing old deployed data.
    source_root = repo / "SourceCode" / "Content" / "packs"
    for role, packs in required.items():
        for name in packs:
            src = source_root / name
            dst = repo / role / "Content" / "packs" / name
            if not src.is_file():
                raise SystemExit(f"missing source pack: {src}")
            if sha256(src) != sha256(dst):
                raise SystemExit(f"runtime pack hash mismatch: {dst}")

def do_plan(repo: Path):
    candidates = sorted(candidate_paths(repo), key=str.casefold)
    existing = []
    missing = []
    for rel in candidates:
        p = repo / rel
        if p.is_file():
            existing.append((rel, p))
        else:
            missing.append(rel)

    ext_counts = Counter()
    role_counts = Counter()
    bytes_total = 0
    for rel, p in existing:
        ext = p.suffix.casefold() or "<none>"
        ext_counts[ext] += 1
        role_counts[rel.split("/", 1)[0]] += 1
        bytes_total += p.stat().st_size

    return candidates, existing, missing, ext_counts, role_counts, bytes_total

def write_manifest(root: Path, repo: Path, rows: list[dict]) -> Path:
    manifest = {
        "schema": "summit.runtime-legacy-quarantine/v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo),
        "files": rows,
    }
    path = root / "MANIFEST.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

def quarantine(repo: Path) -> int:
    validate_pack_presence(repo)
    candidates, existing, missing, ext_counts, role_counts, total = do_plan(repo)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    qroot = repo / "runtime_legacy_quarantine" / stamp
    rows = []

    print(f"CANDIDATES={len(candidates)}")
    print(f"EXISTING_TO_MOVE={len(existing)}")
    print(f"ALREADY_ABSENT={len(missing)}")
    print(f"BY_ROLE={dict(role_counts)}")
    print(f"BY_EXTENSION={dict(sorted(ext_counts.items()))}")
    print(f"BYTES_TO_MOVE={total}")
    print(f"QUARANTINE_ROOT={qroot}")

    qroot.mkdir(parents=True, exist_ok=False)

    try:
        for rel, src in existing:
            dst = qroot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            before = sha256(src)
            size = src.stat().st_size
            shutil.move(str(src), str(dst))
            after = sha256(dst)
            if before != after:
                raise RuntimeError(f"hash changed while moving {rel}")
            rows.append({
                "relative_path": rel,
                "bytes": size,
                "sha256": before,
            })
        manifest = write_manifest(qroot, repo, rows)
    except Exception:
        print("MOVE_FAILED: attempting rollback", file=sys.stderr)
        for row in reversed(rows):
            rel = row["relative_path"]
            src = qroot / rel
            dst = repo / rel
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        raise

    print(f"MOVED={len(rows)}")
    print(f"MANIFEST={manifest}")
    print("RESULT=PASS")
    return 0

def dry_run(repo: Path) -> int:
    validate_pack_presence(repo)
    candidates, existing, missing, ext_counts, role_counts, total = do_plan(repo)
    print("MODE=DRY_RUN")
    print(f"CANDIDATES={len(candidates)}")
    print(f"EXISTING_TO_MOVE={len(existing)}")
    print(f"ALREADY_ABSENT={len(missing)}")
    print(f"BY_ROLE={dict(role_counts)}")
    print(f"BY_EXTENSION={dict(sorted(ext_counts.items()))}")
    print(f"BYTES_TO_MOVE={total}")
    print("\nFirst 80 existing files:")
    for rel, _ in existing[:80]:
        print(rel)
    if len(existing) > 80:
        print(f"... +{len(existing)-80} more")
    print("RESULT=DRY_RUN_PASS")
    return 0

def restore(repo: Path, manifest_path: Path) -> int:
    manifest_path = manifest_path.expanduser().resolve()
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    qroot = manifest_path.parent
    restored = 0
    skipped = 0
    for row in doc.get("files", []):
        rel = row["relative_path"]
        src = qroot / rel
        dst = repo / rel
        if not src.is_file():
            print(f"MISSING_IN_QUARANTINE {rel}", file=sys.stderr)
            skipped += 1
            continue
        if dst.exists():
            print(f"DESTINATION_EXISTS {rel}", file=sys.stderr)
            skipped += 1
            continue
        if sha256(src) != row["sha256"]:
            print(f"HASH_MISMATCH {rel}", file=sys.stderr)
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        restored += 1
    print(f"RESTORED={restored}")
    print(f"SKIPPED={skipped}")
    print("RESULT=" + ("PASS" if skipped == 0 else "REVIEW"))
    return 0 if skipped == 0 else 1

def main() -> int:
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser(
        description="Reversibly move pack-replaced legacy runtime files out of cliente/ and Servidor/"
    )
    ap.add_argument("--repo-root", type=Path, default=here.parents[3] if len(here.parents) > 3 else Path.cwd())
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Move files into runtime_legacy_quarantine/<timestamp>/")
    mode.add_argument("--restore", type=Path, metavar="MANIFEST", help="Restore a prior quarantine manifest")
    args = ap.parse_args()

    repo = args.repo_root.expanduser().resolve()
    if not (repo / "SourceCode").is_dir() or not (repo / "Servidor").is_dir() or not (repo / "cliente").is_dir():
        raise SystemExit(f"repo-root must contain SourceCode/, Servidor/, cliente/: {repo}")

    if args.restore:
        return restore(repo, args.restore)
    if args.apply:
        return quarantine(repo)
    return dry_run(repo)

if __name__ == "__main__":
    raise SystemExit(main())
