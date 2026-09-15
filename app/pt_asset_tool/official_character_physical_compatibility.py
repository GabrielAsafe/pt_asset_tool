from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import pathlib
from typing import Any

from .config import Settings
from .motion_core import parse_inx_link_header, verified_inx_link_target
from .official_character_donor_census import _parse_donor_spec, _snapshot_stats, _writer_policy_snapshot
from .rare_rigid_context import parse_model062_physique_context
from .rare_rigid_geometry import _parse_skeleton_tms
from .semantic_census import classify_semantic, physical_probe
from .utils import sha256_file

FORMAT = "PT_OFFICIAL_CHARACTER_PHYSICAL_COMPATIBILITY_V2"
RELEASE = "0.9.3"
MODEL_HEADER = b"SMD Model data Ver 0.62"


def _logical(rel: str) -> str:
    p = rel.replace("\\", "/").lstrip("./")
    if p.lower().startswith("image/"):
        p = p[6:]
    return p


def _name_similarity(a: str, b: str) -> float:
    aa = pathlib.PurePosixPath(a).stem.lower()
    bb = pathlib.PurePosixPath(b).stem.lower()
    return difflib.SequenceMatcher(a=aa, b=bb).ratio()


def _bone_key(ctx: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted((str(x).casefold() for x in (ctx.get("bind_bones") or []))))


def _model_row(root: pathlib.Path, p: pathlib.Path) -> dict[str, Any]:
    rel = p.relative_to(root).as_posix()
    logical = _logical(rel)
    sem = classify_semantic(logical, ".smd", None)
    probe = physical_probe(p, rel)
    row: dict[str, Any] = {
        "relative_path": rel,
        "logical_path": logical,
        "sha256": sha256_file(p),
        "size": p.stat().st_size,
        "semantic_group": sem.semantic_group,
        "semantic_role": sem.semantic_role,
        "semantic_confidence": sem.confidence,
        "physical_family": probe.get("physical_family"),
        "parse_status": "UNSUPPORTED",
    }
    try:
        if not p.read_bytes()[:24].startswith(MODEL_HEADER[:24]):
            return row
        ctx = parse_model062_physique_context(p)
        row.update(ctx)
        row["bone_key"] = list(_bone_key(ctx))
        row["parse_status"] = "PASS"
    except Exception as exc:
        row["parse_status"] = "FAIL"
        row["parse_error"] = f"{type(exc).__name__}:{exc}"
    return row


def _scan_models(root: pathlib.Path, *, player_only: bool) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for p in sorted(root.rglob("*.smd"), key=lambda x: x.as_posix().lower()):
        try:
            r = _model_row(root, p)
            if player_only and r["semantic_group"] != "PLAYER":
                continue
            rows.append(r)
        except Exception as exc:
            errors.append({"relative_path": p.relative_to(root).as_posix(), "error": f"{type(exc).__name__}:{exc}"})
    return rows, errors


def _path_prefix_counts(rows: list[dict[str, Any]], depth: int = 3) -> dict[str, int]:
    c: collections.Counter[str] = collections.Counter()
    for r in rows:
        parts = pathlib.PurePosixPath(str(r.get("relative_path") or "")).parts
        if not parts:
            continue
        c["/".join(parts[:min(depth, len(parts))])] += 1
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0].lower())))


def _discover_donor_player_models(
    all_models: list[dict[str, Any]], skeletons: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Discover player-like donor models physically, without assuming a char/ path.

    A donor model is retained when either the semantic census already recognizes it
    as PLAYER or its serialized Physique bind-bone set is a subset of at least one
    parseable donor SMB.  This intentionally runs *after* Model0.62 parsing.
    """
    selected: list[dict[str, Any]] = []
    semantic_count = 0
    skeleton_bound_count = 0
    both_count = 0
    parsed_count = 0
    unsupported_count = 0
    failed_count = 0
    for r in all_models:
        st = r.get("parse_status")
        if st == "PASS":
            parsed_count += 1
        elif st == "FAIL":
            failed_count += 1
        else:
            unsupported_count += 1
        semantic = r.get("semantic_group") == "PLAYER"
        sk_matches = _skeleton_matches(r, skeletons) if st == "PASS" else []
        physical = bool(sk_matches)
        if semantic:
            semantic_count += 1
        if physical:
            skeleton_bound_count += 1
        if semantic and physical:
            both_count += 1
        if semantic or physical:
            rr = dict(r)
            rr["donor_player_discovery"] = (
                "SEMANTIC_AND_SKELETON" if semantic and physical
                else "SKELETON_BINDING" if physical
                else "SEMANTIC_PATH"
            )
            rr["donor_skeleton_match_count"] = len(sk_matches)
            rr["donor_skeleton_match_sample"] = sk_matches[:5]
            selected.append(rr)
    selected.sort(key=lambda r: (
        0 if r.get("donor_player_discovery") == "SEMANTIC_AND_SKELETON" else
        1 if r.get("donor_player_discovery") == "SKELETON_BINDING" else 2,
        str(r.get("logical_path") or "").lower(),
    ))
    diagnostics = {
        "all_smd_count": len(all_models),
        "model062_parse_pass": parsed_count,
        "model_parse_fail": failed_count,
        "model_unsupported": unsupported_count,
        "semantic_player_count": semantic_count,
        "skeleton_bound_player_count": skeleton_bound_count,
        "semantic_and_skeleton_count": both_count,
        "selected_player_like_count": len(selected),
        "all_smd_prefix_counts_top": dict(list(_path_prefix_counts(all_models).items())[:80]),
        "selected_prefix_counts_top": dict(list(_path_prefix_counts(selected).items())[:80]),
        "unmatched_parse_pass_sample": [
            {
                "relative_path": r.get("relative_path"),
                "logical_path": r.get("logical_path"),
                "semantic_group": r.get("semantic_group"),
                "bind_bone_count": r.get("bind_bone_count"),
                "bind_bones": (r.get("bind_bones") or [])[:16],
            }
            for r in all_models
            if r.get("parse_status") == "PASS" and r not in selected
        ][:80],
    }
    return selected, diagnostics


def _scan_skeletons(root: pathlib.Path) -> list[dict[str, Any]]:
    rows=[]
    for p in sorted(root.rglob("*.smb"), key=lambda x:x.as_posix().lower()):
        rel=p.relative_to(root).as_posix()
        rec={"relative_path":rel,"logical_path":_logical(rel),"sha256":sha256_file(p),"size":p.stat().st_size,"parse_status":"FAIL"}
        try:
            bones=_parse_skeleton_tms(p)
            rec.update({"parse_status":"PASS","bone_count":len(bones),"bones":sorted(bones,key=str.lower),"bone_key":[x.casefold() for x in sorted(bones,key=str.lower)]})
        except Exception as exc:
            rec["parse_error"]=f"{type(exc).__name__}:{exc}"
        rows.append(rec)
    return rows


def _scan_inx(root: pathlib.Path) -> list[dict[str, Any]]:
    rows=[]
    for p in sorted(root.rglob("*.inx"), key=lambda x:x.as_posix().lower()):
        rel=p.relative_to(root).as_posix()
        rec={"relative_path":rel,"logical_path":_logical(rel),"sha256":sha256_file(p),"size":p.stat().st_size,"parse_status":"FAIL"}
        try:
            rec.update(parse_inx_link_header(p))
            rec["verified_link"] = verified_inx_link_target(p)
            rec["parse_status"]="PASS"
        except Exception as exc:
            rec["parse_error"]=f"{type(exc).__name__}:{exc}"
        rows.append(rec)
    return rows


def _skeleton_matches(model: dict[str, Any], skeletons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if model.get("parse_status") != "PASS" or not model.get("bind_bones"):
        return []
    mb={x.casefold() for x in model["bind_bones"]}
    out=[]
    for s in skeletons:
        if s.get("parse_status") != "PASS":
            continue
        sb={x.casefold() for x in s.get("bones") or []}
        if mb.issubset(sb):
            out.append({"logical_path":s["logical_path"],"relative_path":s["relative_path"],"sha256":s["sha256"],"bone_count":s["bone_count"],"extra_bone_count":len(sb-mb)})
    out.sort(key=lambda x:(x["extra_bone_count"],x["logical_path"].lower()))
    return out


def _compat_score(d: dict[str, Any], s: dict[str, Any]) -> tuple[float, list[str]]:
    evidence=[]
    score=0.0
    if d.get("parse_status") != "PASS" or s.get("parse_status") != "PASS":
        return 0.0, evidence
    db=set(d.get("bone_key") or [])
    sb=set(s.get("bone_key") or [])
    if db and db == sb:
        score += 60; evidence.append("EXACT_BIND_BONE_SET")
    elif db and db.issubset(sb):
        score += 35; evidence.append("DONOR_BONES_SUBSET_OF_SUMMIT_MODEL")
    elif db and sb:
        jac=len(db&sb)/len(db|sb)
        if jac >= .9:
            score += 20*jac; evidence.append(f"BONE_JACCARD_{jac:.3f}")
    if d.get("physique_mode") == s.get("physique_mode"):
        score += 10; evidence.append("SAME_PHYSIQUE_MODE")
    if d.get("object_count") == s.get("object_count"):
        score += 6; evidence.append("SAME_OBJECT_COUNT")
    if d.get("total_vertices") == s.get("total_vertices"):
        score += 2; evidence.append("SAME_VERTEX_COUNT")
    if d.get("total_faces") == s.get("total_faces"):
        score += 2; evidence.append("SAME_FACE_COUNT")
    ns=_name_similarity(d["logical_path"],s["logical_path"])
    score += 20*ns
    if ns >= .75: evidence.append(f"NAME_SIMILARITY_{ns:.3f}")
    return round(score,3), evidence


def _map_donor(donor_name: str, models: list[dict[str, Any]], skeletons: list[dict[str, Any]], summit_models: list[dict[str, Any]], summit_skeletons: list[dict[str, Any]]) -> dict[str, Any]:
    summit_by_logical={r["logical_path"].casefold():r for r in summit_models}
    exact_bone_index: dict[tuple[str,...], list[dict[str,Any]]] = collections.defaultdict(list)
    for s in summit_models:
        if s.get("parse_status") == "PASS" and s.get("bone_key"):
            exact_bone_index[tuple(s["bone_key"])].append(s)
    mapped=[]
    stats=collections.Counter()
    for d in models:
        if d.get("parse_status") != "PASS":
            stats["unparsed"] += 1
            continue
        logical=d["logical_path"]
        exact=summit_by_logical.get(logical.casefold())
        state="DONOR_ONLY"
        if exact:
            state="EXACT_ALREADY_IN_SUMMIT" if exact["sha256"]==d["sha256"] else "SAME_LOGICAL_PATH_CHANGED"
        donor_skels=_skeleton_matches(d,skeletons)[:10]
        summit_skels=_skeleton_matches(d,summit_skeletons)[:10]
        candidates=[]
        pool=exact_bone_index.get(tuple(d.get("bone_key") or []), [])
        if not pool:
            # Fall back to name-near player models; score function remains conservative.
            pool=summit_models
        for s in pool:
            score,evidence=_compat_score(d,s)
            if score < 35:
                continue
            candidates.append({"summit_logical_path":s["logical_path"],"summit_sha256":s["sha256"],"score":score,"evidence":evidence,"object_count":s.get("object_count"),"total_vertices":s.get("total_vertices"),"total_faces":s.get("total_faces"),"bind_bone_count":s.get("bind_bone_count")})
        candidates.sort(key=lambda x:(-x["score"],x["summit_logical_path"].lower()))
        transplant_candidate = state != "EXACT_ALREADY_IN_SUMMIT" and bool(candidates) and bool(donor_skels) and bool(summit_skels)
        if transplant_candidate:
            state2="PHYSICAL_TRANSPLANT_MAPPING_CANDIDATE"
        else:
            state2=state
        stats[state2]+=1
        mapped.append({
            "donor":donor_name,
            "donor_relative_path":d["relative_path"],
            "donor_logical_path":logical,
            "donor_sha256":d["sha256"],
            "semantic_group":d["semantic_group"],
            "semantic_role":d["semantic_role"],
            "physical_family":d["physical_family"],
            "physique_mode":d.get("physique_mode"),
            "object_count":d.get("object_count"),
            "total_vertices":d.get("total_vertices"),
            "total_faces":d.get("total_faces"),
            "bind_bone_count":d.get("bind_bone_count"),
            "bind_bones":d.get("bind_bones") or [],
            "summit_presence":state,
            "mapping_status":state2,
            "exact_summit_sha256": exact.get("sha256") if exact else None,
            "donor_skeleton_matches":donor_skels,
            "summit_skeleton_matches":summit_skels,
            "summit_model_compatibility_candidates":candidates[:20],
            "transplant_write_authorized":False,
        })
    mapped.sort(key=lambda r:(0 if r["mapping_status"]=="PHYSICAL_TRANSPLANT_MAPPING_CANDIDATE" else 1, r["donor_logical_path"].lower()))
    return {"rows":mapped,"counts":dict(stats)}


def _dedupe_cross_donor(rows_by_donor: dict[str,list[dict[str,Any]]]) -> list[dict[str,Any]]:
    groups: dict[tuple[str,str], list[tuple[str,dict[str,Any]]]] = collections.defaultdict(list)
    for dn,rows in rows_by_donor.items():
        for r in rows:
            groups[(r["logical_path"].casefold(),r["sha256"])].append((dn,r))
    out=[]
    for (_,sha), vals in groups.items():
        dn0,r0=vals[0]
        out.append({"logical_path":r0["logical_path"],"sha256":sha,"donors":[x[0] for x in vals],"donor_count":len(vals),"semantic_group":r0["semantic_group"],"physique_mode":r0.get("physique_mode"),"bind_bone_count":r0.get("bind_bone_count")})
    out.sort(key=lambda x:x["logical_path"].lower())
    return out


def _write_csv(path: pathlib.Path, mappings: list[dict[str,Any]]) -> None:
    fields=["donor","donor_logical_path","donor_sha256","summit_presence","mapping_status","physique_mode","object_count","total_vertices","total_faces","bind_bone_count","top_summit_candidate","top_score"]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in mappings:
            top=(r.get("summit_model_compatibility_candidates") or [{}])[0]
            w.writerow({"donor":r["donor"],"donor_logical_path":r["donor_logical_path"],"donor_sha256":r["donor_sha256"],"summit_presence":r["summit_presence"],"mapping_status":r["mapping_status"],"physique_mode":r.get("physique_mode"),"object_count":r.get("object_count"),"total_vertices":r.get("total_vertices"),"total_faces":r.get("total_faces"),"bind_bone_count":r.get("bind_bone_count"),"top_summit_candidate":top.get("summit_logical_path"),"top_score":top.get("score")})


def run(root:pathlib.Path, output:pathlib.Path, donor_specs:list[str]) -> dict[str,Any]:
    root=root.resolve(); settings=Settings.discover(root)
    guards_before=_writer_policy_snapshot(root)
    if not all(v["pass"] for v in guards_before["writers"].values()):
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    summit_before=_snapshot_stats(settings.client_root)
    summit_models,summit_errors=_scan_models(settings.client_root,player_only=True)
    summit_skeletons=_scan_skeletons(settings.client_root)
    donors=[]; rows_by_donor={}; all_mappings=[]
    for spec in donor_specs:
        name,droot=_parse_donor_spec(spec)
        before=_snapshot_stats(droot)
        all_models,errors=_scan_models(droot,player_only=False)
        skeletons=_scan_skeletons(droot)
        models,discovery=_discover_donor_player_models(all_models,skeletons)
        inx=_scan_inx(droot)
        mapping=_map_donor(name,models,skeletons,summit_models,summit_skeletons)
        after=_snapshot_stats(droot)
        if before != after: raise RuntimeError(f"DONOR_CHANGED_DURING_READ_ONLY_AUDIT:{name}")
        rows_by_donor[name]=models
        all_mappings.extend(mapping["rows"])
        donors.append({"name":name,"root":str(droot),"read_only":True,"all_smd_count":len(all_models),"all_smd_parse_pass":sum(r.get("parse_status")=="PASS" for r in all_models),"player_model_count":len(models),"player_model_parse_pass":sum(r.get("parse_status")=="PASS" for r in models),"player_discovery":discovery,"skeleton_count":len(skeletons),"skeleton_parse_pass":sum(r.get("parse_status")=="PASS" for r in skeletons),"inx_count":len(inx),"inx_parse_pass":sum(r.get("parse_status")=="PASS" for r in inx),"mapping_counts":mapping["counts"],"skeletons":skeletons,"inx":inx})
    if _snapshot_stats(settings.client_root) != summit_before:
        raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_READ_ONLY_AUDIT")
    guards_after=_writer_policy_snapshot(root)
    if guards_after != guards_before: raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_READ_ONLY_AUDIT")

    candidate_rows=[r for r in all_mappings if r["mapping_status"]=="PHYSICAL_TRANSPLANT_MAPPING_CANDIDATE"]
    changed_rows=[r for r in all_mappings if r["summit_presence"]=="SAME_LOGICAL_PATH_CHANGED"]
    absent_rows=[r for r in all_mappings if r["summit_presence"]=="DONOR_ONLY"]
    # Old/new donor copies are usually identical. Show unique physical assets to keep results actionable.
    unique_assets=_dedupe_cross_donor(rows_by_donor)
    unique_candidate_keys={(r["donor_logical_path"].casefold(),r["donor_sha256"]) for r in candidate_rows}
    unique_candidate_count=len(unique_candidate_keys)
    candidate_rows.sort(key=lambda r:(-(r.get("summit_model_compatibility_candidates") or [{"score":0}])[0].get("score",0),r["donor_logical_path"].lower()))

    output.parent.mkdir(parents=True,exist_ok=True)
    csv_path=output.with_suffix(".csv"); md_path=output.with_suffix(".md")
    report={
        "format":FORMAT,"status":"PASS","release_version":RELEASE,
        "summit_client_root":str(settings.client_root),"client_and_donors_read_only":True,
        "summit":{"player_model_count":len(summit_models),"player_model_parse_pass":sum(r.get("parse_status")=="PASS" for r in summit_models),"skeleton_count":len(summit_skeletons),"skeleton_parse_pass":sum(r.get("parse_status")=="PASS" for r in summit_skeletons),"scan_errors":summit_errors[:100]},
        "donors":donors,
        "unique_donor_player_assets":unique_assets,
        "mapping_summary":{"mapping_row_count":len(all_mappings),"physical_transplant_mapping_candidate_rows":len(candidate_rows),"physical_transplant_mapping_candidate_unique_assets":unique_candidate_count,"same_logical_path_changed_rows":len(changed_rows),"donor_only_rows":len(absent_rows),"exact_already_in_summit_rows":sum(r["summit_presence"]=="EXACT_ALREADY_IN_SUMMIT" for r in all_mappings)},
        "priority_candidates":candidate_rows[:120],
        "same_logical_path_changed":changed_rows[:120],
        "donor_only":absent_rows[:120],
        "guards":{"certified_writer_hashes_valid":True,"writer_modules_modified":False,"production_policies_modified":False,"policy_sha256":guards_after["policies"]},
        "decision":{"transplant_write_authorized":False,"new_class_claimed":False,"next_on_pass":"choose one physically mapped official donor body/head family, assemble textures/config dependencies read-only, open it in Blender, then build an isolated Summit-slot transplant candidate"},
        "outputs":{"json":str(output),"csv":str(csv_path),"markdown":str(md_path)},
    }
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _write_csv(csv_path,all_mappings)
    lines=["# Official Character Physical Compatibility V0.9.3","",f"Summit player models parsed: **{report['summit']['player_model_parse_pass']}**",f"Unique donor player assets: **{len(unique_assets)}**",f"Unique physical transplant mapping candidates: **{unique_candidate_count}**",f"Same logical path but changed: **{len(changed_rows)}**",f"Donor-only rows: **{len(absent_rows)}**","","## Top candidates",""]
    for r in candidate_rows[:40]:
        top=(r.get("summit_model_compatibility_candidates") or [{}])[0]
        lines.append(f"- `{r['donor_logical_path']}` -> `{top.get('summit_logical_path','')}` score={top.get('score','')} bones={r.get('bind_bone_count')} presence={r['summit_presence']}")
    lines += ["","No client files are written by this audit."]
    md_path.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); ap.add_argument("--output",required=True); ap.add_argument("--donor",action="append",required=True); a=ap.parse_args(argv)
    out=pathlib.Path(a.output)
    try:
        r=run(pathlib.Path(a.root),out,list(a.donor))
        compact={"format":r["format"],"status":r["status"],"release_version":r["release_version"],"client_and_donors_read_only":r["client_and_donors_read_only"],"summit":r["summit"],"donors":[{k:d[k] for k in ("name","root","read_only","all_smd_count","all_smd_parse_pass","player_model_count","player_model_parse_pass","player_discovery","skeleton_count","skeleton_parse_pass","inx_count","inx_parse_pass","mapping_counts")} for d in r["donors"]],"mapping_summary":r["mapping_summary"],"priority_candidates":[{"donor":x["donor"],"donor_logical_path":x["donor_logical_path"],"summit_presence":x["summit_presence"],"bind_bone_count":x["bind_bone_count"],"donor_skeletons":[s["logical_path"] for s in x["donor_skeleton_matches"][:3]],"summit_skeletons":[s["logical_path"] for s in x["summit_skeleton_matches"][:3]],"top_summit_candidates":x["summit_model_compatibility_candidates"][:3]} for x in r["priority_candidates"][:30]],"decision":r["decision"],"guards":r["guards"],"outputs":r["outputs"]}
        print(json.dumps(compact,ensure_ascii=False,indent=2)); print(f"official_character_physical_compatibility=PASS unique_candidates={r['mapping_summary']['physical_transplant_mapping_candidate_unique_assets']} read_only=true")
        return 0
    except Exception as exc:
        fail={"format":FORMAT,"status":"FAIL","release_version":RELEASE,"error":f"{type(exc).__name__}:{exc}","transplant_write_authorized":False}
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(fail,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(fail,ensure_ascii=False,indent=2)); return 2

if __name__ == "__main__":
    raise SystemExit(main())
