#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import os
import re
import shlex
import sqlite3
import sys
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "2.0.0"
ASSET_EXT_RE = re.compile(r"(?i)\.(ase|smd|smb|inx|bmp|tga|dds|png|jpg|jpeg|gif|wav|bgm|mp3|ogg|ini|inf|txt|npc|spm|spp|spc|part|scfg|smap|sfld|sres|sloc|sgcf|scsp)$")
ENTITY_ID_RE = re.compile(r"^(monster|npc|item|quest|map|model|text)\.[A-Za-z0-9_.-]+$", re.I)
ITEM_CODE_RE = re.compile(r"^[A-Z]{1,3}[0-9]{2,4}$", re.I)

BALANCE_COLUMNS = {
    "monster": ["name","level","life","attack_damage","attack_rating","attack_speed","attack_range","absorption","skill_damage","skill_rating","defence","block","stun_percent","move_speed","experience","model_file","monster_race","size","fall_item_max"],
    "item": ["code","name","english_name","level","price","weight","attack_damage","attack_rating","attack_speed","critical","defence","durability","strength","spirit","talent","agility","health","job","linked_file"],
    "npc": ["name","state","event_code","model_file","model_scale","linked_file"],
    "map": ["logical_path","limit_max","open_limit","actor_count","boss_count","start_point_count"],
    "quest": ["name","title","level","kind"],
}


def jdump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def jload(s, default=None):
    try:
        return json.loads(s)
    except Exception:
        return default


def norm_path(s: str) -> str:
    s = str(s or "").replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    return s.strip().lstrip("./").casefold()


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).strip().casefold()
    return re.sub(r"\s+", " ", s)


def extract_family(path: str):
    n = norm_path(path)
    m = re.search(r"(?:^|/)char/(monster|npc|player|character)/([^/]+)(?:/|$)", n)
    if not m:
        return None
    kind = m.group(1)
    if kind == "character": kind = "player"
    return kind, m.group(2)


def scalar_name(fields: dict, fallback="") -> str:
    for k in ("name", "display_name", "english_name", "title"):
        v = fields.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return fallback or ""


def semantic_fields(payload: dict, entity_type: str) -> dict:
    sem = payload.get("semantic") if isinstance(payload, dict) else None
    if isinstance(sem, dict) and isinstance(sem.get("fields"), dict):
        return dict(sem["fields"])
    if entity_type == "map" and isinstance(payload, dict):
        fields = {}
        for k in ("logical_path", "limit_max", "open_limit"):
            if k in payload:
                fields[k] = payload[k]
        if isinstance(payload.get("actors"), list):
            fields["actor_count"] = len(payload["actors"])
        if isinstance(payload.get("bosses"), list):
            fields["boss_count"] = len(payload["bosses"])
        if isinstance(payload.get("points"), list):
            fields["start_point_count"] = len(payload["points"])
        return fields
    return {}


def classify_subtype(payload: dict, entity_type: str) -> str:
    if not isinstance(payload, dict):
        return entity_type
    kind = payload.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    schema = payload.get("schema")
    if isinstance(schema, str) and schema:
        return schema
    return entity_type


def is_schema_document(entity_id: str, origin: str, payload: dict) -> bool:
    if "/schemas/" in norm_path(origin) or str(entity_id).endswith(".schema"):
        return True
    return isinstance(payload, dict) and "$schema" in payload and "properties" in payload and "semantic" not in payload


def flatten_fields(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                yield key, v
            else:
                yield key, v
    else:
        yield prefix, obj


def collect_token_map(v1: sqlite3.Connection):
    votes = collections.defaultdict(collections.Counter)
    type_hints = collections.defaultdict(collections.Counter)
    cmd_votes = collections.defaultdict(collections.Counter)
    q = "SELECT entity_type,payload_json FROM entities"
    for et, pjson in v1.execute(q):
        payload = jload(pjson, {})
        if not isinstance(payload, dict) or is_schema_document("", "", payload):
            continue
        fields = semantic_fields(payload, et)
        for k, v in fields.items():
            if isinstance(v, bool): typ="bool"
            elif isinstance(v, int): typ="int"
            elif isinstance(v, float): typ="float"
            elif isinstance(v, str): typ="str"
            elif isinstance(v, list): typ="list"
            elif isinstance(v, dict): typ="dict"
            else: typ="other"
            type_hints[(et,k)][typ] += 1
        sem = payload.get("semantic") or {}
        for d in sem.get("directives", []) or []:
            if not isinstance(d, dict):
                continue
            key = d.get("key")
            hx = d.get("legacy_token_hex")
            tok = d.get("legacy_token")
            if key and hx:
                votes[hx.casefold()][key] += 1
            if key and tok:
                cmd_votes[str(tok)][key] += 1
    token_map = {hx: c.most_common(1)[0][0] for hx,c in votes.items()}
    cmd_map = {cmd: c.most_common(1)[0][0] for cmd,c in cmd_votes.items()}
    hints = {k: c.most_common(1)[0][0] for k,c in type_hints.items()}
    return token_map, cmd_map, hints


def split_values(s: str):
    s = str(s or "").strip()
    if not s:
        return []
    try:
        return shlex.split(s, posix=False)
    except Exception:
        return s.split()


def atom(v: str):
    v = str(v).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    if re.fullmatch(r"[-+]?\d+", v):
        try: return int(v)
        except Exception: pass
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", v):
        try: return float(v)
        except Exception: pass
    return v


def parse_directive_value(raw: str, hint: str | None):
    s = str(raw or "").strip()
    if not s:
        return "" if hint == "str" else []
    if hint == "str":
        if len(s)>=2 and s[0]==s[-1] and s[0] in "\"'": return s[1:-1]
        return s
    parts = split_values(s)
    vals = [atom(x) for x in parts]
    if hint in ("int","float") and vals:
        return vals[0]
    if hint == "list":
        return vals
    if len(vals) == 1:
        return vals[0]
    return vals


def decode_hex_value(hexs: str, fallback: str = "") -> str:
    if not hexs:
        return fallback
    try:
        b=bytes.fromhex(hexs)
    except Exception:
        return fallback
    for enc in ("utf-8","cp949","cp1252","latin1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return fallback


def normalize_scfg_directives(entity_type, directives, token_map, cmd_map, hints):
    grouped = collections.defaultdict(list)
    unknown = []
    for d in directives or []:
        hx = str(d.get("cmd_hex") or "").casefold()
        cmd = str(d.get("cmd") or "")
        key = token_map.get(hx) or cmd_map.get(cmd)
        if not key:
            unknown.append({"cmd":cmd,"cmd_hex":hx,"values":d.get("values","")})
            continue
        raw_value=decode_hex_value(str(d.get("values_hex") or ""), str(d.get("values") or ""))
        grouped[key].append(parse_directive_value(raw_value, hints.get((entity_type,key))))
    fields = {}
    for k, vals in grouped.items():
        if len(vals) == 1:
            fields[k] = vals[0]
        else:
            fields[k] = {"$repeated": vals}
    if unknown:
        fields["_unknown_directives"] = unknown
    return fields


def derive_edges(entity_type, entity_id, fields, payload, source, version_key):
    out=[]
    def add(rel, target_kind, target, confidence="exact", meta=None):
        if target in (None, "", []): return
        out.append((entity_type,entity_id,version_key,rel,target_kind,str(target),source,confidence,jdump(meta or {})))

    # High-value semantic relations.
    for k in ("model_file","linked_file"):
        v=fields.get(k)
        if isinstance(v,str): add(k,"asset",v,"exact")
    mid=fields.get("model_config_id")
    if isinstance(mid,str): add("model_config","entity",mid,"exact")

    # Monster drop relations.
    fi=fields.get("fall_item")
    if isinstance(fi,dict) and isinstance(fi.get("$repeated"),list):
        for row in fi["$repeated"]:
            vals=row if isinstance(row,list) else [row]
            rate=vals[0] if vals and isinstance(vals[0],(int,float)) else None
            for code in vals[1:] if rate is not None else vals:
                if isinstance(code,str) and ITEM_CODE_RE.fullmatch(code) and code.casefold() not in ("money","coin"):
                    add("drops","item_code",code.upper(),"semantic",{"weight":rate})

    if isinstance(payload,dict):
        if isinstance(payload.get("actors"),list):
            for a in payload["actors"]:
                if isinstance(a,dict) and a.get("monster_id"):
                    add("spawns","monster",a["monster_id"],a.get("resolution","exact"),{"weight":a.get("weight")})
        if isinstance(payload.get("bosses"),list):
            for b in payload["bosses"]:
                if not isinstance(b,dict): continue
                if b.get("master_monster_id"):
                    add("boss","monster",b["master_monster_id"],b.get("master_resolution","exact"),{"hours":b.get("open_hours")})
                if b.get("slave_monster_id"):
                    add("boss_slave","monster",b["slave_monster_id"],b.get("slave_resolution","exact"),{"count":b.get("slave_count")})

    # Generic asset/entity references in semantic fields.
    def walk(v, key=""):
        if isinstance(v,dict):
            for kk,vv in v.items(): walk(vv, f"{key}.{kk}" if key else kk)
        elif isinstance(v,list):
            for vv in v: walk(vv,key)
        elif isinstance(v,str):
            vv=v.strip().strip('"')
            if ASSET_EXT_RE.search(vv): add("references","asset",vv,"heuristic",{"field":key})
            elif ENTITY_ID_RE.fullmatch(vv): add("references","entity",vv,"heuristic",{"field":key})
    walk(fields)
    return out


def open_v1(path: Path):
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)


def init_v2(db: sqlite3.Connection):
    db.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE sources(id INTEGER PRIMARY KEY,name TEXT,root TEXT,kind TEXT);
    CREATE TABLE canonical_entities(
      entity_type TEXT, entity_id TEXT PRIMARY KEY, subtype TEXT, name TEXT, origin_path TEXT,
      fields_json TEXT, payload_json TEXT, source_name TEXT
    );
    CREATE INDEX ce_type ON canonical_entities(entity_type);
    CREATE INDEX ce_name ON canonical_entities(name);
    CREATE TABLE entity_versions(
      version_key TEXT PRIMARY KEY, source_name TEXT, source_kind TEXT, provenance_kind TEXT,
      entity_type TEXT, source_entity_id TEXT, canonical_id TEXT, match_method TEXT,
      name TEXT, origin_path TEXT, pack_sha256 TEXT, fields_json TEXT, raw_json TEXT
    );
    CREATE INDEX ev_type ON entity_versions(entity_type);
    CREATE INDEX ev_canonical ON entity_versions(canonical_id);
    CREATE INDEX ev_source ON entity_versions(source_name);
    CREATE TABLE attributes(
      version_key TEXT, entity_type TEXT, entity_id TEXT, field_key TEXT, value_json TEXT,
      PRIMARY KEY(version_key,field_key)
    );
    CREATE INDEX attr_entity ON attributes(entity_type,entity_id,field_key);
    CREATE TABLE edges(
      id INTEGER PRIMARY KEY, from_type TEXT, from_id TEXT, version_key TEXT, relation TEXT,
      to_kind TEXT, to_id TEXT, source_name TEXT, confidence TEXT, meta_json TEXT
    );
    CREATE INDEX edge_from ON edges(from_type,from_id);
    CREATE INDEX edge_to ON edges(to_kind,to_id);
    CREATE TABLE runtime_asset_health(
      norm_asset TEXT PRIMARY KEY, asset_sample TEXT, attempts INTEGER, failures INTEGER,
      client_files INTEGER, server_files INTEGER, source_files INTEGER, any_files INTEGER,
      matched_paths TEXT
    );
    CREATE TABLE file_coverage(
      norm_path TEXT PRIMARY KEY, copies INTEGER, source_count INTEGER, hash_variants INTEGER,
      sourcecode INTEGER, cliente INTEGER, servidor INTEGER, donor INTEGER, locations_json TEXT
    );
    CREATE TABLE field_conflicts(
      entity_type TEXT, canonical_id TEXT, field_key TEXT, variants INTEGER, values_json TEXT
    );
    CREATE INDEX fc_entity ON field_conflicts(entity_type,canonical_id);
    CREATE TABLE unmatched_versions(
      version_key TEXT PRIMARY KEY, source_name TEXT, source_kind TEXT, entity_type TEXT,
      source_entity_id TEXT, name TEXT, origin_path TEXT, fields_json TEXT
    );
    CREATE TABLE runtime_failures(
      role TEXT, category TEXT, action TEXT, asset TEXT, attempts INTEGER
    );
    CREATE TABLE asset_references(
      id INTEGER PRIMARY KEY, source_name TEXT, from_path TEXT, raw_ref TEXT, norm_ref TEXT,
      occurrences INTEGER, match_quality TEXT, resolved_paths_json TEXT
    );
    CREATE INDEX ar_ref ON asset_references(norm_ref);
    CREATE INDEX ar_from ON asset_references(source_name,from_path);
    CREATE TABLE asset_families(
      source_name TEXT, source_kind TEXT, family_type TEXT, family_name TEXT, family_norm TEXT,
      directory TEXT, file_count INTEGER, model_count INTEGER, texture_count INTEGER, audio_count INTEGER,
      referenced_by_files INTEGER, entity_refs INTEGER, entity_ids_json TEXT, hashes_json TEXT, status TEXT,
      PRIMARY KEY(source_name,family_type,family_norm)
    );
    CREATE INDEX af_status ON asset_families(status);
    CREATE INDEX af_name ON asset_families(family_norm);
    """)


def build(catalog: Path, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    v1=open_v1(catalog)
    v2path=outdir/"workbench_v2.sqlite3"
    if v2path.exists(): v2path.unlink()
    v2=sqlite3.connect(v2path)
    init_v2(v2)
    v2.execute("INSERT INTO meta VALUES('version',?)",(VERSION,))
    v2.execute("INSERT INTO meta VALUES('source_catalog',?)",(str(catalog.resolve()),))

    src_by_id={}
    for sid,name,root,kind in v1.execute("SELECT id,name,root,kind FROM sources"):
        src_by_id[sid]=(name,root,kind)
        v2.execute("INSERT INTO sources VALUES(?,?,?,?)",(sid,name,root,kind))

    token_map,cmd_map,hints=collect_token_map(v1)
    v2.execute("INSERT INTO meta VALUES('directive_token_map_size',?)",(str(len(token_map)),))
    hints_export={f"{et}.{key}":typ for (et,key),typ in hints.items()}
    (outdir/"directive_token_map.json").write_text(json.dumps({"by_hex":token_map,"by_token":cmd_map,"type_hints":hints_export},indent=2,ensure_ascii=False),encoding="utf-8")

    canonical_ids=set(); canon_by_name=collections.defaultdict(list)
    canonical_count=0
    q="SELECT entity_type,entity_id,name,origin_path,payload_json FROM entities"
    for et,eid,name,origin,pjson in v1.execute(q):
        payload=jload(pjson,{})
        if not isinstance(payload,dict) or is_schema_document(eid,origin,payload):
            continue
        fields=semantic_fields(payload,et)
        subtype=classify_subtype(payload,et)
        cname=scalar_name(fields,name)
        canonical_ids.add(eid.casefold())
        if cname: canon_by_name[(et,norm_text(cname))].append(eid)
        v2.execute("INSERT INTO canonical_entities VALUES(?,?,?,?,?,?,?,?)",
                   (et,eid,subtype,cname,origin,jdump(fields),jdump(payload),"SourceCode"))
        vk=f"canonical:{eid}"
        v2.execute("INSERT INTO entity_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (vk,"SourceCode","project","canonical_json",et,eid,eid,"canonical",cname,origin,"",jdump(fields),jdump(payload)))
        for k,v in fields.items():
            v2.execute("INSERT OR REPLACE INTO attributes VALUES(?,?,?,?,?)",(vk,et,eid,k,jdump(v)))
        for edge in derive_edges(et,eid,fields,payload,"SourceCode",vk):
            v2.execute("INSERT INTO edges(from_type,from_id,version_key,relation,to_kind,to_id,source_name,confidence,meta_json) VALUES(?,?,?,?,?,?,?,?,?)",edge)
        canonical_count+=1

    scfg_count=0; matched=0; unmatched=0
    q="SELECT source_id,pack_path,pack_sha256,record_index,kind,logical_path,entity_id,entity_type,directives_json FROM scfg_records"
    for sid,pack_path,pack_sha,idx,kind,logical,eid,et,djson in v1.execute(q):
        sname,sroot,skind=src_by_id.get(sid,(f"source_{sid}","","unknown"))
        directives=jload(djson,[]) or []
        fields=normalize_scfg_directives(et,directives,token_map,cmd_map,hints)
        name=scalar_name(fields,"")
        cid=None; method="unmatched"
        if eid and eid.casefold() in canonical_ids:
            cid=next((x for x in canonical_ids if x==eid.casefold()),None)
            # Recover original-cased id from canonical table cheaply.
            rr=v2.execute("SELECT entity_id FROM canonical_entities WHERE lower(entity_id)=lower(?)",(eid,)).fetchone()
            cid=rr[0] if rr else eid
            method="entity_id"
        elif name:
            candidates=canon_by_name.get((et,norm_text(name)),[])
            if len(candidates)==1:
                cid=candidates[0]; method="unique_name"
        vk=f"scfg:{sname}:{pack_sha[:12]}:{idx}:{eid}"
        v2.execute("INSERT INTO entity_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (vk,sname,skind,"scfg",et,eid,cid,method,name,logical,pack_sha,jdump(fields),djson))
        key=cid or eid
        for k,v in fields.items():
            v2.execute("INSERT OR REPLACE INTO attributes VALUES(?,?,?,?,?)",(vk,et,key,k,jdump(v)))
        for edge in derive_edges(et,key,fields,{},sname,vk):
            v2.execute("INSERT INTO edges(from_type,from_id,version_key,relation,to_kind,to_id,source_name,confidence,meta_json) VALUES(?,?,?,?,?,?,?,?,?)",edge)
        if cid: matched+=1
        else:
            unmatched+=1
            v2.execute("INSERT INTO unmatched_versions VALUES(?,?,?,?,?,?,?,?)",(vk,sname,skind,et,eid,name,logical,jdump(fields)))
        scfg_count+=1
        if scfg_count % 1000 == 0: v2.commit()

    # Aggregate file source coverage.
    rows=v1.execute("""
      SELECT f.norm_path,s.name,s.kind,f.rel_path,f.sha256
      FROM files f JOIN sources s ON s.id=f.source_id
      ORDER BY f.norm_path
    """)
    current=None; bucket=[]
    def flush_cov(npath,b):
        if not b: return
        names={x[0] for x in b}; hashes={x[3] for x in b if x[3]}
        loc=[{"source":x[0],"kind":x[1],"path":x[2],"sha256":x[3]} for x in b]
        v2.execute("INSERT INTO file_coverage VALUES(?,?,?,?,?,?,?,?,?)",(
            npath,len(b),len(names),len(hashes),int("SourceCode" in names),int("cliente" in names),int("Servidor" in names),
            sum(1 for x in b if x[1]=="donor"),jdump(loc)))
    for npath,sname,skind,rel,sha in rows:
        if current is None: current=npath
        if npath!=current:
            flush_cov(current,bucket); current=npath; bucket=[]
        bucket.append((sname,skind,rel,sha))
    flush_cov(current,bucket)
    v2.commit()

    # Resolve all references captured by V1 into the physical file catalog.
    coverage_exact={r[0]:r[1:] for r in v2.execute("SELECT norm_path,sourcecode,cliente,servidor,donor,locations_json FROM file_coverage")}
    basename_map=collections.defaultdict(list)
    for npath in coverage_exact:
        basename_map[npath.rsplit("/",1)[-1]].append(npath)

    family_ref_files=collections.defaultdict(set)
    refq=v1.execute("""
      SELECT s.name,f.rel_path,MIN(r.raw_ref),r.norm_ref,COUNT(*)
      FROM refs r JOIN files f ON f.id=r.file_id JOIN sources s ON s.id=f.source_id
      GROUP BY f.id,r.norm_ref
      ORDER BY s.name,f.rel_path
    """)
    for sname,from_path,raw_ref,nref,occ in refq:
        candidates=[]; quality="unresolved"
        if nref in coverage_exact:
            candidates=[nref]; quality="exact"
        else:
            base=nref.rsplit("/",1)[-1]
            suff=[p for p in basename_map.get(base,[]) if p.endswith(nref) or nref.endswith(p)]
            if len(suff)==1: candidates=suff; quality="suffix"
            elif len(suff)>1: candidates=suff[:50]; quality="ambiguous_suffix"
            elif len(basename_map.get(base,[]))==1: candidates=basename_map[base]; quality="basename_unique"
            elif len(basename_map.get(base,[]))>1: candidates=basename_map[base][:50]; quality="ambiguous_basename"
        v2.execute("INSERT INTO asset_references(source_name,from_path,raw_ref,norm_ref,occurrences,match_quality,resolved_paths_json) VALUES(?,?,?,?,?,?,?)",
                   (sname,from_path,raw_ref,nref,occ,quality,jdump(candidates)))
        fam=extract_family(nref)
        if fam: family_ref_files[fam].add((sname,from_path))
    v2.commit()

    # Physical monster/NPC/player asset families, including families that have no active definition.
    fams=collections.defaultdict(lambda:{"files":[],"models":0,"textures":0,"audio":0,"hashes":set(),"display":None,"dir":None,"source_kind":""})
    for sname,skind,rel,cat,sha in v1.execute("""
      SELECT s.name,s.kind,f.rel_path,f.category,f.sha256
      FROM files f JOIN sources s ON s.id=f.source_id
    """):
        fam=extract_family(rel)
        if not fam: continue
        ftype,fname=fam; key=(sname,ftype,fname)
        d=fams[key]; d["source_kind"]=skind; d["files"].append(rel); d["hashes"].add(sha)
        mdisp=re.search(r"(?i)(?:^|[\\/])char[\\/](?:monster|npc|player|character)[\\/]([^\\/]+)", rel)
        d["display"]=mdisp.group(1) if mdisp else fname
        reln=rel.replace("\\","/")
        marker=f"char/{ftype}/"
        low=reln.casefold(); pos=low.find(marker)
        d["dir"]=(reln[:pos+len(marker)]+d["display"]).strip("/") if pos>=0 else reln.rsplit("/",1)[0]
        if cat=="model": d["models"]+=1
        elif cat=="texture": d["textures"]+=1
        elif cat=="audio": d["audio"]+=1

    family_entities=collections.defaultdict(set)
    for from_id,to_id in v2.execute("SELECT from_id,to_id FROM edges WHERE to_kind='asset'"):
        fam=extract_family(to_id)
        if fam: family_entities[fam].add(from_id)

    for (sname,ftype,fname),d in fams.items():
        entity_ids=sorted(family_entities.get((ftype,fname),set()))
        ref_files=len(family_ref_files.get((ftype,fname),set()))
        if d["models"] and not entity_ids:
            status="ORPHAN_NO_ENTITY"
        elif entity_ids:
            status="LINKED_TO_ENTITY"
        else:
            status="SUPPORT_ASSETS"
        v2.execute("INSERT INTO asset_families VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            sname,d["source_kind"],ftype,d["display"] or fname,fname,d["dir"] or "",len(d["files"]),d["models"],d["textures"],d["audio"],
            ref_files,len(entity_ids),jdump(entity_ids),jdump(sorted(x for x in d["hashes"] if x)),status))
    v2.commit()

    # Runtime health aggregates, using exact normalized path first and basename fallback.
    runtime=v1.execute("""
      SELECT norm_asset,MIN(asset),COUNT(*),SUM(result)
      FROM runtime_events GROUP BY norm_asset
    """)
    for na,sample,attempts,failures in runtime:
        candidates=[]
        if na in coverage_exact:
            candidates=[na]
        else:
            # Runtime often omits executable-root prefix; suffix match via basename narrows candidates.
            base=na.rsplit("/",1)[-1]
            for p in basename_map.get(base,[]):
                if p.endswith(na) or na.endswith(p): candidates.append(p)
        sc=cl=sv=dn=0; loc=[]
        for p in candidates:
            a,b,c,d,ljson=coverage_exact[p]
            sc=max(sc,a); cl=max(cl,b); sv=max(sv,c); dn=max(dn,d)
            loc.extend(jload(ljson,[]) or [])
        v2.execute("INSERT INTO runtime_asset_health VALUES(?,?,?,?,?,?,?,?,?)",(
            na,sample,attempts,failures,cl,sv,sc,int(bool(candidates)),jdump(loc[:50])))
    for role,cat,action,asset,cnt in v1.execute("""
      SELECT role,category,action,asset,COUNT(*) FROM runtime_events
      WHERE result=1 GROUP BY role,category,action,asset ORDER BY COUNT(*) DESC
    """):
        v2.execute("INSERT INTO runtime_failures VALUES(?,?,?,?,?)",(role,cat,action,asset,cnt))
    v2.commit()

    # Cross-version field conflicts for matched entities.
    groups=collections.defaultdict(lambda: collections.defaultdict(set))
    for et,cid,field,value in v2.execute("""
      SELECT ev.entity_type,ev.canonical_id,a.field_key,a.value_json
      FROM entity_versions ev JOIN attributes a ON a.version_key=ev.version_key
      WHERE ev.canonical_id IS NOT NULL AND a.field_key NOT LIKE '\\_%'
    """):
        groups[(et,cid)][field].add(value)
    for (et,cid),fields in groups.items():
        for k,vals in fields.items():
            if len(vals)>1:
                v2.execute("INSERT INTO field_conflicts VALUES(?,?,?,?,?)",(et,cid,k,len(vals),jdump(sorted(vals))))
    v2.commit()

    export_reports(v2,outdir)
    write_dashboard(v2,outdir)

    summary={
        "version":VERSION,
        "canonical_entities":canonical_count,
        "scfg_versions":scfg_count,
        "matched_scfg_versions":matched,
        "unmatched_scfg_versions":unmatched,
        "directive_keys":len(token_map),
        "edges":v2.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "field_conflicts":v2.execute("SELECT COUNT(*) FROM field_conflicts").fetchone()[0],
        "runtime_assets":v2.execute("SELECT COUNT(*) FROM runtime_asset_health").fetchone()[0],
        "runtime_unresolved_assets":v2.execute("SELECT COUNT(*) FROM runtime_asset_health WHERE any_files=0").fetchone()[0],
        "runtime_failed_assets":v2.execute("SELECT COUNT(*) FROM runtime_asset_health WHERE failures>0").fetchone()[0],
        "asset_references":v2.execute("SELECT COUNT(*) FROM asset_references").fetchone()[0],
        "asset_families":v2.execute("SELECT COUNT(*) FROM asset_families").fetchone()[0],
        "orphan_asset_families":v2.execute("SELECT COUNT(*) FROM asset_families WHERE status='ORPHAN_NO_ENTITY'").fetchone()[0],
    }
    (outdir/"overview_v2.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    v2.close(); v1.close()
    print("=== WORKBENCH V2 COMPLETE ===")
    for k,v in summary.items(): print(f"{k.upper()}={v}")
    print(f"DB={v2path}")
    print(f"DASHBOARD={outdir/'index_v2.html'}")


def export_csv(db,outdir,name,sql):
    cur=db.execute(sql); cols=[d[0] for d in cur.description]
    p=outdir/name
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(cols); w.writerows(cur)


def export_reports(db,outdir):
    export_csv(db,outdir,"entity_master.csv","""
      SELECT c.entity_type,c.entity_id,c.subtype,c.name,c.origin_path,
             COUNT(v.version_key) versions,COUNT(DISTINCT v.source_name) sources,
             SUM(CASE WHEN v.provenance_kind='scfg' THEN 1 ELSE 0 END) scfg_versions,
             (SELECT COUNT(*) FROM field_conflicts f WHERE f.canonical_id=c.entity_id) conflict_fields
      FROM canonical_entities c LEFT JOIN entity_versions v ON v.canonical_id=c.entity_id
      GROUP BY c.entity_id ORDER BY c.entity_type,c.name,c.entity_id
    """)
    export_csv(db,outdir,"entity_versions.csv","""
      SELECT version_key,source_name,source_kind,provenance_kind,entity_type,source_entity_id,canonical_id,
             match_method,name,origin_path,pack_sha256,fields_json
      FROM entity_versions ORDER BY entity_type,COALESCE(canonical_id,source_entity_id),source_name
    """)
    export_csv(db,outdir,"field_conflicts.csv","SELECT * FROM field_conflicts ORDER BY entity_type,canonical_id,field_key")
    export_csv(db,outdir,"unmatched_versions.csv","SELECT * FROM unmatched_versions ORDER BY entity_type,name,source_name")
    export_csv(db,outdir,"content_graph.csv","SELECT from_type,from_id,relation,to_kind,to_id,source_name,confidence,meta_json FROM edges ORDER BY from_type,from_id,relation")
    export_csv(db,outdir,"runtime_asset_health.csv","SELECT * FROM runtime_asset_health ORDER BY failures DESC,attempts DESC,norm_asset")
    export_csv(db,outdir,"file_coverage.csv","SELECT * FROM file_coverage ORDER BY donor DESC,hash_variants DESC,norm_path")
    export_csv(db,outdir,"runtime_failures_v2.csv","SELECT * FROM runtime_failures ORDER BY attempts DESC")
    export_csv(db,outdir,"asset_references.csv","SELECT source_name,from_path,raw_ref,norm_ref,occurrences,match_quality,resolved_paths_json FROM asset_references ORDER BY source_name,from_path,norm_ref")
    export_csv(db,outdir,"asset_families.csv","SELECT * FROM asset_families ORDER BY status,family_type,family_name,source_name")
    export_csv(db,outdir,"orphan_asset_families.csv","SELECT * FROM asset_families WHERE status='ORPHAN_NO_ENTITY' ORDER BY family_type,family_name,source_name")

    # Balance matrix: one row per entity version with common columns.
    p=outdir/"balance_matrix.csv"
    allcols=["entity_type","canonical_id","source_entity_id","name","source_name","source_kind","provenance_kind","match_method"]
    fields=[]
    for et,cols in BALANCE_COLUMNS.items():
        for c in cols:
            if c not in fields: fields.append(c)
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=allcols+fields); w.writeheader()
        for row in db.execute("SELECT entity_type,canonical_id,source_entity_id,name,source_name,source_kind,provenance_kind,match_method,fields_json FROM entity_versions ORDER BY entity_type,name"):
            et,cid,sid,name,sn,sk,pk,mm,fjson=row
            obj=jload(fjson,{}) or {}
            out={"entity_type":et,"canonical_id":cid,"source_entity_id":sid,"name":name,"source_name":sn,"source_kind":sk,"provenance_kind":pk,"match_method":mm}
            for c in fields:
                if c in obj: out[c]=jdump(obj[c]) if isinstance(obj[c],(dict,list)) else obj[c]
            w.writerow(out)


def write_dashboard(db,outdir):
    counts=db.execute("SELECT entity_type,COUNT(*) FROM canonical_entities GROUP BY entity_type ORDER BY COUNT(*) DESC").fetchall()
    failures=db.execute("SELECT role,category,action,asset,attempts FROM runtime_failures ORDER BY attempts DESC LIMIT 100").fetchall()
    conflicts=db.execute("""
      SELECT f.entity_type,f.canonical_id,c.name,COUNT(*) fields
      FROM field_conflicts f LEFT JOIN canonical_entities c ON c.entity_id=f.canonical_id
      GROUP BY f.entity_type,f.canonical_id,c.name ORDER BY fields DESC LIMIT 300
    """).fetchall()
    unmatched=db.execute("SELECT source_name,entity_type,source_entity_id,name,origin_path FROM unmatched_versions ORDER BY source_name,entity_type LIMIT 300").fetchall()
    runtime_missing=db.execute("SELECT asset_sample,attempts,failures FROM runtime_asset_health WHERE any_files=0 ORDER BY failures DESC,attempts DESC LIMIT 300").fetchall()
    orphan_fams=db.execute("SELECT source_name,family_type,family_name,directory,file_count,model_count,texture_count,referenced_by_files FROM asset_families WHERE status='ORPHAN_NO_ENTITY' ORDER BY family_type,family_name LIMIT 500").fetchall()
    cards="".join(f"<div class=card><b>{html.escape(t)}</b><br>{n}</div>" for t,n in counts)
    def tbl(headers,rows):
        return "<table><thead><tr>"+"".join(f"<th>{html.escape(str(h))}</th>" for h in headers)+"</tr></thead><tbody>"+"".join("<tr>"+"".join(f"<td>{html.escape(str(v if v is not None else ''))}</td>" for v in r)+"</tr>" for r in rows)+"</tbody></table>"
    doc=f'''<!doctype html><meta charset="utf-8"><title>Summit Content Workbench V2</title>
<style>body{{font:14px system-ui;margin:24px;max-width:1700px}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{border:1px solid #bbb;padding:12px;min-width:130px}}table{{border-collapse:collapse;width:100%;margin:10px 0 32px}}th,td{{border:1px solid #ccc;padding:5px;vertical-align:top}}th{{position:sticky;top:0;background:white}}input{{padding:8px;width:450px}}</style>
<h1>Summit Content Workbench V2</h1><div class=cards>{cards}</div>
<p>Abra a interface dinâmica com <code>serve</code> para pesquisar entidades e comparar versões. Este HTML é um resumo offline.</p>
<input id=q placeholder="filtrar tabelas" oninput="document.querySelectorAll('tbody tr').forEach(r=>r.style.display=r.innerText.toLowerCase().includes(this.value.toLowerCase())?'':'none')">
<h2>Runtime failures</h2>{tbl(['role','category','action','asset','attempts'],failures)}
<h2>Entidades com campos divergentes</h2>{tbl(['type','id','name','conflict fields'],conflicts)}
<h2>Versões SCFG sem match canonical</h2>{tbl(['source','type','source id','name','origin'],unmatched)}
<h2>Famílias de assets sem entidade ativa</h2>{tbl(['source','family type','family','directory','files','models','textures','referencing files'],orphan_fams)}
<h2>Assets tentados em runtime sem arquivo resolvido no catálogo</h2>{tbl(['asset','attempts','failures'],runtime_missing)}
'''
    (outdir/"index_v2.html").write_text(doc,encoding="utf-8")


def resolve_db(path: str):
    p=Path(path).resolve()
    if p.is_dir(): p=p/"workbench_v2.sqlite3"
    if not p.exists(): raise SystemExit(f"V2 DB not found: {p}")
    return sqlite3.connect(p)


def cmd_search(args):
    db=resolve_db(args.db)
    q=f"%{args.q}%"
    sql="SELECT entity_type,entity_id,name,subtype,origin_path FROM canonical_entities WHERE (entity_id LIKE ? OR name LIKE ?)"
    par=[q,q]
    if args.type:
        sql+=" AND entity_type=?"; par.append(args.type)
    sql+=" ORDER BY entity_type,name LIMIT ?"; par.append(args.limit)
    for r in db.execute(sql,par): print("\t".join(str(x or "") for x in r))


def entity_id_from_args(db,args):
    eid=args.id
    row=db.execute("SELECT entity_id FROM canonical_entities WHERE entity_id=? OR lower(entity_id)=lower(?)",(eid,eid)).fetchone()
    if row: return row[0]
    rows=db.execute("SELECT entity_id FROM canonical_entities WHERE name=? COLLATE NOCASE",(eid,)).fetchall()
    if len(rows)==1: return rows[0][0]
    if not rows: raise SystemExit(f"entity not found: {eid}")
    raise SystemExit(f"ambiguous name: {eid} ({len(rows)} matches)")


def cmd_show(args):
    db=resolve_db(args.db); eid=entity_id_from_args(db,args)
    c=db.execute("SELECT entity_type,entity_id,subtype,name,origin_path,fields_json FROM canonical_entities WHERE entity_id=?",(eid,)).fetchone()
    print(json.dumps({"entity_type":c[0],"entity_id":c[1],"subtype":c[2],"name":c[3],"origin_path":c[4],"fields":jload(c[5],{})},indent=2,ensure_ascii=False))
    print("\n=== VERSIONS ===")
    for r in db.execute("SELECT source_name,source_kind,provenance_kind,match_method,source_entity_id,origin_path,fields_json FROM entity_versions WHERE canonical_id=? ORDER BY source_name,provenance_kind",(eid,)):
        print(f"--- source={r[0]} kind={r[1]} provenance={r[2]} match={r[3]} source_id={r[4]} origin={r[5]}")
        print(json.dumps(jload(r[6],{}),indent=2,ensure_ascii=False))
    print("\n=== RELATIONS ===")
    for r in db.execute("SELECT relation,to_kind,to_id,source_name,confidence,meta_json FROM edges WHERE from_id=? ORDER BY relation,to_id",(eid,)):
        print("\t".join(str(x or "") for x in r))


def cmd_diff(args):
    db=resolve_db(args.db); eid=entity_id_from_args(db,args)
    versions=[]
    for r in db.execute("SELECT source_name,provenance_kind,origin_path,fields_json FROM entity_versions WHERE canonical_id=? ORDER BY source_name,provenance_kind",(eid,)):
        versions.append((r[0],r[1],r[2],jload(r[3],{}) or {}))
    keys=sorted(set().union(*(v[3].keys() for v in versions)))
    print(f"ENTITY={eid} VERSIONS={len(versions)}")
    for key in keys:
        vals=[]
        for sn,pk,op,fields in versions:
            vals.append((sn,pk,fields.get(key,None)))
        canon={jdump(v) for _,_,v in vals}
        if len(canon)>1 or args.all:
            print(f"\n[{key}]")
            for sn,pk,v in vals: print(f"  {sn}/{pk}: {json.dumps(v,ensure_ascii=False)}")


def cmd_families(args):
    db=resolve_db(args.db)
    sql="SELECT source_name,source_kind,family_type,family_name,directory,file_count,model_count,texture_count,audio_count,referenced_by_files,entity_refs,status FROM asset_families WHERE 1=1"
    par=[]
    if args.type:
        sql+=" AND family_type=?"; par.append(args.type)
    if args.status:
        sql+=" AND status=?"; par.append(args.status)
    if args.q:
        sql+=" AND (family_name LIKE ? OR directory LIKE ?)"; par.extend([f"%{args.q}%",f"%{args.q}%"])
    sql+=" ORDER BY status,family_type,family_name,source_name LIMIT ?"; par.append(args.limit)
    for r in db.execute(sql,par):
        print("\t".join(str(x or "") for x in r))


def load_overrides(path: Path):
    if not path.exists(): return {"schema":"summit.balance-overrides/v2","overrides":[]}
    obj=jload(path.read_text(encoding="utf-8"),None)
    if not isinstance(obj,dict): raise SystemExit("invalid overrides file")
    obj.setdefault("schema","summit.balance-overrides/v2"); obj.setdefault("overrides",[])
    return obj


def cmd_override(args):
    p=Path(args.file).resolve(); obj=load_overrides(p)
    if args.action=="list":
        print(json.dumps(obj,indent=2,ensure_ascii=False)); return
    if args.action=="set":
        try: value=json.loads(args.value)
        except Exception: value=args.value
        found=None
        for o in obj["overrides"]:
            if o.get("entity_type")==args.type and o.get("entity_id")==args.id:
                found=o; break
        if found is None:
            found={"entity_type":args.type,"entity_id":args.id,"set":{},"reason":args.reason or ""}; obj["overrides"].append(found)
        found.setdefault("set",{})[args.field]=value
        if args.reason: found["reason"]=args.reason
    elif args.action=="unset":
        for o in list(obj["overrides"]):
            if o.get("entity_type")==args.type and o.get("entity_id")==args.id:
                o.get("set",{}).pop(args.field,None)
                if not o.get("set"): obj["overrides"].remove(o)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"OVERRIDES={p}")


def serve(args):
    dbpath=Path(args.db).resolve()
    if dbpath.is_dir(): dbpath=dbpath/"workbench_v2.sqlite3"
    overrides=Path(args.overrides).resolve()
    verbose_log = args.verbose
    class H(BaseHTTPRequestHandler):
        def db(self): return sqlite3.connect(dbpath)
        def send(self,body,status=200,ctype="text/html; charset=utf-8"):
            b=body.encode("utf-8"); self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
        def page(self,title,body):
            css="body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:5px}input,select{padding:6px}a{text-decoration:none}pre{white-space:pre-wrap;background:#f6f6f6;padding:10px}"
            nav='<p><a href="/">Resumo</a> | <a href="/entities">Entidades</a> | <a href="/families">Asset families</a> | <a href="/runtime">Runtime</a> | <a href="/conflicts">Conflitos</a> | <a href="/overrides">Overrides</a></p>'
            return f'<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title><style>{css}</style>{nav}<h1>{html.escape(title)}</h1>{body}'
        def do_GET(self):
            u=urlparse(self.path); qs=parse_qs(u.query); db=self.db()
            if u.path=="/":
                rows=db.execute("SELECT entity_type,COUNT(*) FROM canonical_entities GROUP BY entity_type").fetchall()
                body="<ul>"+"".join(f'<li><a href="/entities?type={html.escape(t)}">{html.escape(t)}</a>: {n}</li>' for t,n in rows)+"</ul>"
                body+=f"<p>SCFG versions: {db.execute('SELECT COUNT(*) FROM entity_versions WHERE provenance_kind=\'scfg\'').fetchone()[0]}</p>"
                body+=f"<p>Field conflicts: {db.execute('SELECT COUNT(*) FROM field_conflicts').fetchone()[0]}</p>"
                body+=f"<p>Runtime failed assets: {db.execute('SELECT COUNT(*) FROM runtime_asset_health WHERE failures>0').fetchone()[0]}</p>"
                self.send(self.page("Summit Content Workbench V2",body)); return
            if u.path=="/entities":
                typ=qs.get("type",[""])[0]; q=qs.get("q",[""])[0]; par=[]
                sql="SELECT entity_type,entity_id,name,subtype FROM canonical_entities WHERE 1=1"
                if typ: sql+=" AND entity_type=?"; par.append(typ)
                if q: sql+=" AND (entity_id LIKE ? OR name LIKE ?)"; par.extend([f"%{q}%",f"%{q}%"])
                sql+=" ORDER BY entity_type,name LIMIT 1000"
                rows=db.execute(sql,par).fetchall()
                body='<form><input name=q value="'+html.escape(q)+'" placeholder="buscar"><input name=type value="'+html.escape(typ)+'" placeholder="type"><button>Buscar</button></form>'
                body+="<table><tr><th>type</th><th>id</th><th>name</th><th>subtype</th></tr>"+"".join(f'<tr><td>{html.escape(str(a))}</td><td><a href="/entity?id={html.escape(str(b))}">{html.escape(str(b))}</a></td><td>{html.escape(str(c or ""))}</td><td>{html.escape(str(d))}</td></tr>' for a,b,c,d in rows)+"</table>"
                self.send(self.page("Entidades",body)); return
            if u.path=="/entity":
                eid=qs.get("id",[""])[0]
                c=db.execute("SELECT entity_type,entity_id,subtype,name,origin_path,fields_json FROM canonical_entities WHERE entity_id=?",(eid,)).fetchone()
                if not c: self.send(self.page("Não encontrado",""),404); return
                body=f"<h2>{html.escape(c[3] or c[1])}</h2><p><code>{html.escape(c[1])}</code> — {html.escape(c[0])} / {html.escape(c[2])}</p><p>{html.escape(c[4])}</p><h3>Canonical</h3><pre>{html.escape(json.dumps(jload(c[5],{}),indent=2,ensure_ascii=False))}</pre>"
                body+="<h3>Versões</h3><table><tr><th>source</th><th>kind</th><th>match</th><th>origin</th><th>fields</th></tr>"
                for r in db.execute("SELECT source_name,provenance_kind,match_method,origin_path,fields_json FROM entity_versions WHERE canonical_id=? ORDER BY source_name",(eid,)):
                    body+=f"<tr><td>{html.escape(r[0])}</td><td>{html.escape(r[1])}</td><td>{html.escape(r[2])}</td><td>{html.escape(r[3])}</td><td><pre>{html.escape(json.dumps(jload(r[4],{}),indent=2,ensure_ascii=False))}</pre></td></tr>"
                body+="</table><h3>Relações</h3><table><tr><th>relation</th><th>target kind</th><th>target</th><th>source</th></tr>"
                for r in db.execute("SELECT relation,to_kind,to_id,source_name FROM edges WHERE from_id=? ORDER BY relation,to_id LIMIT 2000",(eid,)):
                    body+=f"<tr><td>{html.escape(r[0])}</td><td>{html.escape(r[1])}</td><td>{html.escape(r[2])}</td><td>{html.escape(r[3])}</td></tr>"
                body+="</table>"
                self.send(self.page(c[3] or eid,body)); return
            if u.path=="/families":
                q=qs.get("q",[""])[0]; status=qs.get("status",[""])[0]; par=[]
                sql="SELECT source_name,family_type,family_name,directory,file_count,model_count,texture_count,entity_refs,status FROM asset_families WHERE 1=1"
                if q: sql+=" AND (family_name LIKE ? OR directory LIKE ?)"; par.extend([f"%{q}%",f"%{q}%"])
                if status: sql+=" AND status=?"; par.append(status)
                sql+=" ORDER BY status,family_type,family_name LIMIT 2000"
                rows=db.execute(sql,par).fetchall()
                body='<form><input name=q value="'+html.escape(q)+'" placeholder="buscar família"><select name=status><option value="">todos</option><option '+('selected' if status=='ORPHAN_NO_ENTITY' else '')+' value="ORPHAN_NO_ENTITY">órfãos</option><option '+('selected' if status=='LINKED_TO_ENTITY' else '')+' value="LINKED_TO_ENTITY">ligados</option></select><button>Buscar</button></form>'
                body+="<table><tr><th>source</th><th>type</th><th>family</th><th>directory</th><th>files</th><th>models</th><th>textures</th><th>entities</th><th>status</th></tr>"+"".join("<tr>"+"".join(f"<td>{html.escape(str(x))}</td>" for x in r)+"</tr>" for r in rows)+"</table>"
                self.send(self.page("Asset families",body)); return
            if u.path=="/runtime":
                rows=db.execute("SELECT asset_sample,attempts,failures,client_files,server_files,source_files FROM runtime_asset_health ORDER BY failures DESC,attempts DESC LIMIT 1000").fetchall()
                body="<table><tr><th>asset</th><th>attempts</th><th>failures</th><th>client</th><th>server</th><th>source</th></tr>"+"".join("<tr>"+"".join(f"<td>{html.escape(str(x))}</td>" for x in r)+"</tr>" for r in rows)+"</table>"
                self.send(self.page("Runtime asset health",body)); return
            if u.path=="/conflicts":
                rows=db.execute("SELECT entity_type,canonical_id,field_key,variants,values_json FROM field_conflicts ORDER BY variants DESC,entity_type,canonical_id LIMIT 1500").fetchall()
                body="<table><tr><th>type</th><th>entity</th><th>field</th><th>variants</th><th>values</th></tr>"+"".join(f'<tr><td>{html.escape(r[0])}</td><td><a href="/entity?id={html.escape(r[1])}">{html.escape(r[1])}</a></td><td>{html.escape(r[2])}</td><td>{r[3]}</td><td><pre>{html.escape(r[4])}</pre></td></tr>' for r in rows)+"</table>"
                self.send(self.page("Conflitos",body)); return
            if u.path=="/overrides":
                obj=load_overrides(overrides)
                body=f"<p>Arquivo: <code>{html.escape(str(overrides))}</code></p><pre>{html.escape(json.dumps(obj,indent=2,ensure_ascii=False))}</pre>"
                body+='''<h3>Adicionar/alterar</h3><form method="POST"><input name=type placeholder="monster"><input name=id placeholder="monster.x"><input name=field placeholder="life"><input name=value placeholder="20000"><input name=reason placeholder="motivo"><button>Salvar override</button></form>'''
                self.send(self.page("Balance overrides",body)); return
            self.send(self.page("404",""),404)
        def do_POST(self):
            u=urlparse(self.path)
            if u.path!="/overrides": self.send(self.page("404",""),404); return
            n=int(self.headers.get("Content-Length","0")); body=self.rfile.read(n).decode("utf-8","replace"); form=parse_qs(body)
            typ=form.get("type",[""])[0]; eid=form.get("id",[""])[0]; field=form.get("field",[""])[0]; value=form.get("value",[""])[0]; reason=form.get("reason",[""])[0]
            if not typ or not eid or not field: self.send(self.page("Erro","type/id/field obrigatórios"),400); return
            try: val=json.loads(value)
            except Exception: val=value
            obj=load_overrides(overrides); found=None
            for o in obj["overrides"]:
                if o.get("entity_type")==typ and o.get("entity_id")==eid: found=o; break
            if found is None:
                found={"entity_type":typ,"entity_id":eid,"set":{},"reason":reason}; obj["overrides"].append(found)
            found.setdefault("set",{})[field]=val
            if reason: found["reason"]=reason
            overrides.parent.mkdir(parents=True,exist_ok=True); overrides.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            self.send_response(303); self.send_header("Location",f"/entity?id={eid}"); self.end_headers()
        def log_message(self, fmt, *logargs):
            if verbose_log: super().log_message(fmt,*logargs)
    httpd=ThreadingHTTPServer((args.host,args.port),H)
    print(f"WORKBENCH_URL=http://{args.host}:{args.port}/")
    print(f"DB={dbpath}")
    print(f"OVERRIDES={overrides}")
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass


def main():
    ap=argparse.ArgumentParser(description="Summit Content Workbench V2 — normalized entities, donor/source comparison, asset graph and safe balance overrides")
    sp=ap.add_subparsers(dest="cmd",required=True)
    b=sp.add_parser("build"); b.add_argument("--catalog",required=True); b.add_argument("--out",default=".summit_content_workbench_v2")
    s=sp.add_parser("search"); s.add_argument("--db",default=".summit_content_workbench_v2"); s.add_argument("q"); s.add_argument("--type"); s.add_argument("--limit",type=int,default=100)
    sh=sp.add_parser("show"); sh.add_argument("--db",default=".summit_content_workbench_v2"); sh.add_argument("id")
    d=sp.add_parser("diff"); d.add_argument("--db",default=".summit_content_workbench_v2"); d.add_argument("id"); d.add_argument("--all",action="store_true")
    f=sp.add_parser("families"); f.add_argument("--db",default=".summit_content_workbench_v2"); f.add_argument("q",nargs="?",default=""); f.add_argument("--type",choices=["monster","npc","player"]); f.add_argument("--status",choices=["ORPHAN_NO_ENTITY","LINKED_TO_ENTITY","SUPPORT_ASSETS"]); f.add_argument("--limit",type=int,default=200)
    o=sp.add_parser("override"); o.add_argument("--file",default=".summit_content_workbench_v2/balance_overrides.json"); o.add_argument("action",choices=["list","set","unset"]); o.add_argument("--type"); o.add_argument("--id"); o.add_argument("--field"); o.add_argument("--value",default="null"); o.add_argument("--reason",default="")
    sv=sp.add_parser("serve"); sv.add_argument("--db",default=".summit_content_workbench_v2"); sv.add_argument("--overrides",default=".summit_content_workbench_v2/balance_overrides.json"); sv.add_argument("--host",default="127.0.0.1"); sv.add_argument("--port",type=int,default=8765); sv.add_argument("--verbose",action="store_true")
    args=ap.parse_args()
    if args.cmd=="build": build(Path(args.catalog),Path(args.out))
    elif args.cmd=="search": cmd_search(args)
    elif args.cmd=="show": cmd_show(args)
    elif args.cmd=="diff": cmd_diff(args)
    elif args.cmd=="families": cmd_families(args)
    elif args.cmd=="override": cmd_override(args)
    elif args.cmd=="serve": serve(args)

if __name__=="__main__": main()
