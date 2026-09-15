#!/usr/bin/env python3
"""Author, validate and transactionally install Summit NPC/monster bundles.

Safety model:
- server .NPC/.INF is cloned from a known-good template;
- INX/SMD/SMB authoring remains delegated to PT Asset Tool;
- staged visual chains are recursively validated through INX links and textures;
- SPC editing is clone-based only and guarded by the base file SHA-256;
- installation is missing-only except an explicitly generated SPC patch;
- SPC replacement is optimistic-lock + backup + rollback capable.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, shutil, struct, tempfile
from pathlib import Path, PurePosixPath

TOKENS = {
    'internal_name': '*이름'.encode('cp949'),
    'model': '*모양파일'.encode('cp949'),
    'link': '*연결파일'.encode('cp949'),
    'level': '*레벨'.encode('cp949'),
}
IMAGE_EXTS={'.bmp','.tga','.dds','.jpg','.jpeg','.png'}
BIN_EXT_RE=re.compile(rb'(?i)\.(?:bmp|tga|dds|jpg|jpeg|png)')
ALLOWED=set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ .()-\\/')
SPC_RECORD_SIZE=504
SPC_RECORD_COUNT=100
SPC_FILE_SIZE=SPC_RECORD_SIZE*SPC_RECORD_COUNT
ADD_NPC_CODE=0x48470070


def norm(s:str)->str:
    s=s.replace('\\','/').strip().lstrip('./').lstrip('/')
    while '//' in s:s=s.replace('//','/')
    return s

def replace_ext(s:str,ext:str)->str:
    return str(PurePosixPath(norm(s)).with_suffix('.'+ext.lstrip('.')))

def load_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def sha256_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def roots(cfg):
    return {'client':Path(cfg['target_client']).expanduser(),'server':Path(cfg['target_server']).expanduser()}

def ci_find(root:Path, rel:str):
    cur=root
    for part in PurePosixPath(norm(rel)).parts:
        if not cur.is_dir():return None
        direct=cur/part
        if direct.exists():cur=direct;continue
        try:hits=[x for x in cur.iterdir() if x.name.casefold()==part.casefold()]
        except OSError:return None
        if len(hits)!=1:return None
        cur=hits[0]
    return cur if cur.exists() else None

def cstr(data,a,b):
    raw=data[a:b].split(b'\0',1)[0]
    for enc in ('cp949','utf-8','cp1252','latin1'):
        try:return raw.decode(enc)
        except Exception:pass
    return ''

def parse_inx(path:Path):
    data=path.read_bytes(); n=len(data)
    if n==95268: ms=172; layout='MODERN_172'
    elif n==67084: ms=120; layout='LEGACY_120'
    else:return {'layout':'UNKNOWN','size':n,'runtime_refs':[]}
    base=396+512*ms
    model=cstr(data,0,64); motion=cstr(data,64,128); sub=cstr(data,128,192)
    link=cstr(data,base+12,base+76); talklink=cstr(data,base+76,base+140); talkmotion=cstr(data,base+140,base+204)
    refs=[]
    def add(role,val,ext):
        if val:refs.append({'role':role,'logical':norm(val),'runtime':replace_ext(val,ext)})
    add('model',model,'smd');add('motion',motion,'smb');add('sub_model',sub,'inx');add('link_modelinfo',link,'inx');add('talk_link_modelinfo',talklink,'inx');add('talk_motion',talkmotion,'smb')
    return {'layout':layout,'size':n,'model_file':model,'motion_file':motion,'sub_model_file':sub,'link_file':link,'talk_link_file':talklink,'talk_motion_file':talkmotion,'runtime_refs':refs}

def binary_texture_refs(path:Path):
    data=path.read_bytes()[:16*1024*1024];out=[];seen=set()
    for m in BIN_EXT_RE.finditer(data):
        i=m.start()-1;floor=max(0,m.start()-240)
        while i>=floor and data[i] in ALLOWED:i-=1
        raw=data[i+1:m.end()]
        s=norm(raw.decode('latin1','ignore').strip('\0 '))
        if s and s.casefold() not in seen:seen.add(s.casefold());out.append(s)
    return out

def patch_template(src:Path,dst:Path, *, internal_name:str, model_logical:str, link_ref:str, level=None):
    raw=src.read_bytes(); lines=raw.splitlines(keepends=True); done=set();out=[]
    repl={'internal_name':internal_name,'model':model_logical,'link':link_ref}
    if level is not None:repl['level']=str(level)
    for line in lines:
        stripped=line.lstrip(); key=None
        for k,t in TOKENS.items():
            if stripped.startswith(t) and (len(stripped)==len(t) or stripped[len(t):len(t)+1] in b' \t\r\n'):
                key=k;break
        if key in repl:
            prefix=line[:len(line)-len(stripped)]; token=TOKENS[key]; val=repl[key]
            if key=='level': newline=prefix+token+b'\t\t'+str(val).encode('ascii')+b'\r\n'
            else:
                enc='cp949' if key=='internal_name' else 'ascii'
                newline=prefix+token+b'\t\t"'+str(val).encode(enc)+b'"\r\n'
            out.append(newline);done.add(key)
        else:out.append(line)
    for key in ('internal_name','model','level','link'):
        if key in repl and key not in done:
            val=repl[key]; token=TOKENS[key]
            if key=='level':out.append(token+b'\t\t'+str(val).encode('ascii')+b'\r\n')
            else:
                enc='cp949' if key=='internal_name' else 'ascii'
                out.append(token+b'\t\t"'+str(val).encode(enc)+b'"\r\n')
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b''.join(out))

def write_zhoon(dst:Path, display_name:str, chats:list[str], encoding='cp1252'):
    def enc(s):
        try:return s.encode(encoding)
        except UnicodeEncodeError as e:raise SystemExit(f'localization text cannot be encoded as {encoding}: {e}')
    b=b'*J_NAME\t\t"'+enc(display_name)+b'"\r\n'
    for c in chats:b+=b'*J_CHAT\t\t"'+enc(c.replace('"',"'"))+b'"\r\n'
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)

def spec_paths(spec):
    kind=spec['kind'].lower(); ident=spec['id']; ext='.npc' if kind=='npc' else '.inf'; sub='NPC' if kind=='npc' else 'Monster'
    server_rel=norm(spec.get('server_rel') or f'GameServer/{sub}/{ident}{ext}')
    zhoon_rel=norm(spec.get('zhoon_rel') or f'GameServer/{sub}/name/{ident}.zhoon')
    return server_rel,zhoon_rel

def scaffold(spec, out:Path):
    kind=spec['kind'].lower()
    if kind not in {'npc','monster'}:raise SystemExit('kind must be npc or monster')
    template=Path(spec['template_server_def']).expanduser()
    if not template.is_file():raise SystemExit(f'template_server_def not found: {template}')
    ident=spec['id'];server_rel,zhoon_rel=spec_paths(spec)
    sparent=PurePosixPath(server_rel).parent
    try: link=str(PurePosixPath(zhoon_rel).relative_to(sparent)).replace('/','\\')
    except ValueError:link=spec.get('link_ref') or f'name\\{ident}.zhoon'
    model=spec['model_logical'].replace('/','\\')
    (out/'client').mkdir(parents=True,exist_ok=True);(out/'server').mkdir(parents=True,exist_ok=True)
    patch_template(template,out/'server'/server_rel,internal_name=spec['internal_name'],model_logical=model,link_ref=link,level=spec.get('level'))
    write_zhoon(out/'server'/zhoon_rel,spec['display_name'],spec.get('chats',[]),spec.get('localization_encoding','cp1252'))
    expected_inx=replace_ext(spec['model_logical'],'inx')
    contract={'kind':kind,'id':ident,'server_rel':server_rel,'zhoon_rel':zhoon_rel,'internal_name':spec['internal_name'],'display_name':spec['display_name'],'model_logical':norm(spec['model_logical']),'expected_inx':expected_inx,'note':'Put PT Asset Tool outputs under client/ preserving runtime paths, then run mirror-visuals and validate-stage.'}
    if spec.get('spawn_spm'):
        sp=spec['spawn_spm']; weight=int(sp.get('weight',100));(out/'spawn').mkdir(parents=True,exist_ok=True)
        (out/'spawn'/f'{ident}.spm.fragment.txt').write_text(f'*ACTOR "{spec["internal_name"]}" {weight}\r\n',encoding='cp949');contract['spawn_spm']=sp
    if kind=='npc' and spec.get('spc'):
        (out/'spawn').mkdir(parents=True,exist_ok=True)
        req={'status':'READY_FOR_CLONE_PATCH','npc_server_rel':server_rel,'model_logical':norm(spec['model_logical']),**spec['spc']}
        (out/'spawn'/f'{ident}.spc_request.json').write_text(json.dumps(req,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'visual_contract.json').write_text(json.dumps(contract,indent=2,ensure_ascii=False),encoding='utf-8')
    return contract

def walk_visual_chain(root:Path, expected_inx:str):
    result={'root':str(root),'expected_inx':expected_inx,'nodes':[],'textures':[],'missing':[],'ok':True}
    q=[('root_inx',expected_inx)];seen=set()
    while q:
        role,rel=q.pop(0);key=norm(rel).casefold()
        if key in seen:continue
        seen.add(key);p=ci_find(root,rel)
        ent={'role':role,'requested':norm(rel),'present':bool(p),'path':str(p) if p else ''}
        if not p:
            result['nodes'].append(ent);result['missing'].append(ent);result['ok']=False;continue
        ext=p.suffix.casefold();ent['size']=p.stat().st_size;result['nodes'].append(ent)
        if ext=='.inx':
            info=parse_inx(p);ent['layout']=info['layout']
            if info['layout']!='MODERN_172':result['ok']=False;ent['compatible']=False
            else:ent['compatible']=True
            for rr in info.get('runtime_refs',[]):q.append((rr['role'],rr['runtime']))
        elif ext in {'.smd','.smb'}:
            for tr in binary_texture_refs(p):
                tp=ci_find(root,tr);te={'parent':norm(rel),'requested':tr,'present':bool(tp),'path':str(tp) if tp else ''}
                result['textures'].append(te)
                if not tp:result['missing'].append(te);result['ok']=False
    return result

def validate_roots(spec, rs):
    expected=replace_ext(spec['model_logical'],'inx');result={'expected_inx':expected,'sides':{},'server_definition':{},'localization':{},'ok':True}
    for side,root in rs.items():
        sd=walk_visual_chain(root,expected);result['sides'][side]=sd;result['ok']=result['ok'] and sd['ok']
    server_rel,zhoon_rel=spec_paths(spec);srv=rs['server']
    sp=ci_find(srv,server_rel);zp=ci_find(srv,zhoon_rel)
    result['server_definition']={'requested':server_rel,'present':bool(sp),'path':str(sp) if sp else ''}
    result['localization']={'requested':zhoon_rel,'present':bool(zp),'path':str(zp) if zp else ''}
    if not sp or not zp:result['ok']=False
    return result

def validate(spec,cfg):return validate_roots(spec,roots(cfg))

def validate_stage(spec,bundle:Path):return validate_roots(spec,{'client':bundle/'client','server':bundle/'server'})

def mirror_visuals(spec,bundle:Path):
    client=bundle/'client';server=bundle/'server';expected=replace_ext(spec['model_logical'],'inx')
    if not client.is_dir():raise SystemExit(f'client staging directory not found: {client}')
    audit=walk_visual_chain(client,expected);copied=[]
    # copy only present runtime nodes and texture files discovered by the validated client chain
    paths=[]
    for n in audit['nodes']:
        if n.get('present'):paths.append((Path(n['path']),n['requested']))
    for t in audit['textures']:
        if t.get('present'):paths.append((Path(t['path']),t['requested']))
    seen=set()
    for src,rel in paths:
        k=norm(rel).casefold()
        if k in seen:continue
        seen.add(k);dst=server/norm(rel);dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and sha256_file(dst)==sha256_file(src):continue
        if dst.exists():raise SystemExit(f'server staging conflict: {dst}')
        shutil.copy2(src,dst);copied.append(norm(rel))
    return {'ok':audit['ok'],'client_chain':audit,'copied_to_server':copied}

def encode_fixed(text:str,size:int,encoding:str,field:str)->bytes:
    try:b=text.encode(encoding)
    except UnicodeEncodeError as e:raise SystemExit(f'{field} cannot be encoded as {encoding}: {e}')
    if len(b)>=size:raise SystemExit(f'{field} too long: {len(b)} bytes, max {size-1}')
    return b+b'\0'*(size-len(b))

def parse_spc_record(r:bytes,index:int):
    size,code=struct.unpack_from('<ii',r,0);tail=struct.unpack_from('<8i',r,472)
    return {'index':index,'size':size,'code_u32':code&0xffffffff,'runtime_active':(code&0xffffffff)!=0,'standard_add_npc_code':(code&0xffffffff)==ADD_NPC_CODE,'blank':not any(r),'name':cstr(r,8,40),'model_ini':cstr(r,40,104),'server_npc':cstr(r,104,164),'object_serial_u32':tail[0]&0xffffffff,'x':tail[1],'y':tail[2],'z':tail[3],'ax':tail[4],'ay':tail[5],'az':tail[6],'state':tail[7]}

def spc_patch(spec,cfg,bundle:Path):
    if spec.get('kind','').lower()!='npc' or not spec.get('spc'):raise SystemExit('spec must be an npc with an spc block')
    sp=spec['spc'];field_rel=norm(sp['field_spc']);target=ci_find(roots(cfg)['server'],field_rel)
    if not target or not target.is_file():raise SystemExit(f'field SPC not found in target server: {field_rel}')
    data=bytearray(target.read_bytes())
    if len(data)!=SPC_FILE_SIZE:raise SystemExit(f'SPC size {len(data)} is not canonical {SPC_FILE_SIZE}')
    records=[parse_spc_record(bytes(data[i*504:(i+1)*504]),i) for i in range(100)]
    template_idx=sp.get('template_index')
    if template_idx is None:
        template_idx=next((r['index'] for r in records if r['standard_add_npc_code']),None)
    if template_idx is None or not 0<=int(template_idx)<100:raise SystemExit('no valid active template record found')
    template_idx=int(template_idx)
    if not records[template_idx]['standard_add_npc_code']:raise SystemExit(f'template_index {template_idx} is not the observed standard ADD_NPC code 0x{ADD_NPC_CODE:08X}')
    slot=sp.get('slot_index')
    if slot is None:
        # Preserve disabled/stale historical records when possible: automatic mode uses only a fully blank slot.
        slot=next((r['index'] for r in records if r['blank']),None)
        if slot is None:raise SystemExit('no fully blank SPC slot found; set spc.slot_index explicitly to reuse a disabled code==0 record')
    if not 0<=int(slot)<100:raise SystemExit('invalid SPC slot_index')
    slot=int(slot)
    if records[slot]['runtime_active']:raise SystemExit(f'slot {slot} is already runtime-active')
    rec=bytearray(data[template_idx*504:(template_idx+1)*504])
    struct.pack_into('<iI',rec,0,504,ADD_NPC_CODE)
    rec[8:40]=encode_fixed(sp.get('record_name') or spec['internal_name'],32,sp.get('record_encoding','cp949'),'SPC name')
    rec[40:104]=encode_fixed(spec['model_logical'].replace('/','\\'),64,'ascii','SPC model path')
    server_rel,_=spec_paths(spec)
    rec[104:164]=encode_fixed(server_rel.replace('/','\\'),60,'ascii','SPC server NPC path')
    # ModelNameCode2 and smCHAR_INFO.dwObjectSerial are donor-specific; clear them.
    struct.pack_into('<II',rec,164,0,0)
    # STG_AREA::OpenNpc() replaces the packet-level object serial with GetNewObjectSerial().
    struct.pack_into('<8i',rec,472,0,int(sp['x']),int(sp.get('y',0)),int(sp['z']),int(sp.get('ax',0)),int(sp.get('ay',0)),int(sp.get('az',0)),int(sp.get('state',0)))
    before=records[slot];data[slot*504:(slot+1)*504]=rec
    out=bundle/'server'/field_rel;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
    manifest={'kind':'SPC_CLONE_PATCH','target_rel':field_rel,'base_path':str(target),'base_sha256':sha256_file(target),'patched_sha256':sha256_file(out),'template_index':template_idx,'slot_index':slot,'template_record':records[template_idx],'replaced_slot_before':before,'new_record':parse_spc_record(bytes(rec),slot),'output':str(out)}
    (bundle/'spc_patch_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    return manifest

def atomic_replace_from(src:Path,dst:Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+dst.name+'.',suffix='.tmp',dir=str(dst.parent));os.close(fd);tmp=Path(tmp)
    try:
        shutil.copy2(src,tmp);os.replace(tmp,dst)
    finally:
        if tmp.exists():tmp.unlink(missing_ok=True)

def install_plan(spec,cfg,bundle:Path,out:Path):
    validation=validate_stage(spec,bundle);patch=None
    pm=bundle/'spc_patch_manifest.json'
    if pm.is_file():patch=load_json(pm)
    target_roots=roots(cfg);rows=[];conflicts=[]
    for side in ('client','server'):
        base=bundle/side
        if not base.is_dir():continue
        for src in sorted(p for p in base.rglob('*') if p.is_file()):
            rel=src.relative_to(base).as_posix();dst=target_roots[side]/rel;sh=sha256_file(src);action='COPY';detail='destination missing';pre=None
            if dst.exists():
                dh=sha256_file(dst);pre=dh
                if dh==sh:action='PRESENT_IDENTICAL';detail='same SHA-256'
                elif side=='server' and patch and norm(rel).casefold()==norm(patch['target_rel']).casefold() and dh==patch['base_sha256'] and sh==patch['patched_sha256']:
                    action='PATCH';detail='SPC patch base SHA-256 matches'
                else:action='CONFLICT';detail='destination exists with different SHA-256';conflicts.append({'side':side,'rel':rel,'target_sha256':dh,'source_sha256':sh})
            rows.append({'side':side,'rel':rel,'source':str(src.resolve()),'target':str(dst),'size':src.stat().st_size,'source_sha256':sh,'target_pre_sha256':pre,'action':action,'detail':detail})
    plan={'version':6,'created_at':dt.datetime.now().astimezone().isoformat(),'bundle_dir':str(bundle.resolve()),'target_roots':{k:str(v) for k,v in target_roots.items()},'validation':validation,'spc_patch':patch,'rows':rows,'conflicts':conflicts,'safe':validation['ok'] and not conflicts}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(plan,indent=2,ensure_ascii=False),encoding='utf-8');return plan

def install_apply(plan_path:Path,out_log:Path|None=None):
    plan=load_json(plan_path)
    if not plan.get('safe'):raise SystemExit('install plan is not safe; fix validation/conflicts and regenerate it')
    txn=(plan_path.parent/'transactions'/(dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')));(txn/'backup').mkdir(parents=True,exist_ok=True)
    ops=[];status='APPLIED';error=''
    try:
        for row in plan['rows']:
            action=row['action'];src=Path(row['source']);dst=Path(row['target'])
            if action=='PRESENT_IDENTICAL':continue
            if sha256_file(src)!=row['source_sha256']:raise RuntimeError(f'source changed after plan: {src}')
            if action=='COPY':
                if dst.exists():raise RuntimeError(f'destination appeared after plan: {dst}')
                atomic_replace_from(src,dst);ops.append({'action':'COPY','target':str(dst),'installed_sha256':row['source_sha256']})
            elif action=='PATCH':
                if not dst.exists():raise RuntimeError(f'patch target disappeared: {dst}')
                pre=sha256_file(dst)
                if pre!=row['target_pre_sha256']:raise RuntimeError(f'patch target changed after plan: {dst}')
                side=row['side'];backup=txn/'backup'/side/row['rel'];backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,backup)
                atomic_replace_from(src,dst);ops.append({'action':'PATCH','target':str(dst),'installed_sha256':row['source_sha256'],'backup':str(backup),'base_sha256':pre})
            elif action=='CONFLICT':raise RuntimeError(f'unsafe conflict row reached apply: {dst}')
    except Exception as e:
        status='ROLLED_BACK_AFTER_ERROR';error=str(e)
        for op in reversed(ops):
            dst=Path(op['target'])
            if op['action']=='COPY':
                if dst.exists() and sha256_file(dst)==op['installed_sha256']:dst.unlink()
            elif op['action']=='PATCH':
                backup=Path(op['backup'])
                if backup.exists():atomic_replace_from(backup,dst)
        ops=[]
    log={'version':6,'plan':str(plan_path.resolve()),'transaction_dir':str(txn.resolve()),'status':status,'error':error,'operations':ops,'created_at':dt.datetime.now().astimezone().isoformat()}
    if out_log is None:out_log=plan_path.with_suffix('.apply.json')
    out_log.write_text(json.dumps(log,indent=2,ensure_ascii=False),encoding='utf-8')
    if status!='APPLIED':raise SystemExit(f'install failed and was rolled back: {error}')
    return log

def rollback(log_path:Path):
    log=load_json(log_path);result={'removed':[],'restored':[],'skipped':[]}
    for op in reversed(log.get('operations',[])):
        dst=Path(op['target'])
        if op['action']=='COPY':
            if dst.exists() and sha256_file(dst)==op['installed_sha256']:dst.unlink();result['removed'].append(str(dst))
            else:result['skipped'].append({'target':str(dst),'reason':'missing or changed since install'})
        elif op['action']=='PATCH':
            backup=Path(op['backup'])
            if not backup.exists():result['skipped'].append({'target':str(dst),'reason':'backup missing'});continue
            if dst.exists() and sha256_file(dst)!=op['installed_sha256']:result['skipped'].append({'target':str(dst),'reason':'target changed since install'});continue
            atomic_replace_from(backup,dst);result['restored'].append(str(dst))
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('scaffold');a.add_argument('spec');a.add_argument('--out',required=True)
    a=sub.add_parser('validate');a.add_argument('spec');a.add_argument('--config',default='summit_paths.json');a.add_argument('--out')
    a=sub.add_parser('validate-stage');a.add_argument('spec');a.add_argument('--bundle-dir',required=True);a.add_argument('--out')
    a=sub.add_parser('mirror-visuals');a.add_argument('spec');a.add_argument('--bundle-dir',required=True);a.add_argument('--out')
    a=sub.add_parser('spc-patch');a.add_argument('spec');a.add_argument('--config',default='summit_paths.json');a.add_argument('--bundle-dir',required=True);a.add_argument('--out')
    a=sub.add_parser('install-plan');a.add_argument('spec');a.add_argument('--config',default='summit_paths.json');a.add_argument('--bundle-dir',required=True);a.add_argument('--out',required=True)
    a=sub.add_parser('install-apply');a.add_argument('plan');a.add_argument('--out-log')
    a=sub.add_parser('rollback');a.add_argument('log');a.add_argument('--out')
    a=sub.add_parser('example');a.add_argument('--kind',choices=['npc','monster'],required=True);a.add_argument('--out',required=True)
    ns=ap.parse_args()
    if ns.cmd=='example':
        kind=ns.kind;ex={'kind':kind,'id':'new_character','template_server_def':'/absolute/path/to/template.'+('npc' if kind=='npc' else 'inf'),'internal_name':'NEW_CHARACTER','display_name':'Novo Personagem','model_logical':'char/'+kind+'/NewCharacter/NewCharacter.ini','level':1,'chats':['Olá!'],'localization_encoding':'cp1252'}
        if kind=='monster':ex['spawn_spm']={'weight':100,'field_spm':'GameServer/Field/example.spm'}
        else:ex['spc']={'field_spc':'GameServer/Field/example.ase.spc','x':0,'y':0,'z':0,'ax':0,'ay':0,'az':0,'record_name':'NEW_CHARACTER','record_encoding':'cp949'}
        Path(ns.out).write_text(json.dumps(ex,indent=2,ensure_ascii=False),encoding='utf-8');print(ns.out);return 0
    if ns.cmd=='install-apply':
        res=install_apply(Path(ns.plan),Path(ns.out_log) if ns.out_log else None);print(json.dumps(res,indent=2,ensure_ascii=False));return 0
    if ns.cmd=='rollback':
        res=rollback(Path(ns.log));txt=json.dumps(res,indent=2,ensure_ascii=False);print(txt)
        if ns.out:Path(ns.out).write_text(txt,encoding='utf-8')
        return 0
    spec=load_json(ns.spec)
    if ns.cmd=='scaffold':
        out=Path(ns.out);out.mkdir(parents=True,exist_ok=True);res=scaffold(spec,out)
    elif ns.cmd=='validate':res=validate(spec,load_json(ns.config))
    elif ns.cmd=='validate-stage':res=validate_stage(spec,Path(ns.bundle_dir))
    elif ns.cmd=='mirror-visuals':res=mirror_visuals(spec,Path(ns.bundle_dir))
    elif ns.cmd=='spc-patch':res=spc_patch(spec,load_json(ns.config),Path(ns.bundle_dir))
    elif ns.cmd=='install-plan':res=install_plan(spec,load_json(ns.config),Path(ns.bundle_dir),Path(ns.out))
    else:raise AssertionError(ns.cmd)
    txt=json.dumps(res,indent=2,ensure_ascii=False);print(txt)
    if getattr(ns,'out',None) and ns.cmd not in {'scaffold','install-plan'}:Path(ns.out).write_text(txt,encoding='utf-8')
    if ns.cmd in {'validate','validate-stage','mirror-visuals'} and not res.get('ok'):return 2
    if ns.cmd=='install-plan' and not res.get('safe'):return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
