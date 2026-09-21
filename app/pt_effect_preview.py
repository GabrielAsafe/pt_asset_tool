#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import signal
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pt_part_editor as part

FORMAT = "PT_EFFECT_PART_BLENDER_PREVIEW_PLAN_V3"
RESULT_FORMAT = "PT_EFFECT_PART_BLENDER_PREVIEW_RESULT_V3"
PLAN_SCHEMA = "effect-preview-v3"
SUPPORTED_KEYS = {
    "position", "delay", "lifetime", "loops", "emitrate", "numparticles",
    "texture", "gravity", "emitradius", "initial", "fade", "sourceblendmode",
    "particletype", "at",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha(obj: dict) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha(payload)


def _strip_comment(body: str) -> str:
    out=[]; quote=None; esc=False; i=0
    while i < len(body):
        ch=body[i]
        if quote:
            out.append(ch)
            if esc: esc=False
            elif ch == "\\": esc=True
            elif ch == quote: quote=None
            i += 1; continue
        if ch in {'"', "'"}:
            quote=ch; out.append(ch); i += 1; continue
        if body.startswith("//", i) or ch in {"#", ";"}:
            break
        out.append(ch); i += 1
    return "".join(out)


def _brace_delta(code: str) -> Tuple[int,int]:
    op=cl=0; quote=None; esc=False
    for ch in code:
        if quote:
            if esc: esc=False
            elif ch == "\\": esc=True
            elif ch == quote: quote=None
            continue
        if ch in {'"', "'"}: quote=ch; continue
        if ch == "{": op += 1
        elif ch == "}": cl += 1
    return op,cl


def _number_spec(raw: str) -> Optional[dict]:
    raw=raw.strip()
    nk=part.number_kind(raw)
    if nk:
        return {"kind":"FIXED", "value":float(raw), "source_kind":nk, "raw":raw}
    rr=part.parse_random(raw)
    if rr:
        a,b=(float(x) for x in rr["values"])
        return {
            "kind":"RANGE", "a":a, "b":b, "low":min(a,b), "high":max(a,b),
            "raw":raw,
        }
    return None


def _xyz_spec(raw: str) -> Optional[dict]:
    p=part.parse_xyz(raw)
    if not p: return None
    comps=[]
    for item in p["components"]:
        spec=_number_spec(item)
        if not spec: return None
        comps.append(spec)
    return {"kind":"XYZ3", "components":comps, "raw":raw}


def _rgba_spec(raw: str) -> Optional[dict]:
    p=part.parse_rgba(raw)
    if not p: return None
    vals=p["values"]
    return {
        "kind":"RGBA", "rgba255":vals,
        "rgba01":[round(v/255.0, 9) for v in vals], "raw":raw,
    }


def _assignment_spec(raw: str, fade: bool=False) -> Optional[dict]:
    parser=part.parse_fade if fade else part.parse_initial
    parsed=parser(raw)
    if not parsed: return None
    rx=part.FADE_RE if fade else part.INITIAL_RE
    m=rx.fullmatch(raw.strip())
    expr=m.group(2).strip()
    ek=parsed["expr_kind"]
    if ek == "XYZ3": value=_xyz_spec(expr)
    elif ek == "RGBA": value=_rgba_spec(expr)
    else: value=_number_spec(expr)
    if value is None: return None
    return {
        "kind":"FADE_ASSIGN" if fade else "INITIAL_ASSIGN",
        "field":parsed["canonical_field"], "field_spelling":parsed["field"],
        "expr_kind":ek, "value":value, "raw":raw,
    }


def semantic_spec(key: str, raw: str) -> Optional[dict]:
    k=key.casefold(); raw=raw.strip()
    if k in {"delay","lifetime","loops","emitrate","numparticles"}:
        return _number_spec(raw)
    if k == "at":
        return _number_spec(raw) or {"kind":"TOKEN", "value":raw, "raw":raw}
    if k in {"position","gravity","emitradius"}:
        return _xyz_spec(raw)
    if k == "initial": return _assignment_spec(raw, False)
    if k == "fade": return _assignment_spec(raw, True)
    if k == "texture":
        if len(raw)>=2 and raw[0] == raw[-1] and raw[0] in {'"',"'"}:
            return {"kind":"STRING", "value":raw[1:-1], "quote":raw[0], "raw":raw}
        return None
    if k in {"sourceblendmode","particletype"}:
        return {"kind":"TOKEN", "value":raw, "raw":raw}
    return None


class CasefoldResolver:
    """Resolve legacy case-insensitive client paths without rescanning the whole client."""
    def __init__(self, root: Path):
        self.root=root.resolve(); self._cache={}
    def _children(self, d: Path):
        key=str(d)
        if key not in self._cache:
            try:
                self._cache[key]={p.name.casefold():p for p in d.iterdir()}
            except OSError:
                self._cache[key]={}
        return self._cache[key]
    def resolve(self, legacy: str) -> Optional[Path]:
        norm=legacy.replace("\\","/").lstrip("/")
        parts=[x for x in norm.split("/") if x not in {"", "."}]
        if any(x == ".." for x in parts): return None
        cur=self.root
        for name in parts:
            exact=cur/name
            if exact.exists(): cur=exact; continue
            cur=self._children(cur).get(name.casefold())
            if cur is None: return None
        try: cur.resolve().relative_to(self.root)
        except Exception: return None
        return cur.resolve() if cur.exists() else None


def _resolve_texture(resolver: CasefoldResolver, raw_path: str) -> dict:
    p=resolver.resolve(raw_path)
    return {
        "legacy_path":raw_path,
        "resolved_path":str(p) if p else None,
        "exists":bool(p and p.is_file()),
    }


def _nearest_event(stack: List[dict]) -> Optional[dict]:
    for b in reversed(stack):
        if b["kind"] == "eventsequence": return b
    return None


def parse_effect_structure(data: bytes, *, client_root: Optional[Path]=None) -> dict:
    meta=part.inspect_bytes(data)
    lines=part.split_lines_keepends(data)
    resolver=CasefoldResolver(client_root) if client_root else None
    system={"header":None,"fields":[],"eventsequences":[]}
    stack=[]; warnings=[]; counts={}

    for lineno,line in enumerate(lines,1):
        body,_=part.line_body_eol(line)
        code=_strip_comment(body)
        stripped=code.strip()
        if not stripped: continue
        m=part.LINE_RE.match(code)
        key=m.group("key") if m else None
        val=m.group("value") if m else None
        canonical=key.casefold() if key else None
        op,cl=_brace_delta(code)

        if key and op>0 and canonical in {"particlesystem","eventsequence"}:
            new_block={
                "kind":canonical, "header_key":key, "header_value":val.strip(),
                "line":lineno, "fields":[],
            }
            if canonical == "particlesystem" and system["header"] is None:
                system["header"]={k:new_block[k] for k in ("header_key","header_value","line")}
            elif canonical == "eventsequence":
                system["eventsequences"].append(new_block)
            stack.append(new_block)
            op -= 1
        elif key:
            idx=counts.get(canonical,0); counts[canonical]=idx+1
            spec=semantic_spec(canonical,val)
            field={
                "key":key,"canonical_key":canonical,"occurrence":idx,"line":lineno,
                "raw_value":val,"value_kind":part.classify_value(canonical,val),
                "semantic":spec,
            }
            if canonical == "texture" and spec and resolver:
                field["reference"]=_resolve_texture(resolver,spec["value"])
            target=_nearest_event(stack)
            if target is not None: target["fields"].append(field)
            else: system["fields"].append(field)
            if canonical not in SUPPORTED_KEYS:
                warnings.append({"line":lineno,"code":"UNSUPPORTED_KEY","key":key})
            elif spec is None:
                warnings.append({"line":lineno,"code":"UNSUPPORTED_VALUE_SHAPE","key":key,"value":val})

        for _ in range(op):
            stack.append({"kind":"opaque","line":lineno,"fields":[]})
        for _ in range(cl):
            if stack: stack.pop()

    return {
        "parse_status":meta["parse_status"], "authoring_status":meta["authoring_status"],
        "eol":meta["eol"], "brace_open_count":meta["brace_open_count"],
        "brace_close_count":meta["brace_close_count"], "system":system,
        "warnings":warnings,
    }


def _staged_paths(build_root: Path, asset: str):
    rel=Path(asset)
    cand=build_root/"part_editor"/"staged"/rel
    state=build_root/"part_editor"/"state"/(asset.replace("/","__")+".json")
    return cand,state


def load_source(client_root: Path, build_root: Path, asset: str, prefer_staged=True):
    root=client_root.resolve(); source=(root/asset).resolve()
    try: source.relative_to(root)
    except ValueError: raise ValueError("asset escapes client root")
    if source.suffix.lower() != ".part" or not source.is_file(): raise FileNotFoundError(asset)
    src=source.read_bytes(); src_sha=_sha(src)
    if prefer_staged:
        cand,state_path=_staged_paths(build_root.resolve(),asset)
        if cand.is_file() and state_path.is_file():
            state=json.loads(state_path.read_text(encoding="utf-8"))
            cdata=cand.read_bytes(); csha=_sha(cdata)
            if state.get("source_sha256") == src_sha and state.get("candidate_sha256") == csha:
                return cdata,{"base_kind":"STAGED_DRAFT","source_path":str(source),"candidate_path":str(cand),"source_sha256":src_sha,"candidate_sha256":csha,"revision":state.get("revision")}
    return src,{"base_kind":"CLIENT_SOURCE_READONLY","source_path":str(source),"source_sha256":src_sha,"candidate_sha256":src_sha,"revision":0}


def _mid(spec: Optional[dict], default: float=0.0) -> float:
    if not spec: return default
    if spec.get("kind") == "FIXED": return float(spec["value"])
    if spec.get("kind") == "RANGE": return (float(spec["a"])+float(spec["b"]))/2.0
    return default


def _event_preview(event: dict):
    grouped={}
    for f in event["fields"]: grouped.setdefault(f["canonical_key"],[]).append(f)
    initial={}; fade={}
    for f in grouped.get("initial",[]):
        sp=f.get("semantic")
        if sp: initial[sp["field"]]=sp["value"]
    for f in grouped.get("fade",[]):
        sp=f.get("semantic")
        if sp: fade[sp["field"]]=sp["value"]
    def first(k):
        rows=grouped.get(k,[]); return rows[0].get("semantic") if rows else None
    texture=None
    if grouped.get("texture"):
        t=grouped["texture"][0]
        texture={"semantic":t.get("semantic"),"reference":t.get("reference")}
    return {
        "header_value":event["header_value"], "line":event["line"],
        "at":first("at"), "numparticles":first("numparticles"), "emitrate":first("emitrate"),
        "delay":first("delay"), "lifetime":first("lifetime"), "loops":first("loops"),
        "gravity":first("gravity"), "emitradius":first("emitradius"),
        "sourceblendmode":first("sourceblendmode"), "particletype":first("particletype"),
        "texture":texture, "initial":initial, "fade":fade,
        "raw_field_count":len(event["fields"]),
    }


def _complexity(events: list[dict]) -> dict:
    requested=0
    for event in events:
        requested += max(1, int(round(abs(_mid(event.get("numparticles"), 1.0)))))
    return {
        "requested_particle_objects": requested,
        "event_count": len(events),
        "recommended_max_events": min(max(1, len(events)), 64),
        "recommended_max_particles_per_event": 32,
        "recommended_max_total_particles": 256,
    }


def build_preview_plan(client_root: Path, build_root: Path, asset: str, *, prefer_staged=True, write=True):
    data,source_meta=load_source(client_root,build_root,asset,prefer_staged=prefer_staged)
    parsed=parse_effect_structure(data,client_root=client_root)
    # Preview is explicitly approximate and read-only.  Unbalanced legacy
    # braces should block authoring, but they should not prevent us from
    # visualizing the portions that were parsed successfully.  Keep the
    # condition visible as a warning instead of failing the whole preview.
    preview_parse_warnings = []
    if parsed["parse_status"] != "PASS_LEXICAL":
        preview_parse_warnings.append({
            "code": "SOURCE_PARSE_REVIEW",
            "parse_status": parsed["parse_status"],
            "detail": "Preview generated from the lexically recoverable subset; authoring remains blocked until source structure is repaired.",
        })
    sysfields={}
    for f in parsed["system"]["fields"]: sysfields.setdefault(f["canonical_key"],[]).append(f)
    position=None
    if sysfields.get("position"): position=sysfields["position"][0].get("semantic")
    events=[_event_preview(e) for e in parsed["system"]["eventsequences"]]
    refs=[]
    for i,e in enumerate(events):
        t=e.get("texture")
        if t and t.get("reference"):
            refs.append({"event_index":i,**t["reference"]})
    missing=[r for r in refs if not r["exists"]]
    plan={
        "format":FORMAT,"status":"PASS","asset":asset,"source":source_meta,
        "source_payload_sha256":_sha(data), "plan_schema":PLAN_SCHEMA,
        "parse_status":parsed["parse_status"],"authoring_status":parsed["authoring_status"],
        "eol":parsed["eol"],"system_header":parsed["system"]["header"],
        "position":position,"event_count":len(events),"events":events,
        "texture_references":refs,"missing_texture_reference_count":len(missing),
        "missing_texture_references":missing,"semantic_warnings":preview_parse_warnings + parsed["warnings"],
        "complexity":_complexity(events),
        "preview_certification":"BLENDER_PREVIEW_APPROXIMATE",
        "timing_model":"HEURISTIC_AT_DELAY_EMITRATE_PREVIEW_ONLY_NOT_ENGINE_CERTIFIED",
        "loop_model":"LOOPS_PRESERVED_AS_METADATA_NOT_REPEATED_AUTOMATICALLY",
        "blend_model":"APPROXIMATE_PRESERVE_SOURCEBLENDMODE_AS_METADATA",
        "production_authorized":False,"client_write_authorized":False,"server_write_authorized":False,
    }
    plan["plan_content_sha256"]=_json_sha(plan)
    if write:
        safe_asset=asset.replace("/","__")
        out=build_root.resolve()/"effect_preview"/"plans"/(safe_asset+"."+plan["source_payload_sha256"][:16]+".json")
        out.parent.mkdir(parents=True,exist_ok=True)
        tmp=out.with_suffix(out.suffix+".tmp")
        tmp.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,out)
        plan["plan_path"]=str(out)
    return plan


def verify_plan(client_root: Path, build_root: Path, plan: dict) -> dict:
    errors=[]
    if plan.get("format") != FORMAT: errors.append("FORMAT")
    if plan.get("preview_certification") != "BLENDER_PREVIEW_APPROXIMATE": errors.append("CERTIFICATION")
    asset=plan.get("asset")
    if not isinstance(asset,str): errors.append("ASSET")
    else:
        try:
            data,meta=load_source(client_root,build_root,asset,prefer_staged=True)
            if _sha(data) != plan.get("source_payload_sha256"): errors.append("STALE_SOURCE_OR_DRAFT")
            if meta.get("source_sha256") != (plan.get("source") or {}).get("source_sha256"): errors.append("SOURCE_SHA_MISMATCH")
        except Exception as exc:
            errors.append(f"SOURCE_CHECK:{type(exc).__name__}")
    clone=dict(plan); expected=clone.pop("plan_path",None); content_sha=clone.pop("plan_content_sha256",None)
    if content_sha is not None and _json_sha(clone) != content_sha: errors.append("PLAN_CONTENT_SHA_MISMATCH")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"asset":asset,"production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}


def _safe_under_pt_build(app_root: Path, p: Path) -> Path:
    root=(app_root.resolve()/"pt_build").resolve()
    p=p.resolve()
    try: p.relative_to(root)
    except ValueError: raise ValueError("preview output must stay under pt_build")
    return p


def _blender_prefix(blender: str | Sequence[str]) -> list[str]:
    if isinstance(blender, str):
        prefix = shlex.split(blender) if any(c.isspace() for c in blender) else [blender]
    else:
        prefix = [str(x) for x in blender]
    if not prefix:
        raise ValueError("Blender command is empty")
    return prefix


def blender_command(
    app_root: Path, plan_path: Path, *, out_blend: Optional[Path]=None,
    report: Optional[Path]=None, render_dir: Optional[Path]=None,
    blender: str | Sequence[str]="blender", max_events: int=64, max_particles_per_event: int=32,
    max_total_particles: int=256, frames: int=120,
    render_frames: Tuple[int,...]=(1, 30, 60, 90),
    render_size: int=512,
):
    app_root=app_root.resolve(); plan_path=plan_path.resolve()
    base=app_root/"pt_build"/"devtest"/"effect_preview"/"blender"
    base.mkdir(parents=True,exist_ok=True)
    stem=plan_path.stem
    out_blend=_safe_under_pt_build(app_root, out_blend or base/(stem+".blend"))
    report=_safe_under_pt_build(app_root, report or base/(stem+".report.json"))
    render_dir=_safe_under_pt_build(app_root, render_dir or base/(stem+".renders"))
    if not (64 <= int(render_size) <= 2048): raise ValueError("render_size must be in [64, 2048]")
    rf=tuple(sorted({max(1,min(int(frames),int(x))) for x in render_frames}))
    if not rf: rf=(max(1,min(int(frames),30)),)
    args=[
        *_blender_prefix(blender),"--background","--factory-startup","--python-exit-code","1",
        "--python",str(app_root/"pt_effect_blender_preview.py"),"--",
        "--plan",str(plan_path),"--out",str(out_blend),"--report",str(report),
        "--render-dir",str(render_dir),"--render-frames",",".join(str(x) for x in rf),
        "--render-size",str(render_size),
        "--max-events",str(max_events),"--max-particles-per-event",str(max_particles_per_event),
        "--max-total-particles",str(max_total_particles),"--frames",str(frames),
    ]
    return {
        "args":args,"shell":shlex.join(args),"out_blend":str(out_blend),
        "report":str(report),"render_dir":str(render_dir),"render_frames":list(rf),
        "render_size":int(render_size),
        "limits":{"max_events":max_events,"max_particles_per_event":max_particles_per_event,
                  "max_total_particles":max_total_particles,"frames":frames},
    }


def run_blender_preview(
    app_root: Path, plan_path: Path, *, timeout_seconds: float=120.0,
    blender: str | Sequence[str]="blender", render_frames: Tuple[int,...]=(1,30,60,90),
    render_size: int=512,
) -> dict:
    if timeout_seconds <= 0 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be in (0, 120]")
    prefix = _blender_prefix(blender)
    first = Path(prefix[0]).expanduser()
    if not first.is_file() and shutil.which(prefix[0]) is None:
        raise FileNotFoundError(
            f"Blender launcher not found: {prefix[0]}. Run `python3 pt_asset.py dependencies` for installation/configuration instructions."
        )
    cmd=blender_command(app_root,plan_path,blender=blender,render_frames=render_frames,render_size=render_size)
    proc=subprocess.Popen(
        cmd["args"],cwd=str(Path(app_root).resolve()),text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True
    )
    try:
        stdout,_=proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try:
            stdout,_=proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            stdout,_=proc.communicate()
        return {
            "status":"FAIL","reason":"TIMEOUT","timeout_seconds":timeout_seconds,
            "command":cmd,"stdout_tail":(stdout or "")[-4000:],
            "process_group_terminated":True,"production_authorized":False,
            "client_write_authorized":False,"server_write_authorized":False
        }
    report_path=Path(cmd["report"]); report=None
    if report_path.is_file():
        try: report=json.loads(report_path.read_text(encoding="utf-8"))
        except Exception: report=None
    render_files=[]
    if isinstance(report,dict):
        for item in report.get("render_files") or []:
            try:
                rp=_safe_under_pt_build(Path(app_root), Path(str(item)))
                if rp.is_file() and rp.suffix.lower()==".png": render_files.append(str(rp))
            except Exception:
                pass
    status=(
        "PASS" if proc.returncode == 0 and isinstance(report,dict)
        and report.get("status") == "PASS" and Path(cmd["out_blend"]).is_file()
        else "FAIL"
    )
    return {
        "status":status,"returncode":proc.returncode,"command":cmd,"report":report,
        "render_files":render_files,"stdout_tail":(stdout or "")[-4000:],
        "production_authorized":False,"client_write_authorized":False,
        "server_write_authorized":False
    }

def main():
    ap=argparse.ArgumentParser(description="Build/verify/run staging-only Blender preview plans for Summit .part effects")
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("plan"); p.add_argument("--client-root",required=True); p.add_argument("--build-root",default="pt_build/devtest"); p.add_argument("--asset",required=True); p.add_argument("--source-only",action="store_true")
    p=sub.add_parser("command"); p.add_argument("--app-root",default="."); p.add_argument("--plan",required=True)
    p=sub.add_parser("verify"); p.add_argument("--client-root",required=True); p.add_argument("--build-root",default="pt_build/devtest"); p.add_argument("--plan",required=True)
    p=sub.add_parser("run"); p.add_argument("--app-root",default="."); p.add_argument("--plan",required=True); p.add_argument("--timeout",type=float,default=120.0); p.add_argument("--blender",default="blender")
    a=ap.parse_args()
    if a.cmd == "plan":
        plan=build_preview_plan(Path(a.client_root),Path(a.build_root),a.asset,prefer_staged=not a.source_only,write=True)
        print(json.dumps({k:plan[k] for k in ("status","asset","event_count","missing_texture_reference_count","complexity","preview_certification","plan_path","production_authorized","client_write_authorized")},ensure_ascii=False,indent=2))
    elif a.cmd == "command":
        print(json.dumps(blender_command(Path(a.app_root),Path(a.plan)),ensure_ascii=False,indent=2))
    elif a.cmd == "verify":
        plan=json.loads(Path(a.plan).read_text(encoding="utf-8")); print(json.dumps(verify_plan(Path(a.client_root),Path(a.build_root),plan),ensure_ascii=False,indent=2))
    else:
        print(json.dumps(run_blender_preview(Path(a.app_root),Path(a.plan),timeout_seconds=a.timeout,blender=a.blender),ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
