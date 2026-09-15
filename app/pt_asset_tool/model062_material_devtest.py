from __future__ import annotations

import json
import pathlib
from typing import Any

from .blender_workspace import asset_workspace_name
from .model062_material_writer import locate_materials, rebuild_material_fields, verify_material_candidate
from .release_1_coverage import CONTENT_DOMAINS, content_domain

FORMAT = "PT_MODEL062_MATERIAL_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_MODEL062_MATERIAL_AUTOMATED_DEVTEST_BATCH_V1"
MODEL062_FAMILIES = {
    "SMD_MODEL_062_RIGID_PHYSIQUE",
    "SMD_MODEL_062_STATIC",
    "SMD_MODEL_062_MIXED_PHYSIQUE",
}


def choose_model062_material_representatives(registry, domain: str, *, limit: int = 2) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in registry.assets:
        if content_domain(asset) != domain or str(asset.family or "") not in MODEL062_FAMILIES:
            continue
        if int(getattr(asset, "material_count", 0) or 0) <= 0:
            continue
        rows.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "domain": domain,
            "family": asset.family,
            "material_count": int(asset.material_count or 0),
            "object_count": int(asset.object_count or 0),
            "size": int(asset.size or 0),
        })
    if not rows or int(limit) <= 0:
        return []
    # A Release 1.0 domain can contain more than one physical Model0.62 family
    # (notably rigid + static).  A material writer witness from one family must
    # never paint the other family green merely because their material structs
    # look similar.  Cover every present family first, then spend any remaining
    # budget on layout-complexity extremes.  The requested limit is therefore a
    # minimum budget; family coverage is mandatory even if a future real Mixed
    # sample makes the domain require three representatives.
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_family.setdefault(str(row["family"]), []).append(row)
    for family_rows in by_family.values():
        family_rows.sort(key=lambda r: (-r["material_count"], -r["object_count"], -r["size"], r["asset"].casefold()))

    target = max(int(limit), len(by_family))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family in sorted(by_family):
        row = by_family[family][0]
        out.append(row); seen.add(str(row["asset_id"]))

    # Fill with globally simple/complex layouts after family diversity is
    # guaranteed. This catches fixed-layout edge cases without sacrificing the
    # family x domain contract.
    ordered = sorted(rows, key=lambda r: (r["material_count"], r["object_count"], r["size"], r["asset"].casefold()))
    fill_order = []
    if ordered:
        fill_order.extend((ordered[0], ordered[-1]))
    fill_order.extend(reversed(ordered))
    for row in fill_order:
        aid = str(row["asset_id"])
        if aid in seen:
            continue
        out.append(row); seen.add(aid)
        if len(out) >= target:
            break
    return out[:target]


def run_model062_material_automated_devtest(settings, registry, resolver, row: dict[str, Any]) -> dict[str, Any]:
    root = pathlib.Path(settings.project_root).resolve()
    asset = registry.resolve(row["asset"])
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    before = source.read_bytes()
    layout = locate_materials(before)
    if int(layout.get("material_count") or 0) <= 0:
        raise RuntimeError(f"material devtest representative has no Model0.62 materials: {asset.primary_path}")
    materials = list(layout.get("materials") or [])
    # Prefer an in-use material; fall back to the first structurally present row.
    material = next((m for m in materials if m.get("in_use")), materials[0])
    index = int(material["index"])
    old_two_side = int((material.get("values") or {}).get("two_side") or 0)
    new_two_side = 0 if old_two_side == 1 else 1
    edits = {"two_side": new_two_side}
    rebuilt, writer_report = rebuild_material_fields(before, material_index=index, edits=edits)

    work = root / "pt_build" / "devtest" / "release_1_auto" / "materials" / asset_workspace_name(asset.primary_path)
    work.mkdir(parents=True, exist_ok=True)
    artifact = work / pathlib.PurePosixPath(asset.primary_path).name
    artifact.write_bytes(rebuilt)
    verification = verify_material_candidate(before, rebuilt, material_index=index, edits=edits)
    status = "PASS" if writer_report.get("status") == "PASS" and verification.get("status") == "PASS" else "FAIL"
    result = {
        "format": FORMAT,
        "status": status,
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "domain": content_domain(asset),
        "family": asset.family,
        "source": str(source),
        "artifact": str(artifact),
        "material_index": index,
        "edit": {"field": "two_side", "before": old_two_side, "after": new_two_side},
        "writer": writer_report,
        "verification": verification,
        "candidate_only": True,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    report = work / "result.json"
    result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_model062_material_automated_devtest_batch(settings, registry, resolver, rows: list[dict[str, Any]]) -> dict[str, Any]:
    results=[]; failed=[]; passed=[]
    for row in rows:
        try:
            result = run_model062_material_automated_devtest(settings, registry, resolver, row)
        except Exception as exc:
            result = {
                "format": FORMAT, "status": "FAIL", "asset": row.get("asset"), "domain": row.get("domain"),
                "errors": [f"{type(exc).__name__}: {exc}"], "production_authorized": False,
                "client_write_authorized": False, "client_modified": False,
            }
        results.append(result)
        if result.get("status") == "PASS": passed.append(str(row.get("asset")))
        else: failed.append({"asset": row.get("asset"), "domain": row.get("domain"), "errors": result.get("errors") or (result.get("verification") or {}).get("errors")})
    status = "PASS" if rows and not failed and len(passed) == len(rows) else ("EMPTY" if not rows else "FAIL")
    root=pathlib.Path(settings.project_root).resolve()
    out=root/"pt_build"/"devtest"/"release_1_auto"/"materials"/"batch_result.json"
    payload={
        "format": BATCH_FORMAT, "status": status, "requested": len(rows),
        "passed_assets": passed, "failed_assets": failed, "results": results,
        "automatic_only": True, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
        "report": str(out),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def choose_all_model062_material_representatives(registry, *, per_domain: int = 2) -> dict[str, list[dict[str, Any]]]:
    return {d: choose_model062_material_representatives(registry, d, limit=per_domain) for d in CONTENT_DOMAINS}

CORPUS_FORMAT = "PT_MODEL062_MATERIAL_PHYSICAL_CORPUS_AUDIT_V1"


def audit_model062_material_physical_corpus(registry, resolver, *, sample_limit: int = 100) -> dict[str, Any]:
    # FIX25_MATERIAL_FAMILY_EVIDENCE: preserve the physical family on every corpus row.
    """Parse the material region of every physical Model0.62 asset with materials.

    Representative devtests prove allowlisted candidate writes.  This corpus
    audit separately proves that the fixed material-region parser closes on all
    shipped Model0.62 material layouts and agrees with inventory material counts.
    """
    from collections import Counter
    by_domain = {d: Counter() for d in CONTENT_DOMAINS}
    failures=[]; rows=[]
    for asset in registry.assets:
        if str(asset.family or "") not in MODEL062_FAMILIES:
            continue
        expected=int(getattr(asset,"material_count",0) or 0)
        if expected <= 0:
            continue
        domain=content_domain(asset)
        if domain not in by_domain:
            continue
        by_domain[domain]["ASSET_COUNT"] += 1
        try:
            source=pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
            layout=locate_materials(source.read_bytes())
            parsed=int(layout.get("material_count") or 0)
            if parsed != expected:
                raise RuntimeError(f"material count mismatch inventory={expected} parsed={parsed}")
            in_use=sum(1 for m in (layout.get("materials") or []) if m.get("in_use"))
            by_domain[domain]["MATERIAL_COUNT"] += parsed
            by_domain[domain]["IN_USE_MATERIAL_COUNT"] += in_use
            rows.append({
                "asset_id":asset.asset_id,"asset":asset.primary_path,"domain":domain,
                "family":str(asset.family or ""),
                "status":"PASS","material_count":parsed,"in_use_material_count":in_use,
            })
        except Exception as exc:
            by_domain[domain]["FAIL_COUNT"] += 1
            row={
                "asset_id":asset.asset_id,"asset":asset.primary_path,"domain":domain,
                "family":str(asset.family or ""),
                "status":"FAIL","error":f"{type(exc).__name__}: {exc}",
            }
            rows.append(row); failures.append(row)
    pass_domains=[]; domain_summary={}
    for d,c in by_domain.items():
        count=int(c.get("ASSET_COUNT") or 0); fail=int(c.get("FAIL_COUNT") or 0)
        st="PASS" if count and not fail else ("NOT_PRESENT" if not count else "FAIL")
        domain_summary[d]={**dict(sorted(c.items())),"status":st}
        if st=="PASS": pass_domains.append(d)
    return {
        "format":CORPUS_FORMAT,
        "status":"PASS" if rows and not failures else ("EMPTY" if not rows else "FAIL"),
        "asset_count":len(rows),"failure_count":len(failures),
        "pass_domains":sorted(pass_domains),"by_domain":domain_summary,
        "failure_sample":failures[:max(0,int(sample_limit))],"rows":rows,
        "policy":{
            "corpus_wide_physical_parse":True,"candidate_writes_are_separate_representative_gate":True,
            "production_authorized":False,"client_write_authorized":False,
        },
        "client_modified":False,
    }
