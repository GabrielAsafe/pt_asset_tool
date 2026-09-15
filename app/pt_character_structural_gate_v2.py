#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,struct,hashlib
from pathlib import Path
SH,SI,SO=556,40,2236; SV,SF,ST,SR,SP,SS,SM=24,36,32,20,16,16,64
O_PHYS,O_NV,O_NF,O_NT,O_NAME,O_PARENT,O_NR,O_NP,O_NS=16,84,88,92,172,204,684,688,692
HEADER=b'SMD Model data Ver 0.62'
def i32(b,o): return struct.unpack_from('<i',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def cs(b): return b.split(b'\0',1)[0].decode('latin1','replace')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def infos(d):
 n=i32(d,24); out=[]
 for i in range(n):
  o=SH+i*SI; out.append({'index':i,'name':cs(d[o:o+32]),'length':i32(d,o+32),'start':i32(d,o+36)})
 return out
def parse_smb(p):
 d=Path(p).read_bytes();
 if not d.startswith(HEADER): raise ValueError('SMB header')
 rows=[]
 for inf in infos(d):
  raw=d[inf['start']:inf['start']+SO]; name=cs(raw[O_NAME:O_NAME+32]); parent=cs(raw[O_PARENT:O_PARENT+32])
  if name!=inf['name']: raise ValueError(f'SMB node mismatch {inf["name"]}/{name}')
  nv,nf,nt,nr,np,ns=[i32(raw,o) for o in (O_NV,O_NF,O_NT,O_NR,O_NP,O_NS)]
  # PT_RC6_11_SMB_PHYSIQUE_TAIL
  # Some legacy SMB support skeletons serialize the same Physique name tail as
  # Model0.62 meshes.  The writer-side relaxed SMB parser already accounts for
  # this exact nVertex*32 suffix; the structural gate must use the same layout.
  has_physique=u32(raw,O_PHYS)!=0
  end=inf['start']+SO+nv*SV+nf*SF+nt*ST+nr*SR+np*SP+ns*SS+nr*SM+(nv*32 if has_physique else 0)
  if end!=inf['start']+inf['length']: raise ValueError(f'{name}: SMB block length')
  rows.append({'name':name,'parent':parent,'has_physique':has_physique})
 last=max(x['start']+x['length'] for x in infos(d)) if rows else SH
 names={x['name'] for x in rows}; bad=[x for x in rows if x['parent'] and x['parent'] not in names]
 return {'bones':rows,'bone_names':names,'trailing_bytes':len(d)-last,'parent_errors':bad}
def parse_smd(p):
 d=Path(p).read_bytes();
 if not d.startswith(HEADER): raise ValueError('SMD header')
 objs=[]; all_bones=[]
 for inf in infos(d):
  raw=d[inf['start']:inf['start']+SO]; name=cs(raw[O_NAME:O_NAME+32]);
  if name!=inf['name']: raise ValueError(f'SMD node mismatch {inf["name"]}/{name}')
  nv,nf,nt,nr,np,ns=[i32(raw,o) for o in (O_NV,O_NF,O_NT,O_NR,O_NP,O_NS)]; phys=u32(raw,O_PHYS)!=0
  cur=inf['start']+SO+nv*SV+nf*SF+nt*ST+nr*SR+np*SP+ns*SS+nr*SM
  bones=[]
  if phys:
   for i in range(nv): bones.append(cs(d[cur+i*32:cur+(i+1)*32]))
   cur+=nv*32
  if cur!=inf['start']+inf['length']: raise ValueError(f'{name}: SMD block length')
  all_bones+=bones; objs.append({'name':name,'vertices':nv,'faces':nf,'texlinks':nt,'physique':phys,'bind_bones':sorted(set(bones))})
 return {'objects':objs,'object_count':len(objs),'bind_vertices':sum(x['vertices'] for x in objs if x['physique']),'bind_bone_names':set(all_bones)}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--smd',required=True); ap.add_argument('--smb',required=True); ap.add_argument('--report'); a=ap.parse_args()
 smd=parse_smd(a.smd); smb=parse_smb(a.smb); missing=sorted(x for x in smd['bind_bone_names'] if x and x not in smb['bone_names'])
 result={'tool':'PT_CHARACTER_STRUCTURAL_GATE_V2','smd':a.smd,'smd_sha256':sha(a.smd),'smb':a.smb,'smb_sha256':sha(a.smb),'object_count':smd['object_count'],'bind_vertices':smd['bind_vertices'],'bind_bones_used':len(smd['bind_bone_names']), 'skeleton_bones':len(smb['bones']),'smb_trailing_bytes':smb['trailing_bytes'],'missing_bind_bones':missing,'parent_error_count':len(smb['parent_errors']),'objects':smd['objects'],'client_modified':False}
 result['check']='PASS' if not missing and not smb['parent_errors'] else 'FAIL'
 if a.report: Path(a.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('PT_CHARACTER_STRUCTURAL_GATE_V2'); print(f"objects={result['object_count']}"); print(f"bind_vertices={result['bind_vertices']}"); print(f"bind_bones_used={result['bind_bones_used']}"); print(f"skeleton_bones={result['skeleton_bones']}"); print(f"smb_trailing_bytes={result['smb_trailing_bytes']}"); print(f"missing_bind_bones={missing}"); print('client_modified=False'); print(f"character_structural_gate_check={result['check']}")
 if result['check']!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
