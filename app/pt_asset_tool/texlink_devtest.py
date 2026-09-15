from __future__ import annotations

import json
import pathlib
from typing import Any

from .multilayer_texlink import parse_multilayer_semantics
from .validation import ValidationContext, ValidationRunner
from .release_1_coverage import content_domain

FORMAT = "PT_MULTILAYER_TEXLINK_AUTOMATED_DEVTEST_BATCH_V1"


def choose_multilayer_representatives(registry, resolver, *, limit: int = 4, domain: str | None = None) -> list[dict[str, Any]]:
    rows=[]
    for asset in registry.assets:
        if asset.family not in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"}:
            continue
        asset_domain = content_domain(asset)
        if domain is not None and asset_domain != str(domain):
            continue
        source=resolver.resolve(asset.primary_path, required=False)
        if source is None:
            continue
        try:
            sem=parse_multilayer_semantics(pathlib.Path(source))
        except Exception:
            continue
        if sem.get("source_semantics") != "PASS" or int(sem.get("max_layers") or 0) != 2 or int(sem.get("multilayer_faces") or 0) < 1:
            continue
        # Prefer STATIC because it has no model-info ambiguity; keep rigid rows as
        # fallback/coverage once the static family is represented.
        features={"FAMILY_" + ("STATIC" if asset.family=="SMD_MODEL_062_STATIC" else "RIGID")}
        ml=int(sem.get("multilayer_faces") or 0); total=int(sem.get("total_faces") or 0)
        features.add("FULL_FACE_MULTILAYER" if ml==total else "PARTIAL_FACE_MULTILAYER")
        if int(sem.get("uv_distinct_multilayer_faces") or 0)>0:
            features.add("DISTINCT_UV_STAGE")
        rows.append({
            "asset": asset.primary_path, "family": asset.family, "domain": asset_domain,
            "multilayer_faces": ml, "total_faces": total,
            "distinct_uv_faces": int(sem.get("uv_distinct_multilayer_faces") or 0),
            "coverage_features": sorted(features),
        })
    all_features=set().union(*(set(r["coverage_features"]) for r in rows)) if rows else set()
    rows.sort(key=lambda r: (-len(r["coverage_features"]), -r["multilayer_faces"], r["asset"].casefold()))
    out=[]; covered=set(); remaining=list(rows)
    while all_features-covered and remaining:
        row=max(remaining,key=lambda r:(len(set(r["coverage_features"])-covered),len(r["coverage_features"]),r["multilayer_faces"],r["asset"].casefold()))
        if not (set(row["coverage_features"])-covered): break
        out.append(row); covered.update(row["coverage_features"]); remaining.remove(row)
    target=max(int(limit),len(out))
    for row in rows:
        if row not in out: out.append(row)
        if len(out)>=target: break
    return out


def run_multilayer_texlink_automated_devtest_batch(settings, registry, resolver, certifications, rows: list[dict[str, Any]], *, uv_delta: float = 0.03125) -> dict[str, Any]:
    runner=ValidationRunner(ValidationContext(settings,resolver,certifications))
    results=[]; failures=[]
    for row in rows:
        try:
            asset=registry.resolve(row["asset"])
            result=runner.multilayer_texlink_roundtrip(asset, lod="auto", uv_delta=float(uv_delta))
            results.append({
                "asset": asset.primary_path, "family": asset.family, "status": result.get("status", result.get("overall", "PASS")),
                "mode": result.get("mode"), "lod": result.get("lod"), "rebuilt_smd": result.get("rebuilt_smd"),
                "texlink_structure_exact": result.get("texlink_structure_exact"),
                "htexture_nexttex_byte_identical": result.get("htexture_nexttex_byte_identical"),
                "non_witness_bytes_byte_identical": result.get("non_witness_bytes_byte_identical"),
                "client_modified": False,
            })
        except Exception as exc:
            failures.append({"asset": row.get("asset"), "family": row.get("family"), "error": f"{type(exc).__name__}: {exc}"})
    result={
        "format":FORMAT,"status":"PASS" if results and not failures else ("EMPTY" if not rows else "FAIL"),
        "requested":len(rows),"passed_assets":[x["asset"] for x in results],"failed_assets":failures,"results":results,
        "automatic_only":True,"runtime_authorized":False,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
    out=pathlib.Path(settings.project_root).resolve()/"pt_build"/"devtest"/"texlink_auto"/"batch_result.json"
    out.parent.mkdir(parents=True,exist_ok=True); result["report"]=str(out)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result
