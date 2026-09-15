#!/usr/bin/env python3
"""
Summit Tale Hardened Round-Trip Restore V4

Dry-run by default.

Safety:
- only changed workspace files are candidates;
- secure path containment for workspace and game root;
- verifies published_build SHA when present;
- detects client drift against source_sha256;
- recognizes ALREADY_APPLIED;
- backs up ALL targets before any write;
- verifies every backup;
- atomically replaces destination files;
- verifies post-write SHA/size;
- rolls back already-written files if any operation fails;
- writes a transaction report.

Use --apply only after reviewing the dry-run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import tempfile


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_rel(value: str) -> str:
    value = value.replace("\\", "/")
    p = pathlib.PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    rel = p.as_posix().lstrip("./")
    if not rel or rel == ".":
        raise ValueError("empty relative path")
    return rel


def safe_join(base: pathlib.Path, rel: str) -> pathlib.Path:
    rel = normalize_rel(rel)
    base = base.resolve()
    out = (base / pathlib.PurePosixPath(rel)).resolve()
    try:
        out.relative_to(base)
    except ValueError:
        raise ValueError(f"path escapes base directory: {rel!r}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", type=pathlib.Path)
    ap.add_argument("--game-root", type=pathlib.Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--asset-id", action="append", default=[])
    ap.add_argument("--target", action="append", default=[])
    ap.add_argument(
        "--allow-unhashed",
        action="store_true",
        help="allow apply for legacy workspace entries without source_sha256",
    )
    a = ap.parse_args()

    ws = a.workspace.expanduser().resolve()
    manifest_path = ws / "workspace_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"workspace manifest missing: {manifest_path}")

    M = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = (a.game_root or pathlib.Path(M["game_root"])).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"game root missing: {root}")

    asset_filter = {x.upper() for x in a.asset_id}
    target_filter = {normalize_rel(x).lower() for x in a.target}

    seen_targets = set()
    candidates = []
    skipped = []

    for row in M.get("files", []):
        asset_id = str(row.get("asset_id", ""))
        workspace_rel = normalize_rel(row["workspace_path"])
        target_rel = normalize_rel(row["roundtrip_target"])

        if asset_filter and asset_id.upper() not in asset_filter:
            continue
        if target_filter and target_rel.lower() not in target_filter:
            continue

        key = target_rel.lower()
        if key in seen_targets:
            raise ValueError(f"duplicate roundtrip_target in workspace manifest: {target_rel}")
        seen_targets.add(key)

        src = safe_join(ws, workspace_rel)
        dst = safe_join(root, target_rel)

        if not src.is_file():
            skipped.append((asset_id, target_rel, "WORKSPACE_FILE_MISSING"))
            continue

        src_sha = sha256_file(src)
        src_size = src.stat().st_size

        published = row.get("published_build")
        if published:
            expected = published.get("sha256")
            expected_size = published.get("size")
            if expected and src_sha != expected:
                raise RuntimeError(
                    f"{asset_id}: workspace file differs from published_build SHA"
                )
            if expected_size is not None and src_size != int(expected_size):
                raise RuntimeError(
                    f"{asset_id}: workspace file differs from published_build size"
                )

        original_sha = row.get("source_sha256")
        original_size = row.get("source_size")

        if not original_sha and not a.allow_unhashed:
            raise RuntimeError(
                f"{asset_id}: source_sha256 missing. Reprepare/register with hashes "
                "or use --allow-unhashed only after manual review."
            )

        dst_exists = dst.is_file()
        dst_sha = sha256_file(dst) if dst_exists else None
        dst_size = dst.stat().st_size if dst_exists else None

        # V4 critical fix:
        # Do NOT skip solely because the workspace slot equals the registered
        # source. The client may still contain a previously published managed
        # build and therefore need a real restore-to-source write.
        #
        # Only call it UNCHANGED when BOTH workspace and client are the
        # registered source. If client already equals any other workspace build,
        # ALREADY_APPLIED remains correct.
        if original_sha and src_sha == original_sha:
            if (
                dst_exists
                and dst_sha == original_sha
                and (original_size is None or dst_size == int(original_size))
            ):
                skipped.append((asset_id, target_rel, "UNCHANGED"))
                continue

        if dst_exists and dst_sha == src_sha and dst_size == src_size:
            skipped.append((asset_id, target_rel, "ALREADY_APPLIED"))
            continue

        if original_sha:
            if not dst_exists:
                raise RuntimeError(
                    f"{asset_id}: client asset disappeared since workspace creation: {dst}"
                )

            managed_hashes = {original_sha}
            managed_sizes = {}
            if original_size is not None:
                managed_sizes[original_sha] = int(original_size)

            current_pub = row.get("published_build") or {}
            if current_pub.get("sha256"):
                managed_hashes.add(current_pub["sha256"])
                if current_pub.get("size") is not None:
                    managed_sizes[current_pub["sha256"]] = int(current_pub["size"])

            for item in row.get("published_history", []) or []:
                h = item.get("sha256")
                if h:
                    managed_hashes.add(h)
                    if item.get("size") is not None:
                        managed_sizes[h] = int(item["size"])

            # Backward compatibility: V1 bridge stored publication history globally.
            for item in M.get("bridge_history", []) or []:
                if (
                    item.get("action") == "publish"
                    and str(item.get("asset_id", "")).upper() == asset_id.upper()
                    and item.get("published_sha256")
                ):
                    h = item["published_sha256"]
                    managed_hashes.add(h)
                    if item.get("published_size") is not None:
                        managed_sizes[h] = int(item["published_size"])

            if dst_sha not in managed_hashes:
                raise RuntimeError(
                    f"{asset_id}: CLIENT_DRIFT detected. "
                    f"found {dst_sha}; it is neither the registered source nor a "
                    "previously published build for this Asset_ID. Refusing to overwrite."
                )

            expected_managed_size = managed_sizes.get(dst_sha)
            if expected_managed_size is not None and dst_size != expected_managed_size:
                raise RuntimeError(
                    f"{asset_id}: CLIENT_DRIFT size mismatch for managed SHA {dst_sha}: "
                    f"expected {expected_managed_size}, found {dst_size}"
                )

            client_state = (
                "REGISTERED_SOURCE"
                if dst_sha == original_sha
                else "PREVIOUSLY_PUBLISHED_BUILD"
            )
        else:
            client_state = "UNHASHED_LEGACY"

        candidates.append({
            "row": row,
            "asset_id": asset_id,
            "workspace_rel": workspace_rel,
            "target_rel": target_rel,
            "src": src,
            "dst": dst,
            "src_sha": src_sha,
            "src_size": src_size,
            "dst_exists": dst_exists,
            "dst_sha": dst_sha,
            "dst_size": dst_size,
            "client_state": client_state,
        })

    print("SUMMIT_ROUNDTRIP_RESTORE_V4")
    print(f"workspace={ws}")
    print(f"game_root={root}")
    print(f"mode={'APPLY' if a.apply else 'DRY_RUN'}")
    print(f"candidate_count={len(candidates)}")
    print(f"skipped_count={len(skipped)}")

    for asset_id, target, reason in skipped:
        print(f"SKIP asset_id={asset_id} target={target} reason={reason}")

    for op in candidates:
        print(
            f"{'WRITE' if a.apply else 'PLAN'} "
            f"asset_id={op['asset_id']} "
            f"{op['src']} -> {op['dst']} "
            f"sha256={op['src_sha']} size={op['src_size']} "
            f"client_state={op['client_state']}"
        )

    if not a.apply:
        print("No files changed. Use --apply after review.")
        print("roundtrip_restore_check=DRY_RUN_PASS")
        return

    if not candidates:
        print("No changed assets require writing.")
        print("roundtrip_restore_check=PASS")
        return

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_root = ws / f"_roundtrip_backup_v2_{stamp}"
    backup_root.mkdir(parents=True, exist_ok=False)

    # Backup all destinations before the first write.
    for op in candidates:
        if op["dst_exists"]:
            backup = safe_join(backup_root, op["target_rel"])
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(op["dst"], backup)
            if sha256_file(backup) != op["dst_sha"] or backup.stat().st_size != op["dst_size"]:
                raise RuntimeError(f"backup verification failed for {op['asset_id']}")
            op["backup"] = backup
        else:
            op["backup"] = None

    written = []
    try:
        for op in candidates:
            dst = op["dst"]
            dst.parent.mkdir(parents=True, exist_ok=True)

            fd, tmp_name = tempfile.mkstemp(
                prefix=dst.name + ".",
                suffix=".roundtrip.tmp",
                dir=dst.parent,
            )
            os.close(fd)
            tmp = pathlib.Path(tmp_name)
            try:
                shutil.copy2(op["src"], tmp)
                if sha256_file(tmp) != op["src_sha"] or tmp.stat().st_size != op["src_size"]:
                    raise RuntimeError(f"temporary copy verification failed for {op['asset_id']}")
                os.replace(tmp, dst)
            finally:
                if tmp.exists():
                    tmp.unlink()

            if sha256_file(dst) != op["src_sha"] or dst.stat().st_size != op["src_size"]:
                raise RuntimeError(f"post-write verification failed for {op['asset_id']}")

            written.append(op)
            print(
                f"WROTE asset_id={op['asset_id']} "
                f"target={op['target_rel']} "
                f"sha256={op['src_sha']} size={op['src_size']} "
                f"previous_client_state={op['client_state']}"
            )

    except Exception:
        print("WRITE_FAILURE: rolling back already-written assets")
        for op in reversed(written):
            if op["backup"] is not None:
                shutil.copy2(op["backup"], op["dst"])
                if sha256_file(op["dst"]) != op["dst_sha"]:
                    print(f"ROLLBACK_VERIFY_FAIL asset_id={op['asset_id']}")
            else:
                op["dst"].unlink(missing_ok=True)
            print(f"ROLLED_BACK asset_id={op['asset_id']} target={op['target_rel']}")
        raise

    report = {
        "tool": "SUMMIT_ROUNDTRIP_RESTORE_V4",
        "status": "PASS",
        "workspace": str(ws),
        "game_root": str(root),
        "backup_root": str(backup_root),
        "written": [
            {
                "asset_id": op["asset_id"],
                "roundtrip_target": op["target_rel"],
                "sha256": op["src_sha"],
                "size": op["src_size"],
                "backup": str(op["backup"]) if op["backup"] else None,
                "previous_client_sha256": op["dst_sha"],
                "previous_client_size": op["dst_size"],
                "previous_client_state": op["client_state"],
            }
            for op in candidates
        ],
        "skipped": [
            {"asset_id": aid, "roundtrip_target": t, "reason": r}
            for aid, t, r in skipped
        ],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    report_path = backup_root / "transaction.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Backup: {backup_root}")
    print(f"Transaction: {report_path}")
    print("roundtrip_restore_check=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"roundtrip_restore_check=FAIL: {type(exc).__name__}: {exc}")
        raise
