#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

MAGIC = b'SGRF'
VERSION = 2
HEADER = struct.Struct('<4sHH10I32s')
QUEST = struct.Struct('<6I2i3I')
ENTRY = struct.Struct('<2I')
MIX = struct.Struct('<6Ii2I')

FLAG_REPEATABLE = 1 << 0
FLAG_SUPPORTED = 1 << 1

KIND_PREREQUISITE = 1
KIND_CLASS = 2
KIND_FACTION = 3
KIND_STAGE = 4
KIND_OBJECTIVE = 5
KIND_NPC = 6
KIND_LOCATION = 7
KIND_QUEST_ITEM = 8
KIND_REWARD = 9
KIND_NOTE = 10
KIND_RUNTIME_ID = 11
KIND_RUNTIME_TAG = 12

KIND_MIX_INGREDIENT = 100
KIND_MIX_BONUS = 101
KIND_MIX_RULE = 102
KIND_MIX_SHELTOM = 103


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        v = value.strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _format_objective(value: Any, prefix: str = '') -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, dict):
        target = str(value.get('target', '')).strip()
        count = value.get('count')
        if count is not None and target:
            text = f'{count}x {target}'
        else:
            parts = [f'{k}: {v}' for k, v in value.items() if v not in (None, '', [], {})]
            text = '; '.join(parts)
    else:
        text = str(value).strip()
    if not text:
        return ''
    return f'[{prefix}] {text}' if prefix else text


def _format_reward_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, dict):
        labels = {'classic_and_idhas': 'Classic/Idhas', 'cronus': 'Cronus'}
        out: list[str] = []
        for key, child in value.items():
            label = labels.get(key, key.replace('_', ' ').title())
            for item in _as_strings(child):
                out.append(f'[{label}] {item}')
        return out
    return [str(value)]


def _level_range(quest: dict[str, Any]) -> tuple[int, int]:
    level = quest.get('level')
    if isinstance(level, dict):
        lo = level.get('min')
        hi = level.get('max')
        return (-1 if lo is None else int(lo), -1 if hi is None else int(hi))
    if level is not None:
        value = int(level)
        return value, value
    lo = quest.get('level_min')
    return (-1 if lo is None else int(lo), -1)


def _flatten_quest(category: str, quest: dict[str, Any]) -> dict[str, Any]:
    prerequisites = _as_strings(quest.get('prerequisites'))
    classes = _as_strings(quest.get('classes'))
    factions = _as_strings(quest.get('factions')) + _as_strings(quest.get('faction'))
    stages: list[str] = []
    objectives: list[str] = []
    npcs = _as_strings(quest.get('npc'))
    locations: list[str] = []
    quest_items: list[str] = []
    rewards = _format_reward_values(quest.get('reward'))
    notes = _as_strings(quest.get('notes'))

    for stage in quest.get('stages', []) or []:
        stage_name = str(stage.get('name', '')).strip()
        if stage_name:
            stages.append(stage_name)
        for objective in stage.get('objectives', []) or []:
            text = _format_objective(objective, stage_name)
            if text:
                objectives.append(text)
        npcs += _as_strings(stage.get('npcs'))
        locations += _as_strings(stage.get('locations'))
        quest_items += _as_strings(stage.get('quest_items'))
        for reward in stage.get('rewards', []) or []:
            text = str(reward).strip()
            if text:
                rewards.append(f'[{stage_name}] {text}' if stage_name else text)
        for note in stage.get('notes', []) or []:
            text = str(note).strip()
            if text:
                notes.append(f'[{stage_name}] {text}' if stage_name else text)

    for objective in quest.get('objectives', []) or []:
        text = _format_objective(objective)
        if text:
            objectives.append(text)

    lo, hi = _level_range(quest)
    return {
        'id': str(quest['id']), 'name': str(quest.get('name', quest['id'])),
        'type': str(quest.get('type', 'quest')), 'category': category,
        'source': str(quest.get('source', '')), 'lore': '',
        'level_min': lo, 'level_max': hi, 'repeatable': bool(quest.get('repeatable', False)),
        'prerequisites': _uniq(prerequisites), 'classes': _uniq(classes), 'factions': _uniq(factions),
        'stages': _uniq(stages), 'objectives': _uniq(objectives), 'npcs': _uniq(npcs),
        'locations': _uniq(locations), 'quest_items': _uniq(quest_items),
        'rewards': _uniq(rewards), 'notes': _uniq(notes),
    }


def _format_rule(key: str, value: Any) -> list[str]:
    label = key.replace('_', ' ').strip().capitalize()
    if isinstance(value, bool):
        return [f'{label}: {"sim" if value else "nao"}']
    if isinstance(value, (str, int, float)):
        return [f'{label}: {value}']
    if isinstance(value, list):
        return [f'{label}: ' + ', '.join(str(x) for x in value)]
    if isinstance(value, dict):
        out: list[str] = []
        for child_key, child_value in value.items():
            child_label = child_key.replace('_', ' ').strip()
            if isinstance(child_value, bool):
                child_text = 'sim' if child_value else 'nao'
            elif isinstance(child_value, list):
                child_text = ', '.join(str(x) for x in child_value)
            else:
                child_text = str(child_value)
            out.append(f'{label} / {child_label}: {child_text}')
        return out
    return [f'{label}: {value}']


def _format_bonus(bonus: Any) -> str:
    if isinstance(bonus, str):
        return bonus.strip()
    if not isinstance(bonus, dict):
        return str(bonus).strip()
    raw = str(bonus.get('raw', '')).strip()
    if raw:
        return raw
    label = str(bonus.get('label', bonus.get('stat', 'Bonus'))).strip()
    value = bonus.get('value')
    unit = str(bonus.get('unit', '')).strip()
    suffix = '%' if unit == 'percent' else ''
    return f'{label} +{value}{suffix}' if value is not None else label


def main() -> None:
    ap = argparse.ArgumentParser(description='Compile Summit gameplay reference quest + mix catalog')
    ap.add_argument('canonical', type=Path, help='Content/canonical/gameplay_reference')
    ap.add_argument('output', type=Path)
    args = ap.parse_args()

    root = args.canonical.resolve()
    index = json.loads((root / 'index.json').read_text(encoding='utf-8'))
    quest_doc = json.loads((root / index['quest_catalog']).read_text(encoding='utf-8'))
    binding_doc = json.loads((root / index['quest_runtime_bindings']).read_text(encoding='utf-8'))
    mix_doc = json.loads((root / index['mix_catalog']).read_text(encoding='utf-8'))

    bindings: dict[str, dict[str, Any]] = {str(x['guide_id']): x for x in binding_doc.get('bindings', [])}

    quests: list[dict[str, Any]] = []
    category_map = [('progression_quests', 'progression'), ('daily_quests', 'daily'),
                    ('aline_daily_quests', 'daily_aline'), ('weekly_quests', 'weekly')]
    for key, category in category_map:
        for quest in quest_doc.get(key, []) or []:
            item = _flatten_quest(category, quest)
            binding = bindings.get(item['id'], {})
            item['supported'] = bool(binding.get('supported', False))
            item['runtime_ids'] = [int(x) for x in binding.get('runtime_ids', [])]
            item['runtime_tags'] = [str(x) for x in binding.get('runtime_tags', [])]
            if binding.get('note'):
                item['notes'] = _uniq(item['notes'] + [str(binding['note'])])
            quests.append(item)
    ids = [q['id'] for q in quests]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate quest guide ids')
    quests.sort(key=lambda q: (q['level_min'] < 0, q['level_min'], q['name'].casefold(), q['id']))

    strings = bytearray()
    offsets: dict[bytes, int] = {}
    def intern(value: str) -> int:
        raw = str(value).encode('utf-8')
        if b'\0' in raw:
            raise ValueError('NUL in gameplay reference string')
        if raw not in offsets:
            offsets[raw] = len(strings)
            strings.extend(raw + b'\0')
        return offsets[raw]

    entries: list[tuple[int, int]] = []
    quest_records: list[tuple[int, ...]] = []
    list_fields = [
        ('prerequisites', KIND_PREREQUISITE), ('classes', KIND_CLASS), ('factions', KIND_FACTION),
        ('stages', KIND_STAGE), ('objectives', KIND_OBJECTIVE), ('npcs', KIND_NPC),
        ('locations', KIND_LOCATION), ('quest_items', KIND_QUEST_ITEM), ('rewards', KIND_REWARD),
        ('notes', KIND_NOTE),
    ]
    for quest in quests:
        list_start = len(entries)
        for field, kind in list_fields:
            for value in quest[field]:
                entries.append((kind, intern(value)))
        for runtime_id in quest['runtime_ids']:
            entries.append((KIND_RUNTIME_ID, intern(str(runtime_id))))
        for runtime_tag in quest['runtime_tags']:
            entries.append((KIND_RUNTIME_TAG, intern(runtime_tag)))
        flags = (FLAG_REPEATABLE if quest['repeatable'] else 0) | (FLAG_SUPPORTED if quest['supported'] else 0)
        quest_records.append((intern(quest['id']), intern(quest['name']), intern(quest['type']),
                              intern(quest['category']), intern(quest['source']), intern(quest['lore']),
                              quest['level_min'], quest['level_max'], flags, list_start, len(entries) - list_start))

    mix_records: list[tuple[int, ...]] = []
    meta_start = len(entries)
    for key, value in (mix_doc.get('rules') or {}).items():
        for text in _format_rule(str(key), value):
            entries.append((KIND_MIX_RULE, intern(text)))
    for sheltom in mix_doc.get('sheltoms', []) or []:
        name = str(sheltom.get('name', '')).strip()
        level = sheltom.get('minimum_character_level')
        if name:
            entries.append((KIND_MIX_SHELTOM, intern(f'{name} - nivel minimo {level}' if level is not None else name)))
    source = mix_doc.get('source') or {}
    source_url = str(source.get('url', '')).strip()
    retrieved = str(source.get('retrieved_date', '')).strip()
    mix_records.append((
        intern('__catalog__'), intern('meta'), intern(str(mix_doc.get('title', 'Tabela de Mix'))),
        intern(source_url), intern(retrieved), int((mix_doc.get('summary') or {}).get('total_combinations', 0)),
        -1, meta_start, len(entries) - meta_start,
    ))

    recipes = mix_doc.get('recipes', []) or []
    recipe_ids: set[str] = set()
    for recipe in recipes:
        recipe_id = str(recipe['id'])
        if recipe_id in recipe_ids:
            raise ValueError(f'duplicate mix recipe id: {recipe_id}')
        recipe_ids.add(recipe_id)
        list_start = len(entries)
        for ingredient in recipe.get('ingredients', []) or []:
            name = str(ingredient.get('sheltom', '')).strip()
            qty = int(ingredient.get('quantity', 0))
            min_level = ingredient.get('min_character_level')
            text = f'{qty}x {name}'
            if min_level is not None:
                text += f' (nivel {int(min_level)})'
            entries.append((KIND_MIX_INGREDIENT, intern(text)))
        bonus_texts = [_format_bonus(x) for x in recipe.get('bonuses', []) or []]
        for text in bonus_texts:
            if text:
                entries.append((KIND_MIX_BONUS, intern(text)))
        source_notation = recipe.get('source_notation') or {}
        source_ingredients = str(source_notation.get('ingredients', '')).strip()
        source_bonuses = ' | '.join(str(x) for x in source_notation.get('bonuses', []) or [])
        mix_records.append((
            intern(recipe_id), intern(str(recipe.get('item_type', ''))), intern(str(recipe.get('item_type_label', ''))),
            intern(source_ingredients), intern(source_bonuses), int(recipe.get('total_sheltoms', 0)),
            int(recipe.get('minimum_character_level', -1)), list_start, len(entries) - list_start,
        ))

    quest_offset = HEADER.size
    entry_offset = quest_offset + len(quest_records) * QUEST.size
    mix_offset = entry_offset + len(entries) * ENTRY.size
    string_offset = mix_offset + len(mix_records) * MIX.size
    body = bytearray()
    for record in quest_records: body.extend(QUEST.pack(*record))
    for entry in entries: body.extend(ENTRY.pack(*entry))
    for record in mix_records: body.extend(MIX.pack(*record))
    body.extend(strings)
    digest = hashlib.sha256(body).digest()
    header = HEADER.pack(MAGIC, VERSION, 0,
                         len(quest_records), quest_offset, QUEST.size,
                         len(entries), entry_offset, ENTRY.size,
                         len(mix_records), mix_offset, MIX.size, string_offset,
                         digest)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(header + body)
    report = {
        'format': 'SGRF', 'version': VERSION,
        'quests': len(quest_records), 'supported_quests': sum(1 for q in quests if q['supported']),
        'list_entries': len(entries),
        'quest_categories': {category: sum(1 for q in quests if q['category'] == category) for _, category in category_map},
        'mix_recipes': len(recipes),
        'mix_categories': dict((mix_doc.get('summary') or {}).get('categories', {})),
        'bytes': args.output.stat().st_size,
        'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_suffix(args.output.suffix + '.report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    main()
