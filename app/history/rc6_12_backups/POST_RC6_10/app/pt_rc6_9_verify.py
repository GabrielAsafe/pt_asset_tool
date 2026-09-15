#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args(); app=Path(a.app_root).resolve(); root=app.parent
    delta=app/"pt_build/devtest/rc6_9_model062_delta/result.json"; refresh=app/"pt_build/devtest/rc6_9_inventory_refresh.json"
    out={"format":"PT_RC6_9_VERIFY_V1","production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    if refresh.is_file(): out["inventory_refresh"]=json.loads(refresh.read_text(encoding="utf-8"))
    if delta.is_file(): out["model062_delta"]=json.loads(delta.read_text(encoding="utf-8"))
    proc=subprocess.run([str(root/"VERIFY_PACKAGE.sh")],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    out["package_verify_rc"]=proc.returncode; out["package_verify_output"]=proc.stdout.strip()[-2000:]
    d=out.get("model062_delta") or {}
    out["model062_effective_closed"]=d.get("status")=="PASS" and d.get("effective_failure_count")==0 and d.get("effective_asset_count")==3144
    out["package_verify_pass"]=proc.returncode==0 and "PACKAGE_VERIFY=PASS" in proc.stdout
    out["status"]="PASS" if out["model062_effective_closed"] and out["package_verify_pass"] else "FAIL"
    print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
