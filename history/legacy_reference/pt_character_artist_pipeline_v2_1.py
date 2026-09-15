#!/usr/bin/env python3
"""
PT Character Artist Pipeline V2.1

Profile-driven orchestration:
  Artist Master
  -> generic rigid-skin Normalize Copy
  -> optional TEST-ONLY ambiguity resolver
  -> generic free-mesh validator
  -> generic SMD Model 0.62 writer
  -> independent V3 reimport
  -> optional publish to registered roundtrip workspace

Never installs into the game client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
from datetime import datetime, timezone


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve(root: pathlib.Path, value: str | pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def blender_command():
    raw = os.environ.get("PT_BLENDER_COMMAND")
    if raw:
        return shlex.split(raw)
    return ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]


def run_stage(title, cmd, log_path):
    print(f"\n=== {title} ===")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"{title} failed (exit={rc}); log={log_path}")


def lod_for_object(profile, target):
    for lod, objects in profile.get("lod_groups", {}).items():
        if target in objects:
            return lod
    return "high"


def validate_profile(root, profile_path, profile):
    required = [
        "profile_id",
        "model_smd",
        "model_smd_sha256",
        "skeleton_smb",
        "model_info_inx",
        "roundtrip_target",
        "known_mesh_objects",
    ]
    missing = [k for k in required if k not in profile]
    if missing:
        raise ValueError(f"profile missing fields: {missing}")

    source = resolve(root, profile["model_smd"])
    skeleton = resolve(root, profile["skeleton_smb"])
    model_info = resolve(root, profile["model_info_inx"])

    for p in (source, skeleton, model_info):
        if not p.is_file():
            raise FileNotFoundError(p)

    actual = sha256_file(source)
    expected = profile["model_smd_sha256"].lower()
    if actual != expected:
        raise RuntimeError(
            f"profile source SHA mismatch: {actual} != {expected}"
        )

    objects = profile["known_mesh_objects"]
    if len(objects) != len(set(objects)):
        raise ValueError("profile known_mesh_objects contains duplicates")

    for lod, names in profile.get("lod_groups", {}).items():
        unknown = [x for x in names if x not in objects]
        if unknown:
            raise ValueError(f"profile LOD {lod} references unknown objects: {unknown}")

    return source, skeleton, model_info


def tool_paths(root):
    return {
        "normalize": root / "pt_rigid_skin_normalize_copy_v2.py",
        "force": root / "pt_rigid_skin_force_resolve_test_v2.py",
        "validate": root / "pt_free_mesh_validate_v2.py",
        "writer": root / "pt_blender_to_smd_free_mesh_v3.py",
        "importer": root / "history_py/pt_smd_blender_import_v3_static_armature.py",
        "bridge": root / "summit_workspace_asset_bridge_v1_1.py",
    }


def cmd_doctor(args):
    root = args.root.resolve()
    profile_path = resolve(root, args.profile)
    profile = load_json(profile_path)
    source, skeleton, model_info = validate_profile(root, profile_path, profile)
    tools = tool_paths(root)

    print("PT_CHARACTER_ARTIST_PIPELINE_V2_1_DOCTOR")
    print(f"root={root}")
    print(f"profile={profile_path}")
    print(f"profile_id={profile['profile_id']}")
    print(f"source={source}")
    print(f"source_sha256={sha256_file(source)}")
    print(f"skeleton={skeleton}")
    print(f"model_info={model_info}")

    failed = False
    for name, path in tools.items():
        if name == "bridge":
            # Optional unless publication is requested, but report it.
            state = "OK" if path.is_file() else "OPTIONAL_MISSING"
        else:
            state = "OK" if path.is_file() else "MISSING"
            if not path.is_file():
                failed = True
        print(f"tool_{name}={state}:{path}")

    print(f"known_mesh_objects={len(profile['known_mesh_objects'])}")
    print(f"lod_groups={profile.get('lod_groups', {})}")
    print("pipeline_doctor_check=" + ("FAIL" if failed else "PASS"))
    if failed:
        raise SystemExit(1)


def cmd_list_objects(args):
    root = args.root.resolve()
    profile_path = resolve(root, args.profile)
    profile = load_json(profile_path)
    validate_profile(root, profile_path, profile)

    lod_lookup = {}
    for lod, names in profile.get("lod_groups", {}).items():
        for name in names:
            lod_lookup[name] = lod

    print("PT_CHARACTER_PROFILE_OBJECTS")
    print(f"profile_id={profile['profile_id']}")
    for name in profile["known_mesh_objects"]:
        counts = profile.get("baseline_counts", {}).get(name, {})
        print(
            f"{name}\t"
            f"lod={lod_lookup.get(name, 'unassigned')}\t"
            f"V={counts.get('vertices', '?')}\t"
            f"F={counts.get('faces', '?')}"
        )


def cmd_run(args):
    root = args.root.resolve()
    profile_path = resolve(root, args.profile)
    profile = load_json(profile_path)
    source, skeleton, model_info = validate_profile(root, profile_path, profile)
    tools = tool_paths(root)

    for key in ("normalize", "force", "validate", "writer", "importer"):
        if not tools[key].is_file():
            raise FileNotFoundError(f"required tool missing: {tools[key]}")

    target = args.object
    if target not in profile["known_mesh_objects"]:
        raise ValueError(
            f"{target!r} is not registered in profile {profile['profile_id']}"
        )

    artist = resolve(root, args.artist)
    if not artist.is_file():
        raise FileNotFoundError(artist)

    name = args.name or f"{profile['profile_id']}_{target}"
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        raise ValueError("--name may contain only letters, numbers, dot, underscore, hyphen")

    lod = args.lod or lod_for_object(profile, target)
    if lod not in ("high", "default", "low"):
        raise ValueError("--lod must be high, default or low")

    build_dir = root / "pt_build" / "characters" / profile["profile_id"] / target
    log_dir = root / "logs" / "characters" / profile["profile_id"] / target
    blend_dir = root / "blender"

    normalized = blend_dir / f"{name}_game_normalized.blend"
    forced = blend_dir / f"{name}_game_normalized_forced_test.blend"
    reimport = blend_dir / f"{name}_reimport.blend"
    smd_out = build_dir / f"{name}.smd"

    normalize_json = log_dir / f"{name}_normalize.json"
    force_json = log_dir / f"{name}_force_resolve_test.json"
    validate_json = log_dir / f"{name}_validation.json"
    export_json = build_dir / f"{name}_export_report.json"
    manifest = log_dir / f"{name}_pipeline_manifest.json"

    normalize_log = log_dir / f"{name}_normalize.log"
    force_log = log_dir / f"{name}_force_resolve_test.log"
    validate_log = log_dir / f"{name}_validation.log"
    export_log = log_dir / f"{name}_export.log"
    reimport_log = log_dir / f"{name}_reimport.log"

    outputs = [
        normalized, forced, reimport, smd_out,
        normalize_json, force_json, validate_json, export_json, manifest,
    ]
    if not args.overwrite:
        existing = [p for p in outputs if p.exists()]
        if existing:
            raise FileExistsError(
                "generated outputs already exist; use --overwrite intentionally: "
                + ", ".join(str(p) for p in existing)
            )
    else:
        for p in outputs:
            if p.is_file() or p.is_symlink():
                p.unlink()

    for d in (build_dir, log_dir, blend_dir):
        d.mkdir(parents=True, exist_ok=True)

    source_sha = profile["model_smd_sha256"]
    artist_sha = sha256_file(artist)
    bcmd = blender_command()

    normalize_cmd = bcmd + [
        "--background", str(artist),
        "--python-exit-code", "1",
        "--python", str(tools["normalize"]), "--",
        "--object", target,
        "--out", str(normalized),
        "--report", str(normalize_json),
    ]
    if args.overwrite:
        normalize_cmd.append("--overwrite")
    run_stage("STAGE 1: NORMALIZE COPY", normalize_cmd, normalize_log)

    nr = load_json(normalize_json)
    unresolved = int(nr["unresolved"])
    game_blend = normalized
    force_used = False

    if unresolved:
        if not args.force_test:
            partial = {
                "tool": "PT_CHARACTER_ARTIST_PIPELINE_V2_1",
                "pipeline_check": "REVIEW_REQUIRED",
                "profile": str(profile_path),
                "profile_id": profile["profile_id"],
                "object": target,
                "lod": lod,
                "artist_master": str(artist),
                "artist_master_sha256": artist_sha,
                "artist_master_overwritten": False,
                "normalized_copy": str(normalized),
                "unresolved_vertices": unresolved,
                "review_group": nr.get("review_group"),
                "runtime_installed": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            write_json(manifest, partial)
            print("\nPIPELINE_STATUS=REVIEW_REQUIRED")
            print(f"object={target}")
            print(f"unresolved={unresolved}")
            print(f"normalized_copy={normalized}")
            print(f"manifest={manifest}")
            print("The artist master was preserved.")
            raise SystemExit(3)

        force_cmd = bcmd + [
            "--background", str(normalized),
            "--python-exit-code", "1",
            "--python", str(tools["force"]), "--",
            "--object", target,
            "--out", str(forced),
            "--report", str(force_json),
        ]
        if args.overwrite:
            force_cmd.append("--overwrite")
        run_stage("STAGE 2: FORCE AMBIGUOUS SKIN (TEST ONLY)", force_cmd, force_log)
        fr = load_json(force_json)
        if int(fr["invalid_after"]) != 0:
            raise RuntimeError("force resolver left invalid vertices")
        game_blend = forced
        force_used = True
    else:
        print("\n=== STAGE 2: FORCE AMBIGUOUS SKIN ===")
        print("SKIPPED=no ambiguous vertices")

    validate_cmd = bcmd + [
        "--background", str(game_blend),
        "--python-exit-code", "1",
        "--python", str(tools["validate"]), "--",
        "--smd", str(source),
        "--skeleton", str(skeleton),
        "--object", target,
        "--expected-source-sha256", source_sha,
        "--report", str(validate_json),
    ]
    run_stage("STAGE 3: VALIDATE GAME COPY", validate_cmd, validate_log)
    vr = load_json(validate_json)
    if vr.get("validation_check") != "PASS":
        raise RuntimeError("validator report is not PASS")

    writer_cmd = bcmd + [
        "--background", str(game_blend),
        "--python-exit-code", "1",
        "--python", str(tools["writer"]), "--",
        "--smd", str(source),
        "--skeleton", str(skeleton),
        "--object", target,
        "--expected-source-sha256", source_sha,
        "--out", str(smd_out),
        "--report", str(export_json),
    ]
    run_stage("STAGE 4: EXPORT SMD", writer_cmd, export_log)
    er = load_json(export_json)
    if er.get("semantic_check") != "PASS" or er.get("free_mesh_writer_check") != "PASS":
        raise RuntimeError("writer report is not PASS")

    smd_sha = sha256_file(smd_out)
    smd_size = smd_out.stat().st_size
    if smd_sha != er["output_sha256"] or smd_size != int(er["output_size"]):
        raise RuntimeError("build SHA/size differs from writer report")

    counts = er["output_counts"]
    reimport_cmd = bcmd + [
        "--background",
        "--python-exit-code", "1",
        "--python", str(tools["importer"]), "--",
        "--smd", str(smd_out),
        "--skeleton", str(skeleton),
        "--model-info", str(model_info),
        "--lod", lod,
        "--client-root", str(resolve(root, args.client_root)) if args.client_root else profile.get("client_root", os.environ.get("PT_CLIENT_ROOT", "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")),
        "--out", str(reimport),
        "--no-pack",
    ]
    run_stage("STAGE 5: INDEPENDENT V3 REIMPORT", reimport_cmd, reimport_log)
    reimport_text = reimport_log.read_text(encoding="utf-8")
    if "static_armature_import_check=PASS" not in reimport_text:
        raise RuntimeError("independent reimport did not PASS")
    expected_line = (
        f"OBJECT {target}: V={counts['vertices']} "
        f"F={counts['faces']} UV={counts['texlinks']}"
    )
    if expected_line not in reimport_text:
        raise RuntimeError(
            f"independent reimport counts missing/mismatch; expected: {expected_line}"
        )

    final_manifest = {
        "tool": "PT_CHARACTER_ARTIST_PIPELINE_V2_1",
        "pipeline_check": "PASS",
        "profile": str(profile_path),
        "profile_id": profile["profile_id"],
        "object": target,
        "lod": lod,
        "artist_master": str(artist),
        "artist_master_sha256": artist_sha,
        "artist_master_overwritten": False,
        "normalized_copy": str(normalized),
        "game_copy_used": str(game_blend),
        "test_force_ambiguous_used": force_used,
        "normalize_unresolved_before_test_force": unresolved,
        "validator_report": str(validate_json),
        "export_report": str(export_json),
        "smd": str(smd_out),
        "smd_size": smd_size,
        "smd_sha256": smd_sha,
        "reimport_blend": str(reimport),
        "output_counts": counts,
        "runtime_installed": False,
        "roundtrip_published": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_json(manifest, final_manifest)

    if args.roundtrip_workspace:
        if not tools["bridge"].is_file():
            raise FileNotFoundError(tools["bridge"])
        workspace = resolve(root, args.roundtrip_workspace)
        target_path = args.roundtrip_target or profile["roundtrip_target"]
        publish_cmd = [
            sys.executable, str(tools["bridge"]), "publish",
            str(workspace),
            "--pipeline-manifest", str(manifest),
            "--target", target_path,
        ]
        if args.replace_published:
            publish_cmd.append("--replace-published")
        run_stage(
            "STAGE 6: PUBLISH VALIDATED BUILD TO ROUNDTRIP WORKSPACE",
            publish_cmd,
            log_dir / f"{name}_publish.log",
        )
        final_manifest["roundtrip_published"] = True
        final_manifest["roundtrip_workspace"] = str(workspace)
        final_manifest["roundtrip_target"] = target_path
        final_manifest["roundtrip_replace_published"] = bool(args.replace_published)
        write_json(manifest, final_manifest)

    print("\nPT_CHARACTER_ARTIST_PIPELINE_V2_1")
    print(f"profile_id={profile['profile_id']}")
    print(f"object={target}")
    print(f"lod={lod}")
    print(f"artist_master={artist}")
    print("artist_master_overwritten=False")
    print(f"test_force_ambiguous_used={str(force_used).lower()}")
    print(
        f"output_counts={counts['vertices']}/"
        f"{counts['faces']}/{counts['texlinks']}"
    )
    print(f"smd={smd_out}")
    print(f"smd_size={smd_size}")
    print(f"smd_sha256={smd_sha}")
    print(f"reimport={reimport}")
    print(f"manifest={manifest}")
    print(f"roundtrip_published={str(final_manifest['roundtrip_published']).lower()}")
    print("runtime_installed=False")
    print("pipeline_check=PASS")


def parser():
    root_default = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=pathlib.Path, default=root_default)
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor")
    d.add_argument("--profile", default="profiles/pt_character_profile_pikeman_c01_m5_v1.json")
    d.set_defaults(func=cmd_doctor)

    l = sub.add_parser("list-objects")
    l.add_argument("--profile", default="profiles/pt_character_profile_pikeman_c01_m5_v1.json")
    l.set_defaults(func=cmd_list_objects)

    r = sub.add_parser("run")
    r.add_argument("--profile", default="profiles/pt_character_profile_pikeman_c01_m5_v1.json")
    r.add_argument("--artist", required=True)
    r.add_argument("--object", required=True)
    r.add_argument("--name")
    r.add_argument("--lod", choices=["high", "default", "low"])
    r.add_argument("--force-test", action="store_true")
    r.add_argument("--overwrite", action="store_true")
    r.add_argument("--client-root")
    r.add_argument("--roundtrip-workspace")
    r.add_argument("--roundtrip-target")
    r.add_argument(
        "--replace-published",
        action="store_true",
        help="intentionally replace an already published workspace build",
    )
    r.set_defaults(func=cmd_run)

    return ap


def main():
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"pipeline_check=FAIL: {type(exc).__name__}: {exc}")
        raise
