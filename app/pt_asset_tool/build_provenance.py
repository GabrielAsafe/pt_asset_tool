from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

FORMAT = "PT_ASSET_BUILD_PROVENANCE_V1"


def sha256_file(path: pathlib.Path | str) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def provenance_path(artifact: pathlib.Path | str) -> pathlib.Path:
    p = pathlib.Path(artifact).resolve()
    return p.with_suffix(p.suffix + ".build.json")


def write_build_provenance(
    artifact: pathlib.Path | str,
    *,
    asset,
    source: pathlib.Path | str,
    build_mode: str,
    adapter: str,
    build_status: str,
    production_authorized: bool,
    evidence: dict[str, Any] | None = None,
    selected_context: dict[str, Any] | None = None,
) -> pathlib.Path:
    artifact = pathlib.Path(artifact).resolve()
    source = pathlib.Path(source).resolve()
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if not source.is_file():
        raise FileNotFoundError(source)
    if selected_context is not None:
        from .authoring import verify_selected_authoring_context
        context_verify = verify_selected_authoring_context(selected_context)
        if context_verify.get("status") != "PASS":
            raise RuntimeError(f"cannot write build provenance with invalid selected context: {context_verify.get('errors')}")
    payload = {
        "format": FORMAT,
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "family": asset.family,
        "kind": asset.kind,
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "size": source.stat().st_size,
        },
        "artifact": {
            "path": str(artifact),
            "sha256": sha256_file(artifact),
            "size": artifact.stat().st_size,
        },
        "build_mode": str(build_mode),
        "adapter": str(adapter),
        "build_status": str(build_status),
        "production_authorized": bool(production_authorized),
        "client_write_authorized": False,
        "selected_context": dict(selected_context) if selected_context is not None else None,
        "evidence": dict(evidence or {}),
        "client_modified": False,
    }
    out = provenance_path(artifact)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def verify_build_provenance(
    artifact: pathlib.Path | str,
    *,
    expected_asset_id: str | None = None,
    expected_asset_path: str | None = None,
    expected_source: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    artifact = pathlib.Path(artifact).resolve()
    prov = provenance_path(artifact)
    errors: list[str] = []
    if not prov.is_file():
        return {
            "format": "PT_ASSET_BUILD_PROVENANCE_VERIFY_V1",
            "status": "FAIL",
            "artifact": str(artifact),
            "provenance": str(prov),
            "errors": ["BUILD_PROVENANCE_MISSING"],
            "production_authorized": False,
            "client_write_authorized": False,
        }
    try:
        data = json.loads(prov.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "format": "PT_ASSET_BUILD_PROVENANCE_VERIFY_V1",
            "status": "FAIL",
            "artifact": str(artifact),
            "provenance": str(prov),
            "errors": [f"BUILD_PROVENANCE_PARSE:{type(exc).__name__}"],
            "production_authorized": False,
            "client_write_authorized": False,
        }
    if data.get("format") != FORMAT:
        errors.append("BUILD_PROVENANCE_FORMAT")
    if not artifact.is_file():
        errors.append("ARTIFACT_MISSING")
    else:
        row = data.get("artifact") or {}
        if int(row.get("size") or -1) != artifact.stat().st_size:
            errors.append("ARTIFACT_SIZE_DRIFT")
        if str(row.get("sha256") or "").lower() != sha256_file(artifact).lower():
            errors.append("ARTIFACT_SHA_DRIFT")
    if expected_asset_id and str(data.get("asset_id")) != str(expected_asset_id):
        errors.append("ASSET_ID_MISMATCH")
    if expected_asset_path and str(data.get("asset", "")).replace("\\", "/").casefold() != str(expected_asset_path).replace("\\", "/").casefold():
        errors.append("ASSET_PATH_MISMATCH")
    selected_context = data.get("selected_context")
    selected_context_verification = None
    if selected_context is not None:
        from .authoring import verify_selected_authoring_context
        selected_context_verification = verify_selected_authoring_context(selected_context)
        if selected_context_verification.get("status") != "PASS":
            errors.append("SELECTED_CONTEXT_DRIFT")
    elif (
        data.get("family") in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}
        and str(data.get("build_mode") or "") in {"CANDIDATE_RIGID", "CANDIDATE_RIGID_STRESS", "CANDIDATE_MIXED"}
    ):
        errors.append("SELECTED_CONTEXT_MISSING")

    source_row = data.get("source") or {}
    if expected_source is not None:
        source = pathlib.Path(expected_source).resolve()
        if not source.is_file():
            errors.append("SOURCE_MISSING")
        else:
            if int(source_row.get("size") or -1) != source.stat().st_size:
                errors.append("SOURCE_SIZE_DRIFT")
            if str(source_row.get("sha256") or "").lower() != sha256_file(source).lower():
                errors.append("SOURCE_SHA_DRIFT")
    production = bool(data.get("production_authorized")) and not errors and str(data.get("build_status")) == "PASS"
    return {
        "format": "PT_ASSET_BUILD_PROVENANCE_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "artifact": str(artifact),
        "provenance": str(prov),
        "asset_id": data.get("asset_id"),
        "asset": data.get("asset"),
        "build_mode": data.get("build_mode"),
        "adapter": data.get("adapter"),
        "build_status": data.get("build_status"),
        "selected_context": selected_context,
        "selected_context_verification": selected_context_verification,
        "errors": errors,
        "production_authorized": production,
        "client_write_authorized": False,
    }
