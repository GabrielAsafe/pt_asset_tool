#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile
from pathlib import Path
from typing import Any

FORMAT="PT_RC6_8_MODEL062_INVENTORY_DRIFT_REFRESH_V1"
PHYSICAL_FIELDS=(
    "size","sample_digest","structural_valid","objects","object_count","material_count",
    "total_vertices","total_faces","total_texlinks","physique_objects","texture_refs",
    "issues","mat_file_point","first_obj_info_point","tmframe_count","object_names","name_shape",
    "sha256",
)

def sha_bytes(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def _layout_error(s:str)->bool:
    return any(x in str(s) for x in ("OBJECT_COUNT:","VERTEX_COUNT:","FACE_COUNT:","TEXLINK_COUNT:"))

def _sig(r:dict[str,Any])->str:
    payload={k:r.get(k) for k in PHYSICAL_FIELDS if k not in {"sample_digest"}}
    return json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(",",":"))

def _update_manifest(root:Path, rel:str, new_sha:str)->dict[str,str]:
    manifest=root/"SNAPSHOT_SHA256SUMS.txt"
    if not manifest.is_file():
        return {"status":"NO_MANIFEST","path":rel}
    lines=manifest.read_text(encoding="utf-8").splitlines()
    hit=0
    out=[]
    for line in lines:
        parts=line.split("  ",1)
        if len(parts)==2 and parts[1]==rel:
            out.append(f"{new_sha}  {rel}"); hit+=1
        else:
            out.append(line)
    if hit!=1:
        raise RuntimeError(f"manifest entry count for {rel} is {hit}, expected 1")
    manifest.write_text("\n".join(out)+"\n",encoding="utf-8")
    return {"status":"UPDATED","path":rel,"sha256":new_sha}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    a=ap.parse_args()
    app=Path(a.app_root).expanduser().resolve()
    client=Path(a.client_root).expanduser().resolve()
    invp=app/"data/asset_registry/asset_inventory.json"
    prior=app/"pt_build/devtest/rc6_7_model062_physical/result.json"
    report={"format":FORMAT,"app_root":str(app),"client_root":str(client),
            "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    if not invp.is_file() or not prior.is_file():
        raise SystemExit("refresh_error=missing inventory or RC6.7 result")
    inv=json.loads(invp.read_text(encoding="utf-8"))
    records=inv.get("records") if isinstance(inv,dict) else None
    if not isinstance(records,list):
        raise SystemExit("refresh_error=bad inventory format")
    r7=json.loads(prior.read_text(encoding="utf-8"))
    targets=[]
    for row in r7.get("rows") or []:
        if row.get("status")=="FAIL" and _layout_error(row.get("error","")):
            targets.append(str(row.get("asset") or ""))
    targets=sorted(set(x for x in targets if x),key=str.lower)
    report["targets"]=targets
    changes=[]
    for rel in targets:
        live=client/Path(rel)
        if not live.is_file():
            raise RuntimeError(f"physical client asset missing: {rel}")
        live_sha=sha_file(live)
        canon=[r for r in records if str(r.get("relative_path") or "").casefold()==rel.casefold()
               and str(r.get("path") or "").replace("\\","/").casefold().startswith(str(client).replace("\\","/").rstrip("/").casefold()+"/")]
        if len(canon)!=1:
            raise RuntimeError(f"canonical inventory record count for {rel}={len(canon)}")
        cur=canon[0]
        before_sha=str(cur.get("sha256") or "").lower()
        if before_sha==live_sha:
            changes.append({"asset":rel,"status":"ALREADY_CURRENT","sha256":live_sha})
            continue
        donors=[r for r in records if str(r.get("sha256") or "").lower()==live_sha
                and str(r.get("kind") or "")==str(cur.get("kind") or "")
                and str(r.get("basename") or "").casefold()==str(cur.get("basename") or "").casefold()]
        if not donors:
            raise RuntimeError(f"no known byte-identical inventory donor for {rel} live_sha={live_sha}")
        sigs={_sig(r) for r in donors}
        if len(sigs)!=1:
            raise RuntimeError(f"non-unanimous physical metadata for byte-identical donors of {rel}: {len(sigs)} signatures")
        donor=donors[0]
        old={k:cur.get(k) for k in PHYSICAL_FIELDS}
        for k in PHYSICAL_FIELDS:
            if k in donor:
                cur[k]=donor.get(k)
        changes.append({
            "asset":rel,"status":"REFRESHED_FROM_BYTE_IDENTICAL_CONSENSUS",
            "before_sha256":before_sha,"after_sha256":live_sha,
            "donor_count":len(donors),
            "before_counts":{"objects":old.get("object_count"),"vertices":old.get("total_vertices"),
                             "faces":old.get("total_faces"),"texlinks":old.get("total_texlinks")},
            "after_counts":{"objects":cur.get("object_count"),"vertices":cur.get("total_vertices"),
                            "faces":cur.get("total_faces"),"texlinks":cur.get("total_texlinks")},
        })

    if any(x["status"]=="REFRESHED_FROM_BYTE_IDENTICAL_CONSENSUS" for x in changes):
        backup=app/"history/data_backups/asset_inventory.json.pre_rc6_8"
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():
            shutil.copy2(invp,backup)
        text=json.dumps(inv,indent=2,ensure_ascii=False)+"\n"
        fd,tmp=tempfile.mkstemp(prefix="asset_inventory.",suffix=".tmp",dir=str(invp.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                f.write(text); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,invp)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        report["backup"]=str(backup)

    new_inv_sha=sha_file(invp)
    report["changes"]=changes
    report["inventory_sha256"]=new_inv_sha
    root=app.parent
    report["manifest"]=_update_manifest(root,"app/data/asset_registry/asset_inventory.json",new_inv_sha)
    out=app/"pt_build/devtest/rc6_8_inventory_refresh.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    report["status"]="PASS"
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
