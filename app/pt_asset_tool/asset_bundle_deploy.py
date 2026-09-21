from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import time
from typing import Any

from .asset_compiler import BUNDLE_BUILD_FORMAT
from .asset_contract_registry import get_contract, match_contracts_for_path
from .server_lifecycle import classify_server_path

TX_FORMAT = "PT_ASSET_BUNDLE_TRANSACTION_V1"
APPLY_CONFIRM = "APPLY ASSET BUNDLE"
RESTORE_CONFIRM = "RESTORE ASSET BUNDLE"

_BLOCKED_SOURCE_CAPABILITIES = {
    "RUNTIME_STATE_NOT_ASSET",
    "RUNTIME_DIAGNOSTIC_NOT_ASSET",
    "DORMANT_SOURCE_CONTRACT",
    "OPERATIONAL_CONFIG_AUTHORABLE",
    "SECURITY_CONFIG_OPERATIONAL_ONLY",
}
_BLOCKED_SERVER_POLICIES = {
    "BLOCKED_PERSISTENCE",
    "BLOCKED_STATE",
    "BLOCKED_RUNTIME_INTEGRITY",
    "FORENSICS_ONLY",
    "EXCLUDED_TOOLING",
}
_ALLOWED_PATCH_KINDS = {'SPM_ADD_ACTOR', 'SPC_ADD_NPC', 'LEGACY_SPC_PATCH', 'LEGACY_SPM_PATCH', 'LEGACY_SPP_PATCH', 'LEGACY_TEXT_PATCH'}
_BUNDLE_GRAPH_CONTRACTS = {
    "model.config.ini", "model.cache.inx", "model.smd.062", "model.smb.bone", "stage.smd.072", "texture.standard",
}
_BUNDLE_GRAPH_ROLES = {
    "model.config.ini": {"config"},
    "model.cache.inx": {"derived_cache"},
    "model.smd.062": {"direct_model", "model_file"},
    "model.smb.bone": {"direct_model", "motion_file", "aux_motion_file"},
    "stage.smd.072": {"stage_file"},
    "texture.standard": {"model_texture", "stage_texture"},
}


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    text = str(value or "").strip().replace("\\", "/").lstrip("/")
    rel = pathlib.PurePosixPath(text)
    if not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"INVALID_LOGICAL_PATH:{value}")
    return rel


def _target_path(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path:
    root = pathlib.Path(root).resolve()
    cur = root
    # Reject symlink traversal even when the final file does not exist yet.
    for part in rel.parts[:-1]:
        nxt = cur / part
        if nxt.exists() and nxt.is_symlink():
            raise ValueError(f"TARGET_PARENT_SYMLINK_BLOCKED:{rel.as_posix()}:{nxt}")
        cur = nxt
    target = root.joinpath(*rel.parts)
    try:
        target.parent.resolve().relative_to(root)
    except Exception as exc:
        raise ValueError(f"TARGET_ESCAPES_ROOT:{rel.as_posix()}") from exc
    if target.exists() and target.is_symlink():
        raise ValueError(f"TARGET_SYMLINK_BLOCKED:{rel.as_posix()}")
    return target


def _atomic_copy(source: pathlib.Path, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_manifest(manifest: pathlib.Path | str) -> tuple[pathlib.Path, dict[str, Any]]:
    path = pathlib.Path(manifest).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"ASSET_BUNDLE_MANIFEST_NOT_FOUND:{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != BUNDLE_BUILD_FORMAT or data.get("status") != "PASS":
        raise ValueError("ASSET_BUNDLE_MANIFEST_INVALID")
    overlay = pathlib.Path(str(data.get("overlay_root") or "")).resolve()
    if not overlay.is_dir():
        raise ValueError("ASSET_BUNDLE_OVERLAY_NOT_FOUND")
    try:
        overlay.relative_to(path.parent)
    except Exception as exc:
        raise ValueError("ASSET_BUNDLE_OVERLAY_OUTSIDE_RUN") from exc
    return path, data


def latest_bundle_manifest(project_root: pathlib.Path | str) -> pathlib.Path | None:
    root = pathlib.Path(project_root).resolve() / "pt_build" / "asset_compiler" / "bundles"
    if not root.is_dir():
        return None
    rows = [p for p in root.glob("*/manifest.json") if p.is_file()]
    return max(rows, key=lambda p: p.stat().st_mtime) if rows else None


def _bundle_workspace_root(project_root: pathlib.Path | str) -> pathlib.Path:
    return pathlib.Path(project_root).resolve() / "pt_build" / "asset_compiler" / "bundles"


def _assert_project_manifest(project_root: pathlib.Path | str, manifest_path: pathlib.Path) -> None:
    root = _bundle_workspace_root(project_root).resolve()
    try:
        manifest_path.resolve().relative_to(root)
    except Exception as exc:
        raise ValueError(f"ASSET_BUNDLE_MANIFEST_OUTSIDE_PROJECT:{manifest_path}") from exc


def _active_transactions(project_root: pathlib.Path | str) -> list[dict[str, Any]]:
    root = _bundle_workspace_root(project_root)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.glob("*/transactions/*/transaction.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("format") == TX_FORMAT and data.get("state") == "APPLIED_VERIFIED":
            rows.append({"path": str(path.resolve()), "bundle_id": data.get("bundle_id"), "build_manifest": data.get("build_manifest")})
    rows.sort(key=lambda x: x["path"] or "")
    return rows


def _validate_contract_path(row: dict[str, Any]) -> dict[str, Any]:
    side = str(row.get("target_side") or "").upper()
    rel = _safe_rel(str(row.get("logical_output") or ""))
    kind = str(row.get("kind") or "")
    cid = str(row.get("contract_id") or "").strip()
    if side not in {"CLIENT", "SERVER"}:
        raise ValueError(f"BUNDLE_DEPLOY_SIDE_INVALID:{side}")
    if cid:
        contract = get_contract(cid).public()
        runtime = {x.strip().upper() for x in str(contract.get("runtime") or "").split(";") if x.strip()}
        if side not in runtime:
            raise ValueError(f"BUNDLE_DEPLOY_CONTRACT_SIDE_MISMATCH:{cid}:{side}")
        capability = str(contract.get("capability") or "")
        if capability in _BLOCKED_SOURCE_CAPABILITIES or "OPERATIONAL" in capability or "SECURITY" in capability:
            raise ValueError(f"BUNDLE_DEPLOY_OPERATIONAL_CONTRACT_BLOCKED:{cid}:{capability}")
        candidates = match_contracts_for_path(rel.as_posix())
        exact_ids = {
            str(x.get("contract", {}).get("id") or "")
            for x in candidates if str(x.get("match") or "") == "EXACT_PATH_CONVENTION"
        }
        writer = row.get("writer") if isinstance(row.get("writer"), dict) else {}
        if cid not in exact_ids:
            binding = row.get("binding_evidence") if isinstance(row.get("binding_evidence"), dict) else {}
            role = str(binding.get("role") or "")
            graph_ok = (
                cid in _BUNDLE_GRAPH_CONTRACTS
                and binding.get("status") == "SOURCE_GRAPH_BOUND"
                and binding.get("graph") in {"MODEL_VISUAL_CLOSURE", "FIELD_STAGE_CLOSURE"}
                and ((role in {"stage_file", "stage_texture"} and binding.get("graph") == "FIELD_STAGE_CLOSURE") or (role not in {"stage_file", "stage_texture"} and binding.get("graph") == "MODEL_VISUAL_CLOSURE"))
                and str(binding.get("contract_id") or "") == cid
                and str(binding.get("path") or "").replace("\\", "/").strip("/").casefold() == rel.as_posix().casefold()
                and role in _BUNDLE_GRAPH_ROLES.get(cid, set())
            )
            if not graph_ok:
                raise ValueError(f"BUNDLE_DEPLOY_PATH_CONTRACT_NOT_SOURCE_EXACT_OR_GRAPH_BOUND:{cid}:{rel.as_posix()}")
            if cid in {"model.smd.062", "model.smb.bone", "stage.smd.072", "texture.standard"}:
                if writer.get("writer") != "VERIFIED_ARTIFACT_IMPORT" or writer.get("source_artifact_verified") is not True:
                    raise ValueError(f"BUNDLE_DEPLOY_ARTIFACT_NOT_STRUCTURALLY_VERIFIED:{cid}:{rel.as_posix()}")
                structural = writer.get("structural_validation") if isinstance(writer.get("structural_validation"), dict) else {}
                if structural.get("status") != "PASS":
                    raise ValueError(f"BUNDLE_DEPLOY_ARTIFACT_STRUCTURAL_VALIDATION_NOT_PASS:{cid}:{rel.as_posix()}")
            elif cid == "model.config.ini" and writer.get("writer") != "MODEL_CONFIG_SOURCE_EXACT":
                raise ValueError("BUNDLE_DEPLOY_MODEL_CONFIG_NOT_SOURCE_COMPILED")
            elif cid == "model.cache.inx" and writer.get("writer") != "MODEL_CACHE_INX_SOURCE_NATIVE":
                raise ValueError("BUNDLE_DEPLOY_MODEL_CACHE_NOT_SOURCE_COMPILED")
        if cid == "item.definition.txt" and writer.get("code_identity_status") != "SOURCE_VERIFIED":
            raise ValueError("BUNDLE_DEPLOY_ITEM_CODE_NOT_SOURCE_VERIFIED")
    else:
        if kind not in _ALLOWED_PATCH_KINDS or side != "SERVER":
            raise ValueError(f"BUNDLE_DEPLOY_UNTYPED_ASSET_BLOCKED:{kind}:{side}")
        if kind == "SPM_ADD_ACTOR" and rel.suffix.casefold() != ".spm":
            raise ValueError("BUNDLE_DEPLOY_SPM_PATCH_SUFFIX_INVALID")
        if kind == "SPC_ADD_NPC" and rel.suffix.casefold() != ".spc":
            raise ValueError("BUNDLE_DEPLOY_SPC_PATCH_SUFFIX_INVALID")
        if kind == "LEGACY_TEXT_PATCH" and rel.suffix.casefold() not in {".txt", ".inf", ".npc"}:
            raise ValueError("BUNDLE_DEPLOY_LEGACY_TEXT_PATCH_SUFFIX_INVALID")
        if kind == "LEGACY_SPM_PATCH" and rel.suffix.casefold() != ".spm":
            raise ValueError("BUNDLE_DEPLOY_LEGACY_SPM_PATCH_SUFFIX_INVALID")
        if kind == "LEGACY_SPP_PATCH" and rel.suffix.casefold() != ".spp":
            raise ValueError("BUNDLE_DEPLOY_LEGACY_SPP_PATCH_SUFFIX_INVALID")
        if kind == "LEGACY_SPC_PATCH" and rel.suffix.casefold() != ".spc":
            raise ValueError("BUNDLE_DEPLOY_LEGACY_SPC_PATCH_SUFFIX_INVALID")
        contract = None
    if side == "SERVER":
        cls = classify_server_path(rel.as_posix())
        if cls.write_policy in _BLOCKED_SERVER_POLICIES:
            raise ValueError(f"BUNDLE_DEPLOY_SERVER_PATH_BLOCKED:{rel.as_posix()}:{cls.write_policy}")
    return {"contract_id": cid or None, "path": rel.as_posix(), "side": side, "kind": kind}


def _preflight(
    manifest_path: pathlib.Path,
    manifest: dict[str, Any],
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
) -> list[dict[str, Any]]:
    overlay_root = pathlib.Path(str(manifest["overlay_root"])).resolve()
    files = manifest.get("assets") or []
    if not isinstance(files, list) or not files:
        raise ValueError("ASSET_BUNDLE_HAS_NO_FILES")
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("ASSET_BUNDLE_FILE_ROW_INVALID")
        typed = _validate_contract_path(row)
        side = typed["side"]
        rel = _safe_rel(typed["path"])
        key = (side, rel.as_posix().casefold())
        if key in seen:
            raise ValueError(f"ASSET_BUNDLE_DUPLICATE_TARGET:{side}:{rel.as_posix()}")
        seen.add(key)
        staged = pathlib.Path(str(row.get("output") or "")).resolve()
        if not staged.is_file():
            raise FileNotFoundError(f"ASSET_BUNDLE_STAGED_FILE_NOT_FOUND:{staged}")
        try:
            staged.relative_to(overlay_root)
        except Exception as exc:
            raise ValueError(f"ASSET_BUNDLE_STAGED_OUTSIDE_OVERLAY:{staged}") from exc
        staged_sha = _sha256_file(staged)
        if staged_sha != str(row.get("sha256") or ""):
            raise ValueError(f"ASSET_BUNDLE_STAGED_DRIFT:{side}:{rel.as_posix()}")
        root = client_root if side == "CLIENT" else server_root
        if root is None or not pathlib.Path(root).is_dir():
            raise ValueError(f"ASSET_BUNDLE_TARGET_ROOT_REQUIRED:{side}")
        target = _target_path(pathlib.Path(root), rel)
        evidence = row.get("target_evidence") if isinstance(row.get("target_evidence"), dict) else {}
        policy = str(evidence.get("policy") or "").upper()
        if policy not in {"CREATE_NEW", "REPLACE_EXISTING", "PATCH_EXISTING"}:
            raise ValueError(f"ASSET_BUNDLE_TARGET_POLICY_INVALID:{policy}:{rel.as_posix()}")
        expected_sha = str(evidence.get("sha256") or "") or None
        exists = target.is_file()
        actual_sha = _sha256_file(target) if exists else None
        if policy == "CREATE_NEW" and exists:
            raise ValueError(f"ASSET_BUNDLE_CREATE_TARGET_NOW_EXISTS:{side}:{rel.as_posix()}")
        if policy in {"REPLACE_EXISTING", "PATCH_EXISTING"}:
            if not exists:
                raise ValueError(f"ASSET_BUNDLE_EXPECTED_TARGET_MISSING:{side}:{rel.as_posix()}")
            if not expected_sha or actual_sha != expected_sha:
                raise ValueError(f"ASSET_BUNDLE_TARGET_DRIFT:{side}:{rel.as_posix()}")
        out.append({
            "side": side,
            "path": rel.as_posix(),
            "kind": typed["kind"],
            "contract_id": typed["contract_id"],
            "policy": policy,
            "staged": str(staged),
            "staged_sha256": staged_sha,
            "target": str(target),
            "target_existed": exists,
            "original_sha256": actual_sha,
        })
    return out


def publish_asset_bundle(
    project_root: pathlib.Path | str,
    client_root: pathlib.Path | str,
    server_root: pathlib.Path | str | None,
    manifest: pathlib.Path | str,
    *,
    confirm: str,
) -> dict[str, Any]:
    if confirm != APPLY_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{APPLY_CONFIRM}")
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    manifest_path, data = _load_manifest(manifest)
    _assert_project_manifest(project_root, manifest_path)
    active = _active_transactions(project_root)
    if active:
        raise ValueError(f"ASSET_BUNDLE_ACTIVE_TRANSACTION_RESTORE_FIRST:{len(active)}")
    files = _preflight(manifest_path, data, client_root, server)
    tx_root = manifest_path.parent / "transactions" / (time.strftime("%Y%m%d_%H%M%S") + "_" + hashlib.sha1(os.urandom(16)).hexdigest()[:8])
    backup_root = tx_root / "backup"
    tx_root.mkdir(parents=True, exist_ok=True)
    applied: list[dict[str, Any]] = []
    try:
        for row in files:
            target = pathlib.Path(row["target"])
            if row["target_existed"]:
                backup = backup_root / row["side"].lower() / pathlib.PurePosixPath(row["path"])
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                row["backup"] = str(backup)
                row["backup_sha256"] = _sha256_file(backup)
                if row["backup_sha256"] != row["original_sha256"]:
                    raise RuntimeError(f"ASSET_BUNDLE_BACKUP_VERIFY_FAILED:{row['path']}")
            else:
                row["backup"] = None
                row["backup_sha256"] = None
            _atomic_copy(pathlib.Path(row["staged"]), target)
            deployed = _sha256_file(target)
            if deployed != row["staged_sha256"]:
                raise RuntimeError(f"ASSET_BUNDLE_POST_WRITE_HASH_MISMATCH:{row['path']}")
            row["deployed_sha256"] = deployed
            applied.append(row)
    except Exception:
        for row in reversed(applied):
            target = pathlib.Path(row["target"])
            if row.get("backup"):
                _atomic_copy(pathlib.Path(row["backup"]), target)
            elif target.exists():
                target.unlink()
        raise
    tx = {
        "format": TX_FORMAT,
        "state": "APPLIED_VERIFIED",
        "bundle_id": data.get("bundle_id"),
        "bundle_type": data.get("bundle_type"),
        "build_manifest": str(manifest_path),
        "files": files,
        "file_count": len(files),
        "created_at": time.time(),
        "client_modified": any(x["side"] == "CLIENT" for x in files),
        "server_modified": any(x["side"] == "SERVER" for x in files),
        "runtime_review_required": True,
        "production_authorized": False,
    }
    tx_path = tx_root / "transaction.json"
    tx["transaction_manifest"] = str(tx_path)
    tx_path.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (manifest_path.parent / "latest_transaction.txt").write_text(str(tx_path) + "\n", encoding="utf-8")
    return tx


def _latest_transaction_for_manifest(manifest: pathlib.Path | str) -> tuple[pathlib.Path, dict[str, Any]]:
    manifest_path, _ = _load_manifest(manifest)
    marker = manifest_path.parent / "latest_transaction.txt"
    if not marker.is_file():
        raise FileNotFoundError("ASSET_BUNDLE_TRANSACTION_NOT_FOUND")
    tx_path = pathlib.Path(marker.read_text(encoding="utf-8").strip()).resolve()
    if not tx_path.is_file():
        raise FileNotFoundError(f"ASSET_BUNDLE_TRANSACTION_NOT_FOUND:{tx_path}")
    tx = json.loads(tx_path.read_text(encoding="utf-8"))
    if not isinstance(tx, dict) or tx.get("format") != TX_FORMAT:
        raise ValueError("ASSET_BUNDLE_TRANSACTION_INVALID")
    return tx_path, tx


def restore_asset_bundle(
    project_root: pathlib.Path | str,
    client_root: pathlib.Path | str,
    server_root: pathlib.Path | str | None,
    manifest: pathlib.Path | str,
    *,
    confirm: str,
) -> dict[str, Any]:
    if confirm != RESTORE_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{RESTORE_CONFIRM}")
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    manifest_path, _manifest_data = _load_manifest(manifest)
    _assert_project_manifest(project_root, manifest_path)
    tx_path, tx = _latest_transaction_for_manifest(manifest_path)
    if tx.get("state") != "APPLIED_VERIFIED":
        raise ValueError(f"ASSET_BUNDLE_TRANSACTION_NOT_ACTIVE:{tx.get('state')}")
    files = list(tx.get("files") or [])
    # All drift checks happen before the first restore write.
    for row in files:
        root = client_root if row.get("side") == "CLIENT" else server
        if root is None:
            raise ValueError("ASSET_BUNDLE_SERVER_ROOT_REQUIRED_FOR_RESTORE")
        target = _target_path(pathlib.Path(root), _safe_rel(str(row.get("path") or "")))
        if not target.is_file():
            raise ValueError(f"ASSET_BUNDLE_RESTORE_TARGET_MISSING:{row.get('path')}")
        if _sha256_file(target) != row.get("deployed_sha256"):
            raise ValueError(f"ASSET_BUNDLE_RESTORE_DRIFT:{row.get('path')}")
        if row.get("backup"):
            backup = pathlib.Path(str(row["backup"])).resolve()
            if not backup.is_file() or _sha256_file(backup) != row.get("backup_sha256"):
                raise ValueError(f"ASSET_BUNDLE_RESTORE_BACKUP_INVALID:{row.get('path')}")
    for row in reversed(files):
        root = client_root if row.get("side") == "CLIENT" else server
        assert root is not None
        target = _target_path(pathlib.Path(root), _safe_rel(str(row.get("path") or "")))
        if row.get("backup"):
            _atomic_copy(pathlib.Path(str(row["backup"])), target)
            if _sha256_file(target) != row.get("original_sha256"):
                raise RuntimeError(f"ASSET_BUNDLE_RESTORE_VERIFY_FAILED:{row.get('path')}")
        else:
            target.unlink()
    tx["state"] = "RESTORED_VERIFIED"
    tx["restored_at"] = time.time()
    tx_path.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tx


def asset_bundle_deploy_status(project_root: pathlib.Path | str) -> dict[str, Any]:
    manifest = latest_bundle_manifest(project_root)
    if manifest is None:
        return {"format": TX_FORMAT, "status": "NO_BUNDLE", "latest_manifest": None, "latest_transaction": None}
    tx = None
    try:
        _txp, tx = _latest_transaction_for_manifest(manifest)
    except Exception:
        tx = None
    active = _active_transactions(project_root)
    return {
        "format": TX_FORMAT,
        "status": "READY",
        "latest_manifest": str(manifest),
        "latest_transaction": tx,
        "active_transaction_count": len(active),
        "active_transactions": active,
        "can_publish": (not active) and (not tx or tx.get("state") == "RESTORED_VERIFIED"),
        "can_restore": bool(tx and tx.get("state") == "APPLIED_VERIFIED"),
    }
