#!/usr/bin/env python3
"""
PT Character Asset V1.4

Treat a Summit Tale character as one operational asset set.

High-level commands:
  inspect         resolve model / skeleton / INX / textures and write an asset manifest
  sync-workspace  register/copy resolved components into the round-trip workspace
  build           run the runtime-proven all-LODs geometry pipeline from the profile
  publish-build   publish an already validated build without running Blender again
  status          summarize registry/workspace/client/build state for the character
  deploy-plan     dry-run deployment for the character model
  deploy          verified deployment for the character model

This tool does not silently use --force-test. Production remains REVIEW_REQUIRED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_asset_id(roundtrip_target: str) -> str:
    norm = roundtrip_target.replace("\\", "/").lstrip("./").lower()
    return "AST-" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12].upper()


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve(root: pathlib.Path, value: str | pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def norm_rel(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def safe_client_path(client_root: pathlib.Path, rel: str) -> pathlib.Path:
    dst = (client_root / norm_rel(rel)).resolve()
    try:
        dst.relative_to(client_root)
    except ValueError as exc:
        raise ValueError(f"unsafe client path outside root: {rel}") from exc
    return dst


def client_basename_index(client_root: pathlib.Path):
    index = {}
    for p in client_root.rglob("*"):
        if not p.is_file():
            continue
        index.setdefault(p.name.lower(), []).append(p)
    return index


def discover_component(root, client_root, basename_index, comp):
    local = None
    if comp.get("local_source"):
        candidate = resolve(root, comp["local_source"])
        if candidate.is_file():
            local = candidate

    target = comp.get("roundtrip_target")
    physical = None
    resolution = None

    if target:
        candidate = safe_client_path(client_root, target)
        if candidate.is_file():
            physical = candidate
            resolution = "EXACT_ROUNDTRIP_TARGET"
    elif comp.get("discover_client_by_basename"):
        name = comp["discover_client_by_basename"].lower()
        matches = basename_index.get(name, [])
        if len(matches) == 1:
            physical = matches[0].resolve()
            target = physical.relative_to(client_root).as_posix()
            resolution = "UNIQUE_BASENAME"
        elif len(matches) > 1:
            resolution = "AMBIGUOUS_BASENAME"
        else:
            resolution = "BASENAME_NOT_FOUND"
    else:
        resolution = "NO_CLIENT_DISCOVERY_RULE"

    required = bool(comp.get("required", False))
    # Build dependencies can be satisfied by local source even if the client
    # copy is not uniquely located yet.
    available = physical is not None or local is not None
    status = "PASS" if available else ("MISSING_REQUIRED" if required else "OPTIONAL_MISSING")

    chosen = physical or local
    row = dict(comp)
    row.update({
        "roundtrip_target": target,
        "asset_id": stable_asset_id(target) if target else None,
        "client_path": str(physical) if physical else None,
        "local_source_path": str(local) if local else None,
        "resolution": resolution,
        "available": available,
        "status": status,
        "size": chosen.stat().st_size if chosen else None,
        "sha256": sha256_file(chosen) if chosen else None,
    })
    return row


def inspect_asset(root, profile_path, profile, client_root, workspace=None):
    basename_index = client_basename_index(client_root)
    components = [
        discover_component(root, client_root, basename_index, c)
        for c in profile.get("components", [])
    ]

    workspace_rows = {}
    workspace_manifest = None
    if workspace:
        mp = workspace / "workspace_manifest.json"
        if mp.is_file():
            workspace_manifest = load_json(mp)
            for row in workspace_manifest.get("files", []):
                target = norm_rel(row.get("roundtrip_target", "")).lower()
                if target:
                    workspace_rows[target] = row

    for c in components:
        target = c.get("roundtrip_target")
        wrow = workspace_rows.get(norm_rel(target).lower()) if target else None
        c["workspace_registered"] = bool(wrow)
        c["workspace_asset_id"] = wrow.get("asset_id") if wrow else None
        c["workspace_registered_path"] = wrow.get("workspace_path") if wrow else None

    missing_required = [c["role"] for c in components if c["status"] == "MISSING_REQUIRED"]
    model = next((c for c in components if c["role"] == "model"), None)

    # Protect the geometry baseline used by the profile.
    model_baseline_ok = True
    if model and profile.get("model_smd_sha256"):
        baseline = profile["model_smd_sha256"].lower()
        local_model = resolve(root, profile["model_smd"])
        if not local_model.is_file() or sha256_file(local_model) != baseline:
            model_baseline_ok = False

    report = {
        "tool": "PT_CHARACTER_ASSET_V1_5",
        "character_asset_check": "PASS" if not missing_required and model_baseline_ok else "FAIL",
        "profile": str(profile_path),
        "profile_id": profile["profile_id"],
        "asset_set_id": profile.get("asset_set_id"),
        "display_name": profile.get("display_name"),
        "owner_name": profile.get("owner_name"),
        "class_code": profile.get("class_code"),
        "client_root": str(client_root),
        "workspace": str(workspace) if workspace else None,
        "model_baseline_ok": model_baseline_ok,
        "lod_groups": profile.get("lod_groups", {}),
        "geometry_status": profile.get("geometry_status", {}),
        "components": components,
        "missing_required_roles": missing_required,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return report


def default_asset_manifest(root, profile):
    return root / "logs/characters" / profile["profile_id"] / "character_asset_manifest.json"


def run_checked(cmd):
    print("COMMAND=" + " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def cmd_inspect(args):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    client = resolve(root, args.client_root)
    workspace = resolve(root, args.workspace) if args.workspace else None

    report = inspect_asset(root, pp, profile, client, workspace)
    out = resolve(root, args.out) if args.out else default_asset_manifest(root, profile)
    write_json(out, report)

    print("PT_CHARACTER_ASSET_V1_5")
    print("action=inspect")
    print(f"profile_id={profile['profile_id']}")
    print(f"asset_set_id={profile.get('asset_set_id')}")
    print(f"component_count={len(report['components'])}")
    for c in report["components"]:
        print(
            f"COMPONENT role={c['role']} status={c['status']} "
            f"resolution={c['resolution']} "
            f"target={c.get('roundtrip_target')} "
            f"asset_id={c.get('asset_id')} "
            f"workspace_registered={c['workspace_registered']}"
        )
    print(f"model_baseline_ok={report['model_baseline_ok']}")
    print(f"manifest={out}")
    print(f"character_asset_check={report['character_asset_check']}")
    if report["character_asset_check"] != "PASS":
        raise SystemExit(2)


def cmd_sync_workspace(args):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    client = resolve(root, args.client_root)
    workspace = resolve(root, args.workspace)

    report = inspect_asset(root, pp, profile, client, workspace)
    if report["character_asset_check"] != "PASS":
        raise RuntimeError("character asset inspect did not PASS")

    bridge = root / "summit_workspace_asset_bridge_v1_2.py"
    if not bridge.is_file():
        raise FileNotFoundError(bridge)

    registered = 0
    skipped = 0
    for c in report["components"]:
        target = c.get("roundtrip_target")
        if not target:
            print(f"SKIP role={c['role']} reason=NO_RESOLVED_CLIENT_TARGET")
            skipped += 1
            continue
        if c.get("workspace_registered"):
            print(
                f"SKIP role={c['role']} target={target} "
                "reason=ALREADY_REGISTERED"
            )
            skipped += 1
            continue
        if not c.get("client_path"):
            print(
                f"SKIP role={c['role']} target={target} "
                "reason=CLIENT_FILE_NOT_FOUND"
            )
            skipped += 1
            continue

        cmd = [
            sys.executable, str(bridge), "register",
            str(workspace),
            "--game-root", str(client),
            "--target", target,
            "--workspace-path", c["workspace_path"],
            "--category", c["category"],
            "--subcategory", c["subcategory"],
            "--representation", c["representation"],
            "--owner", profile.get("owner_name", ""),
            "--class-code", profile.get("class_code", ""),
        ]
        run_checked(cmd)
        registered += 1

    final = inspect_asset(root, pp, profile, client, workspace)
    out = default_asset_manifest(root, profile)
    write_json(out, final)

    print("PT_CHARACTER_ASSET_V1_5")
    print("action=sync-workspace")
    print(f"registered={registered}")
    print(f"skipped={skipped}")
    print(f"manifest={out}")
    print(f"character_asset_check={final['character_asset_check']}")



def pipeline_manifest_dir(root, profile):
    return root / "logs/characters" / profile["profile_id"] / "all_lods"


def resolve_pipeline_manifest(root, profile, manifest_arg=None, name=None):
    if manifest_arg and name:
        raise ValueError("choose either --pipeline-manifest or --name, not both")

    if manifest_arg:
        path = resolve(root, manifest_arg)
    elif name:
        path = pipeline_manifest_dir(root, profile) / f"{name}_pipeline_manifest.json"
    else:
        candidates = sorted(
            pipeline_manifest_dir(root, profile).glob("*_pipeline_manifest.json"),
            key=lambda p: p.stat().st_mtime_ns,
            reverse=True,
        )
        passed = []
        for candidate in candidates:
            try:
                row = load_json(candidate)
            except Exception:
                continue
            if (
                row.get("pipeline_check") == "PASS"
                and row.get("profile_id") == profile["profile_id"]
            ):
                passed.append(candidate)
        if not passed:
            raise FileNotFoundError(
                "no PASS pipeline manifest found; use --pipeline-manifest or --name"
            )
        path = passed[0]

    if not path.is_file():
        raise FileNotFoundError(path)

    pm = load_json(path)
    if pm.get("pipeline_check") != "PASS":
        raise ValueError(f"pipeline manifest is not PASS: {path}")
    if pm.get("profile_id") != profile["profile_id"]:
        raise ValueError(
            f"pipeline manifest profile mismatch: {pm.get('profile_id')} "
            f"!= {profile['profile_id']}"
        )
    if pm.get("runtime_installed") not in (False, None):
        raise ValueError("pipeline manifest unexpectedly says runtime_installed=true")

    smd = pathlib.Path(pm["smd"]).expanduser().resolve()
    if not smd.is_file():
        raise FileNotFoundError(f"pipeline SMD missing: {smd}")
    actual_sha = sha256_file(smd)
    actual_size = smd.stat().st_size
    if actual_sha != pm.get("smd_sha256"):
        raise ValueError("pipeline SMD SHA differs from pipeline manifest")
    if actual_size != int(pm.get("smd_size")):
        raise ValueError("pipeline SMD size differs from pipeline manifest")

    return path, pm, smd


def workspace_model_entry(workspace, target):
    mp = workspace / "workspace_manifest.json"
    if not mp.is_file():
        raise FileNotFoundError(mp)
    wm = load_json(mp)
    wanted = norm_rel(target).lower()
    matches = [
        row for row in wm.get("files", [])
        if norm_rel(str(row.get("roundtrip_target", ""))).lower() == wanted
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one workspace entry for {target}; found {len(matches)}"
        )
    return wm, matches[0]


def classify_client_state(entry, client_sha):
    if client_sha is None:
        return "MISSING"
    source_sha = entry.get("source_sha256")
    if client_sha == source_sha:
        return "REGISTERED_SOURCE"

    managed = set()
    current = entry.get("published_build") or {}
    if current.get("sha256"):
        managed.add(current["sha256"])
    for item in entry.get("published_history", []) or []:
        if item.get("sha256"):
            managed.add(item["sha256"])

    if client_sha in managed:
        if current.get("sha256") == client_sha:
            return "CURRENT_PUBLISHED_BUILD"
        return "PREVIOUSLY_PUBLISHED_BUILD"
    return "CLIENT_DRIFT"


def cmd_publish_build(args):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    workspace = resolve(root, args.workspace)
    bridge = root / "summit_workspace_asset_bridge_v1_2.py"
    if not bridge.is_file():
        raise FileNotFoundError(bridge)

    manifest, pm, smd = resolve_pipeline_manifest(
        root, profile, args.pipeline_manifest, args.name
    )

    cmd = [
        sys.executable, str(bridge), "publish",
        str(workspace),
        "--pipeline-manifest", str(manifest),
        "--target", profile["roundtrip_target"],
    ]
    if args.replace_published:
        cmd.append("--replace-published")

    print("PT_CHARACTER_ASSET_V1_5")
    print("action=publish-build")
    print(f"profile_id={profile['profile_id']}")
    print(f"asset_set_id={profile.get('asset_set_id')}")
    print(f"pipeline_manifest={manifest}")
    print(f"smd={smd}")
    print(f"smd_size={pm['smd_size']}")
    print(f"smd_sha256={pm['smd_sha256']}")
    run_checked(cmd)
    print("character_asset_publish_build_check=PASS")


def cmd_status(args):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    workspace = resolve(root, args.workspace)

    wm, entry = workspace_model_entry(workspace, profile["roundtrip_target"])
    workspace_path = resolve(workspace, entry["workspace_path"])
    workspace_sha = sha256_file(workspace_path) if workspace_path.is_file() else None
    workspace_size = workspace_path.stat().st_size if workspace_path.is_file() else None

    game_root_raw = args.client_root or wm.get("game_root")
    client_root = resolve(root, game_root_raw) if game_root_raw else None
    client_path = (
        safe_client_path(client_root, profile["roundtrip_target"])
        if client_root else None
    )
    client_sha = sha256_file(client_path) if client_path and client_path.is_file() else None
    client_size = client_path.stat().st_size if client_path and client_path.is_file() else None
    client_state = classify_client_state(entry, client_sha)

    current_pub = entry.get("published_build") or {}
    current_pub_sha = current_pub.get("sha256")
    workspace_state = (
        "CURRENT_PUBLISHED_BUILD"
        if current_pub_sha and workspace_sha == current_pub_sha
        else (
            "REGISTERED_SOURCE"
            if workspace_sha == entry.get("source_sha256")
            else "WORKSPACE_DRIFT"
        )
    )

    manifests = sorted(
        pipeline_manifest_dir(root, profile).glob("*_pipeline_manifest.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    pass_builds = []
    for mp in manifests:
        try:
            row = load_json(mp)
        except Exception:
            continue
        if (
            row.get("pipeline_check") == "PASS"
            and row.get("profile_id") == profile["profile_id"]
        ):
            pass_builds.append({
                "manifest": str(mp),
                "smd": row.get("smd"),
                "sha256": row.get("smd_sha256"),
                "size": row.get("smd_size"),
                "published": bool(row.get("roundtrip_published")),
                "timestamp": row.get("timestamp"),
            })

    status = {
        "tool": "PT_CHARACTER_ASSET_V1_5",
        "action": "status",
        "profile_id": profile["profile_id"],
        "asset_set_id": profile.get("asset_set_id"),
        "roundtrip_target": profile["roundtrip_target"],
        "workspace": str(workspace),
        "workspace_path": str(workspace_path),
        "workspace_sha256": workspace_sha,
        "workspace_size": workspace_size,
        "workspace_state": workspace_state,
        "client_root": str(client_root) if client_root else None,
        "client_path": str(client_path) if client_path else None,
        "client_sha256": client_sha,
        "client_size": client_size,
        "client_state": client_state,
        "registered_source_sha256": entry.get("source_sha256"),
        "current_published_sha256": current_pub_sha,
        "managed_published_sha_count": len({
            x.get("sha256")
            for x in entry.get("published_history", []) or []
            if x.get("sha256")
        }),
        "pass_build_count": len(pass_builds),
        "latest_pass_build": pass_builds[0] if pass_builds else None,
        "status_check": (
            "PASS"
            if workspace_state != "WORKSPACE_DRIFT"
            and client_state != "CLIENT_DRIFT"
            else "FAIL"
        ),
    }

    if args.out:
        out = resolve(root, args.out)
        write_json(out, status)
    else:
        out = None

    print("PT_CHARACTER_ASSET_V1_5")
    print("action=status")
    print(f"profile_id={profile['profile_id']}")
    print(f"asset_set_id={profile.get('asset_set_id')}")
    print(f"roundtrip_target={profile['roundtrip_target']}")
    print(f"workspace_state={workspace_state}")
    print(f"workspace_sha256={workspace_sha}")
    print(f"client_state={client_state}")
    print(f"client_sha256={client_sha}")
    print(f"registered_source_sha256={entry.get('source_sha256')}")
    print(f"current_published_sha256={current_pub_sha}")
    print(f"managed_published_sha_count={status['managed_published_sha_count']}")
    print(f"pass_build_count={len(pass_builds)}")
    if pass_builds:
        latest = pass_builds[0]
        print(f"latest_pass_manifest={latest['manifest']}")
        print(f"latest_pass_sha256={latest['sha256']}")
        print(f"latest_pass_published={str(latest['published']).lower()}")
    if out:
        print(f"report={out}")
    print(f"character_asset_status_check={status['status_check']}")
    if status["status_check"] != "PASS":
        raise SystemExit(2)



def cmd_build(args):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    pipeline = root / "pt_character_multi_object_lod_pipeline_v2.py"
    if not pipeline.is_file():
        raise FileNotFoundError(pipeline)

    cmd = [
        sys.executable, str(pipeline),
        "--root", str(root),
        "--profile", str(pp),
        "--artist", args.artist,
        "--all-lods",
    ]
    if args.name:
        cmd += ["--name", args.name]
    if args.overwrite:
        cmd.append("--overwrite")
    if args.force_test:
        print(
            "WARNING: --force-test is engineering-only; visual deformation "
            "is the artist's responsibility."
        )
        cmd.append("--force-test")
    if args.client_root:
        cmd += ["--client-root", args.client_root]
    if args.publish:
        if not args.workspace:
            raise ValueError("--publish requires --workspace")
        cmd += [
            "--roundtrip-workspace", args.workspace,
            "--roundtrip-target", profile["roundtrip_target"],
        ]
        if args.replace_published:
            cmd.append("--replace-published")

    run_checked(cmd)


def cmd_deploy(args, apply):
    root = args.root.resolve()
    pp = resolve(root, args.profile)
    profile = load_json(pp)
    restore = root / "summit_roundtrip_restore_v4.py"
    if not restore.is_file():
        raise FileNotFoundError(restore)
    workspace = resolve(root, args.workspace)

    cmd = [
        sys.executable, str(restore),
        str(workspace),
        "--target", profile["roundtrip_target"],
    ]
    if apply:
        cmd.append("--apply")
    run_checked(cmd)



def texture_core_command(args, subcommand):
    root = args.root.resolve()
    tool = root / "pt_character_texture_v1_2.py"
    if not tool.is_file():
        raise FileNotFoundError(tool)
    cmd = [
        sys.executable, str(tool),
        "--root", str(root),
        "--profile", str(resolve(root, args.profile)),
        subcommand,
    ]
    if hasattr(args, "workspace") and args.workspace:
        cmd += ["--workspace", args.workspace]
    if hasattr(args, "role") and args.role:
        cmd += ["--role", args.role]
    if hasattr(args, "overwrite") and args.overwrite:
        cmd.append("--overwrite")
    if hasattr(args, "edited") and args.edited:
        cmd += ["--edited", args.edited]
    if hasattr(args, "name") and args.name:
        cmd += ["--name", args.name]
    if hasattr(args, "artist") and args.artist:
        cmd += ["--artist", args.artist]
    if hasattr(args, "texture") and args.texture:
        cmd += ["--texture", args.texture]
    if hasattr(args, "out") and args.out:
        cmd += ["--out", args.out]
    if hasattr(args, "build_manifest") and args.build_manifest:
        cmd += ["--build-manifest", args.build_manifest]
    if hasattr(args, "replace_published") and args.replace_published:
        cmd.append("--replace-published")
    run_checked(cmd)


def cmd_texture_inspect(args): texture_core_command(args, "inspect")
def cmd_texture_prepare(args): texture_core_command(args, "prepare")
def cmd_texture_build(args): texture_core_command(args, "build")
def cmd_texture_bind_blend(args): texture_core_command(args, "bind-blend")
def cmd_texture_publish(args): texture_core_command(args, "publish")
def cmd_texture_status(args): texture_core_command(args, "status")
def cmd_texture_deploy_plan(args): texture_core_command(args, "deploy-plan")
def cmd_texture_deploy(args): texture_core_command(args, "deploy")



def parser():
    default_root = pathlib.Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=pathlib.Path, default=default_root)
    p.add_argument(
        "--profile",
        default="profiles/pt_character_profile_pikeman_c01_m5_v2.json",
    )
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("inspect")
    i.add_argument("--client-root", required=True)
    i.add_argument("--workspace")
    i.add_argument("--out")
    i.set_defaults(func=cmd_inspect)

    s = sub.add_parser("sync-workspace")
    s.add_argument("--client-root", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_sync_workspace)

    b = sub.add_parser("build")
    b.add_argument("--artist", required=True)
    b.add_argument("--name")
    b.add_argument("--client-root")
    b.add_argument("--workspace")
    b.add_argument("--publish", action="store_true")
    b.add_argument("--replace-published", action="store_true")
    b.add_argument("--force-test", action="store_true")
    b.add_argument("--overwrite", action="store_true")
    b.set_defaults(func=cmd_build)

    pb = sub.add_parser("publish-build")
    pb.add_argument("--workspace", required=True)
    choose = pb.add_mutually_exclusive_group()
    choose.add_argument("--pipeline-manifest")
    choose.add_argument("--name")
    pb.add_argument("--replace-published", action="store_true")
    pb.set_defaults(func=cmd_publish_build)

    st = sub.add_parser("status")
    st.add_argument("--workspace", required=True)
    st.add_argument("--client-root")
    st.add_argument("--out")
    st.set_defaults(func=cmd_status)

    ti = sub.add_parser("texture-inspect")
    ti.add_argument("--workspace", required=True)
    ti.add_argument("--role", default="texture")
    ti.set_defaults(func=cmd_texture_inspect)

    tp = sub.add_parser("texture-prepare")
    tp.add_argument("--workspace", required=True)
    tp.add_argument("--role", default="texture")
    tp.add_argument("--overwrite", action="store_true")
    tp.set_defaults(func=cmd_texture_prepare)

    tb = sub.add_parser("texture-build")
    tb.add_argument("--role", default="texture")
    tb.add_argument("--edited")
    tb.add_argument("--name")
    tb.add_argument("--overwrite", action="store_true")
    tb.set_defaults(func=cmd_texture_build)

    tbb = sub.add_parser("texture-bind-blend")
    tbb.add_argument("--role", default="texture")
    tbb.add_argument("--artist", required=True)
    tbb.add_argument("--texture")
    tbb.add_argument("--out", required=True)
    tbb.add_argument("--overwrite", action="store_true")
    tbb.set_defaults(func=cmd_texture_bind_blend)

    tpub = sub.add_parser("texture-publish")
    tpub.add_argument("--workspace", required=True)
    tpub.add_argument("--role", default="texture")
    tpub.add_argument("--build-manifest")
    tpub.add_argument("--replace-published", action="store_true")
    tpub.set_defaults(func=cmd_texture_publish)

    tst = sub.add_parser("texture-status")
    tst.add_argument("--workspace", required=True)
    tst.add_argument("--role", default="texture")
    tst.set_defaults(func=cmd_texture_status)

    tdp = sub.add_parser("texture-deploy-plan")
    tdp.add_argument("--workspace", required=True)
    tdp.add_argument("--role", default="texture")
    tdp.set_defaults(func=cmd_texture_deploy_plan)

    tde = sub.add_parser("texture-deploy")
    tde.add_argument("--workspace", required=True)
    tde.add_argument("--role", default="texture")
    tde.set_defaults(func=cmd_texture_deploy)

    dp = sub.add_parser("deploy-plan")
    dp.add_argument("--workspace", required=True)
    dp.set_defaults(func=lambda a: cmd_deploy(a, False))

    d = sub.add_parser("deploy")
    d.add_argument("--workspace", required=True)
    d.set_defaults(func=lambda a: cmd_deploy(a, True))

    return p


def main():
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"character_asset_check=FAIL: {type(exc).__name__}: {exc}")
        raise
