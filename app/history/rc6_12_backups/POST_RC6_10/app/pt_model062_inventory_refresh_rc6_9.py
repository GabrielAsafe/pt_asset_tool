#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile
from pathlib import Path
from typing import Any

FORMAT="PT_RC6_9_INVENTORY_DRIFT_DELTA_REFRESH_V1"
PHYSICAL_FIELDS=(
    "size","sample_digest","structural_valid","objects","object_count","material_count",
    "total_vertices","total_faces","total_texlinks","physique_objects","texture_refs","issues",
    "mat_file_point","first_obj_info_point","tmframe_count","object_names","name_shape","sha256",
)

def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def _sig(r:dict[str,Any])->str:
    payload={k:r.get(k) for k in PHYSICAL_FIELDS if k!="sample_digest"}
    return json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":"))

def select_consensus_donors(records:list[dict[str,Any]], canonical:dict[str,Any], live_sha:str)->list[dict[str,Any]]:
    donors=[r for r in records if str(r.get("sha256") or "").lower()==live_sha.lower()
            and str(r.get("kind") or "")==str(canonical.get("kind") or "")
            and str(r.get("basename") or "").casefold()==str(canonical.get("basename") or "").casefold()]
    if not donors:
        raise RuntimeError(f"no byte-identical donor for {canonical.get('relative_path')} sha={live_sha}")
    sigs={_sig(r) for r in donors}
    if len(sigs)!=1:
        raise RuntimeError(f"non-unanimous donor metadata for {canonical.get('relative_path')}: {len(sigs)} signatures")
    return donors

def apply_physical_metadata(canonical:dict[str,Any], donor:dict[str,Any])->None:
    for k in PHYSICAL_FIELDS:
        if k in donor:
            canonical[k]=donor.get(k)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    a=ap.parse_args(); app=Path(a.app_root).resolve(); client=Path(a.client_root).resolve()
    invp=app/"data/asset_registry/asset_inventory.json"
    prior=app/"pt_build/devtest/rc6_8_model062_physical/result.json"
    if not invp.is_file() or not prior.is_file(): raise SystemExit("rc6_9_refresh_error=missing inventory or rc6.8 result")
    inv=json.loads(invp.read_text(encoding="utf-8")); records=inv.get("records") or []
    r8=json.loads(prior.read_text(encoding="utf-8"))
    failures=[r for r in r8.get("rows") or [] if r.get("status")=="FAIL"]
    targets=[]
    for row in failures:
        err=str(row.get("error") or "")
        if "INVENTORY_SHA_DRIFT:" not in err: continue
        rel=str(row.get("asset") or "")
        live_logged=err.split("INVENTORY_SHA_DRIFT:",1)[1].split("!=",1)[1].split(";",1)[0].strip()
        targets.append((rel,live_logged))
    if not targets: raise RuntimeError("no RC6.8 inventory-drift target found")
    prefix=str(client).replace("\\","/").rstrip("/").casefold()+"/"
    changes=[]
    for rel,logged_live_sha in targets:
        live=client/Path(rel)
        if not live.is_file(): raise RuntimeError(f"physical asset missing: {rel}")
        actual_sha=sha_file(live)
        if actual_sha.lower()!=logged_live_sha.lower():
            raise RuntimeError(f"physical SHA changed since RC6.8 for {rel}: logged={logged_live_sha} actual={actual_sha}")
        canon=[r for r in records if str(r.get("relative_path") or "").casefold()==rel.casefold()
               and str(r.get("path") or "").replace("\\","/").casefold().startswith(prefix)]
        if len(canon)!=1: raise RuntimeError(f"canonical record count {rel}={len(canon)}")
        cur=canon[0]; before=str(cur.get("sha256") or "")
        if before.lower()==actual_sha.lower():
            changes.append({"asset":rel,"status":"ALREADY_CURRENT","sha256":actual_sha}); continue
        donors=select_consensus_donors(records,cur,actual_sha)
        before_counts={"objects":cur.get("object_count"),"vertices":cur.get("total_vertices"),"faces":cur.get("total_faces"),"texlinks":cur.get("total_texlinks")}
        apply_physical_metadata(cur,donors[0])
        changes.append({"asset":rel,"status":"REFRESHED_FROM_BYTE_IDENTICAL_CONSENSUS","before_sha256":before,
                        "after_sha256":actual_sha,"donor_count":len(donors),"before_counts":before_counts,
                        "after_counts":{"objects":cur.get("object_count"),"vertices":cur.get("total_vertices"),"faces":cur.get("total_faces"),"texlinks":cur.get("total_texlinks")}})
    backup=app/"history/data_backups/asset_inventory.json.pre_rc6_9"
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists(): shutil.copy2(invp,backup)
    text=json.dumps(inv,indent=2,ensure_ascii=False)+"\n"
    fd,tmp=tempfile.mkstemp(prefix="asset_inventory.",suffix=".tmp",dir=str(invp.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f: f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,invp)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    report={"format":FORMAT,"status":"PASS","targets":[x[0] for x in targets],"changes":changes,
            "inventory_sha256":sha_file(invp),"backup":str(backup),
            "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    out=app/"pt_build/devtest/rc6_9_inventory_refresh.json"; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
