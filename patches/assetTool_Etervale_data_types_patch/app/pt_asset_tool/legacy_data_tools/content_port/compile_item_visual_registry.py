#!/usr/bin/env python3
"""Compila definições visuais canónicas para lookup O(1) do cliente.
O compilador não insere regras especiais por código no C++.
"""
import argparse
import json
import pathlib
import re
import sys

JOBS = {
 'fighter':'JOBCODE_FIGHTER', 'mechanician':'JOBCODE_MECHANICIAN',
 'pikeman':'JOBCODE_PIKEMAN', 'knight':'JOBCODE_KNIGHT',
 'magician':'JOBCODE_MAGICIAN', 'archer':'JOBCODE_ARCHER',
 'atalanta':'JOBCODE_ATALANTA', 'priestess':'JOBCODE_PRIESTESS',
 'assassin':'JOBCODE_ASSASSIN', 'shaman':'JOBCODE_SHAMAN'
}
DEST = 'SourceCode/SrcGame/src/core/gameplay/legacy_support/ItemVisualRegistryGenerated.h'
CANON = 'SourceCode/Content/canonical/item_visuals/catalog.json'
CATALOG = 'SourceCode/SrcGame/src/systems/inventory/legacy/item_catalog_recovered.inc'
PROFILE = 'SourceCode/Content/canonical/item_profiles/item_code_map.json'


def check_path(p, extensions):
    if not isinstance(p, str) or len(p)>180 or '\\' in p or '..' in pathlib.PurePosixPath(p).parts or p.startswith('/') or ':' in p:
        raise ValueError(f'Caminho inseguro/invalido: {p}')
    if not p.lower().endswith(extensions):
        raise ValueError(f'Extensao invalida: {p}')


def validate(doc, repo, check_assets=True):
    if doc.get('schema')!='summit.item-visuals/v1':raise ValueError('Esquema item-visuals incorreto')
    items=doc.get('items')
    if not isinstance(items,list) or not items:raise ValueError('Sem itens')
    reg={}
    # The recovered legacy catalog may be a PARTIAL fixture. The canonical
    # numeric map is complete in the captured Content; where a legacy entry
    # exists, require strict numeric parity rather than rejecting absent rows.
    profile=json.loads((repo/PROFILE).read_text(encoding='utf-8'))
    numeric={x['code']:int(x['numeric'],16) for x in profile['entries']}
    legacy=(repo/CATALOG)
    catalog=legacy.read_text(encoding='utf-8',errors='replace') if legacy.is_file() else ''
    for it in items:
        code=it['code']
        if not re.fullmatch('[A-Z]{2}[0-9]{3}',code):raise ValueError('Codigo invalido: '+str(code))
        ident=int(it['id'],16) if isinstance(it['id'],str) else int(it['id'])
        if code in reg or ident in [x['id'] for x in reg.values()]:raise ValueError('ID/codigo duplicado')
        if numeric.get(code) != ident:
            raise ValueError(f'ID {code} / 0x{ident:08X} nao confere no mapa canonico')
        # Check legacy catalog when an entry for this code was actually captured.
        # Absence in a partial legacy snapshot does not authorize inventing IDs.
        legacy_pattern=rf'sITEM\(0x([0-9a-fA-F]+)u,\s*"[^"]*",\s*"{re.escape(code)}",'
        matched=re.search(legacy_pattern,catalog,re.I)
        if matched and int(matched.group(1),16)!=ident:
            raise ValueError(f'ID {code} nao confere no catalogo C++')
        if it.get('kind')!='costume' or it.get('slot')!=14:
            raise ValueError('Este primeiro adapter suporta apenas visuais de traje (slot 14)')
        models=it.get('equippedModels',{})
        if not isinstance(models,dict) or not models:raise ValueError('Sem modelos por classe para '+code)
        groups=it.get('equippedGroups',{})
        if not isinstance(groups,dict) or any(job not in models for job in groups):
            raise ValueError('Grupo para classe inexistente: '+code)
        for group in groups.values():
            if not isinstance(group,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',group):
                raise ValueError('Grupo de malha invalido: '+code)
        configs=it.get('equippedConfigs',{})
        if not isinstance(configs,dict) or any(job not in models for job in configs):
            raise ValueError('Configuracao para classe inexistente: '+code)
        for job,path in models.items():
            if job not in JOBS:raise ValueError('Classe desconhecida: '+job)
            check_path(path,('.smd',))
            if not path.startswith('char/tmABCD/'):
                raise ValueError('Modelo de traje fora da familia: '+path)
            # The model INX name is derived from the *logical config*, not
            # necessarily the SMD name. Football ships with Cb011.inx for
            # CtmbB11.smd, for example.
            ini=configs.get(job,path[:-4]+'.ini')
            check_path(ini,('.ini',))
            if not ini.startswith('char/tmABCD/'):
                raise ValueError('Configuracao fora da familia: '+ini)
            inx=ini[:-4]+'.inx'
            if check_assets and not (repo/'cliente'/path).is_file():raise ValueError('SMD em falta: '+path)
            if check_assets and not (repo/'cliente'/inx).is_file():raise ValueError('INX em falta: '+inx)
        icon=it.get('icon',''); drop=it.get('dropModel','')
        # Some historic item identities have no item-visual icon/drop override;
        # those are materialized by the existing item catalog, not invented here.
        if icon:
            check_path(icon,('.bmp',))
            if check_assets and not (repo/'cliente'/icon).is_file():raise ValueError('Icone em falta: '+icon)
        if drop:
            check_path(drop,('.smd',))
            if check_assets and not (repo/'cliente'/drop).is_file():raise ValueError('Drop em falta: '+drop)
        reg[code]={'id':ident, 'slot':14, 'kind':'costume', 'models':models, 'icon':icon, 'drop':drop}
    return reg


def q(text):return json.dumps(text,ensure_ascii=True)

def generate(reg):
    lines=['// SUMMIT_ITEM_VISUAL_REGISTRY_V1 — GERADO A PARTIR DE Content/canonical/item_visuals/catalog.json',
         '// NAO EDITAR: python3 SourceCode/tools/content_port/compile_item_visual_registry.py',
         '#pragma once', '#include <unordered_map>', '#include <string>', '#include <cstdint>',
         'namespace summit { namespace content { namespace item_visuals {',
         'struct ItemVisual {',
         '  std::uint32_t itemId; int slot; const char* kind; const char* icon; const char* dropModel;',
         '  std::unordered_map<int, std::string> equippedModels;',
         '};',
         'inline const std::unordered_map<std::uint32_t, ItemVisual>& Registry() {',
         '  static const std::unordered_map<std::uint32_t, ItemVisual> catalog = {']
    for code,item in sorted(reg.items()):
        models=', '.join('{%s, %s}'%(JOBS[job],q(path)) for job,path in sorted(item['models'].items()))
        lines.append('    {0x%08Xu, {0x%08Xu, %d, %s, %s, %s, {%s}}}, // %s' %
          (item['id'],item['id'],item['slot'],q(item['kind']),q(item['icon']),q(item['drop']),models,code))
    lines.extend(['  }; return catalog;', '}',
         'inline const ItemVisual* Find(std::uint32_t code) {',
         '  const auto& all = Registry(); auto it = all.find(code); return it==all.end()?nullptr:&it->second;',
         '}',
         'inline bool HasModelForJob(const ItemVisual& record, int jobCode) {',
         '  return record.equippedModels.find(jobCode)!=record.equippedModels.end();',
         '}',
         'inline bool ResolveModel(const ItemVisual& record, int jobCode, std::string& path) {',
         '  auto it=record.equippedModels.find(jobCode); if(it==record.equippedModels.end()) return false;',
         '  path=it->second; return true;',
         '}', '}}} // summit::content::item_visuals',''])
    return '\n'.join(lines)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo-root',type=pathlib.Path,default=pathlib.Path.home()/'Área de Trabalho/summit')
    ap.add_argument('--no-check-assets',action='store_true')
    ap.add_argument('--verify',action='store_true')
    args=ap.parse_args()
    repo=args.repo_root.expanduser().resolve()
    reg=validate(json.loads((repo/CANON).read_text(encoding='utf-8')),repo,not args.no_check_assets)
    text=generate(reg)
    target=repo/DEST
    if args.verify:
        if not target.is_file() or target.read_text(encoding='utf-8')!=text:raise ValueError('Header gerado desatualizado')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists() or target.read_text(encoding='utf-8')!=text:
            target.write_text(text,encoding='utf-8')
    print('ITEM_VISUAL_REGISTRY=PASS | entradas=%d | header=%s' % (len(reg),target))

if __name__=='__main__':
    try:main()
    except Exception as e:print('ITEM_VISUAL_REGISTRY=FAIL:',e,file=sys.stderr);sys.exit(1)
