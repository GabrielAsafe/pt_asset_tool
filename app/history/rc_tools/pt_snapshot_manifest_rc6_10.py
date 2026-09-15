#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
REL="app/pt_asset_tool/standalone_rigid_devtest.py"; BEFORE="9913140035b62d1c6119d640d6138aab3b02d7a1eb1f399a76db605d492f4dd8"; AFTER="335436350eb2c7163baa9d78dfb6b03dc2fe0794cee2e36986df037dd13c3ea6"
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--current-root",required=True); a=ap.parse_args(); root=Path(a.current_root).resolve(); mf=root/"SNAPSHOT_SHA256SUMS.txt"
 lines=mf.read_text(encoding="utf-8").splitlines(); out=[]; hit=0
 for line in lines:
  parts=line.split("  ",1)
  if len(parts)==2 and parts[1]==REL:
   hit+=1
   if parts[0] not in (BEFORE,AFTER): raise RuntimeError(f"unexpected manifest preimage {parts[0]}")
   actual=sha(root/REL)
   if actual!=AFTER: raise RuntimeError(f"target file sha {actual} != {AFTER}")
   out.append(f"{actual}  {REL}")
  else: out.append(line)
 if hit!=1: raise RuntimeError(f"manifest target count={hit}")
 mf.write_text("\n".join(out)+"\n",encoding="utf-8")
 r={"format":"PT_RC6_10_MANIFEST_UPDATE_V1","status":"PASS","path":REL,"sha256":AFTER}
 print(json.dumps(r,indent=2))
if __name__=="__main__": main()
