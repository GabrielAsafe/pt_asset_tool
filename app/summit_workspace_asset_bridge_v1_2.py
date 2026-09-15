#!/usr/bin/env python3
"""
Summit Tale Workspace Asset Bridge V1.2

Bridges:
  validated PT character pipeline build
        ->
  registry workspace_manifest.json
        ->
  hardened round-trip restore

Commands:
  register:
    Register/copy a physical client asset into a workspace when it is not yet
    present in the source-derived asset catalog.

  publish:
    Publish a pipeline_check=PASS build into an already registered workspace
    slot. Never touches the game client.

The workspace path is never used to infer the client destination. The client
destination remains roundtrip_target in workspace_manifest.json.
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


def stable_asset_id(roundtrip_target: str) -> str:
    normalized = roundtrip_target.replace("\\", "/").lstrip("./").lower()
    return "AST-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12].upper()


def normalize_rel(value: str) -> str:
    value = value.replace("\\", "/")
    p = pathlib.PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    normalized = p.as_posix().lstrip("./")
    if not normalized or normalized == ".":
        raise ValueError("empty relative path")
    return normalized


def safe_join(base: pathlib.Path, rel: str) -> pathlib.Path:
    rel = normalize_rel(rel)
    base = base.resolve()
    path = (base / pathlib.PurePosixPath(rel)).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError(f"path escapes base directory: {rel!r}")
    return path


def load_workspace(workspace: pathlib.Path):
    workspace = workspace.resolve()
    manifest_path = workspace / "workspace_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"workspace manifest missing: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data.get("files"), list):
        raise ValueError("workspace_manifest.json: files must be a list")
    return workspace, manifest_path, data


def atomic_write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def backup_manifest(manifest_path: pathlib.Path) -> pathlib.Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = manifest_path.with_name(f"workspace_manifest.backup_{stamp}.json")
    shutil.copy2(manifest_path, backup)
    if sha256_file(backup) != sha256_file(manifest_path):
        raise RuntimeError("workspace manifest backup verification failed")
    return backup


def find_entry(data, *, target=None, asset_id=None):
    matches = []
    for row in data["files"]:
        if target is not None:
            rt = normalize_rel(str(row.get("roundtrip_target", "")))
            if rt.lower() == normalize_rel(target).lower():
                matches.append(row)
        elif asset_id is not None and str(row.get("asset_id", "")).upper() == asset_id.upper():
            matches.append(row)
    if len(matches) != 1:
        key = f"target={target!r}" if target is not None else f"asset_id={asset_id!r}"
        raise ValueError(f"expected exactly one workspace entry for {key}; found {len(matches)}")
    return matches[0]


def cmd_register(args):
    workspace, manifest_path, data = load_workspace(args.workspace)
    root = pathlib.Path(args.game_root or data.get("game_root", "")).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"game root missing: {root}")

    target = normalize_rel(args.target)
    src = safe_join(root, target)
    if not src.is_file():
        raise FileNotFoundError(f"physical asset missing: {src}")

    asset_id = args.asset_id or stable_asset_id(target)
    workspace_rel = normalize_rel(
        args.workspace_path or f"Physical/{target}"
    )
    dst = safe_join(workspace, workspace_rel)

    for row in data["files"]:
        if str(row.get("asset_id", "")).upper() == asset_id.upper():
            raise ValueError(f"asset_id already registered: {asset_id}")
        if normalize_rel(str(row.get("roundtrip_target", ""))).lower() == target.lower():
            raise ValueError(f"roundtrip_target already registered: {target}")
        if normalize_rel(str(row.get("workspace_path", ""))).lower() == workspace_rel.lower():
            raise ValueError(f"workspace_path already registered: {workspace_rel}")

    if dst.exists() and not args.overwrite:
        raise FileExistsError(f"workspace file already exists: {dst}")

    manifest_backup = backup_manifest(manifest_path)

    if dst.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        old = safe_join(workspace, f"_bridge_backup_{stamp}/{workspace_rel}")
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, old)
        if sha256_file(old) != sha256_file(dst):
            raise RuntimeError("existing workspace file backup verification failed")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    source_sha = sha256_file(src)
    source_size = src.stat().st_size
    if sha256_file(dst) != source_sha or dst.stat().st_size != source_size:
        raise RuntimeError("registered workspace copy verification failed")

    entry = {
        "asset_id": asset_id,
        "workspace_path": workspace_rel,
        "roundtrip_target": target,
        "category": args.category,
        "subcategory": args.subcategory,
        "representation": args.representation,
        "owner_name": args.owner,
        "class_code": args.class_code,
        "source_sha256": source_sha,
        "source_size": source_size,
        "registry_origin": "physical_bridge_v1",
        "registered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    data["files"].append(entry)
    data.setdefault("bridge_history", []).append({
        "action": "register",
        "asset_id": asset_id,
        "roundtrip_target": target,
        "workspace_path": workspace_rel,
        "source_sha256": source_sha,
        "source_size": source_size,
        "manifest_backup": str(manifest_backup),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    atomic_write_json(manifest_path, data)

    print("SUMMIT_WORKSPACE_ASSET_BRIDGE_V1_2")
    print("action=register")
    print(f"asset_id={asset_id}")
    print(f"roundtrip_target={target}")
    print(f"workspace_path={workspace_rel}")
    print(f"source_size={source_size}")
    print(f"source_sha256={source_sha}")
    print(f"manifest_backup={manifest_backup}")
    print("register_check=PASS")


def cmd_publish(args):
    workspace, manifest_path, data = load_workspace(args.workspace)

    pipeline_manifest = pathlib.Path(args.pipeline_manifest).expanduser().resolve()
    if not pipeline_manifest.is_file():
        raise FileNotFoundError(f"pipeline manifest missing: {pipeline_manifest}")
    pm = json.loads(pipeline_manifest.read_text(encoding="utf-8"))

    if pm.get("pipeline_check") != "PASS":
        raise ValueError("pipeline manifest is not PASS")
    if pm.get("runtime_installed") not in (False, None):
        raise ValueError("pipeline manifest unexpectedly says runtime_installed=true")

    smd = pathlib.Path(pm["smd"]).expanduser().resolve()
    if not smd.is_file():
        raise FileNotFoundError(f"pipeline SMD missing: {smd}")

    smd_sha = sha256_file(smd)
    smd_size = smd.stat().st_size
    if smd_sha != pm.get("smd_sha256"):
        raise ValueError("pipeline SMD SHA differs from pipeline manifest")
    if smd_size != int(pm.get("smd_size")):
        raise ValueError("pipeline SMD size differs from pipeline manifest")

    if args.target:
        entry = find_entry(data, target=args.target)
    else:
        entry = find_entry(data, asset_id=args.asset_id)

    workspace_rel = normalize_rel(entry["workspace_path"])
    dst = safe_join(workspace, workspace_rel)

    if not dst.is_file():
        raise FileNotFoundError(f"registered workspace slot missing: {dst}")

    current_sha = sha256_file(dst)
    original_sha = entry.get("source_sha256")
    published = entry.get("published_build")

    if published:
        expected_prev = published.get("sha256")
        if expected_prev and current_sha != expected_prev and current_sha != original_sha:
            raise RuntimeError(
                "workspace slot drifted since previous publication; refusing to replace"
            )
        if not args.replace_published and current_sha == expected_prev:
            raise RuntimeError(
                "workspace slot already contains a published build; "
                "use --replace-published intentionally"
            )
    elif original_sha and current_sha != original_sha:
        raise RuntimeError(
            "workspace slot changed from its registered source before publication"
        )

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = safe_join(workspace, f"_publish_backup_{stamp}/{workspace_rel}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dst, backup)
    if sha256_file(backup) != current_sha:
        raise RuntimeError("workspace publish backup verification failed")

    manifest_backup = backup_manifest(manifest_path)

    tmp = dst.with_name(dst.name + ".publish.tmp")
    if tmp.exists():
        tmp.unlink()
    shutil.copy2(smd, tmp)
    if sha256_file(tmp) != smd_sha or tmp.stat().st_size != smd_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("temporary published build verification failed")
    os.replace(tmp, dst)

    if sha256_file(dst) != smd_sha or dst.stat().st_size != smd_size:
        shutil.copy2(backup, dst)
        raise RuntimeError("publish verification failed; workspace slot restored")

    previous_published = entry.get("published_build")
    if previous_published:
        hist = entry.setdefault("published_history", [])
        prev_sha = previous_published.get("sha256")
        if prev_sha and not any(x.get("sha256") == prev_sha for x in hist):
            hist.append(previous_published)

    new_published = {
        "pipeline_manifest": str(pipeline_manifest),
        "pipeline_manifest_sha256": sha256_file(pipeline_manifest),
        "pipeline_check": "PASS",
        "sha256": smd_sha,
        "size": smd_size,
        "source_smd": str(smd),
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "workspace_backup": str(backup),
    }
    entry["published_build"] = new_published
    hist = entry.setdefault("published_history", [])
    if not any(x.get("sha256") == smd_sha for x in hist):
        hist.append(new_published)
    data.setdefault("bridge_history", []).append({
        "action": "publish",
        "asset_id": entry.get("asset_id"),
        "roundtrip_target": entry.get("roundtrip_target"),
        "workspace_path": workspace_rel,
        "published_sha256": smd_sha,
        "published_size": smd_size,
        "pipeline_manifest": str(pipeline_manifest),
        "manifest_backup": str(manifest_backup),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    atomic_write_json(manifest_path, data)

    print("SUMMIT_WORKSPACE_ASSET_BRIDGE_V1_2")
    print("action=publish")
    print(f"asset_id={entry.get('asset_id')}")
    print(f"roundtrip_target={entry.get('roundtrip_target')}")
    print(f"workspace_path={workspace_rel}")
    print(f"published_size={smd_size}")
    print(f"published_sha256={smd_sha}")
    print(f"managed_published_sha_count={len({x.get('sha256') for x in entry.get('published_history', []) if x.get('sha256')})}")
    print(f"workspace_backup={backup}")
    print(f"manifest_backup={manifest_backup}")
    print("client_modified=False")
    print("publish_check=PASS")



def cmd_publish_file(args):
    workspace, manifest_path, data = load_workspace(args.workspace)

    build_manifest = pathlib.Path(args.build_manifest).expanduser().resolve()
    if not build_manifest.is_file():
        raise FileNotFoundError(f"build manifest missing: {build_manifest}")
    bm = json.loads(build_manifest.read_text(encoding="utf-8"))

    if bm.get("build_check") != "PASS":
        raise ValueError("build manifest is not PASS")
    if bm.get("runtime_installed") not in (False, None):
        raise ValueError("build manifest unexpectedly says runtime_installed=true")

    artifact = pathlib.Path(bm["artifact"]).expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"build artifact missing: {artifact}")

    artifact_sha = sha256_file(artifact)
    artifact_size = artifact.stat().st_size
    if artifact_sha != bm.get("artifact_sha256"):
        raise ValueError("artifact SHA differs from build manifest")
    if artifact_size != int(bm.get("artifact_size")):
        raise ValueError("artifact size differs from build manifest")

    if args.target:
        entry = find_entry(data, target=args.target)
    else:
        entry = find_entry(data, asset_id=args.asset_id)

    manifest_target = bm.get("roundtrip_target")
    if manifest_target and normalize_rel(manifest_target).lower() != normalize_rel(entry["roundtrip_target"]).lower():
        raise ValueError("build manifest target differs from registered asset target")

    workspace_rel = normalize_rel(entry["workspace_path"])
    dst = safe_join(workspace, workspace_rel)
    if not dst.is_file():
        raise FileNotFoundError(f"registered workspace slot missing: {dst}")

    current_sha = sha256_file(dst)
    original_sha = entry.get("source_sha256")
    published = entry.get("published_build")

    if published:
        expected_prev = published.get("sha256")
        if expected_prev and current_sha != expected_prev and current_sha != original_sha:
            raise RuntimeError(
                "workspace slot drifted since previous publication; refusing to replace"
            )
        if not args.replace_published and current_sha == expected_prev:
            raise RuntimeError(
                "workspace slot already contains a published build; "
                "use --replace-published intentionally"
            )
    elif original_sha and current_sha != original_sha:
        raise RuntimeError(
            "workspace slot changed from its registered source before publication"
        )

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = safe_join(workspace, f"_publish_backup_{stamp}/{workspace_rel}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dst, backup)
    if sha256_file(backup) != current_sha:
        raise RuntimeError("workspace publish backup verification failed")

    manifest_backup = backup_manifest(manifest_path)

    tmp = dst.with_name(dst.name + ".publish.tmp")
    if tmp.exists():
        tmp.unlink()
    shutil.copy2(artifact, tmp)
    if sha256_file(tmp) != artifact_sha or tmp.stat().st_size != artifact_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("temporary published artifact verification failed")
    os.replace(tmp, dst)

    if sha256_file(dst) != artifact_sha or dst.stat().st_size != artifact_size:
        shutil.copy2(backup, dst)
        raise RuntimeError("publish verification failed; workspace slot restored")

    previous_published = entry.get("published_build")
    if previous_published:
        hist = entry.setdefault("published_history", [])
        prev_sha = previous_published.get("sha256")
        if prev_sha and not any(x.get("sha256") == prev_sha for x in hist):
            hist.append(previous_published)

    new_published = {
        "build_manifest": str(build_manifest),
        "build_manifest_sha256": sha256_file(build_manifest),
        "build_check": "PASS",
        "sha256": artifact_sha,
        "size": artifact_size,
        "artifact": str(artifact),
        "artifact_role": bm.get("role"),
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "workspace_backup": str(backup),
    }
    entry["published_build"] = new_published
    hist = entry.setdefault("published_history", [])
    if not any(x.get("sha256") == artifact_sha for x in hist):
        hist.append(new_published)

    data.setdefault("bridge_history", []).append({
        "action": "publish",
        "asset_id": entry.get("asset_id"),
        "roundtrip_target": entry.get("roundtrip_target"),
        "workspace_path": workspace_rel,
        "published_sha256": artifact_sha,
        "published_size": artifact_size,
        "build_manifest": str(build_manifest),
        "manifest_backup": str(manifest_backup),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    atomic_write_json(manifest_path, data)

    print("SUMMIT_WORKSPACE_ASSET_BRIDGE_V1_2")
    print("action=publish-file")
    print(f"asset_id={entry.get('asset_id')}")
    print(f"roundtrip_target={entry.get('roundtrip_target')}")
    print(f"workspace_path={workspace_rel}")
    print(f"published_size={artifact_size}")
    print(f"published_sha256={artifact_sha}")
    print(f"managed_published_sha_count={len({x.get('sha256') for x in entry.get('published_history', []) if x.get('sha256')})}")
    print(f"workspace_backup={backup}")
    print(f"manifest_backup={manifest_backup}")
    print("client_modified=False")
    print("publish_file_check=PASS")



def build_parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("register")
    r.add_argument("workspace", type=pathlib.Path)
    r.add_argument("--game-root", type=pathlib.Path)
    r.add_argument("--target", required=True)
    r.add_argument("--workspace-path")
    r.add_argument("--asset-id")
    r.add_argument("--category", default="Characters")
    r.add_argument("--subcategory", default="Physical Asset")
    r.add_argument("--representation", default="Game Asset")
    r.add_argument("--owner", default="")
    r.add_argument("--class-code", default="")
    r.add_argument("--overwrite", action="store_true")
    r.set_defaults(func=cmd_register)

    q = sub.add_parser("publish")
    q.add_argument("workspace", type=pathlib.Path)
    q.add_argument("--pipeline-manifest", required=True)
    key = q.add_mutually_exclusive_group(required=True)
    key.add_argument("--target")
    key.add_argument("--asset-id")
    q.add_argument("--replace-published", action="store_true")
    q.set_defaults(func=cmd_publish)

    pf = sub.add_parser("publish-file")
    pf.add_argument("workspace", type=pathlib.Path)
    pf.add_argument("--build-manifest", required=True)
    key2 = pf.add_mutually_exclusive_group(required=True)
    key2.add_argument("--target")
    key2.add_argument("--asset-id")
    pf.add_argument("--replace-published", action="store_true")
    pf.set_defaults(func=cmd_publish_file)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"bridge_check=FAIL: {type(exc).__name__}: {exc}")
        raise
