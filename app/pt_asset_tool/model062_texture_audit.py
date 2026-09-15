from __future__ import annotations

import pathlib
from collections import Counter
from typing import Any

from .release_1_coverage import CONTENT_DOMAINS, content_domain
from .texture_overlay import _face_texture_scope
from .utils import norm_path

FORMAT = "PT_MODEL062_TEXTURE_REFERENCE_CORPUS_AUDIT_V1"


def _resolve_required_texture(asset, resolver, logical: str) -> tuple[str, str | None]:
    """Resolve one serialized texture reference using only explicit runtime aliases.

    No basename/global guessing is allowed.  The only fallback accepted here is
    the runtime-path alias already recorded on the canonical asset record.
    """
    logical_n = norm_path(logical)
    try:
        path = pathlib.Path(resolver.resolve(logical_n, required=True)).resolve()
        return str(path), None
    except Exception as exact_exc:
        aliases = dict(getattr(asset, "runtime_path_aliases", {}) or {})
        alias = norm_path(aliases.get(logical_n) or "")
        if not alias:
            raise RuntimeError(f"missing texture {logical_n}: {type(exact_exc).__name__}: {exact_exc}")
        try:
            path = pathlib.Path(resolver.resolve(alias, required=True)).resolve()
            return str(path), alias
        except Exception as alias_exc:
            raise RuntimeError(
                f"missing texture {logical_n}; alias {alias}: "
                f"exact={type(exact_exc).__name__}: {exact_exc}; "
                f"alias={type(alias_exc).__name__}: {alias_exc}"
            )


def audit_model062_texture_presence(project_root, registry, resolver, *, sample_limit: int = 100) -> dict[str, Any]:
    # FIX24_RELEASE_CAPABILITY_TARGET_SEPARATION
    """Corpus-wide physical reference audit for face-used Model0.62 textures.

    This complements the proprietary codec gate.  Codec tests prove that BMP/TGA
    bytes can be decoded/edited/rebuilt; this audit proves that every texture
    actually required by a face-used Model0.62 material resolves physically.
    Serialized textures from unused historical material slots are diagnostics,
    not readiness blockers, matching the authoring overlay semantics.
    """
    root = pathlib.Path(project_root).resolve()
    by_domain: dict[str, Counter] = {d: Counter() for d in CONTENT_DOMAINS}
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for asset in registry.assets:
        if str(getattr(asset, "kind", "")) != "SMD_MODEL_062":
            continue
        domain = content_domain(asset)
        if domain not in by_domain:
            continue
        by_domain[domain]["MODEL062_ASSET_COUNT"] += 1
        try:
            scope = _face_texture_scope(asset=asset, resolver=resolver, root=root)
            if scope.get("semantics") != "FACE_REFERENCED_MATERIALS":
                raise RuntimeError(
                    "face-referenced material texture scope could not be proven: "
                    + str(scope.get("error") or "UNKNOWN")
                )
            required = [norm_path(x) for x in (scope.get("required_names") or []) if norm_path(x)]
            if required:
                by_domain[domain]["ASSETS_WITH_REQUIRED_TEXTURES"] += 1
            by_domain[domain]["REQUIRED_TEXTURE_REFERENCE_COUNT"] += len(required)
            resolved_rows = []
            missing_rows = []
            for logical in required:
                try:
                    physical, alias = _resolve_required_texture(asset, resolver, logical)
                    resolved_rows.append({"logical": logical, "physical": physical, "runtime_alias": alias})
                    by_domain[domain]["RESOLVED_TEXTURE_REFERENCE_COUNT"] += 1
                    if alias:
                        by_domain[domain]["RUNTIME_ALIAS_REFERENCE_COUNT"] += 1
                except Exception as exc:
                    missing_rows.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})
                    by_domain[domain]["MISSING_TEXTURE_REFERENCE_COUNT"] += 1
            row = {
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "domain": domain,
                "status": "PASS" if not missing_rows else "FAIL",
                "used_material_ids": list(scope.get("used_material_ids") or []),
                "required_texture_count": len(required),
                "resolved_texture_count": len(resolved_rows),
                "missing_texture_count": len(missing_rows),
                "resolved": resolved_rows,
                "missing": missing_rows,
            }
            rows.append(row)
            if missing_rows:
                failures.append(row)
        except Exception as exc:
            by_domain[domain]["SCOPE_FAILURE_COUNT"] += 1
            row = {
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "domain": domain,
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
            rows.append(row)
            failures.append(row)

    domain_summary: dict[str, Any] = {}
    pass_domains: list[str] = []
    for domain in CONTENT_DOMAINS:
        c = by_domain[domain]
        required = int(c.get("REQUIRED_TEXTURE_REFERENCE_COUNT") or 0)
        missing = int(c.get("MISSING_TEXTURE_REFERENCE_COUNT") or 0)
        scope_fail = int(c.get("SCOPE_FAILURE_COUNT") or 0)
        assets_with = int(c.get("ASSETS_WITH_REQUIRED_TEXTURES") or 0)
        if assets_with == 0:
            status = "NOT_PRESENT"
        else:
            status = "PASS" if missing == 0 and scope_fail == 0 else "FAIL"
        audit_status = "NOT_PRESENT" if assets_with == 0 else ("PASS" if scope_fail == 0 else "FAIL")
        target_content_status = "NOT_PRESENT" if assets_with == 0 else ("PASS" if missing == 0 and scope_fail == 0 else "FAIL")
        domain_summary[domain] = {
            **dict(sorted(c.items())),
            "status": status,
            "audit_status": audit_status,
            "target_content_status": target_content_status,
        }
        if status == "PASS":
            pass_domains.append(domain)

    total_required = sum(int(x.get("required_texture_count") or 0) for x in rows)
    total_scope_failures = sum(int((domain_summary.get(d) or {}).get("SCOPE_FAILURE_COUNT") or 0) for d in CONTENT_DOMAINS)
    audit_complete_domains = sorted(
        d for d in CONTENT_DOMAINS
        if str((domain_summary.get(d) or {}).get("audit_status") or "") == "PASS"
    )
    result = {
        "format": FORMAT,
        "status": "PASS" if rows and not failures else ("EMPTY" if not rows else "FAIL"),
        "audit_status": "PASS" if rows and total_scope_failures == 0 else ("EMPTY" if not rows else "FAIL"),
        "target_content_status": "PASS" if rows and not failures else ("EMPTY" if not rows else "FAIL"),
        "model062_asset_count": len(rows),
        "required_texture_reference_count": total_required,
        "failure_count": len(failures),
        "pass_domains": sorted(pass_domains),
        "audit_complete_domains": audit_complete_domains,
        "by_domain": domain_summary,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "rows": rows,
        "policy": {
            "face_referenced_materials_only": True,
            "unused_serialized_material_textures_do_not_block": True,
            "runtime_alias_must_be_explicit_in_registry": True,
            "basename_or_global_texture_guessing": False,
            "client_write_authorized": False,
            "production_authorized": False,
            "tool_capability_vs_target_content_separated": True,
        },
        "client_modified": False,
    }
    return result
