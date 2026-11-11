#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path
from sres_embedded_localization import extract_sloc_bytes
from sres_embedded_localization import extract_sloc_bytes

SCFG_HEADER = struct.Struct('<4sHH10I32s')
SCFG_RECORD = struct.Struct('<5I')
SCFG_DIRECTIVE = struct.Struct('<3I')
SLOC_HEADER = struct.Struct('<4sHH10I32s')
SLOC_RECORD = struct.Struct('<5I')
ITEM_NAME_TOKEN = '*이름'.encode('cp949')
ITEM_CAPACITY = 32


def unquote(raw: bytes) -> bytes:
    value = raw.strip()
    if len(value) >= 2 and value[:1] == b'"' and value[-1:] == b'"':
        return value[1:-1]
    return value.split(None, 1)[0] if value else b''


def parse_sloc(path: Path) -> dict[tuple[str, str], str]:
    data = extract_sloc_bytes(path) if path.suffix.lower() == '.sres' else path.read_bytes()
    magic, version, flags, count, record_offset, record_size, string_offset, string_size, *_ = SLOC_HEADER.unpack_from(data, 0)
    if magic != b'SLOC' or version != 2 or flags or record_size != SLOC_RECORD.size:
        raise ValueError(f'invalid SLOC: {path}')

    def text(offset: int) -> str:
        start = string_offset + offset
        end = data.index(0, start, string_offset + string_size)
        return data[start:end].decode('utf-8')

    out: dict[tuple[str, str], str] = {}
    for index in range(count):
        locale_off, key_off, text_off, _source_off, _flags = SLOC_RECORD.unpack_from(data, record_offset + index * record_size)
        out[(text(locale_off), text(key_off))] = text(text_off)
    return out


def parse_direct_items(path: Path) -> list[tuple[str, str, bytes]]:
    data = path.read_bytes()
    magic, version, flags, record_count, record_offset, record_size, directive_count, directive_offset, directive_size, string_offset, string_size, *_ = SCFG_HEADER.unpack_from(data, 0)
    if magic != b'SCFG' or version != 1 or flags or record_size != SCFG_RECORD.size or directive_size != SCFG_DIRECTIVE.size:
        raise ValueError(f'invalid SCFG: {path}')

    def raw_string(offset: int) -> bytes:
        start = string_offset + offset
        end = data.index(0, start, string_offset + string_size)
        return data[start:end]

    rows: list[tuple[str, str, bytes]] = []
    for index in range(record_count):
        path_off, id_off, kind, directive_start, directive_len = SCFG_RECORD.unpack_from(data, record_offset + index * record_size)
        if kind != 3:
            continue
        logical_path = raw_string(path_off).decode('utf-8')
        normalized = logical_path.replace('\\', '/').lower()
        prefix = 'gameserver/openitem/'
        if not normalized.startswith(prefix) or '/' in normalized[len(prefix):]:
            continue
        content_id = raw_string(id_off).decode('utf-8')
        legacy_name = b''
        for offset in range(directive_len):
            command_off, values_off, _directive_flags = SCFG_DIRECTIVE.unpack_from(data, directive_offset + (directive_start + offset) * directive_size)
            command = raw_string(command_off)
            values = raw_string(values_off)
            if command == ITEM_NAME_TOKEN or command.lower() == b'*j_name':
                legacy_name = unquote(values)
        rows.append((logical_path, content_id, legacy_name))
    rows.sort(key=lambda row: row[0].replace('\\', '/').lower())
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate UTF-8 SLOC -> legacy byte-buffer localization bridge for OpenItem runtime')
    ap.add_argument('--source-root', type=Path, default=Path('.'))
    args = ap.parse_args()
    root = args.source_root.resolve()
    packs = root / 'Content' / 'packs'
    errors: list[str] = []

    try:
        localization = parse_sloc(packs / 'text_resources.sres')
    except (OSError, ValueError) as exc:
        print(f'ERROR={exc}')
        print('RESULT=FAIL')
        return 1

    for profile in ('client', 'server'):
        try:
            items = parse_direct_items(packs / f'definitions_{profile}.scfg')
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue

        utf8_overflow = 0
        cp1252_rescued = 0
        cp1252_unencodable = 0
        raw_fallback_overflow = 0
        bi128 = None
        for logical_path, content_id, legacy_name in items:
            if len(legacy_name) >= ITEM_CAPACITY:
                raw_fallback_overflow += 1
                errors.append(f'{profile} legacy fallback name overflows {ITEM_CAPACITY} bytes: {logical_path} ({len(legacy_name)})')

            localized = localization.get(('pt-BR', content_id + '.name'))
            if localized is None:
                localized = localization.get(('en', content_id + '.name'))
            if localized is None:
                continue

            utf8_len = len(localized.encode('utf-8'))
            if utf8_len >= ITEM_CAPACITY:
                utf8_overflow += 1
            try:
                encoded = localized.encode('cp1252')
            except UnicodeEncodeError:
                cp1252_unencodable += 1
                continue
            if utf8_len >= ITEM_CAPACITY and len(encoded) < ITEM_CAPACITY:
                cp1252_rescued += 1
            if len(encoded) >= ITEM_CAPACITY:
                errors.append(f'{profile} localized name still overflows after CP1252 encoding: {logical_path} ({len(encoded)})')
            if content_id == 'item.bi128':
                bi128 = (utf8_len, len(encoded))

        print(f'PROFILE={profile}')
        print(f'DIRECT_OPENITEMS={len(items)}')
        print(f'UTF8_ITEM_NAME_OVERFLOW={utf8_overflow}')
        print(f'CP1252_RESCUED_ITEM_NAMES={cp1252_rescued}')
        print(f'CP1252_UNENCODABLE_FALLBACKS={cp1252_unencodable}')
        print(f'RAW_LEGACY_NAME_OVERFLOW={raw_fallback_overflow}')
        if bi128:
            print(f'BI128_UTF8_BYTES={bi128[0]}')
            print(f'BI128_CP1252_BYTES={bi128[1]}')
        if cp1252_rescued == 0:
            errors.append(f'{profile} expected at least one UTF-8 overflow rescued by legacy encoding')

    adapter = root / 'Shared' / 'content' / 'v1' / 'definition' / 'legacy' / 'CompiledDefinitionAdapter.inl'
    encoding = root / 'Shared' / 'content' / 'v1' / 'localization' / 'legacy' / 'LocalizationLegacyEncoding.h'
    if not adapter.is_file():
        errors.append(f'missing adapter: {adapter}')
    if not encoding.is_file():
        errors.append(f'missing localization encoding boundary: {encoding}')
    if adapter.is_file() and encoding.is_file():
        adapter_source = adapter.read_text(encoding='utf-8', errors='replace')
        encoding_source = encoding.read_text(encoding='utf-8', errors='replace')
        for needle in ('EncodeLocalizationUtf8ForLegacy', 'LocalizationStrictMode()'):
            if needle not in adapter_source:
                errors.append(f'localization adapter contract missing: {needle}')
        for needle in ('MultiByteToWideChar(CP_UTF8', 'WideCharToMultiByte', 'return 1252u'):
            if needle not in encoding_source:
                errors.append(f'localization encoding contract missing: {needle}')

    if errors:
        for error in errors:
            print(f'ERROR={error}')
        print('RESULT=FAIL')
        return 1

    print('LEGACY_LOCALIZATION_ENCODING=WINDOWS_1252_FOR_PT_BR')
    print('NON_STRICT_UNENCODABLE_POLICY=PRESERVE_COMPILED_LEGACY_BYTES')
    print('RESULT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
