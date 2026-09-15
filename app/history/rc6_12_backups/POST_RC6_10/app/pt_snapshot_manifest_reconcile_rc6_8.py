#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

FORMAT="PT_RC6_8_ACTIVE_SNAPSHOT_MANIFEST_RECONCILE_V1"
ALLOWED=(
 "app/pt_blender_to_smd_static_v1.py",
 "app/pt_asset_tool/static_roundtrip.py",
 "app/pt_asset_tool/model062_corpus.py",
 "app/data/asset_registry/asset_inventory.json",
)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--current-root"); a=ap.parse_args()
    root=Path(a.current_root).resolve()
    manifest=root/"SNAPSHOT_SHA256SUMS.txt"
    if not manifest.is_file(): raise SystemExit("manifest_reconcile_error=no manifest")
    base=root/"history/manifests/SNAPSHOT_SHA256SUMS.base_0.13.0.txt"
    base.parent.mkdir(parents=True,exist_ok=True)
    if not base.exists(): shutil.copy2(manifest,base)
    lines=manifest.read_text(encoding="utf-8").splitlines()
    rows=[]
    out=[]
    allowed=set(ALLOWED)
    for line in lines:
        parts=line.split("  ",1)
        if len(parts)!=2:
            out.append(line); continue
        old,rel=parts
        p=root/rel
        if not p.is_file():
            out.append(line); continue
        actual=sha(p)
        if actual!=old and rel not in allowed:
            raise RuntimeError(f"unapproved manifest mismatch: {rel} expected={old} actual={actual}")
        if rel in allowed:
            out.append(f"{actual}  {rel}")
            rows.append({"path":rel,"before":old,"after":actual,"changed":old!=actual})
        else:
            out.append(line)
    manifest.write_text("\n".join(out)+"\n",encoding="utf-8")
    state=root/"evidence/active_patch_state.json"
    state.parent.mkdir(parents=True,exist_ok=True)
    payload={"format":FORMAT,"status":"PASS","base_manifest":str(base.relative_to(root)),
             "managed_files":rows,"production_authorized":False,
             "client_write_authorized":False,"server_write_authorized":False}
    state.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(payload,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
