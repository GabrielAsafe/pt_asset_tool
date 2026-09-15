#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path

def classify_error(err: str) -> str:
    err = err or ""
    if "float() argument must be a string or a real number, not 'tuple'" in err:
        return "STATIC_NESTED_VEC3_WRITER_BUG"
    if "rc=-15" in err or "operation exceeded 120s" in err:
        return "TIMEOUT_OR_HANG"
    if "duplicate skeleton NodeName" in err:
        return "DUPLICATE_SKELETON_CONFLICT_FAIL_CLOSED"
    if "source normal is zero in legacy-degenerate fallback" in err:
        return "ZERO_SOURCE_NORMAL_LEGACY_DEGENERATE"
    if "OBJECT_COUNT" in err and ("VERTEX_COUNT" in err or "FACE_COUNT" in err):
        return "MODEL062_COUNT_MISMATCH"
    if "bad tex ptr face" in err:
        return "MODEL062_BAD_TEX_PTR"
    if "missing texture" in err:
        return "MISSING_TEXTURE_REFERENCE"
    if "TextureCounter/AnimTexCounter" in err:
        return "MODEL062_MATERIAL_STRING_SCOPE"
    if "protected TGA header/container unresolved/ambiguous" in err:
        return "PROPRIETARY_TGA_UNRESOLVED"
    if "cannot unpack non-iterable NoneType" in err:
        return "MOTION_NONE_UNPACK"
    if "container_end=0" in err:
        return "MOTION_ZERO_CONTAINER_END"
    if "engine_end=" in err and "container_end=" in err:
        return "MOTION_ENGINE_END_OUTSIDE_CONTAINER"
    if "singular matrix" in err:
        return "MOTION_SINGULAR_MATRIX"
    if "missing parent" in err:
        return "MOTION_MISSING_PARENT"
    return "OTHER"

def collect_gate_failures(name, gate):
    rows=[]
    if isinstance(gate.get("failed_assets"), list):
        for r in gate["failed_assets"]:
            rows.append({"gate":name, **r})
    vals=gate.get("rows")
    if isinstance(vals,list) and name!="motion_semantic_edit":
        for r in vals:
            if r.get("status")=="FAIL":
                rows.append({"gate":name, **r})
    if not rows and isinstance(gate.get("failure_sample"),list):
        for r in gate["failure_sample"]:
            rows.append({"gate":name, **r})
    if name=="motion_semantic_edit":
        rows=[]
        for r in gate.get("rows",[]):
            for writer in ("inx_edit","smb_edit"):
                d=r.get(writer) or {}
                if d.get("status") in {"FAIL","TIMEOUT"}:
                    rows.append({
                        "gate":name, "writer":writer,
                        "asset":r.get("motion_inx"),
                        "motion_smb":r.get("motion_smb"),
                        "error":d.get("error",""),
                    })
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("result_json")
    ap.add_argument("--out",default="")
    args=ap.parse_args()
    data=json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    gates=data.get("gates",{})
    failed=[k for k,v in gates.items() if isinstance(v,dict) and v.get("status")=="FAIL"]
    groups=Counter()
    examples={}
    for name in failed:
        for r in collect_gate_failures(name,gates[name]):
            cls=classify_error(str(r.get("error","")))
            groups[(name,cls)]+=1
            examples.setdefault((name,cls),r)
    report={
        "format":"PT_RELEASE_TRIAGE_V2",
        "source_status":data.get("status"),
        "failed_gates":failed,
        "grouped_failures":[
            {"gate":g,"classification":c,"count":n,"example":examples[(g,c)]}
            for (g,c),n in groups.most_common()
        ],
        "external_gates_pending":data.get("external_gates_pending"),
        "runtime_game_acceptance_pending":data.get("runtime_game_acceptance_pending"),
        "production_authorized":False,
    }
    text=json.dumps(report,indent=2,ensure_ascii=False)
    print(text)
    if args.out:
        Path(args.out).write_text(text+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
