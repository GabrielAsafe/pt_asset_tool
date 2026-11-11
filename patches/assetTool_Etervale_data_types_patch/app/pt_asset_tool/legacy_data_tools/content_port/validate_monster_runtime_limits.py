#!/usr/bin/env python3
"""Valida limites reais de drops e audita HP potencialmente negativo nos monstros.

Fonte de verdade: JSON canónico do Summit. Calcula as entradas materializadas
aplicando os códigos do perfil de itens do servidor; compara as diretivas
interpretadas e os raw_values_hex usados pelo compilador. Sem mutações.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--repo-root', type=Path, required=True)
    cli.add_argument('--strict-map53-hp', action='store_true',
                     help='falha também para HP acima de INT16_MAX nos atores do mapa 53')
    cli.add_argument('--report', type=Path)
    args = cli.parse_args()
    root = args.repo_root.expanduser().resolve()
    canonical = root / 'SourceCode/Content/canonical'
    profile_path = canonical / 'item_profiles/server.items.json'
    header = root / 'SourceCode/Shared/smPacket.h'
    mob_dir = canonical / 'text/resources/Servidor/GameServer/Monster'
    heart_path = canonical / 'stage_spawns/spawns/GameServer/Field/HeartOfFire.ase.spm.json'
    for p in (profile_path, header, heart_path):
        if not p.is_file():
            print(f'ERROR=Ficheiro obrigatorio ausente: {p}', file=sys.stderr)
            return 2
    if not mob_dir.is_dir():
        print('ERROR=Diretorio Monster ausente', file=sys.stderr)
        return 2
    m = re.search(r'^\s*#define\s+FALLITEM_MAX\s+(\d+)', header.read_text(encoding='latin1'), re.M)
    if not m:
        print('ERROR=FALLITEM_MAX nao encontrado', file=sys.stderr)
        return 2
    capacity = int(m.group(1))
    if capacity < 1:
        print('ERROR=FALLITEM_MAX invalido', file=sys.stderr)
        return 2
    server_profile = json.loads(profile_path.read_text(encoding='utf-8'))
    codes = {c.casefold() for c in server_profile['codes'] if isinstance(c, str)}
    heart = json.loads(heart_path.read_text(encoding='utf-8'))
    heart_ids = {a.get('monster_id') for a in heart.get('actors', [])}
    issues = []
    hp_warnings = []
    inspected = 0
    peak = 0
    for path in sorted(mob_dir.glob('*.inf.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc.get('kind') != 'monster_definition':
            continue
        inspected += 1
        mob_id = doc.get('id')
        semantic = doc.get('semantic') or {}
        fields = semantic.get('fields') or {}
        all_directives = semantic.get('directives') or []
        entry = fields.get('fall_item')
        field_rows = entry.get('$repeated', []) if isinstance(entry, dict) else []
        directives = [x for x in all_directives if x.get('key') == 'fall_item']
        # Special/pet/event definitions sometimes have a scalar or absent fall_item
        # and are not represented as $repeated. Only validate repeated tables.
        if isinstance(entry, dict) and field_rows != [x.get('values') for x in directives]:
            issues.append(f'{mob_id}: fall_item fields/directives divergentes')
            continue
        total = 0
        for idx, (row, directive) in enumerate(zip(field_rows, directives), start=1):
            if not isinstance(row, list) or len(row) < 2:
                issues.append(f'{mob_id}: linha {idx} de fall_item malformada')
                continue
            try:
                expected_raw = [str(v).encode('cp949').hex() for v in row]
            except UnicodeEncodeError:
                issues.append(f'{mob_id}: linha {idx} nao codificavel em CP949')
                continue
            if directive.get('raw_values_hex') != expected_raw:
                issues.append(f'{mob_id}: linha {idx} raw_values_hex divergente')
            if row[1] in ('없음', '돈'):
                total += 1
            else:
                total += sum(isinstance(code, str) and code.casefold() in codes for code in row[1:])
        peak = max(peak, total)
        if total > capacity:
            issues.append(f'{mob_id}: FALLITEM_COUNT={total} > FALLITEM_MAX={capacity}')
        hp = fields.get('life')
        if mob_id in heart_ids and isinstance(hp, int) and hp > 32767:
            hp_warnings.append({'monster_id': mob_id, 'hp': hp, 'signed16': ((hp + 32768) % 65536) - 32768})
    missing_heart = sorted(heart_ids - {json.loads(p.read_text(encoding='utf-8')).get('id') for p in mob_dir.glob('*.inf.json')})
    for mob_id in missing_heart:
        issues.append('HeartOfFire: referencia de monstro ausente '+str(mob_id))
    report = {
        'schema': 'summit.monster-runtime-limits/v1',
        'monsters_inspected': inspected, 'fallitem_max': capacity,
        'max_materialized_drop_entries': peak,
        'errors': issues, 'map53_hp_above_signed16': hp_warnings,
        'status': 'FAIL' if issues or (args.strict_map53_hp and hp_warnings) else 'PASS',
    }
    print(f'MONSTER_DEFINITIONS={inspected}')
    print(f'FALLITEM_MAX={capacity}')
    print(f'MAX_MATERIALIZED_DROP_ENTRIES={peak}')
    for issue in issues:
        print('ERROR='+issue)
    for warning in hp_warnings:
        print('WARNING_MAP53_HP '+warning['monster_id']+' hp='+str(warning['hp'])+' signed16='+str(warning['signed16']))
    print('MAP53_HP_WARNINGS='+str(len(hp_warnings)))
    print('RESULT='+report['status'])
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 1 if report['status'] == 'FAIL' else 0


if __name__ == '__main__':
    sys.exit(main())
