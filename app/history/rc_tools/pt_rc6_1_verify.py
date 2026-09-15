#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

STATIC_MARKER='PT_RC6_1_VEC3_NUMERIC_LEAF_NORMALIZER'
MOTION_MARKER='PT_RC6_1_2_MOTION_BUDGET'
DONE_RE=re.compile(r'MOTION_SEMANTIC\s+(\d+)/(\d+)\s+DONE\s+inx=(\w+)\s+smb=(\w+)\s+source=(\w+)\s+elapsed=([0-9.]+)s')

def find_motion(app: Path):
    for p in app.rglob('*.py'):
        if 'pt_build' in p.parts or '__pycache__' in p.parts:
            continue
        try: s=p.read_text(encoding='utf-8')
        except Exception: continue
        if MOTION_MARKER in s: return p
    return None

def strings(obj):
    if isinstance(obj,dict):
        for v in obj.values(): yield from strings(v)
    elif isinstance(obj,list):
        for v in obj: yield from strings(v)
    elif isinstance(obj,str): yield obj

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--app-root',default='.')
    a=ap.parse_args(); app=Path(a.app_root).resolve()
    writer=app/'pt_blender_to_smd_free_mesh_v3.py'; motion=find_motion(app)
    result_path=app/'pt_build/devtest/release_1_auto/result.json'
    log_path=app/'pt_build/devtest/rc6_1_2_release.log'
    out={
      'format':'PT_RC6_1_2_VERIFY_CURRENT_V1',
      'static_patch_present':writer.exists() and STATIC_MARKER in writer.read_text(encoding='utf-8'),
      'motion_patch_present':motion is not None,
      'motion_patch_file':str(motion) if motion else None,
      'release_result_present':result_path.exists(),
      'captured_release_log_present':log_path.exists(),
      'production_authorized':False,'client_write_authorized':False,'server_write_authorized':False,
    }
    if result_path.exists():
        try: r=json.loads(result_path.read_text(encoding='utf-8'))
        except Exception as exc: out['release_result_error']=f'{type(exc).__name__}: {exc}'
        else:
            summary=r.get('summary',{})
            for key in ('static','static_corpus','rigid','rigid_standalone','animation_pose_space','model062_physical_corpus','model062_texture_presence'):
                if key in summary:
                    value=summary[key]; out[key]=value.get('status') if isinstance(value,dict) else value
            all_strings=list(strings(r))
            out['static_float_tuple_error_count']=sum("float() argument must be a string or a real number, not 'tuple'" in x for x in all_strings)
            out['static_rc6_1_shape_fail_count']=sum('PT_RC6_1_VEC3_NORMALIZE_FAIL' in x for x in all_strings)
            out['release_status']=r.get('status'); out['automatic_gate_status']=r.get('automatic_gate_status')
    if log_path.exists():
        rows=[]
        for line in log_path.read_text(encoding='utf-8',errors='replace').splitlines():
            m=DONE_RE.search(line)
            if m:
                rows.append({'index':int(m.group(1)),'total':int(m.group(2)),'inx':m.group(3),'smb':m.group(4),'source':m.group(5),'elapsed_sec':float(m.group(6))})
        out['motion_done_context_count']=len(rows)
        out['motion_max_elapsed_sec']=max((x['elapsed_sec'] for x in rows),default=None)
        out['motion_contexts_over_130s']=[x for x in rows if x['elapsed_sec']>130]
        out['motion_contexts_over_200s']=[x for x in rows if x['elapsed_sec']>200]
    print(json.dumps(out,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
