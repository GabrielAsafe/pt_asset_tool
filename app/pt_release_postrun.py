#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from collections import Counter
from pathlib import Path
import pt_release_triage_v3 as triage_mod

FORMAT="PT_RC6_POSTRUN_SUMMARY_V1"
KEY_GATES=(
    "model062_physical_corpus","rigid_context_census","rigid_lod_context_corpus",
    "model062_rigid","model062_rigid_standalone","model062_static","model062_static_corpus",
    "animation_pose_space","model062_texture_presence","proprietary_texture_corpus","motion_semantic_edit",
)

def _gate(data,name):
    g=data.get("gates",{}).get(name)
    if isinstance(g,dict): return g
    s=data.get("summary",{}).get(name)
    return s if isinstance(s,dict) else {}

def _errkey(e): return triage_mod.errkey(e)

def _motion_rows(data):
    return list((_gate(data,"motion_semantic_edit") or {}).get("rows") or [])

def summarize(data:dict, log_text:str="", baseline_triage:dict|None=None):
    tri=triage_mod.triage(data)
    static_gate=_gate(data,"model062_static")
    static_errors=Counter(_errkey(x.get("error")) for x in static_gate.get("failed_assets",[]))
    motion=tri.get("motion",{})
    elapsed=[float(r.get("elapsed_seconds") or 0) for r in _motion_rows(data)]
    if not elapsed and log_text:
        elapsed=[float(x) for x in re.findall(r"MOTION_SEMANTIC .*? elapsed=([0-9.]+)s",log_text)]
    statuses={k:_gate(data,k).get("status") for k in KEY_GATES}
    result={
        "format":FORMAT,
        "release_status":data.get("status"),
        "automatic_gate_status":data.get("automatic_gate_status"),
        "key_gate_statuses":statuses,
        "static":{
            "status":static_gate.get("status"),
            "requested":static_gate.get("requested"),
            "passed_count":len(static_gate.get("passed_assets",[]) or []),
            "failed_count":len(static_gate.get("failed_assets",[]) or []),
            "error_counts":dict(static_errors),
            "legacy_float_tuple_count":static_errors.get("STATIC_FLOAT_TUPLE",0),
            "vec3_normalize_fail_count":static_errors.get("STATIC_VEC3_NORMALIZE_FAIL",0),
        },
        "motion":{
            **motion,
            "over_130_seconds":sum(x>130 for x in elapsed),
            "over_200_seconds":sum(x>200 for x in elapsed),
            "max_elapsed_seconds_from_result_or_log":max(elapsed,default=motion.get("max_elapsed_seconds",0) or 0),
        },
        "model062_physical":tri.get("model062_physical"),
        "rigid_context_census":tri.get("rigid_context_census"),
        "texture_presence":tri.get("texture_presence"),
        "integrity":{
            "production_authorized":bool(data.get("production_authorized",False)),
            "client_write_authorized":bool(data.get("client_write_authorized",False)),
            "server_write_authorized":bool(data.get("server_write_authorized",False)),
            "client_modified":data.get("client_modified", data.get("environment",{}).get("client_modified")),
        },
    }
    result["rc6_1_2_targets"]={
        "static_legacy_float_tuple_closed":result["static"]["legacy_float_tuple_count"]==0,
        "motion_contexts_over_200_closed":result["motion"]["over_200_seconds"]==0,
        "motion_contexts_over_130_closed":result["motion"]["over_130_seconds"]==0,
    }
    if baseline_triage:
        b_m=baseline_triage.get("motion",{}); b_m62=baseline_triage.get("model062_physical",{})
        result["delta_vs_baseline"]={
            "motion_failure_context_delta":int(result["motion"].get("failure_context_count",0) or 0)-int(b_m.get("failure_context_count",0) or 0),
            "motion_over_200_delta":int(result["motion"].get("over_200_seconds",0) or 0)-int(b_m.get("over_200_seconds",0) or 0),
            "model062_count_layout_delta":int((result["model062_physical"].get("counts") or {}).get("COUNT_LAYOUT_MISMATCH",0))-int((b_m62.get("counts") or {}).get("COUNT_LAYOUT_MISMATCH",0)),
            "model062_bad_texlink_delta":int((result["model062_physical"].get("counts") or {}).get("BAD_TEXLINK_POINTER",0))-int((b_m62.get("counts") or {}).get("BAD_TEXLINK_POINTER",0)),
        }
    return result

def main():
    ap=argparse.ArgumentParser(description="Summarize RC6 physical release output without pasting the giant JSON")
    ap.add_argument("--result",default="pt_build/devtest/release_1_auto/result.json")
    ap.add_argument("--log",default="pt_build/devtest/rc6_1_2_release.log")
    ap.add_argument("--baseline-triage")
    ap.add_argument("--out",default="pt_build/devtest/rc6_postrun_summary.json")
    a=ap.parse_args(); result_path=Path(a.result)
    data=json.loads(result_path.read_text(encoding="utf-8")); log_text=Path(a.log).read_text(encoding="utf-8",errors="replace") if Path(a.log).is_file() else ""
    baseline=json.loads(Path(a.baseline_triage).read_text(encoding="utf-8")) if a.baseline_triage and Path(a.baseline_triage).is_file() else None
    out=summarize(data,log_text,baseline); op=Path(a.out); op.parent.mkdir(parents=True,exist_ok=True); op.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
