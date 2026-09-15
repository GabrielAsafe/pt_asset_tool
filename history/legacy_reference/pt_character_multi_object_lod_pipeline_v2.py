#!/usr/bin/env python3
"""
PT Character Multi-Object / LOD Pipeline V2

Production-oriented orchestration for multiple mesh objects from one character
profile.

Selection:
  --all-lods
or
  --lod high|default|low
or
  --object NAME --object NAME ...

--all-lods rebuilds the union of profile high/default/low groups into ONE SMD
and independently reimports the final file once for each LOD.

Flow:
  artist master
  -> conservative normalization for every target
  -> optional TEST-ONLY forced resolution for unresolved target(s)
  -> multi-object validation
  -> ONE combined multi-object SMD build
  -> ONE independent V3 reimport
  -> optional roundtrip publish

The runtime client is never modified here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def sha256_file(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve(root, value):
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


def validate_profile(root, profile):
    for key in (
        "profile_id", "model_smd", "model_smd_sha256",
        "skeleton_smb", "model_info_inx", "roundtrip_target",
        "known_mesh_objects", "lod_groups",
    ):
        if key not in profile:
            raise ValueError(f"profile missing {key}")

    source = resolve(root, profile["model_smd"])
    skeleton = resolve(root, profile["skeleton_smb"])
    model_info = resolve(root, profile["model_info_inx"])
    for p in (source, skeleton, model_info):
        if not p.is_file():
            raise FileNotFoundError(p)

    actual = sha256_file(source)
    expected = profile["model_smd_sha256"].lower()
    if actual != expected:
        raise RuntimeError(f"source SHA mismatch: {actual} != {expected}")

    return source, skeleton, model_info


def selected_targets(args, profile):
    if args.all_lods:
        targets = []
        for lod in ("high", "default", "low"):
            names = list(profile["lod_groups"].get(lod, []))
            if not names:
                raise ValueError(f"profile has no objects for LOD {lod}")
            for name in names:
                if name not in targets:
                    targets.append(name)
        return targets, ["high", "default", "low"], "all_lods"

    if args.lod:
        targets = list(profile["lod_groups"].get(args.lod, []))
        if not targets:
            raise ValueError(f"profile has no objects for LOD {args.lod}")
        return targets, [args.lod], f"lod_{args.lod}"

    targets = list(dict.fromkeys(args.object or []))
    if not targets:
        raise ValueError("choose --all-lods, --lod or at least one --object")

    unknown = [x for x in targets if x not in profile["known_mesh_objects"]]
    if unknown:
        raise ValueError(f"objects not in profile: {unknown}")

    lods = [
        lod
        for lod in ("high", "default", "low")
        if any(x in profile["lod_groups"].get(lod, []) for x in targets)
    ]
    reimports = [args.reimport_lod] if args.reimport_lod else (lods[:1] or ["high"])
    return targets, reimports, "multi_" + "_".join(targets)


def parse_args():
    root_default = pathlib.Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=pathlib.Path, default=root_default)
    p.add_argument(
        "--profile",
        default="profiles/pt_character_profile_pikeman_c01_m5_v1.json",
    )
    p.add_argument("--artist", required=True)

    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument(
        "--all-lods",
        action="store_true",
        help="rebuild profile HIGH + DEFAULT + LOW objects in one SMD",
    )
    sel.add_argument("--lod", choices=["high", "default", "low"])
    sel.add_argument("--object", action="append")

    p.add_argument("--reimport-lod", choices=["high", "default", "low"])
    p.add_argument("--name")
    p.add_argument("--force-test", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--client-root")
    p.add_argument("--roundtrip-workspace")
    p.add_argument("--roundtrip-target")
    p.add_argument("--replace-published", action="store_true")
    return p.parse_args()


def main():
    a = parse_args()
    root = a.root.resolve()
    profile_path = resolve(root, a.profile)
    profile = load_json(profile_path)
    source, skeleton, model_info = validate_profile(root, profile)
    targets, reimport_lods, selection_scope = selected_targets(a, profile)

    artist = resolve(root, a.artist)
    if not artist.is_file():
        raise FileNotFoundError(artist)

    name = a.name or (
        f"{profile['profile_id']}_all_lods"
        if a.all_lods else
        (
            f"{profile['profile_id']}_lod_{a.lod}"
            if a.lod else
            f"{profile['profile_id']}_{'_'.join(targets)}"
        )
    )
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        raise ValueError("unsafe --name")

    tools = {
        "normalize": root / "pt_rigid_skin_normalize_copy_v2.py",
        "force": root / "pt_rigid_skin_force_resolve_test_v2.py",
        "validator": root / "pt_free_mesh_validate_multi_v1.py",
        "writer": root / "pt_blender_to_smd_free_mesh_v4_multi.py",
        "importer": root / "history_py/pt_smd_blender_import_v3_static_armature.py",
        "bridge": root / "summit_workspace_asset_bridge_v1_1.py",
    }
    for key in ("normalize", "force", "validator", "writer", "importer"):
        if not tools[key].is_file():
            raise FileNotFoundError(tools[key])

    scope = selection_scope
    build_dir = root / "pt_build/characters" / profile["profile_id"] / scope
    log_dir = root / "logs/characters" / profile["profile_id"] / scope
    work_dir = root / "blender/_pipeline_work" / name
    blend_dir = root / "blender"

    normalized_final = blend_dir / f"{name}_game_normalized.blend"
    forced_final = blend_dir / f"{name}_game_normalized_forced_test.blend"
    game_final = forced_final if a.force_test else normalized_final
    smd_out = build_dir / f"{name}.smd"
    validation_report = log_dir / f"{name}_validation.json"
    export_report = build_dir / f"{name}_export_report.json"
    manifest = log_dir / f"{name}_pipeline_manifest.json"

    generated = [
        normalized_final, forced_final, smd_out,
        validation_report, export_report, manifest,
    ]
    for _lod in reimport_lods:
        generated.append(
            blend_dir / (
                f"{name}_reimport_{_lod}.blend"
                if len(reimport_lods) > 1
                else f"{name}_reimport.blend"
            )
        )
    if not a.overwrite:
        existing = [p for p in generated if p.exists()]
        if existing:
            raise FileExistsError(
                "outputs exist; use --overwrite intentionally: "
                + ", ".join(str(x) for x in existing)
            )
        if work_dir.exists():
            raise FileExistsError(f"work dir exists: {work_dir}")
    else:
        for p in generated:
            if p.is_file() or p.is_symlink():
                p.unlink()
        if work_dir.exists():
            shutil.rmtree(work_dir)

    for d in (build_dir, log_dir, work_dir, blend_dir):
        d.mkdir(parents=True, exist_ok=True)

    bcmd = blender_command()
    current = artist
    normalize_rows = []
    unresolved_targets = []

    # Normalize every target into a chain of private work copies.
    for idx, target in enumerate(targets, 1):
        out = work_dir / f"{idx:02d}_normalize_{target}.blend"
        rp = log_dir / f"{name}_normalize_{target}.json"
        lp = log_dir / f"{name}_normalize_{target}.log"

        cmd = bcmd + [
            "--background", str(current),
            "--python-exit-code", "1",
            "--python", str(tools["normalize"]), "--",
            "--object", target,
            "--out", str(out),
            "--report", str(rp),
            "--overwrite",
        ]
        run_stage(f"NORMALIZE {target}", cmd, lp)
        row = load_json(rp)
        normalize_rows.append(row)
        if int(row["unresolved"]) > 0:
            unresolved_targets.append(target)
        current = out

    shutil.copy2(current, normalized_final)
    if sha256_file(current) != sha256_file(normalized_final):
        raise RuntimeError("final normalized copy verification failed")

    if unresolved_targets and not a.force_test:
        partial = {
            "tool": "PT_CHARACTER_MULTI_OBJECT_LOD_PIPELINE_V2",
            "pipeline_check": "REVIEW_REQUIRED",
            "profile": str(profile_path),
            "profile_id": profile["profile_id"],
            "selection": {
                "all_lods": bool(a.all_lods),
                "lod": a.lod,
                "objects": targets,
                "reimport_lods": reimport_lods,
            },
            "artist_master": str(artist),
            "artist_master_sha256": sha256_file(artist),
            "artist_master_overwritten": False,
            "normalized_copy": str(normalized_final),
            "unresolved_targets": unresolved_targets,
            "normalize_reports": normalize_rows,
            "runtime_installed": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        write_json(manifest, partial)
        print("\nPIPELINE_STATUS=REVIEW_REQUIRED")
        print(f"objects={targets}")
        print(f"unresolved_targets={unresolved_targets}")
        print(f"normalized_copy={normalized_final}")
        print(f"manifest={manifest}")
        raise SystemExit(3)

    current_game = normalized_final
    force_rows = []
    if unresolved_targets:
        current = normalized_final
        for idx, target in enumerate(unresolved_targets, 1):
            out = work_dir / f"{idx:02d}_force_{target}.blend"
            rp = log_dir / f"{name}_force_{target}.json"
            lp = log_dir / f"{name}_force_{target}.log"
            cmd = bcmd + [
                "--background", str(current),
                "--python-exit-code", "1",
                "--python", str(tools["force"]), "--",
                "--object", target,
                "--out", str(out),
                "--report", str(rp),
                "--overwrite",
            ]
            run_stage(f"FORCE {target} (TEST ONLY)", cmd, lp)
            row = load_json(rp)
            if int(row["invalid_after"]) != 0:
                raise RuntimeError(f"{target}: force resolver left invalid vertices")
            force_rows.append(row)
            current = out

        shutil.copy2(current, forced_final)
        if sha256_file(current) != sha256_file(forced_final):
            raise RuntimeError("final force-test copy verification failed")
        current_game = forced_final

    # Validate all targets in one Blender session.
    validator_cmd = bcmd + [
        "--background", str(current_game),
        "--python-exit-code", "1",
        "--python", str(tools["validator"]), "--",
        "--smd", str(source),
        "--skeleton", str(skeleton),
        "--report", str(validation_report),
        "--report-dir", str(log_dir / f"{name}_object_validation"),
        "--expected-source-sha256", profile["model_smd_sha256"],
    ]
    for target in targets:
        validator_cmd += ["--object", target]
    run_stage("VALIDATE MULTI-OBJECT", validator_cmd, log_dir / f"{name}_validation.log")
    vr = load_json(validation_report)
    if vr.get("validation_check") != "PASS":
        raise RuntimeError("multi-object validation did not PASS")

    # Build all target blocks in one final SMD.
    writer_cmd = bcmd + [
        "--background", str(current_game),
        "--python-exit-code", "1",
        "--python", str(tools["writer"]), "--",
        "--smd", str(source),
        "--skeleton", str(skeleton),
        "--out", str(smd_out),
        "--report", str(export_report),
        "--expected-source-sha256", profile["model_smd_sha256"],
    ]
    for target in targets:
        writer_cmd += ["--object", target]
    run_stage("EXPORT MULTI-OBJECT SMD", writer_cmd, log_dir / f"{name}_export.log")
    er = load_json(export_report)
    if (
        er.get("semantic_check") != "PASS"
        or er.get("multi_object_writer_check") != "PASS"
    ):
        raise RuntimeError("multi-object writer did not PASS")

    smd_sha = sha256_file(smd_out)
    smd_size = smd_out.stat().st_size
    if smd_sha != er["output_sha256"] or smd_size != int(er["output_size"]):
        raise RuntimeError("final SMD SHA/size differs from writer report")

    # Independent reimports for every requested LOD view.
    client_root = (
        resolve(root, a.client_root)
        if a.client_root else
        pathlib.Path(
            os.environ.get(
                "PT_CLIENT_ROOT",
                "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente",
            )
        )
    )

    output_by_name = {x["object"]: x["output_counts"] for x in er["objects"]}
    reimport_results = {}

    for reimport_lod in reimport_lods:
        reimport_out = (
            blend_dir / f"{name}_reimport_{reimport_lod}.blend"
            if len(reimport_lods) > 1
            else blend_dir / f"{name}_reimport.blend"
        )
        reimport_log = log_dir / f"{name}_reimport_{reimport_lod}.log"

        run_stage(
            f"INDEPENDENT V3 REIMPORT ({reimport_lod.upper()})",
            bcmd + [
                "--background",
                "--python-exit-code", "1",
                "--python", str(tools["importer"]), "--",
                "--smd", str(smd_out),
                "--skeleton", str(skeleton),
                "--model-info", str(model_info),
                "--lod", reimport_lod,
                "--client-root", str(client_root),
                "--out", str(reimport_out),
                "--no-pack",
            ],
            reimport_log,
        )

        reimport_text = reimport_log.read_text(encoding="utf-8")
        if "static_armature_import_check=PASS" not in reimport_text:
            raise RuntimeError(
                f"independent reimport did not PASS for LOD {reimport_lod}"
            )

        # The importer lists all objects, so verify all rebuilt target counts
        # on every independent reimport.
        for target in targets:
            c = output_by_name[target]
            expected = (
                f"OBJECT {target}: V={c['vertices']} "
                f"F={c['faces']} UV={c['texlinks']}"
            )
            if expected not in reimport_text:
                raise RuntimeError(
                    f"reimport mismatch for {target} at LOD {reimport_lod}; "
                    f"expected {expected}"
                )

        expected_visible = profile["lod_groups"].get(reimport_lod, [])
        # Importer prints the active list from INX. Require all profile members.
        for target in expected_visible:
            if target not in reimport_text:
                raise RuntimeError(
                    f"LOD {reimport_lod}: expected visible object {target} "
                    "not present in reimport log"
                )

        reimport_results[reimport_lod] = {
            "blend": str(reimport_out),
            "log": str(reimport_log),
            "visible_objects_expected": expected_visible,
            "check": "PASS",
        }


    final_manifest = {
        "tool": "PT_CHARACTER_MULTI_OBJECT_LOD_PIPELINE_V2",
        "pipeline_check": "PASS",
        "profile": str(profile_path),
        "profile_id": profile["profile_id"],
        "selection": {
            "all_lods": bool(a.all_lods),
            "lod": a.lod,
            "objects": targets,
            "reimport_lods": reimport_lods,
        },
        "artist_master": str(artist),
        "artist_master_sha256": sha256_file(artist),
        "artist_master_overwritten": False,
        "normalized_copy": str(normalized_final),
        "game_copy_used": str(current_game),
        "test_force_ambiguous_used": bool(unresolved_targets and a.force_test),
        "unresolved_targets_before_force_test": unresolved_targets,
        "normalize_reports": [str(log_dir / f"{name}_normalize_{x}.json") for x in targets],
        "validation_report": str(validation_report),
        "export_report": str(export_report),
        "smd": str(smd_out),
        "smd_size": smd_size,
        "smd_sha256": smd_sha,
        "reimports": reimport_results,
        "output_counts": output_by_name,
        "non_target_object_blocks_byte_identical": er["non_target_object_blocks_byte_identical"],
        "roundtrip_published": False,
        "runtime_installed": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_json(manifest, final_manifest)

    if a.roundtrip_workspace:
        if not tools["bridge"].is_file():
            raise FileNotFoundError(tools["bridge"])
        workspace = resolve(root, a.roundtrip_workspace)
        target_path = a.roundtrip_target or profile["roundtrip_target"]
        cmd = [
            sys.executable, str(tools["bridge"]), "publish",
            str(workspace),
            "--pipeline-manifest", str(manifest),
            "--target", target_path,
        ]
        if a.replace_published:
            cmd.append("--replace-published")
        run_stage("PUBLISH TO ROUNDTRIP WORKSPACE", cmd, log_dir / f"{name}_publish.log")
        final_manifest["roundtrip_published"] = True
        final_manifest["roundtrip_workspace"] = str(workspace)
        final_manifest["roundtrip_target"] = target_path
        final_manifest["roundtrip_replace_published"] = bool(a.replace_published)
        write_json(manifest, final_manifest)

    print("\nPT_CHARACTER_MULTI_OBJECT_LOD_PIPELINE_V2")
    print(f"profile_id={profile['profile_id']}")
    print(f"all_lods={str(bool(a.all_lods)).lower()}")
    print(f"lod={a.lod}")
    print(f"objects={targets}")
    print(f"reimport_lods={reimport_lods}")
    print(f"object_count={len(targets)}")
    print("artist_master_overwritten=False")
    print(f"test_force_ambiguous_used={str(final_manifest['test_force_ambiguous_used']).lower()}")
    for target in targets:
        c = output_by_name[target]
        print(f"OBJECT {target}: output_counts={c['vertices']}/{c['faces']}/{c['texlinks']}")
    print(f"non_target_object_blocks_byte_identical={er['non_target_object_blocks_byte_identical']}")
    print(f"smd={smd_out}")
    print(f"smd_size={smd_size}")
    print(f"smd_sha256={smd_sha}")
    for _lod, _row in reimport_results.items():
        print(f"reimport_{_lod}={_row['blend']}")
    print(f"manifest={manifest}")
    print(f"roundtrip_published={str(final_manifest['roundtrip_published']).lower()}")
    print("runtime_installed=False")
    print("multi_object_pipeline_v2_check=PASS")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"multi_object_pipeline_v2_check=FAIL: {type(exc).__name__}: {exc}")
        raise
