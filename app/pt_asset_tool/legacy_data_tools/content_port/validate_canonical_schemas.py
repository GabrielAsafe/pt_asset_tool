#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    pass


SUPPORTED_SCHEMA_KEYS = {
    '$schema', '$id', '$defs', '$ref', 'title', 'description',
    'type', 'const', 'enum', 'required', 'properties', 'additionalProperties',
    'items', 'minItems', 'maxItems', 'uniqueItems',
    'minLength', 'maxLength', 'pattern',
    'minimum', 'maximum', 'minProperties', 'maxProperties',
    'anyOf', 'allOf', 'oneOf',
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _instance_type_name(value: Any) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return type(value).__name__


def _matches_type(value: Any, expected: str) -> bool:
    if expected == 'null':
        return value is None
    if expected == 'boolean':
        return isinstance(value, bool)
    if expected == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == 'string':
        return isinstance(value, str)
    if expected == 'array':
        return isinstance(value, list)
    if expected == 'object':
        return isinstance(value, dict)
    raise SchemaValidationError(f'unsupported schema type: {expected!r}')


def _resolve_pointer(root: Any, ref: str) -> Any:
    if not ref.startswith('#/'):
        raise SchemaValidationError(f'only local JSON pointer refs are supported: {ref!r}')
    cur = root
    for token in ref[2:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        if not isinstance(cur, dict) or token not in cur:
            raise SchemaValidationError(f'invalid local $ref: {ref!r}')
        cur = cur[token]
    return cur


def _validate_schema_shape(schema: Any, where: str = '#') -> None:
    if not isinstance(schema, dict):
        raise SchemaValidationError(f'{where}: schema node must be an object')

    unknown = set(schema) - SUPPORTED_SCHEMA_KEYS
    if unknown:
        names = ', '.join(sorted(unknown))
        raise SchemaValidationError(f'{where}: unsupported schema keyword(s): {names}')

    for key in ('properties', '$defs'):
        child_map = schema.get(key)
        if child_map is not None:
            if not isinstance(child_map, dict):
                raise SchemaValidationError(f'{where}/{key}: expected object')
            for name, child in child_map.items():
                _validate_schema_shape(child, f'{where}/{key}/{name}')

    if isinstance(schema.get('additionalProperties'), dict):
        _validate_schema_shape(schema['additionalProperties'], f'{where}/additionalProperties')

    if isinstance(schema.get('items'), dict):
        _validate_schema_shape(schema['items'], f'{where}/items')

    for key in ('anyOf', 'allOf', 'oneOf'):
        branches = schema.get(key)
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                raise SchemaValidationError(f'{where}/{key}: expected non-empty array')
            for index, child in enumerate(branches):
                _validate_schema_shape(child, f'{where}/{key}/{index}')


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    if '$ref' in schema:
        target = _resolve_pointer(root, schema['$ref'])
        _validate(value, target, root, path)
        return

    if 'anyOf' in schema:
        errors = []
        for branch in schema['anyOf']:
            try:
                _validate(value, branch, root, path)
                break
            except SchemaValidationError as exc:
                errors.append(str(exc))
        else:
            raise SchemaValidationError(f'{path}: does not match anyOf: ' + ' | '.join(errors))

    if 'allOf' in schema:
        for branch in schema['allOf']:
            _validate(value, branch, root, path)

    if 'oneOf' in schema:
        matches = 0
        last_error = None
        for branch in schema['oneOf']:
            try:
                _validate(value, branch, root, path)
                matches += 1
            except SchemaValidationError as exc:
                last_error = exc
        if matches != 1:
            suffix = f'; last error: {last_error}' if last_error else ''
            raise SchemaValidationError(f'{path}: expected exactly one oneOf match, got {matches}{suffix}')

    if 'type' in schema:
        expected = schema['type']
        accepted = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in accepted):
            raise SchemaValidationError(
                f'{path}: expected type {expected!r}, got {_instance_type_name(value)!r}'
            )

    if 'const' in schema and not _json_equal(value, schema['const']):
        raise SchemaValidationError(f'{path}: expected const {schema["const"]!r}, got {value!r}')

    if 'enum' in schema and not any(_json_equal(value, item) for item in schema['enum']):
        raise SchemaValidationError(f'{path}: value {value!r} is not in enum {schema["enum"]!r}')

    if isinstance(value, dict):
        required = schema.get('required', [])
        for key in required:
            if key not in value:
                raise SchemaValidationError(f'{path}: missing required property {key!r}')

        min_props = schema.get('minProperties')
        if min_props is not None and len(value) < min_props:
            raise SchemaValidationError(f'{path}: expected at least {min_props} properties, got {len(value)}')
        max_props = schema.get('maxProperties')
        if max_props is not None and len(value) > max_props:
            raise SchemaValidationError(f'{path}: expected at most {max_props} properties, got {len(value)}')

        properties = schema.get('properties', {})
        for key, child_schema in properties.items():
            if key in value:
                _validate(value[key], child_schema, root, f'{path}.{key}')

        additional = schema.get('additionalProperties', True)
        extras = set(value) - set(properties)
        if additional is False and extras:
            raise SchemaValidationError(f'{path}: unexpected properties: {sorted(extras)!r}')
        if isinstance(additional, dict):
            for key in extras:
                _validate(value[key], additional, root, f'{path}.{key}')

    if isinstance(value, list):
        min_items = schema.get('minItems')
        if min_items is not None and len(value) < min_items:
            raise SchemaValidationError(f'{path}: expected at least {min_items} items, got {len(value)}')
        max_items = schema.get('maxItems')
        if max_items is not None and len(value) > max_items:
            raise SchemaValidationError(f'{path}: expected at most {max_items} items, got {len(value)}')

        if schema.get('uniqueItems'):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':')) for item in value]
            if len(encoded) != len(set(encoded)):
                raise SchemaValidationError(f'{path}: array items must be unique')

        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, root, f'{path}[{index}]')

    if isinstance(value, str):
        min_length = schema.get('minLength')
        if min_length is not None and len(value) < min_length:
            raise SchemaValidationError(f'{path}: string shorter than minLength={min_length}')
        max_length = schema.get('maxLength')
        if max_length is not None and len(value) > max_length:
            raise SchemaValidationError(f'{path}: string longer than maxLength={max_length}')
        pattern = schema.get('pattern')
        if pattern is not None and re.search(pattern, value) is None:
            raise SchemaValidationError(f'{path}: string {value!r} does not match pattern {pattern!r}')

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get('minimum')
        if minimum is not None and value < minimum:
            raise SchemaValidationError(f'{path}: value {value!r} is below minimum {minimum!r}')
        maximum = schema.get('maximum')
        if maximum is not None and value > maximum:
            raise SchemaValidationError(f'{path}: value {value!r} is above maximum {maximum!r}')


def validate(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        _validate(value, schema, schema, '$')
    except SchemaValidationError as exc:
        raise SchemaValidationError(f'{label}: {exc}') from exc


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Validate Summit canonical JSON documents against the bundled schema subset (stdlib only)'
    )
    ap.add_argument('--canonical-text', type=Path, required=True)
    ap.add_argument('--canonical-spawns', type=Path, required=True)
    ap.add_argument('--canonical-maps', type=Path, required=True)
    ap.add_argument('--canonical-start-points', type=Path, required=True)
    ap.add_argument('--canonical-fixed-npcs', type=Path, required=True)
    a = ap.parse_args()

    schema_root = Path(__file__).resolve().parent / 'schemas'
    text_schema = load(schema_root / 'canonical_text_resource.schema.json')
    spawn_schema = load(schema_root / 'stage_spawn.schema.json')
    map_schema = load(schema_root / 'map_catalog.schema.json')
    localization_schema = load(schema_root / 'localization_catalog.schema.json')
    start_point_schema = load(schema_root / 'stage_start_points.schema.json')
    fixed_npc_schema = load(schema_root / 'fixed_npcs.schema.json')
    family_schemas = {
        'monster_definition': load(schema_root / 'monster_definition.schema.json'),
        'npc_definition': load(schema_root / 'npc_definition.schema.json'),
        'open_item_definition': load(schema_root / 'item_definition.schema.json'),
    }
    gameplay_schema = load(schema_root / 'gameplay_config.schema.json')

    for schema_name, schema in {
        'canonical_text_resource': text_schema,
        'stage_spawn': spawn_schema,
        'map_catalog': map_schema,
        'localization_catalog': localization_schema,
        'gameplay_config': gameplay_schema,
        'stage_start_points': start_point_schema,
        'fixed_npcs': fixed_npc_schema,
        **family_schemas,
    }.items():
        _validate_schema_shape(schema, f'schema:{schema_name}')

    text_idx = load(a.canonical_text / 'index.json')['documents']
    spawn_idx = load(a.canonical_spawns / 'index.json')['documents']
    start_idx = load(a.canonical_start_points / 'index.json')['documents']
    fixed_idx = load(a.canonical_fixed_npcs / 'index.json')['documents']

    family_counts = {k: 0 for k in family_schemas}
    gameplay_count = 0

    for e in text_idx:
        path = a.canonical_text / e['json_path']
        doc = load(path)
        validate(doc, text_schema, str(path))
        kind = doc.get('kind')
        if kind in family_schemas:
            validate(doc, family_schemas[kind], str(path))
            family_counts[kind] += 1
        if kind == 'ini_config' and doc.get('selection_reason') == 'immutable_gameplay_config':
            validate(doc, gameplay_schema, str(path))
            gameplay_count += 1

    for e in spawn_idx:
        path = a.canonical_spawns / e['json_path']
        validate(load(path), spawn_schema, str(path))

    for e in start_idx:
        path = a.canonical_start_points / e['json_path']
        validate(load(path), start_point_schema, str(path))

    for e in fixed_idx:
        path = a.canonical_fixed_npcs / e['json_path']
        validate(load(path), fixed_npc_schema, str(path))

    for profile in ('client', 'server'):
        path = a.canonical_maps / f'{profile}.maps.json'
        validate(load(path), map_schema, str(path))

    loc_index = load(a.canonical_text / 'localization' / 'index.json')
    for entry in loc_index['catalogs']:
        path = a.canonical_text / entry['path']
        validate(load(path), localization_schema, str(path))

    print(json.dumps({
        'status': 'PASS',
        'validator': 'stdlib_jsonschema_subset',
        'canonical_text': len(text_idx),
        'stage_spawns': len(spawn_idx),
        'stage_start_points': len(start_idx),
        'fixed_npc_maps': len(fixed_idx),
        'map_catalogs': 2,
        'localization_catalogs': len(loc_index['catalogs']),
        'definition_families': family_counts,
        'gameplay_configs': gameplay_count,
    }))


if __name__ == '__main__':
    main()
