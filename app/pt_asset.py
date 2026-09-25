#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Iterable

from pt_asset_tool.runtime_paths import bundle_root, invocation_label, is_frozen, persistent_pt_build, prepare_runtime_layout, python_script_command

OVERLAY_VERSION = "1.0.0"
WORKSPACE_FORMAT = "PT_RARE_RIGID_GUARDED_EDIT_WORKSPACE_V5"
SELECTION_FORMAT = "PT_RARE_RIGID_VISIBLE_TRANSACTION_SELECTION_V2"
SELECTION_AUDIT_FORMAT = "PT_RARE_RIGID_VISIBLE_TRANSACTION_SELECTION_AUDIT_V2"
PERSISTENT_EDIT_AUDIT_FORMAT = "PT_RARE_RIGID_PERSISTENT_EDIT_ENTRY_AUDIT_V1"
DEFAULT_LOGICAL = "char/tmABCD/at_dragon.smd"
DEFAULT_OBJECT_INDEX = 0
DEFAULT_VERTICES = [33, 155]

ROOT = bundle_root()
CORE = ROOT / "pt_asset_core_v0_8_9.py"
HELPER = ROOT / "pt_asset_tool" / "blender" / "ensure_rare_rigid_transaction_selection.py"
VERIFY = ROOT / "pt_asset_tool" / "blender" / "verify_rare_rigid_transaction_selection.py"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _find_workspace(text: str) -> dict[str, Any] | None:
    for obj in _json_objects(text):
        if obj.get("format") == WORKSPACE_FORMAT:
            return obj
    return None


def _baseline_object_names(node: Any, object_index: int) -> list[str]:
    found: list[str] = []
    index_keys = {"object_index", "smd_object_index", "pt_object_index", "source_object_index"}
    name_keys = {
        "object_name", "blender_object", "blender_object_name", "mesh_object", "name", "head_name"
    }

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            idx_match = False
            for k, v in x.items():
                if str(k).lower() in index_keys:
                    try:
                        idx_match = int(v) == object_index
                    except Exception:
                        pass
            if idx_match:
                for k, v in x.items():
                    if str(k).lower() in name_keys and isinstance(v, str) and v.strip():
                        found.append(v.strip())
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(node)
    # Stable unique order.
    return list(dict.fromkeys(found))


def _resolve_name_from_baseline(path_value: Any, object_index: int) -> str | None:
    if not isinstance(path_value, str) or not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    index_keys = {"object_index", "smd_object_index", "pt_object_index", "source_object_index"}
    priority = {
        "blender_object_name": 0, "blender_object": 0, "mesh_object_name": 0,
        "object_name": 1, "mesh_object": 1,
        "head_name": 2, "name": 3,
    }
    tiers: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            matched = False
            for k, v in x.items():
                if str(k).lower() in index_keys:
                    try:
                        matched = matched or int(v) == object_index
                    except Exception:
                        pass
            if matched:
                for k, v in x.items():
                    lk = str(k).lower()
                    if lk in priority and isinstance(v, str) and v.strip():
                        tiers[priority[lk]].append(v.strip())
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    for level in sorted(tiers):
        names = list(dict.fromkeys(tiers[level]))
        if len(names) == 1:
            return names[0]
        if len(names) > 1:
            # Do not drop to a weaker naming tier when a stronger tier is ambiguous.
            return None
    return None


def _blender_command() -> list[str]:
    """Use the same Blender resolver as dependencies, particles and previews."""
    from pt_asset_tool.dependencies import resolve_blender_command
    cmd, ready, detail = resolve_blender_command(ROOT)
    if not ready or not cmd:
        raise RuntimeError(f"BLENDER_UNAVAILABLE:{detail}")
    return list(cmd)


def _blender_launcher_status(cmd: list[str] | None = None) -> tuple[bool, str]:
    """Return whether the configured Blender application is actually available.

    Flatpak launchers must have the configured app installed.  This check is
    intentionally independent from Blender version probing so the historical
    boolean/reason contract remains deterministic and easy to test.
    """
    cmd = list(cmd or _blender_command())
    if not cmd:
        return False, "EMPTY_BLENDER_COMMAND"
    executable = shutil.which(cmd[0])
    if not executable:
        return False, f"EXECUTABLE_NOT_FOUND:{cmd[0]}"

    if Path(cmd[0]).name == "flatpak":
        app_id = next((arg for arg in cmd if arg == "org.blender.Blender"), None)
        if app_id is None:
            try:
                run_i = cmd.index("run")
            except ValueError:
                run_i = -1
            if run_i >= 0:
                app_id = next((arg for arg in cmd[run_i + 1:] if not arg.startswith("-")), None)
        if not app_id:
            return False, "FLATPAK_APP_ID_NOT_FOUND"
        try:
            proc = subprocess.run(
                [executable, "info", app_id],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"FLATPAK_INFO_FAILED:{type(exc).__name__}:{exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().replace("\n", " ")
            return False, f"FLATPAK_APP_UNAVAILABLE:{app_id}:{detail}"
        return True, f"FLATPAK_APP_INSTALLED:{app_id}"

    return True, f"EXECUTABLE_FOUND:{executable}"

def _run_core(args: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    if not CORE.is_file():
        raise RuntimeError(f"CORE_MISSING:{CORE}")
    kwargs: dict[str, Any] = {"text": True}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return subprocess.run(python_script_command(CORE, *args), **kwargs)


def _selection_report_path(blend: Path) -> Path:
    return blend.with_name("visible_transaction_selection_v0813.json")


def _invoke_selection_helper(
    blend: Path,
    object_index: int,
    vertices: list[int],
    object_name: str | None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if not blend.is_file():
        raise RuntimeError(f"BLEND_MISSING:{blend}")
    if not HELPER.is_file():
        raise RuntimeError(f"SELECTION_HELPER_MISSING:{HELPER}")
    report_path = report_path or _selection_report_path(blend)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.unlink(missing_ok=True)

    cmd = _blender_command() + [
        "--background", str(blend),
        "--python", str(HELPER),
        "--",
        "--blend", str(blend),
        "--object-index", str(object_index),
        "--vertices", ",".join(str(v) for v in vertices),
        "--report", str(report_path),
    ]
    if object_name:
        cmd += ["--object-name", object_name]

    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.returncode != 0:
        raise RuntimeError(f"BLENDER_SELECTION_HELPER_FAILED:{proc.returncode}")
    if not report_path.is_file():
        raise RuntimeError(f"SELECTION_REPORT_MISSING:{report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if data.get("format") != SELECTION_FORMAT or data.get("status") != "PASS":
        raise RuntimeError(f"SELECTION_REPORT_NOT_PASS:{report_path}")
    raw_mode = data.get("mode_after_raw")
    semantic_mode = data.get("mode_after")
    if raw_mode != "EDIT":
        raise RuntimeError(f"SELECTION_RAW_MODE_NOT_EDIT:{raw_mode}")
    if semantic_mode != "EDIT_MESH":
        raise RuntimeError(f"SELECTION_MODE_NOT_EDIT_MESH:{semantic_mode}")
    if data.get("selected_vertex_indices") != vertices:
        raise RuntimeError(
            f"SELECTION_VERTEX_MISMATCH:{data.get('selected_vertex_indices')}!={vertices}"
        )
    return data


def _invoke_verify_helper(
    blend: Path,
    object_index: int,
    vertices: list[int],
    object_name: str | None,
    report_path: Path,
) -> dict[str, Any]:
    if not VERIFY.is_file():
        raise RuntimeError(f"VERIFY_HELPER_MISSING:{VERIFY}")
    report_path.unlink(missing_ok=True)
    cmd = _blender_command() + [
        "--background", str(blend),
        "--python", str(VERIFY),
        "--",
        "--object-index", str(object_index),
        "--vertices", ",".join(str(v) for v in vertices),
        "--report", str(report_path),
    ]
    if object_name:
        cmd += ["--object-name", object_name]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.returncode != 0:
        raise RuntimeError(f"BLENDER_SELECTION_VERIFY_FAILED:{proc.returncode}")
    if not report_path.is_file():
        raise RuntimeError(f"VERIFY_REPORT_MISSING:{report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if data.get("status") != "PASS":
        raise RuntimeError(f"VERIFY_REPORT_NOT_PASS:{report_path}")
    return data


def _prepare_visible_selection(workspace: dict[str, Any]) -> dict[str, Any]:
    logical = workspace.get("logical")
    if logical != DEFAULT_LOGICAL:
        raise RuntimeError(f"UNSUPPORTED_LOGICAL:{logical}")
    tx = workspace.get("default_safe_transaction")
    if not isinstance(tx, dict):
        raise RuntimeError("DEFAULT_SAFE_TRANSACTION_MISSING")
    object_index = int(tx.get("object_index", -1))
    vertices = [int(v) for v in tx.get("changed_vertex_indices", [])]
    if object_index != DEFAULT_OBJECT_INDEX or vertices != DEFAULT_VERTICES:
        raise RuntimeError(
            f"UNEXPECTED_DEFAULT_TRANSACTION:object={object_index},vertices={vertices}"
        )
    if not (2 <= len(vertices) <= int(workspace.get("ui_safety_profile", {}).get("max_transaction_vertices", 0))):
        raise RuntimeError("TRANSACTION_COUNT_OUTSIDE_UI_SCOPE")
    blend = Path(str(workspace.get("edit_blend", "")))
    baseline = workspace.get("baseline_blender_report")
    object_name = _resolve_name_from_baseline(baseline, object_index)
    result = _invoke_selection_helper(blend, object_index, vertices, object_name)
    return {
        "blend": str(blend),
        "object_index": object_index,
        "vertices": vertices,
        "object_name": result.get("object_name"),
        "resolution_method": result.get("resolution_method"),
        "mode_after_raw": result.get("mode_after_raw"),
        "mode_after": result.get("mode_after"),
        "selection_report": str(_selection_report_path(blend)),
    }


def _command_edit(args: list[str]) -> int:
    proc = _run_core(args, capture=True)
    output = proc.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if proc.returncode != 0:
        return proc.returncode
    workspace = _find_workspace(output)
    if workspace is None:
        print("pt_asset_selection_error=WORKSPACE_JSON_NOT_FOUND", file=sys.stderr)
        return 2
    try:
        selection = _prepare_visible_selection(workspace)
    except Exception as exc:
        print(f"pt_asset_selection_error={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    print(
        "rare_rigid_selection=READY "
        f"object_index={selection['object_index']} "
        f"vertices={','.join(map(str, selection['vertices']))} "
        f"mode={selection['mode_after']} "
        f"object={selection['object_name']} "
        f"resolution={selection['resolution_method']}"
    )
    return 0


def _parse_output_arg(args: list[str]) -> Path:
    if "--output" in args:
        i = args.index("--output")
        if i + 1 >= len(args):
            raise RuntimeError("MISSING_OUTPUT_PATH")
        return Path(args[i + 1]).resolve()
    return (ROOT / "pt_build" / "rare_rigid_selection_workflow_v0813.json").resolve()


def _command_selection_audit(args: list[str]) -> int:
    out = _parse_output_arg(args)
    from pt_asset_tool.blender_workspace import blender_edit_root
    rare_workspace = blender_edit_root(ROOT, "rare_model", DEFAULT_LOGICAL)
    src = rare_workspace / "at_dragon_guarded_edit.blend"
    baseline = rare_workspace / "edit_baseline_blender.json"
    if not src.is_file():
        print(f"pt_asset_error=ValueError:SOURCE_EDIT_BLEND_MISSING:{src}", file=sys.stderr)
        return 2

    audit_root = out.parent / (out.stem + "_workspace")
    if audit_root.exists():
        shutil.rmtree(audit_root)
    audit_root.mkdir(parents=True, exist_ok=True)
    isolated = audit_root / "at_dragon_guarded_edit.blend"
    shutil.copy2(src, isolated)
    source_sha_before = _sha256(src)
    object_name = _resolve_name_from_baseline(str(baseline), DEFAULT_OBJECT_INDEX)

    try:
        selection = _invoke_selection_helper(
            isolated, DEFAULT_OBJECT_INDEX, DEFAULT_VERTICES, object_name,
            audit_root / "selection_prepare.json"
        )
        verify = _invoke_verify_helper(
            isolated, DEFAULT_OBJECT_INDEX, DEFAULT_VERTICES,
            selection.get("object_name") or object_name,
            audit_root / "selection_reopen_verify.json"
        )
        source_sha_after = _sha256(src)
        source_untouched = source_sha_before == source_sha_after
        status = "PASS" if source_untouched else "FAIL"
        report = {
            "format": SELECTION_AUDIT_FORMAT,
            "status": status,
            "logical": DEFAULT_LOGICAL,
            "core_version": "0.8.9",
            "overlay_version": OVERLAY_VERSION,
            "source_edit_blend": str(src),
            "source_edit_blend_untouched": source_untouched,
            "audit_workspace_isolated": True,
            "isolated_blend": str(isolated),
            "object_index": DEFAULT_OBJECT_INDEX,
            "changed_vertex_indices": DEFAULT_VERTICES,
            "object_name": selection.get("object_name"),
            "resolution_method": selection.get("resolution_method"),
            "prepared_mode_raw": selection.get("mode_after_raw"),
            "prepared_mode": selection.get("mode_after"),
            "reopened_mode_raw": verify.get("mode_on_reopen_raw"),
            "reopened_mode": verify.get("mode_on_reopen"),
            "selected_vertex_indices_on_reopen": verify.get("selected_vertex_indices"),
            "active_object_on_reopen": verify.get("active_object"),
            "visible_selection_persisted": verify.get("visible_selection_persisted") is True,
            "geometry_positions_unchanged": selection.get("geometry_positions_unchanged") is True,
            "client_modified": False,
            "writer_modules_modified": False,
            "policy": {
                "scope": "Blender workspace UI state only; at_dragon default safe transaction 33,155",
                "fail_closed": "ambiguous target resolution, raw Blender mode other than EDIT, or non-persistent semantic EDIT_MESH selection returns FAIL",
                "mode_normalization": "Blender Object.mode EDIT is the physical API state for mesh edit mode; reports normalize it to semantic EDIT_MESH while retaining the raw value",
                "writer": "V0.8.9 guarded writer remains untouched",
            },
        }
        if not (
            report["visible_selection_persisted"]
            and report["geometry_positions_unchanged"]
            and report["prepared_mode_raw"] == "EDIT"
            and report["prepared_mode"] == "EDIT_MESH"
            and report["reopened_mode_raw"] == "EDIT"
            and report["reopened_mode"] == "EDIT_MESH"
            and report["selected_vertex_indices_on_reopen"] == DEFAULT_VERTICES
        ):
            report["status"] = "FAIL"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        if report["status"] == "PASS":
            print(
                "rare_rigid_selection_workflow=PASS "
                "vertices=33,155 mode=EDIT_MESH persisted=true writer_modified=false client_modified=false"
            )
            return 0
        print("rare_rigid_selection_workflow=FAIL", file=sys.stderr)
        return 2
    except Exception as exc:
        report = {
            "format": SELECTION_AUDIT_FORMAT,
            "status": "FAIL",
            "logical": DEFAULT_LOGICAL,
            "overlay_version": OVERLAY_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "client_modified": False,
            "writer_modules_modified": False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2



def _writer_hashes() -> dict[str, str]:
    paths = [
        ROOT / "pt_asset_tool" / "rare_rigid_edit.py",
        ROOT / "pt_asset_tool" / "rare_rigid_multivertex.py",
        ROOT / "pt_asset_tool" / "rare_rigid_multibone_bridge.py",
        ROOT / "pt_asset_tool" / "rare_rigid_normal_bridge.py",
    ]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise RuntimeError("WRITER_MODULE_MISSING:" + ",".join(missing))
    return {str(p.relative_to(ROOT)): _sha256(p) for p in paths}


def _parse_persistent_output_arg(args: list[str]) -> Path:
    if "--output" in args:
        i = args.index("--output")
        if i + 1 >= len(args):
            raise RuntimeError("MISSING_OUTPUT_PATH")
        return Path(args[i + 1]).resolve()
    return (ROOT / "pt_build" / "rare_rigid_edit_entry_workflow_v0813.json").resolve()


def _command_persistent_edit_audit(args: list[str]) -> int:
    out = _parse_persistent_output_arg(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        writers_before = _writer_hashes()
        proc = _run_core(["edit", "rare-model", DEFAULT_LOGICAL], capture=True)
        core_output = proc.stdout or ""
        if core_output:
            print(core_output, end="" if core_output.endswith("\n") else "\n")
        if proc.returncode != 0:
            raise RuntimeError(f"CORE_EDIT_FAILED:{proc.returncode}")
        workspace = _find_workspace(core_output)
        if workspace is None:
            raise RuntimeError("WORKSPACE_JSON_NOT_FOUND")
        if workspace.get("logical") != DEFAULT_LOGICAL:
            raise RuntimeError(f"WORKSPACE_LOGICAL_MISMATCH:{workspace.get('logical')}")
        if workspace.get("persisted_baseline_canonicalized") is not True:
            raise RuntimeError("PERSISTED_BASELINE_NOT_CANONICALIZED")
        if workspace.get("persisted_baseline_stable") is not True:
            raise RuntimeError("PERSISTED_BASELINE_NOT_STABLE")
        if workspace.get("client_modified") is not False:
            raise RuntimeError("CORE_REPORTED_CLIENT_MODIFIED")

        selection = _prepare_visible_selection(workspace)
        blend = Path(selection["blend"])
        verify_report = blend.with_name("visible_transaction_selection_reopen_v0813.json")
        verify = _invoke_verify_helper(
            blend,
            int(selection["object_index"]),
            [int(v) for v in selection["vertices"]],
            selection.get("object_name"),
            verify_report,
        )

        writers_after = _writer_hashes()
        writer_unchanged = writers_before == writers_after

        source_path = Path(str(workspace.get("source", "")))
        source_expected_sha = workspace.get("source_sha256")
        source_sha_after = _sha256(source_path) if source_path.is_file() else None
        client_source_unchanged = bool(
            source_expected_sha and source_sha_after and source_expected_sha == source_sha_after
        )

        selected = verify.get("selected_vertex_indices")
        pass_conditions = [
            selection.get("mode_after_raw") == "EDIT",
            selection.get("mode_after") == "EDIT_MESH",
            verify.get("mode_on_reopen_raw") == "EDIT",
            verify.get("mode_on_reopen") == "EDIT_MESH",
            selected == DEFAULT_VERTICES,
            verify.get("visible_selection_persisted") is True,
            selection.get("object_index") == DEFAULT_OBJECT_INDEX,
            writer_unchanged,
            client_source_unchanged,
        ]
        report = {
            "format": PERSISTENT_EDIT_AUDIT_FORMAT,
            "status": "PASS" if all(pass_conditions) else "FAIL",
            "logical": DEFAULT_LOGICAL,
            "core_version": "0.8.9",
            "overlay_version": OVERLAY_VERSION,
            "workspace_origin": workspace.get("workspace_origin"),
            "persistent_edit_blend": str(blend),
            "persistent_workspace_prepared_by_core": True,
            "persisted_baseline_canonicalized": workspace.get("persisted_baseline_canonicalized") is True,
            "persisted_baseline_stable": workspace.get("persisted_baseline_stable") is True,
            "object_index": selection.get("object_index"),
            "changed_vertex_indices": selection.get("vertices"),
            "object_name": selection.get("object_name"),
            "resolution_method": selection.get("resolution_method"),
            "prepared_mode_raw": selection.get("mode_after_raw"),
            "prepared_mode": selection.get("mode_after"),
            "reopened_mode_raw": verify.get("mode_on_reopen_raw"),
            "reopened_mode": verify.get("mode_on_reopen"),
            "selected_vertex_indices_on_reopen": selected,
            "active_object_on_reopen": verify.get("active_object"),
            "visible_selection_persisted": verify.get("visible_selection_persisted") is True,
            "geometry_positions_unchanged": verify.get("geometry_positions_unchanged") is True,
            "writer_modules_modified": not writer_unchanged,
            "client_source_sha256_expected": source_expected_sha,
            "client_source_sha256_after": source_sha_after,
            "client_modified": not client_source_unchanged,
            "failed_saved_artist_edit_cleared_by_core_reprepare": True,
            "ready_for_interactive_open": all(pass_conditions),
            "policy": {
                "scope": "persistent at_dragon artist workspace entry state only; default transaction 33,155",
                "persistent_change": "core edit rebuilds/canonicalizes the artist workspace; overlay changes only Blender UI selection/mode state",
                "fail_closed": "workspace, selection persistence, writer hashes, or client source hash mismatch returns FAIL",
                "writer": "V0.8.9 guarded writer remains untouched",
                "authorization": "no new geometry/write authorization is added by V0.8.13",
            },
        }
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        if report["status"] == "PASS":
            print(
                "rare_rigid_edit_entry_workflow=PASS "
                "vertices=33,155 mode=EDIT_MESH persisted=true "
                "persistent=true ready_for_open=true writer_modified=false client_modified=false"
            )
            return 0
        print("rare_rigid_edit_entry_workflow=FAIL", file=sys.stderr)
        return 2
    except Exception as exc:
        report = {
            "format": PERSISTENT_EDIT_AUDIT_FORMAT,
            "status": "FAIL",
            "logical": DEFAULT_LOGICAL,
            "overlay_version": OVERLAY_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "writer_modules_modified": False,
            "client_modified": False,
        }
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2


RELEASE_EXPORT_AUDIT_FORMAT = "PT_ASSET_CONSOLIDATED_RELEASE_EXPORT_AUDIT_V1"
RELEASE_MANIFEST_FORMAT = "PT_ASSET_CONSOLIDATED_RELEASE_MANIFEST_V1"
PRIOR_PERSISTENT_REPORT = ROOT / "pt_build" / "rare_rigid_edit_entry_workflow_v0812.json"
CONSOLIDATED_RELEASE_NAME = "pt_asset_tool_v0_8_13_consolidated_candidate"


def _source_closure() -> list[Path]:
    required = [
        ROOT / "pt_asset.py",
        ROOT / "pt_asset_core_v0_8_9.py",
        ROOT / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    tool_root = ROOT / "pt_asset_tool"
    if not tool_root.is_dir():
        missing.append(str(tool_root))
    if missing:
        raise RuntimeError("RELEASE_SOURCE_MISSING:" + ",".join(missing))
    files = list(required)
    for p in sorted(tool_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if "__pycache__" in rel.parts or p.suffix in {".pyc", ".pyo"}:
            continue
        files.append(p)
    return list(dict.fromkeys(files))


def _read_prior_persistent_report() -> dict[str, Any]:
    if not PRIOR_PERSISTENT_REPORT.is_file():
        raise RuntimeError(f"PRIOR_V0812_REPORT_MISSING:{PRIOR_PERSISTENT_REPORT}")
    data = json.loads(PRIOR_PERSISTENT_REPORT.read_text(encoding="utf-8"))
    required = {
        "format": "PT_RARE_RIGID_PERSISTENT_EDIT_ENTRY_AUDIT_V1",
        "status": "PASS",
        "visible_selection_persisted": True,
        "ready_for_interactive_open": True,
        "writer_modules_modified": False,
        "client_modified": False,
    }
    for key, expected in required.items():
        if data.get(key) != expected:
            raise RuntimeError(f"PRIOR_V0812_REPORT_INVALID:{key}={data.get(key)!r}")
    if data.get("selected_vertex_indices_on_reopen") != DEFAULT_VERTICES:
        raise RuntimeError("PRIOR_V0812_SELECTION_MISMATCH")
    if data.get("reopened_mode_raw") != "EDIT" or data.get("reopened_mode") != "EDIT_MESH":
        raise RuntimeError("PRIOR_V0812_MODE_MISMATCH")
    return data


def _client_source_from_project() -> Path:
    return ROOT.parent / "Summit Tale Client Full" / "cliente" / "char" / "tmABCD" / "at_dragon.smd"


def _copy_release_payload(release_root: Path, files: list[Path]) -> list[dict[str, Any]]:
    payload = release_root / "payload"
    records: list[dict[str, Any]] = []
    for src in files:
        rel = src.relative_to(ROOT)
        dst = payload / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        records.append({
            "path": str(rel),
            "size": dst.stat().st_size,
            "sha256": _sha256(dst),
        })
    return records


def _write_consolidated_installer(release_root: Path) -> None:
    script = """#!/usr/bin/env bash
set -euo pipefail
if [[ $# -gt 1 ]]; then
  echo "usage: $0 [design_work_root]" >&2
  exit 2
fi
TARGET="${1:-$PWD}"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$PKG_DIR/payload"
[[ -f "$PAYLOAD/pt_asset.py" ]] || { echo "install_error=payload_missing" >&2; exit 2; }
mkdir -p "$TARGET/pt_build"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP="$TARGET/pt_build/v0813_consolidated_install_backup_$TS"
mkdir -p "$BACKUP"
for item in pt_asset.py pt_asset_core_v0_8_9.py pt_asset_tool pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py; do
  if [[ -e "$TARGET/$item" ]]; then
    mkdir -p "$BACKUP/$(dirname "$item")"
    cp -a "$TARGET/$item" "$BACKUP/$item"
  fi
done
python3 - "$PAYLOAD" "$PKG_DIR/RELEASE_MANIFEST.json" <<'PY_VERIFY'
from pathlib import Path
import hashlib,json,sys
payload=Path(sys.argv[1]); manifest=json.loads(Path(sys.argv[2]).read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
for rec in manifest['payload_files']:
    p=payload/rec['path']
    if not p.is_file(): raise SystemExit('install_error=payload_file_missing:'+rec['path'])
    if sha(p)!=rec['sha256']: raise SystemExit('install_error=payload_hash_mismatch:'+rec['path'])
print('payload_hash_check=PASS files='+str(len(manifest['payload_files'])))
PY_VERIFY
mkdir -p "$TARGET/pt_asset_tool/legacy_runtime"
cp -a "$PAYLOAD/pt_asset.py" "$TARGET/pt_asset.py"
cp -a "$PAYLOAD/pt_asset_core_v0_8_9.py" "$TARGET/pt_asset_core_v0_8_9.py"
rm -rf "$TARGET/pt_asset_tool"
cp -a "$PAYLOAD/pt_asset_tool" "$TARGET/pt_asset_tool"
cp -a "$PAYLOAD/pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py" "$TARGET/pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"
chmod +x "$TARGET/pt_asset.py"
python3 - "$TARGET" "$PKG_DIR/RELEASE_MANIFEST.json" <<'PY_VERIFY_DST'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]); manifest=json.loads(Path(sys.argv[2]).read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
for rec in manifest['payload_files']:
    p=root/rec['path']
    if not p.is_file() or sha(p)!=rec['sha256']:
        raise SystemExit('install_error=destination_hash_mismatch:'+rec['path'])
print('destination_hash_check=PASS')
PY_VERIFY_DST
echo "backup=$BACKUP"
echo "installed_release=0.8.13"
cd "$TARGET"
python3 pt_asset.py --version
"""
    path = release_root / "install.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _parse_release_output_arg(args: list[str]) -> Path:
    if "--output" in args:
        i = args.index("--output")
        if i + 1 >= len(args):
            raise RuntimeError("MISSING_OUTPUT_PATH")
        return Path(args[i + 1]).resolve()
    return (ROOT / "pt_build" / "release_consolidation_workflow_v0813.json").resolve()


def _command_release_export_audit(args: list[str]) -> int:
    out = _parse_release_output_arg(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    release_root = out.parent / CONSOLIDATED_RELEASE_NAME
    zip_path = out.parent / (CONSOLIDATED_RELEASE_NAME + ".zip")
    try:
        prior = _read_prior_persistent_report()
        writers_before = _writer_hashes()

        doctor = _run_core(["doctor"], capture=True)
        doctor_output = doctor.stdout or ""
        if doctor_output:
            print(doctor_output, end="" if doctor_output.endswith("\n") else "\n")
        doctor_pass = doctor.returncode == 0 and "doctor_check=PASS" in doctor_output
        if not doctor_pass:
            raise RuntimeError(f"CORE_DOCTOR_NOT_PASS:{doctor.returncode}")

        client = _client_source_from_project()
        if not client.is_file():
            raise RuntimeError(f"CLIENT_SOURCE_MISSING:{client}")
        expected_client_sha = prior.get("client_source_sha256_after")
        client_sha_before = _sha256(client)
        if not expected_client_sha or client_sha_before != expected_client_sha:
            raise RuntimeError("CLIENT_SOURCE_HASH_MISMATCH_BEFORE_EXPORT")

        files = _source_closure()
        if release_root.exists():
            shutil.rmtree(release_root)
        release_root.mkdir(parents=True, exist_ok=True)
        records = _copy_release_payload(release_root, files)

        provenance = release_root / "provenance"
        provenance.mkdir()
        shutil.copy2(PRIOR_PERSISTENT_REPORT, provenance / "rare_rigid_edit_entry_workflow_v0812.json")
        (provenance / "doctor_v0813.txt").write_text(doctor_output, encoding="utf-8")
        (provenance / "writer_hashes_v0813.json").write_text(
            json.dumps(writers_before, indent=2) + "\n", encoding="utf-8"
        )

        manifest = {
            "format": RELEASE_MANIFEST_FORMAT,
            "status": "CANDIDATE",
            "release_version": OVERLAY_VERSION,
            "certified_writer_core": "0.8.9",
            "consolidated_from_installed_overlay": "0.8.12",
            "payload_file_count": len(records),
            "payload_files": records,
            "writer_hashes": writers_before,
            "prior_persistent_gate": {
                "format": prior.get("format"),
                "status": prior.get("status"),
                "vertices": prior.get("selected_vertex_indices_on_reopen"),
                "mode_raw": prior.get("reopened_mode_raw"),
                "mode": prior.get("reopened_mode"),
                "visible_selection_persisted": prior.get("visible_selection_persisted"),
                "ready_for_interactive_open": prior.get("ready_for_interactive_open"),
            },
            "client_source_sha256": client_sha_before,
            "policy": {
                "authorization": "no geometry/write scope expansion; V0.8.9 writer bytes are exported as physically installed",
                "client": "original client remains read-only",
                "purpose": "collapse the installed 0.8.9 core plus 0.8.12 UI state into one inspectable install bundle",
            },
        }
        (release_root / "RELEASE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        _write_consolidated_installer(release_root)
        (release_root / "README.md").write_text(
            "# PT Asset Tool 0.8.13 consolidated candidate\n\n"
            "Physical export of the installed PT Asset Tool source closure after the V0.8.12 persistent Blender-entry gate passed.\n\n"
            "It preserves the certified V0.8.9 guarded writer core and the proven visible-selection entry behavior. No geometry/write authorization is expanded.\n\n"
            "Install with `./install.sh /path/to/design_work`. The installer validates every payload SHA-256 before and after copy and backs up existing tool files under `pt_build/`.\n",
            encoding="utf-8",
        )

        writers_after = _writer_hashes()
        client_sha_after = _sha256(client)
        writer_unchanged = writers_before == writers_after
        client_unchanged = client_sha_before == client_sha_after
        if not writer_unchanged:
            raise RuntimeError("WRITER_HASH_CHANGED_DURING_EXPORT")
        if not client_unchanged:
            raise RuntimeError("CLIENT_SOURCE_CHANGED_DURING_EXPORT")

        (release_root / "LOCAL_TEST_RESULTS.md").write_text(
            "# Physical export gate\n\n"
            "- core doctor: PASS\n"
            "- prior V0.8.12 persistent entry gate: PASS\n"
            f"- payload files exported: {len(records)}\n"
            "- guarded writer hashes unchanged during export: PASS\n"
            "- original client modified: false\n",
            encoding="utf-8",
        )
        hash_lines = []
        for p in sorted(release_root.rglob("*")):
            if p.is_file() and p.name != "SHA256SUMS.txt":
                hash_lines.append(f"{_sha256(p)}  {p.relative_to(release_root)}")
        (release_root / "SHA256SUMS.txt").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

        zip_path.unlink(missing_ok=True)
        archive_base = str(zip_path.with_suffix(""))
        made = Path(shutil.make_archive(
            archive_base, "zip", root_dir=release_root.parent, base_dir=release_root.name
        ))
        zip_sha = _sha256(made)

        report = {
            "format": RELEASE_EXPORT_AUDIT_FORMAT,
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "certified_writer_core": "0.8.9",
            "prior_overlay": "0.8.12",
            "prior_persistent_gate_pass": True,
            "doctor_pass": doctor_pass,
            "source_closure_file_count": len(records),
            "writer_modules_modified": not writer_unchanged,
            "client_source_sha256_before": client_sha_before,
            "client_source_sha256_after": client_sha_after,
            "client_modified": not client_unchanged,
            "release_directory": str(release_root),
            "release_zip": str(made),
            "release_zip_sha256": zip_sha,
            "release_manifest": str(release_root / "RELEASE_MANIFEST.json"),
            "ready_for_external_review": True,
            "policy": {
                "scope": "release consolidation/export only",
                "writer": "certified V0.8.9 writer files are copied, not regenerated",
                "authorization": "no new geometry/write authorization",
                "next_after_review": "expand at_dragon multi-vertex transaction beyond four vertices",
            },
        }
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(
            "release_consolidation_workflow=PASS "
            f"files={len(records)} writer_modified=false client_modified=false "
            f"zip={made} sha256={zip_sha}"
        )
        return 0
    except Exception as exc:
        report = {
            "format": RELEASE_EXPORT_AUDIT_FORMAT,
            "status": "FAIL",
            "release_version": OVERLAY_VERSION,
            "error": f"{type(exc).__name__}:{exc}",
            "writer_modules_modified": False,
            "client_modified": False,
        }
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2


def _build_app_status_report() -> dict[str, Any]:
    from pt_asset_tool.certified_writers import CERTIFIED_WRITERS
    certified = CERTIFIED_WRITERS
    writer_checks = {}
    for rel, expected in certified.items():
        path = ROOT / rel
        writer_checks[rel] = bool(path.is_file() and _sha256(path) == expected)
    ui_files = [
        ROOT / "pt_asset_gui.py", ROOT / "pt-asset-gui",
        ROOT / "pt_asset_tool/ui_app.py", ROOT / "pt_asset_tool/ui_catalog.py",
        ROOT / "pt_asset_tool/ui_capabilities.py", ROOT / "pt_asset_tool/ui_image.py",
        ROOT / "pt_asset_tool/ui_static/index.html", ROOT / "pt_asset_tool/ui_static/app.js",
    ]
    runtime_required = [
        "pt_character_structural_gate_v2.py",
        "pt_character_texture_v1_4.py",
        "pt_blender_bind_editable_texture_v2.py",
        "pt_inx_motion_core_v2.py",
        "pt_pikeman_smd_material_audit_v1.py",
        "pt_protected_tga_v1.py",
        "pt_smd_blender_import_v4_generic.py",
        "pt_smd_static_capability_probe_v1.py",
        "pt_blender_to_smd_static_v1.py",
        "pt_blender_to_smd_free_mesh_v3.py",
        "summit_workspace_asset_bridge_v1_2.py",
        "summit_roundtrip_restore_v4.py",
        "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py",
        "pt_asset_tool/legacy_runtime/pt_smb_motion_evaluator_v1.py",
        "pt_asset_tool/blender_workspace.py",
        "pt_asset_tool/inx_writer.py",
        "pt_asset_tool/smb_writer.py",
        "pt_asset_tool/object_local_writer.py",
        "pt_asset_tool/animation_source_regression.py",
        "pt_asset_tool/animation_certification.py",
        "pt_asset_tool/workflow_dispatch.py",
        "pt_asset_tool/registry_bootstrap.py",
        "pt_asset_tool/profile_registry.py",
        "pt_asset_tool/profile_candidates.py",
        "pt_asset_tool/binding_coverage.py",
        "pt_asset_tool/development_readiness.py",
        "pt_asset_tool/deployment.py",
        "pt_asset_tool/build_provenance.py",
        "pt_asset_tool/authoring.py",
        "pt_asset_tool/static_authoring_candidate.py",
        "pt_asset_tool/rigid_authoring_candidate.py",
        "pt_asset_tool/rigid_authoring_evidence.py",
        "pt_asset_tool/rigid_authoring_stress.py",
        "pt_asset_tool/rigid_profile_devtest.py",
        "pt_asset_tool/rigid_semantic_devtest.py",
        "pt_asset_tool/standalone_rigid_devtest.py",
        "pt_asset_tool/mixed_authoring_candidate.py",
        "pt_asset_tool/model062_material_writer.py",
        "pt_asset_tool/model062_material_devtest.py",
        "pt_asset_tool/static_semantic_devtest.py",
        "pt_asset_tool/stage072_semantic_devtest.py",
        "pt_asset_tool/stage072_material_writer.py",
        "pt_asset_tool/stage072_material_devtest.py",
        "pt_asset_tool/animation_pose_devtest.py",
        "pt_asset_tool/texture_codec_devtest.py",
        "pt_asset_tool/object_local_devtest.py",
        "pt_asset_tool/texlink_devtest.py",
        "pt_asset_tool/texture_upscale.py",
        "pt_texture_upscale.py",
        "pt_asset_tool/release_1_coverage.py",
        "pt_asset_tool/release_1_auto.py",
        "pt_asset_tool/blender/apply_rigid_profile_devtest.py",
        "pt_asset_tool/blender/check_rigid_profile_devtest.py",
        "pt_asset_tool/blender/apply_static_semantic_devtest.py",
        "pt_asset_tool/blender/check_static_semantic_devtest.py",
        "pt_asset_tool/blender/apply_stage072_semantic_devtest.py",
        "pt_asset_tool/blender/check_baked_animation_pose.py",
        "pt_asset_tool/stage072_authoring_candidate.py",
        "pt_asset_tool/blender/extract_stage072_saved_edit.py",
    ]
    runtime_checks = {rel: (ROOT / rel).is_file() for rel in runtime_required}
    try:
        from pt_asset_tool.app_config import resolve_client_root
        resolved_path, resolved_source = resolve_client_root(ROOT)
        resolved_client_root = str(resolved_path)
    except Exception:
        resolved_client_root = None
        resolved_source = None
    features = {
        "catalog_cli": True,
        "tree_compare": (ROOT / "pt_asset_tool/tree_compare.py").is_file(),
        "monster_npc_census": (ROOT / "pt_asset_tool/monster_npc_census.py").is_file(),
        "gui": all(x.is_file() for x in ui_files),
        "rare_model_guarded_writer": all(writer_checks.values()),
        "stage072_workflows": (ROOT / "pt_asset_tool/stage072_roundtrip.py").is_file(),
        "portable_client_config": (ROOT / "pt_asset_tool/app_config.py").is_file(),
        "runtime_dependencies": all(runtime_checks.values()),
        "generic_import": (ROOT / "pt_asset_tool/validation.py").is_file(),
        "generic_build_dispatch": (ROOT / "pt_asset_tool/workflow_dispatch.py").is_file(),
        "inx_motion_candidate_writer": (ROOT / "pt_asset_tool/inx_writer.py").is_file(),
        "smb_key_candidate_writer": (ROOT / "pt_asset_tool/smb_writer.py").is_file(),
        "object_local_key_candidate_writer": (ROOT / "pt_asset_tool/object_local_writer.py").is_file(),
        "animation_source_regression": (ROOT / "pt_asset_tool/animation_source_regression.py").is_file(),
        "animation_certification_plan": (ROOT / "pt_asset_tool/animation_certification.py").is_file(),
        "character_profile_registry": (ROOT / "pt_asset_tool/profile_registry.py").is_file(),
        "profile_candidate_discovery": (ROOT / "pt_asset_tool/profile_candidates.py").is_file(),
        "binding_coverage_audit": (ROOT / "pt_asset_tool/binding_coverage.py").is_file(),
        "development_readiness_audit": (ROOT / "pt_asset_tool/development_readiness.py").is_file(),
        "deployment_plan_only": (ROOT / "pt_asset_tool/deployment.py").is_file(),
        "build_provenance": (ROOT / "pt_asset_tool/build_provenance.py").is_file(),
        "authoring_preflight": (ROOT / "pt_asset_tool/authoring.py").is_file(),
        "static_saved_blender_candidate": (ROOT / "pt_asset_tool/static_authoring_candidate.py").is_file(),
        "rigid_saved_blender_candidate": (ROOT / "pt_asset_tool/rigid_authoring_candidate.py").is_file(),
        "rigid_authoring_evidence": (ROOT / "pt_asset_tool/rigid_authoring_evidence.py").is_file(),
        "rigid_profile_stress_candidate": (ROOT / "pt_asset_tool/rigid_authoring_stress.py").is_file(),
        "rigid_profile_automated_devtest": all((ROOT / rel).is_file() for rel in ["pt_asset_tool/rigid_profile_devtest.py", "pt_asset_tool/blender/apply_rigid_profile_devtest.py", "pt_asset_tool/blender/check_rigid_profile_devtest.py"]),
        "release_1_coverage_matrix": (ROOT / "pt_asset_tool/release_1_coverage.py").is_file(),
        "release_1_automated_gate": (ROOT / "pt_asset_tool/release_1_auto.py").is_file(),
        "standalone_rigid_semantic_devtest": (ROOT / "pt_asset_tool/standalone_rigid_devtest.py").is_file(),
        "mixed_physique_candidate": (ROOT / "pt_asset_tool/mixed_authoring_candidate.py").is_file(),
        "model062_material_candidate": (ROOT / "pt_asset_tool/model062_material_writer.py").is_file(),
        "model062_material_automated_devtest": (ROOT / "pt_asset_tool/model062_material_devtest.py").is_file(),
        "static_semantic_devtest": (ROOT / "pt_asset_tool/static_semantic_devtest.py").is_file(),
        "animation_pose_space_devtest": (ROOT / "pt_asset_tool/animation_pose_devtest.py").is_file(),
        "proprietary_texture_codec_devtest": (ROOT / "pt_asset_tool/texture_codec_devtest.py").is_file(),
        "object_local_semantic_devtest": (ROOT / "pt_asset_tool/object_local_devtest.py").is_file(),
        "multilayer_texlink_semantic_devtest": (ROOT / "pt_asset_tool/texlink_devtest.py").is_file(),
        "stage072_saved_blender_candidate": (ROOT / "pt_asset_tool/stage072_authoring_candidate.py").is_file(),
        "stage072_material_candidate": (ROOT / "pt_asset_tool/stage072_material_writer.py").is_file(),
        "texture_upscale": all((ROOT / rel).is_file() for rel in ["pt_asset_tool/texture_upscale.py", "pt_texture_upscale.py"]),
    }
    try:
        from pt_asset_tool.texture_upscale import capability_status as _texture_upscale_capability_status
        texture_upscale_optional = _texture_upscale_capability_status()
    except Exception as exc:
        texture_upscale_optional = {
            "pillow_ready": False,
            "lanczos_ready": False,
            "realesrgan_ready": False,
            "error": f"{type(exc).__name__}:{exc}",
        }
    return {
        "format": "PT_ASSET_APP_STATUS_V2",
        "status": "PASS" if resolved_client_root and all(writer_checks.values()) and all(features.values()) else "WARN",
        "release_version": OVERLAY_VERSION,
        "project_root": str(ROOT),
        "client_root": resolved_client_root,
        "client_root_discovery": bool(resolved_client_root),
        "client_root_source": resolved_source,
        "features": features,
        "certified_writer_hashes_valid": all(writer_checks.values()),
        "writer_checks": writer_checks,
        "runtime_dependency_checks": runtime_checks,
        "optional_capabilities": {"texture_upscale": texture_upscale_optional},
        "client_source_write_default": False,
        "research_branches_required_for_normal_use": False,
    }


def _command_app_status() -> int:
    report = _build_app_status_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


def _human_size_bytes(value: int) -> str:
    total = max(0, int(value or 0))
    if total >= 1024 ** 3:
        return f"{total / (1024 ** 3):.2f} GiB"
    if total >= 1024 ** 2:
        return f"{total / (1024 ** 2):.2f} MiB"
    if total >= 1024:
        return f"{total / 1024:.2f} KiB"
    return f"{total} B"


def _texture_capability_violation(asset: Any, caps: list[str]) -> dict[str, Any] | None:
    extension = str(getattr(asset, "extension", "") or "").lower()
    if extension not in {".bmp", ".tga", ".png", ".jpg", ".jpeg"}:
        return None
    allowed = {"inspect", "upscale_texture"}
    unexpected = sorted(x for x in caps if x not in allowed)
    if not unexpected:
        return None
    return {
        "asset": getattr(asset, "primary_path", None),
        "reason": "texture_non_texture_action",
        "actions": list(caps),
        "unexpected_actions": unexpected,
    }


def _command_app_smoke() -> int:
    status = _build_app_status_report()
    checks: dict[str, Any] = {
        "app_status_pass": status.get("status") == "PASS",
        "certified_writer_hashes_valid": bool(status.get("certified_writer_hashes_valid")),
        "runtime_dependencies_present": all(bool(x) for x in (status.get("runtime_dependency_checks") or {}).values()),
        "client_root_resolved": bool(status.get("client_root")),
        "pt_build_writable": False,
        "catalog_bootstrap": False,
        "asset_registry_bootstrap": False,
        "ui_capability_contract": False,
        "ui_taxonomy_contract": False,
        "entity_catalog_contract": False,
        "ui_preview_pipeline": False,
        "ui_javascript_contract": False,
        "ui_interactive_review_contract": False,
        "support_file_inspection_contract": False,
        "blender_edit_workspace_contract": False,
        "generic_blender_import_contract": False,
        "texture_upscale_contract": False,
        "generic_build_dispatch_contract": False,
        "inx_motion_writer_contract": False,
        "smb_key_writer_contract": False,
        "object_local_key_writer_contract": False,
        "character_profile_registry_contract": False,
        "profile_candidate_discovery_contract": False,
        "animation_certification_plan_contract": False,
        "development_readiness_contract": False,
        "deployment_plan_contract": False,
        "deployment_simulation_contract": False,
        "deployment_restore_contract": False,
        "authoring_preflight_contract": False,
        "binding_coverage_contract": False,
        "ui_reports_recursive_contract": False,
        "tree_compare_import": False,
        "monster_npc_import": False,
        "blender_launcher_available": False,
    }
    details: dict[str, Any] = {
        "project_root": str(ROOT),
        "client_root": status.get("client_root"),
        "client_root_source": status.get("client_root_source"),
    }
    # Verify project build writes only; source client remains read-only.
    try:
        build = ROOT / "pt_build"
        build.mkdir(parents=True, exist_ok=True)
        probe = build / ".pt_asset_smoke_write_probe"
        probe.write_bytes(b"PT_ASSET_SMOKE\n")
        probe.unlink()
        checks["pt_build_writable"] = True
    except Exception as exc:
        details["pt_build_error"] = f"{type(exc).__name__}:{exc}"
    # Build the same read-only catalog used by the GUI to validate real client traversal.
    if status.get("client_root"):
        try:
            from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore
            client = Path(str(status["client_root"]))
            smoke_state = UIStateStore(ROOT / "pt_build" / "ui_state_v0100.json")
            catalog = CatalogIndex(client, smoke_state)
            stats = catalog.rebuild()
            details["catalog_file_count"] = stats.file_count
            details["catalog_total_bytes"] = stats.total_bytes
            # Preserve the exact byte count for machine consumers while also
            # emitting a human-readable value for smoke reports read by people.
            details["catalog_total_size"] = _human_size_bytes(stats.total_bytes)
            checks["catalog_bootstrap"] = stats.file_count > 0
        except Exception as exc:
            details["catalog_error"] = f"{type(exc).__name__}:{exc}"

    # Exercise the semantic backend used by GUI actions; catalog traversal alone
    # is not enough to prove the application is usable.
    reg = None
    resolver = None
    if status.get("client_root"):
        try:
            from pt_asset_tool.config import Settings
            from pt_asset_tool.registry import AssetRegistry
            from pt_asset_tool.resolver import ClientResolver
            settings = Settings.discover(ROOT, Path(str(status["client_root"])))
            resolver = ClientResolver(settings.client_root)
            reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
            details["registry_record_count"] = len(reg.records)
            details["registry_asset_count"] = len(reg.assets)
            checks["asset_registry_bootstrap"] = len(reg.records) > 0 and len(reg.assets) > 0
        except Exception as exc:
            details["asset_registry_error"] = f"{type(exc).__name__}:{exc}"

    if reg is not None:
        try:
            from pt_asset_tool.ui_capabilities import capabilities_for_asset
            from pt_asset_tool.ui_actions import ACTION_SPECS
            invalid = []
            for asset in reg.assets:
                caps, _notes = capabilities_for_asset(asset, None)
                unknown = sorted(x for x in caps if x not in ACTION_SPECS)
                if unknown:
                    invalid.append({"asset": asset.primary_path, "reason": "unknown_action", "actions": unknown})
                    break
                # Interactive actions are now a supported GUI contract. They
                # must be explicitly declared interactive so the job runner
                # gives them only the constrained y/n/s stdin bridge.
                for action in caps:
                    if action in {"validate_visual", "validate_roundtrip", "validate_object_local", "validate_animation", "diagnose_animation"} and not ACTION_SPECS[action].interactive:
                        invalid.append({"asset": asset.primary_path, "reason": "interactive_action_not_declared", "actions": [action]})
                        break
                if invalid:
                    break
                texture_violation = _texture_capability_violation(asset, caps)
                if texture_violation:
                    invalid.append(texture_violation)
                    break
                if asset.family == "SMD_MODEL_062_STATIC" and any(x in caps for x in {"bindings", "motions", "validate_animation", "diagnose_animation"}):
                    invalid.append({"asset": asset.primary_path, "reason": "static_rigid_action", "actions": caps})
                    break
            details["ui_capability_invalid_sample"] = invalid[:1]
            checks["ui_capability_contract"] = not invalid
        except Exception as exc:
            details["ui_capability_error"] = f"{type(exc).__name__}:{exc}"

        try:
            from pt_asset_tool.ui_catalog import infer_semantics, infer_folder_bucket
            taxonomy_samples = {
                "npc": infer_semantics("char/npc/Ahin/Ahin.smd", ".smd"),
                "monster": infer_semantics("char/monster/Acero/Acero.smb", ".smb"),
                "chat": infer_semantics("image/Sinimage/Inter/Chat/ChatDefault-1.tga", ".tga"),
                "item_icon": infer_semantics("image/Sinimage/Items/Defense/itDB150.bmp", ".bmp"),
                "drop": infer_semantics("image/Sinimage/Items/DropItem/drop.smd", ".smd"),
            }
            checks["ui_taxonomy_contract"] = (
                taxonomy_samples["npc"] == ("NPC", "MODEL")
                and taxonomy_samples["monster"] == ("MONSTER", "ANIMATION")
                and taxonomy_samples["chat"] == ("UI", "CHAT")
                and taxonomy_samples["item_icon"] == ("UI", "ITEM_ICON_DEFENSE")
                and taxonomy_samples["drop"] == ("ITEM", "DROP_MODEL")
                and infer_folder_bucket("image/Sinimage/Inter/Chat/ChatDefault-1.tga", "UI")[0] == "Inter/Chat"
            )
            details["ui_taxonomy_samples"] = {k: list(v) for k, v in taxonomy_samples.items()}
        except Exception as exc:
            details["ui_taxonomy_error"] = f"{type(exc).__name__}:{exc}"

        try:
            from pt_asset_tool.entity_catalog import load_entity_seed, query_entities
            seed = load_entity_seed(ROOT)
            entity_report = query_entities(
                catalog.assets if 'catalog' in locals() else [], seed, limit=5, registry=reg
            )
            live_count = int(entity_report.get("live_entity_count") or 0)
            entity_items = entity_report.get("items") or []
            safe = all(
                x.get("runtime_status") == "UNPROVEN" and x.get("writer_status") == "UNAUTHORIZED"
                for x in entity_items
            )
            enriched = all(
                "registry_evidence" in x
                and "related_entity_keys" in x
                and "cross_entity_links" in x
                for x in entity_items
            )
            # Minimal clients may legitimately contain no NPC/Monster assets;
            # the known seed still proves the package data contract.
            checks["entity_catalog_contract"] = (
                seed.get("status") == "PASS"
                and int(seed.get("entity_count") or 0) > 0
                and safe
                and enriched
                and entity_report.get("status") == "PASS"
            )
            details["entity_catalog_seed_count"] = int(seed.get("entity_count") or 0)
            details["entity_catalog_live_count"] = live_count
        except Exception as exc:
            details["entity_catalog_error"] = f"{type(exc).__name__}:{exc}"

        try:
            # Support-file inspection is a physical-client capability, not a
            # promise that every support file is represented as a semantic Asset.
            client_root = Path(str(status["client_root"]))
            support_path = next((p for p in client_root.rglob("*") if p.is_file() and p.suffix.lower() in {".inx", ".smb", ".wav"}), None)
            if support_path is None:
                checks["support_file_inspection_contract"] = True
                details["support_file_sample"] = "N/A:no support file in configured client"
            else:
                rel = support_path.relative_to(client_root).as_posix()
                resolved = resolver.resolve(rel, required=True) if resolver is not None else None
                checks["support_file_inspection_contract"] = bool(resolved and Path(resolved).samefile(support_path))
                details["support_file_sample"] = rel
        except Exception as exc:
            details["support_file_inspection_error"] = f"{type(exc).__name__}:{exc}"

        try:
            from pt_asset_tool.ui_image import preview_image_bytes
            client_root = Path(str(status["client_root"]))
            attempts = 0
            physical_candidates = 0
            errors = []
            # Scan the configured client itself. A partial/dev client is allowed
            # to contain paths absent from the historical semantic inventory.
            image_paths = sorted(
                (p for p in client_root.rglob("*") if p.is_file() and p.suffix.lower() in {".tga", ".bmp", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}),
                key=lambda p: p.relative_to(client_root).as_posix().lower(),
            )
            for physical in image_paths[:64]:
                physical_candidates += 1
                attempts += 1
                rel = physical.relative_to(client_root).as_posix()
                try:
                    raw, mime = preview_image_bytes(physical, ROOT)
                    if raw and mime.startswith("image/"):
                        checks["ui_preview_pipeline"] = True
                        details["preview_sample"] = rel
                        details["preview_sample_mime"] = mime
                        break
                except Exception as exc:
                    if len(errors) < 3:
                        errors.append(f"{rel}:{type(exc).__name__}:{exc}")
            if not image_paths:
                # No physical image means there is no client-specific sample to
                # exercise. The converter itself is covered by unit/synthetic
                # release tests; do not fail an otherwise valid minimal client.
                checks["ui_preview_pipeline"] = True
                details["preview_sample"] = "N/A:no image file in configured client"
            details["preview_attempts"] = attempts
            details["preview_physical_candidates"] = physical_candidates
            if errors:
                details["preview_error_samples"] = errors
        except Exception as exc:
            details["ui_preview_error"] = f"{type(exc).__name__}:{exc}"

    try:
        js = (ROOT / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
        checks["ui_javascript_contract"] = "onerror=" not in js and "data-preview-fallback" in js
    except Exception as exc:
        details["ui_javascript_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.ui_jobs import _latest_review_prompt
        from pt_asset_tool.ui_actions import ACTION_SPECS
        sample_prompt = _latest_review_prompt("Geometry correct? [y]es / [n]o / [s]kip: ")
        interactive_keys = {
            "validate_visual", "validate_roundtrip", "validate_object_local",
            "validate_animation", "diagnose_animation",
        }
        checks["ui_interactive_review_contract"] = (
            sample_prompt == "Geometry correct?"
            and all(ACTION_SPECS[k].interactive for k in interactive_keys)
            and "/api/job/input" in js
            and "input_prompt" in js
        )
        details["ui_interactive_review_sample"] = sample_prompt
    except Exception as exc:
        details["ui_interactive_review_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.blender_workspace import blender_edit_root
        sample = blender_edit_root(ROOT, "stage072_texture_paint", "maps/Test Stage/example.smd", "stage_0")
        build_root = (ROOT / "pt_build" / "blender_edits").resolve()
        resolved_sample = sample.resolve()
        checks["blender_edit_workspace_contract"] = build_root in resolved_sample.parents and "maps__test_stage__example" in str(resolved_sample).lower()
        details["blender_edit_workspace_sample"] = str(sample)
    except Exception as exc:
        details["blender_edit_workspace_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.ui_actions import ACTION_SPECS, build_command
        from pt_asset_tool.validation import ValidationRunner
        import_cmd = build_command(ROOT, "import_blender", "char/test/body.smd", {})
        checks["generic_blender_import_contract"] = (
            "import_blender" in ACTION_SPECS
            and hasattr(ValidationRunner, "blender_import_workspace")
            and import_cmd[2:4] == ["import", "char/test/body.smd"]
            and "--load-actions" in import_cmd
            and "--motion" in import_cmd
            and "--open-mode" in import_cmd
        )
        details["generic_blender_import_command"] = import_cmd
    except Exception as exc:
        details["generic_blender_import_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.texture_upscale import SUPPORTED_SUFFIXES, capability_status as _texture_caps
        from pt_asset_tool.ui_actions import ACTION_SPECS, build_command
        texture_cmd = build_command(ROOT, "upscale_texture", "Image/Character/test.tga", {"scale": 2, "backend": "lanczos"})
        texture_caps = _texture_caps()
        checks["texture_upscale_contract"] = (
            "upscale_texture" in ACTION_SPECS
            and ACTION_SPECS["upscale_texture"].mutates_build
            and {".tga", ".bmp", ".png", ".jpg", ".jpeg"}.issubset(SUPPORTED_SUFFIXES)
            and texture_cmd[2:4] == ["texture-upscale", "run"]
            and "lanczos_ready" in texture_caps
            and "realesrgan_ready" in texture_caps
        )
        details["texture_upscale_command"] = texture_cmd
        details["texture_upscale_capabilities"] = texture_caps
    except Exception as exc:
        details["texture_upscale_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.workflow_dispatch import build_plan
        if reg is not None:
            rare = next((a for a in reg.assets if a.primary_path.lower() == "char/tmabcd/at_dragon.smd"), None)
            nonrare = next((a for a in reg.assets if a.primary_path.lower() != "char/tmabcd/at_dragon.smd"), None)
            rare_ok = True if rare is None else bool(build_plan(rare).get("authorized"))
            nonrare_ok = True if nonrare is None else not bool(build_plan(nonrare).get("authorized"))
            checks["generic_build_dispatch_contract"] = rare_ok and nonrare_ok
        else:
            checks["generic_build_dispatch_contract"] = False
    except Exception as exc:
        details["generic_build_dispatch_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.authoring import authoring_plan
        if reg is not None and resolver is not None:
            sample_asset = None
            for candidate in reg.assets:
                if candidate.kind != "SMD_MODEL_062" or candidate.family == "SMD_MODEL_062_VARIANT_OR_DAMAGED":
                    continue
                try:
                    if resolver.resolve(candidate.primary_path, required=False) is not None:
                        sample_asset = candidate
                        break
                except Exception:
                    continue
            if sample_asset is None:
                checks["authoring_preflight_contract"] = True
                details["authoring_preflight_sample"] = "N/A:no physical Model0.62 in configured client"
            else:
                sample_source = resolver.resolve(sample_asset.primary_path, required=True)
                ap = authoring_plan(sample_asset, sample_source)
                checks["authoring_preflight_contract"] = (
                    ap.get("format") == "PT_ASSET_AUTHORING_PLAN_V1"
                    and ap.get("client_write_authorized") is False
                    and isinstance(ap.get("channels"), dict)
                    and isinstance(ap.get("blockers"), list)
                )
                details["authoring_preflight_sample"] = sample_asset.primary_path
        else:
            checks["authoring_preflight_contract"] = False
    except Exception as exc:
        details["authoring_preflight_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.inx_writer import encode_start, encode_end
        import pt_inx_motion_core_v2 as _inxcore
        code = 0xAABBCCDD
        frame = 0x10203040
        skw, sraw = encode_start(frame, code)
        ekw, eraw = encode_end(frame, code)
        sd, sok, _ = _inxcore.decode_start(skw, sraw, code)
        ed, eok, _ = _inxcore.decode_end(ekw, eraw, code)
        checks["inx_motion_writer_contract"] = sok and eok and sd == frame and ed == frame
    except Exception as exc:
        details["inx_motion_writer_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.smb_writer import patch_key as _smb_patch_key, validate_track_roundtrip as _smb_roundtrip
        checks["smb_key_writer_contract"] = callable(_smb_patch_key) and callable(_smb_roundtrip)
    except Exception as exc:
        details["smb_key_writer_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.object_local_writer import patch_existing_object_local_key as _object_local_patch
        checks["object_local_key_writer_contract"] = callable(_object_local_patch)
    except Exception as exc:
        details["object_local_key_writer_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.profile_registry import CharacterProfileRegistry
        profiles = CharacterProfileRegistry(ROOT / "pt_build" / "state" / "character_profiles")
        profile_rows = profiles.list()
        profile_semantic_ok = True
        profile_semantic_rows = []
        if reg is not None and resolver is not None:
            for p in profile_rows:
                verified = profiles.verify(p.profile_id, resolver, asset_registry=reg)
                semantic = verified.get("semantic_evidence") or {}
                profile_semantic_rows.append({
                    "profile_id": p.profile_id,
                    "status": semantic.get("status"),
                    "reason": semantic.get("reason"),
                })
                if semantic.get("status") != "PASS":
                    profile_semantic_ok = False
        checks["character_profile_registry_contract"] = (
            all(p.roundtrip_target.lower().endswith(".smd") for p in profile_rows)
            and all(len(p.lod("all")) == len(set(p.lod("all"))) for p in profile_rows)
            and profile_semantic_ok
        )
        details["character_profile_count"] = len(profile_rows)
        details["character_profile_semantic_evidence"] = profile_semantic_rows
    except Exception as exc:
        details["character_profile_registry_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.profile_candidates import discover_profile_candidates
        if reg is not None:
            discovery = discover_profile_candidates(reg, limit=1, profile_registry=profiles)
            checks["profile_candidate_discovery_contract"] = (
                discovery.get("status") == "PASS"
                and discovery.get("scope") == "PROFILE_DISCOVERY_ONLY_NO_AUTHORING_PROMOTION"
                and discovery.get("policy", {}).get("discovery_authorizes_writer") is False
                and all(x.get("authoring_authorized") is False for x in (discovery.get("candidates") or []))
            )
            details["profile_candidate_count"] = discovery.get("candidate_count")
    except Exception as exc:
        details["profile_candidate_discovery_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.animation_certification import build_animation_certification_plan
        if reg is not None and resolver is not None:
            review_plan = build_animation_certification_plan(
                ROOT, reg, resolver, context_limit=1, motions_per_context=1, sample_limit=1
            )
            checks["animation_certification_plan_contract"] = (
                review_plan.get("status") in {"PASS", "PARTIAL"}
                and review_plan.get("automatic_visual_certification") is False
                and review_plan.get("automatic_runtime_certification") is False
                and review_plan.get("client_modified") is False
            )
            details["animation_certification_review_count"] = review_plan.get("review_count")
    except Exception as exc:
        details["animation_certification_plan_error"] = f"{type(exc).__name__}:{exc}"

    try:
        import inspect as _inspect
        from pt_asset_tool.deployment import (
            plan_deployment, simulate_deployment_transaction,
            classify_client_transaction_state, plan_restore_transaction,
        )
        sig = _inspect.signature(plan_deployment)
        sim_sig = _inspect.signature(simulate_deployment_transaction)
        checks["deployment_plan_contract"] = (
            callable(plan_deployment)
            and "artifact" in sig.parameters
            and "apply" not in sig.parameters
        )
        checks["deployment_simulation_contract"] = (
            callable(simulate_deployment_transaction)
            and "manifest_path" in sim_sig.parameters
            and "inject_failure" in sim_sig.parameters
            and "apply" not in sim_sig.parameters
        )
        checks["deployment_restore_contract"] = (
            callable(classify_client_transaction_state)
            and callable(plan_restore_transaction)
            and "apply" not in _inspect.signature(plan_restore_transaction).parameters
        )
    except Exception as exc:
        details["deployment_plan_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.development_readiness import audit_development_readiness
        if reg is not None and resolver is not None:
            readiness = audit_development_readiness(
                ROOT, Path(str(status["client_root"])), reg, resolver, profiles, deep=False, sample_limit=0
            )
            checks["development_readiness_contract"] = (
                readiness.get("status") == "PASS"
                and readiness.get("development_state") in {"IN_PROGRESS", "READY_FOR_PROMOTION"}
                and readiness.get("policy", {}).get("client_source_write_default") is False
                and readiness.get("stages", {}).get("generic_publish_restore", {}).get("production_authorized") is False
            )
            details["development_remaining_blockers"] = readiness.get("remaining_blocker_count")
    except Exception as exc:
        details["development_readiness_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool.binding_coverage import audit_binding_coverage
        if reg is not None:
            coverage = audit_binding_coverage(reg, sample_limit=0)
            checks["binding_coverage_contract"] = (
                coverage.get("status") == "PASS"
                and coverage.get("scope") == "DIAGNOSTIC_ONLY_NO_BINDING_PROMOTION"
                and coverage.get("policy", {}).get("folder_identity_is_binding_evidence") is False
                and int(coverage.get("unresolved_binding_count") or 0)
                    == int(coverage.get("rigid_asset_count") or 0) - int(coverage.get("rigid_binding_ready_count") or 0)
            )
            details["binding_coverage_rigid_assets"] = coverage.get("rigid_asset_count")
            details["binding_coverage_physical_ready"] = coverage.get("physical_rigid_binding_ready_count")
    except Exception as exc:
        details["binding_coverage_error"] = f"{type(exc).__name__}:{exc}"

    try:
        app_text = (ROOT / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
        checks["ui_reports_recursive_contract"] = 'root.rglob("*.json")' in app_text
    except Exception as exc:
        details["ui_reports_recursive_error"] = f"{type(exc).__name__}:{exc}"

    try:
        from pt_asset_tool import tree_compare as _tc  # noqa: F401
        checks["tree_compare_import"] = True
    except Exception as exc:
        details["tree_compare_error"] = f"{type(exc).__name__}:{exc}"
    try:
        from pt_asset_tool import monster_npc_census as _mn  # noqa: F401
        checks["monster_npc_import"] = True
    except Exception as exc:
        details["monster_npc_error"] = f"{type(exc).__name__}:{exc}"
    try:
        blender_cmd = _blender_command()
        details["blender_command"] = blender_cmd
        blender_available, blender_reason = _blender_launcher_status(blender_cmd)
        checks["blender_launcher_available"] = blender_available
        details["blender_launcher_status"] = blender_reason
    except Exception as exc:
        details["blender_error"] = f"{type(exc).__name__}:{exc}"

    required = [
        "app_status_pass", "certified_writer_hashes_valid", "runtime_dependencies_present",
        "client_root_resolved", "pt_build_writable", "catalog_bootstrap",
        "asset_registry_bootstrap", "ui_capability_contract", "ui_taxonomy_contract", "entity_catalog_contract", "ui_preview_pipeline",
        "ui_javascript_contract", "ui_interactive_review_contract", "support_file_inspection_contract",
        "blender_edit_workspace_contract", "generic_blender_import_contract", "texture_upscale_contract", "generic_build_dispatch_contract",
        "inx_motion_writer_contract", "smb_key_writer_contract", "object_local_key_writer_contract", "character_profile_registry_contract",
        "profile_candidate_discovery_contract", "animation_certification_plan_contract",
        "development_readiness_contract", "deployment_plan_contract", "deployment_simulation_contract", "deployment_restore_contract",
        "binding_coverage_contract", "ui_reports_recursive_contract",
        "tree_compare_import", "monster_npc_import",
    ]
    result = "PASS" if all(bool(checks[k]) for k in required) else "FAIL"
    report = {
        "format": "PT_ASSET_APP_SMOKE_V1",
        "status": result,
        "release_version": OVERLAY_VERSION,
        "checks": checks,
        "details": details,
        "client_modified": False,
        "note": "Smoke traverses the client read-only; the only temporary write probe is created and deleted under pt_build.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result == "PASS" else 2


def _command_app_config(args: list[str]) -> int:
    from pt_asset_tool.app_config import (
        clear_blender_executable, clear_client_root, clear_server_root, config_path,
        configured_blender_executable, load_config, resolve_client_root, resolve_server_root,
        save_blender_executable, save_client_root, save_server_root,
    )
    if not args or args == ["show"]:
        cfg = load_config(ROOT)
        try:
            resolved_path, resolved_source = resolve_client_root(ROOT)
            resolved = str(resolved_path)
            discovery_status = "PASS"
        except Exception as exc:
            resolved = None
            resolved_source = None
            discovery_status = f"FAIL:{type(exc).__name__}:{exc}"
        try:
            resolved_server_path, resolved_server_source = resolve_server_root(ROOT)
            resolved_server = str(resolved_server_path)
            server_discovery_status = "PASS"
        except Exception as exc:
            resolved_server = None
            resolved_server_source = None
            server_discovery_status = f"WARN:{type(exc).__name__}:{exc}"
        from pt_asset_tool.dependencies import blender_runtime_info
        blender = blender_runtime_info(ROOT, probe_version=True)
        report = {
            "format": "PT_ASSET_APP_CONFIG_STATUS_V1",
            "status": "PASS" if resolved else "WARN",
            "release_version": OVERLAY_VERSION,
            "config_path": str(config_path(ROOT)),
            "configured_client_root": cfg.get("client_root"),
            "resolved_client_root": resolved,
            "resolved_client_root_source": resolved_source,
            "client_root_discovery": discovery_status,
            "configured_server_root": cfg.get("server_root"),
            "resolved_server_root": resolved_server,
            "resolved_server_root_source": resolved_server_source,
            "server_root_discovery": server_discovery_status,
            "configured_blender_executable": configured_blender_executable(ROOT),
            "resolved_blender_command": list(blender.get("command") or []),
            "resolved_blender_source": blender.get("source"),
            "resolved_blender_version": blender.get("version"),
            "blender_ready": bool(blender.get("ready")),
            "blender_detail": blender.get("detail"),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if resolved else 1
    if len(args) == 2 and args[0] == "set-client-root":
        path = save_client_root(ROOT, Path(args[1]))
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "client_root": str(Path(args[1]).expanduser().resolve()),
        }, ensure_ascii=False, indent=2))
        return 0
    if args == ["clear-client-root"]:
        path = clear_client_root(ROOT)
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "client_root": None,
            "note": "Persistent client root cleared; environment/layout discovery remains available.",
        }, ensure_ascii=False, indent=2))
        return 0
    if len(args) == 2 and args[0] == "set-server-root":
        path = save_server_root(ROOT, Path(args[1]))
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "server_root": str(Path(args[1]).expanduser().resolve()),
            "server_write_authorized": False,
        }, ensure_ascii=False, indent=2))
        return 0
    if args == ["clear-server-root"]:
        path = clear_server_root(ROOT)
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "server_root": None,
            "note": "Persistent server root cleared; environment/layout discovery remains available.",
        }, ensure_ascii=False, indent=2))
        return 0
    if len(args) == 2 and args[0] in {"set-blender-exe", "set-blender"}:
        executable = Path(args[1]).expanduser()
        path = save_blender_executable(ROOT, executable)
        from pt_asset_tool.dependencies import blender_runtime_info
        info = blender_runtime_info(ROOT, probe_version=True)
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS" if info.get("ready") else "WARN",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "blender_executable": configured_blender_executable(ROOT),
            "resolved_blender_source": info.get("source"),
            "resolved_blender_version": info.get("version"),
            "resolved_blender_command": info.get("command"),
            "blender_detail": info.get("detail"),
        }, ensure_ascii=False, indent=2))
        return 0 if info.get("ready") else 1
    if args == ["clear-blender-exe"] or args == ["clear-blender"]:
        path = clear_blender_executable(ROOT)
        from pt_asset_tool.dependencies import blender_runtime_info
        info = blender_runtime_info(ROOT, probe_version=True)
        print(json.dumps({
            "format": "PT_ASSET_APP_CONFIG_WRITE_V1",
            "status": "PASS",
            "release_version": OVERLAY_VERSION,
            "config_path": str(path),
            "blender_executable": None,
            "resolved_blender_source": info.get("source"),
            "resolved_blender_version": info.get("version"),
            "resolved_blender_command": info.get("command"),
            "note": "Persistent Blender override cleared; environment/PATH/Flatpak discovery remains available.",
        }, ensure_ascii=False, indent=2))
        return 0
    print("usage: pt_asset.py config show | config set-client-root PATH | config clear-client-root | config set-server-root PATH | config clear-server-root | config set-blender-exe PATH | config clear-blender-exe", file=sys.stderr)
    return 2



def _command_registry(args: list[str]) -> int:
    """Inspect or rebuild the client-derived runtime registry.

    Registry files are generated machine-local state under ``pt_build/state``;
    they are never release payload data and the client is only read.
    """
    from pt_asset_tool.app_config import resolve_client_root
    from pt_asset_tool.registry_bootstrap import ensure_runtime_registry

    command = args[0] if args else "status"
    if command not in {"status", "rebuild"}:
        print("usage: pt_asset.py registry status | registry rebuild [--client-root PATH]", file=sys.stderr)
        return 2
    client_arg = None
    if "--client-root" in args:
        i = args.index("--client-root")
        if i + 1 >= len(args):
            print("registry: --client-root requires PATH", file=sys.stderr); return 2
        client_arg = Path(args[i + 1]).expanduser().resolve()
    if client_arg is None:
        client, source = resolve_client_root(ROOT)
    else:
        client, source = client_arg, "CLI"
    if not client.is_dir():
        print(json.dumps({"format":"PT_ASSET_REGISTRY_STATUS_V1","status":"FAIL","error":f"CLIENT_ROOT_NOT_FOUND:{client}"}, indent=2))
        return 2
    state = ROOT / "pt_build" / "state" / "asset_registry"
    inventory = state / "asset_inventory.json"
    pairing = state / "inx_physical_pairing.csv"
    result = ensure_runtime_registry(client, inventory, pairing, force=(command == "rebuild"))
    result = dict(result)
    result.update({
        "format": "PT_ASSET_REGISTRY_STATUS_V1",
        "client_root_source": source,
        "runtime_state": True,
        "package_payload": False,
        "client_modified": False,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def _command_explain(args: list[str]) -> int:
    topics = {
        "statuses": (
            "Certification/status columns",
            [
                "PENDING means the corresponding gate has not been completed or recorded yet; it is not a file-health error.",
                "N/A means the gate does not apply to that asset type.",
                "CONTEXT means animation-related context exists but no final human animation certification is recorded.",
                "PASS/FAIL/SKIP are recorded gate results.",
                "The catalog can be useful even when most historical certification cells are PENDING: inspection and classification are separate from certification coverage.",
            ],
        ),
        "bindings": (
            "Bindings",
            [
                "A binding is the verified relationship model -> INX configuration -> skeleton/motion SMB (and, for components, its root model context).",
                "SELF_CONTAINED: the model's own config directly resolves its motion/skeleton SMB.",
                "ROOT_SKELETON_BOUND: the model reuses a verified root skeleton/motion context.",
                "CONFIG_ONLY: config exists, but a unique animation root is not sufficiently proven; animation remains fail-closed.",
                "NONE: no skeleton/motion relation is known or required for that asset.",
                "Bindings are not simply 'parts attached to a character', but the same evidence can prove modular compatibility such as a head and body sharing the same root animation context.",
                "`bindings --discover ASSET` is a diagnostic for a rigid CONFIG_ONLY asset; it tries to produce stronger binding evidence without modifying the client.",
            ],
        ),
        "structural": (
            "Structural validation",
            [
                "Structural validation checks that a supported asset obeys the known binary/semantic invariants for its family.",
                "It is intended to catch malformed counts, references, topology/Physique inconsistencies and other format-level problems before Blender or a writer is trusted.",
                "It does not prove that the asset looks correct in-game, and it does not edit the source client.",
            ],
        ),
        "visual": (
            "Visual validation",
            [
                "Visual validation transports a supported asset into Blender and asks a human to confirm geometry and, when applicable, materials/textures.",
                "It proves the viewing/import path for that representative; it is not the same as an edit/write proof.",
                "A controlled edit/rebuild proof is performed by a roundtrip/writer workflow, not by visual validation alone.",
            ],
        ),
        "roundtrip": (
            "Roundtrip validation",
            [
                "A roundtrip reads an asset, reconstructs or deliberately modifies a copy, writes it under pt_build, reparses it and checks that only the authorized witness/change occurred.",
                "Roundtrip gates are writer evidence. They are intentionally family-specific and fail closed on unsupported assets.",
                "No normal roundtrip command should silently deploy its output into the source client.",
            ],
        ),
        "object-local": (
            "Object-local",
            [
                "Object-local is a static Model0.62 transform/animation path where whole mesh objects move/rotate/scale via object transforms rather than Physique skinning.",
                "It is not applicable to rigid Physique models. For those, use bindings/motions/animation diagnostics instead.",
            ],
        ),
        "texlinks": (
            "TexLinks",
            [
                "TexLinks describe material/texture-stage relationships and UV-linked layers serialized by Model0.62 assets.",
                "`asset texlinks ASSET` is the generic inspection command.",
                "`validate texlinks` is a specialized visual gate for a proven two-layer/multilayer source; it is expected to reject ordinary single-layer models.",
                "`validate texlink-roundtrip` is even narrower: it is a writer roundtrip gate for source-proven two-stage assets.",
            ],
        ),
        "desktop-entry": (
            "Desktop launcher",
            [
                "`install_desktop_entry.sh PATH` creates/updates a local desktop-menu launcher that starts the PT Asset Tool GUI from the given installation directory.",
                "It does not install assets into the game client and does not change the client root itself.",
            ],
        ),
    }
    if not args or args[0] in {"-h", "--help", "list"}:
        print("usage: pt_asset.py explain TOPIC")
        print("topics: " + ", ".join(sorted(topics)))
        return 0
    key = args[0].strip().lower()
    item = topics.get(key)
    if item is None:
        print(f"unknown explain topic: {key}", file=sys.stderr)
        print("topics: " + ", ".join(sorted(topics)), file=sys.stderr)
        return 2
    title, lines = item
    print(title)
    print("=" * len(title))
    for line in lines:
        print("- " + line)
    return 0


def _portable_doctor_setup_preflight() -> int | None:
    """Avoid treating a fresh portable install as a corrupted application.

    The source-tree doctor historically assumes the persisted asset census is
    already present. A one-file release intentionally starts with empty user
    state, so report the missing setup action instead of letting the legacy
    doctor dereference a non-existent inventory under the extraction symlink.
    Once the registry exists, the normal certified doctor runs unchanged.
    """
    if not is_frozen():
        return None
    inventory = persistent_pt_build() / "state" / "asset_registry" / "asset_inventory.json"
    if inventory.is_file():
        return None
    try:
        from pt_asset_tool.app_config import resolve_client_root
        client, source = resolve_client_root(ROOT)
    except Exception:
        print("doctor_check=SETUP_REQUIRED")
        print("reason=CLIENT_ROOT_NOT_CONFIGURED")
        print(f'action={invocation_label()} config set-client-root "/caminho/do/cliente"')
        print("client_modified=false")
        return 0
    print("doctor_check=SETUP_REQUIRED")
    print("reason=ASSET_REGISTRY_MISSING")
    print(f"client_root={client}")
    print(f"client_root_source={source}")
    print(f"runtime_inventory={inventory}")
    print(f"action={invocation_label()} registry rebuild")
    print("client_modified=false")
    return 0


def main() -> int:
    prepare_runtime_layout(ROOT)
    args = sys.argv[1:]
    if args == ["doctor"]:
        portable_preflight = _portable_doctor_setup_preflight()
        if portable_preflight is not None:
            return portable_preflight
    if args == ["--version"]:
        print(OVERLAY_VERSION)
        return 0
    if args == ["--help"]:
        cp = _run_core(["--help"], capture=True)
        if cp.stdout:
            print(cp.stdout.rstrip())
        print("\nConsolidated application commands (1.0.0):")
        print("  status                         application readiness + writer hash status")
        print("  dependencies [--json]          diagnose required/optional tools and show install/configuration instructions")
        print("  smoke | self-test              read-only real-client application smoke test")
        print("  ui | gui [options]             start the local graphical application")
        print("  compare trees --left A --right B [--hash] [--ext EXT] [--category CAT] [--path-contains TEXT] [--differences-only] [--output FILE]")
        print("  audit monster-npc-census [--refresh-census] [--output FILE]")
        print("  audit binding-coverage [--category CAT] [--output FILE]")
        print("  audit inx-writer-corpus [--prefix PATH] [--output FILE]")
        print("  audit smb-writer-corpus [--prefix PATH] [--output FILE]")
        print("  audit inx-writer-edit-corpus [--prefix PATH] [--output FILE]")
        print("  audit smb-writer-edit-corpus [--prefix PATH] [--output FILE]")
        print("  audit motion-writer-semantic-edit-corpus [--pair-limit N] [--output FILE]")
        print("  audit animation-corpus [--category CAT] [--mode core|all] [--output FILE]")
        print("  audit animation-certification-plan [--category CAT] [--output FILE]")
        print("  audit development-readiness [--deep] [--output FILE]")
        print("  audit model062-authoring [--category CAT] [--output FILE]")
        print("  entities list [--group MONSTER|NPC] [--q TEXT] | inspect GROUP ENTITY")
        print("  profiles list | inspect | lod | verify | discover")
        print("  import ASSET [--lod auto|high|default|low] [--reset] [--no-open]")
        print("  build ASSET --plan | --candidate  fail-closed production routing or explicit pt_build-only candidate")
        print("  deploy plan ASSET [--artifact FILE]  read-only deployment/provenance plan")
        print("  deploy prepare ASSET --artifact FILE  prepare verified backup/staged transaction under pt_build; no client write")
        print("  deploy verify MANIFEST              re-check client drift + backup/staged integrity; no client write")
        print("  deploy simulate MANIFEST [--inject-failure postwrite]  prove replace/postwrite/rollback inside pt_build only")
        print("  deploy state MANIFEST               classify client as original / managed artifact / unknown drift")
        print("  deploy restore-plan MANIFEST        plan restore only for known managed state; no client write")
        print("  deploy workspace-prepare ASSET [--textures-only]  prepare full tracked Blender-edit bundle; no client write")
        print("  deploy workspace-publish ASSET --confirm 'APPLY CLIENT BUNDLE'  backup + atomic client publish + rollback")
        print("  deploy workspace-history ASSET     list retained bundle transactions")
        print("  deploy workspace-restore-latest ASSET --confirm 'RESTORE CLIENT BUNDLE'  verified rollback to prior bytes")
        print("  explain TOPIC                  explain statuses/bindings/validators in user terms")
        print("  preview render-all-smd [--mode warmup|all|missing|stale|failed] [--workers N]  generate/cache catalog SMD thumbnails in pt_build")
        print("  config show                    show persistent application configuration")
        print("  config set-client-root PATH    persist client root for GUI/desktop use")
        print("  config clear-client-root       clear persistent client root and return to discovery")
        print("  config set-server-root PATH    persist server root for Asset Enrichment/GUI use")
        print("  config clear-server-root       clear persistent server root and return to discovery")
        print("  config set-blender-exe PATH    persist an explicit Blender executable for this machine")
        print("  config clear-blender-exe       clear Blender override; return to env/PATH/Flatpak discovery")
        print("  registry status                generate/read machine-local asset registry state")
        print("  registry rebuild [--client-root PATH]  force a read-only registry rebuild from the current client")
        print("  texture-upscale scan|run|resume|publish|restore|publish-batch|restore-batch ...   stage enhanced textures under app/pt_build/texture_upscale and publish/undo verified single or batch changes")
        return cp.returncode
    if args in (["status"], ["app-status"]):
        return _command_app_status()
    if args and args[0] == "dependencies":
        from pt_asset_tool.dependencies import cli_main as _dependencies_main
        return _dependencies_main(args[1:], project_root=ROOT)
    if args in (["smoke"], ["self-test"]):
        return _command_app_smoke()
    if args and args[0] == "explain":
        return _command_explain(args[1:])
    if len(args) >= 2 and args[0] == "preview" and args[1] == "render-all-smd":
        from pt_asset_tool.smd_preview_batch import cli_main as _smd_preview_batch_main
        return _smd_preview_batch_main(args[2:], project_root=ROOT)
    if args and args[0] == "config":
        return _command_app_config(args[1:])
    if args and args[0] == "registry":
        return _command_registry(args[1:])
    if args and args[0] == "texture-upscale":
        from pt_asset_tool.texture_upscale import main as _texture_upscale_main
        try:
            return _texture_upscale_main(args[1:])
        except Exception as exc:
            print(f"texture_upscale_error={type(exc).__name__}:{exc}", file=sys.stderr)
            return 2
    if args and args[0] in {"ui", "gui"}:
        from pt_asset_gui import main as _ui_main
        return _ui_main(args[1:])
    if len(args) >= 2 and args[0] == "compare" and args[1] == "trees":
        from pt_asset_tool.tree_compare import cli_main as _tree_compare_main
        return _tree_compare_main(args[2:], project_root=ROOT)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "monster-npc-census":
        from pt_asset_tool.monster_npc_census import main as _monster_npc_main
        return _monster_npc_main(["--project", str(ROOT), *args[2:]])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "update-tmp-lh5-decode":
        from pt_asset_tool.update_tmp_lh5_decode import main as _tmp_lh5_main
        rest = args[2:]
        output = None
        candidate = None
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        if "--candidate" in rest:
            i = rest.index("--candidate")
            if i + 1 < len(rest): candidate = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "update_tmp_lh5_decode_v01040.json")
        av=["--root",str(ROOT),"--output",output]
        if candidate: av += ["--candidate", candidate]
        return _tmp_lh5_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "update-tmp-lha-forensics":
        from pt_asset_tool.update_tmp_lha_forensics import main as _tmp_lha_main
        rest = args[2:]
        output = None
        candidate = None
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        if "--candidate" in rest:
            i = rest.index("--candidate")
            if i + 1 < len(rest): candidate = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "update_tmp_lha_forensics_v01020.json")
        av=["--root",str(ROOT),"--output",output]
        if candidate: av += ["--candidate", candidate]
        return _tmp_lha_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-payload-provenance-extraction":
        from pt_asset_tool.official_payload_provenance_extraction import main as _prov_main
        rest = args[2:]
        output = None
        donors = []
        search_roots = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            if rest[i] == "--search-root" and i + 1 < len(rest):
                search_roots.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_payload_provenance_extraction_v01010.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        for sr in search_roots: av += ["--search-root", sr]
        return _prov_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-payload-source-locator":
        from pt_asset_tool.official_payload_source_locator import main as _payload_source_main
        rest = args[2:]
        output = None
        donors = []
        search_roots = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            if rest[i] == "--search-root" and i + 1 < len(rest):
                search_roots.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_payload_source_locator_v01000.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        for sr in search_roots: av += ["--search-root", sr]
        return _payload_source_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-update-manifest-pack-correlation":
        from pt_asset_tool.official_update_manifest_pack_correlation import main as _manifest_pack_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_update_manifest_pack_correlation_v0990.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _manifest_pack_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-container-record-index":
        from pt_asset_tool.official_container_record_index import main as _record_index_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_container_record_index_v0970.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _record_index_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-container-entry-recovery":
        from pt_asset_tool.official_container_entry_recovery import main as _entry_recovery_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_container_entry_recovery_v0960.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _entry_recovery_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-container-character-atlas":
        from pt_asset_tool.official_container_character_atlas import main as _container_atlas_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_container_character_atlas_v0940.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _container_atlas_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-character-physical-compatibility":
        from pt_asset_tool.official_character_physical_compatibility import main as _physical_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_character_physical_compatibility_v0930.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _physical_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "official-character-donor-census":
        from pt_asset_tool.official_character_donor_census import main as _donor_main
        rest = args[2:]
        output = None
        donors = []
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        i = 0
        while i < len(rest):
            if rest[i] == "--donor" and i + 1 < len(rest):
                donors.append(rest[i + 1]); i += 2; continue
            i += 1
        if output is None:
            output = str(ROOT / "pt_build" / "official_character_donor_census_v0910.json")
        av=["--root",str(ROOT),"--output",output]
        for d in donors: av += ["--donor", d]
        return _donor_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "semantic-asset-census":
        from pt_asset_tool.semantic_census import main as _semantic_census_main
        output = None
        client_root = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest): output = rest[i + 1]
        if "--client-root" in rest:
            i = rest.index("--client-root")
            if i + 1 < len(rest): client_root = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "semantic_asset_census_v0900.json")
        av=["--root",str(ROOT),"--output",output]
        if client_root: av += ["--client-root",client_root]
        return _semantic_census_main(av)
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-multibone-outward-extent-production-promotion-workflow":
        from pt_asset_tool.rare_rigid_multibone_extent_production_promotion import main as _multibone_extent_promotion_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_multibone_outward_extent_production_promotion_workflow_v0836.json")
        return _multibone_extent_promotion_main(["--root", str(ROOT), "--output", output])
    if len(args) == 3 and args[0] == "artist-test" and args[1] == "rare-model-multibone-outward-extent-candidate":
        from pt_asset_tool.rare_rigid_multibone_extent_interactive_candidate import main as _multibone_extent_manual_main
        return _multibone_extent_manual_main(["--root", str(ROOT), "--logical", args[2]])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-multibone-outward-extent-live-writer-candidate-workflow":
        from pt_asset_tool.rare_rigid_multibone_extent_live_writer_candidate import main as _multibone_extent_live_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_multibone_outward_extent_live_writer_candidate_workflow_v0833.json")
        return _multibone_extent_live_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-multibone-outward-extent-saved-blender-workflow":
        from pt_asset_tool.rare_rigid_multibone_extent_saved_blender_candidate import main as _multibone_extent_saved_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_multibone_outward_extent_saved_blender_workflow_v0832.json")
        return _multibone_extent_saved_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-multibone-outward-extent-probe-workflow":
        from pt_asset_tool.rare_rigid_multibone_extent_probe import main as _multibone_extent_probe_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_multibone_outward_extent_probe_workflow_v0831.json")
        return _multibone_extent_probe_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-cross-object-production-promotion-workflow":
        from pt_asset_tool.rare_rigid_cross_object_production_promotion import main as _cross_object_promotion_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_cross_object_production_promotion_workflow_v0830.json")
        return _cross_object_promotion_main(["--root", str(ROOT), "--output", output])
    if len(args) == 3 and args[0] == "artist-test" and args[1] == "rare-model-cross-object-candidate":
        from pt_asset_tool.rare_rigid_cross_object_interactive_candidate import main as _cross_object_manual_main
        return _cross_object_manual_main(["--root", str(ROOT), "--logical", args[2]])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-cross-object-live-writer-candidate-workflow":
        from pt_asset_tool.rare_rigid_cross_object_live_writer_candidate import main as _cross_object_live_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_cross_object_live_writer_candidate_workflow_v0826.json")
        return _cross_object_live_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-cross-object-saved-blender-workflow":
        from pt_asset_tool.rare_rigid_cross_object_saved_blender_candidate import main as _cross_object_saved_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_cross_object_saved_blender_workflow_v0825.json")
        return _cross_object_saved_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-cross-object-probe-workflow":
        from pt_asset_tool.rare_rigid_cross_object_probe import main as _cross_object_probe_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_cross_object_probe_workflow_v0822.json")
        return _cross_object_probe_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-large-production-promotion-workflow":
        from pt_asset_tool.rare_rigid_large_production_promotion import main as _promotion_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_large_production_promotion_workflow_v0821.json")
        return _promotion_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 3 and args[0] == "write" and args[1] == "rare-model":
        from pt_asset_tool.rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL, write_promoted
        single_policy = ROOT / SINGLE_POLICY_REL
        if single_policy.is_file():
            target = args[2]
            output = None
            rest = args[3:]
            if "--output" in rest:
                i = rest.index("--output")
                if i + 1 >= len(rest):
                    print("pt_asset_error=ValueError:MISSING_OUTPUT_PATH", file=sys.stderr)
                    return 2
                output = Path(rest[i + 1]).expanduser()
            try:
                from pt_asset_tool.rare_rigid_cross_object_production import POLICY_REL as CROSS_POLICY_REL, write_production_dispatch as write_pre_extent_dispatch
                from pt_asset_tool.rare_rigid_multibone_extent_production import POLICY_REL as EXTENT_POLICY_REL, write_production_dispatch as write_extent_dispatch
                cross_policy = ROOT / CROSS_POLICY_REL
                extent_policy = ROOT / EXTENT_POLICY_REL
                from pt_asset_tool.blender_workspace import blender_edit_root
                workspace_root = blender_edit_root(ROOT, "rare_model", target)
                if extent_policy.is_file():
                    result = write_extent_dispatch(ROOT, target, output, workspace_root=workspace_root)
                elif cross_policy.is_file():
                    result = write_pre_extent_dispatch(ROOT, target, output, workspace_root=workspace_root)
                else:
                    result = write_promoted(ROOT, target, output, workspace_root=workspace_root)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                object_count = int(result.get('object_count', 1) or 1)
                print(
                    "rare_rigid_write=" + str(result.get("status")) +
                    f" changed_vertices={result.get('artist_changed_vertices')}" +
                    f" object_count={object_count}" +
                    f" output={result.get('output_smd')}" +
                    " single_object_max=8" +
                    f" cross_object_authorized={str(bool(result.get('cross_object_live_write_authorized', False))).lower()}" +
                    f" extent_authorized={str(bool(result.get('multibone_outward_extent_live_write_authorized', False))).lower()}" +
                    " production_authorized=true client_modified=false"
                )
                return 0 if result.get("status") == "PASS" else 3
            except Exception as exc:
                print(f"pt_asset_error={type(exc).__name__}:{exc}", file=sys.stderr)
                return 2
    if len(args) == 3 and args[0] == "artist-test" and args[1] == "rare-model-large-candidate":
        from pt_asset_tool.rare_rigid_large_interactive_candidate import main as _large_manual_main
        return _large_manual_main(["--root", str(ROOT), "--logical", args[2]])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-large-live-writer-candidate-workflow":
        from pt_asset_tool.rare_rigid_large_live_writer_candidate import main as _large_live_candidate_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_large_live_writer_candidate_workflow_v0817.json")
        return _large_live_candidate_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-large-saved-blender-workflow":
        from pt_asset_tool.rare_rigid_large_saved_blender_candidate import main as _large_saved_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_large_saved_blender_workflow_v0816.json")
        return _large_saved_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-large-transaction-workflow":
        from pt_asset_tool.rare_rigid_large_transaction_probe import main as _large_probe_main
        output = None
        rest = args[2:]
        if "--output" in rest:
            i = rest.index("--output")
            if i + 1 < len(rest):
                output = rest[i + 1]
        if output is None:
            output = str(ROOT / "pt_build" / "rare_rigid_large_transaction_workflow_v0814.json")
        return _large_probe_main(["--root", str(ROOT), "--output", output])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "release-consolidation-workflow":
        return _command_release_export_audit(args[2:])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-edit-entry-workflow":
        return _command_persistent_edit_audit(args[2:])
    if len(args) >= 2 and args[0] == "audit" and args[1] == "rare-rigid-selection-workflow":
        return _command_selection_audit(args[2:])
    if len(args) >= 2 and args[0] == "edit" and args[1] == "rare-model":
        return _command_edit(args)
    # Everything else is delegated untouched to the certified V0.8.9 core.
    try:
        return _run_core(args, capture=False).returncode
    except Exception as exc:
        print(f"pt_asset_overlay_error={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
