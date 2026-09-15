#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path
SR_EXPECTED="4c2eec01766d63f014730625c7299ddbd0808b9f55130ec28cb710562078afc6"
MC_EXPECTED="3da0fe3bdafdb56ec5ca87e64ee08ad6e218ffafecbd55515a2820bbd1c33877"
STATIC_EXPECTED="f01673a6c9f04a7b3b407edc9c2d7fead0ea2e7dc2e6d4d5086f5fd6cf68a388"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def classify(error):
    e=str(error)
    if "INVENTORY_SHA_DRIFT:" in e: return "INVENTORY_SHA_DRIFT"
    if any(x in e for x in ("bad tex ptr","tex ptr OOB","next tex ptr invalid","texlink cycle")):
        return "BAD_TEXLINK_POINTER"
    if any(x in e for x in ("OBJECT_COUNT:","VERTEX_COUNT:","FACE_COUNT:","TEXLINK_COUNT:")):
        return "COUNT_LAYOUT_MISMATCH"
    return "OTHER"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default="."); a=ap.parse_args()
    app=Path(a.app_root).resolve()
    p=app/"pt_build/devtest/rc6_8_model062_physical/result.json"
    refresh=app/"pt_build/devtest/rc6_8_inventory_refresh.json"
    out={
      "format":"PT_RC6_8_VERIFY_V1",
      "static_roundtrip_sha256":sha(app/"pt_asset_tool/static_roundtrip.py"),
      "model062_corpus_sha256":sha(app/"pt_asset_tool/model062_corpus.py"),
      "static_writer_sha256":sha(app/"pt_blender_to_smd_static_v1.py"),
      "hashes_ok":sha(app/"pt_asset_tool/static_roundtrip.py")==SR_EXPECTED and
                  sha(app/"pt_asset_tool/model062_corpus.py")==MC_EXPECTED and
                  sha(app/"pt_blender_to_smd_static_v1.py")==STATIC_EXPECTED,
      "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,
    }
    if refresh.is_file(): out["inventory_refresh"]=json.loads(refresh.read_text(encoding="utf-8"))
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
      "corpus_status":d.get("status"),"asset_count":d.get("asset_count"),
      "failure_count":d.get("failure_count"),
      "duplicate_node_name_asset_count":d.get("duplicate_node_name_asset_count"),
      "failure_classes":dict(sorted(counts.items())),
      "failure_classes_by_domain":{k:dict(sorted(v.items())) for k,v in sorted(by_domain.items())},
      "failure_sample":failures[:50],
      "count_layout_closed":int(counts.get("COUNT_LAYOUT_MISMATCH",0))==0,
      "inventory_drift_closed":int(counts.get("INVENTORY_SHA_DRIFT",0))==0,
      "bad_texlink_closed":int(counts.get("BAD_TEXLINK_POINTER",0))==0,
    })
    out["status"]="PASS" if out["hashes_ok"] and out["count_layout_closed"] and out["inventory_drift_closed"] and out["bad_texlink_closed"] else "FAIL"
    print(json.dumps(out,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
