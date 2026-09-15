from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .object_local import parse_object_local_smd
from .object_local_writer import patch_existing_object_local_key
from .utils import run_logged, sha256_file
from .validation import ValidationContext, ValidationRunner
from .release_1_coverage import content_domain

FORMAT = "PT_OBJECT_LOCAL_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_OBJECT_LOCAL_AUTOMATED_DEVTEST_BATCH_V1"


def _work(root: pathlib.Path, asset_path: str) -> pathlib.Path:
    safe = str(asset_path).replace("\\", "/").strip("/").replace("/", "__")
    return root / "pt_build" / "devtest" / "object_local_auto" / safe


def _candidate_edits(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Choose at most one existing key per channel, including segmented tracks."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obj in parsed.get("objects") or []:
        oi = int(obj["index"])
        if "ROT" not in seen and obj.get("rot_keys"):
            key = obj["rot_keys"][0]
            vals = [float(x) for x in key["q_incremental_xyzw"]]
            vals[0] += 0.001
            rows.append({"object_index": oi, "object_name": obj["name"], "channel": "ROT", "key_index": 0, "values": vals})
            seen.add("ROT")
        if "POS" not in seen and obj.get("pos_keys"):
            key = obj["pos_keys"][0]
            vals = [float(x) for x in key["xyz"]]
            vals[0] += 0.125
            rows.append({"object_index": oi, "object_name": obj["name"], "channel": "POS", "key_index": 0, "values": vals})
            seen.add("POS")
        if "SCALE" not in seen and obj.get("scale_keys"):
            key = obj["scale_keys"][0]
            vals = [float(x) for x in key["xyz"]]
            vals[0] += 1.0 / 256.0
            rows.append({"object_index": oi, "object_name": obj["name"], "channel": "SCALE", "key_index": 0, "values": vals})
            seen.add("SCALE")
        if len(seen) == 3:
            break
    return rows


def run_object_local_automated_devtest(settings, registry, resolver, certifications, *, asset_path: str, fps: int = 30) -> dict[str, Any]:
    asset = registry.resolve(asset_path)
    if asset.family != "SMD_MODEL_062_STATIC":
        raise RuntimeError(f"object-local automated devtest requires static Model0.62, got {asset.family}")
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    source_sha = sha256_file(source)
    parsed = parse_object_local_smd(source, strict_v1=True)
    if int(parsed.get("animated_object_count") or 0) < 1:
        raise RuntimeError("object-local source contains no visible animated object")
    segmented = [o["name"] for o in parsed.get("objects") or [] if int(o.get("TmFrameCnt") or 0)]
    edits = _candidate_edits(parsed)
    if not edits:
        raise RuntimeError("object-local source contains no editable ROT/POS/SCALE key")

    root = pathlib.Path(settings.project_root).resolve()
    work = _work(root, asset.primary_path)
    if work.exists():
        shutil.rmtree(work)
    import_work = work / "01_import"
    writer_work = work / "02_writer"
    bake_work = work / "03_blender_bake"
    for p in (import_work, writer_work, bake_work):
        p.mkdir(parents=True, exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    runner.structural(asset)
    overlay, _texture_report = runner._texture_overlay(asset, import_work)
    _src, pristine, _lod = runner._prepare_static_blend(asset, import_work, overlay)

    writer_rows = []
    for idx, edit in enumerate(edits, start=1):
        out = writer_work / f"{idx:02d}_{edit['channel'].lower()}.smd"
        result = patch_existing_object_local_key(
            source, out,
            object_index=int(edit["object_index"]), channel=edit["channel"],
            key_index=int(edit["key_index"]), values=edit["values"],
            expected_source_sha256=source_sha,
        )
        if result.get("status") != "PASS" or not result.get("all_non_authorized_bytes_byte_identical"):
            raise RuntimeError(f"object-local {edit['channel']} writer gate failed")
        writer_rows.append({
            "channel": edit["channel"], "object_index": edit["object_index"],
            "object_name": edit["object_name"], "changed_byte_count": result.get("changed_byte_count"),
            "tm_prev_rot_rebuilt_from_key": result.get("tm_prev_rot_rebuilt_from_key"),
            "output_sha256": result.get("output_sha256"),
        })
    if sha256_file(source) != source_sha:
        raise RuntimeError("client source drift during object-local automated devtest")

    preview = bake_work / "object_local_preview.blend"
    bake_report = bake_work / "bake_report.json"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "bake_object_local.py"), "--",
        "--smd", str(source), "--out", str(preview), "--report", str(bake_report), "--fps", str(int(fps)),
    ], bake_work / "01_bake.log")
    baked = json.loads(bake_report.read_text(encoding="utf-8"))
    if baked.get("status") != "PASS":
        raise RuntimeError(f"object-local Blender bake failed: {baked}")

    result = {
        "format": FORMAT, "status": "PASS", "asset": asset.primary_path,
        "source_sha256": source_sha,
        "channels_present": sorted({c for o in parsed.get("objects") or [] for c in o.get("channels_animated") or []}),
        "candidate_writer_channels_tested": [r["channel"] for r in writer_rows],
        "writer_results": writer_rows,
        "blender_bake": {
            "status": baked.get("status"), "preview_version": baked.get("preview_version"),
            "animated_object_count": baked.get("animated_object_count"),
            "channels_animated": baked.get("channels_animated"),
            "legacy_affine_object_count": baked.get("legacy_affine_object_count"),
            "zero_scale_spawn_object_count": baked.get("zero_scale_spawn_object_count"),
            "parent_edge_count": baked.get("parent_edge_count"),
            "unresolved_parent_count": baked.get("unresolved_parent_count"),
            "blend": str(preview), "report": str(bake_report),
        },
        "animated_child_count": int(parsed.get("animated_child_count") or 0),
        "unresolved_parent_count": int(parsed.get("unresolved_parent_count") or 0),
        "segmented_tmframe_supported": True,
        "segmented_tmframe_objects": segmented,
        "automatic_only": True, "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    rp = work / "result.json"; result["report"] = str(rp)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def choose_object_local_representatives(registry, resolver, *, limit: int = 4, domain: str | None = None) -> list[dict[str, Any]]:
    candidates=[]
    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_STATIC":
            continue
        asset_domain = content_domain(asset)
        if domain is not None and asset_domain != str(domain):
            continue
        source = resolver.resolve(asset.primary_path, required=False)
        if source is None:
            continue
        try:
            parsed = parse_object_local_smd(source, strict_v1=True)
        except Exception:
            continue
        if int(parsed.get("animated_object_count") or 0) < 1:
            continue
        channels=sorted({
            ("ROT" if str(c) == "ROT_AFFINE" else str(c))
            for o in parsed.get("objects") or []
            for c in (o.get("channels_animated") or [])
        })
        features = set(channels)
        if bool(parsed.get("legacy_affine_object_count")):
            features.add("LEGACY_AFFINE")
        if any(int(o.get("TmFrameCnt") or 0) for o in parsed.get("objects") or []):
            features.add("SEGMENTED_TMFRAME")
        if any(o.get("zero_scale_reference_axes") for o in parsed.get("objects") or []):
            features.add("ZERO_SCALE_SPAWN")
        if int(parsed.get("parent_edge_count") or 0) > 0:
            features.add("HIERARCHICAL")
        if int(parsed.get("unresolved_parent_count") or 0) > 0:
            features.add("UNRESOLVED_PARENT")
        if int(parsed.get("animated_child_count") or 0) > 0:
            features.add("ANIMATED_CHILD")
        candidates.append({
            "asset": asset.primary_path, "domain": asset_domain,
            "channels": channels,
            "legacy_affine": "LEGACY_AFFINE" in features,
            "segmented_tmframe": "SEGMENTED_TMFRAME" in features,
            "zero_scale_spawn": "ZERO_SCALE_SPAWN" in features,
            "hierarchical": "HIERARCHICAL" in features,
            "unresolved_parent": "UNRESOLVED_PARENT" in features,
            "animated_child": "ANIMATED_CHILD" in features,
            "coverage_features": sorted(features),
            "object_count": int(parsed.get("object_count") or 0),
        })
    all_features = set().union(*(set(r["coverage_features"]) for r in candidates)) if candidates else set()
    candidates.sort(key=lambda r: (-len(r["coverage_features"]), -r["object_count"], r["asset"].casefold()))
    out=[]; covered=set()
    # Greedy feature-set cover. `limit` is a preferred sample budget, not a
    # permission to leave a physical subtype untested. If more witnesses are
    # required to cover the domain, return them and let the release runner run
    # all of them.
    remaining=list(candidates)
    while all_features - covered and remaining:
        row=max(remaining, key=lambda r: (len(set(r["coverage_features"]) - covered), len(r["coverage_features"]), r["object_count"], r["asset"].casefold()))
        if not (set(row["coverage_features"]) - covered):
            break
        out.append(row); covered.update(row["coverage_features"]); remaining.remove(row)
    target=max(int(limit), len(out))
    for row in candidates:
        if row not in out:
            out.append(row)
        if len(out) >= target:
            break
    return out


def run_object_local_automated_devtest_batch(settings, registry, resolver, certifications, rows: list[dict[str, Any]], *, fps: int = 30) -> dict[str, Any]:
    results=[]; failures=[]
    for row in rows:
        try:
            results.append(run_object_local_automated_devtest(settings, registry, resolver, certifications, asset_path=row["asset"], fps=fps))
        except Exception as exc:
            failures.append({"asset": row.get("asset"), "error": f"{type(exc).__name__}: {exc}"})
    result={
        "format": BATCH_FORMAT, "status": "PASS" if results and not failures else ("EMPTY" if not rows else "FAIL"),
        "requested": len(rows), "passed_assets": [x.get("asset") for x in results], "failed_assets": failures,
        "results": results, "automatic_only": True, "runtime_authorized": False,
        "production_authorized": False, "client_write_authorized": False, "client_modified": False,
    }
    out=pathlib.Path(settings.project_root).resolve()/"pt_build"/"devtest"/"object_local_auto"/"batch_result.json"
    out.parent.mkdir(parents=True,exist_ok=True); result["report"]=str(out)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result
