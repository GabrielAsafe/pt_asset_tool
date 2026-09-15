#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import pt_effect_preview as preview

FORMAT="PT_EFFECT_PREVIEW_VERIFY_V2"

def _under(root:Path,p:Path):
    try: p.resolve().relative_to(root.resolve()); return True
    except Exception: return False

def verify(client_root: Path, build_root: Path, plan_path: Path, report_path: Path|None=None):
    plan=json.loads(plan_path.read_text(encoding="utf-8")); base=preview.verify_plan(client_root,build_root,plan); errors=list(base.get("errors",[])); report=None; renders=[]
    br=build_root.resolve(); pt_build_root=br.parent if br.parent.name == "pt_build" else br
    if report_path is not None:
        if not report_path.is_file(): errors.append("REPORT_MISSING")
        else:
            try: report=json.loads(report_path.read_text(encoding="utf-8"))
            except Exception: errors.append("REPORT_JSON_INVALID")
        if isinstance(report,dict):
            if report.get("format") != preview.RESULT_FORMAT: errors.append("REPORT_FORMAT")
            if report.get("status") != "PASS": errors.append("REPORT_STATUS")
            if report.get("asset") != plan.get("asset"): errors.append("REPORT_ASSET")
            if report.get("source_payload_sha256") != plan.get("source_payload_sha256"): errors.append("REPORT_SOURCE_SHA")
            if report.get("plan_content_sha256") != plan.get("plan_content_sha256"): errors.append("REPORT_PLAN_SHA")
            blend=Path(str(report.get("blend") or ""))
            if not blend.is_file(): errors.append("BLEND_MISSING")
            elif not _under(pt_build_root,blend): errors.append("BLEND_OUTSIDE_BUILD_ROOT")
            for item in report.get("render_files") or []:
                rp=Path(str(item)); renders.append(str(rp))
                if rp.suffix.lower() != ".png": errors.append("RENDER_NOT_PNG")
                elif not rp.is_file(): errors.append("RENDER_MISSING")
                elif not _under(pt_build_root,rp): errors.append("RENDER_OUTSIDE_BUILD_ROOT")
            if not renders: errors.append("NO_RENDER_PREVIEWS")
            if int(report.get("created_sprite_objects") or 0) < 1: errors.append("NO_SPRITES_CREATED")
    return {"format":FORMAT,"status":"PASS" if not errors else "FAIL","asset":plan.get("asset"),"errors":errors,"plan":str(plan_path),"report":str(report_path) if report_path else None,"render_files":renders,"preview_certification":"BLENDER_PREVIEW_APPROXIMATE","production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--client-root",required=True); ap.add_argument("--build-root",default="pt_build/devtest"); ap.add_argument("--plan",required=True); ap.add_argument("--report")
    a=ap.parse_args(); r=verify(Path(a.client_root),Path(a.build_root),Path(a.plan),Path(a.report) if a.report else None); print(json.dumps(r,ensure_ascii=False,indent=2)); raise SystemExit(0 if r["status"]=="PASS" else 1)
if __name__=="__main__": main()
