#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

VALID_RUNTIME_PROFILES = frozenset({'client', 'server'})


def item_code(document: dict) -> str | None:
    """Return the case-folded legacy item code using the compiler-compatible directive rule."""
    for directive in document.get('semantic', {}).get('directives', []):
        if directive.get('key') != 'code':
            continue
        values = directive.get('raw_values_hex') or []
        if values:
            return bytes.fromhex(values[0]).decode('latin1').strip().casefold()
        semantic = directive.get('values') or []
        if semantic:
            return str(semantic[0]).strip().casefold()
    return None


def explicit_runtime_profiles(document: dict) -> frozenset[str] | None:
    """Return explicit canonical runtime profiles, or None when legacy fallback applies."""
    if 'runtime_profiles' not in document:
        return None
    raw = document.get('runtime_profiles')
    if not isinstance(raw, list):
        raise ValueError(f"{document.get('id', '<unknown>')}: runtime_profiles must be an array")

    normalized: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            raise ValueError(f"{document.get('id', '<unknown>')}: runtime profile must be a string")
        profile = value.strip().casefold()
        if profile not in VALID_RUNTIME_PROFILES:
            raise ValueError(
                f"{document.get('id', '<unknown>')}: unsupported runtime profile {value!r}"
            )
        normalized.append(profile)

    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{document.get('id', '<unknown>')}: duplicate runtime profile")
    return frozenset(normalized)


def item_enabled_for_profile(
    document: dict,
    profile_name: str,
    legacy_profile_codes: set[str] | frozenset[str],
) -> bool:
    """Resolve canonical explicit policy first, then the legacy executable profile fallback."""
    profile = profile_name.strip().casefold()
    if profile not in VALID_RUNTIME_PROFILES:
        raise ValueError(f'unsupported item profile: {profile_name!r}')

    code = item_code(document)
    if code is None:
        return False

    explicit = explicit_runtime_profiles(document)
    if explicit is not None:
        return profile in explicit

    return code in legacy_profile_codes


def load_open_item_documents(canonical_text_root: Path) -> list[dict]:
    """Load indexed canonical OpenItem documents in deterministic index order."""
    root = canonical_text_root.resolve()
    index_path = root / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    rows: list[dict] = []
    for entry in index.get('documents') or []:
        if entry.get('kind') != 'open_item_definition':
            continue
        path = root / entry['json_path']
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('kind') != 'open_item_definition':
            raise ValueError(f'indexed OpenItem has unexpected kind: {path}')
        rows.append(document)
    return rows


def effective_profile_codes(
    documents: Iterable[dict],
    profile_name: str,
    legacy_profile_codes: set[str] | frozenset[str],
) -> set[str]:
    """Return code-level coverage after canonical overrides are applied per document."""
    out: set[str] = set()
    for document in documents:
        code = item_code(document)
        if code and item_enabled_for_profile(document, profile_name, legacy_profile_codes):
            out.add(code)
    return out
