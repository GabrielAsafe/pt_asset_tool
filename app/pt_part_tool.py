#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

FORMAT='PT_PARTICLE_PART_READONLY_V2'
REF_RE=re.compile("(?ix)(?:[\\\"']([^\\\"'\\r\\n]+\\.(?:tga|bmp|png|dds|jpg|jpeg|smd|ase|part|wav|ogg|mp3))[\\\"']|([A-Za-z0-9_./\\\\()@+\\-\\[\\] ]+\\.(?:tga|bmp|png|dds|jpg|jpeg|smd|ase|part|wav|ogg|mp3)))")
ASSIGN_RE=re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=|:|\s)\s*(.*?)\s*$')
INT_RE=re.compile(r'^[+-]?\d+$')
FLOAT_RE=re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
VEC_RE=re.compile(r'^\s*[\[(]?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*[, ]+\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:[, ]+\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))?\s*(?:[, ]+\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))?\s*[\])]?$')


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def detect(data: bytes):
    if b'\x00' in data:
        return 'BINARY_NUL',''
    try:
        return 'ASCII',data.decode('ascii')
    except UnicodeDecodeError:
        pass
    try:
        return 'UTF8',data.decode('utf-8')
    except UnicodeDecodeError:
        return 'LATIN1',data.decode('latin-1')


def eol(data: bytes) -> str:
    crlf=data.count(b'\r\n'); rest=data.replace(b'\r\n',b'')
    lf=rest.count(b'\n'); cr=rest.count(b'\r')
    n=sum(bool(x) for x in (crlf,lf,cr))
    if n==0:return 'NONE'
    if n>1:return 'MIXED'
    return 'CRLF' if crlf else ('LF' if lf else 'CR')


def strip_comments_and_strings(line: str) -> str:
    out=[]; quote=None; i=0
    while i < len(line):
        ch=line[i]
        if quote:
            if ch=='\\' and i+1 < len(line):
                out.extend('  '); i+=2; continue
            if ch==quote: quote=None
            out.append(' '); i+=1; continue
        if ch in ('"', "'"):
            quote=ch; out.append(' '); i+=1; continue
        if line.startswith('//', i):
            break
        if ch in ('#',';') and not ''.join(out).strip():
            break
        out.append(ch); i+=1
    return ''.join(out)


def split_assignment(line: str):
    s=line.strip()
    if not s or s.startswith(('{','}','//','#',';')):
        return None
    m=ASSIGN_RE.match(line)
    if not m:
        return None
    key=m.group(1); value=m.group(2).strip()
    if not value:
        return None
    return key,value


def value_kind(value: str) -> str:
    v=value.strip().rstrip(',')
    low=v.lower()
    if low in {'true','false','on','off','yes','no'}:
        return 'BOOL'
    if INT_RE.fullmatch(v):
        return 'INT'
    if FLOAT_RE.fullmatch(v):
        return 'FLOAT'
    m=VEC_RE.fullmatch(v)
    if m:
        n=sum(x is not None for x in m.groups())
        if n in (2,3,4): return f'VEC{n}'
    if (len(v)>=2 and v[0]==v[-1] and v[0] in ('"',"'")):
        return 'STRING'
    if any(ext in low for ext in ('.tga','.bmp','.png','.dds','.jpg','.jpeg','.smd','.ase','.part','.wav','.ogg','.mp3')):
        return 'PATHLIKE'
    return 'TOKEN'


@dataclass
class Analysis:
    format:str; relative_path:str; size:int; sha256:str; text_kind:str; eol:str
    line_count:int; blank_lines:int; comment_lines:int; brace_open_count:int
    brace_close_count:int; max_brace_depth:int; assignment_count:int; key_counts:dict
    key_value_kinds:dict; references:list; block_headers:list; parse_status:str


def analyze_bytes(data: bytes, rel: str) -> Analysis:
    kind,text=detect(data)
    if kind=='BINARY_NUL':
        return Analysis(FORMAT,rel,len(data),sha(data),kind,eol(data),0,0,0,0,0,0,0,{}, {}, [], [],'BLOCKED_BINARY_NUL')
    lines=text.splitlines(); blank=comments=op=cl=depth=maxdepth=0
    keys=Counter(); kinds=defaultdict(Counter); refs=[]; block_headers=[]
    for no,line in enumerate(lines,1):
        s=line.strip()
        if not s:
            blank+=1; continue
        if s.startswith(('//','#',';')):
            comments+=1
        code=strip_comments_and_strings(line)
        # block header: token(s) immediately before an opening brace
        if '{' in code:
            before=code.split('{',1)[0].strip()
            if before:
                block_headers.append(before)
        opens=code.count('{'); closes=code.count('}')
        op+=opens; cl+=closes
        depth += opens
        maxdepth=max(maxdepth,depth)
        depth -= closes
        assignment=split_assignment(line)
        if assignment:
            key,value=assignment
            keys[key]+=1; kinds[key][value_kind(value)]+=1
        for rm in REF_RE.finditer(line):
            raw=(rm.group(1) or rm.group(2) or '').strip()
            norm=re.sub(r'/+', '/', raw.strip('"\'').replace('\\','/').strip())
            if norm:
                refs.append({'line':no,'raw':raw,'normalized':norm,'extension':Path(norm).suffix.lower()})
    if depth != 0 or op != cl:
        status='REVIEW_UNBALANCED_BRACES'
    elif depth < 0:
        status='REVIEW_NEGATIVE_BRACE_DEPTH'
    else:
        status='PASS_LEXICAL'
    return Analysis(FORMAT,rel,len(data),sha(data),kind,eol(data),len(lines),blank,comments,op,cl,maxdepth,
                    sum(keys.values()),dict(sorted(keys.items())),
                    {k:dict(v) for k,v in sorted(kinds.items())},refs,block_headers,status)


def analyze_file(p: Path, root: Path) -> Analysis:
    return analyze_bytes(p.read_bytes(),p.relative_to(root).as_posix())


def iter_parts(root: Path):
    for dp,dn,fn in os.walk(root):
        dn.sort(key=str.casefold)
        for n in sorted(fn,key=str.casefold):
            if n.lower().endswith('.part'):
                yield Path(dp)/n


def write_json(p: Path, obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def schema_fingerprint(a: Analysis) -> str:
    payload={
        'keys':sorted(a.key_counts),
        'kinds':{k:sorted(v) for k,v in a.key_value_kinds.items()},
        'blocks':sorted(set(a.block_headers)),
    }
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]


def census(root: Path):
    rows=[]; kinds=Counter(); eols=Counter(); stats=Counter(); refs=Counter(); keys=Counter(); schemas=Counter()
    anomalies=[]
    for p in iter_parts(root):
        a=analyze_file(p,root); d=asdict(a); d['schema_fingerprint']=schema_fingerprint(a); rows.append(d)
        kinds[a.text_kind]+=1; eols[a.eol]+=1; stats[a.parse_status]+=1; keys.update(a.key_counts); schemas[d['schema_fingerprint']]+=1
        if a.parse_status!='PASS_LEXICAL' or a.eol!='CRLF':
            anomalies.append({'asset':a.relative_path,'parse_status':a.parse_status,'eol':a.eol})
        for r in a.references: refs[r['extension']]+=1
    return {'format':'PT_PARTICLE_PART_CENSUS_V2','status':'PASS' if not stats['BLOCKED_BINARY_NUL'] else 'REVIEW',
            'asset_count':len(rows),'text_kind_counts':dict(kinds),'eol_counts':dict(eols),'parse_status_counts':dict(stats),
            'reference_extension_counts':dict(refs),'top_lexical_keys':keys.most_common(200),'schema_count':len(schemas),
            'top_schema_fingerprints':schemas.most_common(50),'anomalies':anomalies,'rows':rows,
            'production_authorized':False,'client_write_authorized':False,'client_modified':False}


def profile(root: Path):
    key_freq=Counter(); key_kinds=defaultdict(Counter); block_freq=Counter(); schemas=defaultdict(list); refs=Counter(); anomalies=[]
    total=0
    for p in iter_parts(root):
        a=analyze_file(p,root); total+=1; fp=schema_fingerprint(a); schemas[fp].append(a.relative_path)
        key_freq.update(a.key_counts)
        for k,kv in a.key_value_kinds.items(): key_kinds[k].update(kv)
        block_freq.update(a.block_headers)
        for r in a.references: refs[r['extension']]+=1
        if a.parse_status!='PASS_LEXICAL' or a.eol!='CRLF': anomalies.append({'asset':a.relative_path,'parse_status':a.parse_status,'eol':a.eol,'brace_open_count':a.brace_open_count,'brace_close_count':a.brace_close_count})
    schema_rows=sorted(({'fingerprint':fp,'asset_count':len(paths),'representatives':paths[:5]} for fp,paths in schemas.items()),key=lambda x:(-x['asset_count'],x['fingerprint']))
    return {'format':'PT_PARTICLE_PART_SEMANTIC_PROFILE_V1','status':'PASS','asset_count':total,'unique_key_count':len(key_freq),
            'unique_block_header_count':len(block_freq),'schema_count':len(schemas),'top_keys':key_freq.most_common(250),
            'key_value_kinds':{k:dict(v) for k,v in sorted(key_kinds.items())},'top_block_headers':block_freq.most_common(100),
            'reference_extension_counts':dict(refs),'schemas':schema_rows,'anomalies':anomalies,
            'editing_authorized':False,'production_authorized':False,'client_write_authorized':False}


def noop_one(src: Path, root: Path, build: Path):
    data=src.read_bytes(); rel=src.relative_to(root)
    out=build/'part_roundtrip_v2'/rel; out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(data)
    cand=out.read_bytes()
    return {'asset':rel.as_posix(),'status':'PASS' if cand==data else 'FAIL','byte_identical':cand==data,
            'source_sha256':sha(data),'candidate_sha256':sha(cand),'candidate':str(out),'client_modified':False}


def main():
    ap=argparse.ArgumentParser(description='PT Asset Tool R14 .part particle read-only + semantic profiling')
    sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('census'); p.add_argument('--client-root',required=True); p.add_argument('--out',default='')
    p=sub.add_parser('profile'); p.add_argument('--client-root',required=True); p.add_argument('--out',default='')
    p=sub.add_parser('inspect'); p.add_argument('--client-root',required=True); p.add_argument('asset')
    p=sub.add_parser('roundtrip-corpus'); p.add_argument('--client-root',required=True); p.add_argument('--build-root',default='pt_build/devtest')
    a=ap.parse_args(); root=Path(a.client_root).expanduser().resolve()
    if a.cmd=='census':
        r=census(root); out=Path(a.out) if a.out else Path('pt_build/devtest/part_census_v2/result.json'); write_json(out,r)
        print(json.dumps({k:r[k] for k in ['status','asset_count','text_kind_counts','eol_counts','parse_status_counts','reference_extension_counts','schema_count']}|{'anomaly_count':len(r['anomalies']),'report':str(out)},indent=2,ensure_ascii=False))
    elif a.cmd=='profile':
        r=profile(root); out=Path(a.out) if a.out else Path('pt_build/devtest/part_profile/result.json'); write_json(out,r)
        print(json.dumps({'status':r['status'],'asset_count':r['asset_count'],'unique_key_count':r['unique_key_count'],'unique_block_header_count':r['unique_block_header_count'],'schema_count':r['schema_count'],'anomaly_count':len(r['anomalies']),'reference_extension_counts':r['reference_extension_counts'],'report':str(out)},indent=2,ensure_ascii=False))
    elif a.cmd=='inspect':
        print(json.dumps(asdict(analyze_file(root/a.asset,root)),indent=2,ensure_ascii=False))
    else:
        build=Path(a.build_root).resolve(); rows=[noop_one(p,root,build) for p in iter_parts(root)]; f=[x for x in rows if x['status']!='PASS']
        r={'format':'PT_PARTICLE_PART_NOOP_CORPUS_V2','status':'PASS' if not f else 'FAIL','asset_count':len(rows),'pass_count':len(rows)-len(f),'failure_count':len(f),'rows':rows,'client_modified':False,'client_write_authorized':False,'production_authorized':False}
        out=build/'part_roundtrip_v2/corpus_result.json'; write_json(out,r)
        print(json.dumps({k:r[k] for k in ['status','asset_count','pass_count','failure_count']}|{'report':str(out)},indent=2))
if __name__=='__main__': main()
