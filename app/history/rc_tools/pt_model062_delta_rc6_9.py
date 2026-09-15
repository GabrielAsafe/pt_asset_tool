#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, pathlib
from pathlib import Path
from pt_asset_tool.config import Settings
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.model062_corpus import FAMILIES, _physical_mode
from pt_asset_tool.release_1_coverage import content_domain
from pt_asset_tool.static_roundtrip import _parse as parse_model062_bytes

FORMAT="PT_RC6_9_MODEL062_DELTA_CLOSURE_V1"
TARGET="char/tmABCD/TmbC01.smd"

def validate_asset(asset,resolver):
    source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve(); b=source.read_bytes()
    live=hashlib.sha256(b).hexdigest(); inv=str((asset.source_record or {}).get("sha256") or "").lower()
    parsed=parse_model062_bytes(b); objects=list(parsed.get("object_list") or (parsed.get("objects") or {}).values())
    mode=_physical_mode(objects); family=str(asset.family or ""); errors=[]
    object_count=len(objects); vertices=sum(int(o.get("nv") or 0) for o in objects); faces=sum(int(o.get("nf") or 0) for o in objects); texlinks=sum(int(o.get("nt") or 0) for o in objects)
    expected_mode=FAMILIES.get(family)
    if inv and live!=inv: errors.append(f"INVENTORY_SHA_DRIFT:{inv}!={live}")
    if expected_mode and mode!=expected_mode: errors.append(f"PHYSIQUE_MODE:{expected_mode}!={mode}")
    checks=(("OBJECT_COUNT",int(asset.object_count or 0),object_count),("VERTEX_COUNT",int(asset.total_vertices or 0),vertices),("FACE_COUNT",int(asset.total_faces or 0),faces),("MATERIAL_COUNT",int(asset.material_count or 0),int(parsed.get("mat_count") or 0)),("TEXLINK_COUNT",int((asset.source_record or {}).get("total_texlinks") or 0),texlinks))
    for name,exp,got in checks:
        if exp and exp!=got: errors.append(f"{name}:{exp}!={got}")
    return {"asset_id":asset.asset_id,"asset":asset.primary_path,"domain":content_domain(asset),"family":family,
            "status":"PASS" if not errors else "FAIL","errors":errors,"source_sha256":live,"inventory_source_sha256":inv,
            "physical_mode":mode,"object_count":object_count,"vertices":vertices,"faces":faces,"texlinks":texlinks,"material_count":int(parsed.get("mat_count") or 0)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    a=ap.parse_args(); app=Path(a.app_root).resolve(); client=Path(a.client_root).resolve()
    prior=app/"pt_build/devtest/rc6_8_model062_physical/result.json"
    if not prior.is_file(): raise SystemExit("rc6_9_delta_error=missing rc6.8 full corpus")
    base=json.loads(prior.read_text(encoding="utf-8")); failures=[r for r in base.get("rows") or [] if r.get("status")=="FAIL"]
    if int(base.get("asset_count") or 0)!=3144 or int(base.get("failure_count") or 0)!=1 or len(failures)!=1 or str(failures[0].get("asset") or "").casefold()!=TARGET.casefold() or "INVENTORY_SHA_DRIFT:" not in str(failures[0].get("error") or ""):
        raise RuntimeError("RC6.8 base result is not the expected 3144/1 TmbC01 drift proof")
    settings=Settings.discover(app,client); resolver=ClientResolver(client); registry=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    asset=next((x for x in registry.assets if str(x.primary_path).casefold()==TARGET.casefold()),None)
    if asset is None: raise RuntimeError("target asset not found in registry")
    delta=validate_asset(asset,resolver)
    effective_fail=0 if delta["status"]=="PASS" else 1
    report={"format":FORMAT,"status":"PASS" if effective_fail==0 else "FAIL","basis":"RC6.8_FULL_CORPUS_PLUS_SINGLE_ASSET_DELTA",
            "base":{"asset_count":3144,"failure_count":1,"target":TARGET,"base_status":base.get("status")},"delta":delta,
            "effective_asset_count":3144,"effective_pass_count":3144-effective_fail,"effective_failure_count":effective_fail,
            "unchanged_assets_reused":3143,"assets_reread":1,"production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,"client_modified":False}
    out=app/"pt_build/devtest/rc6_9_model062_delta/result.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps(report,indent=2,ensure_ascii=False))
    if report["status"]!="PASS": raise SystemExit(3)
if __name__=="__main__": main()
