#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

MAGIC = b'SLOC'
VERSION = 2
HEADER = struct.Struct('<4sHH10I32s')
RECORD = struct.Struct('<5I')  # locale, key, text, source, flags
QUALITY_FLAGS = {
    'translated': 1,
    'untranslated_fallback': 2,
    'legacy_fallback': 4,
    'legacy_source': 8,
}


def build_sloc_bytes(root: Path) -> tuple[bytes, dict]:
    """Deterministic compiled catalog for embedding into a single SRES v2 pack."""
    root = root.resolve()
    index_path = root / 'localization' / 'index.json'
    if not index_path.is_file():
        raise SystemExit('canonical localization/index.json is missing; run materialize_localization_catalog.py')
    index = json.loads(index_path.read_text(encoding='utf-8'))

    rows = []
    locale_counts = {}
    for entry in index['catalogs']:
        doc = json.loads((root / entry['path']).read_text(encoding='utf-8'))
        locale = doc['locale']
        locale_counts[locale] = len(doc['entries'])
        for value in doc['entries']:
            quality = value['quality']
            if quality not in QUALITY_FLAGS:
                raise ValueError(f'unsupported localization quality {quality!r}')
            rows.append((locale, value['key'], value['text'], value.get('source', ''), QUALITY_FLAGS[quality]))
    rows.sort(key=lambda x: (x[0], x[1]))

    # Every runtime key must have English fallback.
    all_keys = {row[1] for row in rows}
    en_keys = {row[1] for row in rows if row[0] == 'en'}
    missing = sorted(all_keys - en_keys)
    if missing:
        raise ValueError(f'{len(missing)} localization keys have no English fallback: {missing[:20]}')

    strings = bytearray()
    offsets = {}
    def intern(value: str) -> int:
        raw = value.encode('utf-8')
        if b'\0' in raw:
            raise ValueError('NUL in localization string')
        if raw not in offsets:
            offsets[raw] = len(strings)
            strings.extend(raw + b'\0')
        return offsets[raw]

    records = [(intern(locale), intern(key), intern(text), intern(source), flags) for locale, key, text, source, flags in rows]
    record_offset = HEADER.size
    record_size = RECORD.size
    string_offset = record_offset + len(records) * record_size
    string_size = len(strings)
    body = bytearray()
    for record in records:
        body.extend(RECORD.pack(*record))
    body.extend(strings)
    digest = hashlib.sha256(body).digest()
    header = HEADER.pack(
        MAGIC, VERSION, 0,
        len(records), record_offset, record_size,
        string_offset, string_size,
        0, 0, 0, 0, 0,
        digest,
    )
    data = bytes(header + body)
    report = {
        'format': 'SLOC', 'version': VERSION,
        'entries': len(records), 'keys': len(all_keys),
        'english_keys': len(en_keys), 'locales': locale_counts,
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
    }
    return data, report


def main() -> None:
    ap = argparse.ArgumentParser(description='Legacy standalone SLOC compiler (SRES compiler embeds directly)')
    ap.add_argument('canonical', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    data, report = build_sloc_bytes(args.canonical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.with_suffix(args.output.suffix + '.report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
