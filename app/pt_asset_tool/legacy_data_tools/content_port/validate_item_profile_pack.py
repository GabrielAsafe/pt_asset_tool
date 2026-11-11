#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
from pathlib import Path

from item_profile_policy import effective_profile_codes,item_enabled_for_profile,load_open_item_documents
from client_profile_map_383a import verify_client_snapshot_383a  # SUMMIT383A_VALIDATE_CLIENT_JSON

HEADER = struct.Struct('<4sHH10I32s')
RECORD = struct.Struct('<5I')
DIRECTIVE = struct.Struct('<3I')
OPEN_ITEM_KIND = 3
ITEM_TOKEN_CODE = b'\x2A\xC4\xDA\xB5\xE5'
ITEM_TOKEN_UNIQUE = b'\x2A\xC0\xAF\xB4\xCF\xC5\xA9'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unquote(raw: bytes) -> bytes:
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith(b'"') and raw.endswith(b'"'):
        return raw[1:-1]
    return raw


def parse_int(raw: bytes) -> int | None:
    raw = unquote(raw)
    if not raw:
        return 1  # legacy *Unique with no value means TRUE
    try:
        return int(raw.split(None, 1)[0], 0)
    except ValueError:
        return None


def parse_pack(path: Path) -> list[dict[str, object]]:
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise ValueError('SCFG too small')
    h = HEADER.unpack_from(data)
    magic, version, flags, rc, ro, rs, dc, do, ds, so, ss, r0, r1, digest = h
    if magic != b'SCFG' or version != 1:
        raise ValueError('not SCFG v1')
    if flags or r0 or r1:
        raise ValueError('non-canonical SCFG header flags/reserved values')
    if rs != RECORD.size or ds != DIRECTIVE.size:
        raise ValueError('unexpected SCFG record/directive size')
    if hashlib.sha256(data[HEADER.size:]).digest() != digest:
        raise ValueError('SCFG body hash mismatch')
    if ro != HEADER.size or do != ro + rc * rs or so != do + dc * ds or so + ss != len(data):
        raise ValueError('non-canonical SCFG layout')

    def string(off: int) -> bytes:
        if off >= ss:
            raise ValueError('bad string offset')
        begin = so + off
        end = data.find(b'\0', begin, so + ss)
        if end < 0:
            raise ValueError('unterminated SCFG string')
        return data[begin:end]

    rows: list[dict[str, object]] = []
    for i in range(rc):
        po, io, kind, start, count = RECORD.unpack_from(data, ro + i * rs)
        if kind != OPEN_ITEM_KIND:
            continue
        if start > dc or count > dc - start:
            raise ValueError('bad directive range')
        code: str | None = None
        unique: int | None = 0
        for j in range(start, start + count):
            co, vo, dflags = DIRECTIVE.unpack_from(data, do + j * ds)
            if dflags:
                raise ValueError('unexpected directive flags')
            command = string(co)
            values = string(vo)
            if command == ITEM_TOKEN_CODE and code is None:
                code = unquote(values).decode('latin1')
            elif command == ITEM_TOKEN_UNIQUE:
                unique = parse_int(values)
        path_text = string(po).decode('utf-8', 'replace')
        rows.append({
            'path': path_text,
            'content_id': string(io).decode('utf-8', 'replace'),
            'code': code,
            'code_fold': code.casefold() if code else None,
            'unique': unique,
            'direct': _is_direct_openitem(path_text),
        })
    return rows


def _is_direct_openitem(path: str) -> bool:
    normalized = path.replace('\\', '/').strip('/')
    prefix = 'gameserver/openitem/'
    folded = normalized.casefold()
    if not folded.startswith(prefix):
        return False
    return '/' not in normalized[len(prefix):]


def load_profile(path: Path, source_root: Path) -> tuple[dict, set[str]]:
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') != 'summit.item-profile/v1':
        raise ValueError(f'unsupported item profile schema: {path}')
    codes = {str(x).casefold() for x in doc.get('codes') or []}
    if not codes:
        raise ValueError(f'empty item profile: {path}')
    source = doc.get('source') or {}
    rel = source.get('path')
    expected = source.get('sha256')
    if not rel or not expected:
        raise ValueError(f'profile source metadata missing: {path}')
    src = source_root / rel
    if not src.is_file():
        raise ValueError(f'profile source file missing: {src}')
    actual = sha256(src)
    if actual != expected:
        raise ValueError(f'profile source hash is stale: {src}')
    if doc.get('profile') == 'client' and rel == 'Content/canonical/item_profiles/client_item_code_map.json':
        verify_client_snapshot_383a(doc, source_root, src)
    return doc, codes


def validate_one(source_root: Path, content_root: Path, profile_name: str, show_duplicates: bool = False, item_profiles_root: Path | None = None, canonical_text_root: Path | None = None) -> tuple[bool, list[str]]:
    profile_path = (item_profiles_root or (content_root / 'canonical/item_profiles')) / f'{profile_name}.items.json'
    pack_path = content_root / 'packs' / f'definitions_{profile_name}.scfg'
    report_path = pack_path.with_suffix(pack_path.suffix + '.report.json')
    profile, legacy_codes = load_profile(profile_path, source_root)
    if canonical_text_root is None:
        if item_profiles_root is not None:
            canonical_text_root = item_profiles_root.resolve().parent / 'text'
        else:
            canonical_text_root = content_root / 'canonical/text'
    canonical_documents = load_open_item_documents(canonical_text_root)
    docs_by_id = {str(d['id']): d for d in canonical_documents}
    effective_codes = effective_profile_codes(canonical_documents, profile_name, legacy_codes)

    rows = parse_pack(pack_path)
    direct = [r for r in rows if r['direct']]
    missing = [r for r in rows if not r['code']]

    def row_allowed(row: dict[str, object]) -> bool:
        document = docs_by_id.get(str(row.get('content_id') or ''))
        if document is None:
            return False
        return item_enabled_for_profile(document, profile_name, legacy_codes)

    out_of_profile = [r for r in rows if r['code_fold'] and not row_allowed(r)]
    direct_missing = [r for r in direct if not r['code']]
    direct_out = [r for r in direct if r['code_fold'] and not row_allowed(r)]

    direct_codes = [str(r['code_fold']) for r in direct if r['code_fold']]
    counts = collections.Counter(direct_codes)
    duplicates = {k: v for k, v in counts.items() if v > 1}
    represented = set(direct_codes)
    profile_not_direct = effective_codes - represented

    compiler_profile = None
    filtered = None
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        compiler_profile = report.get('profile')
        filtered = report.get('filtered_open_items')

    ok = bool(direct) and not missing and not out_of_profile and compiler_profile == profile_name
    lines = [
        f'PROFILE={profile_name}',
        f'PROFILE_FILE={profile_path}',
        f'PROFILE_SOURCE={profile["source"]["path"]}',
        f'LEGACY_PROFILE_CODES={len(legacy_codes)}',
        f'EFFECTIVE_PROFILE_CODES={len(effective_codes)}',
        f'PACK={pack_path}',
        f'PACK_SHA256={sha256(pack_path)}',
        f'PACK_OPENITEM_RECORDS={len(rows)}',
        f'PACK_DIRECT_OPENITEM_RECORDS={len(direct)}',
        f'PACK_DIRECT_UNIQUE_CODES={len(represented)}',
        f'MISSING_CODE_ALL={len(missing)}',
        f'OUT_OF_PROFILE_ALL={len(out_of_profile)}',
        f'MISSING_CODE_DIRECT={len(direct_missing)}',
        f'OUT_OF_PROFILE_DIRECT={len(direct_out)}',
        f'DUPLICATE_DIRECT_CODES={len(duplicates)}',
        f'PROFILE_CODES_WITHOUT_DIRECT_OPENITEM={len(profile_not_direct)}',
        f'COMPILER_PROFILE={compiler_profile}',
        f'COMPILER_FILTERED_OPENITEMS={filtered}',
    ]
    for r in out_of_profile[:100]:
        lines.append(f"OUT_OF_PROFILE code='{r['code']}' unique={r['unique']} path='{r['path']}'")
    for r in missing[:100]:
        lines.append(f"MISSING_CODE path='{r['path']}'")
    if show_duplicates:
        for code, count in sorted(duplicates.items()):
            variants = [(r['path'], r['unique']) for r in direct if r['code_fold'] == code]
            lines.append(f"DUPLICATE_INFO code='{code}' count={count} variants={variants!r}")
    lines.append(f'RESULT={"PASS" if ok else "FAIL"}')
    lines.append('NOTE=DUPLICATE_DIRECT_CODES is informational: multiple OpenItem records may intentionally share a CODE with different UniqueItem variants.')
    lines.append('NOTE=PROFILE_CODES_WITHOUT_DIRECT_OPENITEM is informational: the effective profile (canonical override plus legacy fallback) may be a superset of startup OpenItem definitions.')
    return ok, lines


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate profiled SCFG OpenItem packs against canonical runtime_profiles with legacy executable profiles as fallback')
    ap.add_argument('--source-root', type=Path, default=Path('.'), help='SourceCode root')
    ap.add_argument('--content-root', type=Path, default=Path('Content'), help='Content root, relative to source-root unless absolute')
    ap.add_argument('--canonical-item-profiles', type=Path, help='Legacy fallback item profiles root when output content root is separate')
    ap.add_argument('--canonical-text', type=Path, help='Canonical text root that owns explicit runtime_profiles overrides')
    ap.add_argument('--profile', choices=('client', 'server', 'both'), default='both')
    ap.add_argument('--report', type=Path)
    ap.add_argument('--show-duplicates', action='store_true', help='list duplicate CODE variants; duplicates are informational')
    args = ap.parse_args()

    source_root = args.source_root.resolve()
    content_root = args.content_root
    if not content_root.is_absolute():
        content_root = source_root / content_root
    content_root = content_root.resolve()

    item_profiles_root = args.canonical_item_profiles.resolve() if args.canonical_item_profiles else None
    canonical_text_root = args.canonical_text.resolve() if args.canonical_text else None

    profiles = ('client', 'server') if args.profile == 'both' else (args.profile,)
    all_lines: list[str] = []
    all_ok = True
    for name in profiles:
        try:
            ok, lines = validate_one(source_root, content_root, name, args.show_duplicates, item_profiles_root, canonical_text_root)
        except Exception as exc:
            ok, lines = False, [f'PROFILE={name}', f'ERROR={exc}', 'RESULT=FAIL']
        all_ok = all_ok and ok
        if all_lines:
            all_lines.append('')
        all_lines.extend(lines)

    all_lines.append('')
    all_lines.append(f'OVERALL_RESULT={"PASS" if all_ok else "FAIL"}')
    text = '\n'.join(all_lines) + '\n'
    print(text, end='')
    if args.report:
        report = args.report if args.report.is_absolute() else source_root / args.report
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text, encoding='utf-8')
    return 0 if all_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
