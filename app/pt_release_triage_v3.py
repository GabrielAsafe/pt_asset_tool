#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

FORMAT="PT_RELEASE_1_BLOCKER_TRIAGE_V3"

def classify_model062(gate):
    cats=Counter(); domains=defaultdict(Counter); samples={}
    for r in gate.get("rows",[]):
        if r.get("status") == "PASS": continue
        e=r.get("error","")
        if any(x in e for x in ("OBJECT_COUNT","VERTEX_COUNT","FACE_COUNT","TEXLINK_COUNT")): cat="COUNT_LAYOUT_MISMATCH"
        elif "bad tex ptr" in e.casefold(): cat="BAD_TEXLINK_POINTER"
        else: cat="OTHER"
        cats[cat]+=1; domains[r.get("domain","UNKNOWN")][cat]+=1; samples.setdefault(cat,r)
    return {"counts":dict(cats),"by_domain":{k:dict(v) for k,v in domains.items()},"samples":samples}

def errkey(e):
    e=str(e or "")
    if "float() argument must be a string or a real number, not 'tuple'" in e: return "STATIC_FLOAT_TUPLE"
    if "PT_RC6_1_VEC3_NORMALIZE_FAIL" in e: return "STATIC_VEC3_NORMALIZE_FAIL"
    if "source normal is zero" in e: return "ZERO_SOURCE_NORMAL"
    if "duplicate skeleton NodeName" in e: return "DUPLICATE_SKELETON_CONFLICT"
    if "live source pose check failed" in e: return "LIVE_POSE_MISMATCH"
    if "rc=-15" in e: return "TIMEOUT_OR_TERMINATED"
    return re.sub(r"\d+","N",e.split(";",1)[0])[:180] or "UNKNOWN"

def classify_motion(g):
    cats=Counter(); elapsed=[]; rows=[]
    for r in g.get("rows",[]):
        if r.get("inx_edit",{}).get("status") in {"PASS","SKIP"} and r.get("smb_edit",{}).get("status") in {"PASS","SKIP"}: continue
        reasons=[]
        for k in ("inx_edit","smb_edit"):
            x=r.get(k) or {}; reason=x.get("reason") or x.get("error") or x.get("status")
            reasons.append(str(reason))
        joined=" | ".join(reasons)
        if joined.count("TIMEOUT") or "exceeded" in joined: cat="TIMEOUT"
        elif "cannot unpack non-iterable NoneType" in joined: cat="NONE_UNPACK"
        elif "engine_end" in joined and "container_end" in joined: cat="ENGINE_END_OUTSIDE_CONTAINER"
        elif "container_end=0" in joined: cat="ZERO_CONTAINER_END"
        elif "singular" in joined.casefold(): cat="SINGULAR_MATRIX"
        elif "parent" in joined.casefold(): cat="MISSING_PARENT_OR_HIERARCHY"
        else: cat="OTHER"
        cats[cat]+=1; elapsed.append(float(r.get("elapsed_seconds") or 0)); rows.append({"category":cat,"motion_inx":r.get("motion_inx"),"motion_smb":r.get("motion_smb"),"elapsed_seconds":r.get("elapsed_seconds")})
    return {"counts":dict(cats),"failure_context_count":len(rows),"max_elapsed_seconds":max(elapsed,default=0),"over_200_seconds":sum(x>200 for x in elapsed),"rows":rows}

def triage(data):
    gates=data.get("gates",{}); summary=data.get("summary",{})
    m62=classify_model062(gates.get("model062_physical_corpus",{}))
    static=Counter(errkey(x.get("error")) for x in gates.get("model062_static",{}).get("failed_assets",[]))
    rigid=Counter(errkey(x.get("error")) for x in gates.get("model062_rigid",{}).get("failed_assets",[]))
    rigid_s=Counter(errkey(x.get("error")) for x in gates.get("model062_rigid_standalone",{}).get("failed_assets",[]))
    motion=classify_motion(gates.get("motion_semantic_edit",{}))
    census=gates.get("rigid_context_census",{})
    return {
      "format":FORMAT,"release_status":data.get("status"),
      "model062_physical":m62,
      "static_representative_errors":dict(static),"rigid_representative_errors":dict(rigid),"rigid_standalone_errors":dict(rigid_s),
      "rigid_context_census":{"status":census.get("status"),"rigid_asset_count":census.get("rigid_asset_count"),"unresolved_count":census.get("unresolved_count"),"by_domain":census.get("by_domain")},
      "motion":motion,
      "texture_presence":{"failure_count":gates.get("model062_texture_presence",{}).get("failure_count"),"required_refs":gates.get("model062_texture_presence",{}).get("required_texture_reference_count")},
      "work_buckets":{
        "OFFLINE_CODE_FIRST":["MODEL062_COUNT_LAYOUT_MISMATCH","MODEL062_BAD_TEXLINK_POINTER","RIGID_CONTEXT_RESOLUTION","MOTION_NON_TIMEOUT_WRITER_ERRORS"],
        "PHYSICAL_BLENDER_PROOF":["STATIC_WRITER","RIGID_WRITER_TIMEOUTS","ANIMATION_POSE_SPACE"],
        "EXTERNAL_RUNTIME_REQUIRED":["MODEL062_MIXED_AUTHENTIC","GAME_RUNTIME_ACCEPTANCE","PUBLISH_RESTORE_ROLLBACK"]},
      "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,
    }

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--result",required=True); ap.add_argument("--out"); a=ap.parse_args(); data=json.loads(Path(a.result).read_text(encoding='utf-8')); r=triage(data)
    if a.out: Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
