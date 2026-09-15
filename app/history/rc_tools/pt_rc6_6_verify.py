#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

EXPECTED_STATIC_SHA='f01673a6c9f04a7b3b407edc9c2d7fead0ea2e7dc2e6d4d5086f5fd6cf68a388'
EXPECTED_CORE_SHA='a48843bf9b1235090b156a13d0a6110b6877c1d27c8bb20176167c6fc6266c6a'

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--app-root",default=".")
    a=ap.parse_args()
    app=Path(a.app_root).resolve()
    result_path=app/"pt_build/devtest/rc6_6_static_focused/result.json"
    out={
        "format":"PT_RC6_6_VERIFY_V1",
        "production_authorized":False,
        "client_write_authorized":False,
        "server_write_authorized":False,
    }
    sw=app/"pt_blender_to_smd_static_v1.py"
    core=app/"pt_blender_to_smd_free_mesh_v3.py"
    out["static_writer_sha256"]=sha(sw) if sw.is_file() else None
    out["free_mesh_core_sha256"]=sha(core) if core.is_file() else None
    out["static_writer_expected_sha256"]=EXPECTED_STATIC_SHA
    out["free_mesh_core_expected_sha256"]=EXPECTED_CORE_SHA
    out["hashes_ok"]=(out["static_writer_sha256"]==EXPECTED_STATIC_SHA and out["free_mesh_core_sha256"]==EXPECTED_CORE_SHA)
    if not result_path.is_file():
        out["status"]="NO_RESULT"
        print(json.dumps(out,indent=2,ensure_ascii=False))
        return
    d=json.loads(result_path.read_text(encoding="utf-8"))
    r=d.get("result") if isinstance(d.get("result"),dict) else {}
    failed=r.get("failed_assets",[]) or []
    errors=[str(x.get("error","")) for x in failed if isinstance(x,dict)]
    out.update({
        "bootstrap_status":d.get("status"),
        "server_design_intercepted":d.get("server_design_intercepted"),
        "selected_row_count":d.get("selected_row_count"),
        "requested":r.get("requested"),
        "passed_count":len(r.get("passed_assets",[]) or []),
        "failed_count":len(failed),
        "legacy_float_tuple_count":sum("float() argument must be a string or a real number, not 'tuple'" in e for e in errors),
        "rc6_1_vec3_fail_count":sum("PT_RC6_1_VEC3_NORMALIZE_FAIL" in e for e in errors),
        "rc6_5_divergent_count":sum("PT_RC6_5_MULTI_VEC3_DIVERGENT" in e for e in errors),
        "equal_normals_count_mismatch_count":sum("equal_normals vertex-count mismatch" in e for e in errors),
        "failed_assets":[{"asset":x.get("asset"),"domain":x.get("domain"),"error_tail":str(x.get("error",""))[-1000:]} for x in failed[:20] if isinstance(x,dict)],
        "result_report":r.get("report"),
    })
    out["status"]="PASS" if out["hashes_ok"] and d.get("status")=="PASS" else "FAIL"
    print(json.dumps(out,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
