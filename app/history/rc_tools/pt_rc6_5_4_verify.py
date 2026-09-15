#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args()
    app=Path(a.app_root).resolve()
    p=app/"pt_build/devtest/rc6_5_4_static_focused/result.json"
    out={
      "format":"PT_RC6_5_4_VERIFY_V1",
      "production_authorized":False,
      "client_write_authorized":False,
      "server_write_authorized":False,
    }
    if not p.is_file():
        out["status"]="NO_RESULT"
        print(json.dumps(out,indent=2,ensure_ascii=False)); return
    d=json.loads(p.read_text(encoding="utf-8"))
    out["bootstrap_status"]=d.get("status")
    out["server_design_intercepted"]=d.get("server_design_intercepted")
    out["expected_domain_counts"]=d.get("expected_domain_counts")
    out["selected_row_count"]=d.get("selected_row_count")
    out["domain_selection"]=d.get("domain_selection")
    r=d.get("result") if isinstance(d.get("result"),dict) else {}
    failed=r.get("failed_assets",[]) or []
    errors=[str(x.get("error","")) for x in failed if isinstance(x,dict)]
    out["requested"]=r.get("requested")
    out["passed_count"]=len(r.get("passed_assets",[]) or [])
    out["failed_count"]=len(failed)
    out["legacy_float_tuple_count"]=sum(
        "float() argument must be a string or a real number, not 'tuple'" in e for e in errors
    )
    out["rc6_1_vec3_fail_count"]=sum("PT_RC6_1_VEC3_NORMALIZE_FAIL" in e for e in errors)
    out["rc6_5_divergent_count"]=sum("PT_RC6_5_MULTI_VEC3_DIVERGENT" in e for e in errors)
    samples=[]
    for e in errors:
        m=re.search(
            r"PT_RC6_5_MULTI_VEC3_DIVERGENT count=(\d+) nonzero=(\d+) "
            r"max_unit_component_delta=([0-9.eE+-]+)", e
        )
        if m:
            samples.append({
                "count":int(m.group(1)),
                "nonzero":int(m.group(2)),
                "max_delta":float(m.group(3)),
            })
    out["divergence_samples"]=samples[:20]
    out["failed_assets"]=[
        {
            "asset":x.get("asset"),
            "domain":x.get("domain"),
            "error_tail":str(x.get("error",""))[-700:],
        }
        for x in failed[:20] if isinstance(x,dict)
    ]
    out["result_report"]=r.get("report")
    out["status"]="PASS" if d.get("status")=="PASS" else "FAIL"
    print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
