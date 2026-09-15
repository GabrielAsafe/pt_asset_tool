#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from collections import Counter
from pathlib import Path

FORMAT="PT_RIGID_CONTEXT_RECOVERY_TRIAGE_V1"

def _group(asset:str):
    p=Path(asset); m=re.match(r"^(.*?)(\d+)$",p.stem)
    return (p.parent.as_posix().casefold(),m.group(1).casefold()) if m else None

def analyze(census:dict, min_siblings:int=3):
    rows=list(census.get("rows") or [])
    resolved={}
    for r in rows:
        grp=_group(str(r.get("asset") or ""))
        sk=str(r.get("binding_skeleton_smb") or "")
        if not grp or r.get("status") != "PASS" or not sk: continue
        resolved.setdefault(grp,[]).append(r)
    candidates=[]; remaining=[]
    for r in rows:
        if str(r.get("context_class") or "").upper() != "UNRESOLVED" and r.get("status") != "FAIL": continue
        if r.get("status") != "FAIL": continue
        grp=_group(str(r.get("asset") or "")); rec=None
        if grp and str(r.get("binding_source") or "") == "NONE" and int(r.get("config_count") or 0) == 0:
            sib=resolved.get(grp,[])
            sk=Counter(str(x.get("binding_skeleton_smb")).casefold() for x in sib)
            if len(sib) >= min_siblings and len(sk) == 1:
                skeleton=next(iter(sk))
                rec={
                    "asset":r.get("asset"),"domain":r.get("domain"),"candidate_skeleton_smb":skeleton,
                    "evidence":"UNANIMOUS_SAME_DIRECTORY_TRAILING_NUMERIC_SIBLINGS",
                    "resolved_sibling_count":len(sib),"resolved_sibling_assets":[x.get("asset") for x in sib[:8]],
                    "current_binding_source":r.get("binding_source"),"current_config_count":r.get("config_count"),
                    "promotion_status":"DIAGNOSTIC_ONLY_REQUIRES_RESOLVER_AND_PHYSICAL_IMPORT_PROOF",
                }
        if rec: candidates.append(rec)
        else: remaining.append({k:r.get(k) for k in ("asset","domain","binding_source","config_count","reason")})
    return {"format":FORMAT,"status":"PASS","original_unresolved_count":census.get("unresolved_count",len(candidates)+len(remaining)),"high_confidence_candidate_count":len(candidates),"remaining_unresolved_count":len(remaining),"candidates":candidates,"remaining":remaining,"policy":"NO_GATE_PROMOTION_DIAGNOSTIC_ONLY","production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--result",required=True); ap.add_argument("--out"); a=ap.parse_args(); d=json.loads(Path(a.result).read_text(encoding="utf-8")); census=(d.get("gates",{}).get("rigid_context_census") or d.get("summary",{}).get("rigid_context_census") or {}); r=analyze(census)
    if a.out: Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
