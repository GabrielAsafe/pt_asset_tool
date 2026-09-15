from __future__ import annotations

import json
import pathlib
from typing import Any

from .animation_pose_devtest import (
    choose_animation_pose_representatives,
    choose_animation_pose_physical_representatives,
    filter_animation_pose_physical_representatives,
    run_animation_pose_automated_devtest_batch,
)
from .environment_validation import run_environment_validation
from .model062_material_devtest import (
    audit_model062_material_physical_corpus,
    choose_all_model062_material_representatives,
    run_model062_material_automated_devtest_batch,
)
from .release_1_coverage import CONTENT_DOMAINS, build_release_1_automated_gate_plan, content_domain_from_values
from .rigid_semantic_devtest import run_rigid_semantic_automated_devtest_batch
from .standalone_animation_devtest import (
    choose_standalone_animation_representatives,
    run_standalone_animation_pose_devtest_batch,
    audit_smb_animation_corpus,
)
from .standalone_rigid_devtest import (
    choose_standalone_rigid_authorable_representatives,
    run_standalone_rigid_automated_devtest_batch,
)
from .static_semantic_devtest import (
    audit_model062_static_physical_corpus,
    choose_static_semantic_representatives,
    run_static_semantic_automated_devtest_batch,
)
from .texlink_devtest import choose_multilayer_representatives, run_multilayer_texlink_automated_devtest_batch
from .texture_codec_devtest import audit_proprietary_texture_codecs
from .writer_corpus_audit import audit_smb_writer_corpus, audit_smb_writer_edit_corpus

FORMAT = "PT_ASSET_PHYSICAL_REGRESSION_AUTO_V1"

# These are not arbitrary representatives: each path exposed a concrete failure
# in the first complete Release-1 run against the physical client.  Keeping the
# set explicit turns those historical regressions into permanent automatic
# witnesses while normal representative selection continues to cover breadth.
KNOWN_RIGID_REGRESSIONS = (
    ("char/monster/MonWolverin/wolverin.smd", "char/monster/MonWolverin/MonWolverin-01.inx", "MONSTER"),
    ("char/monster/death_knight/death_knight.smd", "char/monster/death_knight/death_knight.inx", "MONSTER"),
    ("char/monster/Beetle/beetle.smd", "char/monster/Beetle/beetle.inx", "MONSTER"),
    ("char/npc/Bcn02/Bcn02.smd", "char/npc/Bcn02/Bcn02.inx", "NPC"),
)
KNOWN_STATIC_REGRESSIONS = (
    ("weapons/crownasafut.smd", "WEAPON_ITEM"),
)
KNOWN_TEXLINK_REGRESSIONS = (
    ("Field/Iron/i2-bip12_ani.smd", "MAP"),
)
KNOWN_MATERIAL_REGRESSIONS = (
    "image/Sinimage/Items/DropItem/itdg101.smd",
    "char/Flag/wow.smd",
    "char/npc/TN-017/TN-017.smd",
    "char/monster/hobogolem/hobogolem-D.smd",
    "Field/dungeon/dun-4-ani-33.smd",
)


def _progress(message: str) -> None:
    print(f"[physical-regression-auto] {message}", flush=True)


def _run(label: str, fn):
    _progress(f"START {label}")
    try:
        result = fn()
    except Exception as exc:
        result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    _progress(f"DONE  {label} status={result.get('status') if isinstance(result, dict) else 'UNKNOWN'}")
    return result


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]; seen=set()
    for row in rows:
        key=str(row.get("asset") or "").replace("\\", "/").casefold()
        if not key or key in seen:
            continue
        seen.add(key); out.append(row)
    return out


def _asset_exists(registry, logical: str, family: str | None = None) -> bool:
    try:
        asset=registry.resolve(logical)
    except Exception:
        return False
    return family is None or str(asset.family or "") == str(family)


def _known_rigid_rows(registry) -> list[dict[str, Any]]:
    rows=[]
    for asset_path, inx, domain in KNOWN_RIGID_REGRESSIONS:
        if not _asset_exists(registry, asset_path, "SMD_MODEL_062_RIGID_PHYSIQUE"):
            continue
        rows.append({"asset":asset_path,"model_info_inx":inx,"domain":domain})
    return rows


def _known_static_rows(registry) -> list[dict[str, Any]]:
    return [
        {"asset":asset,"domain":domain}
        for asset,domain in KNOWN_STATIC_REGRESSIONS
        if _asset_exists(registry,asset,"SMD_MODEL_062_STATIC")
    ]


def _known_texlink_rows(registry) -> list[dict[str, Any]]:
    rows=[]
    for asset_path,domain in KNOWN_TEXLINK_REGRESSIONS:
        if not _asset_exists(registry,asset_path,"SMD_MODEL_062_RIGID_PHYSIQUE"):
            continue
        asset=registry.resolve(asset_path)
        rows.append({"asset":asset.primary_path,"family":asset.family,"domain":domain,"coverage_features":["FAMILY_RIGID"]})
    return rows


def _material_rows(registry) -> list[dict[str, Any]]:
    rows=[]
    for domain_rows in choose_all_model062_material_representatives(registry,per_domain=1).values():
        rows.extend(domain_rows)
    for logical in KNOWN_MATERIAL_REGRESSIONS:
        if not _asset_exists(registry,logical):
            continue
        asset=registry.resolve(logical)
        if str(asset.family or "") not in {"SMD_MODEL_062_RIGID_PHYSIQUE","SMD_MODEL_062_STATIC","SMD_MODEL_062_MIXED_PHYSIQUE"}:
            continue
        if int(getattr(asset,"material_count",0) or 0) <= 0:
            continue
        domain=content_domain_from_values(asset.primary_path,str(asset.category or ""))
        rows.append({"asset_id":asset.asset_id,"asset":asset.primary_path,"domain":domain,"family":asset.family,"material_count":int(asset.material_count or 0)})
    return _dedupe(rows)


def _physical_files_by_domain(registry, suffix: str) -> dict[str, list[str]]:
    wanted=str(suffix).casefold(); out={d:[] for d in CONTENT_DOMAINS}; seen={d:set() for d in CONTENT_DOMAINS}
    for record in registry.records:
        if str(record.get("extension") or "").casefold() != wanted:
            continue
        logical=str(record.get("relative_path") or "").replace("\\","/")
        domain=content_domain_from_values(logical,str(record.get("category_hint") or ""))
        if domain not in out: continue
        key=logical.casefold()
        if key in seen[domain]: continue
        seen[domain].add(key); out[domain].append(logical)
    for domain in out: out[domain].sort(key=str.casefold)
    return out


def run_physical_regression_auto(
    settings, registry, resolver, certifications, *,
    fps: int = 30, blender_timeout_seconds: float = 60.0, smb_sample_limit: int = 25,
    rigid_operation_timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Focused physical gate for fixes discovered by the first full client run.

    This is deliberately smaller than ``release-1-auto``.  It proves the
    environment again, executes the exact historical failure witnesses plus one
    current representative per present domain, and runs the relevant read-only
    corpora.  It never authorizes production and never writes the client.
    """
    root=pathlib.Path(settings.project_root).resolve()
    out=root/"pt_build"/"devtest"/"physical_regression_auto"/"result.json"
    _progress(f"BEGIN client_root={settings.client_root}")

    environment=_run("environment",lambda:run_environment_validation(
        settings,registry,resolver,blender_timeout_seconds=float(blender_timeout_seconds)))
    gates: dict[str, Any]={"environment":environment}
    if environment.get("status") != "PASS":
        result={
            "format":FORMAT,"status":"FAIL","physical_regression_ready":False,"gates":gates,
            "required_failures":["environment"],"production_authorized":False,"client_write_authorized":False,
            "client_modified":bool(environment.get("client_modified")),"report":str(out),
        }
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return result

    plan=build_release_1_automated_gate_plan(registry,rigid_per_domain=1,static_per_domain=1)

    material_rows=_material_rows(registry)
    gates["model062_material_witnesses"]=_run("model062_material_witnesses",lambda:run_model062_material_automated_devtest_batch(settings,registry,resolver,material_rows))
    gates["model062_material_corpus"]=_run("model062_material_corpus",lambda:audit_model062_material_physical_corpus(registry,resolver,sample_limit=100))

    rigid_rows=_known_rigid_rows(registry)
    # Add one normal current PLAYER representative so the focused gate is not
    # exclusively a historical MONSTER/NPC regression suite.
    for row in (plan.get("rigid_representatives") or {}).get("PLAYER",[])[:1]: rigid_rows.append(row)
    rigid_rows=_dedupe(rigid_rows)
    gates["rigid_regressions"]=_run("rigid_regressions",lambda:run_rigid_semantic_automated_devtest_batch(
        settings,registry,resolver,certifications,rigid_rows,amplitude=0.12,
        operation_timeout_seconds=float(rigid_operation_timeout_seconds),resume=True,
        progress=lambda m:_progress(f"RIGID {m}"),
    ))

    static_rows=[]
    for domain in CONTENT_DOMAINS:
        static_rows.extend(choose_static_semantic_representatives(registry,resolver,domain,limit=1))
    static_rows=_dedupe(_known_static_rows(registry)+static_rows)
    gates["static_regressions"]=_run("static_regressions",lambda:run_static_semantic_automated_devtest_batch(settings,registry,resolver,certifications,static_rows,amplitude=0.08,require_topology=True))
    gates["static_corpus"]=_run("static_corpus",lambda:audit_model062_static_physical_corpus(registry,resolver,sample_limit=100))

    standalone_rows=[]
    for domain in ("PLAYER","NPC","MONSTER","EFFECT","MAP"):
        standalone_rows.extend(choose_standalone_rigid_authorable_representatives(registry,resolver,domain,limit=1))
    standalone_rows=_dedupe(standalone_rows)
    gates["standalone_rigid"]=_run("standalone_rigid",lambda:run_standalone_rigid_automated_devtest_batch(settings,registry,resolver,certifications,standalone_rows,amplitude=0.12)) if standalone_rows else {"status":"EMPTY","requested":0}

    animation_rows=[]
    for domain in ("PLAYER","NPC","MONSTER"):
        broad_animation = choose_animation_pose_representatives(registry,domain,limit=50)
        animation_rows.extend(filter_animation_pose_physical_representatives(broad_animation,resolver,limit=1))
    animation_rows=_dedupe(animation_rows)
    gates["animation_pose"]=_run("animation_pose",lambda:run_animation_pose_automated_devtest_batch(settings,registry,resolver,certifications,animation_rows,fps=int(fps)))

    standalone_animation=[]
    for rows in choose_standalone_animation_representatives(registry,resolver,per_domain=1).values(): standalone_animation.extend(rows)
    standalone_animation=_dedupe(standalone_animation)
    gates["standalone_animation_pose"]=_run("standalone_animation_pose",lambda:run_standalone_animation_pose_devtest_batch(settings,registry,resolver,certifications,standalone_animation,fps=int(fps))) if standalone_animation else {"status":"EMPTY","requested":0}
    gates["smb_animation_corpus"]=_run("smb_animation_corpus",lambda:audit_smb_animation_corpus(registry,resolver,sample_limit=100))

    texlink_rows=_known_texlink_rows(registry)
    for domain in CONTENT_DOMAINS:
        texlink_rows.extend(choose_multilayer_representatives(registry,resolver,limit=1,domain=domain))
    texlink_rows=_dedupe(texlink_rows)
    gates["texlink_regressions"]=_run("texlink_regressions",lambda:run_multilayer_texlink_automated_devtest_batch(settings,registry,resolver,certifications,texlink_rows)) if texlink_rows else {"status":"EMPTY","requested":0}

    gates["texture_codecs"]=_run("texture_codecs",lambda:audit_proprietary_texture_codecs(root,registry,resolver,per_family=3))

    smb_files=_physical_files_by_domain(registry,".smb")
    writer_domains={}
    for domain in ("MONSTER","EFFECT"):
        paths=smb_files.get(domain) or []
        if not paths: continue
        writer_domains[domain]={
            "noop":_run(f"smb_noop[{domain}]",lambda paths=paths:audit_smb_writer_corpus(root,settings.client_root,logical_paths=paths,sample_limit=int(smb_sample_limit))),
            "edit":_run(f"smb_edit[{domain}]",lambda paths=paths:audit_smb_writer_edit_corpus(root,settings.client_root,logical_paths=paths,sample_limit=int(smb_sample_limit))),
        }
    gates["smb_writer_regressions"]={
        "status":"PASS" if writer_domains and all(v["noop"].get("status")=="PASS" and v["edit"].get("status")=="PASS" for v in writer_domains.values()) else ("EMPTY" if not writer_domains else "FAIL"),
        "by_domain":writer_domains,
    }

    optional_empty={"standalone_rigid","standalone_animation_pose","texlink_regressions"}
    required_failures=[]
    for name,row in gates.items():
        status=str((row or {}).get("status") or "") if isinstance(row,dict) else ""
        if status == "PASS": continue
        if name in optional_empty and status == "EMPTY": continue
        required_failures.append(name)
    result={
        "format":FORMAT,"status":"PASS" if not required_failures else "FAIL",
        "physical_regression_ready":not required_failures,"required_failures":required_failures,
        "selection":{
            "materials":[r.get("asset") for r in material_rows],"rigid":[r.get("asset") for r in rigid_rows],
            "static":[r.get("asset") for r in static_rows],"standalone_rigid":[r.get("asset") for r in standalone_rows],
            "animation":[r.get("asset") for r in animation_rows],"standalone_animation":[r.get("asset") for r in standalone_animation],
            "texlink":[r.get("asset") for r in texlink_rows],
        },
        "gates":gates,
        "next_gate":"release-1-auto --resume" if not required_failures else "FIX_REPORTED_PHYSICAL_REGRESSIONS",
        "production_authorized":False,"client_write_authorized":False,"client_modified":False,
        "report":str(out),
    }
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _progress(f"END status={result['status']} report={out}")
    return result
