#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

FORMAT="PT_RC6_5_5_STATIC_RECOVERY_V1"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args()
    app=Path(a.app_root).resolve()
    batch=app/"pt_build/devtest/static_semantic_auto/batch_result.json"
    install=app/"pt_build/devtest/rc6_5_4_install.json"
    out=app/"pt_build/devtest/rc6_5_5_static_focused/result.json"
    result={
      "format":FORMAT, "mode":"RECOVER", "app_root":str(app),
      "production_authorized":False, "client_write_authorized":False, "server_write_authorized":False,
    }
    if not batch.is_file() or not install.is_file():
        result.update({"status":"STALE_OR_UNPROVEN","reason":"missing batch or rc6.5.4 install evidence"})
        print(json.dumps(result,indent=2,ensure_ascii=False)); raise SystemExit(4)
    data=json.loads(batch.read_text(encoding="utf-8"))
    fresh_by_mtime=batch.stat().st_mtime_ns > install.stat().st_mtime_ns
    failed=data.get("failed_assets",[]) or []
    errors=[str(x.get("error","")) for x in failed if isinstance(x,dict)]
    rc65=sum("PT_RC6_5_MULTI_VEC3_DIVERGENT" in e for e in errors)
    rc61=sum("PT_RC6_1_VEC3_NORMALIZE_FAIL" in e for e in errors)
    legacy=sum("float() argument must be a string or a real number, not 'tuple'" in e for e in errors)
    passed=len(data.get("passed_assets",[]) or [])
    requested=int(data.get("requested",-1))
    evidence_new = rc65 > 0 or (requested==13 and passed==13 and not failed)
    fresh = requested==13 and fresh_by_mtime and (evidence_new or (rc61==0 and legacy==0))
    result["fresh_by_mtime"]=fresh_by_mtime
    result["requested"]=requested
    result["passed_count"]=passed
    result["failed_count"]=len(failed)
    result["rc6_5_divergent_count"]=rc65
    result["rc6_1_vec3_fail_count"]=rc61
    result["legacy_float_tuple_count"]=legacy
    result["batch_mtime_ns"]=batch.stat().st_mtime_ns
    result["install_mtime_ns"]=install.stat().st_mtime_ns
    if not fresh:
        result.update({"status":"STALE_OR_UNPROVEN","reason":"batch cannot be proven to be RC6.5.4 post-install evidence"})
        print(json.dumps(result,indent=2,ensure_ascii=False)); raise SystemExit(4)
    result["status"]=data.get("status","UNKNOWN")
    result["result"]=data
    result["recovered_without_blender_rerun"]=True
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "format":FORMAT,"status":result["status"],"mode":"RECOVER",
        "requested":requested,"passed_count":passed,"failed_count":len(failed),
        "rc6_5_divergent_count":rc65,"recovered_without_blender_rerun":True
    },indent=2,ensure_ascii=False))

if __name__=="__main__": main()
