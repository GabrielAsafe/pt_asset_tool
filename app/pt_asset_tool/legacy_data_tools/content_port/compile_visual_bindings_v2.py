#!/usr/bin/env python3
"""Constrói bindings V2 apenas para associações declaradas no catálogo canónico.

O INX é uma cache compilada de caminho lógico INI, não precisa do nome da malha.
Candidatos do relatório de provas não entram automaticamente no jogo.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, sys

CAT = 'SourceCode/Content/canonical/item_visuals/catalog.json'
PROFILE = 'SourceCode/Content/canonical/item_profiles/item_code_map.json'
# Actual M1..M7 biped link families. M8 is deliberately omitted: no
# class code has been established for that family in this checkout.
MOTION_FAMILY = {'fighter':1, 'mechanician':1, 'knight':1,
                 'archer':2, 'atalanta':2, 'magician':3,
                 'pikeman':4, 'priestess':5, 'assassin':6, 'shaman':7}
JOBS = {'fighter':1, 'mechanician':2, 'archer':3, 'pikeman':4,
        'atalanta':5, 'knight':6, 'magician':7, 'priestess':8,
        'assassin':9, 'shaman':10}

def safe_path(value):
    if not isinstance(value, str) or len(value)>180 or not re.fullmatch(r'[A-Za-z0-9_./-]+',value):
        raise ValueError('unsafe path: '+str(value))
    path=pathlib.PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not value.startswith('char/tmABCD/'):
        raise ValueError('unsafe model location: '+value)
    return value

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def collect(root, *, require_assets=True):
    catalog=json.loads((root/CAT).read_text(encoding='utf8'))
    profile=json.loads((root/PROFILE).read_text(encoding='utf8'))
    if catalog.get('schema')!='summit.item-visuals/v1':raise ValueError('visual schema mismatch')
    ids={x['code']:int(x['numeric'],16) for x in profile['entries']}
    rows=[]; seen=set(); unbound=[]
    for item in catalog['items']:
        code=item['code']; ident=int(item['id'],16)
        if code in seen or ids.get(code)!=ident:raise ValueError('identity conflict: '+code)
        seen.add(code)
        if item['slot']!=14 or item['kind']!='costume':raise ValueError('not a costume: '+code)
        configs=item.get('equippedConfigs',{})
        groups=item.get('equippedGroups',{})
        if not isinstance(groups,dict) or any(k not in item['equippedModels'] for k in groups):
            raise ValueError('unknown equippedGroups class for '+code)
        if not isinstance(configs,dict) or any(k not in item['equippedModels'] for k in configs):
            raise ValueError('unknown equippedConfigs class for '+code)
        for cls, model in item['equippedModels'].items():
            if cls not in JOBS:raise ValueError('class not defined: '+cls)
            model=safe_path(model)
            if not model.lower().endswith('.smd'):raise ValueError('expected .smd')
            # Explicit config is mandatory whenever the logical INI/compiled
            # INX has a DIFFERENT name from the SMD (e.g. Football Ca011).
            # Existing Dragon bindings use a verified same-stem cache.
            logical=safe_path(configs[cls]) if cls in configs else model[:-4]+'.ini'
            if not logical.lower().endswith('.ini'):raise ValueError('expected logical .ini')
            inx=logical[:-4]+'.inx'
            group_override=groups.get(cls)
            if group_override is not None and (not isinstance(group_override,str) or
                not re.fullmatch(r'[A-Za-z0-9_]{1,15}',group_override)):
                raise ValueError('invalid mesh group override: '+code+' '+cls)
            smd_path=root/'cliente'/model; inx_path=root/'cliente'/inx
            present=smd_path.is_file() and inx_path.is_file()
            if require_assets and not present:
                raise ValueError('missing SMD/INX for '+code+' '+cls)
            if present:
                if inx_path.stat().st_size != 95268:
                    raise ValueError('unexpected INX size: '+inx)
                model_name = model.rsplit('/',1)[-1][:-4].casefold()
                raw_ref = inx_path.read_bytes()[:64].split(b'\0', 1)[0].decode('latin1', 'replace')
                if raw_ref.replace('\\','/').rsplit('/',1)[-1].casefold() != model_name + '.ase':
                    raise ValueError('INX model reference mismatch: '+inx+' -> '+raw_ref)
                # An INX may point to a valid SMD but use a skeleton intended
                # for another class. Check the actual EX-format link field
                # before publishing; file existence alone is insufficient.
                raw = inx_path.read_bytes()
                model_group_count = int.from_bytes(raw[192:196], 'little', signed=True)
                group_model = raw[196:212].split(b'\0',1)[0].decode('cp949','replace')
                if model_group_count != 1 or group_model.casefold() != (group_override or model_name).casefold():
                    raise ValueError('INX high model group mismatch: '+inx+' -> '+group_model)
                link = raw[88472:88536].split(b'\0',1)[0].decode('cp949','replace').replace('\\','/')
                match = re.search(r'/M([1-8])bip\.in$',link,re.IGNORECASE)
                if not match or int(match.group(1)) != MOTION_FAMILY[cls]:
                    raise ValueError('INX biped family mismatch: '+inx+' '+cls+' -> '+link)
            row={'code':code,'id':ident,'job':JOBS[cls], 'class':cls,
                 'smd':model,'config':logical,'inx':inx,'motion_family':MOTION_FAMILY[cls], 'mesh_group':group_override, 'present':present}
            if present:
                row['smd_sha256']=sha(smd_path)
                row['inx_sha256']=sha(inx_path)
            rows.append(row)
    # Inventory assets that are not yet bound must remain visible as candidates.
    known={r['smd'].casefold() for r in rows}
    for p in sorted((root/'cliente/char/tmABCD').glob('CA87*.smd')):
        if p.relative_to(root/'cliente').as_posix().casefold() not in known:
            unbound.append(p.relative_to(root/'cliente').as_posix())
    return rows,unbound

def generate_header(rows):
    active=[r for r in rows if r['present']]
    by_config={}
    for r in active:
        logical=r['config'].casefold()
        identity=(r['smd'].casefold(), r['motion_family'])
        if logical in by_config and by_config[logical] != identity:
            raise ValueError('conflicting models for logical INI: '+r['config'])
        by_config[logical]=identity
    lines=['// Generated by compile_visual_bindings_v2.py; never modify manually',
           '#pragma once','#include <cstdint>','#include <string>','#include <cctype>',
           'namespace summit { namespace inventory { namespace visual_v2 {',
           'struct Binding { std::uint32_t itemCode; int job; const char* config; const char* inx; const char* smd; unsigned motionFamily; const char* meshGroup; };',
           'inline const Binding* Find(std::uint32_t code, int job) {',
           '  static const Binding entries[] = {']
    for r in sorted(active,key=lambda r:(r['id'],r['job'])):
        config=r['config']; inx=r['inx']  # Keep canonical relative separators
        group=('"'+r['mesh_group']+'"') if r.get('mesh_group') else 'nullptr'
        lines.append('    {0x%08Xu, %d, "%s", "%s", "%s", %du, %s}, // %s %s' % (r['id'],r['job'],config,inx,r['smd'],r['motion_family'],group,r['code'],r['class']))
    lines.extend(['  };','  for (const auto& row : entries) if(row.itemCode==code && row.job==job) return &row;',
                  '  return nullptr;','}',
                  'inline bool LogicalConfigEquals(const char *a, const char *b) {',
                  '  if (!a || !b) return false;',
                  '  while (*a && *b) {',
                  '    const char ca = *a == 92 ? 47 : static_cast<char>(std::tolower(static_cast<unsigned char>(*a)));',
                  '    const char cb = *b == 92 ? 47 : static_cast<char>(std::tolower(static_cast<unsigned char>(*b)));',
                  '    if (ca != cb) return false;',
                  '    ++a; ++b;',
                  '  }',
                  '  return !*a && !*b;',
                  '}',
                  'inline const Binding *FindByConfig(const char *config) {',
                  '  if (!config) return nullptr;',
                  '  const std::uint32_t ids[] = {'+', '.join('0x%08Xu'%id for id in sorted({r['id'] for r in active}))+'};',
                  '  for (auto id : ids) for (int job=1; job<=10; ++job) {',
                  '    const Binding *row = Find(id, job);',
                  '    if (row && LogicalConfigEquals(row->config, config)) return row;',
                  '  }',
                  '  return nullptr;',
                  '}',
                  'inline bool HasAnyBinding(std::uint32_t code) {',
                  '  static const std::uint32_t itemIds[] = {'+', '.join('0x%08Xu'%id for id in sorted({r['id'] for r in active}))+'};',
                  '  for (auto id : itemIds) {',
                  '    if (id == code) return true;',
                  '  }',
                  '  return false;',
                  '}','}}} // summit::inventory::visual_v2',''])
    return '\n'.join(lines)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True,type=pathlib.Path)
    ap.add_argument('--out',required=True,type=pathlib.Path)
    ap.add_argument('--report',required=True,type=pathlib.Path)
    ap.add_argument('--allow-missing-assets',action='store_true')
    args=ap.parse_args();root=args.root.expanduser().resolve()
    rows,unbound=collect(root,require_assets=not args.allow_missing_assets)
    # Never publish bindings without a physical INX. Unvalidated candidates are not activated.
    report={'schema':'summit.item-visual-binding-build/v2', 'bindings':rows,
            'unbound_dragon_assets':unbound,'activated':sum(r['present'] for r in rows),
            'skipped':sum(not r['present'] for r in rows),
            'note':'File presence/size is NOT a successful Wine/render test'}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(generate_header(rows),encoding='utf-8')
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('BINDINGS=',report['activated'],'UNBOUND_DRAGON=',len(unbound), 'SKIPPED=',report['skipped'])
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError) as ex: print('VISUAL_BINDINGS_FAIL=',ex,file=sys.stderr);sys.exit(2)
