from __future__ import annotations
import hashlib, json, struct
from collections import Counter
from pathlib import Path

HEADER=b'SMD Model data Ver 0.62'
SH,SI,SO=556,40,2236
SV,SF,ST,SR,SP,SS,SM=24,36,32,20,16,16,64
O_PHYS,O_NV,O_NF,O_NT,O_NAME,O_NR,O_NP,O_NS=16,84,88,92,172,684,688,692
F_TEX=32; T_U,T_V,T_NEXT=0,12,28


def _i32(b,o): return struct.unpack_from('<i',b,o)[0]
def _u32(b,o): return struct.unpack_from('<I',b,o)[0]
def _cs(b): return b.split(b'\0',1)[0].decode('latin1','replace')
def _sha(b): return hashlib.sha256(b).hexdigest()


def _parse(data:bytes):
    if len(data)<SH or not data.startswith(HEADER):
        raise ValueError('not SMD Model data Ver 0.62')
    n=_i32(data,24); mat=_i32(data,28); mat_point=_i32(data,32); first_obj=_i32(data,36)
    infos=[]
    for i in range(n):
        o=SH+i*SI
        infos.append({'index':i,'name':_cs(data[o:o+32]),'length':_i32(data,o+32),'start':_i32(data,o+36)})
    objs={}
    object_list=[]
    for inf in infos:
        raw=data[inf['start']:inf['start']+SO]
        name=_cs(raw[O_NAME:O_NAME+32])
        if name!=inf['name']:
            raise ValueError(f'node mismatch {inf["name"]}/{name}')
        nv,nf,nt,nr,np,ns=[_i32(raw,o) for o in (O_NV,O_NF,O_NT,O_NR,O_NP,O_NS)]
        phys=_u32(raw,O_PHYS)!=0
        vo=inf['start']+SO; fo=vo+nv*SV; to=fo+nf*SF
        verts=[struct.unpack_from('<6i',data,vo+i*SV) for i in range(nv)]
        texbase=_u32(raw,12)
        faces=[]
        for fi in range(nf):
            off=fo+fi*SF
            a,b,c,mid=struct.unpack_from('<4H',data,off)
            ptr=_u32(data,off+F_TEX)
            # PT_RC6_8_ZERO_TEXLINK_FACE
            # Runtime/importer semantics: a NULL serialized lpTexLink means the
            # face has no TexLink chain.  Do not reinterpret it relative to the
            # object's old TexLink base.
            if ptr == 0:
                faces.append({'verts':(a,b,c),'material':mid,'uv_layers':[]})
                continue
            delta=ptr-texbase
            if delta<0 or delta%ST: raise ValueError(f'{name} bad tex ptr face {fi} ptr=0x{ptr:08X} base=0x{texbase:08X}')
            ti=delta//ST
            if not 0<=ti<nt: raise ValueError(f'{name} tex ptr OOB face {fi} index={ti} count={nt}')
            chain=[]; cur=ti; seen=set()
            while True:
                if cur in seen: raise ValueError('texlink cycle')
                seen.add(cur); oo=to+cur*ST
                us=struct.unpack_from('<3f',data,oo+T_U); vs=struct.unpack_from('<3f',data,oo+T_V)
                chain.append(tuple((round(us[j],7),round(vs[j],7)) for j in range(3)))
                nxt=_u32(data,oo+T_NEXT)
                if not nxt: break
                dd=nxt-texbase
                if dd<0 or dd%ST: raise ValueError('next tex ptr invalid')
                cur=dd//ST
            faces.append({'verts':(a,b,c),'material':mid,'uv_layers':chain})
        phys_off=to+nt*ST+nr*SR+np*SP+ns*SS+nr*SM
        physique_names=[]
        if phys:
            for pi in range(nv):
                physique_names.append(_cs(data[phys_off+pi*32:phys_off+(pi+1)*32]))
        end=phys_off+(nv*32 if phys else 0)
        if end!=inf['start']+inf['length']:
            raise ValueError(f'{name} block length')
        obj={'index':inf['index'],'table_name':inf['name'],'name':name,
             'vertices':verts,'faces':faces,'nv':nv,'nf':nf,'nt':nt,
             'nr':nr,'np':np,'ns':ns,'phys':phys,'physique_names':physique_names,'vertex_offset':vo,
             'block':data[inf['start']:inf['start']+inf['length']]}
        object_list.append(obj)
        # Backwards-compatible name lookup. Legacy authoring callers address
        # objects by NodeName and therefore remain fail-closed/ambiguous when
        # the physical file contains duplicate names. Corpus-wide structural
        # audits must use object_list so duplicate physical blocks are not lost.
        objs[name]=obj
    return {'n':n,'mat_count':mat,'mat_region':data[mat_point:first_obj],
            'infos':infos,'objects':objs,'object_list':object_list}


def _face_signature(obj):
    out=[]
    for f in obj['faces']:
        layer=f['uv_layers'][0] if f['uv_layers'] else ((0,0),(0,0),(0,0))
        corners=sorted((f['verts'][i],layer[i]) for i in range(3))
        out.append((f['material'],tuple(corners),len(f['uv_layers'])))
    return Counter(out)


def compare_static_roundtrip(source:Path, output:Path, target:str, witness_report:Path, report_path:Path|None=None):
    sb=Path(source).read_bytes(); ob=Path(output).read_bytes()
    s=_parse(sb); o=_parse(ob)
    witness=json.loads(Path(witness_report).read_text(encoding='utf-8'))
    errors=[]; details={}
    if s['n']!=o['n']: errors.append('OBJECT_COUNT')
    if s['mat_count']!=o['mat_count']: errors.append('MATERIAL_COUNT')
    if s['mat_region']!=o['mat_region']: errors.append('MATERIAL_REGION_BYTES')
    if set(s['objects'])!=set(o['objects']): errors.append('OBJECT_NAMES')
    if target not in s['objects'] or target not in o['objects']: errors.append('TARGET_MISSING')
    witness_object=str(witness.get('object') or '')
    if witness_object.lower()!=target.lower(): errors.append('WITNESS_TARGET_MISMATCH')
    non_target=[]
    for name in set(s['objects']) & set(o['objects']):
        if name==target: continue
        if s['objects'][name]['block']!=o['objects'][name]['block']: non_target.append(name)
    if non_target: errors.append('NON_TARGET_BLOCK_CHANGED')

    if target in s['objects'] and target in o['objects']:
        x,y=s['objects'][target],o['objects'][target]
        pos_s=[tuple(v[:3]) for v in x['vertices']]
        pos_o=[tuple(v[:3]) for v in y['vertices']]
        if [x['nv'],x['nf'],x['nt']] != [y['nv'],y['nf'],y['nt']]: errors.append('COUNTS')
        if _face_signature(x)!=_face_signature(y): errors.append('FACE_UV_MATERIAL')
        if [x['nr'],x['np'],x['ns']] != [y['nr'],y['np'],y['ns']]: errors.append('OBJECT_LOCAL_ANIMATION_COUNTS')
        if x['phys'] or y['phys']: errors.append('PHYSIQUE_MODE')

        expected={}
        before_mismatch=[]
        for row in witness.get('changed_vertices') or []:
            vi=int(row['vertex'])
            if not 0<=vi<len(pos_s):
                errors.append('WITNESS_VERTEX_OOB'); continue
            before=tuple(int(round(float(c)*256.0)) for c in row['before'])
            after=tuple(int(round(float(c)*256.0)) for c in row['after'])
            expected[vi]=after
            if before!=pos_s[vi]: before_mismatch.append({'vertex':vi,'report':before,'source':pos_s[vi]})
        if before_mismatch: errors.append('WITNESS_SOURCE_MISMATCH')
        if not expected: errors.append('WITNESS_EMPTY')
        effective={i:p for i,p in expected.items() if p!=pos_s[i]}
        if not effective: errors.append('WITNESS_QUANTIZED_AWAY')
        actual_changed={i for i,(a,b) in enumerate(zip(pos_s,pos_o)) if a!=b}
        expected_changed=set(effective)
        if actual_changed != expected_changed: errors.append('CHANGED_VERTEX_SET')
        wrong=[]
        for vi,exp in effective.items():
            if pos_o[vi]!=exp: wrong.append({'vertex':vi,'expected':exp,'actual':pos_o[vi]})
        if wrong: errors.append('WITNESS_POSITION_VALUE')
        untouched_wrong=[i for i in range(len(pos_s)) if i not in expected_changed and pos_s[i]!=pos_o[i]]
        if untouched_wrong: errors.append('UNTOUCHED_VERTEX_CHANGED')
        if len(sb) != len(ob): errors.append('FILE_SIZE')
        allowed_ranges=[]
        allowed_bytes=set()
        base=int(x['vertex_offset'])
        for vi in sorted(expected_changed):
            lo=base+vi*SV; hi=lo+12
            allowed_ranges.append([lo,hi])
            allowed_bytes.update(range(lo,hi))
        diff_bytes=[i for i,(aa,bb) in enumerate(zip(sb,ob)) if aa!=bb]
        if len(sb)!=len(ob):
            diff_outside=['SIZE_MISMATCH']
        else:
            diff_outside=[i for i in diff_bytes if i not in allowed_bytes]
        if diff_outside: errors.append('NON_XYZ_BYTES_CHANGED')
        if sb==ob: errors.append('BYTE_IDENTICAL_AFTER_EDIT')
        deltas=[]
        for vi in sorted(expected_changed):
            d=tuple(pos_o[vi][j]-pos_s[vi][j] for j in range(3))
            deltas.append({'vertex':vi,'source_fixed':pos_s[vi],'output_fixed':pos_o[vi],'delta_fixed':d,
                           'delta_units':tuple(round(v/256.0,7) for v in d)})
        details={
            'source_counts':[x['nv'],x['nf'],x['nt']], 'output_counts':[y['nv'],y['nf'],y['nt']],
            'face_uv_material_semantic_exact':_face_signature(x)==_face_signature(y),
            'source_animation_keys':[x['nr'],x['np'],x['ns']], 'output_animation_keys':[y['nr'],y['np'],y['ns']],
            'source_physique':x['phys'],'output_physique':y['phys'],
            'witness_reported_vertices':sorted(expected), 'expected_changed_vertices':sorted(expected_changed),
            'actual_changed_vertices':sorted(actual_changed), 'changed_vertex_deltas':deltas,
            'witness_source_mismatch':before_mismatch, 'wrong_changed_positions':wrong,
            'untouched_wrong_vertices':untouched_wrong,
            'allowed_xyz_byte_ranges':allowed_ranges,
            'diff_byte_count':len(diff_bytes),
            'diff_bytes_outside_witness_xyz':diff_outside,
            'non_xyz_bytes_byte_identical':not bool(diff_outside) and len(sb)==len(ob),
            'object_local_animation_preserved_byte_identical':([x['nr'],x['np'],x['ns']]==[y['nr'],y['np'],y['ns']] and not bool(diff_outside) and len(sb)==len(ob)),
        }
    result={'tool':'PT_STATIC_ROUNDTRIP_COMPARE_V1','source':str(source),'output':str(output),
            'source_sha256':_sha(sb),'output_sha256':_sha(ob),'target':target,
            'details':details,'non_target_changed':non_target,'errors':errors,
            'byte_identical':sb==ob,'intentional_geometry_edit':True,'client_modified':False,
            'check':'PASS' if not errors else 'FAIL'}
    if report_path:
        Path(report_path).parent.mkdir(parents=True,exist_ok=True)
        Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if errors:
        raise RuntimeError('static roundtrip compare failed: '+','.join(errors))
    return result
