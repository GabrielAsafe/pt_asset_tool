from __future__ import annotations

import collections
import pathlib
import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from .source_catalog import SourceTree, iter_source_files, read_source_text, source_rel


PLAYER_CLASSES = (
    'Mechanician', 'Fighter', 'Pikeman', 'Archer',
    'Knight', 'Atalanta', 'Priestess', 'Magician',
    'Assassin', 'Shaman',
)
_CLASS_BY_KEY = {x.casefold(): x for x in PLAYER_CLASSES}
_CLASS_FILE_ALIASES = {
    'mechanician': ('mechanician', 'mechanican', 'mechskill'),
    'fighter': ('fighter',),
    'pikeman': ('pikeman',),
    'archer': ('archer',),
    'knight': ('knight',),
    'atalanta': ('atalanta',),
    'priestess': ('priestess',),
    'magician': ('magician',),
    'assassin': ('assassin',),
    'shaman': ('shaman',),
}
SKILL_ASSET_FOLDER = {'Mechanician': 'Mecha'}

_CLASS_ENUM_ALIASES = {
    'Mechanician': {'MechanicianSkill', 'MechanicanSkill'},
    'Fighter': {'FighterSkill'}, 'Pikeman': {'PikemanSkill'},
    'Archer': {'ArcherSkill'}, 'Knight': {'KnightSkill'},
    'Atalanta': {'AtalantaSkill'}, 'Priestess': {'PriestessSkill'},
    'Magician': {'MagicianSkill'}, 'Assassin': {'AssassinSkill'},
    'Shaman': {'ShamanSkill'},
}

ASSET_EXTENSIONS = (
    'wav', 'ogg', 'mp3', 'mid', 'bgm', 'part', 'lua', 'bmp', 'tga', 'dds', 'png', 'jpg', 'jpeg',
    'smd', 'smb', 'inx', 'ase', 'max', 'spc', 'spm', 'spp', 'txt', 'msg', 'sin', 'fnt', 'fx', 'zif', 'sct', 'pkg', 'zhoon', 'ini'
)
_ASSET_LITERAL_RE = re.compile(
    r'''(?P<q>["'])(?P<path>[^"'\r\n]+\.(?:''' + '|'.join(ASSET_EXTENSIONS) + r'''))(?P=q)''',
    re.IGNORECASE,
)
_SOUND_DEFINE_RE = re.compile(
    r'^\s*#\s*define\s+(?P<symbol>[A-Za-z_][A-Za-z0-9_]*(?:SOUND|SND|WAV|AUDIO)[A-Za-z0-9_]*)\s+(?P<code>0x[0-9A-Fa-f]+|\d+)',
    re.MULTILINE | re.IGNORECASE,
)
_SOUND_PAIR_SYMBOL_RE = re.compile(
    r'''\{\s*["'](?P<path>[^"']+\.wav)["']\s*,\s*(?P<symbol>[A-Za-z_][A-Za-z0-9_]*(?:SOUND|SND|WAV|AUDIO)[A-Za-z0-9_]*)\s*\}''',
    re.IGNORECASE,
)
_SOUND_PAIR_CODE_RE = re.compile(
    r'''\{\s*["'](?P<path>[^"']+\.wav)["']\s*,\s*(?P<code>0x[0-9A-Fa-f]+|\d+)\s*\}''',
    re.IGNORECASE,
)
_SOUND_TABLE_LINE_RE = re.compile(r'(?im)^\s*(?P<path>(?:wav|assets[\\/]+audio)[\\/][^\r\n]+?\.wav)\s+(?P<code>0x[0-9A-Fa-f]+|\d+)\s*(?://.*)?$')
_SKILL_PLAY_SOUND_RE = re.compile(r'\bSkillPlaySound\s*\(\s*(?P<symbol>SKILL_SOUND_[A-Za-z0-9_]+|0x[0-9A-Fa-f]+|\d+)')
_DIRECT_WAV_LITERAL_RE = re.compile(r'''[\"'](?P<path>(?:wav|assets[\\/]+audio)[\\/][^\"'\r\n]+?\.wav)[\"']''', re.IGNORECASE)
_GENERIC_CALL_FIRST_ARG_RE = re.compile(
    r'''(?P<callee>[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.|::)[A-Za-z_][A-Za-z0-9_]*)*)\s*\(\s*(?P<arg>"[^"\r\n]*"|'[^'\r\n]*'|0x[0-9A-Fa-f]+|\d+|[A-Za-z_][A-Za-z0-9_:]*)''',
    re.MULTILINE,
)
_CONTROL_CALL_NAMES = {'if', 'for', 'while', 'switch', 'catch', 'sizeof', 'return'}
_PARTICLE_LOAD_RE = re.compile(r'''\b(?:PARTICLE\s*->\s*Load|LoadParticle|LoadScript)\s*\(\s*["'](?P<path>[^"']+\.part)["']''', re.IGNORECASE)
_EFFECT_TOKEN_RE = re.compile(r'''AssaParticle_[A-Za-z0-9_]+\s*\(\s*["'](?P<token>[^"']+)["']''')
_PARTICLE_START_TOKEN_RE = re.compile(r'''(?:PARTICLE\s*->\s*Start|StartParticle)\s*\(\s*["'](?P<token>[^"']+)["']''', re.IGNORECASE)
_ANIMATION_TYPE_RE = re.compile(r'''\bAnimate\s*\([^;\n]{0,120}?\b(?P<animation>ANIMATIONTYPE_[A-Za-z0-9_]+)''')
_HANDLER_DELEGATE_RE = re.compile(r'''\b(?P<handler>[A-Z][A-Z0-9_]*HANDLER)\s*->''')
_SKILL_CASE_RE = re.compile(
    r'''\bcase\s+(?:(?:ESkillID::)?SKILLID_(?P<skillid>[A-Za-z0-9_]+)|(?P<enum>[A-Za-z]+Skill)::(?P<tiny>[A-Za-z0-9_]+))\s*:'''
)
_SKILL_MENTION_RE = re.compile(
    r'''\b(?:(?:ESkillID::)?SKILLID_(?P<skillid>[A-Za-z0-9_]+)|(?P<enum>[A-Za-z]+Skill)::(?P<tiny>[A-Za-z0-9_]+))\b'''
)
_SWITCH_CASE_BOUNDARY_RE = re.compile(r'(?m)^\s*(?:case\b[^:\r\n]*:|default\s*:)' )
_NAMED_CASE_LABEL_RE = re.compile(r'(?m)^\s*case\s+(?P<label>[^:\r\n]+?)\s*:')
_FUNCTION_DEF_RE = re.compile(
    r'''(?mx)
    ^\s*(?:[A-Za-z_][A-Za-z0-9_:<>*&\s]*?\s+)?
    (?P<qualified>(?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_~][A-Za-z0-9_~]*)
    \s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:->[^\{]+)?\{
    '''
)
_JOB_ROW_RE = re.compile(
    r'''\{\s*["'](?P<name>Mechanician|Fighter|Pikeman|Archer|Knight|Atalanta|Priestess|Magician|Assassine|Assassin|Shaman)[^"']*["']\s*,\s*["'][^"']*["']\s*,\s*(?P<code>(?:JOB_CODE|CLASSFLAG)_[A-Za-z0-9_]+)\s*,\s*(?P<slot>\d+)''',
    re.IGNORECASE,
)
_MAX_JOB_RE = re.compile(r'^\s*#\s*define\s+(MAX_JOBNUM|MAX_JOB_CAPACITY)\s+(\d+)', re.MULTILINE)

_ITEM_FORMAT_RE = re.compile(
    r"(?P<call>(?:wsprintf|sprintf_s|FormatString)\s*\([^;\n]{0,500}?[\"'](?P<template>[^\"']*it%s\.(?:ASE|SMD|bmp))[\"'][^;\n]{0,500}?(?P<fields>DorpItem|LastCategory)[^;\n]{0,500}?)",
    re.IGNORECASE,
)
_FIELD_COMPANION_RE = re.compile(
    r"SetFieldInfoPath\s*\([^;\n]{0,300}?[\"'](?P<ext>spp|spc|spm)[\"']\s*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    source_file: str
    line: int
    evidence_type: str
    value: str
    context: str = ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_asset_path(value: str) -> str:
    value = value.strip().replace('\\', '/')
    while '//' in value:
        value = value.replace('//', '/')
    if value.casefold().startswith('assets/audio/'):
        value = 'wav/' + value[len('assets/audio/'):]
    return value.lstrip('./')


def _line_number(text: str, offset: int) -> int:
    return text.count('\n', 0, offset) + 1


def _parse_int(value: str) -> int:
    return int(value, 16) if value.lower().startswith('0x') else int(value)




def _strip_c_comments(text: str) -> str:
    """Blank C/C++ comments while preserving offsets and quoted strings.

    Source-evidence offsets must remain stable so line attribution from the
    original file is still correct. Newlines are therefore preserved and every
    non-newline comment byte is replaced by a space.
    """
    out = list(text)
    i = 0
    quote: str | None = None
    esc = False
    while i < len(text):
        ch = text[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            continue
        if text.startswith('//', i):
            j = text.find('\n', i)
            if j < 0:
                j = len(text)
            for k in range(i, j):
                out[k] = ' '
            i = j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            end = len(text) if j < 0 else j + 2
            for k in range(i, end):
                if out[k] not in {'\n', '\r'}:
                    out[k] = ' '
            i = end
            continue
        i += 1
    return ''.join(out)


def _catalog_skill_maps(skill_catalog: Iterable[dict[str, Any]] | None):
    by_skill: dict[str, set[str]] = collections.defaultdict(set)
    valid: dict[tuple[str, str], str] = {}
    for row in skill_catalog or ():
        cls = str(row.get('class') or '')
        skill = str(row.get('skill_name') or '')
        if cls not in PLAYER_CLASSES or not skill:
            continue
        by_skill[skill.casefold()].add(cls)
        valid[(cls, skill.casefold())] = skill
    enum_to_class: dict[str, str] = {}
    for cls, aliases in _CLASS_ENUM_ALIASES.items():
        for alias in aliases:
            enum_to_class[alias.casefold()] = cls
    return by_skill, valid, enum_to_class


def _infer_catalog_case(
    match: re.Match[str],
    *,
    file_class: str | None,
    by_skill: dict[str, set[str]],
    valid: dict[tuple[str, str], str],
    enum_to_class: dict[str, str],
) -> tuple[str, str, str] | None:
    raw_skill = str(match.group('skillid') or match.group('tiny') or '')
    if not raw_skill:
        return None
    key = raw_skill.casefold()
    enum = str(match.group('enum') or '')
    if enum:
        cls = enum_to_class.get(enum.casefold())
        canonical = valid.get((cls or '', key))
        if cls and canonical:
            return cls, canonical, 'ENUM_CLASS'
        return None
    if file_class:
        canonical = valid.get((file_class, key))
        if canonical:
            return file_class, canonical, 'FILE_CLASS'
    owners = sorted(by_skill.get(key, ()))
    if len(owners) == 1:
        cls = owners[0]
        canonical = valid.get((cls, key), raw_skill)
        return cls, canonical, 'CATALOG_UNIQUE_SKILLID'
    return None


def _case_block(text: str, match: re.Match[str], *, max_chars: int = 5000) -> str:
    end = min(len(text), match.start() + max_chars)
    nxt = _SWITCH_CASE_BOUNDARY_RE.search(text, match.end())
    if nxt is not None:
        end = min(end, nxt.start())
    return text[match.start():end]


def _case_context_at_offset(block: str, offset: int) -> tuple[str, int]:
    """Return the nearest lexical case label before *offset* in a function block.

    This is diagnostic/context evidence only.  It never authorizes an asset by
    itself; authorization still requires a unique T5 alias or another proven
    runtime binding.  Offsets are preserved because comments are blanked rather
    than removed.
    """
    last = None
    for match in _NAMED_CASE_LABEL_RE.finditer(block, 0, max(0, offset)):
        last = match
    if last is None:
        return '', 0
    label = ' '.join(str(last.group('label') or '').split())
    return label, block[:last.start()].count('\n')


def _brace_block(text: str, open_brace: int, *, max_chars: int = 8_000_000) -> str:
    # FIX22_CORE_CORPUS_AND_T5_ATTRIBUTION: active legacy dispatchers such as
    # SkillSub_legacy_client.inl::PlaySkillAttack exceed the former 50k cap.
    # Keep a finite guard while allowing the complete function body to be scanned.
    """Return one C/C++ brace-delimited block, fail-closed on imbalance."""
    if open_brace < 0 or open_brace >= len(text) or text[open_brace] != '{':
        return ''
    depth = 0
    limit = min(len(text), open_brace + max_chars)
    i = open_brace
    while i < limit:
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
        i += 1
    return ''


def _skill_alias_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def _catalog_aliases(skill_catalog: Iterable[dict[str, Any]] | None) -> dict[str, list[tuple[str, str]]]:
    """Map normalized skill aliases to canonical (class, skill) pairs.

    Alias evidence is intentionally weaker than SKILLID/enum evidence.  It is
    only promoted to a runtime binding when the alias is present in the C/C++
    function identifier itself and the same function body contains an effect
    start or direct .part literal.  Body-only mentions are diagnostic probes.
    """
    out: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for row in skill_catalog or ():
        cls = str(row.get('class') or '')
        skill = str(row.get('skill_name') or '')
        if cls not in PLAYER_CLASSES or not skill:
            continue
        key = _skill_alias_key(skill)
        if key:
            out[key].append((cls, skill))
    return dict(out)


def _handler_class_from_path(rel: str) -> str | None:
    name = pathlib.PurePosixPath(rel).name.casefold()
    for key, aliases in _CLASS_FILE_ALIASES.items():
        if any(alias in name for alias in aliases):
            return _CLASS_BY_KEY[key]
    return None


def _extract_case_blocks(text: str, class_name: str) -> list[tuple[str, int, str]]:
    """Return skill switch blocks from a class-scoped handler.

    EU handlers mix three spellings in the same file: ``SKILLID_X``,
    ``ESkillID::SKILLID_X`` and ``AssassinSkill::X`` / ``ShamanSkill::X``.
    The first 0.14 parser only recognized the tiny-enum spelling, which made
    source coverage look much smaller than it really was.
    """
    wanted_enums = _CLASS_ENUM_ALIASES.get(class_name, {class_name + 'Skill'})
    matches = []
    for m in _SKILL_CASE_RE.finditer(text):
        enum = m.group('enum')
        if enum and enum not in wanted_enums:
            continue
        matches.append(m)
    out: list[tuple[str, int, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.start() + 5000)
        block = text[m.start():end]
        skill = m.group('skillid') or m.group('tiny') or ''
        out.append((skill, _line_number(text, m.start()), block))
    return out


def _runtime_layer_from_path(rel: str) -> str:
    low = '/' + rel.replace('\\', '/').casefold().lstrip('/')
    # Oracle/archive trees are evidence snapshots, not compiled runtime source.
    # Treating their ``server``/``game`` path segments as live runtime created
    # false T5 probes (for example legacy formula functions with no client FX).
    if any(marker in low for marker in ('/legacy_oracle/', '/old_src/', '/history/', '/archive/')):
        return 'SOURCE_REVIEW'
    # FIX21_CURRENT_SOURCE_SCAN_HYGIENE:
    # Shared *_client/_server.inl implementations are active runtime source.
    if (
        '/srcserver/' in low
        or '/server/' in low
        or low.endswith('_server.inl')
        or low.endswith('_server.inc')
    ):
        return 'SERVER_RUNTIME'
    if (
        '/srcgame/' in low
        or '/game/' in low
        or low.endswith('_client.inl')
        or low.endswith('_client.inc')
        or ('/shared/gameplay/' in low and ('_client.' in low or '/client/' in low))
    ):
        return 'CLIENT_RUNTIME'
    return 'SOURCE_REVIEW'


def _class_source_scope(rel: str) -> tuple[str | None, str | None]:
    """Classify class-specific source files for migration coverage.

    Shared headers do not count as runtime implementation. Class names are
    resolved from handler/source filenames for all ten playable classes.
    """
    low = rel.replace('\\', '/').casefold()
    if any(marker in ('/' + low) for marker in ('/legacy_oracle/', '/old_src/', '/history/', '/archive/')):
        return None, None
    name = pathlib.PurePosixPath(low).name
    cls = None
    for key, aliases in _CLASS_FILE_ALIASES.items():
        if any(alias in name for alias in aliases):
            cls = _CLASS_BY_KEY[key]
            break
    if cls is None:
        return None, None
    if 'skillhandler' in name or '/game/game/' in ('/' + low):
        return cls, 'CLIENT_RUNTIME'
    if '/server/' in ('/' + low) or '/srcserver/' in ('/' + low):
        return cls, 'SERVER_RUNTIME'
    return cls, 'CLASS_SOURCE'


def parse_reference_skill_catalog(tree: SourceTree, classes: Iterable[str] = ('Assassin', 'Shaman')) -> list[dict[str, Any]]:
    """Extract skill UI contract rows from reference ``shared/skill.h``.

    The parser follows class/tier comments and does not hardcode skill names.
    It therefore remains useful when the reference source changes.
    """
    wanted = {x.casefold(): x for x in classes}
    candidates = [p for p in iter_source_files(tree.root) if p.name.casefold() == 'skill.h']
    if not candidates:
        return []
    # Prefer the shared header, because game-side headers may contain copies.
    candidates.sort(key=lambda p: (0 if '/shared/' in ('/' + source_rel(tree.root, p).casefold()) else 1, len(p.parts)))
    path = candidates[0]
    text, _ = read_source_text(path)
    rel = source_rel(tree.root, path)
    rows: list[dict[str, Any]] = []
    ordinal_counts: dict[str, int] = {}
    tier_slot_counts: dict[tuple[str,int], int] = {}
    current_class: str | None = None
    tier: int | None = None
    class_header = re.compile(r'^\s*//\s*([A-Za-z]+)\s+Skills\s*-\s*Tier\s*(\d+)', re.IGNORECASE)
    tier_header = re.compile(r'^\s*//\s*Tier\s*(\d+)', re.IGNORECASE)
    entry = re.compile(
        r'''\{\s*"[^"]*"\s*,\s*(SKILLID_[A-Za-z0-9_]+)\s*,\s*"([^"]*)"(?:\s*,\s*"([^"]*)")?\s*\}\s*,?'''
    )
    for lineno, line in enumerate(text.splitlines(), start=1):
        mh = class_header.search(line)
        if mh:
            key = mh.group(1).casefold()
            current_class = wanted.get(key)
            tier = int(mh.group(2)) if current_class else None
            continue
        mt = tier_header.search(line)
        if mt and current_class:
            tier = int(mt.group(1))
            continue
        if line.lstrip().startswith('//') and 'skills' in line.casefold() and current_class:
            # Any new class section ends the current wanted section.
            if not any(x.casefold() in line.casefold() for x in wanted.values()):
                current_class = None
                tier = None
            continue
        if not current_class or tier is None:
            continue
        me = entry.search(line)
        if not me:
            continue
        skill_id, button_base, explicit_tga = me.group(1), me.group(2), me.group(3) or ''
        ordinal_counts[current_class] = ordinal_counts.get(current_class, 0) + 1
        tier_key = (current_class, tier)
        tier_slot_counts[tier_key] = tier_slot_counts.get(tier_key, 0) + 1
        rows.append({
            'class': current_class,
            'tier': tier,
            'tier_slot': tier_slot_counts[tier_key],
            'class_ordinal': ordinal_counts[current_class],
            'skill_id': skill_id,
            'skill_name': skill_id.removeprefix('SKILLID_'),
            'button_base': button_base,
            'asset_class_folder': SKILL_ASSET_FOLDER.get(current_class, current_class),
            'button_normal': f"image/Sinimage/skill/{SKILL_ASSET_FOLDER.get(current_class, current_class)}/Button/{button_base}.bmp" if button_base else '',
            'button_hover': f"image/Sinimage/skill/{SKILL_ASSET_FOLDER.get(current_class, current_class)}/Button/{button_base}_.bmp" if button_base else '',
            'explicit_tga': explicit_tga,
            'source_id': tree.source_id,
            'source_file': rel,
            'source_line': lineno,
        })
    return rows



def _numeric_source_constants(tree: SourceTree) -> dict[str, int]:
    """Collect direct numeric #define / enum constants used by skill registries."""
    out: dict[str, int] = {}
    rx_define = re.compile(
        r'^\s*#\s*define\s+(?P<name>SKILL(?:PLAYID|_PLAY)_[A-Za-z0-9_]+)\s+(?P<value>0x[0-9A-Fa-f]+|\d+)\b',
        re.MULTILINE,
    )
    rx_enum = re.compile(
        r'\b(?P<name>SKILLPLAYID_[A-Za-z0-9_]+)\s*=\s*(?P<value>0x[0-9A-Fa-f]+|\d+)\b'
    )
    for path in iter_source_files(tree.root):
        name = path.name.casefold()
        if name not in {'skill.h', 'character.h'}:
            continue
        try:
            text, _enc = read_source_text(path)
        except OSError:
            continue
        for m in rx_define.finditer(text):
            out[m.group('name')] = _parse_int(m.group('value'))
        for m in rx_enum.finditer(text):
            out[m.group('name')] = _parse_int(m.group('value'))
    out.setdefault('0', 0)
    return out


def parse_skill_motion_registry(tree: SourceTree) -> dict[str, Any]:
    """Parse the runtime table addressed by INX ``SkillCodeList`` bytes.

    Two source families are supported:

    * EU/reference: ``game/game/SkillManager.h`` -> ``saSkillData``.
    * Summit/legacy: ``SkillDataCode.inl`` -> ``SkillDataCode``.

    The returned ``index`` is semantic: it is exactly the byte value stored in
    MotionInfo.SkillCodeList and dereferenced by ``SetMotionFromCode``.
    Commented-out rows are intentionally ignored.  Parsing is constrained to
    the registry initializer itself so later sound tables cannot be mistaken
    for SkillData rows.
    """
    constants = _numeric_source_constants(tree)
    candidates: list[tuple[int, pathlib.Path, str, str]] = []
    for path in iter_source_files(tree.root):
        low = source_rel(tree.root, path).casefold()
        name = path.name.casefold()
        score = 99
        kind = ''
        if name == 'skillmanager.h':
            # Prefer the actual game runtime declaration.
            score = 0 if '/game/game/' in ('/' + low) else 4
            kind = 'EU_SKILLMANAGER_SASKILLDATA'
        elif name == 'skilldatacode.inl':
            # Prefer the actual client runtime table, not duplicated oracle copies.
            score = 1 if '/srcgame/' in ('/' + low) else 5
            kind = 'LEGACY_SKILLDATACODE'
        else:
            continue
        candidates.append((score, path, low, kind))
    if not candidates:
        return {
            'source_id': tree.source_id, 'status': 'NOT_FOUND', 'source_file': '',
            'registry_kind': '', 'entries': [], 'entry_count': 0, 'constants': constants,
            'selector_witnesses': [],
        }
    candidates.sort(key=lambda x: (x[0], len(x[2]), x[2]))
    _score, path, _low, kind = candidates[0]
    text, _enc = read_source_text(path)
    rel = source_rel(tree.root, path)

    if kind == 'EU_SKILLMANAGER_SASKILLDATA':
        start_rx = re.compile(r'\bstatic\s+SkillData\s+saSkillData\s*\[[^\]]*\]\s*=\s*\{')
    else:
        start_rx = re.compile(r'\bSKILL_DATA_CODE\s+SkillDataCode\s*\[[^\]]*\]\s*=\s*\{')
    sm = start_rx.search(text)
    if not sm:
        return {
            'source_id': tree.source_id, 'status': 'REGISTRY_INITIALIZER_NOT_FOUND',
            'source_file': rel, 'registry_kind': kind, 'entries': [], 'entry_count': 0,
            'constants': constants, 'selector_witnesses': [],
        }
    # These legacy tables are flat initializers; the first top-level `};` after
    # the declaration terminates the registry.  Constraining the body is vital
    # in SkillManager.h because saSoundData immediately follows saSkillData.
    tail = text[sm.end():]
    em = re.search(r'^\s*\};', tail, re.MULTILINE)
    if not em:
        return {
            'source_id': tree.source_id, 'status': 'REGISTRY_TERMINATOR_NOT_FOUND',
            'source_file': rel, 'registry_kind': kind, 'entries': [], 'entry_count': 0,
            'constants': constants, 'selector_witnesses': [],
        }
    body_start = sm.end()
    body = tail[:em.start()]
    body_start_line = _line_number(text, body_start)

    # Strip // comments before matching. This matters for Summit because the
    # Assassin/Shaman rows are physically present but commented out.
    entries: list[dict[str, Any]] = []
    current_class = ''
    class_ordinals: dict[str, int] = {}
    # Accept `//Assassin`, `////ASSASSIN`, etc., but a commented-out class
    # heading does not activate a section in the current runtime table because
    # the rows below are comments too and are intentionally ignored.
    class_comment_re = re.compile(r'^\s*//+\s*(?P<class>[A-Za-z]+)\s*$', re.IGNORECASE)
    row_re = re.compile(
        r'\{\s*"(?P<name>[^"]*)"\s*,\s*(?P<play>[A-Za-z_][A-Za-z0-9_]*|0x[0-9A-Fa-f]+|\d+)\s*\}'
    )
    terminator_re = re.compile(r'^\s*\{\s*(?:0|NULL)\s*,\s*(?:0|NULL)\s*\}\s*,?\s*$')
    wanted_classes = dict(_CLASS_BY_KEY)
    for offset, raw in enumerate(body.splitlines()):
        lineno = body_start_line + offset
        # Detect live section comments, but do not let `////ASSASSIN` in the
        # Summit file classify commented-out rows as active: those rows are
        # removed below before matching, so class labels are harmless metadata.
        cm = class_comment_re.match(raw)
        if cm:
            current_class = wanted_classes.get(cm.group('class').casefold(), '')
        code = raw.split('//', 1)[0]
        if terminator_re.match(code):
            break
        m = row_re.search(code)
        if not m:
            continue
        name = m.group('name')
        play_token = m.group('play')
        if play_token.lower().startswith('0x') or play_token.isdigit():
            play_id = _parse_int(play_token)
        else:
            play_id = constants.get(play_token)
        idx = len(entries)
        cls = current_class
        ordinal = 0
        if cls:
            class_ordinals[cls] = class_ordinals.get(cls, 0) + 1
            ordinal = class_ordinals[cls]
        entries.append({
            'index': idx,
            'name': name,
            'play_token': play_token,
            'play_id': play_id,
            'class': cls,
            'class_ordinal': ordinal,
            'source_id': tree.source_id,
            'source_file': rel,
            'source_line': lineno,
        })
        if not name:
            # Summit uses { "", 0 } as its terminator.
            break

    semantic_entries = [x for x in entries if x.get('name')]

    # Find the runtime selector witness. Prefer active source directories and
    # avoid legacy_oracle/archive copies when the real implementation exists.
    selector_rx = re.compile(
        r'SkillCodeList\s*\[[^\]]+\].{0,1000}?SkillDataCode\s*\[\s*bSkill\s*\]\s*\.\s*dwPlaySkillCode',
        re.DOTALL,
    )
    witness_candidates: list[tuple[int, dict[str, Any]]] = []
    for spath in iter_source_files(tree.root):
        sname = spath.name.casefold()
        if sname not in {'character.cpp', 'character.cpp.inl', 'character_legacy_client.inl'}:
            continue
        srel = source_rel(tree.root, spath)
        slow = srel.casefold()
        try:
            stext, _senc = read_source_text(spath)
        except OSError:
            continue
        smatch = selector_rx.search(stext)
        if not smatch:
            continue
        if 'legacy_oracle' in slow or 'old_src' in slow or '/history/' in ('/' + slow):
            score = 50
        elif '/srcgame/' in ('/' + slow) or '/srcserver/' in ('/' + slow):
            score = 0
        elif '/shared/gameplay/' in ('/' + slow):
            score = 1
        else:
            score = 10
        witness_candidates.append((score, {
            'source_id': tree.source_id,
            'source_file': srel,
            'source_line': _line_number(stext, smatch.start()),
            'evidence': 'SETMOTION_SKILLCODELIST_TO_SKILLDATACODE',
        }))
    witness_candidates.sort(key=lambda x: (x[0], x[1]['source_file']))
    selector_witnesses = [witness_candidates[0][1]] if witness_candidates else []

    return {
        'source_id': tree.source_id,
        'status': 'PASS' if semantic_entries else 'EMPTY',
        'source_file': rel,
        'registry_kind': kind,
        'entries': semantic_entries,
        'entry_count': len(semantic_entries),
        'constants': constants,
        'class_counts': dict(collections.Counter(x['class'] for x in semantic_entries if x['class'])),
        'selector_witnesses': selector_witnesses,
    }

def _call_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def _looks_audio_callee(callee: str) -> bool:
    key = _call_key(callee)
    return any(marker in key for marker in ('sound', 'audio', 'wav', 'snd'))


def _looks_effect_callee(callee: str) -> bool:
    key = _call_key(callee)
    return any(marker in key for marker in ('particle', 'effect', 'skillfx', 'assa'))


def _unquote_call_arg(raw: str) -> str:
    raw = str(raw or '').strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1]
    return raw


def _generic_audio_calls_in_block(
    block: str,
    *,
    symbol_to_code: dict[str, int],
    code_to_path: dict[int, str],
    symbol_to_path: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return safely-resolved audio identities plus broader diagnostics.

    Only sound-like callees are inspected.  A generic call becomes runtime
    asset evidence only when its first argument is itself a sound identity we
    can resolve conservatively (known sound symbol, numeric sound code, or WAV
    literal).  Unresolved calls remain diagnostics and never authorize import.
    """
    resolved: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen_resolved: set[tuple[str, int | None, str]] = set()
    seen_diag: set[tuple[str, str]] = set()
    for cm in _GENERIC_CALL_FIRST_ARG_RE.finditer(block):
        callee = str(cm.group('callee') or '')
        if not _looks_audio_callee(callee):
            continue
        raw_arg = str(cm.group('arg') or '').strip()
        diag_key = (callee.casefold(), raw_arg.casefold())
        symbol = ''
        code: int | None = None
        path = ''
        arg = _unquote_call_arg(raw_arg)
        quoted = raw_arg[:1] in {'"', "'"}
        if quoted and arg.casefold().endswith('.wav'):
            path = _norm_asset_path(arg)
        elif re.fullmatch(r'0x[0-9A-Fa-f]+|\d+', arg):
            code = _parse_int(arg)
            path = code_to_path.get(code, '')
        elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:]*', arg):
            candidate = arg.split('::')[-1]
            upper_candidate = candidate.upper()
            if (
                candidate in symbol_to_code
                or candidate in symbol_to_path
                or upper_candidate.startswith(('SKILL_SOUND_', 'SOUND_', 'SND_', 'AUDIO_', 'WAV_'))
            ):
                symbol = candidate
                code = symbol_to_code.get(symbol)
                path = symbol_to_path.get(symbol, '')
                if not path and isinstance(code, int):
                    path = code_to_path.get(code, '')
        is_resolved_identity = bool(path or symbol or isinstance(code, int))
        if diag_key not in seen_diag:
            seen_diag.add(diag_key)
            diagnostics.append({
                'callee': callee,
                'raw_argument': raw_arg,
                'symbol': symbol,
                'code': code,
                'path': path,
                'resolved_identity': is_resolved_identity,
                'call_line_offset': block[:cm.start()].count('\n'),
                'call_char_offset': cm.start(),
                'call_excerpt': ' '.join(str(cm.group(0) or '').split()),
            })
        if not is_resolved_identity:
            continue
        key = (symbol, code, path.casefold())
        if key in seen_resolved:
            continue
        seen_resolved.add(key)
        resolved.append({
            'symbol': symbol,
            'code': code,
            'path': path,
            'evidence': 'GENERIC_AUDIO_CALL',
            'callee': callee,
        })
    return resolved, diagnostics


def _generic_effect_tokens_in_block(block: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Collect quoted effect tokens from effect-like APIs plus diagnostics.

    Direct ``.part`` literals are handled separately by the physical-asset
    scanner.  Here we only promote extensionless quoted strings as effect
    tokens; identifiers/numerics remain diagnostic-only.
    """
    tokens: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    seen_diag: set[tuple[str, str]] = set()
    for cm in _GENERIC_CALL_FIRST_ARG_RE.finditer(block):
        callee = str(cm.group('callee') or '')
        if not _looks_effect_callee(callee):
            continue
        raw_arg = str(cm.group('arg') or '').strip()
        diag_key = (callee.casefold(), raw_arg.casefold())
        arg = _unquote_call_arg(raw_arg)
        quoted = raw_arg[:1] in {'"', "'"}
        token = ''
        if quoted and arg and not pathlib.PurePosixPath(arg.replace('\\', '/')).suffix:
            token = arg
        if diag_key not in seen_diag:
            seen_diag.add(diag_key)
            diagnostics.append({
                'callee': callee,
                'raw_argument': raw_arg,
                'token': token,
                'resolved_token': bool(token),
                'call_line_offset': block[:cm.start()].count('\n'),
                'call_char_offset': cm.start(),
                'call_excerpt': ' '.join(str(cm.group(0) or '').split()),
            })
        if token and token.casefold() not in seen_tokens:
            seen_tokens.add(token.casefold())
            tokens.append(token)
    return tokens, diagnostics


def _sounds_in_block(
    block: str,
    *,
    symbol_to_code: dict[str, int],
    code_to_path: dict[int, str],
    symbol_to_path: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract proven audio calls/literals plus non-authorizing diagnostics."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for sm in _SKILL_PLAY_SOUND_RE.finditer(block):
        raw = sm.group('symbol')
        if raw.startswith('SKILL_SOUND_'):
            symbol = raw
            code = symbol_to_code.get(symbol)
        else:
            symbol = ''
            code = _parse_int(raw)
        path = symbol_to_path.get(symbol, '') if symbol else code_to_path.get(code or -1, '')
        key = (symbol, code, path.casefold())
        if key not in seen:
            seen.add(key)
            out.append({'symbol': symbol, 'code': code, 'path': path, 'evidence': 'SKILL_PLAY_SOUND', 'callee': 'SkillPlaySound'})
    for wm in _DIRECT_WAV_LITERAL_RE.finditer(block):
        path = _norm_asset_path(wm.group('path'))
        key = ('', None, path.casefold())
        if key not in seen:
            seen.add(key)
            out.append({'symbol': '', 'code': None, 'path': path, 'evidence': 'DIRECT_WAV_LITERAL', 'callee': ''})
    generic, diagnostics = _generic_audio_calls_in_block(
        block,
        symbol_to_code=symbol_to_code,
        code_to_path=code_to_path,
        symbol_to_path=symbol_to_path,
    )
    for row in generic:
        key = (str(row.get('symbol') or ''), row.get('code'), str(row.get('path') or '').casefold())
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out, diagnostics


def scan_source_evidence(
    tree: SourceTree,
    skill_catalog: Iterable[dict[str, Any]] | None = None,
    skill_handler_aliases: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    sound_symbol_to_code: dict[str, int] = {}
    sound_code_to_path: dict[int, str] = {}
    sound_symbol_to_path: dict[str, str] = {}
    literal_refs: list[EvidenceRef] = []
    sound_calls: list[dict[str, Any]] = []
    skill_cases: list[dict[str, Any]] = []
    class_parts: dict[str, list[EvidenceRef]] = {x: [] for x in PLAYER_CLASSES}
    effect_tokens: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    max_jobs: dict[str, int] = {}
    format_relations: list[dict[str, Any]] = []
    class_skill_mentions: list[dict[str, Any]] = []
    skill_alias_probes: list[dict[str, Any]] = []
    runtime_asset_call_probes: list[dict[str, Any]] = []
    runtime_audio_call_probes: list[dict[str, Any]] = []
    runtime_effect_call_probes: list[dict[str, Any]] = []
    files_scanned = 0
    source_files: list[str] = []
    catalog_by_skill, catalog_valid, catalog_enum_to_class = _catalog_skill_maps(skill_catalog)
    catalog_alias_map = _catalog_aliases(skill_catalog)
    handler_alias_map = {
        _skill_alias_key(k): (str(v[0]), str(v[1]))
        for k, v in (skill_handler_aliases or {}).items()
        if k and isinstance(v, tuple) and len(v) == 2
    }

    texts: list[tuple[pathlib.Path, str, str]] = []
    for path in iter_source_files(tree.root):
        files_scanned += 1
        try:
            text, _enc = read_source_text(path)
        except OSError:
            continue
        rel = source_rel(tree.root, path)
        source_files.append(rel)
        texts.append((path, rel, text))

        scope_class, scope_layer = _class_source_scope(rel)
        if scope_class:
            seen_mentions: set[str] = set()
            wanted_enums = _CLASS_ENUM_ALIASES.get(scope_class, {scope_class + 'Skill'})
            for mm in _SKILL_MENTION_RE.finditer(text):
                enum = mm.group('enum')
                if enum and enum not in wanted_enums:
                    continue
                skill = mm.group('skillid') or mm.group('tiny') or ''
                if not skill or skill in seen_mentions:
                    continue
                seen_mentions.add(skill)
                class_skill_mentions.append({
                    'class': scope_class,
                    'skill_name': skill,
                    'layer': scope_layer,
                    'source_id': tree.source_id,
                    'source_file': rel,
                    'source_line': _line_number(text, mm.start()),
                })

        for m in _SOUND_DEFINE_RE.finditer(text):
            sound_symbol_to_code[m.group('symbol')] = _parse_int(m.group('code'))
        for m in _MAX_JOB_RE.finditer(text):
            max_jobs[m.group(1)] = int(m.group(2))
        for m in _JOB_ROW_RE.finditer(text):
            jobs.append({
                'name': m.group('name'),
                'job_code': m.group('code'),
                'slot': int(m.group('slot')),
                'source_file': rel,
                'source_line': _line_number(text, m.start()),
            })
        for m in _ITEM_FORMAT_RE.finditer(text):
            template = _norm_asset_path(m.group('template'))
            relation = 'ITEM_DORPITEM_MODEL_TEMPLATE' if template.casefold().endswith(('.ase', '.smd')) else 'ITEM_ICON_TEMPLATE'
            format_relations.append({
                'relation': relation,
                'template': template,
                'field': m.group('fields'),
                'source_id': tree.source_id,
                'source_file': rel,
                'source_line': _line_number(text, m.start()),
            })
        for m in _FIELD_COMPANION_RE.finditer(text):
            format_relations.append({
                'relation': 'FIELD_SERVER_COMPANION',
                'extension': '.' + m.group('ext').casefold(),
                'source_id': tree.source_id,
                'source_file': rel,
                'source_line': _line_number(text, m.start()),
            })
        for m in _ASSET_LITERAL_RE.finditer(text):
            literal_refs.append(EvidenceRef(
                tree.source_id, rel, _line_number(text, m.start()), 'ASSET_LITERAL',
                _norm_asset_path(m.group('path')),
            ))
        for m in _SOUND_PAIR_SYMBOL_RE.finditer(text):
            sound_symbol_to_path[m.group('symbol')] = _norm_asset_path(m.group('path'))
        for m in _SOUND_PAIR_CODE_RE.finditer(text):
            sound_code_to_path[_parse_int(m.group('code'))] = _norm_asset_path(m.group('path'))
        for m in _SOUND_TABLE_LINE_RE.finditer(text):
            sound_code_to_path[_parse_int(m.group('code'))] = _norm_asset_path(m.group('path'))

    # Resolve symbol->numeric->path after all headers/tables have been scanned.
    for symbol, code in sound_symbol_to_code.items():
        if symbol not in sound_symbol_to_path and code in sound_code_to_path:
            sound_symbol_to_path[symbol] = sound_code_to_path[code]

    for _path, rel, text in texts:
        handler_class = _handler_class_from_path(rel)
        for m in _SKILL_PLAY_SOUND_RE.finditer(text):
            raw = m.group('symbol')
            if raw.startswith('SKILL_SOUND_'):
                symbol = raw
                code = sound_symbol_to_code.get(symbol)
            else:
                symbol = ''
                code = _parse_int(raw)
            path = sound_symbol_to_path.get(symbol, '') if symbol else sound_code_to_path.get(code or -1, '')
            sound_calls.append({
                'class': handler_class,
                'symbol': symbol,
                'code': code,
                'path': path,
                'source_id': tree.source_id,
                'source_file': rel,
                'source_line': _line_number(text, m.start()),
            })

        if handler_class:
            for m in _PARTICLE_LOAD_RE.finditer(text):
                class_parts[handler_class].append(EvidenceRef(
                    tree.source_id, rel, _line_number(text, m.start()), 'CLASS_PARTICLE_LITERAL',
                    _norm_asset_path(m.group('path')), handler_class,
                ))
            for skill_name, case_line, block in _extract_case_blocks(text, handler_class):
                sounds, _audio_diags = _sounds_in_block(
                    block, symbol_to_code=sound_symbol_to_code, code_to_path=sound_code_to_path,
                    symbol_to_path=sound_symbol_to_path,
                )
                tokens: list[str] = []
                for tm in _EFFECT_TOKEN_RE.finditer(block):
                    tokens.append(tm.group('token'))
                for tm in _PARTICLE_START_TOKEN_RE.finditer(block):
                    tokens.append(tm.group('token'))
                generic_tokens, _effect_diags = _generic_effect_tokens_in_block(block)
                tokens.extend(generic_tokens)
                part_literals = sorted({
                    _norm_asset_path(pm.group('path'))
                    for pm in _ASSET_LITERAL_RE.finditer(block)
                    if str(pm.group('path') or '').casefold().endswith('.part')
                }, key=str.casefold)
                animations = sorted({m.group('animation') for m in _ANIMATION_TYPE_RE.finditer(block)}, key=str.casefold)
                infrastructure_handlers = {
                    'SKILLMANAGERHANDLER', 'TIMERSKILLHANDLER', 'SETTINGSHANDLER',
                    'DAMAGEHANDLER', 'CHARACTERGAME', 'ITEMHANDLER', 'QUESTGAME',
                }
                delegates = sorted({
                    m.group('handler') for m in _HANDLER_DELEGATE_RE.finditer(block)
                    if m.group('handler') not in infrastructure_handlers
                }, key=str.casefold)
                skill_cases.append({
                    'class': handler_class,
                    'skill_name': skill_name,
                    'sounds': sounds,
                    'effect_tokens': sorted(set(tokens), key=str.casefold),
                    'particle_literals': part_literals,
                    'animations': animations,
                    'delegates': delegates,
                    'source_id': tree.source_id,
                    'source_file': rel,
                    'source_line': case_line,
                    'layer': _runtime_layer_from_path(rel),
                    'scope_basis': 'FILE_CLASS',
                })
                for token in tokens:
                    effect_tokens.append({
                        'class': handler_class,
                        'skill_name': skill_name,
                        'token': token,
                        'source_file': rel,
                        'source_line': case_line,
                    })

    # Tier-5 and other legacy skill dispatch often lives in shared source files
    # whose filename does not identify a player class. When the reference skill
    # catalog is supplied, infer only switch cases that map unambiguously to one
    # catalog skill. This preserves the fail-closed rule: ambiguous SKILLID names
    # are ignored, while enum-qualified cases remain directly attributable.
    if catalog_valid:
        seen_cases = {
            (str(x.get('class')), str(x.get('skill_name')).casefold(), str(x.get('source_file')), int(x.get('source_line') or 0))
            for x in skill_cases
        }
        seen_mentions = {
            (str(x.get('class')), str(x.get('skill_name')).casefold(), str(x.get('layer')), str(x.get('source_file')), int(x.get('source_line') or 0))
            for x in class_skill_mentions
        }
        for _path, rel, original_text in texts:
            code = _strip_c_comments(original_text)
            file_class, file_layer = _class_source_scope(rel)
            runtime_layer = file_layer or _runtime_layer_from_path(rel)
            for m in _SKILL_CASE_RE.finditer(code):
                inferred = _infer_catalog_case(
                    m, file_class=file_class, by_skill=catalog_by_skill,
                    valid=catalog_valid, enum_to_class=catalog_enum_to_class,
                )
                if inferred is None:
                    continue
                cls, skill_name, basis = inferred
                line = _line_number(original_text, m.start())
                case_key = (cls, skill_name.casefold(), rel, line)
                block = _case_block(code, m)
                sounds, _audio_diags = _sounds_in_block(
                    block, symbol_to_code=sound_symbol_to_code, code_to_path=sound_code_to_path,
                    symbol_to_path=sound_symbol_to_path,
                )
                tokens: list[str] = []
                for tm in _EFFECT_TOKEN_RE.finditer(block):
                    tokens.append(tm.group('token'))
                for tm in _PARTICLE_START_TOKEN_RE.finditer(block):
                    tokens.append(tm.group('token'))
                generic_tokens, _effect_diags = _generic_effect_tokens_in_block(block)
                tokens.extend(generic_tokens)
                part_literals = sorted({
                    _norm_asset_path(pm.group('path'))
                    for pm in _ASSET_LITERAL_RE.finditer(block)
                    if str(pm.group('path') or '').casefold().endswith('.part')
                }, key=str.casefold)
                animations = sorted({x.group('animation') for x in _ANIMATION_TYPE_RE.finditer(block)}, key=str.casefold)
                infrastructure_handlers = {
                    'SKILLMANAGERHANDLER', 'TIMERSKILLHANDLER', 'SETTINGSHANDLER',
                    'DAMAGEHANDLER', 'CHARACTERGAME', 'ITEMHANDLER', 'QUESTGAME',
                }
                delegates = sorted({
                    x.group('handler') for x in _HANDLER_DELEGATE_RE.finditer(block)
                    if x.group('handler') not in infrastructure_handlers
                }, key=str.casefold)
                if case_key not in seen_cases:
                    skill_cases.append({
                        'class': cls, 'skill_name': skill_name, 'sounds': sounds,
                        'effect_tokens': sorted(set(tokens), key=str.casefold),
                        'particle_literals': part_literals,
                        'animations': animations, 'delegates': delegates,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': line,
                        'scope_basis': basis, 'layer': runtime_layer,
                    })
                    seen_cases.add(case_key)
                    for token in sorted(set(tokens), key=str.casefold):
                        effect_tokens.append({
                            'class': cls, 'skill_name': skill_name, 'token': token,
                            'source_file': rel, 'source_line': line, 'scope_basis': basis,
                        })
                layer = runtime_layer
                mention_key = (cls, skill_name.casefold(), layer, rel, line)
                if mention_key not in seen_mentions:
                    class_skill_mentions.append({
                        'class': cls, 'skill_name': skill_name, 'layer': layer,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': line,
                        'scope_basis': basis,
                    })
                    seen_mentions.add(mention_key)

    # Legacy Summit trees may not contain modern SKILLID switch dispatch at all.
    # Recover a narrow, structural binding from runtime C/C++ function identifiers:
    # the canonical skill alias must occur in the function/method identity itself,
    # and effect evidence must live inside that exact brace-delimited function body.
    # This is stronger than arbitrary text proximity and remains fail-closed for
    # body-only mentions, comments and donor/reference names.
    if catalog_valid and catalog_alias_map:
        seen_case_keys = {
            (str(x.get('class')), str(x.get('skill_name')).casefold(), str(x.get('source_file')), int(x.get('source_line') or 0))
            for x in skill_cases
        }
        for _path, rel, original_text in texts:
            layer = _runtime_layer_from_path(rel)
            if layer not in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}:
                continue
            code = _strip_c_comments(original_text)
            file_class, _file_layer = _class_source_scope(rel)
            for fm in _FUNCTION_DEF_RE.finditer(code):
                qualified = str(fm.group('qualified') or '')
                if not qualified:
                    continue
                pieces = qualified.split('::')
                if pieces[-1].casefold() in _CONTROL_CALL_NAMES:
                    continue
                method_key = _skill_alias_key(pieces[-1])
                owner_key = _skill_alias_key(pieces[-2]) if len(pieces) >= 2 else ''
                owner_core = owner_key
                if owner_core.startswith('c') and len(owner_core) > 1:
                    owner_core = owner_core[1:]
                if owner_core.endswith('handler'):
                    owner_core = owner_core[:-7]
                open_brace = fm.end() - 1
                body = _brace_block(code, open_brace)
                if not body:
                    continue
                sounds, audio_diags = _sounds_in_block(
                    body, symbol_to_code=sound_symbol_to_code, code_to_path=sound_code_to_path,
                    symbol_to_path=sound_symbol_to_path,
                )
                generic_tokens, effect_diags = _generic_effect_tokens_in_block(body)
                tokens = sorted(
                    {m.group('token') for m in _EFFECT_TOKEN_RE.finditer(body)}
                    | {m.group('token') for m in _PARTICLE_START_TOKEN_RE.finditer(body)}
                    | set(generic_tokens),
                    key=str.casefold,
                )
                preload_part_literals = sorted({
                    _norm_asset_path(m.group('path'))
                    for m in _PARTICLE_LOAD_RE.finditer(body)
                    if str(m.group('path') or '').casefold().endswith('.part')
                }, key=str.casefold)
                preload_part_keys = {x.casefold() for x in preload_part_literals}
                part_literals = sorted({
                    _norm_asset_path(m.group('path'))
                    for m in _ASSET_LITERAL_RE.finditer(body)
                    if str(m.group('path') or '').casefold().endswith('.part')
                    and _norm_asset_path(m.group('path')).casefold() not in preload_part_keys
                }, key=str.casefold)
                animations = sorted({m.group('animation') for m in _ANIMATION_TYPE_RE.finditer(body)}, key=str.casefold)
                infrastructure_handlers = {
                    'SKILLMANAGERHANDLER', 'TIMERSKILLHANDLER', 'SETTINGSHANDLER',
                    'DAMAGEHANDLER', 'CHARACTERGAME', 'ITEMHANDLER', 'QUESTGAME',
                    'PARTYHANDLER', 'SOUNDHANDLER',
                }
                delegates = sorted({
                    m.group('handler') for m in _HANDLER_DELEGATE_RE.finditer(body)
                    if m.group('handler') not in infrastructure_handlers
                }, key=str.casefold)
                layer = _runtime_layer_from_path(rel)
                function_line = _line_number(original_text, fm.start('qualified'))
                block_line = _line_number(original_text, open_brace)
                for diag in audio_diags:
                    diag = dict(diag)
                    line_offset = int(diag.pop('call_line_offset', 0) or 0)
                    char_offset = int(diag.pop('call_char_offset', 0) or 0)
                    case_label, case_line_offset = _case_context_at_offset(body, char_offset)
                    runtime_audio_call_probes.append({
                        'source_id': tree.source_id, 'source_file': rel,
                        'source_line': block_line + line_offset,
                        'function_source_line': function_line,
                        'case_label': case_label,
                        'case_source_line': (block_line + case_line_offset) if case_label else 0,
                        'layer': layer, 'function': qualified, **diag,
                    })
                for diag in effect_diags:
                    diag = dict(diag)
                    line_offset = int(diag.pop('call_line_offset', 0) or 0)
                    char_offset = int(diag.pop('call_char_offset', 0) or 0)
                    case_label, case_line_offset = _case_context_at_offset(body, char_offset)
                    runtime_effect_call_probes.append({
                        'source_id': tree.source_id, 'source_file': rel,
                        'source_line': block_line + line_offset,
                        'function_source_line': function_line,
                        'case_label': case_label,
                        'case_source_line': (block_line + case_line_offset) if case_label else 0,
                        'layer': layer, 'function': qualified, **diag,
                    })
                if tokens or part_literals or preload_part_literals or sounds:
                    runtime_asset_call_probes.append({
                        'source_id': tree.source_id,
                        'source_file': rel,
                        'source_line': _line_number(original_text, fm.start()),
                        'layer': layer,
                        'function': qualified,
                        'effect_tokens': tokens,
                        'particle_literals': part_literals,
                        'particle_preload_literals': preload_part_literals,
                        'sounds': sounds,
                    })
                # Legacy client dispatch often routes many skills through one generic
                # function (for example RecvProcessSkill).  When a switch case
                # label itself contains one unique canonical skill alias, bind
                # only the assets inside that lexical case segment.  This is
                # stronger than whole-function proximity and catches labels such
                # as SKILL_PLAY_RISING_SLASH without requiring modern SKILLID_*
                # spelling.  Modern SKILLID/enum cases are handled by the parser
                # above and are deliberately skipped here to avoid duplicates.
                named_cases = list(_NAMED_CASE_LABEL_RE.finditer(body)) if layer == 'CLIENT_RUNTIME' else []
                for case_index, cm in enumerate(named_cases):
                    case_label = str(cm.group('label') or '')
                    if _SKILL_MENTION_RE.search(case_label):
                        continue
                    label_key = _skill_alias_key(case_label)
                    case_owners: set[tuple[str, str]] = set()
                    for alias_key, owners in catalog_alias_map.items():
                        if len(alias_key) >= 6 and alias_key in label_key:
                            case_owners.update(owners)
                    if len(case_owners) != 1:
                        continue
                    cls, skill_name = next(iter(case_owners))
                    if file_class and file_class != cls:
                        continue
                    case_end = named_cases[case_index + 1].start() if case_index + 1 < len(named_cases) else len(body)
                    case_body = body[cm.start():case_end]
                    case_sounds, _case_audio_diags = _sounds_in_block(
                        case_body, symbol_to_code=sound_symbol_to_code, code_to_path=sound_code_to_path,
                        symbol_to_path=sound_symbol_to_path,
                    )
                    case_generic_tokens, _case_effect_diags = _generic_effect_tokens_in_block(case_body)
                    case_tokens = sorted(
                        {m.group('token') for m in _EFFECT_TOKEN_RE.finditer(case_body)}
                        | {m.group('token') for m in _PARTICLE_START_TOKEN_RE.finditer(case_body)}
                        | set(case_generic_tokens),
                        key=str.casefold,
                    )
                    case_preloads = sorted({
                        _norm_asset_path(m.group('path'))
                        for m in _PARTICLE_LOAD_RE.finditer(case_body)
                        if str(m.group('path') or '').casefold().endswith('.part')
                    }, key=str.casefold)
                    case_preload_keys = {x.casefold() for x in case_preloads}
                    case_parts = sorted({
                        _norm_asset_path(m.group('path'))
                        for m in _ASSET_LITERAL_RE.finditer(case_body)
                        if str(m.group('path') or '').casefold().endswith('.part')
                        and _norm_asset_path(m.group('path')).casefold() not in case_preload_keys
                    }, key=str.casefold)
                    if not (case_sounds or case_tokens or case_parts):
                        continue
                    case_line = block_line + body[:cm.start()].count('\n')
                    case_key = (cls, skill_name.casefold(), rel, case_line)
                    if case_key in seen_case_keys:
                        continue
                    case_animations = sorted({m.group('animation') for m in _ANIMATION_TYPE_RE.finditer(case_body)}, key=str.casefold)
                    case_delegates = sorted({
                        m.group('handler') for m in _HANDLER_DELEGATE_RE.finditer(case_body)
                        if m.group('handler') not in infrastructure_handlers
                    }, key=str.casefold)
                    skill_cases.append({
                        'class': cls, 'skill_name': skill_name, 'sounds': case_sounds,
                        'effect_tokens': case_tokens, 'particle_literals': case_parts,
                        'animations': case_animations, 'delegates': case_delegates,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': case_line,
                        'scope_basis': 'RUNTIME_CASE_SKILL_ALIAS', 'layer': layer,
                        'function': qualified, 'case_label': ' '.join(case_label.split()),
                    })
                    seen_case_keys.add(case_key)
                    class_skill_mentions.append({
                        'class': cls, 'skill_name': skill_name, 'layer': layer,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': case_line,
                        'scope_basis': 'RUNTIME_CASE_SKILL_ALIAS',
                    })
                    for token in case_tokens:
                        effect_tokens.append({
                            'class': cls, 'skill_name': skill_name, 'token': token,
                            'source_file': rel, 'source_line': case_line,
                            'scope_basis': 'RUNTIME_CASE_SKILL_ALIAS',
                        })

                matches: list[tuple[str, str, str]] = []
                owner_handler_key = owner_key[1:] if owner_key.startswith('c') and len(owner_key) > 1 else owner_key
                mapped = handler_alias_map.get(owner_handler_key)
                if mapped is not None:
                    matches.append((mapped[0], mapped[1], 'REFERENCE_HANDLER_ALIAS_CURRENT_BODY'))
                for alias_key, owners in catalog_alias_map.items():
                    if len(owners) != 1:
                        continue
                    cls, skill_name = owners[0]
                    strong_identity = (
                        owner_core == alias_key
                        or method_key == alias_key
                        or (len(alias_key) >= 6 and alias_key in method_key)
                        or (file_class == cls and alias_key in method_key)
                    )
                    if strong_identity:
                        matches.append((cls, skill_name, 'RUNTIME_FUNCTION_SKILL_ALIAS'))
                dedup_matches: list[tuple[str, str, str]] = []
                seen_match = set()
                for cls, skill_name, basis in matches:
                    key = (cls, skill_name.casefold())
                    if key in seen_match:
                        continue
                    seen_match.add(key)
                    dedup_matches.append((cls, skill_name, basis))
                for cls, skill_name, basis in dedup_matches:
                    line = _line_number(original_text, fm.start())
                    probe = {
                        'class': cls, 'skill_name': skill_name, 'source_id': tree.source_id,
                        'source_file': rel, 'source_line': line, 'layer': layer,
                        'function': qualified, 'scope_basis': basis,
                        'effect_tokens': tokens, 'particle_literals': part_literals, 'sounds': sounds,
                        'has_runtime_effect_evidence': bool(tokens or part_literals),
                        'has_runtime_audio_evidence': bool(sounds),
                    }
                    skill_alias_probes.append(probe)
                    if not (tokens or part_literals or sounds):
                        continue
                    case_key = (cls, skill_name.casefold(), rel, line)
                    if case_key in seen_case_keys:
                        continue
                    skill_cases.append({
                        'class': cls, 'skill_name': skill_name, 'sounds': sounds,
                        'effect_tokens': tokens, 'particle_literals': part_literals,
                        'animations': animations, 'delegates': delegates,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': line,
                        'scope_basis': basis, 'layer': layer,
                    })
                    seen_case_keys.add(case_key)
                    class_skill_mentions.append({
                        'class': cls, 'skill_name': skill_name, 'layer': layer,
                        'source_id': tree.source_id, 'source_file': rel, 'source_line': line,
                        'scope_basis': basis,
                    })
                    for token in tokens:
                        effect_tokens.append({
                            'class': cls, 'skill_name': skill_name, 'token': token,
                            'source_file': rel, 'source_line': line,
                            'scope_basis': basis,
                        })

    return {
        'source': tree.to_dict(),
        'source_files_scanned': files_scanned,
        'source_files': source_files,
        'sound_symbol_to_code': {k: v for k, v in sorted(sound_symbol_to_code.items())},
        'sound_code_to_path': {f'0x{k:04X}': v for k, v in sorted(sound_code_to_path.items())},
        'sound_symbol_to_path': {k: v for k, v in sorted(sound_symbol_to_path.items())},
        'literal_refs': [x.to_dict() for x in literal_refs],
        'sound_calls': sound_calls,
        'skill_cases': skill_cases,
        'class_parts': {k: [x.to_dict() for x in v] for k, v in class_parts.items()},
        'effect_tokens': effect_tokens,
        'jobs': jobs,
        'max_jobs': max_jobs,
        'format_relations': format_relations,
        'class_skill_mentions': class_skill_mentions,
        'skill_alias_probes': skill_alias_probes,
        'runtime_asset_call_probes': runtime_asset_call_probes,
        'runtime_audio_call_probes': runtime_audio_call_probes,
        'runtime_effect_call_probes': runtime_effect_call_probes,
    }
