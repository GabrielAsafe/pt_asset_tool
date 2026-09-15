from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from .workflow_dispatch import build_plan
from .build_provenance import verify_build_provenance

FORMAT = "PT_ASSET_DEPLOYMENT_PLAN_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def plan_deployment(project_root, resolver, registry, target: str, artifact: str | pathlib.Path | None = None) -> dict[str, Any]:
    """Produce a read-only deployment plan for one asset.

    The planner deliberately has no apply mode.  It exists so generic
    publish/restore can be designed around explicit provenance, source drift,
    backup and rollback requirements before any app-level client write is
    enabled.
    """
    project_root = pathlib.Path(project_root).resolve()
    build_root = (project_root / "pt_build").resolve()
    asset = registry.resolve(target)
    source = pathlib.Path(resolver.resolve(asset.primary_path)).resolve()
    writer_plan = build_plan(asset)

    artifact_path: pathlib.Path | None = None
    artifact_error: str | None = None
    if artifact is not None:
        raw = pathlib.Path(artifact).expanduser()
        artifact_path = (project_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if not _inside(build_root, artifact_path):
            artifact_error = "ARTIFACT_OUTSIDE_PT_BUILD"
        elif not artifact_path.is_file():
            artifact_error = "ARTIFACT_MISSING"

    source_sha = _sha256(source)
    artifact_sha = _sha256(artifact_path) if artifact_path is not None and artifact_error is None else None
    artifact_size = artifact_path.stat().st_size if artifact_path is not None and artifact_error is None else None
    source_size = source.stat().st_size

    blockers: list[str] = []
    provenance = None
    if not writer_plan.get("authorized"):
        blockers.append("ASSET_WRITER_NOT_PRODUCTION_AUTHORIZED")
    if artifact is None:
        blockers.append("BUILD_ARTIFACT_REQUIRED")
    elif artifact_error:
        blockers.append(artifact_error)
    elif artifact_path is not None:
        provenance = verify_build_provenance(
            artifact_path,
            expected_asset_id=asset.asset_id,
            expected_asset_path=asset.primary_path,
            expected_source=source,
        )
        if provenance.get("status") != "PASS":
            blockers.append("BUILD_PROVENANCE_INVALID")
        else:
            selected_context = provenance.get("selected_context")
            if selected_context is not None:
                from .authoring import verify_selected_context_for_asset
                context_asset_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver)
                provenance["selected_context_asset_verification"] = context_asset_verify
                if context_asset_verify.get("status") != "PASS":
                    blockers.append("BUILD_SELECTED_CONTEXT_ASSET_MISMATCH")
            if not provenance.get("production_authorized"):
                blockers.append("BUILD_PROVENANCE_NOT_PRODUCTION_AUTHORIZED")
    if artifact_sha is not None and artifact_sha == source_sha and artifact_size == source_size:
        blockers.append("ARTIFACT_EQUALS_SOURCE_NO_DEPLOYMENT_NEEDED")

    # These are app-level deployment gates and remain blockers even for a
    # certified build writer until generic publish/restore is explicitly
    # promoted and regression-tested.
    blockers.extend([
        "GENERIC_CLIENT_DEPLOYMENT_POLICY_NOT_PROMOTED",
        "TRANSACTION_MANIFEST_NOT_CREATED",
        "PREWRITE_CLIENT_DRIFT_GATE_REQUIRED",
        "VERIFIED_BACKUP_AND_ROLLBACK_GATE_REQUIRED",
    ])

    return {
        "format": FORMAT,
        "status": "BLOCKED" if blockers else "PLAN_READY",
        "operation": "PUBLISH_PLAN_ONLY",
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "family": asset.family,
        "kind": asset.kind,
        "source_client_path": str(source),
        "source_sha256": source_sha,
        "source_size": source_size,
        "artifact": str(artifact_path) if artifact_path is not None else None,
        "artifact_sha256": artifact_sha,
        "artifact_size": artifact_size,
        "artifact_inside_pt_build": bool(artifact_path is not None and _inside(build_root, artifact_path)),
        "artifact_differs_from_source": bool(
            artifact_sha is not None and (artifact_sha != source_sha or artifact_size != source_size)
        ),
        "writer_plan": writer_plan,
        "build_provenance": provenance,
        "blockers": blockers,
        "client_write_authorized": False,
        "apply_mode_available": False,
        "required_transaction_contract": {
            "source_identity": "asset registry logical path + physical SHA/size",
            "artifact_identity": "pt_build-contained artifact SHA/size",
            "prewrite_client_state": "registered source or known managed build only",
            "backup": "copy destination before first write and verify SHA/size",
            "publish": "atomic replace from verified temporary copy",
            "rollback": "restore every already-written destination after any failure",
            "postwrite": "verify destination SHA/size equals planned artifact",
        },
        "client_modified": False,
    }


def prepare_deployment_transaction(project_root, resolver, registry, target: str, artifact: str | pathlib.Path) -> dict[str, Any]:
    """Prepare a verified deployment transaction without writing the client.

    The transaction snapshots the current client source into pt_build and stages
    a byte-verified copy of the requested artifact.  It intentionally does not
    implement apply; the remaining promotion/policy blockers are preserved.
    """
    import json
    import shutil
    import uuid

    project_root = pathlib.Path(project_root).resolve()
    plan = plan_deployment(project_root, resolver, registry, target, artifact)
    if plan.get("artifact") is None:
        raise RuntimeError("deployment prepare requires an artifact")
    if "ARTIFACT_OUTSIDE_PT_BUILD" in plan.get("blockers", []):
        raise RuntimeError("deployment prepare refuses artifact outside pt_build")
    if "ARTIFACT_MISSING" in plan.get("blockers", []):
        raise RuntimeError("deployment prepare requires an existing artifact")
    if "ARTIFACT_EQUALS_SOURCE_NO_DEPLOYMENT_NEEDED" in plan.get("blockers", []):
        raise RuntimeError("deployment prepare refuses a byte-identical no-op artifact")

    source = pathlib.Path(plan["source_client_path"]).resolve()
    artifact_path = pathlib.Path(plan["artifact"]).resolve()
    safe_asset = "__".join(
        x for x in pathlib.PurePosixPath(str(plan["asset"])).with_suffix("").parts if x
    ) or "asset"
    safe_asset = "".join(c if c.isalnum() or c in "._-" else "_" for c in safe_asset)[:140]
    txid = uuid.uuid4().hex[:12]
    txroot = (project_root / "pt_build" / "deploy_transactions" / safe_asset / txid).resolve()
    backup = txroot / "backup" / pathlib.PurePosixPath(str(plan["asset"])).name
    staged = txroot / "staged" / artifact_path.name
    provenance_snapshot = txroot / "provenance" / "build_provenance.json"
    manifest = txroot / "transaction.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    staged.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source, backup)
    shutil.copy2(artifact_path, staged)
    build_prov = plan.get("build_provenance") or {}
    prov_src = pathlib.Path(str(build_prov.get("provenance") or "")) if build_prov else None
    provenance_copy = None
    if prov_src is not None and prov_src.is_file():
        provenance_snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prov_src, provenance_snapshot)
        provenance_copy = {
            "path": str(provenance_snapshot),
            "sha256": _sha256(provenance_snapshot),
            "size": provenance_snapshot.stat().st_size,
            "source_path": str(prov_src),
            "source_verification": build_prov,
        }
    backup_sha = _sha256(backup)
    staged_sha = _sha256(staged)
    errors: list[str] = []
    if backup_sha != plan["source_sha256"] or backup.stat().st_size != plan["source_size"]:
        errors.append("BACKUP_VERIFICATION_FAILED")
    if staged_sha != plan["artifact_sha256"] or staged.stat().st_size != plan["artifact_size"]:
        errors.append("STAGED_ARTIFACT_VERIFICATION_FAILED")
    # Re-check the source after both copies to catch a client mutation racing
    # transaction preparation. This is still a read-only drift gate.
    current_source_sha = _sha256(source)
    current_source_size = source.stat().st_size
    if current_source_sha != plan["source_sha256"] or current_source_size != plan["source_size"]:
        errors.append("CLIENT_DRIFT_DURING_PREPARE")

    remaining = [
        x for x in plan.get("blockers", [])
        if x not in {
            "TRANSACTION_MANIFEST_NOT_CREATED",
            "VERIFIED_BACKUP_AND_ROLLBACK_GATE_REQUIRED",
            "PREWRITE_CLIENT_DRIFT_GATE_REQUIRED",
        }
    ]
    if errors:
        remaining = errors + remaining
    payload = {
        "format": "PT_ASSET_DEPLOYMENT_TRANSACTION_V1",
        "status": "PREPARED_BLOCKED" if remaining else "PREPARED",
        "transaction_id": txid,
        "asset_id": plan["asset_id"],
        "asset": plan["asset"],
        "family": plan["family"],
        "kind": plan["kind"],
        "transaction_root": str(txroot),
        "destination": str(source),
        "source_snapshot": {
            "sha256": plan["source_sha256"],
            "size": plan["source_size"],
            "post_prepare_sha256": current_source_sha,
            "post_prepare_size": current_source_size,
        },
        "artifact_input": {
            "path": str(artifact_path),
            "sha256": plan["artifact_sha256"],
            "size": plan["artifact_size"],
        },
        "backup": {
            "path": str(backup),
            "sha256": backup_sha,
            "size": backup.stat().st_size,
            "verified": backup_sha == plan["source_sha256"] and backup.stat().st_size == plan["source_size"],
        },
        "staged_artifact": {
            "path": str(staged),
            "sha256": staged_sha,
            "size": staged.stat().st_size,
            "verified": staged_sha == plan["artifact_sha256"] and staged.stat().st_size == plan["artifact_size"],
        },
        "build_provenance_snapshot": provenance_copy,
        "selected_context": build_prov.get("selected_context") if build_prov else None,
        "selected_context_asset_verification": build_prov.get("selected_context_asset_verification") if build_prov else None,
        "writer_plan": plan["writer_plan"],
        "plan_blockers": list(plan.get("blockers") or []),
        "remaining_blockers": remaining,
        "rollback_material_ready": not errors,
        "prewrite_drift_snapshot_ready": "CLIENT_DRIFT_DURING_PREPARE" not in errors,
        "apply_mode_available": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["manifest"] = str(manifest)
    return payload


def verify_deployment_transaction(manifest_path: str | pathlib.Path) -> dict[str, Any]:
    """Re-verify a prepared transaction and current client drift without writes."""
    import json

    manifest_path = pathlib.Path(manifest_path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("format") != "PT_ASSET_DEPLOYMENT_TRANSACTION_V1":
        errors.append("FORMAT")

    def check_file(section: str, expected_sha: str | None, expected_size: int | None):
        row = data.get(section) or {}
        p = pathlib.Path(str(row.get("path") or ""))
        if not p.is_file():
            errors.append(section.upper() + "_MISSING")
            return
        if expected_size is not None and p.stat().st_size != int(expected_size):
            errors.append(section.upper() + "_SIZE_DRIFT")
        if expected_sha and _sha256(p) != expected_sha:
            errors.append(section.upper() + "_SHA_DRIFT")

    source = pathlib.Path(str(data.get("destination") or ""))
    snap = data.get("source_snapshot") or {}
    if not source.is_file():
        errors.append("CLIENT_SOURCE_MISSING")
    else:
        if source.stat().st_size != int(snap.get("size") or -1) or _sha256(source) != snap.get("sha256"):
            errors.append("CLIENT_DRIFT")
    check_file("backup", snap.get("sha256"), snap.get("size"))
    art = data.get("artifact_input") or {}
    check_file("staged_artifact", art.get("sha256"), art.get("size"))
    prov = data.get("build_provenance_snapshot")
    snapshot_data = None
    if prov:
        pp = pathlib.Path(str(prov.get("path") or ""))
        if not pp.is_file():
            errors.append("BUILD_PROVENANCE_SNAPSHOT_MISSING")
        else:
            if pp.stat().st_size != int(prov.get("size") or -1):
                errors.append("BUILD_PROVENANCE_SNAPSHOT_SIZE_DRIFT")
            if _sha256(pp) != str(prov.get("sha256") or ""):
                errors.append("BUILD_PROVENANCE_SNAPSHOT_SHA_DRIFT")
            try:
                snapshot_data = json.loads(pp.read_text(encoding="utf-8"))
            except Exception:
                errors.append("BUILD_PROVENANCE_SNAPSHOT_PARSE")

    selected_context = data.get("selected_context")
    selected_context_verification = None
    if selected_context is not None:
        from .authoring import verify_selected_authoring_context
        selected_context_verification = verify_selected_authoring_context(selected_context)
        if selected_context_verification.get("status") != "PASS":
            errors.append("SELECTED_CONTEXT_DRIFT")
        if snapshot_data is not None and snapshot_data.get("selected_context") != selected_context:
            errors.append("SELECTED_CONTEXT_SNAPSHOT_MISMATCH")
    elif snapshot_data is not None and snapshot_data.get("selected_context") is not None:
        errors.append("SELECTED_CONTEXT_TRANSACTION_MISSING")

    return {
        "format": "PT_ASSET_DEPLOYMENT_TRANSACTION_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "manifest": str(manifest_path),
        "transaction_id": data.get("transaction_id"),
        "asset": data.get("asset"),
        "errors": sorted(set(errors)),
        "client_drift": "CLIENT_DRIFT" in errors,
        "rollback_material_ready": not any(x.startswith("BACKUP_") for x in errors),
        "staged_artifact_ready": not any(x.startswith("STAGED_ARTIFACT_") for x in errors),
        "build_provenance_snapshot_ready": not any(x.startswith("BUILD_PROVENANCE_SNAPSHOT_") for x in errors),
        "selected_context": selected_context,
        "selected_context_verification": selected_context_verification,
        "selected_context_ready": not any(x.startswith("SELECTED_CONTEXT_") for x in errors),
        "apply_mode_available": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def simulate_deployment_transaction(manifest_path: str | pathlib.Path, *, inject_failure: str | None = None) -> dict[str, Any]:
    """Exercise atomic replace + rollback entirely inside pt_build.

    This is a proof harness for the generic deployment transaction contract. It
    never opens the real client destination for writing: the backup is copied
    into a disposable sandbox under the prepared transaction root, the staged
    artifact is atomically replaced into that sandbox, post-write identity is
    verified, and rollback is then exercised from the verified backup.

    ``inject_failure='postwrite'`` simulates an exception after the replacement
    and requires rollback to recover the original source identity.
    """
    import json
    import os
    import shutil
    import uuid

    manifest_path = pathlib.Path(manifest_path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = verify_deployment_transaction(manifest_path)
    if verified.get("status") != "PASS":
        raise RuntimeError(f"deployment simulation requires a verified transaction: {verified.get('errors')}")
    if inject_failure not in {None, "postwrite"}:
        raise ValueError("inject_failure must be omitted or 'postwrite'")

    txroot = pathlib.Path(str(data.get("transaction_root") or manifest_path.parent)).resolve()
    # A prepared manifest is only trusted for simulation if all of its mutable
    # test material remains inside the transaction root / pt_build hierarchy.
    backup = pathlib.Path(str((data.get("backup") or {}).get("path") or "")).resolve()
    staged = pathlib.Path(str((data.get("staged_artifact") or {}).get("path") or "")).resolve()
    if not _inside(txroot, backup) or not _inside(txroot, staged):
        raise RuntimeError("deployment simulation refuses transaction material outside transaction_root")

    sim_id = uuid.uuid4().hex[:12]
    simroot = (txroot / "simulation" / sim_id).resolve()
    simroot.mkdir(parents=True, exist_ok=False)
    destination = simroot / pathlib.PurePosixPath(str(data.get("asset") or "asset.bin")).name
    temp_publish = simroot / (destination.name + ".publish_tmp")
    temp_rollback = simroot / (destination.name + ".rollback_tmp")
    report_path = simroot / "simulation.json"

    source_snap = data.get("source_snapshot") or {}
    artifact = data.get("artifact_input") or {}
    expected_source_sha = str(source_snap.get("sha256") or "")
    expected_source_size = int(source_snap.get("size") or -1)
    expected_artifact_sha = str(artifact.get("sha256") or "")
    expected_artifact_size = int(artifact.get("size") or -1)

    # Start from the verified backup rather than the live client destination.
    shutil.copy2(backup, destination)
    errors: list[str] = []
    if destination.stat().st_size != expected_source_size or _sha256(destination) != expected_source_sha:
        errors.append("SIMULATION_BASELINE_VERIFICATION_FAILED")

    atomic_replace_pass = False
    postwrite_verification_pass = False
    rollback_attempted = False
    rollback_pass = False
    failure_injected = False
    caught_error: str | None = None

    try:
        shutil.copy2(staged, temp_publish)
        if temp_publish.stat().st_size != expected_artifact_size or _sha256(temp_publish) != expected_artifact_sha:
            raise RuntimeError("SIMULATION_STAGED_COPY_VERIFICATION_FAILED")
        os.replace(temp_publish, destination)
        atomic_replace_pass = True
        postwrite_verification_pass = (
            destination.stat().st_size == expected_artifact_size
            and _sha256(destination) == expected_artifact_sha
        )
        if not postwrite_verification_pass:
            raise RuntimeError("SIMULATION_POSTWRITE_VERIFICATION_FAILED")
        if inject_failure == "postwrite":
            failure_injected = True
            raise RuntimeError("INJECTED_POSTWRITE_FAILURE")
    except Exception as exc:
        caught_error = f"{type(exc).__name__}: {exc}"
    finally:
        # Always exercise rollback after a simulated write. This proves both the
        # happy-path replacement and the recovery path without leaving an edited
        # sandbox destination behind.
        if atomic_replace_pass:
            rollback_attempted = True
            try:
                shutil.copy2(backup, temp_rollback)
                if temp_rollback.stat().st_size != expected_source_size or _sha256(temp_rollback) != expected_source_sha:
                    raise RuntimeError("SIMULATION_ROLLBACK_COPY_VERIFICATION_FAILED")
                os.replace(temp_rollback, destination)
                rollback_pass = (
                    destination.stat().st_size == expected_source_size
                    and _sha256(destination) == expected_source_sha
                )
                if not rollback_pass:
                    errors.append("SIMULATION_ROLLBACK_VERIFICATION_FAILED")
            except Exception as exc:
                errors.append(f"SIMULATION_ROLLBACK_ERROR:{type(exc).__name__}:{exc}")

    if caught_error and not failure_injected:
        errors.append(caught_error)
    if not atomic_replace_pass:
        errors.append("SIMULATION_ATOMIC_REPLACE_NOT_PROVEN")
    if not postwrite_verification_pass:
        errors.append("SIMULATION_POSTWRITE_NOT_PROVEN")
    if not rollback_attempted or not rollback_pass:
        errors.append("SIMULATION_ROLLBACK_NOT_PROVEN")

    # Re-read only the real client source after simulation to prove this harness
    # did not modify it.
    live_source = pathlib.Path(str(data.get("destination") or ""))
    client_unchanged = bool(
        live_source.is_file()
        and live_source.stat().st_size == expected_source_size
        and _sha256(live_source) == expected_source_sha
    )
    if not client_unchanged:
        errors.append("CLIENT_CHANGED_DURING_SIMULATION")

    payload = {
        "format": "PT_ASSET_DEPLOYMENT_SIMULATION_V1",
        "status": "PASS" if not errors else "FAIL",
        "transaction_id": data.get("transaction_id"),
        "simulation_id": sim_id,
        "manifest": str(manifest_path),
        "simulation_root": str(simroot),
        "simulated_destination": str(destination),
        "atomic_replace_pass": atomic_replace_pass,
        "postwrite_verification_pass": postwrite_verification_pass,
        "rollback_attempted": rollback_attempted,
        "rollback_pass": rollback_pass,
        "failure_injected": failure_injected,
        "injected_failure_point": inject_failure,
        "caught_error": caught_error,
        "errors": sorted(set(errors)),
        "client_source_unchanged": client_unchanged,
        "client_modified": False,
        "client_write_authorized": False,
        "apply_mode_available": False,
        "proof_scope": "PT_BUILD_SANDBOX_ONLY_ATOMIC_REPLACE_POSTWRITE_ROLLBACK",
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["report"] = str(report_path)
    return payload


def classify_client_transaction_state(manifest_path: str | pathlib.Path) -> dict[str, Any]:
    """Classify the live destination against the prepared original/build identities.

    This is the fail-closed state classifier required by generic restore:
    - ORIGINAL_SOURCE: destination still matches the source snapshot;
    - MANAGED_ARTIFACT: destination exactly matches the transaction artifact;
    - UNKNOWN_DRIFT: any other bytes/size;
    - MISSING: destination disappeared.

    The classifier is read-only and does not imply that apply/restore is enabled.
    """
    import json

    manifest_path = pathlib.Path(manifest_path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("format") != "PT_ASSET_DEPLOYMENT_TRANSACTION_V1":
        raise RuntimeError("client state classification requires PT_ASSET_DEPLOYMENT_TRANSACTION_V1")
    destination = pathlib.Path(str(data.get("destination") or ""))
    source = data.get("source_snapshot") or {}
    artifact = data.get("artifact_input") or {}
    if not destination.is_file():
        state = "MISSING"
        actual_sha = None
        actual_size = None
    else:
        actual_size = destination.stat().st_size
        actual_sha = _sha256(destination)
        if actual_size == int(source.get("size") or -1) and actual_sha == str(source.get("sha256") or ""):
            state = "ORIGINAL_SOURCE"
        elif actual_size == int(artifact.get("size") or -1) and actual_sha == str(artifact.get("sha256") or ""):
            state = "MANAGED_ARTIFACT"
        else:
            state = "UNKNOWN_DRIFT"
    return {
        "format": "PT_ASSET_CLIENT_TRANSACTION_STATE_V1",
        "status": "PASS" if state in {"ORIGINAL_SOURCE", "MANAGED_ARTIFACT"} else "BLOCKED",
        "manifest": str(manifest_path),
        "transaction_id": data.get("transaction_id"),
        "asset": data.get("asset"),
        "destination": str(destination),
        "state": state,
        "actual_sha256": actual_sha,
        "actual_size": actual_size,
        "original_source_sha256": source.get("sha256"),
        "managed_artifact_sha256": artifact.get("sha256"),
        "known_state": state in {"ORIGINAL_SOURCE", "MANAGED_ARTIFACT"},
        "restore_candidate": state == "MANAGED_ARTIFACT",
        "client_write_authorized": False,
        "client_modified": False,
    }


def plan_restore_transaction(manifest_path: str | pathlib.Path) -> dict[str, Any]:
    """Plan restoration from a prepared verified backup; never writes the client."""
    import json

    manifest_path = pathlib.Path(manifest_path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = classify_client_transaction_state(manifest_path)
    errors: list[str] = []

    # Verify immutable rollback material separately. verify_deployment_transaction
    # intentionally fails when the client is the managed artifact, so restore
    # planning verifies backup/staged/provenance directly instead of requiring the
    # destination to still equal the original source.
    snap = data.get("source_snapshot") or {}
    backup = data.get("backup") or {}
    backup_path = pathlib.Path(str(backup.get("path") or ""))
    if not backup_path.is_file():
        errors.append("BACKUP_MISSING")
    else:
        if backup_path.stat().st_size != int(snap.get("size") or -1):
            errors.append("BACKUP_SIZE_DRIFT")
        if _sha256(backup_path) != str(snap.get("sha256") or ""):
            errors.append("BACKUP_SHA_DRIFT")

    prov = data.get("build_provenance_snapshot")
    if prov:
        p = pathlib.Path(str(prov.get("path") or ""))
        if not p.is_file():
            errors.append("BUILD_PROVENANCE_SNAPSHOT_MISSING")
        else:
            if p.stat().st_size != int(prov.get("size") or -1):
                errors.append("BUILD_PROVENANCE_SNAPSHOT_SIZE_DRIFT")
            if _sha256(p) != str(prov.get("sha256") or ""):
                errors.append("BUILD_PROVENANCE_SNAPSHOT_SHA_DRIFT")

    blockers: list[str] = list(errors)
    if state["state"] == "ORIGINAL_SOURCE":
        blockers.append("RESTORE_NOT_NEEDED_CLIENT_IS_ORIGINAL_SOURCE")
    elif state["state"] == "UNKNOWN_DRIFT":
        blockers.append("CLIENT_DRIFT_UNKNOWN_REFUSE_RESTORE")
    elif state["state"] == "MISSING":
        blockers.append("CLIENT_SOURCE_MISSING_REFUSE_RESTORE")
    elif state["state"] == "MANAGED_ARTIFACT":
        # Known managed state is the only byte identity where restoration could
        # eventually be authorized, but app-level writes remain disabled.
        blockers.append("GENERIC_CLIENT_RESTORE_POLICY_NOT_PROMOTED")
        blockers.append("RESTORE_APPLY_MODE_DISABLED")

    restore_semantically_eligible = (
        state["state"] == "MANAGED_ARTIFACT"
        and not errors
        and backup_path.is_file()
    )
    return {
        "format": "PT_ASSET_RESTORE_PLAN_V1",
        "status": "RESTORE_CANDIDATE_BLOCKED" if restore_semantically_eligible else "BLOCKED",
        "manifest": str(manifest_path),
        "transaction_id": data.get("transaction_id"),
        "asset": data.get("asset"),
        "client_state": state,
        "backup": backup,
        "restore_semantically_eligible": restore_semantically_eligible,
        "blockers": blockers,
        "apply_mode_available": False,
        "client_write_authorized": False,
        "client_modified": False,
        "policy": {
            "original_source": "UNCHANGED_NO_RESTORE",
            "managed_artifact": "RESTORE_MAY_BE_PLANNED_BUT_APPLY_DISABLED",
            "unknown_drift": "FAIL_CLOSED",
        },
    }
