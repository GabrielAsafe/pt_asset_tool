#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
EXPECTED="335436350eb2c7163baa9d78dfb6b03dc2fe0794cee2e36986df037dd13c3ea6"
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args(); app=Path(a.app_root).resolve()
 p=app/"pt_build/devtest/rc6_10_rigid_context_delta/result.json"
 out={"format":"PT_RC6_10_VERIFY_V1","standalone_rigid_devtest_sha256":sha(app/"pt_asset_tool/standalone_rigid_devtest.py"),
      "expected_sha256":EXPECTED,"hash_ok":sha(app/"pt_asset_tool/standalone_rigid_devtest.py")==EXPECTED,
      "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
 if not p.is_file(): out["status"]="NO_RESULT"; print(json.dumps(out,indent=2,ensure_ascii=False)); return
 d=json.loads(p.read_text(encoding="utf-8")); out.update({k:d.get(k) for k in ("basis","rigid_asset_count","baseline_unresolved_count","target_count","promoted_count","target_failure_count","effective_unresolved_count","effective_unresolved_by_domain","census_rows_reused","target_rows_revalidated","remaining_unresolved")})
 out["status"]="PASS" if out["hash_ok"] and d.get("status")=="PASS" else "FAIL"
 print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
