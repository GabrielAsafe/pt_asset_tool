#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

SCFG_HEADER = struct.Struct("<4sHH10I32s")
SCFG_RECORD = struct.Struct("<5I")
SCFG_DIRECTIVE = struct.Struct("<3I")

TEXT_EXTS = {
    ".txt",".ini",".inf",".json",".csv",".tsv",".md",".cfg",".conf",".log",".lst",".map",
    ".cpp",".cc",".c",".h",".hpp",".inl",".py",".sh",".bat",".ps1",".xml",".yml",".yaml",
    ".npc",".spm",".spp",".spc"
}
MODEL_EXTS = {".ase",".smd",".smb",".inx",".obj",".3ds"}
TEXTURE_EXTS = {".bmp",".tga",".dds",".png",".jpg",".jpeg",".gif",".webp"}
AUDIO_EXTS = {".wav",".bgm",".mp3",".ogg",".flac",".mid",".midi"}
PARTICLE_EXTS = {".part",".efk",".fx"}
PACK_EXTS = {".scfg",".smap",".sfld",".sres",".sloc",".sgcf",".scsp"}
ARCHIVE_EXTS = {".zip",".7z",".rar",".tar",".gz",".bz2",".xz"}
EXEC_EXTS = {".exe",".dll",".so",".a",".lib",".o",".obj"}

ASSET_TOKEN_RE = re.compile(
    rb'(?i)(?:[A-Z]:[\\/])?'
    rb'(?:[A-Za-z0-9 _.\-\(\)\[\]]+[\\/])+'
    rb'[A-Za-z0-9 _.\-\(\)\[\]]+\.(?:'
    rb'ase|smd|smb|inx|bmp|tga|dds|png|jpg|jpeg|gif|wav|bgm|mp3|ogg|'
    rb'ini|inf|txt|npc|spm|spp|spc|part|scfg|smap|sfld|sres|sloc|sgcf|scsp'
    rb')'
)

NAME_KEYS = ("name","display_name","english_name","j_name","title","nome")
ID_KEYS = ("id","code","npc_id","monster_id","item_id","quest_id","logical_path")
STAT_KEYS = {
    "level","hp","life","max_hp","attack","attack_min","attack_max","damage","damage_min","damage_max",
    "defense","absorb","block","accuracy","exp","experience","speed","move_speed","attack_speed",
    "range","price","weight","drop_rate","spawn_rate"
}

def sha256_file(p: Path, chunk=1024*1024) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def norm_path(s: str) -> str:
    s=s.replace("\\","/").replace("//","/")
    while "//" in s:
        s=s.replace("//","/")
    return s.strip().lstrip("./").casefold()

def category_for(path: Path) -> str:
    s=norm_path(str(path))
    ext=path.suffix.casefold()
    parts=set(s.split("/"))
    if ext in PACK_EXTS: return "runtime_pack"
    if ext in MODEL_EXTS: return "model"
    if ext in TEXTURE_EXTS: return "texture"
    if ext in AUDIO_EXTS: return "audio"
    if ext in PARTICLE_EXTS: return "particle"
    if ext in ARCHIVE_EXTS: return "archive"
    if ext in EXEC_EXTS: return "binary"
    if "monster" in parts or "/monster/" in s: return "monster_data"
    if "npc" in parts or "/npc/" in s or ext==".npc": return "npc_data"
    if "openitem" in s or "/item/" in s or "items" in parts: return "item_data"
    if "quest" in parts or "/quest/" in s: return "quest_data"
    if "field" in parts or "/field/" in s or "stage" in parts: return "map_data"
    if "ui" in parts or "interface" in parts or "image" in parts: return "ui_data"
    if ext in TEXT_EXTS: return "text_source"
    return "other"

def entity_type_for_path(s: str) -> str:
    n=norm_path(s)
    if "/monster/" in n or "monster_definition" in n: return "monster"
    if "/npc/" in n or "npc_definition" in n: return "npc"
    if "/openitem/" in n or "/item/" in n or "item." in n: return "item"
    if "/quest/" in n or "quest." in n: return "quest"
    if "/field/" in n or n.endswith((".ase.spm",".ase.spp",".ase.spc")): return "map"
    return "unknown"

def decode_bytes(b: bytes) -> str:
    for enc in ("utf-8","cp1252","cp949","latin1"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("latin1","replace")

def walk_json(obj, prefix=""):
    if isinstance(obj, dict):
        for k,v in obj.items():
            p=f"{prefix}.{k}" if prefix else str(k)
            yield p,v
            yield from walk_json(v,p)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            p=f"{prefix}[{i}]"
            yield p,v
            yield from walk_json(v,p)

def extract_json_entity(path: Path):
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    et=entity_type_for_path(str(path))
    if et=="unknown":
        return None
    flat=list(walk_json(obj))
    idv=None; name=None; stats={}
    for key,val in flat:
        leaf=key.rsplit(".",1)[-1].split("[",1)[0].casefold()
        if idv is None and leaf in ID_KEYS and isinstance(val,(str,int)):
            idv=str(val)
        if name is None and leaf in NAME_KEYS and isinstance(val,str) and val.strip():
            name=val.strip()
        if leaf in STAT_KEYS and isinstance(val,(int,float,str)):
            stats[leaf]=val
    if not idv:
        idv=path.stem
    return et,idv,name or "",stats,obj

def extract_asset_tokens(path: Path, max_bytes: int, binary_strings: bool) -> list[str]:
    try:
        size=path.stat().st_size
    except OSError:
        return []
    ext=path.suffix.casefold()
    if ext in TEXT_EXTS or binary_strings or ext in MODEL_EXTS:
        limit=min(size,max_bytes)
        try:
            data=path.open("rb").read(limit)
        except Exception:
            return []
        out=[]
        seen=set()
        for m in ASSET_TOKEN_RE.finditer(data):
            raw=m.group(0)
            txt=decode_bytes(raw).replace("\x00","").strip()
            n=norm_path(txt)
            if n and n not in seen:
                seen.add(n); out.append(txt)
        return out
    return []

def parse_scfg(path: Path):
    try:
        data=path.read_bytes()
        if len(data)<SCFG_HEADER.size: return []
        h=SCFG_HEADER.unpack_from(data,0)
        magic,ver,flags,rc,ro,rs,dc,do,ds,so,ss,r0,r1,digest=h
        if magic!=b"SCFG" or ver!=1: return []
        if ro!=SCFG_HEADER.size or rs!=SCFG_RECORD.size or ds!=SCFG_DIRECTIVE.size: return []
        if do!=ro+rc*rs or so!=do+dc*ds or so+ss!=len(data): return []
        if hashlib.sha256(data[SCFG_HEADER.size:]).digest()!=digest: return []
        def s(off):
            if off>=ss: raise ValueError("string offset")
            a=so+off; e=data.find(b"\0",a,so+ss)
            if e<0: raise ValueError("unterminated")
            return data[a:e]
        out=[]
        for i in range(rc):
            po,io,kind,st,count=SCFG_RECORD.unpack_from(data,ro+i*rs)
            if st>dc or count>dc-st: continue
            dirs=[]
            for j in range(st,st+count):
                co,vo,fl=SCFG_DIRECTIVE.unpack_from(data,do+j*ds)
                dirs.append({"cmd":decode_bytes(s(co)),"values":decode_bytes(s(vo)),"flags":fl,
                             "cmd_hex":s(co).hex(),"values_hex":s(vo).hex()})
            out.append({"record_index":i,"kind":kind,"path":decode_bytes(s(po)),
                        "id":decode_bytes(s(io)),"directives":dirs})
        return out
    except Exception:
        return []

def init_db(db):
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS sources(
      id INTEGER PRIMARY KEY, name TEXT UNIQUE, root TEXT, kind TEXT
    );
    CREATE TABLE IF NOT EXISTS files(
      id INTEGER PRIMARY KEY, source_id INTEGER, rel_path TEXT, norm_path TEXT, basename TEXT,
      ext TEXT, category TEXT, size INTEGER, sha256 TEXT, mtime REAL,
      UNIQUE(source_id, rel_path)
    );
    CREATE INDEX IF NOT EXISTS idx_files_norm ON files(norm_path);
    CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256);
    CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);

    CREATE TABLE IF NOT EXISTS refs(
      id INTEGER PRIMARY KEY, file_id INTEGER, raw_ref TEXT, norm_ref TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_refs_norm ON refs(norm_ref);

    CREATE TABLE IF NOT EXISTS entities(
      id INTEGER PRIMARY KEY, source_id INTEGER, entity_type TEXT, entity_id TEXT,
      name TEXT, origin_path TEXT, stats_json TEXT, payload_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_entities_eid ON entities(entity_id);

    CREATE TABLE IF NOT EXISTS scfg_records(
      id INTEGER PRIMARY KEY, source_id INTEGER, pack_path TEXT, pack_sha256 TEXT,
      record_index INTEGER, kind INTEGER, logical_path TEXT, entity_id TEXT,
      entity_type TEXT, directives_json TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_scfg_eid ON scfg_records(entity_id);

    CREATE TABLE IF NOT EXISTS runtime_events(
      id INTEGER PRIMARY KEY, source TEXT, tick TEXT, tid TEXT, role TEXT,
      category TEXT, action TEXT, asset TEXT, norm_asset TEXT, result INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_runtime_asset ON runtime_events(norm_asset);
    CREATE INDEX IF NOT EXISTS idx_runtime_cat ON runtime_events(category);
    """)

def source_id(db,name,root,kind):
    db.execute("INSERT OR IGNORE INTO sources(name,root,kind) VALUES(?,?,?)",(name,str(root),kind))
    return db.execute("SELECT id FROM sources WHERE name=?",(name,)).fetchone()[0]

def import_runtime_log(db, path: Path):
    if not path.exists(): return 0
    count=0
    with path.open("r",encoding="utf-8",errors="replace") as f:
        for line in f:
            parts=line.rstrip("\n").split("\t")
            if len(parts)<6: continue
            tick,tid,role,cat,action=parts[:5]
            asset="\t".join(parts[5:])
            result=1 if any(x in action.upper() for x in ("FAIL","MISS","ERROR")) else 0
            db.execute("""INSERT INTO runtime_events(source,tick,tid,role,category,action,asset,norm_asset,result)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                       (str(path),tick,tid,role,cat,action,asset,norm_path(asset),result))
            count+=1
    return count

def scan_source(db, sid:int, root:Path, max_ref_bytes:int, binary_strings:bool, skip_dirs:set[str]):
    files=0; refs=0; entities=0; scfg_count=0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip_dirs and not d.startswith(".git")]
        dpp=Path(dp)
        for fn in fns:
            p=dpp/fn
            try:
                rel=p.relative_to(root).as_posix()
                st=p.stat()
            except OSError:
                continue
            try:
                digest=sha256_file(p)
            except Exception:
                digest=""
            cat=category_for(Path(rel))
            db.execute("""INSERT OR REPLACE INTO files(source_id,rel_path,norm_path,basename,ext,category,size,sha256,mtime)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                       (sid,rel,norm_path(rel),p.name,p.suffix.casefold(),cat,st.st_size,digest,st.st_mtime))
            fid=db.execute("SELECT id FROM files WHERE source_id=? AND rel_path=?",(sid,rel)).fetchone()[0]
            files+=1

            for raw in extract_asset_tokens(p,max_ref_bytes,binary_strings):
                db.execute("INSERT INTO refs(file_id,raw_ref,norm_ref) VALUES(?,?,?)",(fid,raw,norm_path(raw)))
                refs+=1

            if p.suffix.casefold()==".json":
                e=extract_json_entity(p)
                if e:
                    et,eid,name,stats,obj=e
                    db.execute("""INSERT INTO entities(source_id,entity_type,entity_id,name,origin_path,stats_json,payload_json)
                                  VALUES(?,?,?,?,?,?,?)""",
                               (sid,et,eid,name,rel,json.dumps(stats,ensure_ascii=False),json.dumps(obj,ensure_ascii=False)))
                    entities+=1

            if p.suffix.casefold()==".scfg":
                records=parse_scfg(p)
                for r in records:
                    et=entity_type_for_path(r["path"]+" "+r["id"])
                    db.execute("""INSERT INTO scfg_records(source_id,pack_path,pack_sha256,record_index,kind,
                                  logical_path,entity_id,entity_type,directives_json)
                                  VALUES(?,?,?,?,?,?,?,?,?)""",
                               (sid,rel,digest,r["record_index"],r["kind"],r["path"],r["id"],et,
                                json.dumps(r["directives"],ensure_ascii=False)))
                    scfg_count+=1
    return files,refs,entities,scfg_count

def export_csv(db, out:Path, sql:str, name:str):
    cur=db.execute(sql)
    cols=[d[0] for d in cur.description]
    p=out/name
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(cols); w.writerows(cur.fetchall())
    return p

def write_html(db,out:Path,overview:dict):
    entity_rows=db.execute("""
      SELECT s.name,e.entity_type,e.entity_id,e.name,e.origin_path,e.stats_json
      FROM entities e JOIN sources s ON s.id=e.source_id
      ORDER BY e.entity_type,e.name,e.entity_id LIMIT 5000
    """).fetchall()
    failures=db.execute("""
      SELECT role,category,action,asset,COUNT(*) c
      FROM runtime_events WHERE result=1
      GROUP BY role,category,action,asset ORDER BY c DESC LIMIT 500
    """).fetchall()
    coll=db.execute("""
      SELECT norm_path,COUNT(DISTINCT source_id) sources,COUNT(DISTINCT sha256) hashes
      FROM files GROUP BY norm_path HAVING sources>1 AND hashes>1
      ORDER BY sources DESC,norm_path LIMIT 1000
    """).fetchall()

    def table(headers, rows):
        return "<table><thead><tr>"+''.join(f"<th>{html.escape(str(h))}</th>" for h in headers)+"</tr></thead><tbody>"+''.join(
            "<tr>"+''.join(f"<td>{html.escape(str(x))}</td>" for x in row)+"</tr>" for row in rows
        )+"</tbody></table>"

    doc=f"""<!doctype html><meta charset="utf-8">
<title>Summit Content Workbench</title>
<style>
body{{font:14px system-ui;margin:24px;max-width:1600px}} table{{border-collapse:collapse;width:100%;margin:12px 0 32px}}
th,td{{border:1px solid #ccc;padding:5px;vertical-align:top}} th{{position:sticky;top:0;background:#fff}}
input{{padding:8px;width:420px}} .cards{{display:flex;gap:12px;flex-wrap:wrap}} .card{{border:1px solid #ccc;padding:12px;min-width:160px}}
</style>
<h1>Summit Content Workbench</h1>
<div class=cards>
{''.join(f'<div class=card><b>{html.escape(str(k))}</b><br>{html.escape(str(v))}</div>' for k,v in overview.items() if isinstance(v,(str,int,float)))}
</div>
<p><input id=q placeholder="filtrar tabelas..." oninput="filterTables(this.value)"></p>
<h2>Entities (amostra até 5000)</h2>
{table(["source","type","id","name","origin","stats"],entity_rows)}
<h2>Runtime failures</h2>
{table(["role","category","action","asset","count"],failures)}
<h2>Mesmo path, conteúdo diferente entre fontes</h2>
{table(["normalized path","sources","hash variants"],coll)}
<script>
function filterTables(q){{q=q.toLowerCase();document.querySelectorAll('tbody tr').forEach(tr=>{{tr.style.display=tr.innerText.toLowerCase().includes(q)?'':'none'}})}}
</script>
"""
    (out/"index.html").write_text(doc,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(description="Summit Content Workbench v1: inventory, provenance, donor diff and runtime asset telemetry.")
    ap.add_argument("--repo-root",default=".")
    ap.add_argument("--source",action="append",default=[],help="extra source NAME=PATH")
    ap.add_argument("--donor",action="append",default=[],help="donor NAME=PATH; repeatable")
    ap.add_argument("--out",default="content_workbench_out")
    ap.add_argument("--binary-strings",action="store_true",help="scan asset-like strings in all binaries too (slower)")
    ap.add_argument("--max-ref-bytes",type=int,default=16*1024*1024)
    ap.add_argument("--skip-dir",action="append",default=[])
    args=ap.parse_args()

    repo=Path(args.repo_root).resolve()
    out=Path(args.out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    dbp=out/"catalog.sqlite3"
    if dbp.exists(): dbp.unlink()
    db=sqlite3.connect(dbp)
    init_db(db)

    roots=[]
    defaults=[
        ("SourceCode",repo/"SourceCode","project"),
        ("cliente",repo/"cliente","runtime"),
        ("Servidor",repo/"Servidor","runtime"),
    ]
    for n,p,k in defaults:
        if p.exists(): roots.append((n,p,k))
    for spec,kind in [(x,"source") for x in args.source]+[(x,"donor") for x in args.donor]:
        if "=" not in spec:
            raise SystemExit(f"expected NAME=PATH: {spec}")
        n,p=spec.split("=",1)
        roots.append((n,Path(p).expanduser().resolve(),kind))

    skip={" .git".strip(),"node_modules","__pycache__"}
    skip.update(args.skip_dir)

    summary=[]
    for name,root,kind in roots:
        if not root.exists():
            print(f"[WARN] missing root {name}={root}",file=sys.stderr); continue
        sid=source_id(db,name,root,kind)
        f,r,e,s=scan_source(db,sid,root,args.max_ref_bytes,args.binary_strings,skip)
        db.commit()
        summary.append((name,kind,str(root),f,r,e,s))
        print(f"[OK] {name}: files={f} refs={r} json_entities={e} scfg_records={s}")

    runtime_logs=[
        repo/"cliente/LOGS/runtime_asset_attempts.log",
        repo/"Servidor/LOGS/runtime_asset_attempts.log",
    ]
    rt=0
    for p in runtime_logs:
        n=import_runtime_log(db,p); rt+=n
        if n: print(f"[OK] runtime log {p}: events={n}")
    db.commit()

    overview={
        "sources":db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "files":db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "unique_hashes":db.execute("SELECT COUNT(DISTINCT sha256) FROM files WHERE sha256<>''").fetchone()[0],
        "asset_refs":db.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
        "json_entities":db.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "scfg_records":db.execute("SELECT COUNT(*) FROM scfg_records").fetchone()[0],
        "runtime_events":db.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0],
        "runtime_failures":db.execute("SELECT COUNT(*) FROM runtime_events WHERE result=1").fetchone()[0],
        "donor_sources":db.execute("SELECT COUNT(*) FROM sources WHERE kind='donor'").fetchone()[0],
    }
    (out/"overview.json").write_text(json.dumps(overview,indent=2,ensure_ascii=False),encoding="utf-8")

    export_csv(db,out,"""
      SELECT s.name source,s.kind source_kind,f.rel_path,f.category,f.ext,f.size,f.sha256
      FROM files f JOIN sources s ON s.id=f.source_id ORDER BY s.name,f.rel_path
    ""","assets.csv")
    export_csv(db,out,"""
      SELECT s.name source,e.entity_type,e.entity_id,e.name,e.origin_path,e.stats_json
      FROM entities e JOIN sources s ON s.id=e.source_id ORDER BY e.entity_type,e.name,e.entity_id
    ""","entities.csv")
    export_csv(db,out,"""
      SELECT s.name source,r.pack_path,r.pack_sha256,r.record_index,r.kind,r.logical_path,r.entity_id,r.entity_type,r.directives_json
      FROM scfg_records r JOIN sources s ON s.id=r.source_id ORDER BY s.name,r.pack_path,r.record_index
    ""","scfg_records.csv")
    export_csv(db,out,"""
      SELECT role,category,action,asset,COUNT(*) attempts
      FROM runtime_events GROUP BY role,category,action,asset ORDER BY attempts DESC
    ""","runtime_assets.csv")
    export_csv(db,out,"""
      SELECT role,category,action,asset,COUNT(*) attempts
      FROM runtime_events WHERE result=1 GROUP BY role,category,action,asset ORDER BY attempts DESC
    ""","runtime_failures.csv")
    export_csv(db,out,"""
      SELECT norm_path,COUNT(DISTINCT source_id) source_count,COUNT(DISTINCT sha256) hash_variants,
             GROUP_CONCAT(DISTINCT s.name) sources
      FROM files f JOIN sources s ON s.id=f.source_id
      GROUP BY norm_path HAVING source_count>1 AND hash_variants>1
      ORDER BY source_count DESC,norm_path
    ""","donor_path_conflicts.csv")
    export_csv(db,out,"""
      SELECT sha256,COUNT(*) copies,GROUP_CONCAT(s.name||':'||f.rel_path,' | ') locations
      FROM files f JOIN sources s ON s.id=f.source_id
      WHERE sha256<>'' GROUP BY sha256 HAVING copies>1 ORDER BY copies DESC
    ""","duplicate_assets.csv")
    export_csv(db,out,"""
      SELECT s.name source,f.category,COUNT(*) files,SUM(f.size) bytes
      FROM files f JOIN sources s ON s.id=f.source_id GROUP BY s.name,f.category ORDER BY s.name,files DESC
    ""","category_summary.csv")

    balance_template={
      "schema":"summit.balance-overrides.v1",
      "notes":"Never edit donor files in place. Put only intentional overrides here. Future compiler can project these into canonical content.",
      "overrides":[
        {
          "entity_type":"monster",
          "entity_id":"example.monster",
          "source_selector":"canonical",
          "set":{"level":100,"hp":18800},
          "reason":"example only; remove before use"
        }
      ]
    }
    (out/"balance_overrides.template.json").write_text(json.dumps(balance_template,indent=2,ensure_ascii=False),encoding="utf-8")
    write_html(db,out,overview)
    db.close()

    print("\n=== COMPLETE ===")
    for k,v in overview.items(): print(f"{k.upper()}={v}")
    print(f"DB={dbp}")
    print(f"DASHBOARD={out/'index.html'}")
    print(f"CSV_DIR={out}")

if __name__=="__main__":
    main()
