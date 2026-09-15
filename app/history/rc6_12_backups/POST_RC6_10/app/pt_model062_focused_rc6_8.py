#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from pt_asset_tool.config import Settings
from pt_asset_tool.resolver import ClientResolver
from pt_asset_tool.registry import AssetRegistry
from pt_asset_tool.model062_corpus import audit_model062_physical_corpus

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    a=ap.parse_args()
    app=Path(a.app_root).expanduser().resolve()
    client=Path(a.client_root).expanduser().resolve()
    settings=Settings.discover(app,client)
    resolver=ClientResolver(client)
    registry=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    result=audit_model062_physical_corpus(registry,resolver,sample_limit=500)
    out=app/"pt_build/devtest/rc6_8_model062_physical/result.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
    print(json.dumps({
      "format":"PT_RC6_8_MODEL062_FOCUSED_RUN_V1",
      "status":result.get("status"),"asset_count":result.get("asset_count"),
      "failure_count":result.get("failure_count"),
      "duplicate_node_name_asset_count":result.get("duplicate_node_name_asset_count"),
      "pass_domains":result.get("pass_domains"),"report":str(out),
      "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,
    },indent=2,ensure_ascii=False))

if __name__=="__main__": main()
