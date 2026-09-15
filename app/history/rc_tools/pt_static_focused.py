#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, importlib, inspect, json, os, sys
from pathlib import Path

FORMAT="PT_RC6_5_STATIC_FOCUSED_RUN_V1"
MARKER="PT_STATIC_SEMANTIC_AUTOMATED_DEVTEST_BATCH_V1"

def strings(node):
    return " ".join(x.value for x in ast.walk(node) if isinstance(x,ast.Constant) and isinstance(x.value,str))

def discover(app:Path):
    rows=[]
    for root in (app/"pt_asset_tool",app/"dev_tests"):
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                src=p.read_text(encoding="utf-8")
            except Exception:
                continue
            if MARKER not in src and "static_semantic_auto" not in src:
                continue
            try:
                tree=ast.parse(src)
            except Exception:
                continue
            for fn in ast.walk(tree):
                if isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    blob=strings(fn)
                    score=(100 if MARKER in blob else 0)
                    lname=fn.name.casefold()
                    score += 10*sum(t in lname for t in ("static","semantic","auto","batch"))
                    if score:
                        rows.append((score,p,fn.name))
    rows.sort(reverse=True,key=lambda x:x[0])
    return rows

def module_name(app:Path,p:Path):
    return ".".join(p.relative_to(app).with_suffix("").parts)

def build_kwargs(fn,app:Path,client:Path):
    sig=inspect.signature(fn); kw={}; unknown=[]
    output=app/"pt_build/devtest/rc6_5_static_focused"
    mapping={
      "client_root":client,"client_dir":client,"client_path":client,
      "app_root":app,"app_dir":app,"repo_root":app,
      "output_root":output,"out_root":output,"work_root":output,"workdir":output,
      "report_root":output,"devtest_root":output,
      "blender_timeout_seconds":120.0,"timeout_seconds":120.0,"operation_timeout_seconds":120.0,
      "resume":False,"automatic_only":True,"runtime_authorized":False,
      "production_authorized":False,"client_write_authorized":False,
    }
    for name,param in sig.parameters.items():
        if name in mapping:
            kw[name]=mapping[name]
        elif param.default is not inspect._empty:
            pass
        elif param.kind in (inspect.Parameter.VAR_POSITIONAL,inspect.Parameter.VAR_KEYWORD):
            pass
        else:
            unknown.append(name)
    return kw,unknown

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--app-root",default=".")
    ap.add_argument("--client-root",default=os.environ.get("CLIENT_ROOT","/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente"))
    ap.add_argument("--discover-only",action="store_true")
    a=ap.parse_args()
    app=Path(a.app_root).expanduser().resolve()
    client=Path(a.client_root).expanduser().resolve()
    report={"format":FORMAT,"app_root":str(app),"client_root":str(client),
            "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    candidates=discover(app)
    report["candidates"]=[{"score":s,"file":str(p),"function":fn} for s,p,fn in candidates[:10]]
    if not candidates:
        report["status"]="FAIL_DISCOVERY"
        print(json.dumps(report,indent=2,ensure_ascii=False))
        raise SystemExit(2)
    best=candidates[0]
    if len(candidates)>1 and candidates[1][0]==best[0]:
        report["status"]="FAIL_AMBIGUOUS"
        print(json.dumps(report,indent=2,ensure_ascii=False))
        raise SystemExit(2)
    score,path,name=best
    sys.path.insert(0,str(app))
    mod=importlib.import_module(module_name(app,path))
    fn=getattr(mod,name)
    kwargs,unknown=build_kwargs(fn,app,client)
    report["selected"]={"score":score,"module":mod.__name__,"function":name,
                        "signature":str(inspect.signature(fn)),
                        "kwargs":{k:str(v) if isinstance(v,Path) else v for k,v in kwargs.items()},
                        "unknown_required":unknown}
    if a.discover_only:
        report["status"]="DISCOVERY_PASS" if not unknown else "DISCOVERY_NEEDS_MAPPING"
        print(json.dumps(report,indent=2,ensure_ascii=False))
        if unknown:
            raise SystemExit(2)
        return
    if unknown:
        report["status"]="FAIL_UNKNOWN_REQUIRED_PARAMETERS"
        print(json.dumps(report,indent=2,ensure_ascii=False))
        raise SystemExit(2)
    result=fn(**kwargs)
    report["result"]=result
    report["status"]=result.get("status","UNKNOWN") if isinstance(result,dict) else "RETURNED_NON_DICT"
    out=app/"pt_build/devtest/rc6_5_static_focused/result.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False,default=str))
    if report["status"]!="PASS":
        raise SystemExit(3)

if __name__=="__main__":
    main()
