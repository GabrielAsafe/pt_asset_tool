#!/usr/bin/env python3
"""SUMMIT Content Studio: safe canonical editor, preflight, build and publish.

No external dependencies. Runtime packs are NEVER edited directly. This app delegates
compilation and deployment to the project's already-established content_port scripts.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

CODE = re.compile(r'^[A-Z]{2}[0-9]{3}$')
HEX = re.compile(r'^0x[0-9A-F]{8}$')
SCHEMA = 'summit.content-studio-change/v1'
PACKS = {
    'client': ('field_runtime.sfld','skin_reforms.sskm','text_resources.sres','localization.sloc',
               'gameplay_config.sgcf','gameplay_reference.sgrf','definitions_client.scfg','maps_client.smap'),
    'server': ('field_runtime.sfld','skin_reforms.sskm','text_resources.sres','localization.sloc',
               'gameplay_config.sgcf','gameplay_reference.sgrf','definitions_server.scfg','maps_server.smap','coin_shop.scsp'),
}
EXTENSIONS = {'icon':{'.bmp','.dds','.png','.tga'}, 'model':{'.inx','.smd','.smb','.ini','.ase'},
              'animation':{'.inx','.smd','.smb','.ase'}, 'sound':{'.wav','.ogg','.mp3'},
              'texture':{'.dds','.bmp','.tga','.png'}, 'particle':{'.part','.dds','.tga','.png'},
              'map_asset':{'.ase','.smd','.smb'}, 'other':None}

class StudioError(Exception): pass

def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def file_sha(path: Path) -> str: return sha(path.read_bytes())
def jbytes(doc: object) -> bytes: return (json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def load_json(path: Path):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc: raise StudioError(f'JSON inválido em {path}: {exc}') from exc

def inside(root: Path, name: str, *, existing=False) -> Path:
    """Reject traversal and symlink escapes, including nonexistent children."""
    if not isinstance(name,str) or not name or '\\' in name or '\x00' in name: raise StudioError(f'Caminho inválido: {name!r}')
    rel=PurePosixPath(name)
    if rel.is_absolute() or any(x in ('','.','..') for x in rel.parts) or ':' in rel.parts[0]:
        raise StudioError(f'Caminho inseguro (fora da raiz): {name!r}')
    p=root.joinpath(*rel.parts)
    if not p.resolve().is_relative_to(root.resolve()): raise StudioError(f'Link simbólico fora da raiz: {name}')
    if existing and not p.is_file(): raise StudioError(f'Ficheiro não encontrado: {name}')
    return p

def canonical_path(repo: Path) -> Path:
    source=repo/'SourceCode'
    if not (source/'Content/canonical/text/index.json').is_file():
        raise StudioError('Não encontrei SourceCode/Content/canonical/text/index.json. Usar --root na raiz SUMMIT.')
    return source/'Content/canonical'

def result(code, status, path='', actual='', expected='', action='', detail='') -> dict:
    return dict(id=code,status=status,path=str(path),actual=str(actual),expected=str(expected),action=action,detail=str(detail))

class Audit:
    def __init__(self, root: Path, phase: str, *, strict_assets=False):
        self.root=root; self.phase=phase; self.strict_assets=strict_assets; self.checks=[]
    def add(self,*args,**kw): self.checks.append(result(*args,**kw))
    def error(self,code,msg,path='',action=''):
        self.add(code,'BLOCK',path,actual=msg,action=action)
    def warn(self,code,msg,path='',action=''):
        self.add(code,'WARN',path,actual=msg,action=action)
    def ok(self,code,msg='',path=''):
        self.add(code,'PASS',path,detail=msg)
    def skip(self,code,msg): self.add(code,'SKIP',detail=msg)
    def report(self):
        counts={x:sum(c['status']==x for c in self.checks) for x in ('PASS','WARN','BLOCK','SKIP')}
        return {'schema':'summit.content-studio-report/v1','root':str(self.root),'phase':self.phase,
                'status':'FAIL' if counts['BLOCK'] else 'PASS', 'counts':counts,'checks':self.checks}

def run_gate(a:Audit, code: str, program: Path, args: list[str], hint: str, *, cwd=None):
    if not program.is_file():
        a.warn(code,'Validador existente não encontrado; não certificado',str(program),'Repor tools/content_port/');return
    try:
        p=subprocess.run([sys.executable,str(program),*map(str,args)],cwd=cwd or a.root,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=180)
        if p.returncode:
            output=(p.stderr+'\n'+p.stdout).strip().splitlines()
            useful=[l.strip() for l in output if any(w in l for w in ('SchemaValidationError','ERROR=','FAIL','missing','collision','Traceback','^'))]
            summary=next((l for l in useful if 'SchemaValidationError:' in l), '')
            if not summary: summary=next((l for l in useful if 'ERROR=' in l or 'FAIL' in l), '')
            if not summary: summary=output[-1] if output else 'O validador terminou com erro'
            a.error(code,summary,program.name, hint + ' | Consulte o log do validador; código='+str(p.returncode))
            a.checks[-1]['details']=output[-18:]
        else: a.ok(code,'Verificação existente executada com êxito',program.name)
    except (OSError,subprocess.TimeoutExpired) as exc: a.error(code,str(exc),program.name,hint)

def basic_json_check(a:Audit, canonical:Path):
    required=['text/index.json','stage_spawns/index.json','stage_start_points/index.json','fixed_npcs/index.json',
              'maps/client.maps.json','maps/server.maps.json','item_profiles/item_code_map.json',
              'item_profiles/client_item_code_map.json','item_profiles/client.items.json','item_profiles/server.items.json']
    missing=[x for x in required if not (canonical/x).is_file()]
    if missing: a.error('SRC001','Ficheiros obrigatórios ausentes: '+', '.join(missing),canonical,'Restaurar a árvore canónica');return False
    a.ok('SRC001','Entradas canónicas obrigatórias presentes')
    count=0; errors=[]
    for p in canonical.rglob('*.json'):
        if p.is_symlink(): errors.append(f'link simbólico: {p.relative_to(canonical)}');continue
        try: json.loads(p.read_text(encoding='utf-8'));count+=1
        except Exception as exc: errors.append(f'{p.relative_to(canonical)}: {exc}')
        if len(errors)>=15:break
    if errors: a.error('SRC_JSON',' | '.join(errors),canonical,'Corrigir JSON UTF-8; não compilar')
    else:a.ok('SRC_JSON',f'{count} documentos JSON válidos')
    return not errors

def text_and_links(a:Audit,canonical:Path):
    textroot=canonical/'text'; idx=load_json(textroot/'index.json'); entries=idx.get('documents')
    if not isinstance(entries,list):a.error('SRC002','index.json não tem documents[]');return
    ids={}; aliases={}; paths={}; bad=[]
    for i,e in enumerate(entries):
        try:
            path=inside(textroot,e['json_path'],existing=True)
            doc=load_json(path);ident=e['id']; did=doc['id']; kind=doc['kind']
            if did!=ident or (e.get('kind') and e.get('kind')!=kind):raise ValueError(f'id/kind divergente: {ident}/{did}')
            if ident in ids:raise ValueError(f'ID duplicado {ident}')
            ids[ident]=e['json_path'];paths[ident]=path
            for alias in doc.get('runtime_paths',[]):
                key=alias.replace('\\','/').casefold()
                if key in aliases and aliases[key]!=ident: raise ValueError(f'alias {alias} pertence a {aliases[key]} e {ident}')
                aliases[key]=ident
        except Exception as exc:bad.append(f'index[{i}] {e.get("json_path", "?")}: {exc}')
        if len(bad)>=15:break
    if bad:a.error('SRC002',' | '.join(bad),textroot/'index.json','Corrigir IDs, aliases e caminhos do índice sem duplicação')
    else:a.ok('SRC002',f'{len(ids)} IDs e {len(aliases)} aliases consistentes')
    # CI linked .zhoon, provenance, legacy bytes and names agree
    check=0; collisions=[]
    for ident,p in paths.items():
        if not ident.startswith('item.ci'):continue
        d=load_json(p);fields=(d.get('semantic') or {}).get('fields') or {};code=fields.get('code','')
        if not re.fullmatch(r'CI[0-9]{3}',code):continue
        check+=1
        if ident!='item.'+code.lower():collisions.append(f'{code}: id={ident!r}, esperado item.{code.lower()}')
        linked=fields.get('linked_file','').replace('\\','/')
        if linked.casefold()!=f'Name/{code}.zhoon'.casefold():
            collisions.append(f'{code}: linked_file={linked!r} em vez de Name/{code}.zhoon');continue
        loc=textroot/'resources/Servidor/GameServer/OpenItem/name'/f'{code}.zhoon.json'
        if not loc.is_file():collisions.append(f'{code}: ficheiro Name/{code}.zhoon não existe');continue
        nd=load_json(loc)
        source=nd.get('source') or {};reason=nd.get('selection_reason')
        if reason not in ('runtime_text_family','immutable_gameplay_config','ui_text_config','ui_text_resource'):
            collisions.append(f'{code}: selection_reason={reason!r}; usar runtime_text_family')
        if source.get('migration_status')=='native_canonical_generated':
            if source.get('generated_from')!=ident:collisions.append(f'{code}: generated_from={source.get("generated_from")!r}; esperado {ident}')
            if source.get('legacy_path') or source.get('legacy_sha256'):collisions.append(f'{code}: metadados legacy incompatíveis com origem generated_only')
        nm=fields.get('name','')
        named=[x.get('text') for x in (nd.get('semantic') or {}).get('entries',[]) if x.get('kind')=='name']
        if nm not in named:collisions.append(f'{code}: nome .zhoon difere do OpenItem: {nm!r} vs {named!r}')
        if nm=='Pedra Azul':collisions.append(f'{code}: nome CI ainda igual a Pedra Azul')
        try:
            raw=base64.b64decode(nd['compatibility']['legacy_payload_base64'],validate=True)
            if nm.encode('cp1252') not in raw:collisions.append(f'{code}: nome não consta no payload legacy CP1252')
        except Exception as exc:collisions.append(f'{code}: payload legacy inválido: {exc}')
    if collisions:a.error('LOC_CI',' | '.join(collisions[:18]),textroot,'Corrigir OpenItem, índice, linked_file, J_NAME, payload e metadados como conjunto')
    elif check:a.ok('LOC_CI',f'{check} itens CI com nome, link, esquema e bytes legacy consistentes')
    else:a.skip('LOC_CI','Nenhum item CI encontrado')

def id_maps(a:Audit,canonical:Path,source:Path):
    profiles=canonical/'item_profiles'; maps={}; broken=[]
    for profile,file in (('client','client_item_code_map.json'),('server','item_code_map.json')):
        p=profiles/file;d=load_json(p);ents=d.get('entries',[])
        if profile=='server' and (list(d)!=['schema','entries'] or d.get('schema')!='summit.item-code-map/v1'):
            broken.append('Mapa servidor: chaves/ordem ou schema inválidos (parser C++ estrito)')
        if profile=='server' and len(p.read_bytes())>256*1024:broken.append('Mapa servidor excede 256 KiB')
        if not isinstance(ents,list) or not ents: broken.append(f'{file}: entries[] vazio');continue
        vals={};nums={};legacy_clashes=[]
        for i,e in enumerate(ents):
            if list(e)!=['code','numeric'] or not (CODE.fullmatch(str(e.get('code',''))) if profile=='server' or str(e.get('code','')).upper().startswith('CI') else re.fullmatch(r'(?:[A-Za-z]{2}[0-9]{3}|RESULT[0-9]+)',str(e.get('code','')))) or not HEX.fullmatch(str(e.get('numeric',''))):
                broken.append(f'{file}[{i}]: code/numeric/ordem inválidos');continue
            c=e['code'];n=e['numeric']
            if c in vals and (profile=='server' or c.startswith('CI')):broken.append(f'{file}: code {c} repetido')
            if n in nums and nums[n]!=c:
                if c.startswith('CI') or nums[n].startswith('CI'):broken.append(f'{file}: ID {n} partilhado por {c} e {nums[n]}')
                else:legacy_clashes.append(f'{c}/{nums[n]}={n}')
            if int(n,16)==0:broken.append(f'{file}: ID zero em {c}')
            vals[c]=n;nums[n]=c
        maps[profile]=vals
        if legacy_clashes:a.warn('ID_LEGACY',f'{profile}: {len(legacy_clashes)} colisões numéricas históricas não-CI (não renumerar)',profiles/file,'Auditar separadamente antes de criar um item com ID reutilizado')
        if profile=='server' and len(ents)>2000:broken.append('Mapa servidor excede MAX_ITEM=2000 (documentado no snapshot)')
    cm=maps.get('client',{});sm=maps.get('server',{})
    cs=[x for x in cm if x.startswith('CI')];ss=[x for x in sm if x.startswith('CI')]
    for c in sorted(set(cs)|set(ss)):
        if c not in cm or c not in sm or cm[c]!=sm[c]:broken.append(f'{c}: ID cliente={cm.get(c)} servidor={sm.get(c)}')
    if broken:a.error('ID001-005',' | '.join(broken[:16]),profiles,'Não renumerar IDs publicados; corrigir mapeamentos e snapshots de origem')
    else:a.ok('ID001-005',f'{len(sm)} entradas server, {len(cm)} client, {len(ss)} CI coerentes')
    # Profile SHA of referenced canonical source; checks are read-only.
    ps=[]
    for profile in ('client','server'):
        p=profiles/f'{profile}.items.json';d=load_json(p)
        meta=d.get('source') or {};rel=meta.get('path','');expected=meta.get('sha256')
        try:
            q=inside(source,rel,existing=True)
            if file_sha(q)!=expected:ps.append(f'{profile}: snapshot SHA diferente de {rel}')
        except Exception as exc:ps.append(f'{profile}: {exc}')
    cli=load_json(profiles/'client_item_code_map.json'); smeta=cli.get('source') or {}
    inc_rel=smeta.get('path','')
    if inc_rel:
        p=source/inc_rel
        if p.exists():
            if file_sha(p)!=smeta.get('sha256'):ps.append('client_item_code_map.source SHA diferente de item_catalog_recovered.inc')
        else:a.warn('ID_INVENTORY','Sem catálogo .inc para verificar projeção do cliente',p,'Inspecionar o cliente no repositório Fedora')
    if ps:a.error('ID_SNAPSHOT',' | '.join(ps),profiles,'Regenerar snapshot/perfis pela tool nativa; preservar IDs')
    else:a.ok('ID_SNAPSHOT','Snapshots e perfis canónicos sincronizados')

def gameplay_relations(a:Audit,canonical:Path):
    root=canonical/'professions_v2'
    files={key:root/name for key,name in [('nodes','nodes_base_map58_417.json'),('loot','loot_tables_base_417.json'),
          ('bindings','item_bindings_base_417.json'),('drops','gm_drops_415.json')]}
    if not all(p.is_file() for p in files.values()):
        a.skip('GAME_417','Conjunto 417A/417C incompleto; validar com patch dedicado, não inferir ausência de funcionalidade')
    else:
        try:
            nodes=load_json(files['nodes'])['nodes'];tables=load_json(files['loot'])['tables'];bindings=load_json(files['bindings'])['items']
            drops=load_json(files['drops'])['entries']
            t={x['id']:x for x in tables};b={x['resource_key']:x for x in bindings}
            errors=[];seen=set();key_seen=set()
            for n in nodes:
                nid=n.get('node_id');r=n.get('resource_key');p=n.get('position') or {}
                if nid in seen:errors.append(f'node_id {nid} duplicado')
                seen.add(nid)
                if r in key_seen:errors.append(f'resource_key {r} em múltiplos nodes base')
                key_seen.add(r)
                if n.get('map_id')!=58 or not all(isinstance(p.get(k),int) for k in ('x','y','z')):
                    errors.append(f'node {nid}: map_id/XYZ inválidos')
                if n.get('loot_table') not in t:errors.append(f'node {nid}: loot_table inexistente')
                elif r not in b:errors.append(f'node {nid}: binding inexistente para {r}')
                else:
                    rewards=t[n['loot_table']].get('rewards',[])
                    if not any(x.get('resource_key')==r and x.get('native_code')==b[r]['native_code'] and x.get('storage')=='physical' for x in rewards):
                        errors.append(f'node {nid}: loot físico não coincide com binding {r}')
            for x in drops:
                if not isinstance(x.get('model_contains'),str) or not x['model_contains'] or x['model_contains']!=x['model_contains'].lower():
                    errors.append('DROP: model_contains vazio ou não ASCII minúsculo')
                if not isinstance(x.get('chance_bp'),int) or not 0<=x['chance_bp']<=10000:
                    errors.append('DROP: chance_bp fora de 0..10000')
                if x.get('storage')=='physical' and x.get('quantity')!=1:errors.append('DROP físico requer quantity=1 no contrato 415A')
            if errors:a.error('GAME_417',' | '.join(errors[:18]),root,'Corrigir nodes, loot, bindings e drops antes do build')
            else:a.ok('GAME_417',f'{len(nodes)} nodes, {len(tables)} loot tables, {len(bindings)} bindings, {len(drops)} regras GM coerentes',root)
            a.warn('GAME_RUNTIME','JSON de professions_v2 e gathering não implica ativação runtime pelo compilador de packs; validar C++/GM/DB em separado',root,
                'Usar verificações 417C, GM GMSP e teste físico do DAT no jogo')
        except Exception as exc:a.error('GAME_417',str(exc),root,'Reparar estrutura das quatro fontes')
    # Documents for model/animated characters cannot replace actual native animation assets.
    models=canonical/'model_configs/report.json'
    if models.is_file():
        d=load_json(models);n=d.get('unresolved',0)
        if isinstance(n,int) and n>0:a.warn('MODEL_CONFIG',f'{n} modelos ainda classificados como unresolved no relatório do snapshot',models,
             'Validar cada .ini/.inx/.smd/.smb real; não inventar animação')

def assets(a:Audit,canonical:Path):
    client=a.root/'cliente'; artroot=client/'image/Sinimage/Items/Crafting'
    if not client.is_dir():a.skip('AST001-002','cliente/ não incluído; validar na instalação Fedora com --root .');return
    # CI material icon fallback is part of this project; reported as separate gate when catalog is available.
    if not artroot.is_dir():
        if a.strict_assets:a.error('AST001','Diretório de ícones Crafting ausente',artroot,'Instalar BMPs originais no cliente')
        else:a.warn('AST001','Diretório Crafting não localizado (o catálogo pode apontar para outro)',artroot)
        return
    errors=[];present=0
    for i in range(101,169):
        p=artroot/f'itCI{i}.bmp'
        if not p.exists():errors.append(f'CI{i}: ausente');continue
        raw=p.read_bytes();present+=1
        if len(raw)<54 or raw[:2]!=b'BM':errors.append(f'CI{i}: assinatura BMP inválida');continue
        try:
            offset=struct.unpack_from('<I',raw,10)[0]; dib=struct.unpack_from('<I',raw,14)[0]
            width,height,planes,bpp=struct.unpack_from('<iiHH',raw,18)
            if dib<40 or width<=0 or height==0 or planes!=1 or bpp not in (24,32) or offset>=len(raw):errors.append(f'CI{i}: cabeçalho BMP incoerente')
        except struct.error:errors.append(f'CI{i}: truncado')
    if errors:
        msg=f'BMPs={present}/68: '+', '.join(errors[:14])
        if a.strict_assets:a.error('AST001-002',msg,artroot,'Verificar caminho exacto no sITEM e repor BMP válido')
        else:a.warn('AST001-002',msg,artroot,'Validar antes de publicar os itens CI')
    else:a.ok('AST001-002','68 BMP CI estruturalmente válidos; compatibilidade gráfica só no jogo',artroot)

def tree_digest(root:Path):
    # Same family digest as consolidate_canonical_content.py, not a guessed hash.
    h=hashlib.sha256();n=0;size=0
    for p in sorted((x for x in root.rglob('*') if x.is_file()),key=lambda x:x.relative_to(root).as_posix().casefold()):
        rel=p.relative_to(root).as_posix().encode('utf-8');b=p.stat().st_size
        h.update(rel+b'\0'+str(b).encode('ascii')+b'\0'+file_sha(p).encode('ascii')+b'\n')
        n+=1;size+=b
    return {'sha256':h.hexdigest(),'files':n,'bytes':size}

def verify_ci_scfg(pack:Path,names:dict[str,str]):
    hdr=struct.Struct('<4sHH10I32s');record=struct.Struct('<5I');directive=struct.Struct('<3I')
    buf=pack.read_bytes()
    if len(buf)<hdr.size:raise StudioError('SCFG truncado')
    mag,ver,flags,nr,ro,rs,nd,do,ds,so,ns,r1,r2,digest=hdr.unpack_from(buf)
    if mag!=b'SCFG' or ver!=1 or flags or r1 or r2 or rs!=record.size or ds!=directive.size:
        raise StudioError('SCFG header inválido')
    if ro!=hdr.size or do!=ro+nr*rs or so!=do+nd*ds or so+ns!=len(buf) or sha(buf[hdr.size:])!=digest.hex():
        raise StudioError('SCFG offsets ou SHA-256 do corpo inválidos')
    strings=buf[so:]
    def st(i):
        if i<0 or i>=ns:raise StudioError('SCFG string offset fora de limites')
        j=strings.find(b'\0',i)
        if j<0:raise StudioError('SCFG string sem terminador')
        return strings[i:j]
    found={};bad=[]
    for i in range(nr):
        po,io,kind,start,count=record.unpack_from(buf,ro+i*rs)
        if kind!=3:continue
        ident=st(io).decode('utf-8','strict')
        if ident not in names:continue
        if ident in found:bad.append(ident+': record duplicado');continue
        if start>nd or count>nd-start:raise StudioError('SCFG diretivas fora de limites')
        values={}
        for j in range(start,start+count):
            ko,vo,flags=directive.unpack_from(buf,do+j*ds)
            if flags:raise StudioError('SCFG directive flags inválidas')
            key=st(ko)
            if key in (b'*J_NAME',bytes.fromhex('2ac4dab5e5')):values.setdefault(key,[]).append(st(vo))
        found[ident]=values
    for ident,name in names.items():
        x=found.get(ident)
        if x is None:bad.append(ident+': record não encontrado');continue
        code=ident[5:].upper()
        if x.get(bytes.fromhex('2ac4dab5e5'))!=[('"'+code+'"').encode('ascii')]:bad.append(code+':CODE')
        try:expected=('"'+name+'"').encode('cp1252')
        except UnicodeEncodeError:bad.append(code+':nome incompatível com CP1252');continue
        if x.get(b'*J_NAME')!=[expected]:bad.append(code+':J_NAME (nome no pack divergente)')
    if bad:raise StudioError(', '.join(bad[:15])+f' (total={len(bad)})')
    return len(found)

def packs(a:Audit):
    p=a.root/'SourceCode/Content/packs'; issues=[]
    for role,files in PACKS.items():
        for name in files:
            f=p/name
            if not f.is_file():issues.append(name+' ausente');continue
            if f.stat().st_size<64:issues.append(name+' demasiado pequeno')
    if issues:a.error('PACK001',' | '.join(sorted(set(issues))),p,'Executar compile; não publicar packs antigos')
    else:a.ok('PACK001',f'{len(set(sum((list(v) for v in PACKS.values()), [])))} packs presentes')
    # Compare manifests to actual pack SHA and current canonical tree: stale-but-valid packs must never publish.
    manifest=a.root/'SourceCode/Content/BUILD.json'
    if not manifest.is_file():a.error('PACK003','BUILD.json inexistente',manifest,'Compilar Content antes de publicar')
    else:
        try:
            entries=load_json(manifest)['packs']; problems=[]
            for row in entries.values():
                q=inside(a.root/'SourceCode/Content',row['path'],existing=True)
                if q.stat().st_size!=row['bytes'] or file_sha(q)!=row['sha256']:
                    problems.append(row['path']+' difere do BUILD.json')
            if problems:a.error('PACK003',' | '.join(problems),manifest,'Recompilar sem alterar packs manualmente')
            else:a.ok('PACK003',f'{len(entries)} packs coincidem com BUILD.json',manifest)
        except Exception as exc:a.error('PACK003',str(exc),manifest,'Regenerar BUILD.json pela tool de compilação')
    provenance=a.root/'SourceCode/Content/CANONICAL_SOURCE.json'
    if not provenance.is_file():a.error('PACK_FRESHNESS','CANONICAL_SOURCE.json em falta',provenance,'Compilar com consolidate_canonical_content.py')
    else:
        try:
            families=load_json(provenance)['families'];c=a.root/'SourceCode/Content/canonical'
            stale=[fam for fam,row in families.items() if tree_digest(c/fam)!=row]
            new=set(x.name for x in c.iterdir() if x.is_dir())-set(families)
            if stale or new:a.error('PACK_FRESHNESS','Fontes alteradas depois do último build: '+', '.join(stale+sorted(new)),provenance,
                   'Executar compile antes de publish; não publicar packs antigos')
            else:a.ok('PACK_FRESHNESS',f'{len(families)} famílias canónicas idênticas ao build',provenance)
        except Exception as exc:a.error('PACK_FRESHNESS',str(exc),provenance,'Regenerar manifesto pela compilação nativa')
    source=a.root/'SourceCode'; cp=source/'tools/content_port' 
    # Reuse binary inspectors, not just magic checks.
    inspectors={'definitions_client.scfg':'inspect_definitions.py','definitions_server.scfg':'inspect_definitions.py',
      'localization.sloc':'inspect_localization.py','text_resources.sres':'inspect_text_resources.py',
      'field_runtime.sfld':'inspect_field_runtime.py','maps_client.smap':'inspect_maps.py','maps_server.smap':'inspect_maps.py',
      'gameplay_reference.sgrf':'inspect_gameplay_reference.py','gameplay_config.sgcf':'inspect_gameplay_config.py','coin_shop.scsp':'inspect_coin_shop.py'}
    for name,script in inspectors.items():
        if (p/name).is_file():run_gate(a,'PACK_INSPECT',cp/script,[str(p/name)],'Compilar novamente e inspecionar o pack')
    # Independent SCFG code/name check, including CP1252 bytes and body SHA.
    try:
        ci_names={}
        index=load_json(source/'Content/canonical/text/index.json')['documents']
        for e in index:
            if not str(e.get('id','')).startswith('item.ci'):continue
            d=load_json(source/'Content/canonical/text'/e['json_path'])
            code=(d.get('semantic') or {}).get('fields',{}).get('code','')
            if re.fullmatch('CI[0-9]{3}',code):ci_names[d['id']]=(d.get('semantic') or {}).get('fields',{}).get('name','')
        if ci_names:
            for name in ('definitions_client.scfg','definitions_server.scfg'):
                if (p/name).is_file():
                    n=verify_ci_scfg(p/name,ci_names)
                    a.ok('PACK_CI_NAMES',f'{n} itens com CODE e J_NAME corretos (CP1252, SHA, offsets)',name)
        else:a.skip('PACK_CI_NAMES','Nenhuma definição CI canónica')
    except Exception as exc:a.error('PACK_CI_NAMES',str(exc),p,'Reconstruir packs depois de corrigir nomes ligados e origem canónica')
    # Specialized 419B verifier is additionally reused if installed.

    verifier=a.root/'bugfixes/SUMMIT_PATCH_419B_LINKS_CI_INDEPENDENTES_2026-11-02/tools/verify_compiled_names_419b.py'
    if verifier.is_file():run_gate(a,'PACK_CI_NAMES',verifier,['--root',str(a.root)],'Nomes CI divergentes; reconstruir Content e verificar .zhoon')


def deploy(a:Audit):
    packs=a.root/'SourceCode/Content/packs'
    if not (a.root/'cliente').is_dir() or not (a.root/'Servidor').is_dir():
        a.skip('PUB001','Instalação runtime cliente/Servidor não incluída');return
    for role,dest in (('client','cliente'),('server','Servidor')):
        invalid=[]
        for name in PACKS[role]:
            s=packs/name;t=a.root/dest/'Content/packs'/name
            if not s.is_file() or not t.is_file():invalid.append(name+': ausente')
            elif file_sha(s)!=file_sha(t):invalid.append(name+': SHA diferente')
        if invalid:a.error('PUB001',f'{role}: '+', '.join(invalid),dest,'Publicar os packs do papel correto com deploy_runtime_content.py')
        else:a.ok('PUB001',f'{role}: {len(PACKS[role])} packs SHA iguais',dest)
    s=a.root/'SourceCode/Content/canonical/item_profiles/item_code_map.json';t=a.root/'Servidor/Content/packs/item_code_map.json'
    if not t.exists():a.error('PUB002','item_code_map.json runtime ausente',t,'Distribuir o mapa por publicador próprio; deploy_runtime_content.py NÃO o inclui')
    elif file_sha(s)!=file_sha(t):a.error('PUB002','Mapa IDs servidor difere da fonte',t,'Sincronizar com mecanismo explícito, sem renumerar itens')
    else:a.ok('PUB002','Mapa runtime dos IDs coincide com o canónico',t)
    drops=a.root/'Servidor/Content/crafting/gm_drops_415.json'
    if not drops.exists():a.warn('PUB003','Regras GM dos drops não encontradas; depende da funcionalidade ativa',drops)
    else:
        try: load_json(drops);a.ok('PUB003','Regras GM JSON legíveis',drops)
        except Exception as exc:a.error('PUB003',str(exc),drops)

def validate(root:Path,phase:str,*,strict_assets=False) -> Audit:
    a=Audit(root,phase,strict_assets=strict_assets)
    try:canonical=canonical_path(root)
    except StudioError as exc:a.error('SRC001',str(exc));return a
    if phase=='source':
        if not basic_json_check(a,canonical):return a
        try:text_and_links(a,canonical);id_maps(a,canonical,root/'SourceCode')
        except Exception as exc:a.error('SOURCE_INTERNAL',str(exc),canonical,'Corrigir fonte canónica')
        cp=root/'SourceCode/tools/content_port'
        run_gate(a,'VAL_TEXT',cp/'validate_canonical_text.py',[str(canonical/'text')], 'Corrigir fonte, ID/alias, source.generated_from ou localização')
        schema_args=['--canonical-text',str(canonical/'text'),'--canonical-spawns',str(canonical/'stage_spawns'),
          '--canonical-maps',str(canonical/'maps'),'--canonical-start-points',str(canonical/'stage_start_points'),
          '--canonical-fixed-npcs',str(canonical/'fixed_npcs')]
        run_gate(a,'VAL_SCHEMA',cp/'validate_canonical_schemas.py',schema_args,
          'Verificar seleção de origem generated/legacy, enum selection_reason, propriedades obrigatórias')
        run_gate(a,'VAL_MAP_POLICY',cp/'validate_single_entry_map_policy.py',['--canonical-maps',str(canonical/'maps')],
          'Corrigir entradas dos mapas, start_points e fallback de centro')
        # Optional checks requiring source code missing from Content+tools upload; WARN not fake PASS.
        if (root/'SourceCode/Shared').is_dir():
            run_gate(a,'VAL_MONSTER_DROP',cp/'validate_monster_runtime_limits.py',['--repo-root',str(root)],
                'Reduzir drops realmente materializados para FALLITEM_MAX; sincronizar diretivas/bytes CP949')
        else:a.skip('VAL_MONSTER_DROP','Código C++/Shared não incluído no snapshot; executar no Fedora')
        for gate,script in [('VAL_NPC_SHOP','validate_npc_shop_catalog.py'),('VAL_COIN_SHOP','validate_coin_shop_catalog.py')]:
            if script=='validate_coin_shop_catalog.py' and not (root/'SourceCode/SrcServer').is_dir():
                a.skip(gate,'Validador requer código de comércio em SourceCode/SrcServer; executar no Fedora')
            else:run_gate(a,gate,cp/script,['--repo-root',str(root/'SourceCode')],'Corrigir catálogo e códigos dos itens em ambos perfis')
        gameplay_relations(a,canonical)
        assets(a,canonical)
    elif phase=='post-build':
        packs(a)
    elif phase=='post-deploy':
        packs(a);deploy(a);assets(a,canonical)
    else:raise StudioError(f'Fase desconhecida: {phase}')
    return a

def show_report(a:Audit,format:str, report_path=None):
    rep=a.report()
    if format=='json': print(json.dumps(rep,ensure_ascii=False,indent=2))
    else:
        print(f'SUMMIT_CONTENT_STUDIO phase={rep["phase"]} status={rep["status"]} mode=READ_ONLY')
        for c in rep['checks']:
            detail=c['actual'] or c['detail'];suffix=(' | '+str(detail)) if detail else ''
            print(f'[{c["status"]}] {c["id"]} {c["path"]}{suffix}')
            if c['status']=='BLOCK':print('       COMO CORRIGIR: '+(c['action'] or 'Consultar validação'))
        print('RESULT='+rep['status']+' '+' '.join(f'{k}={v}' for k,v in rep['counts'].items()))
    if report_path:
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 1 if rep['status']=='FAIL' else 0

def pointer(doc, ptr: str):
    """RFC6901-style pointer, resolves container and last token without changing document."""
    if not isinstance(ptr,str) or not ptr.startswith('/') or ptr=='/':raise StudioError(f'JSON pointer inválido: {ptr}')
    parts=[s.replace('~1','/').replace('~0','~') for s in ptr[1:].split('/')]
    cur=doc
    for name in parts[:-1]:
        try:cur=cur[int(name)] if isinstance(cur,list) else cur[name]
        except (KeyError,IndexError,ValueError,TypeError) as exc:raise StudioError(f'Pointer não existe: {ptr} em {name}') from exc
    return cur, parts[-1]

def ptr_get(doc, ptr):
    parent,last=pointer(doc,ptr)
    try:return parent[int(last)] if isinstance(parent,list) else parent[last]
    except (IndexError,KeyError,ValueError,TypeError) as exc:raise StudioError(f'Pointer não encontrado: {ptr}') from exc

def resolve_doc(repo:Path,name:str):
    if not name.startswith('SourceCode/Content/canonical/') or not name.endswith('.json'):
        raise StudioError('Operação JSON limitada a SourceCode/Content/canonical/**/*.json')
    protected=(
        'SourceCode/Content/canonical/item_profiles/',
        'SourceCode/Content/canonical/text/resources/',
        'SourceCode/Content/canonical/maps/',
    )
    indexes=('/index.json',)
    if name.startswith(protected) or name.endswith(indexes):
        raise StudioError('Modificação direta de índices/IDs/recursos textuais/mapas bloqueada: usar create/update/delete com família apropriada; perfis numéricos exigem migração explícita')
    return inside(repo,name)

def prepare(repo:Path, spec:dict, *, allow_delete=False):
    if spec.get('schema')!=SCHEMA or not isinstance(spec.get('operations'),list) or not spec['operations']:
        raise StudioError(f'Especificação requer schema={SCHEMA} e operations[] não vazio')
    canonical=canonical_path(repo)
    changes:dict[str,bytes|None]={}; asset_new=[]
    def get(path:Path):
        rel=path.relative_to(repo).as_posix()
        if rel in changes:
            val=changes[rel]
            if val is None:raise StudioError('Ficheiro já eliminado nesta transação: '+rel)
            return json.loads(val)
        if not path.is_file():raise StudioError('Ficheiro não encontrado: '+rel)
        return load_json(path)
    def put(path:Path,doc):changes[path.relative_to(repo).as_posix()]=jbytes(doc)
    def locate_index(family):
        table={'text': 'text/index.json','stage_spawns':'stage_spawns/index.json',
             'stage_start_points':'stage_start_points/index.json','fixed_npcs':'fixed_npcs/index.json'}
        if family not in table:raise StudioError('Família indexada inválida: '+str(family))
        idx=canonical/table[family];return idx,idx.parent
    for n,op in enumerate(spec['operations']):
        kind=op.get('op','')
        try:
            if kind in ('create','update','delete'):
                fam=op.get('family')
                if fam=='map':
                    maps=canonical/'maps'; data=op.get('profiles',{})
                    if kind!='delete' and set(data)!={'client','server'}:
                        raise StudioError('Mapas exigem definitions client+server; passar profiles.client e profiles.server')
                    identifier=op.get('id') or (data.get('client') or {}).get('id')
                    if not identifier:raise StudioError('ID do mapa em falta')
                    for profile in ('client','server'):
                        p=maps/f'{profile}.maps.json';d=get(p);arr=d['maps'];matches=[i for i,x in enumerate(arr) if x.get('id')==identifier]
                        if len(matches)>1:raise StudioError(f'{profile}: ID de mapa duplicado')
                        if kind=='create':
                            if matches:raise StudioError(f'{profile}: mapa {identifier} já existe')
                            val=data[profile]
                            if val.get('id')!=identifier:raise StudioError(f'{profile}: ID difere')
                            arr.append(val)
                        elif kind=='update':
                            if not matches:raise StudioError(f'{profile}: mapa {identifier} não existe')
                            if data[profile].get('id')!=identifier:raise StudioError('Não renumerar o mapa durante update')
                            if data[profile].get('legacy_field_code')!=arr[matches[0]].get('legacy_field_code'):
                                raise StudioError('Código de campo do mapa protegido; criar migração explícita')
                            arr[matches[0]]=data[profile]
                        else:
                            if not allow_delete:raise StudioError('Para eliminar, acrescentar --confirm-delete')
                            if not matches:raise StudioError(f'{profile}: mapa não existe')
                            arr.pop(matches[0])
                        d['map_count']=len(arr);put(p,d)
                    continue
                idxpath,base=locate_index(fam); index=get(idxpath);entries=index.get('documents')
                if not isinstance(entries,list):raise StudioError('Índice sem documents[]')
                ident=op.get('id') or (op.get('document') or {}).get('id')
                if not ident:raise StudioError('id obrigatório')
                matches=[e for e in entries if e.get('id')==ident]
                if len(matches)>1:raise StudioError('ID duplicado no índice')
                if kind=='create':
                    if matches:raise StudioError('ID já existe: '+ident)
                    rel=op.get('json_path')
                    p=inside(base,rel)
                    if p.exists() or p.relative_to(repo).as_posix() in changes:raise StudioError('Destino já existe: '+str(p))
                    doc=op.get('document');
                    if not isinstance(doc,dict) or doc.get('id')!=ident:raise StudioError('document.id não coincide com id')
                    if fam=='text' and doc.get('kind')=='open_item_definition':
                        code=(doc.get('semantic') or {}).get('fields',{}).get('code')
                        if not isinstance(code,str) or not CODE.fullmatch(code) or ident!='item.'+code.lower():
                            raise StudioError('Novo item exige code AA999 e id=item.aa999 sem aliases de identidade')
                        profiles=canonical/'item_profiles'
                        for manifest in ('client_item_code_map.json','item_code_map.json'):
                            codes=[x['code'] for x in load_json(profiles/manifest)['entries']]
                            if code not in codes:raise StudioError('Novo item '+code+' não possui ID nativo em '+manifest+'; criar/migrar ID explicitamente antes da publicação')
                        # Existing canonical item with the same numeric code must never be shadowed.
                        for row in entries:
                            if row.get('kind')!='open_item_definition':continue
                            oldpath=inside(base,row['json_path'])
                            old=get(oldpath)
                            if (old.get('semantic') or {}).get('fields',{}).get('code')==code:
                                raise StudioError('Código de item já utilizado pela definição '+str(row['id']))
                    if fam=='text':
                        rp=doc.get('runtime_paths',[])
                        if not isinstance(rp,list) or not rp:raise StudioError('text requer runtime_paths válidos')
                        ent={'id':ident,'kind':doc.get('kind',''),'legacy_path':(doc.get('source') or {}).get('legacy_path','<generated>'),
                             'json_path':rel,'runtime_paths':rp,'legacy_sha256':(doc.get('source') or {}).get('legacy_sha256','')}
                        if not ent['kind']:raise StudioError('text requer kind')
                    else:
                        ent={'id':ident,'logical_path':doc.get('logical_path'), 'json_path':rel}
                        if not ent['logical_path']:raise StudioError('Família indexada exige logical_path')
                    entries.append(ent);put(idxpath,index);put(p,doc)
                elif kind=='update':
                    if not matches:raise StudioError('ID não encontrado: '+ident)
                    p=inside(base,matches[0]['json_path'],existing=True); old=get(p);new=op.get('document')
                    if not isinstance(new,dict) or new.get('id')!=ident:raise StudioError('Identidade não pode mudar')
                    if fam=='text':
                        if new.get('kind')!=old.get('kind'):raise StudioError('Mudança de kind requer nova entidade')
                        matches[0]['runtime_paths']=new.get('runtime_paths',[])
                        matches[0]['legacy_sha256']=(new.get('source') or {}).get('legacy_sha256','')
                    else:matches[0]['logical_path']=new.get('logical_path')
                    put(idxpath,index);put(p,new)
                else:
                    if not allow_delete:raise StudioError('Delete exige --confirm-delete')
                    if not matches:raise StudioError('ID não encontrado: '+ident)
                    p=inside(base,matches[0]['json_path'],existing=True); old=get(p)
                    if old.get('kind')=='open_item_definition':raise StudioError('Eliminar item com identidade publicada pode corromper DAT; operação bloqueada')
                    if fam=='text':
                        # Protect against dangling refs in other canonical files, not based on same resource.
                        for candidate in (canonical/'text/resources').rglob('*.json'):
                            if candidate==p:continue
                            raw=candidate.read_text(encoding='utf-8')
                            if f'"{ident}"' in raw or any(f'"{x}"' in raw for x in old.get('runtime_paths',[])):
                                raise StudioError(f'{ident} ainda referido em {candidate.relative_to(canonical)}')
                    entries.remove(matches[0]);put(idxpath,index)
                    changes[p.relative_to(repo).as_posix()]=None
            elif kind in ('append','set','remove'):
                p=resolve_doc(repo,op['path']);d=get(p);par,last=pointer(d,op['pointer'])
                if kind=='append':
                    arr=ptr_get(d,op['pointer'])
                    if not isinstance(arr,list):raise StudioError('append exige array')
                    value=op.get('value')
                    if value in arr:raise StudioError('append duplicado: objeto já existe')
                    arr.append(value)
                elif kind=='set':
                    if isinstance(par,list):
                        ix=int(last)
                        if ix<0 or ix>=len(par):raise StudioError('Índice fora dos limites')
                        par[ix]=op.get('value')
                    else:
                        if last not in par:raise StudioError('Chave nova não permitida por set; usar create em documento completo')
                        par[last]=op.get('value')
                else:
                    if not allow_delete:raise StudioError('remove exige --confirm-delete')
                    if isinstance(par,list):
                        ix=int(last)
                        if ix<0 or ix>=len(par):raise StudioError('Índice fora dos limites')
                        par.pop(ix)
                    else:
                        if last not in par:raise StudioError('Chave inexistente')
                        del par[last]
                put(p,d)
            elif kind=='asset_import':
                family=op.get('family')
                if family not in EXTENSIONS:raise StudioError('Asset family inválida: '+str(family))
                dest=op.get('destination','')
                if not (dest.startswith('cliente/') or dest.startswith('Servidor/')):raise StudioError('Assets apenas em cliente/ ou Servidor/')
                destination=inside(repo,dest)
                if destination.exists():raise StudioError('Asset de destino já existe (sem overwrite): '+dest)
                src=Path(op.get('source','')).expanduser()
                if not src.is_absolute():src=inside(repo,op.get('source',''),existing=True)
                if not src.is_file() or src.is_symlink():raise StudioError('Asset fonte não é ficheiro regular: '+str(src))
                if EXTENSIONS[family] is not None and destination.suffix.lower() not in EXTENSIONS[family]:raise StudioError('Extensão inválida para '+family)
                data=src.read_bytes()
                if not data:raise StudioError('Asset vazio')
                expected=op.get('sha256')
                if expected and expected!=sha(data):raise StudioError(f'Asset SHA divergente: {src}')
                if family=='icon' and destination.suffix.lower()=='.bmp':
                    if len(data)<54 or data[:2]!=b'BM':raise StudioError('Ícone BMP inválido; não renomear PNG para BMP')
                rel=destination.relative_to(repo).as_posix()
                if rel in changes:raise StudioError('Asset de destino duplicado')
                changes[rel]=data;asset_new.append(rel)
            else:raise StudioError('Operação desconhecida: '+str(kind))
        except (KeyError,TypeError,ValueError,IndexError) as exc:raise StudioError(f'operations[{n}]: {exc}') from exc
    if not changes:raise StudioError('Transação não altera ficheiros')
    return changes,asset_new

def stage_validate(repo:Path,changes:dict[str,bytes|None],asset_new:list[str]) -> Audit:
    # Audit a private clone of canonical before committing anything to the actual project.
    with tempfile.TemporaryDirectory(prefix='summit_content_studio_') as tmp:
        staging=Path(tmp);(staging/'SourceCode/Content').mkdir(parents=True)
        shutil.copytree(repo/'SourceCode/Content/canonical',staging/'SourceCode/Content/canonical')
        (staging/'SourceCode/tools').symlink_to((repo/'SourceCode/tools').resolve(),target_is_directory=True)
        # metadata inventory sources may be omitted in staging; intentionally no false PASS
        for rel,data in changes.items():
            if not rel.startswith('SourceCode/Content/canonical/'):continue
            p=inside(staging,rel)
            if data is None:
                if p.exists():p.unlink()
            else:
                p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        a=Audit(staging,'candidate')
        c=staging/'SourceCode/Content/canonical'
        if basic_json_check(a,c):
            try:text_and_links(a,c);id_maps(a,c,staging/'SourceCode')
            except Exception as exc:a.error('CANDIDATE',str(exc))
            cp=repo/'SourceCode/tools/content_port'
            run_gate(a,'VAL_TEXT',cp/'validate_canonical_text.py',[str(c/'text')], 'Reparar o documento proposto')
            args=['--canonical-text',str(c/'text'),'--canonical-spawns',str(c/'stage_spawns'),
               '--canonical-maps',str(c/'maps'),'--canonical-start-points',str(c/'stage_start_points'),
               '--canonical-fixed-npcs',str(c/'fixed_npcs')]
            run_gate(a,'VAL_SCHEMA',cp/'validate_canonical_schemas.py',args,'Respeitar schema da família; ver erro detalhado')
            run_gate(a,'VAL_MAP_POLICY',cp/'validate_single_entry_map_policy.py',['--canonical-maps',str(c/'maps')],
                'Ajustar start_points/centro/autoridade do mapa')
        for rel in asset_new:
            data=changes[rel]
            if not data:a.error('ASSET','Asset vazio',rel)
            else:a.ok('ASSET','Fonte existente, bytes reais e destino novo',rel)
        return a

def apply_spec(repo:Path,spec:dict,*,dry_run=False,allow_delete=False):
    changes,asset_new=prepare(repo,spec,allow_delete=allow_delete)
    print(f'CONTENT_CHANGE_PREVIEW files={len(changes)} assets={len(asset_new)}')
    for rel,data in changes.items():print(f'  {"DELETE" if data is None else "WRITE"} {rel} sha={sha(data)[:16] if data is not None else "-"}')
    if any(not x.startswith('SourceCode/Content/canonical/') for x in changes):
        print('WARNING: cópia de assets físicos exige que a referência canónica seja criada/atualizada separadamente')
    staged=stage_validate(repo,changes,asset_new)
    if show_report(staged,'text'):
        raise StudioError('CANDIDATE_INVALID: nenhum ficheiro do projeto foi alterado')
    if dry_run:
        print('SUMMIT_CONTENT_CHANGE_PLAN_PASS read_only=1');return
    txroot=repo/'bugfixes/_content_studio_transactions';txroot.mkdir(parents=True,exist_ok=True)
    lock=txroot/'.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise StudioError('Outra transação ou lock pendente: '+str(lock))
    os.close(fd)
    try:
        # Optimistic check on all touched files before writing
        original={}; preconditions=spec.get('preconditions',{})
        for rel,data in changes.items():
            p=inside(repo,rel)
            current=p.read_bytes() if p.is_file() else None
            if data is None and current is None:raise StudioError('Ficheiro para eliminar já não existe: '+rel)
            if current is not None and rel in asset_new:raise StudioError('Asset de destino passou a existir: '+rel)
            expected=preconditions.get(rel)
            if expected is not None and expected!=(sha(current) if current is not None else None):
                raise StudioError(f'Precondition SHA alterada: {rel}')
            original[rel]=current
        txid=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8]
        tx=txroot/txid;tx.mkdir()
        rows=[]
        for i,(rel,data) in enumerate(changes.items()):
            current=original[rel];backup=None
            if current is not None:
                backup=f'backup/{i:04d}.bin'; bp=tx/backup;bp.parent.mkdir(parents=True,exist_ok=True);bp.write_bytes(current)
            rows.append({'path':rel,'before_sha256':sha(current) if current is not None else None,
                         'after_sha256':sha(data) if data is not None else None,'backup':backup})
        manifest={'schema':'summit.content-studio-transaction/v1','status':'PREPARED','id':txid,'changes':rows}
        (tx/'manifest.json').write_bytes(jbytes(manifest))
        completed=[]
        try:
            for rel,data in changes.items():
                target=inside(repo,rel)
                if data is None:target.unlink()
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    tmpfile=target.parent/f'.{target.name}.{uuid.uuid4().hex}.tmp'
                    try:tmpfile.write_bytes(data);os.replace(tmpfile,target)
                    finally:
                        if tmpfile.exists():tmpfile.unlink()
                completed.append(rel)
        except Exception:
            for rel in reversed(completed):
                target=inside(repo,rel);old=original[rel]
                if old is None:
                    if target.exists():target.unlink()
                else:target.write_bytes(old)
            raise
        manifest['status']='APPLIED';(tx/'manifest.json').write_bytes(jbytes(manifest))
        print(f'SUMMIT_CONTENT_CHANGE_APPLIED tx={txid} files={len(rows)} backup={tx}')
    finally:lock.unlink(missing_ok=True)

def undo(repo:Path,txid:str):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}',txid):raise StudioError('ID de transação inválido')
    tx=inside(repo/'bugfixes/_content_studio_transactions',txid)
    m=load_json(tx/'manifest.json')
    if m.get('status')!='APPLIED':raise StudioError('Transação não está APPLIED')
    changes=m.get('changes',[])
    if not changes:raise StudioError('Manifest sem alterações')
    # First verify all files; never undo a user's later edit.
    for row in changes:
        p=inside(repo,row['path']); actual=file_sha(p) if p.is_file() else None
        if actual!=row['after_sha256']:raise StudioError('Undo BLOQUEADO: alteração posterior em '+row['path'])
        if row['backup']:
            b=inside(tx,row['backup'],existing=True)
            if file_sha(b)!=row['before_sha256']:raise StudioError('Backup corrompido: '+str(b))
    for row in reversed(changes):
        p=inside(repo,row['path'])
        if row['backup']:
            data=inside(tx,row['backup'],existing=True).read_bytes();p.parent.mkdir(parents=True,exist_ok=True)
            temp=p.parent/f'.{p.name}.{uuid.uuid4().hex}.restore';temp.write_bytes(data);os.replace(temp,p)
        elif p.exists():p.unlink()
    m['status']='UNDONE';(tx/'manifest.json').write_bytes(jbytes(m))
    print(f'SUMMIT_CONTENT_CHANGE_UNDONE tx={txid} files={len(changes)} backups_preserved=1')

def make_template(repo:Path,family:str,output:Path):
    c=canonical_path(repo)
    families={
        'item':('text/resources/Servidor/GameServer/OpenItem','*.txt.json'),
        'monster':('text/resources/Servidor/GameServer/Monster','*.inf.json'),
        'npc':('text/resources/Servidor/GameServer/NPC','*.npc.json'),
        'spawn':('stage_spawns/spawns/GameServer/Field','*.json'),
        'map':('maps','client.maps.json'),
    }
    if family not in families:raise StudioError('template suporta item, monster, npc, spawn e map; assets físicos exigem asset_import')
    directory,pat=families[family];files=sorted((c/directory).glob(pat))
    if not files:raise StudioError('Exemplo real da família não encontrado: '+family)
    doc=load_json(files[0]);doc['id']='EDIT_ME_NEW_ID'
    if family=='map':
        sample=doc['maps'][0];sample['id']='EDIT_ME_NEW_MAP_ID'
        sample2=copy.deepcopy(sample)
        spec={'schema':SCHEMA,'operations':[{'op':'create','family':'map','id':'EDIT_ME_NEW_MAP_ID','profiles':{'client':sample,'server':sample2}}]}
    else:
        fam='text' if family in ('item','monster','npc') else 'stage_spawns'
        rel=('resources/Servidor/GameServer/'+{'item':'OpenItem/NEW.txt.json','monster':'Monster/NEW.inf.json','npc':'NPC/NEW.npc.json'}.get(family,'')) if fam=='text' else 'spawns/GameServer/Field/NEW.ase.spm.json'
        spec={'schema':SCHEMA,'operations':[{'op':'create','family':fam,'id':doc['id'],'json_path':rel,'document':doc}]}
    if output.exists():raise StudioError('Template já existe; não substituir: '+str(output))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(jbytes(spec))
    print(f'SUMMIT_CONTENT_TEMPLATE_WRITTEN family={family} path={output} STATUS=RASCUNHO_NAO_PUBLICAR')


def program(root:Path,name:str,args:list[str]):
    script=root/'SourceCode/tools/content_port'/name
    if not script.is_file():raise StudioError('Ferramenta nativa em falta: '+str(script))
    print('EXEC_NATIVE='+name,flush=True)
    p=subprocess.run([sys.executable,str(script),*map(str,args)],cwd=root)
    if p.returncode:raise StudioError(f'{name} falhou com exit={p.returncode}; não continuar para publicação')

def main(argv=None):
    ap=argparse.ArgumentParser(description='SUMMIT Content Studio: creator, validator, compiler, publisher, transações')
    ap.add_argument('--root',type=Path,default=Path('.'),help='Raiz com SourceCode, cliente, Servidor')
    sub=ap.add_subparsers(dest='command',required=True)
    v=sub.add_parser('validate',help='Preflight sem alterações');v.add_argument('--phase',choices=['source','post-build','post-deploy'],default='source');v.add_argument('--format',choices=['text','json'],default='text');v.add_argument('--report',type=Path);v.add_argument('--strict-assets',action='store_true')
    sub.add_parser('catalog',help='Tipos de conteúdo e operações suportados')
    for command in ('template','creator'):
        t=sub.add_parser(command,help='Gerar rascunho a partir de recurso real');t.add_argument('--family',choices=['item','monster','npc','map','spawn'],required=True);t.add_argument('--output',type=Path,required=True)
    change=sub.add_parser('change',help='CRUD transacional; dry-run por omissão');change.add_argument('--spec',type=Path,required=True);change.add_argument('--apply',action='store_true');change.add_argument('--confirm-delete',action='store_true')
    u=sub.add_parser('undo',help='Repor uma transação se nada foi alterado entretanto');u.add_argument('--transaction',required=True)
    sub.add_parser('compile',help='Preflight + compilador canónico nativo; NÃO publica automaticamente')
    pub=sub.add_parser('publish',help='Publicação nativa de packs; exige pré-verificação');pub.add_argument('--ack-runtime-stopped',action='store_true');pub.add_argument('--strict-assets',action='store_true')
    args=ap.parse_args(argv);root=args.root.expanduser().resolve()
    try:
        if args.command=='validate':
            return show_report(validate(root,args.phase,strict_assets=args.strict_assets),args.format,args.report)
        if args.command=='catalog':
            print('SUMMIT_CONTENT_STUDIO_CREATOR_CAPABILITIES')
            print('INDEXED: item/monster/npc/other text-resource, stage_spawns, stage_start_points, fixed_npcs: create/update/delete')
            print('MAP: create/update/delete em client e server simultaneamente; legacy_field_code protegido')
            print('JSON: append/set/remove via JSON pointer em qualquer ficheiro canónico (crafting, drops, quests, lojas, etc.)')
            print('ASSETS: asset_import de icon/model/animation/sound/texture/particle/map_asset reais, sem sobrescrita')
            print('LIMITS: não cria .inx/.smd/.smb/.ase, rigging, animação, DLL/EXE nem efeitos nativos a partir de JSON')
            print('WORKFLOW: template -> editar JSON -> change --spec (prévia) -> change --apply -> validate -> compile -> publish')
            return 0
        if args.command in ('template','creator'):make_template(root,args.family,args.output);return 0
        if args.command=='change':
            spec=load_json(args.spec.expanduser().resolve());apply_spec(root,spec,dry_run=not args.apply,allow_delete=args.confirm_delete);return 0
        if args.command=='undo':undo(root,args.transaction);return 0
        if args.command=='compile':
            if show_report(validate(root,'source'),'text'):raise StudioError('PREFLIGHT_BLOCK: compilação cancelada; corrigir erros da fonte')
            program(root,'consolidate_canonical_content.py',['--repo-root',str(root),'--no-deploy'])
            if show_report(validate(root,'post-build'),'text'):raise StudioError('POSTBUILD_BLOCK: packs gerados mas inválidos; não publicar')
            print('SUMMIT_CONTENT_COMPILE_PASS packs_verified=1 published=0');return 0
        if args.command=='publish':
            if not args.ack_runtime_stopped:raise StudioError('Publicação exige --ack-runtime-stopped: parar cliente/servidor antes de publicar')
            if show_report(validate(root,'source',strict_assets=args.strict_assets),'text'):
                raise StudioError('PREFLIGHT_BLOCK: não publicar fonte inválida')
            if show_report(validate(root,'post-build'),'text'):
                raise StudioError('POSTBUILD_BLOCK: não publicar packs inválidos ou antigos')
            # Blocking pre-publication checks for files outside pack deploy's scope.
            server_map=root/'Servidor/Content/packs/item_code_map.json'
            canonical_map=root/'SourceCode/Content/canonical/item_profiles/item_code_map.json'
            if not server_map.is_file() or file_sha(server_map)!=file_sha(canonical_map):
                raise StudioError('PREPUBLISH_BLOCK PUB002: item_code_map.json do servidor não coincide com canónico; deploy_runtime_content.py não o distribui. Sincronizar por publicador de IDs primeiro')
            if show_report(validate(root,'source',strict_assets=True),'text'):
                raise StudioError('PREPUBLISH_BLOCK: assets do cliente inválidos ou em falta')
            # Deploy native can write; explicit action only. Extra runtime ID-map is intentionally not copied.
            program(root,'deploy_runtime_content.py',['--repo-root',str(root)])
            audit=validate(root,'post-deploy',strict_assets=True)
            if show_report(audit,'text'):
                raise StudioError('POSTDEPLOY_INCOMPLETE: packs distribuídos, faltam verificar/sincronizar assets ou item_code_map via fluxo próprio')
            print('SUMMIT_CONTENT_PUBLISH_PASS role_packs_verified=1 runtime_smoke_test=PENDING');return 0
        raise StudioError('Comando desconhecido')
    except (StudioError,OSError) as exc:
        print('SUMMIT_CONTENT_BLOCKED '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
