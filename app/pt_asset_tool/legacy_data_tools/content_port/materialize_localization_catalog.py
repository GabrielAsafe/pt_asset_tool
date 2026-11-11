#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
from collections import defaultdict, Counter
from pathlib import Path, PurePosixPath

SCHEMA = 'summit.localization-catalog/v1'
LOCALES = ('en', 'pt-BR', 'zh-TW', 'ko')
TOKEN_LOCALE = {'E': 'en', 'J': 'pt-BR', 'T': 'zh-TW'}
TOKEN_RE = re.compile(br'^\s*\*([EJT])_(NAME|CHAT)\b', re.IGNORECASE)


def norm(path: str) -> str:
    parts = []
    for part in path.replace('\\', '/').split('/'):
        if not part or part == '.':
            continue
        if part == '..':
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return '/'.join(parts)


def runtime_path(doc: dict) -> str:
    for value in doc.get('runtime_paths', []):
        n = norm(value)
        if not n.casefold().startswith(('servidor/', 'cliente/')):
            return n
    return norm(doc['source']['legacy_path'])


def decode_token_value(raw: bytes, token_prefix: str) -> str:
    encodings = {
        'E': ('utf-8', 'cp1252'),
        'J': ('cp1252', 'utf-8'),
        'T': ('big5', 'cp950'),
    }[token_prefix.upper()]
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    # Preserve information without pretending it decoded cleanly.
    return raw.decode('latin1')


def extract_zhoon_locales(doc: dict) -> dict[str, dict[str, list[str]]]:
    payload = base64.b64decode(doc['compatibility']['legacy_payload_base64'])
    out: dict[str, dict[str, list[str]]] = defaultdict(lambda: {'name': [], 'chat': []})
    for raw_line in payload.splitlines():
        m = TOKEN_RE.match(raw_line)
        if not m:
            continue
        prefix = m.group(1).decode('ascii').upper()
        kind = m.group(2).decode('ascii').lower()
        rest = raw_line[m.end():].strip()
        if not rest:
            value_bytes = b''
        elif rest.startswith(b'"'):
            # Historical resources do not use escaped quotes as a grammar.
            end = rest.rfind(b'"')
            value_bytes = rest[1:end] if end > 0 else rest[1:]
        else:
            value_bytes = rest.split(None, 1)[0]
        out[TOKEN_LOCALE[prefix]][kind].append(decode_token_value(value_bytes, prefix))
    return out


def contains_hangul(value: str) -> bool:
    return any('\uac00' <= ch <= '\ud7a3' for ch in value)


def linked_resource(def_doc: dict, by_path: dict[str, dict]) -> dict | None:
    linked = def_doc.get('semantic', {}).get('fields', {}).get('linked_file')
    if not isinstance(linked, str) or not linked:
        return None
    base = PurePosixPath(runtime_path(def_doc)).parent.as_posix()
    target = norm(base + '/' + linked).casefold()
    return by_path.get(target)


def add_entry(entries: dict[str, list[dict]], locale: str, key: str, text: str, quality: str, source: str) -> None:
    if not isinstance(text, str) or text == '':
        return
    entries[locale].append({
        'key': key,
        'text': text,
        'quality': quality,
        'source': source,
    })


def choose_first(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ''


def build_catalog(canonical_root: Path) -> dict:
    root = canonical_root.resolve()
    index = json.loads((root / 'index.json').read_text(encoding='utf-8'))['documents']
    docs = [json.loads((root / e['json_path']).read_text(encoding='utf-8')) for e in index]
    by_path: dict[str, dict] = {}
    for d in docs:
        for alias in d.get('runtime_paths', []):
            by_path[norm(alias).casefold()] = d

    zhoon_cache: dict[str, dict[str, dict[str, list[str]]]] = {}
    for d in docs:
        if d.get('kind') == 'localization_resource':
            zhoon_cache[d['id']] = extract_zhoon_locales(d)

    entries: dict[str, list[dict]] = {locale: [] for locale in LOCALES}
    bindings = []
    stats = Counter()

    # Source-controlled runtime/UI messages. Runtime-visible strings live in
    # canonical JSON and are materialized into the same SLOC catalogue.
    runtime_messages_path = root / 'runtime_messages.json'
    if runtime_messages_path.is_file():
        runtime_messages = json.loads(runtime_messages_path.read_text(encoding='utf-8'))
        if runtime_messages.get('schema') != 'summit.runtime-localization-source/v1':
            raise ValueError(f'unsupported runtime message schema: {runtime_messages.get("schema")!r}')
        seen_runtime_keys = set()
        for item in runtime_messages.get('entries', []):
            key = item.get('key')
            locales = item.get('locales')
            if not isinstance(key, str) or not key or key in seen_runtime_keys:
                raise ValueError(f'invalid/duplicate runtime localization key: {key!r}')
            if not isinstance(locales, dict) or not isinstance(locales.get('en'), str) or not locales.get('en'):
                raise ValueError(f'runtime localization key {key!r} requires an English value')
            seen_runtime_keys.add(key)
            for locale, text in locales.items():
                if locale not in LOCALES:
                    raise ValueError(f'unsupported runtime locale {locale!r} for key {key!r}')
                if not isinstance(text, str) or not text:
                    raise ValueError(f'empty runtime localization value for {locale}:{key}')
                add_entry(entries, locale, key, text, 'translated', 'runtime_messages')
            if 'pt-BR' not in locales:
                add_entry(entries, 'pt-BR', key, locales['en'], 'untranslated_fallback', 'runtime_messages')

    definition_kinds = {'monster_definition', 'npc_definition', 'open_item_definition'}
    for d in sorted((x for x in docs if x.get('kind') in definition_kinds), key=lambda x: x['id']):
        fields = d.get('semantic', {}).get('fields', {})
        name_key = f"{d['id']}.name"
        linked = linked_resource(d, by_path)
        localized = zhoon_cache.get(linked['id'], {}) if linked else {}

        e_name = choose_first(*(localized.get('en', {}).get('name', [])[:1]))
        j_name = choose_first(*(localized.get('pt-BR', {}).get('name', [])[:1]))
        t_name = choose_first(*(localized.get('zh-TW', {}).get('name', [])[:1]))
        english_name = fields.get('english_name') if isinstance(fields.get('english_name'), str) else ''
        legacy_name = fields.get('name') if isinstance(fields.get('name'), str) else ''

        en_text = choose_first(e_name, english_name, j_name, legacy_name, t_name)
        en_quality = 'translated' if choose_first(e_name, english_name) else 'untranslated_fallback'
        add_entry(entries, 'en', name_key, en_text, en_quality, linked['id'] if linked else d['id'])
        if en_quality == 'untranslated_fallback':
            stats['english_name_fallbacks'] += 1

        pt_text = choose_first(j_name, legacy_name, en_text)
        add_entry(entries, 'pt-BR', name_key, pt_text, 'translated' if j_name else 'legacy_fallback', linked['id'] if linked else d['id'])
        if t_name:
            add_entry(entries, 'zh-TW', name_key, t_name, 'translated', linked['id'])
        if legacy_name and contains_hangul(legacy_name):
            add_entry(entries, 'ko', name_key, legacy_name, 'legacy_source', d['id'])

        chat_keys = []
        chats = {locale: list(localized.get(locale, {}).get('chat', [])) for locale in ('en', 'pt-BR', 'zh-TW')}
        direct_dialog = fields.get('dialog') if isinstance(fields.get('dialog'), str) else ''
        max_chats = max([len(v) for v in chats.values()] + ([1] if direct_dialog else [0]))
        for i in range(max_chats):
            key = f"{d['id']}.chat.{i + 1}"
            en = chats['en'][i] if i < len(chats['en']) else ''
            pt = chats['pt-BR'][i] if i < len(chats['pt-BR']) else ''
            tw = chats['zh-TW'][i] if i < len(chats['zh-TW']) else ''
            legacy = direct_dialog if i == 0 else ''
            en_text = choose_first(en, pt, legacy, tw)
            if not en_text:
                continue
            quality = 'translated' if en else 'untranslated_fallback'
            add_entry(entries, 'en', key, en_text, quality, linked['id'] if linked else d['id'])
            if quality == 'untranslated_fallback':
                stats['english_chat_fallbacks'] += 1
            if pt or legacy:
                add_entry(entries, 'pt-BR', key, choose_first(pt, legacy, en_text), 'translated' if pt else 'legacy_fallback', linked['id'] if linked else d['id'])
            if tw:
                add_entry(entries, 'zh-TW', key, tw, 'translated', linked['id'])
            if legacy and contains_hangul(legacy):
                add_entry(entries, 'ko', key, legacy, 'legacy_source', d['id'])
            chat_keys.append(key)

        bindings.append({
            'content_id': d['id'],
            'kind': d['kind'],
            'name_key': name_key,
            'chat_keys': chat_keys,
            'linked_resource_id': linked['id'] if linked else None,
        })

    # Keep standalone localization resources auditable even when they are not
    # referenced by a Monster/NPC/Item definition.
    bound_resource_ids = {b['linked_resource_id'] for b in bindings if b['linked_resource_id']}
    for d in sorted((x for x in docs if x.get('kind') == 'localization_resource' and x['id'] not in bound_resource_ids), key=lambda x: x['id']):
        localized = zhoon_cache[d['id']]
        for locale, groups in localized.items():
            for i, text in enumerate(groups['name'], 1):
                key = f"{d['id']}.name" if i == 1 else f"{d['id']}.name.{i}"
                add_entry(entries, locale, key, text, 'translated', d['id'])
                if locale != 'en' and not any(e['key'] == key for e in entries['en']):
                    add_entry(entries, 'en', key, text, 'untranslated_fallback', d['id'])
                    stats['english_standalone_fallbacks'] += 1
            for i, text in enumerate(groups['chat'], 1):
                key = f"{d['id']}.chat.{i}"
                add_entry(entries, locale, key, text, 'translated', d['id'])
                if locale != 'en' and not any(e['key'] == key for e in entries['en']):
                    add_entry(entries, 'en', key, text, 'untranslated_fallback', d['id'])
                    stats['english_standalone_fallbacks'] += 1

    # Deterministic de-duplication: exact locale/key duplicates must agree.
    for locale in LOCALES:
        dedup = {}
        for e in entries[locale]:
            old = dedup.get(e['key'])
            if old and old['text'] != e['text']:
                raise ValueError(f'conflicting localization value for {locale}:{e["key"]}: {old["text"]!r} vs {e["text"]!r}')
            if old is None or (old['quality'] != 'translated' and e['quality'] == 'translated'):
                dedup[e['key']] = e
        entries[locale] = [dedup[k] for k in sorted(dedup)]

    # pt-BR is a maintained canonical language, not a permissive J_* fallback.
    # Keep the override outside the generated localization/ directory so rebuilding
    # the catalogs cannot silently re-introduce English/Korean/mojibake into PT.
    pt_override_path = root / 'localization_overrides' / 'pt-BR.json'
    pt_override_loaded = False
    if pt_override_path.exists():
        override_doc = json.loads(pt_override_path.read_text(encoding='utf-8'))
        if override_doc.get('schema') != SCHEMA or override_doc.get('locale') != 'pt-BR':
            raise ValueError(f'invalid pt-BR canonical override: {pt_override_path}')
        override_entries = override_doc.get('entries')
        if not isinstance(override_entries, list):
            raise ValueError(f'pt-BR canonical override entries must be a list: {pt_override_path}')
        override_by_key = {}
        for row in override_entries:
            if not isinstance(row, dict):
                raise ValueError('pt-BR canonical override contains non-object entry')
            key = row.get('key')
            text = row.get('text')
            if not isinstance(key, str) or not key:
                raise ValueError('pt-BR canonical override contains invalid/empty key')
            if key in override_by_key:
                raise ValueError(f'duplicate pt-BR canonical override key: {key}')
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f'empty pt-BR canonical override text: {key}')
            override_by_key[key] = {
                'key': key,
                'text': text,
                'quality': 'translated',
                'source': row.get('source') or 'pt-BR-canonical-override',
            }

        generated_en_keys = {e['key'] for e in entries['en']}
        override_keys = set(override_by_key)
        missing = sorted(generated_en_keys - override_keys)
        extra = sorted(override_keys - generated_en_keys)
        if missing or extra:
            raise ValueError(
                'pt-BR canonical override must exactly cover the runtime catalog: '
                f'missing={len(missing)} {missing[:20]} extra={len(extra)} {extra[:20]}'
            )
        entries['pt-BR'] = [override_by_key[k] for k in sorted(override_by_key)]
        stats['pt_br_canonical_overrides'] = len(entries['pt-BR'])
        pt_override_loaded = True

    en_keys = {e['key'] for e in entries['en']}
    all_keys = {e['key'] for locale in LOCALES for e in entries[locale]}
    missing_en = sorted(all_keys - en_keys)
    if missing_en:
        raise ValueError(f'missing English fallback for {len(missing_en)} localization keys: {missing_en[:20]}')

    loc_root = root / 'localization'
    if loc_root.exists():
        shutil.rmtree(loc_root)
    loc_root.mkdir(parents=True)
    manifests = []
    for locale in LOCALES:
        doc = {
            'schema': SCHEMA,
            'schema_version': 1,
            'locale': locale,
            'fallback_locale': None if locale == 'en' or (locale == 'pt-BR' and pt_override_loaded) else 'en',
            'entries': entries[locale],
        }
        path = loc_root / f'{locale}.json'
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        manifests.append({'locale': locale, 'path': path.relative_to(root).as_posix(), 'entries': len(entries[locale])})
    (loc_root / 'bindings.json').write_text(json.dumps({'schema': 'summit.localization-bindings/v1', 'bindings': bindings}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = {
        'schema': 'summit.localization-report/v1',
        'keys': len(all_keys),
        'english_keys': len(en_keys),
        'locales': {locale: len(entries[locale]) for locale in LOCALES},
        'bindings': len(bindings),
        'fallbacks': dict(stats),
        'missing_english_fallback': 0,
    }
    (loc_root / 'index.json').write_text(json.dumps({'schema': 'summit.localization-index/v1', 'catalogs': manifests, 'bindings': 'localization/bindings.json'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (loc_root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description='Materialize stable-key UTF-8 localization catalogs from canonical JSON resources')
    ap.add_argument('canonical', type=Path)
    args = ap.parse_args()
    print(json.dumps(build_catalog(args.canonical), ensure_ascii=False))


if __name__ == '__main__':
    main()
