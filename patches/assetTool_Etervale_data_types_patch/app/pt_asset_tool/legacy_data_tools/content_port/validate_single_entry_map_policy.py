#!/usr/bin/env python3
"""READ ONLY. Verifica a política de entrada para mapas com ponto canónico único.

- 0 pontos: center é a alternativa explícita;
- 1 ponto: center e start_point têm de coincidir (cliente e servidor);
- N pontos (>1): default usa center e entrada contextual usa ponto mais próximo.
Garante também igualdade de coordenadas entre cliente/servidor no mapa 58.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--canonical-maps', type=Path, required=True)
    args = ap.parse_args()
    docs = {}
    errors = []
    one = zero = many = 0
    for role in ('client', 'server'):
        path = args.canonical_maps / f'{role}.maps.json'
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
            if doc.get('profile') != role or not isinstance(doc.get('maps'), list):
                raise ValueError(f'Catálogo ou profile inválido: {path}')
            maps = doc['maps']
            codes = [m['legacy_field_code'] for m in maps]
            if len(codes) != len(set(codes)):
                raise ValueError(f'IDs de mapa duplicados: {role}')
            docs[role] = {m['legacy_field_code']: m for m in maps}
            for m in maps:
                starts = m.get('start_points', [])
                center = m.get('center')
                if not isinstance(starts, list) or not isinstance(center, dict):
                    errors.append(f'{role} mapa={m["legacy_field_code"]}: dados inválidos')
                    continue
                if not starts:
                    zero += 1
                elif len(starts) == 1:
                    one += 1
                    if starts[0] != center:
                        errors.append(f'{role} mapa={m["legacy_field_code"]}: SINGLE_START_DIFF center={center} start={starts[0]}')
                else:
                    many += 1
        except (OSError, ValueError, KeyError, TypeError) as ex:
            errors.append(f'{role}: {ex}')
    if set(docs) == {'client', 'server'}:
        try:
            c = docs['client'][58]
            s = docs['server'][58]
            for field in ('center', 'start_points'):
                if c[field] != s[field]:
                    errors.append(f'map58 CLIENT_SERVER_DIFF {field}')
            if len(c['start_points']) != 1 or len(s['start_points']) != 1:
                errors.append('map58 deve ter exatamente um ponto inicial')
        except (KeyError, TypeError) as ex:
            errors.append(f'map58 ausente/inválido: {ex}')
    print(f'MAPS_SINGLE={one} MAPS_ZERO={zero} MAPS_MULTIPLE={many}')
    print('POLICY=ONE_START_AUTHORITATIVE;ZERO_CENTER_FALLBACK;MULTI_CENTER_DEFAULT_NEAREST_CONTEXTUAL')
    for err in errors:
        print('ERROR=' + err)
    print('RESULT=' + ('FAIL' if errors else 'PASS'))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
