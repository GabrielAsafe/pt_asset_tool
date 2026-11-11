#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,json
from pathlib import Path

def norm_map(m):
    m=copy.deepcopy(m);m.pop('source_line',None)
    for op in m.get('operations',[]): op.pop('line',None)
    for x in m.get('warp_operations_cpp',[]): x.pop('line',None)
    for x in m.get('unsupported_cpp',[]): x.pop('line',None)
    return m

def op_signature(op):
    d=dict(op);d.pop('line',None);return json.dumps(d,sort_keys=True,ensure_ascii=False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('server',type=Path);ap.add_argument('client',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    s=json.loads(a.server.read_text(encoding='utf-8'));c=json.loads(a.client.read_text(encoding='utf-8'))
    sm={m['legacy_field_code']:m for m in s['maps']};cm={m['legacy_field_code']:m for m in c['maps']}
    diffs=[]
    for code in sorted(set(sm)|set(cm)):
        x=sm.get(code);y=cm.get(code)
        if x is None or y is None:
            diffs.append({'field_code':code,'status':'missing_side'});continue
        if norm_map(x)==norm_map(y):continue
        sx=[op_signature(o) for o in x.get('operations',[])];cy=[op_signature(o) for o in y.get('operations',[])]
        only_s=[];only_c=[]
        # sequence-aware simple multiset diff for readable audit
        from collections import Counter
        sc=Counter(sx);cc=Counter(cy)
        for sig,n in (sc-cc).items(): only_s += [json.loads(sig)]*n
        for sig,n in (cc-sc).items(): only_c += [json.loads(sig)]*n
        diffs.append({'field_code':code,'id':x.get('id'),'stage_server':x.get('stage'),'stage_client':y.get('stage'),'server_only_operations':only_s,'client_only_operations':only_c})
    report={'schema':'summit.map-shadow-comparison/v1','server':str(a.server),'client':str(a.client),'field_count_server':len(sm),'field_count_client':len(cm),'different_fields':len(diffs),'diffs':diffs}
    a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    md=['# Legacy hardcoded map client/server comparison','',f'- Server fields: **{len(sm)}**',f'- Client fields: **{len(cm)}**',f'- Fields with semantic differences: **{len(diffs)}**','']
    for d in diffs:
        md += [f'## Field {d["field_code"]} — `{d.get("id")}`','']
        if d.get('stage_server')!=d.get('stage_client'):md.append(f'- Stage: server `{d.get("stage_server")}` / client `{d.get("stage_client")}`')
        if d.get('server_only_operations'):
            md.append('- Server-only operations:')
            for x in d['server_only_operations']:md.append('  - `'+json.dumps(x,ensure_ascii=False,sort_keys=True)+'`')
        if d.get('client_only_operations'):
            md.append('- Client-only operations:')
            for x in d['client_only_operations']:md.append('  - `'+json.dumps(x,ensure_ascii=False,sort_keys=True)+'`')
        md.append('')
    a.out.with_suffix('.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps({'different_fields':len(diffs),'out':str(a.out)}))
if __name__=='__main__':main()
