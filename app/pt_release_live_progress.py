#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

FORMAT='PT_RELEASE_LIVE_PROGRESS_V1'
START_RE=re.compile(r'\[release-1-auto\] START ([^\s]+)')
DONE_RE=re.compile(r'\[release-1-auto\] DONE\s+([^\s]+).*?status=([^\s]+)')
MOTION_BEGIN_RE=re.compile(r'MOTION_SEMANTIC begin contexts=(\d+) total=(\d+) timeout=([0-9.]+)s')
MOTION_RE=re.compile(r'MOTION_SEMANTIC (\d+)/(\d+) (START|RESUME|DONE)(.*)')
ELAPSED_RE=re.compile(r'elapsed=([0-9.]+)s')
WATCHDOG_RE=re.compile(r'\[blender-watchdog\] TIMEOUT .*? age=([0-9.]+)s limit=([0-9.]+)s')


def summarize(text:str)->dict:
    completed=[]; starts=[]; current=None; motion_total=0; motion_seen=0; motion_done=0; motion_resumed=0; motion_started=0; motion_elapsed=[]; watchdog=[]
    release_end=None
    for line in text.splitlines():
        m=START_RE.search(line)
        if m:
            current=m.group(1); starts.append(current)
        m=DONE_RE.search(line)
        if m:
            gate,status=m.groups(); completed.append({'gate':gate,'status':status})
            if current==gate: current=None
        m=MOTION_BEGIN_RE.search(line)
        if m: motion_total=int(m.group(2))
        m=MOTION_RE.search(line)
        if m:
            idx,total,kind,tail=m.groups(); idx=int(idx); total=int(total); motion_total=max(motion_total,total); motion_seen=max(motion_seen,idx)
            if kind=='DONE':
                motion_done=max(motion_done,idx); em=ELAPSED_RE.search(tail)
                if em: motion_elapsed.append(float(em.group(1)))
            elif kind=='RESUME': motion_resumed += 1
            elif kind=='START': motion_started += 1
        m=WATCHDOG_RE.search(line)
        if m: watchdog.append({'age_seconds':float(m.group(1)),'limit_seconds':float(m.group(2)),'line':line[-1000:]})
        if '[release-1-auto] END ' in line: release_end=line.strip()
    motion_progress=max(motion_seen,motion_done)
    return {
        'format':FORMAT,
        'release_end_seen':release_end is not None,
        'release_end_line':release_end,
        'current_gate':current,
        'completed_gate_count':len(completed),
        'completed_gates':completed,
        'motion':{
            'total_contexts':motion_total,
            'highest_context_seen':motion_progress,
            'remaining_contexts':max(0,motion_total-motion_progress) if motion_total else None,
            'resume_line_count':motion_resumed,
            'start_line_count':motion_started,
            'completed_elapsed_samples':len(motion_elapsed),
            'max_elapsed_seconds':max(motion_elapsed,default=0.0),
            'over_130_seconds':sum(x>130 for x in motion_elapsed),
            'over_200_seconds':sum(x>200 for x in motion_elapsed),
        },
        'blender_watchdog_timeout_count':len(watchdog),
        'blender_watchdog_timeouts':watchdog,
        'production_authorized':False,
        'client_write_authorized':False,
        'server_write_authorized':False,
    }


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--log',default='pt_build/devtest/rc6_1_2_release.log'); ap.add_argument('--out')
    a=ap.parse_args(); p=Path(a.log); text=p.read_text(encoding='utf-8',errors='replace'); result=summarize(text)
    if a.out:
        op=Path(a.out); op.parent.mkdir(parents=True,exist_ok=True); op.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
