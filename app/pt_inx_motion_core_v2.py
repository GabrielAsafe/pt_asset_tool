#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, struct
from pathlib import Path

TOOL='PT_INX_MOTION_CORE_V2'
MOTION_INFO_MAX=512
OFF_MOTIONINFO=0x18C
CHRMOTION_EXT=10
STATE_NAMES={
    0x040:'STAND',0x050:'WALK',0x060:'RUN',0x080:'FALLDOWN',0x100:'ATTACK',
    0x110:'DAMAGE',0x120:'DEAD',0x130:'SOMETIME',0x140:'EAT',0x150:'SKILL',
    0x170:'FALLSTAND',0x180:'FALLDAMAGE',0x200:'RESTART',0x210:'WARP',
    0x220:'YAHOO',0x300:'HAMMER'}
LAYOUTS={
    95268:{
        'name':'MODERN_172','motion_size':172,
        'item_count':0x24,'item_list':0x28,'item_list_len':104,
        'job_code_bit':0x90,'skill_code_list':0x94,'skill_code_len':8,'map_position':0x9C,
        'repeat':0xA0,'key_code':0xA4,'motion_frame':0xA8,
    },
    67084:{
        'name':'LEGACY_120','motion_size':120,
        'item_count':0x24,'item_list':0x28,'item_list_len':52,
        'job_code_bit':0x5C,'skill_code_list':0x60,'skill_code_len':8,'map_position':0x68,
        'repeat':0x6C,'key_code':0x70,'motion_frame':0x74,
    },
}

def dword(v): return v & 0xffffffff
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def i32(b,o): return struct.unpack_from('<i',b,o)[0]
def cstr(b): return b.split(b'\0',1)[0].decode('latin1','replace')

def get_speed_sum(text):
    raw=text.encode('latin1'); sum2=dwsum=cnt=0
    for ch in raw:
        if ch==0: break
        value=ch-0x20 if 97<=ch<=122 else ch
        sum2=dword(sum2+value*(cnt+1)); dwsum=dword(dwsum+value*(cnt*cnt)); cnt+=1
    return dword((dwsum<<24)|(cnt<<16)|sum2)

def reconstruct_codes(file_type_kw,link_kw,has_link):
    if has_link:
        file_code=dword((link_kw&0xFF000000)|((file_type_kw&0xFF000000)>>8)|(link_kw&0x0000FF00)|((file_type_kw&0x0000FF00)>>8))
        link_code=dword(((file_type_kw&0xFF)<<24)|((link_kw&0xFF)<<16)|((link_kw&0x00FF0000)>>8)|((file_type_kw&0x00FF0000)>>16))
        return file_code,link_code
    return dword(((file_type_kw&0xFF000000)>>16)|((file_type_kw&0x00FF0000)<<8)|((file_type_kw&0x0000FF00)>>8)|((file_type_kw&0xFF)<<16)),None

def decode_start(raw_kw,raw_frame,code):
    if not (raw_kw or raw_frame): return 0,True,0
    kw=dword((raw_kw&0xFF000000)|((raw_kw&0x0000FF00)<<8)|(raw_frame&0x0000FF00)|((raw_frame&0xFF000000)>>24))
    fr=dword(((raw_frame&0xFF)<<24)|(raw_frame&0x00FF0000)|((raw_kw&0x00FF0000)>>8)|(raw_kw&0xFF))
    return fr,kw==code,kw

def decode_end(raw_kw,raw_frame,code):
    if not (raw_kw or raw_frame): return 0,True,0
    kw=dword(((raw_frame&0x0000FF00)<<16)|((raw_frame&0xFF000000)>>8)|(raw_kw&0x0000FF00)|((raw_kw&0xFF000000)>>24))
    fr=dword(((raw_kw&0x00FF0000)<<8)|((raw_kw&0xFF)<<16)|((raw_frame&0x00FF0000)>>8)|(raw_frame&0xFF))
    return fr,kw==code,kw

def detect_layout(data):
    lay=LAYOUTS.get(len(data))
    if not lay: raise ValueError(f'unsupported INX size={len(data)}; known={sorted(LAYOUTS)}')
    x=dict(lay); x['file_size']=len(data); x['motion_count_off']=OFF_MOTIONINFO+MOTION_INFO_MAX*x['motion_size']
    x['file_type_kw_off']=x['motion_count_off']+4; x['link_kw_off']=x['motion_count_off']+8; x['link_file_off']=x['motion_count_off']+12
    return x

def parse_inx(path):
    p=Path(path); data=p.read_bytes(); lay=detect_layout(data)
    mc=u32(data,lay['motion_count_off']); file_kw=u32(data,lay['file_type_kw_off']); link_kw=u32(data,lay['link_kw_off']); link_file=cstr(data[lay['link_file_off']:lay['link_file_off']+64])
    if not 0<=mc<=512: raise ValueError(f'invalid MotionCount={mc}')
    file_code,link_code=reconstruct_codes(file_kw,link_kw,bool(link_file))
    motions=[]
    for idx in range(mc):
        off=OFF_MOTIONINFO+idx*lay['motion_size']
        state=u32(data,off); kw1=u32(data,off+4); raw_start=u32(data,off+8); kw2=u32(data,off+12); raw_end=u32(data,off+16)
        if idx>=CHRMOTION_EXT and (kw1 or kw2):
            start,sok,skw=decode_start(kw1,raw_start,file_code); end,eok,ekw=decode_end(kw2,raw_end,file_code)
            encoding="KEYWORD_ENCODED"
        else:
            # Some legacy clones (for example GM-001f) keep extended MotionInfo
            # frame fields plain with both keyword DWORDs zero. The runtime does
            # not need a decryption step for those records.
            start,end=raw_start,raw_end; sok=eok=True; skw=ekw=0
            encoding="PLAIN"
        item_count=u32(data,off+lay['item_count'])
        item_raw=list(data[off+lay['item_list']:off+lay['item_list']+lay['item_list_len']])
        skill_raw=list(data[off+lay['skill_code_list']:off+lay['skill_code_list']+lay['skill_code_len']])
        # The runtime treats both arrays as zero-terminated semantic lists.
        # Keep the raw fixed-width bytes for forensic parity and expose the
        # effective values separately for contract resolution.
        item_codes=item_raw[:min(item_count,len(item_raw))] if item_count else []
        skill_codes=[]
        for code_byte in skill_raw:
            if code_byte==0:
                break
            skill_codes.append(code_byte)
        motions.append({
            'index':idx,'state':state,'state_name':STATE_NAMES.get(state,f'UNKNOWN_0x{state:08X}'),
            'start':start,'end':end,'start_ok':sok,'end_ok':eok,
            'start_keyword':skw,'end_keyword':ekw,
            'event_frames':[u32(data,off+0x14+i*4) for i in range(4)],
            'item_code_count':item_count,'item_code_list':item_codes,'item_code_list_raw':item_raw,
            'job_code_bit':u32(data,off+lay['job_code_bit']),
            'skill_code_list':skill_codes,'skill_code_list_raw':skill_raw,
            'map_position':i32(data,off+lay['map_position']),
            'repeat':u32(data,off+lay['repeat']),'key_code':data[off+lay['key_code']],
            'motion_frame':i32(data,off+lay['motion_frame']),'encoding':encoding,
        })
    return {'path':str(p),'layout':lay,'motion_count':mc,'file_code':file_code,'link_code':link_code,'link_file':link_file,'motions':motions}

def smb_frames(path):
    d=Path(path).read_bytes()
    if len(d)<556 or not d.startswith(b'SMD Model data Ver 0.62'): raise ValueError('invalid SMB')
    n=i32(d,40)
    if not 0<=n<=32: raise ValueError(f'invalid TmFrameCounter={n}')
    return [{'slot':i,'start':i32(d,44+i*16),'end':i32(d,48+i*16),'pos_num':i32(d,52+i*16),'pos_cnt':i32(d,56+i*16)} for i in range(n)]

def validate_with_smb(parsed,smb):
    frames=smb_frames(smb); errors=[]; active=0
    for m in parsed['motions']:
        if not m['start_ok'] or not m['end_ok']: errors.append(f"motion[{m['index']}] keyword decode")
        mf=m['motion_frame']
        if mf<=0: continue
        active+=1; slot=mf-1
        if not 0<=slot<len(frames): errors.append(f"motion[{m['index']}] frame slot {slot} outside {len(frames)}"); continue
        base=frames[slot]['start']//160; eng_end=(m['end']+base)*160
        if eng_end>frames[slot]['end']: errors.append(f"motion[{m['index']}] engine_end {eng_end} > container_end {frames[slot]['end']}")
    return {'smb':str(smb),'tm_frame_count':len(frames),'motions_with_container':active,'errors':errors,'check':'PASS' if not errors else 'FAIL'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--inx',required=True); ap.add_argument('--smb'); ap.add_argument('--logical-path'); ap.add_argument('--report'); a=ap.parse_args()
    x=parse_inx(a.inx); result={'tool':TOOL,**x,'client_modified':False}
    if a.logical_path:
        result['logical_path']=a.logical_path; result['logical_path_code']=get_speed_sum(a.logical_path); result['logical_path_code_match']=result['logical_path_code']==x['file_code']
    if a.smb: result['smb_validation']=validate_with_smb(x,a.smb)
    result['keyword_failures']=[m['index'] for m in x['motions'] if not (m['start_ok'] and m['end_ok'])]
    result['check']='PASS' if not result['keyword_failures'] and (not a.smb or result['smb_validation']['check']=='PASS') else 'FAIL'
    if a.report:
        rp=Path(a.report); rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(TOOL); print(f"layout={x['layout']['name']}"); print(f"motion_count={x['motion_count']}"); print(f"link_file={x['link_file']!r}"); print(f"keyword_failures={result['keyword_failures']}")
    if a.logical_path: print(f"logical_path_code_match={result['logical_path_code_match']}")
    if a.smb: print(f"smb_validation={result['smb_validation']['check']}")
    print('client_modified=False'); print(f"inx_motion_core_check={result['check']}")
    if result['check']!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
