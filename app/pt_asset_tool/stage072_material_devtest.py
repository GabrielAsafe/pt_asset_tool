from __future__ import annotations
import json, pathlib
from typing import Any
from .blender_workspace import asset_workspace_name
from .stage072_material_writer import locate_stage_materials, rebuild_stage_material_fields, verify_stage_material_candidate

FORMAT="PT_STAGE072_MATERIAL_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT="PT_STAGE072_MATERIAL_AUTOMATED_DEVTEST_BATCH_V1"

def run_stage072_material_automated_devtest(settings, registry, resolver, row: dict[str,Any]) -> dict[str,Any]:
    root=pathlib.Path(settings.project_root).resolve(); asset=registry.resolve(row['asset'])
    source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve(); before=source.read_bytes()
    layout=locate_stage_materials(before)
    if not layout['materials']: raise RuntimeError(f"Stage0.72 representative has no materials: {asset.primary_path}")
    material=next((x for x in layout['materials'] if x.get('in_use')),layout['materials'][0]); idx=int(material['index'])
    old=int((material.get('values') or {}).get('two_side') or 0); new=0 if old==1 else 1; edits={'two_side':new}
    rebuilt,writer=rebuild_stage_material_fields(before,material_index=idx,edits=edits)
    work=root/'pt_build'/'devtest'/'release_1_auto'/'stage072_materials'/asset_workspace_name(asset.primary_path); work.mkdir(parents=True,exist_ok=True)
    artifact=work/pathlib.PurePosixPath(asset.primary_path).name; artifact.write_bytes(rebuilt)
    verify=verify_stage_material_candidate(before,rebuilt,material_index=idx,edits=edits)
    result={'format':FORMAT,'status':'PASS' if writer.get('status')=='PASS' and verify.get('status')=='PASS' else 'FAIL','asset':asset.primary_path,'material_index':idx,'edit':{'field':'two_side','before':old,'after':new},'artifact':str(artifact),'writer':writer,'verification':verify,'candidate_only':True,'production_authorized':False,'client_write_authorized':False,'client_modified':False}
    report=work/'result.json'; result['report']=str(report); report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return result

def run_stage072_material_automated_devtest_batch(settings,registry,resolver,rows):
    results=[]; passed=[]; failed=[]
    for row in rows:
        try: result=run_stage072_material_automated_devtest(settings,registry,resolver,row)
        except Exception as exc: result={'format':FORMAT,'status':'FAIL','asset':row.get('asset'),'errors':[f'{type(exc).__name__}: {exc}'],'production_authorized':False,'client_write_authorized':False,'client_modified':False}
        results.append(result)
        if result.get('status')=='PASS': passed.append(str(row.get('asset')))
        else: failed.append({'asset':row.get('asset'),'errors':result.get('errors') or (result.get('verification') or {}).get('errors')})
    status='PASS' if rows and not failed and len(passed)==len(rows) else ('EMPTY' if not rows else 'FAIL')
    root=pathlib.Path(settings.project_root).resolve(); out=root/'pt_build'/'devtest'/'release_1_auto'/'stage072_materials'/'batch_result.json'; out.parent.mkdir(parents=True,exist_ok=True)
    payload={'format':BATCH_FORMAT,'status':status,'requested':len(rows),'passed_assets':passed,'failed_assets':failed,'results':results,'automatic_only':True,'production_authorized':False,'client_write_authorized':False,'client_modified':False,'report':str(out)}; out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return payload


CORPUS_FORMAT="PT_STAGE072_MATERIAL_PHYSICAL_CORPUS_AUDIT_V1"

def audit_stage072_material_physical_corpus(registry,resolver):
    """Parse the material layout of every physical Stage0.72 map read-only.

    Representative tests prove allowlisted edits; this corpus gate proves that
    the material locator closes on every shipped Stage0.72 container.
    """
    from .release_1_coverage import CONTENT_DOMAINS, content_domain
    rows=[]; failures=[]; by_domain={d:{"asset_count":0,"material_count":0,"fail_count":0} for d in CONTENT_DOMAINS}
    for asset in registry.assets:
        if str(asset.family or "") != "STAGE_072_MAP_SEPARATE":
            continue
        domain=content_domain(asset)
        if domain not in by_domain:
            continue
        by_domain[domain]["asset_count"] += 1
        try:
            source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
            layout=locate_stage_materials(source.read_bytes())
            parsed=int(layout.get("material_count") or 0)
            expected=int(getattr(asset,"material_count",0) or 0)
            if expected and parsed != expected:
                raise RuntimeError(f"material count mismatch inventory={expected} parsed={parsed}")
            by_domain[domain]["material_count"] += parsed
            rows.append({"asset":asset.primary_path,"domain":domain,"status":"PASS","material_count":parsed})
        except Exception as exc:
            by_domain[domain]["fail_count"] += 1
            row={"asset":asset.primary_path,"domain":domain,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
            rows.append(row); failures.append(row)
    pass_domains=[]
    for domain,row in by_domain.items():
        count=int(row.get("asset_count") or 0); fail=int(row.get("fail_count") or 0)
        row["status"]="PASS" if count and not fail else ("NOT_PRESENT" if not count else "FAIL")
        if row["status"]=="PASS": pass_domains.append(domain)
    return {
        "format":CORPUS_FORMAT,
        "status":"PASS" if rows and not failures else ("EMPTY" if not rows else "FAIL"),
        "asset_count":len(rows),"failure_count":len(failures),
        "pass_domains":sorted(pass_domains),"by_domain":by_domain,
        "failures":failures,"rows":rows,
        "production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
