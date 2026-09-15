#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, pathlib
from collections import Counter
from typing import Any
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.rigid_context_census import _structural_check
from pt_asset_tool.standalone_rigid_devtest import explicit_skeleton_candidate

OLD_UNRESOLVED=16
OLD_RIGID_COUNT=1951
FORMAT="PT_RC6_10_RIGID_CONTEXT_DELTA_V1"

def find_census(obj: Any):
    stack=[obj]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            if x.get("format")=="PT_RIGID_CONTEXT_CENSUS_V1": return x
            stack.extend(x.values())
        elif isinstance(x,list): stack.extend(x)
    return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    a=ap.parse_args(); app=pathlib.Path(a.app_root).resolve(); client=pathlib.Path(a.client_root).resolve()
    priorp=app/"pt_build/devtest/release_1_auto/result.json"
    prior=find_census(json.loads(priorp.read_text(encoding="utf-8")))
    if not prior or prior.get("rigid_asset_count")!=OLD_RIGID_COUNT or prior.get("unresolved_count")!=OLD_UNRESOLVED:
        raise RuntimeError("expected physical baseline rigid census 1951/16 not found")
    settings=Settings.discover(app,client); resolver=ClientResolver(client); registry=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    old_unresolved=[r for r in prior.get("rows",[]) if r.get("status")=="FAIL"]
    targets=[]; untouched=[]
    smd_cache={}; smb_cache={}
    for old in old_unresolved:
        asset=registry.resolve(old["asset"])
        probe=explicit_skeleton_candidate(registry,asset)
        if probe.get("candidate_basis")!="SERIES_SIBLING_CONSENSUS":
            untouched.append({"asset":old["asset"],"domain":old.get("domain"),"reason":old.get("reason"),"new_candidate_basis":probe.get("candidate_basis")})
            continue
        source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
        skeleton=pathlib.Path(resolver.resolve(probe["candidate_smb"],required=True)).resolve()
        structural=_structural_check(source,skeleton,smd_cache=smd_cache,smb_cache=smb_cache)
        row={"asset":asset.primary_path,"asset_id":asset.asset_id,"domain":old.get("domain"),
             "candidate_skeleton_smb":probe.get("candidate_smb"),"candidate_basis":probe.get("candidate_basis"),
             "series_resolved_sibling_count":probe.get("series_resolved_sibling_count"),
             "series_unique_skeleton_count":probe.get("series_unique_skeleton_count"),
             "series_evidence_sample":probe.get("series_evidence_sample"),"structural_gate":structural,
             "status":"PASS" if structural.get("status")=="PASS" else "FAIL"}
        targets.append(row)
    promoted=[r for r in targets if r["status"]=="PASS"]
    still=[r for r in targets if r["status"]!="PASS"]
    effective_unresolved=OLD_UNRESOLVED-len(promoted)
    by_domain=Counter(str(r.get("domain") or "UNKNOWN") for r in untouched+still)
    result={"format":FORMAT,"status":"PASS" if len(targets)==10 and len(promoted)==10 and effective_unresolved==6 else "FAIL",
            "basis":"PRIOR_FULL_CENSUS_PLUS_SERIES_CONSENSUS_DELTA",
            "rigid_asset_count":OLD_RIGID_COUNT,"baseline_unresolved_count":OLD_UNRESOLVED,
            "target_count":len(targets),"promoted_count":len(promoted),"target_failure_count":len(still),
            "effective_unresolved_count":effective_unresolved,"effective_unresolved_by_domain":dict(sorted(by_domain.items())),
            "census_rows_reused":OLD_RIGID_COUNT-len(targets),"target_rows_revalidated":len(targets),
            "targets":targets,"remaining_unresolved":untouched+still,
            "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,"client_modified":False}
    out=app/"pt_build/devtest/rc6_10_rigid_context_delta/result.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if result["status"]!="PASS": raise SystemExit(3)
if __name__=="__main__": main()
