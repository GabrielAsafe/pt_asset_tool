#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path


def extract_function(text:str,name='InitField')->tuple[str,int]:
    m=re.search(r'\bint\s+'+re.escape(name)+r'\s*\([^)]*\)',text)
    if not m: raise ValueError(f'{name} not found')
    b=text.find('{',m.end())
    if b<0: raise ValueError('opening brace not found')
    depth=0; i=b; string=None; esc=False; line_comment=False; block_comment=False
    while i<len(text):
        c=text[i]; n=text[i+1] if i+1<len(text) else ''
        if line_comment:
            if c=='\n': line_comment=False
            i+=1; continue
        if block_comment:
            if c=='*' and n=='/': block_comment=False; i+=2; continue
            i+=1; continue
        if string:
            if esc: esc=False
            elif c=='\\': esc=True
            elif c==string: string=None
            i+=1; continue
        if c=='/' and n=='/': line_comment=True; i+=2; continue
        if c=='/' and n=='*': block_comment=True; i+=2; continue
        if c in ('"',"'"): string=c; i+=1; continue
        if c=='{': depth+=1
        elif c=='}':
            depth-=1
            if depth==0: return text[b+1:i], text[:b+1].count('\n')+1
        i+=1
    raise ValueError('unterminated function')


def strip_cpp_line_comment(line:str)->str:
    out=[]; i=0; string=None; esc=False
    while i<len(line):
        c=line[i]; n=line[i+1] if i+1<len(line) else ''
        if string:
            out.append(c)
            if esc:esc=False
            elif c=='\\':esc=True
            elif c==string:string=None
            i+=1;continue
        if c in ('"',"'"):string=c;out.append(c);i+=1;continue
        if c=='/' and n=='/':break
        out.append(c);i+=1
    return ''.join(out)


def split_args(s:str)->list[str]:
    out=[]; start=0; depth=0; string=None; esc=False
    for i,c in enumerate(s):
        if string:
            if esc:esc=False
            elif c=='\\':esc=True
            elif c==string:string=None
            continue
        if c in ('"',"'"): string=c; continue
        if c in '([{': depth+=1
        elif c in ')]}': depth=max(0,depth-1)
        elif c==',' and depth==0:
            out.append(s[start:i].strip()); start=i+1
    out.append(s[start:].strip())
    return out


def unquote(s:str):
    s=s.strip()
    if len(s)>=2 and s[0]=='"' and s[-1]=='"':
        # Source paths only need the common C escapes used here.
        inner=s[1:-1]
        return inner.replace('\\\\','\\').replace('\\"','"')
    if s in ('0','NULL','nullptr'): return None
    return {'cpp_expr':s}


def slug(s:str)->str:
    return re.sub(r'[^a-z0-9]+','_',s.casefold()).strip('_')


def parse(source:Path):
    text=source.read_text(encoding='utf-8',errors='replace')
    try:
        body,start_line=extract_function(text,'InitFieldLegacy')
        dynamic_body,dynamic_start_line=extract_function(text,'FinalizeLegacyFieldCatalog')
        chunks=[(body,start_line),(dynamic_body,dynamic_start_line)]
    except ValueError:
        body,start_line=extract_function(text,'InitField')
        chunks=[(body,start_line)]
    maps=[]; current=None; cond=[]; unsupported=[]; globals_out={}
    for key,var in [('field_directory','szFieldDirectory'),('map_directory','szMapDirectory'),('title_directory','szTitleDirectory')]:
        mm=re.search(r'strcpy_s\('+var+r',\s*"([^"]*)"\s*\)\s*;',text)
        if mm: globals_out[key]=mm.group(1)

    def condition(): return ' && '.join(cond) if cond else None
    def op(kind,line,**kw):
        rec={'op':kind,'line':line}
        if condition(): rec['condition_cpp']=condition()
        rec.update(kw); current['operations'].append(rec); return rec

    line_stream=[]
    for chunk_body,chunk_start_line in chunks:
        line_stream.extend((chunk_start_line+offset,raw) for offset,raw in enumerate(chunk_body.splitlines(),0))
    for line_no,raw in line_stream:
        stripped=raw.strip()
        if not stripped: continue
        mm=re.match(r'#\s*ifdef\s+(.+)$',stripped)
        if mm: cond.append('defined('+mm.group(1).strip()+')'); continue
        mm=re.match(r'#\s*ifndef\s+(.+)$',stripped)
        if mm: cond.append('!defined('+mm.group(1).strip()+')'); continue
        mm=re.match(r'#\s*if\s+(.+)$',stripped)
        if mm: cond.append('('+mm.group(1).strip()+')'); continue
        if stripped.startswith('#else'):
            if cond: cond[-1]='!('+cond[-1]+')'
            continue
        if stripped.startswith('#endif'):
            if cond: cond.pop()
            continue
        code=strip_cpp_line_comment(raw).strip()
        if not code: continue
        m=re.fullmatch(r'cnt\s*=\s*(\d+)\s*;',code)
        if m:
            current={'legacy_field_code':int(m.group(1)),'operations':[],'source_line':line_no}
            maps.append(current); continue
        # The migrated legacy source increments once after the final static field
        # instead of hardcoding the historical total (53). This is catalog-count
        # bookkeeping, not a map operation.
        if re.fullmatch(r'(?:cnt\+\+|\+\+cnt)\s*;',code):
            current=None
            continue
        if current is None:
            # Initial directory setup and field-code loop are global bootstrap semantics.
            for key,var in [('field_directory','szFieldDirectory'),('map_directory','szMapDirectory'),('title_directory','szTitleDirectory')]:
                mm=re.fullmatch(r'strcpy_s\('+var+r',\s*"([^"]*)"\s*\)\s*;',code)
                if mm: globals_out[key]=mm.group(1); break
            continue
        # Function-style operations.
        m=re.fullmatch(r'sField\[cnt\]\.([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*;',code)
        if m:
            fn=m.group(1); args=split_args(m.group(2))
            if fn=='SetName':
                vals=[unquote(x) for x in args]
                op('set_name',line_no,args=vals)
                current['stage']=vals[0] if vals else None
                current['short_name']=vals[1] if len(vals)>1 else None
            elif fn=='AddStageObject':
                vals=[unquote(x) for x in args]
                op('add_stage_object',line_no,args=vals)
                current.setdefault('stage_objects',[]).append(vals)
            elif fn=='SetCenterPos':
                op('set_center',line_no,args=args); current['center_cpp']=args
            elif fn=='AddStartPoint':
                op('add_start_point',line_no,args=args); current.setdefault('start_points_cpp',[]).append(args)
            elif fn=='AddGate':
                op('add_gate',line_no,args=args); current.setdefault('gates_cpp',[]).append(args)
            elif fn=='AddWarpGate':
                op('add_warp_gate',line_no,args=args); current.setdefault('warp_operations_cpp',[]).append({'kind':'in','args':args,'line':line_no})
            elif fn=='AddWarpOutGate':
                op('add_warp_out_gate',line_no,args=args); current.setdefault('warp_operations_cpp',[]).append({'kind':'out','args':args,'line':line_no})
            elif fn=='AddAmbientPos':
                op('add_ambient',line_no,args=args); current.setdefault('ambient_cpp',[]).append(args)
            else:
                op('call',line_no,function=fn,args=args)
            continue
        # Back-image indexed assignment.
        m=re.fullmatch(r'sField\[cnt\]\.BackImageCode\[(\d+)\]\s*=\s*(.+?)\s*;',code)
        if m:
            idx=int(m.group(1)); expr=m.group(2).strip(); op('set_back_image',line_no,index=idx,cpp_expr=expr)
            arr=current.setdefault('back_images_cpp',[None,None,None]);
            while len(arr)<=idx:arr.append(None)
            arr[idx]=expr; continue
        # Generic direct field assignment.
        m=re.fullmatch(r'sField\[cnt\]\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*;',code)
        if m:
            prop=m.group(1); expr=m.group(2).strip(); op('set_property',line_no,property=prop,cpp_expr=expr)
            current.setdefault('properties_cpp',{})[prop]=expr; continue
        # Modifier of last-created warp gate.
        m=re.fullmatch(r'sField\[cnt\]\.WarpGate\[sField\[cnt\]\.WarpGateActiveNum\]\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*;',code)
        if m:
            op('set_active_warp_property',line_no,property=m.group(1),cpp_expr=m.group(2).strip())
            current.setdefault('warp_operations_cpp',[]).append({'kind':'modifier','property':m.group(1),'value_cpp':m.group(2).strip(),'line':line_no})
            continue
        # A few custom-map control statements contain sField[cnt] inside an if.
        if 'sField[cnt]' in code:
            rec={'line':line_no,'code':code}
            if condition():rec['condition_cpp']=condition()
            unsupported.append(rec); current.setdefault('unsupported_cpp',[]).append(rec)

    for m in maps:
        short=m.get('short_name')
        if isinstance(short,str) and short: m['id']='map.'+slug(short)
        elif isinstance(m.get('stage'),str): m['id']='map.'+slug(Path(m['stage'].replace('\\','/')).stem)
        else:m['id']=f'map.legacy_{m["legacy_field_code"]}'
    return {'schema':'summit.legacy-map-shadow/v1','source':source.as_posix(),'globals':globals_out,'map_count':len(maps),'maps':maps,'unsupported_sfield_statements':unsupported}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('sources',nargs='+',type=Path);ap.add_argument('--out-dir',type=Path,required=True);a=ap.parse_args()
    a.out_dir.mkdir(parents=True,exist_ok=True)
    summary=[]
    for src in a.sources:
        doc=parse(src)
        dst=a.out_dir/(src.stem+'.maps.json')
        dst.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        summary.append({'source':str(src),'output':str(dst),'maps':doc['map_count'],'unsupported':len(doc['unsupported_sfield_statements'])})
        print(f'{src}: maps={doc["map_count"]} unsupported={len(doc["unsupported_sfield_statements"])} -> {dst}')
    (a.out_dir/'index.json').write_text(json.dumps({'schema':'summit.legacy-map-shadow-index/v1','sources':summary},indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
