#!/usr/bin/env python3
"""Read-only structural probe for Summit/Priston client/server asset formats."""
from __future__ import annotations
import argparse, json, re, struct
from pathlib import Path
from typing import List
from asset_common import extract_binary_refs, extract_item_codes, extract_text_refs, read_legacy_text, sha256_file


def u16(b,o): return struct.unpack_from('<H',b,o)[0] if len(b)>=o+2 else None
def u32(b,o): return struct.unpack_from('<I',b,o)[0] if len(b)>=o+4 else None
def i32(b,o): return struct.unpack_from('<i',b,o)[0] if len(b)>=o+4 else None

def clean_cstr(b: bytes) -> str:
    b=b.split(b'\0',1)[0]
    if not b:return ''
    for enc in ('cp949','utf-8','cp1252','latin1'):
        try:return b.decode(enc)
        except Exception:pass
    return ''

def replace_ext(path: str, ext: str) -> str:
    if not path:return ''
    p=path.replace('\\','/')
    pos=p.rfind('.')
    slash=max(p.rfind('/'),p.rfind('\\'))
    if pos>slash:p=p[:pos]
    return p+'.'+ext.lstrip('.')

def parse_inx_core(data: bytes) -> dict:
    """Parse fields whose offsets are deterministic in both known smMODELINFO ABIs.

    Current ABI proof:
      95,268 = header/core + 512*172 motion + 30*172 talk motion + tails
    Legacy ABI proof:
      67,084 = same layout with 120-byte motion records.
    """
    if len(data)==95268:
        motion_size=172; generation='MODERN_172'
    elif len(data)==67084:
        motion_size=120; generation='LEGACY_120'
    else:
        return {'generation':'UNKNOWN','runtime_refs':[]}
    base=396 + 512*motion_size
    model=clean_cstr(data[0:64])
    motion=clean_cstr(data[64:128])
    sub=clean_cstr(data[128:192])
    motion_count=u32(data,base)
    file_type_keyword=u32(data,base+4)
    link_keyword=u32(data,base+8)
    link=clean_cstr(data[base+12:base+76])
    talk_link=clean_cstr(data[base+76:base+140])
    talk_motion=clean_cstr(data[base+140:base+204])
    talk_count_off=base+204 + 30*motion_size
    talk_motion_count=u32(data,talk_count_off)
    refs=[]
    def add(role,logical,runtime_ext=None):
        if not logical:return
        refs.append({'role':role,'logical':logical.replace('\\','/'),'runtime':replace_ext(logical,runtime_ext) if runtime_ext else logical.replace('\\','/')})
    # smPATTERN::LoadCharactor -> smASE_Read(model) -> .smd
    add('model',model,'smd')
    # LoadBipPattern -> smASE_ReadBone(motion) -> .smb
    add('motion',motion,'smb')
    # Sub-model is recursively passed to LoadCharactor -> smModelDecode -> .inx
    add('sub_model',sub,'inx')
    # smModelDecode resolves Link/TalkLink through smFindFile(..., "inx")
    add('link_modelinfo',link,'inx')
    add('talk_link_modelinfo',talk_link,'inx')
    # Talk motion, when populated, is loaded by LoadBipPattern -> .smb
    add('talk_motion',talk_motion,'smb')
    return {
        'generation':generation,
        'motion_record_size':motion_size,
        'model_file':model,'motion_file':motion,'sub_model_file':sub,
        'motion_count':motion_count,'file_type_keyword_u32':file_type_keyword,
        'link_keyword_u32':link_keyword,'link_file':link,
        'talk_link_file':talk_link,'talk_motion_file':talk_motion,
        'talk_motion_count':talk_motion_count,'runtime_refs':refs,
    }

def inspect_bmp(data):
    if len(data)<54:return {'kind':'BMP_SHORT'}
    h={'signature_hex':data[:2].hex(),'bfSize':u32(data,2),'reserved1':u16(data,6),'reserved2':u16(data,8),'bfOffBits':u32(data,10),'dibSize':u32(data,14),'width':i32(data,18),'height':i32(data,22),'planes':u16(data,26),'bpp':u16(data,28),'compression':u32(data,30),'imageSize':u32(data,34)}
    if data[:2]==b'BM':h['kind']='BMP_STANDARD'
    elif h['dibSize']==40 and h['planes']==1 and h['bpp'] in (24,32) and h['compression']==0:
        h['kind']='BMP_PROTECTED_HEADER14_LIKELY'; h['bfSize_delta']=h['bfSize']-len(data); h['note']='DIB/pixels appear standard but 14-byte file header is protected/nonstandard.'
    else:h['kind']='BMP_NONSTANDARD'
    return h

def inspect_dds(data):
    if len(data)<128 or data[:4]!=b'DDS ':return {'kind':'DDS_INVALID_OR_SHORT'}
    return {'kind':'DDS','height':u32(data,12),'width':u32(data,16),'mipmaps':u32(data,28),'fourcc':data[84:88].decode('latin1',errors='replace')}

def inspect_tga(data):
    if len(data)<18:return {'kind':'TGA_SHORT'}
    return {'kind':'TGA','image_type':data[2],'width':u16(data,12),'height':u16(data,14),'bpp':data[16],'descriptor':data[17]}

def inspect_spc(data):
    if len(data)%504:return {'record_size':504,'valid_multiple':False}
    ADD_NPC_CODE=0x48470070
    records=[]; runtime_active=0; standard_add_npc=0; blank=0; disabled_stale=0
    for idx,o in enumerate(range(0,len(data),504)):
        r=data[o:o+504]
        if not any(r):blank+=1;continue
        size,code=struct.unpack_from('<ii',r,0); code_u32=code&0xffffffff
        tail=struct.unpack_from('<8i',r,472); is_active=code_u32!=0; standard=code_u32==ADD_NPC_CODE
        if is_active:runtime_active+=1
        if standard:standard_add_npc+=1
        elif code_u32==0:disabled_stale+=1
        records.append({'index':idx,'packet_size':size,'code_u32':code_u32,'runtime_active':is_active,'standard_add_npc_code':standard,'name':clean_cstr(r[8:40]),'model_ini':clean_cstr(r[40:104]),'server_npc':clean_cstr(r[104:164]),'object_serial_u32':tail[0]&0xffffffff,'x':tail[1],'y':tail[2],'z':tail[3],'ax':tail[4],'ay':tail[5],'az':tail[6],'state':tail[7]})
    return {'record_size':504,'record_count_if_exact':len(data)//504,'canonical_summit':len(data)==50400,'runtime_active_count':runtime_active,'standard_add_npc_count':standard_add_npc,'blank_slot_count':blank,'disabled_stale_count':disabled_stale,'record_sample':records[:16]}

SPM_ALIAS={'ACTOR':('*ACTOR','*출연자'),'BOSS_ACTOR':('*BOSS_ACTOR','*출연자두목'),'MAX_ACTOR_POS':('*MAX_ACTOR_POS','*최대동시출현수'),'MAX_ACTOR':('*MAX_ACTOR','*출현수'),'DELAY':('*DELAY','*출현간격')}
def inspect_spm(path):
    text,enc=read_legacy_text(path); directives={k:0 for k in SPM_ALIAS}; actors=[]
    for raw in text.splitlines():
        line=raw.strip(); up=line.upper()
        if not line or line.startswith('//'):continue
        for k,aliases in SPM_ALIAS.items():
            if any(up.startswith(a.upper()) for a in aliases): directives[k]+=1; break
        m=re.search(r'(?i)(?:\*ACTOR|\*출연자)\s+(?:"([^"]+)"|(\S+))\s+(\d+)',line)
        if m:actors.append({'name':m.group(1) or m.group(2),'weight':int(m.group(3))})
    return {'kind':'SPM_SPAWN_TEXT','analysis_encoding':enc,'directives':directives,'actors':actors,'item_codes':extract_item_codes(path),'references':extract_text_refs(path)}

def inspect_one(path:Path)->dict:
    data=path.read_bytes(); ext=path.suffix.casefold(); out={'path':str(path),'name':path.name,'ext':ext,'size':len(data),'sha256':sha256_file(path),'header_hex_64':data[:64].hex()}
    if ext=='.inx':
        core=parse_inx_core(data)
        out['kind']='INX_smMODELINFO'; out.update(core)
        out['binary_compatible_with_current_summit']=len(data)==95268
        out['references']=extract_binary_refs(path)
    elif ext=='.spp':
        out.update({'kind':'SPP_START_POINTS','record_size':12,'record_count_if_exact':len(data)//12 if len(data)%12==0 else None,'layout':'CURRENT_200' if len(data)==2400 else ('LEGACY_50' if len(data)==600 else 'OTHER'),'canonical_summit':len(data)==2400})
        if len(data)%12==0:
            recs=[struct.unpack_from('<iii',data,o) for o in range(0,len(data),12)]; out['active_count']=sum(1 for r in recs if r[0]); out['active_sample']=[{'state':s,'x':x,'z':z} for s,x,z in recs if s][:12]
    elif ext=='.spc': out.update({'kind':'SPC_FIXED_CHARACTERS',**inspect_spc(data),'references':extract_binary_refs(path)})
    elif ext=='.spm': out.update(inspect_spm(path))
    elif ext in {'.smd','.smb'}:
        head=data[:128].decode('latin1',errors='ignore')
        if 'SMD Model data Ver 0.62' in head: out['kind']='SMD_MODEL_062' if ext=='.smd' else 'SMB_MODEL_062_CONTAINER'
        elif 'SMD Stage data Ver 0.72' in head: out['kind']='SMD_STAGE_072'; out['warning']='Stage0.72 remains writer-gated; use PT Asset Tool evidence.'
        else: out['kind']='SMD_SMB_UNKNOWN_HEADER'
        out['header_ascii_128']=''.join(c if 32<=ord(c)<127 else '.' for c in head); out['references']=extract_binary_refs(path)
    elif ext in {'.inf','.npc','.ini','.in','.txt','.zhoon'}:
        text,enc=read_legacy_text(path); out.update({'kind':'LEGACY_TEXT','analysis_encoding':enc,'references':extract_text_refs(path),'item_codes':extract_item_codes(path),'line_count':text.count('\n')+1})
    elif ext=='.bmp':out.update(inspect_bmp(data))
    elif ext=='.dds':out.update(inspect_dds(data))
    elif ext=='.tga':out.update(inspect_tga(data))
    else: out.update({'kind':'GENERIC_BINARY','references':extract_binary_refs(path)})
    return out

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('paths',nargs='+'); ap.add_argument('--out',default='reverse_report.json'); ap.add_argument('--recursive',action='store_true'); ap.add_argument('--max-files',type=int,default=500)
    a=ap.parse_args(); files:List[Path]=[]
    for raw in a.paths:
        p=Path(raw).expanduser();
        if p.is_file():files.append(p)
        elif p.is_dir(): files.extend(x for x in (p.rglob('*') if a.recursive else p.glob('*')) if x.is_file())
    report=[inspect_one(p) for p in files[:a.max_files]]; Path(a.out).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps({'files':len(report),'out':str(Path(a.out).resolve())},indent=2))
if __name__=='__main__':raise SystemExit(main())
