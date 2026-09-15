#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
FORMAT="PT_RC6_9_ACTIVE_MANIFEST_V1"
MUTABLE=("app/certifications/assets.jsonl",)
MANAGED=("VERIFY_PACKAGE.sh","app/pt_blender_to_smd_static_v1.py","app/pt_asset_tool/static_roundtrip.py","app/pt_asset_tool/model062_corpus.py","app/data/asset_registry/asset_inventory.json","SNAPSHOT_MUTABLE_PATHS.txt")
def sha(p):
    h=hashlib.sha256(); f=Path(p).open("rb")
    with f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--current-root",required=True); a=ap.parse_args(); root=Path(a.current_root).resolve(); manifest=root/"SNAPSHOT_SHA256SUMS.txt"
    if not manifest.is_file(): raise SystemExit("manifest_error=missing")
    baseline=root/"history/manifests/SNAPSHOT_SHA256SUMS.base_0.13.0.txt"; baseline.parent.mkdir(parents=True,exist_ok=True)
    if not baseline.exists(): shutil.copy2(manifest,baseline)
    mutable_file=root/"SNAPSHOT_MUTABLE_PATHS.txt"; mutable_file.write_text("\n".join(MUTABLE)+"\n",encoding="utf-8")
    entries=[]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts=line.split("  ",1)
        if len(parts)==2: entries.append([parts[0],parts[1]])
    out=[]; rows=[]; found=set()
    for expected,rel in entries:
        if rel in MUTABLE:
            rows.append({"path":rel,"action":"REMOVED_FROM_IMMUTABLE_MANIFEST","before":expected,"actual":sha(root/rel) if (root/rel).is_file() else None}); continue
        p=root/rel
        if not p.is_file(): raise RuntimeError(f"manifest file missing: {rel}")
        actual=sha(p); found.add(rel)
        if actual!=expected and rel not in MANAGED:
            raise RuntimeError(f"unapproved manifest mismatch: {rel} expected={expected} actual={actual}")
        out.append([actual if rel in MANAGED else expected,rel])
        if rel in MANAGED: rows.append({"path":rel,"action":"RECONCILED","before":expected,"after":actual,"changed":actual!=expected})
    if "SNAPSHOT_MUTABLE_PATHS.txt" not in found:
        out.append([sha(mutable_file),"SNAPSHOT_MUTABLE_PATHS.txt"]); rows.append({"path":"SNAPSHOT_MUTABLE_PATHS.txt","action":"ADDED","after":sha(mutable_file)})
    out.sort(key=lambda x:x[1])
    manifest.write_text("\n".join(f"{h}  {rel}" for h,rel in out)+"\n",encoding="utf-8")
    report={"format":FORMAT,"status":"PASS","base_manifest":str(baseline.relative_to(root)),"mutable_paths":list(MUTABLE),"changes":rows,"production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    state=root/"evidence/active_patch_state.json"; state.parent.mkdir(parents=True,exist_ok=True); state.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
