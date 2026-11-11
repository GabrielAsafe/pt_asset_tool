"""SUMMIT 383A: verifica o snapshot JSON do catalogo fisico do Game.exe.

Nao altera o cliente em runtime; falha a build se JSON, .inc e perfil divergirem.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MAP_SOURCE = 'Content/canonical/item_profiles/client_item_code_map.json'
CLIENT_SOURCE = 'SrcGame/src/systems/inventory/legacy/item_catalog_recovered.inc'
MAP_SCHEMA = 'summit.client-item-code-map/v1'
RECORD = re.compile(r'^\s*sITEM\s*\(\s*(0x[0-9A-Fa-f]+)[uUlL]*\s*,\s*"(?:[^"\\]|\\.)*"\s*,\s*"([^"\\]+)"', re.M)
START = re.compile(r'^\s*sITEM\s*\(', re.M)
CODE = re.compile(r'^(?:[a-zA-Z]{2}[0-9]{3}|RESULT[1-6])$')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows_from_inc(data: bytes) -> list[dict[str, str]]:
    s = data.decode('utf-8-sig', 'replace')
    matches = RECORD.findall(s)
    if not 100 <= len(matches) <= 4000 or len(matches) != len(START.findall(s)):
        raise ValueError('SUMMIT383A: catalogo sITEM inesperado/incompleto')
    rows = []
    for numeric, code in matches:
        if not CODE.fullmatch(code) or not 0 < int(numeric, 16) <= 0xFFFFFFFF:
            raise ValueError('SUMMIT383A: item CODE/numeric invalido: ' + repr((numeric, code)))
        rows.append({'code': code, 'numeric': f'0x{int(numeric, 16):08X}'})
    return rows


def validate_map(doc: object) -> list[dict[str, str]]:
    if not isinstance(doc, dict) or set(doc) != {'schema', 'source', 'entries'} or doc['schema'] != MAP_SCHEMA:
        raise ValueError('SUMMIT383A: schema do mapa de cliente invalido')
    source = doc['source']
    if not isinstance(source, dict) or set(source) != {'path', 'sha256'} or source['path'] != CLIENT_SOURCE or not re.fullmatch('[0-9a-f]{64}', str(source['sha256'])):
        raise ValueError('SUMMIT383A: metadata de origem invalida')
    entries = doc['entries']
    if not isinstance(entries, list) or not 100 <= len(entries) <= 4000:
        raise ValueError('SUMMIT383A: tamanho do mapa invalido')
    for item in entries:
        if not isinstance(item, dict) or set(item) != {'code', 'numeric'} or not isinstance(item['code'], str) or not CODE.fullmatch(item['code']) or not isinstance(item['numeric'], str) or not re.fullmatch('0x[0-9A-F]{8}', item['numeric']) or int(item['numeric'], 16) == 0:
            raise ValueError('SUMMIT383A: entrada do mapa invalida')
    return entries


def verify_client_snapshot_383a(profile: dict, source_root: Path, snapshot_path: Path) -> None:
    document = json.loads(snapshot_path.read_text(encoding='utf-8'))
    entries = validate_map(document)
    physical = source_root / CLIENT_SOURCE
    if not physical.is_file() or physical.is_symlink():
        raise ValueError('SUMMIT383A: catalogo real do cliente ausente/symlink: ' + str(physical))
    inc_bytes = physical.read_bytes()
    if sha(inc_bytes) != document['source']['sha256']:
        raise ValueError('SUMMIT383A: client_item_code_map.json diverge do item_catalog_recovered.inc; executar sync_client_profile_383a.py inspect')
    real = rows_from_inc(inc_bytes)
    if [(x['code'].casefold(),x['numeric']) for x in entries] != [(x['code'].casefold(),x['numeric']) for x in real]:
        raise ValueError('SUMMIT383A: mapeamento JSON divergente do catalogo C++ do cliente')
    codes = profile.get('codes')
    if not isinstance(codes, list) or len(codes) != len(set(str(c).casefold() for c in codes)) or {str(c).casefold() for c in codes} != {x['code'].casefold() for x in real}:
        raise ValueError('SUMMIT383A: perfil cliente e mapa JSON divergem nos codigos')
