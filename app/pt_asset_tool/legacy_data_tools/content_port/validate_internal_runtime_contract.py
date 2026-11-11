#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

RUNTIME_FILES = (
    'Shared/content/v1/definition/content/DefinitionRuntime.h',
    'Shared/content/v1/skin_reform/content/SkinReformRuntime.h',
    'Shared/content/v1/text_resource/content/TextResourceRuntime.h',
    'Shared/content/v1/localization/content/LocalizationRuntime.h',
    'Shared/content/v1/gameplay_config/content/GameplayConfigRuntime.h',
    'Shared/content/v1/gameplay_reference/content/GameplayReferenceRuntime.h',
    'Shared/content/v1/stage_spawn/legacy/LegacyStageSpawnAdapter.h',
    'Shared/server/legacy_runtime/OnSever_legacy_client.inl',
    'Shared/server/legacy_runtime/OnSever_legacy_server.inl',
    'Shared/world/field/field_legacy_client.inl',
    'Shared/world/field/field_legacy_server.inl',
)


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate that compiled-content pack selection is internal to the client/server binaries')
    ap.add_argument('--source-root', type=Path, default=Path('.'))
    args = ap.parse_args()
    root = args.source_root.resolve()
    errors: list[str] = []

    texts: dict[str, str] = {}
    for rel in RUNTIME_FILES:
        path = root / rel
        if not path.is_file():
            errors.append(f'missing runtime file: {rel}')
            continue
        text = path.read_text(encoding='utf-8', errors='surrogateescape')
        texts[rel] = text
        allowed_env = {
            'SUMMIT_LOCALIZATION_STRICT',
            'SUMMIT_LOCALE',
        }
        env_names = re.findall(r"getenv\([\"'](SUMMIT_[A-Z0-9_]+)[\"']\)", text)
        for name in env_names:
            if name not in allowed_env:
                errors.append(f'content activation reads unsupported SUMMIT environment variable in {rel}: {name}')

    definition = texts.get('Shared/content/v1/definition/content/DefinitionRuntime.h', '')
    for needle in ('definitions_client.scfg', 'definitions_server.scfg', 'CompiledItemDefinitionsEnabled(){return true;}'):
        if needle not in definition:
            errors.append(f'definition runtime contract missing: {needle}')

    client_field = texts.get('Shared/world/field/field_legacy_client.inl', '')
    server_field = texts.get('Shared/world/field/field_legacy_server.inl', '')
    if 'ResolveRuntimePackPath("maps_client.smap")' not in client_field:
        errors.append('client map runtime does not resolve maps_client.smap internally')
    if 'ResolveRuntimePackPath("maps_server.smap")' not in server_field:
        errors.append('server map runtime does not resolve maps_server.smap internally')

    stage = texts.get('Shared/content/v1/stage_spawn/legacy/LegacyStageSpawnAdapter.h', '')
    if 'ResolveRuntimePackPath("field_runtime.sfld")' not in stage:
        errors.append('stage-spawn runtime does not resolve field_runtime.sfld internally')


    for rel in ('Shared/server/legacy_runtime/OnSever_legacy_client.inl', 'Shared/server/legacy_runtime/OnSever_legacy_server.inl'):
        text = texts.get(rel, '')
        if text and 'ResolveRuntimePackPath("field_runtime.sfld")' not in text:
            errors.append(f'field placement runtime does not resolve field_runtime.sfld internally: {rel}')
        for forbidden in ('fread(StartPoint,', 'fread(TransCharFixed,'):
            if forbidden in text:
                errors.append(f'legacy SPP/SPC runtime read remains active in {rel}: {forbidden}')
        for forbidden in ('fwrite(StartPoint,', 'fwrite(TransCharFixed,'):
            if forbidden in text:
                errors.append(f'legacy SPP/SPC runtime write remains active in {rel}: {forbidden}')
        for forbidden in ('OpenNpc(lpFindPlayerInfo);', 'SaveStartPoint(szStartPointFile);', 'SaveCharInfoFixed(szCharFixedFile);'):
            if forbidden in text:
                errors.append(f'legacy live field authoring remains active in {rel}: {forbidden}')

    expected = {
        'Shared/content/v1/text_resource/content/TextResourceRuntime.h': 'ResolveRuntimePackPath("text_resources.sres")',
        'Shared/content/v1/localization/content/LocalizationRuntime.h': 'ActiveTextResourceSource()',
        'Shared/content/v1/gameplay_config/content/GameplayConfigRuntime.h': 'ResolveRuntimePackPath("gameplay_config.sgcf")',
        'Shared/content/v1/gameplay_reference/content/GameplayReferenceRuntime.h': 'ResolveRuntimePackPath("gameplay_reference.sgrf")',
        'Shared/content/v1/skin_reform/content/SkinReformRuntime.h': 'ResolveRuntimePackPath("skin_reforms.sskm")',
    }
    for rel, needle in expected.items():
        if needle not in texts.get(rel, ''):
            errors.append(f'internal pack path missing in {rel}: {needle}')

    sh = root / 'tools/use_compiled_content.sh'
    if sh.is_file():
        text = sh.read_text(encoding='utf-8', errors='replace')
        if 'export SUMMIT_' in text:
            errors.append('compatibility shell helper still exports content activation variables')
        if 'activation is built into the client/server binaries' not in text:
            errors.append('compatibility shell helper does not declare internal activation')

    resolver = root / 'Shared/content/v1/runtime/RuntimeContentPath.h'
    if not resolver.is_file():
        errors.append('missing standalone runtime resolver')
    else:
        resolver_text = resolver.read_text(encoding='utf-8', errors='replace')
        shipped_token = 'candidates[count++] = RuntimeJoinPath(executableDirectory, "Content\\\\packs\\\\" + fileName);'
        source_token = 'SourceCode\\\\Content\\\\packs'
        if 'Content\\\\packs\\\\' not in resolver_text or 'GetModuleFileNameA' not in resolver_text:
            errors.append('runtime resolver is not executable-relative standalone content')
        if shipped_token not in resolver_text:
            errors.append('runtime resolver does not prioritize executable-local Content/packs')
        if 'RuntimeRegularFileExists(candidates[i])' not in resolver_text:
            errors.append('runtime resolver does not verify candidate existence')
        if source_token in resolver_text and shipped_token in resolver_text:
            if resolver_text.find(source_token) < resolver_text.find(shipped_token):
                errors.append('source-tree development fallback precedes executable-local content')

    print(f'SOURCE_ROOT={root}')
    print(f'RUNTIME_FILES_CHECKED={len(RUNTIME_FILES)}')
    if errors:
        for error in errors:
            print(f'ERROR={error}')
        print('RESULT=FAIL')
        return 1
    print('CONTENT_ACTIVATION_ENV_READS=LOCALIZATION_OVERRIDES_ONLY')
    print('PACK_RESOLUTION=EXECUTABLE_FIRST_WITH_SOURCE_TREE_DEV_FALLBACK')
    print('CLIENT_DEFINITION_PACK=definitions_client.scfg')
    print('SERVER_DEFINITION_PACK=definitions_server.scfg')
    print('RESULT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
