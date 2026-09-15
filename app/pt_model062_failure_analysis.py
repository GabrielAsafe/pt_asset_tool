#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path

FORMAT="PT_MODEL062_FAILURE_ANALYSIS_V1"
COUNT_RE=re.compile(r"(OBJECT_COUNT|VERTEX_COUNT|FACE_COUNT|TEXLINK_COUNT):(\d+)!=(\d+)")

def analyze(gate:dict):
    counts=Counter(); by_domain=defaultdict(Counter); object_pairs=Counter(); uniform=Counter(); nonuniform=0; texprefix=Counter(); examples={}
    for r in gate.get("rows",[]):
        if r.get("status") == "PASS": continue
        err=str(r.get("error") or ""); dom=str(r.get("domain") or "UNKNOWN")
        ms=COUNT_RE.findall(err)
        if ms:
            counts["COUNT_LAYOUT_MISMATCH"]+=1; by_domain[dom]["COUNT_LAYOUT_MISMATCH"]+=1; examples.setdefault("COUNT_LAYOUT_MISMATCH",r)
            ratios=[]
            for key,a,b in ms:
                a=int(a); b=int(b)
                if key == "OBJECT_COUNT": object_pairs[f"{a}!={b}"]+=1
                if b: ratios.append(a/b)
            if ratios and max(ratios)-min(ratios) < 1e-12:
                value=ratios[0]
                if abs(value-round(value)) < 1e-12: uniform[str(int(round(value)))+"x"]+=1
                else: uniform[f"{value:.6g}x"]+=1
            else: nonuniform+=1
            continue
        if "bad tex ptr" in err.casefold():
            counts["BAD_TEXLINK_POINTER"]+=1; by_domain[dom]["BAD_TEXLINK_POINTER"]+=1; examples.setdefault("BAD_TEXLINK_POINTER",r)
            stem=Path(str(r.get("asset") or "")).stem; m=re.match(r"([A-Za-z]+)",stem); texprefix[(m.group(1) if m else stem)]+=1
            continue
        counts["OTHER"]+=1; by_domain[dom]["OTHER"]+=1; examples.setdefault("OTHER",r)
    return {"format":FORMAT,"status":"PASS","failure_count":sum(counts.values()),"categories":dict(counts),"by_domain":{k:dict(v) for k,v in by_domain.items()},"count_layout":{"uniform_ratio_count":sum(uniform.values()),"uniform_ratio_distribution":dict(uniform),"nonuniform_ratio_count":nonuniform,"top_object_count_pairs":object_pairs.most_common(20)},"bad_texlink":{"top_asset_stem_prefixes":texprefix.most_common(20)},"examples":examples,"policy":"DIAGNOSTIC_ONLY_NO_PARSER_ASSUMPTION","production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--result",required=True); ap.add_argument("--out"); a=ap.parse_args(); d=json.loads(Path(a.result).read_text(encoding="utf-8")); gate=(d.get("gates",{}).get("model062_physical_corpus") or d.get("summary",{}).get("model062_physical_corpus") or {}); r=analyze(gate)
    if a.out: Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
