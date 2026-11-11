from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from item_profile_policy import (  # noqa: E402
    effective_profile_codes,
    explicit_runtime_profiles,
    item_enabled_for_profile,
)
from validate_item_profile_pack import parse_pack, validate_one  # noqa: E402


def _item(item_id: str, code: str, runtime_profiles=None) -> dict:
    document = {
        'schema': 'summit.canonical-text-resource/v1',
        'schema_version': 1,
        'id': item_id,
        'kind': 'open_item_definition',
        'runtime_paths': [f'GameServer/OpenItem/{code}.txt'],
        'source': {'legacy_path': f'GameServer/OpenItem/{code}.txt'},
        'semantic': {
            'fields': {'code': code},
            'directives': [
                {
                    'line': 1,
                    'key': 'code',
                    'legacy_token': '*code',
                    'legacy_token_hex': '2ac4dab5e5',
                    'loader_status': 'supported_mapped',
                    'values': [code],
                    'raw_values_hex': [code.encode('ascii').hex()],
                    'quoted': [True],
                }
            ],
            'unknown_tokens': {},
        },
    }
    if runtime_profiles is not None:
        document['runtime_profiles'] = runtime_profiles
    return document


def test_explicit_runtime_profiles_override_legacy_fallback() -> None:
    legacy = {'gb101'}
    fallback = _item('item.gb101', 'GB101')
    promoted = _item('item.sp123', 'SP123', ['client', 'server'])
    server_only = _item('item.server_only', 'SV001', ['server'])

    assert item_enabled_for_profile(fallback, 'client', legacy)
    assert item_enabled_for_profile(promoted, 'client', legacy)
    assert item_enabled_for_profile(promoted, 'server', legacy)
    assert not item_enabled_for_profile(server_only, 'client', legacy)
    assert item_enabled_for_profile(server_only, 'server', legacy)

    assert effective_profile_codes([fallback, promoted, server_only], 'client', legacy) == {
        'gb101', 'sp123'
    }
    assert effective_profile_codes([fallback, promoted, server_only], 'server', legacy) == {
        'gb101', 'sp123', 'sv001'
    }


def test_empty_explicit_profiles_disable_legacy_item() -> None:
    disabled = _item('item.gb101', 'GB101', [])
    assert explicit_runtime_profiles(disabled) == frozenset()
    assert not item_enabled_for_profile(disabled, 'client', {'gb101'})
    assert not item_enabled_for_profile(disabled, 'server', {'gb101'})


def test_compile_definitions_honors_canonical_profile_override(tmp_path: Path) -> None:
    tool_root = Path(__file__).resolve().parents[1]
    canonical = tmp_path / 'canonical'
    canonical.mkdir()

    documents = [
        _item('item.gb101', 'GB101'),
        _item('item.sp123', 'SP123', ['client', 'server']),
        _item('item.server_only', 'SV001', ['server']),
    ]
    index_rows = []
    for document in documents:
        path = canonical / f"{document['id']}.json"
        path.write_text(json.dumps(document), encoding='utf-8')
        index_rows.append({
            'id': document['id'],
            'kind': document['kind'],
            'json_path': path.name,
        })
    (canonical / 'index.json').write_text(
        json.dumps({'schema': 'test', 'documents': index_rows}), encoding='utf-8'
    )

    profile = tmp_path / 'client.items.json'
    profile.write_text(
        json.dumps({
            'schema': 'summit.item-profile/v1',
            'profile': 'client',
            'matching': 'ascii-case-insensitive',
            'codes': ['GB101'],
            'source': {'path': 'legacy.inc', 'sha256': 'unused-by-compiler'},
        }),
        encoding='utf-8',
    )

    output = tmp_path / 'definitions_client.scfg'
    subprocess.run(
        [
            sys.executable,
            str(tool_root / 'compile_definitions.py'),
            str(canonical),
            str(output),
            '--item-profile',
            str(profile),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    rows = parse_pack(output)
    codes = {str(row['code']).casefold() for row in rows if row.get('code')}
    assert codes == {'gb101', 'sp123'}

    report = json.loads(output.with_suffix('.scfg.report.json').read_text(encoding='utf-8'))
    assert report['canonical_profile_overrides'] == 2
    decisions = {row['id']: row['decision'] for row in report['canonical_profile_override_rows']}
    assert decisions == {'item.sp123': 'include', 'item.server_only': 'exclude'}
    filtered = {row['id']: row['filter_source'] for row in report['filtered_open_item_rows']}
    assert filtered == {'item.server_only': 'canonical_runtime_profiles'}


def test_validator_accepts_explicit_canonical_include(tmp_path: Path) -> None:
    tool_root = Path(__file__).resolve().parents[1]
    source_root = tmp_path / 'source'
    source_root.mkdir()
    legacy_source = source_root / 'legacy.inc'
    legacy_source.write_text('legacy fallback fixture\n', encoding='utf-8')

    canonical = tmp_path / 'canonical-text'
    canonical.mkdir()
    documents = [
        _item('item.gb101', 'GB101'),
        _item('item.sp123', 'SP123', ['client', 'server']),
    ]
    index_rows = []
    for document in documents:
        path = canonical / f"{document['id']}.json"
        path.write_text(json.dumps(document), encoding='utf-8')
        index_rows.append({
            'id': document['id'],
            'kind': document['kind'],
            'json_path': path.name,
        })
    (canonical / 'index.json').write_text(
        json.dumps({'schema': 'test', 'documents': index_rows}), encoding='utf-8'
    )

    profiles = tmp_path / 'profiles'
    profiles.mkdir()
    profile = profiles / 'client.items.json'
    profile.write_text(
        json.dumps({
            'schema': 'summit.item-profile/v1',
            'profile': 'client',
            'matching': 'ascii-case-insensitive',
            'codes': ['GB101'],
            'source': {
                'path': 'legacy.inc',
                'sha256': hashlib.sha256(legacy_source.read_bytes()).hexdigest(),
            },
        }),
        encoding='utf-8',
    )

    content_root = tmp_path / 'content'
    packs = content_root / 'packs'
    packs.mkdir(parents=True)
    output = packs / 'definitions_client.scfg'
    subprocess.run(
        [
            sys.executable,
            str(tool_root / 'compile_definitions.py'),
            str(canonical),
            str(output),
            '--item-profile',
            str(profile),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    ok, lines = validate_one(
        source_root,
        content_root,
        'client',
        item_profiles_root=profiles,
        canonical_text_root=canonical,
    )
    assert ok, '\n'.join(lines)
    assert any(line == 'LEGACY_PROFILE_CODES=1' for line in lines)
    assert any(line == 'EFFECTIVE_PROFILE_CODES=2' for line in lines)
