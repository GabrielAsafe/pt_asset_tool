#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args()
    app=Path(a.app_root).resolve()
    result=app/"pt_build/devtest/rc6_5_static_focused/result.json"
    install=app/"pt_build/devtest/rc6_5_install.json"
    report={"format":"PT_RC6_5_VERIFY_V1","production_authorized":False,
            "client_write_authorized":False,"server_write_authorized":False}
    if install.is_file():
        report["install"]=json.loads(install.read_text())
    if result.is_file():
        d=json.loads(result.read_text())
        r=d.get("result") if isinstance(d.get("result"),dict) else {}
        failed=r.get("failed_assets",[]) or []
        errors=[str(x.get("error","")) for x in failed]
        report["focused_status"]=d.get("status")
        report["requested"]=r.get("requested")
        report["passed_count"]=len(r.get("passed_assets",[]) or [])
        report["failed_count"]=len(failed)
        report["rc6_1_vec3_fail_count"]=sum("PT_RC6_1_VEC3_NORMALIZE_FAIL" in x for x in errors)
        report["rc6_5_divergent_count"]=sum("PT_RC6_5_MULTI_VEC3_DIVERGENT" in x for x in errors)
        report["legacy_float_tuple_count"]=sum("float() argument must be a string or a real number, not 'tuple'" in x for x in errors)
        ds=[]
        for e in errors:
            m=re.search(r"PT_RC6_5_MULTI_VEC3_DIVERGENT count=(\d+) nonzero=(\d+) max_unit_component_delta=([0-9.eE+-]+)",e)
            if m:
                ds.append({"count":int(m.group(1)),"nonzero":int(m.group(2)),"max_delta":float(m.group(3))})
        report["divergence_samples"]=ds[:20]
    else:
        report["focused_status"]="NO_RESULT"
    print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__":
    main()
