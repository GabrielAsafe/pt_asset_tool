#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

SR_EXPECTED="219140c4e5908a7e637f79eafb0f92d1dd185651990f7229c7b773d8f72d2400"
MC_EXPECTED="89d885c57eab6439cdfff623f072fa5220dd223df5406ae844cac06772817c0d"
STATIC_EXPECTED="f01673a6c9f04a7b3b407edc9c2d7fead0ea2e7dc2e6d4d5086f5fd6cf68a388"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def classify(error:str)->str:
    e=str(error)
    if any(x in e for x in ("bad tex ptr","tex ptr OOB","next tex ptr invalid","texlink cycle")):
        return "BAD_TEXLINK_POINTER"
    if any(x in e for x in ("OBJECT_COUNT:","VERTEX_COUNT:","FACE_COUNT:","TEXLINK_COUNT:")):
        return "COUNT_LAYOUT_MISMATCH"
    return "OTHER"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args()
    app=Path(a.app_root).resolve()
    p=app/"pt_build/devtest/rc6_7_model062_physical/result.json"
    static_batch=app/"pt_build/devtest/static_semantic_auto/batch_result.json"
    out={
      "format":"PT_RC6_7_VERIFY_V1",
      "static_roundtrip_sha256":sha(app/"pt_asset_tool/static_roundtrip.py"),
      "model062_corpus_sha256":sha(app/"pt_asset_tool/model062_corpus.py"),
      "static_writer_sha256":sha(app/"pt_blender_to_smd_static_v1.py"),
      "hashes_ok":(
        sha(app/"pt_asset_tool/static_roundtrip.py")==SR_EXPECTED and
        sha(app/"pt_asset_tool/model062_corpus.py")==MC_EXPECTED and
        sha(app/"pt_blender_to_smd_static_v1.py")==STATIC_EXPECTED
      ),
      "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,
    }
    if static_batch.is_file():
        sb=json.loads(static_batch.read_text(encoding="utf-8"))
        out["static_rc6_6"]={
          "status":sb.get("status"),"requested":sb.get("requested"),
          "passed_count":len(sb.get("passed_assets",[]) or []),
          "failed_count":len(sb.get("failed_assets",[]) or []),
        }
    if not p.is_file():
        out["status"]="NO_RESULT"; print(json.dumps(out,indent=2,ensure_ascii=False)); return
    d=json.loads(p.read_text(encoding="utf-8"))
    failures=[r for r in d.get("rows",[]) or [] if r.get("status")=="FAIL"]
    counts=Counter(classify(r.get("error","")) for r in failures)
    by_domain={}
    for r in failures:
        dom=str(r.get("domain") or "UNKNOWN")
        by_domain.setdefault(dom,Counter())[classify(r.get("error",""))]+=1
    out.update({
      "corpus_status":d.get("status"),
      "asset_count":d.get("asset_count"),
      "failure_count":d.get("failure_count"),
      "duplicate_node_name_asset_count":d.get("duplicate_node_name_asset_count"),
      "failure_classes":dict(sorted(counts.items())),
      "failure_classes_by_domain":{k:dict(sorted(v.items())) for k,v in sorted(by_domain.items())},
      "failure_sample":failures[:30],
      "count_layout_closed":int(counts.get("COUNT_LAYOUT_MISMATCH",0))==0,
      "static_closed":(out.get("static_rc6_6") or {}).get("status")=="PASS" and (out.get("static_rc6_6") or {}).get("passed_count")==13,
    })
    out["status"]="PASS" if out["hashes_ok"] and out["count_layout_closed"] and out["static_closed"] else "FAIL"
    print(json.dumps(out,indent=2,ensure_ascii=False))

if __name__=="__main__": main()
