from __future__ import annotations

import collections
import csv
import pathlib
import re
from typing import Any, Callable, Iterable

import pt_inx_motion_core_v2 as inxcore

from .motion_core import verified_inx_link_target
from .source_catalog import SourceTree, iter_source_files, read_source_text, source_rel


FORMAT = 'PT_ASSET_PLAYER_CLASS_MOTION_CONTRACT_V1'

_CLASS_LITERAL_RE = re.compile(
    r'''CHARACTERCLASS_(?P<class>Mechanician|Fighter|Pikeman|Archer|Knight|Atalanta|Priestess|Magician|Assassin|Shaman)[^\r\n"']{0,240}["'](?P<path>char[\\/][^"'\r\n]+\.(?:ini|inx))["']''',
    re.IGNORECASE,
)
_HEAD_BLOCK_RE = re.compile(
    r'''static\s+HeadModelStruct\s+sa(?P<class>Mechanician|Fighter|Pikeman|Archer|Knight|Atalanta|Priestess|Magician|Assassin|Shaman)HeadModel\s*\[\s*\]\s*\{(?P<body>.*?)\n\s*\};''',
    re.IGNORECASE | re.DOTALL,
)
_QUOTED_HEAD_PATH_RE = re.compile(r'''["'](?P<path>char[\\/][^"'\r\n]+\.(?:inf|inx))["']''', re.IGNORECASE)

_BODY_PATTERNS = {
    'Mechanician': (re.compile(r'^a\d+$', re.IGNORECASE), re.compile(r'^ca\d+$', re.IGNORECASE)),
    'Fighter': (re.compile(r'^b\d+$', re.IGNORECASE), re.compile(r'^cb\d+$', re.IGNORECASE)),
    'Pikeman': (re.compile(r'^c\d+$', re.IGNORECASE), re.compile(r'^cc\d+$', re.IGNORECASE)),
    'Archer': (re.compile(r'^d\d+$', re.IGNORECASE), re.compile(r'^cd\d+$', re.IGNORECASE)),
    'Knight': (re.compile(r'^ma\d+$', re.IGNORECASE), re.compile(r'^cma\d+$', re.IGNORECASE)),
    'Atalanta': (re.compile(r'^mb\d+$', re.IGNORECASE), re.compile(r'^cmb\d+$', re.IGNORECASE)),
    'Priestess': (re.compile(r'^mc\d+$', re.IGNORECASE), re.compile(r'^cmc\d+$', re.IGNORECASE)),
    'Magician': (re.compile(r'^md\d+$', re.IGNORECASE), re.compile(r'^cmd\d+$', re.IGNORECASE)),
    'Assassin': (re.compile(r'^e\d+$', re.IGNORECASE), re.compile(r'^ce\d+$', re.IGNORECASE)),
    'Shaman': (re.compile(r'^me\d+$', re.IGNORECASE), re.compile(r'^cme\d+$', re.IGNORECASE)),
}


def _norm(value: str) -> str:
    value = str(value or '').strip().replace('\\', '/')
    while '//' in value:
        value = value.replace('//', '/')
    return value.lstrip('./')


def _logical_inx(value: str) -> str:
    p = pathlib.PurePosixPath(_norm(value))
    if p.suffix.casefold() in {'.ini', '.inf'}:
        return p.with_suffix('.inx').as_posix()
    return p.as_posix()


def _line_number(text: str, offset: int) -> int:
    return text.count('\n', 0, offset) + 1


def _config_kind(class_name: str, source_literal: str) -> str:
    p = pathlib.PurePosixPath(_norm(source_literal))
    if p.suffix.casefold() == '.inf':
        return 'HEAD_CONFIG'
    stem = p.stem
    base_rx, costume_rx = _BODY_PATTERNS[class_name]
    if base_rx.fullmatch(stem):
        return 'BODY_BASE_CONFIG'
    if costume_rx.fullmatch(stem):
        return 'BODY_COSTUME_CONFIG'
    return 'CLASS_CONFIG'


def parse_reference_class_configs(tree: SourceTree, classes: Iterable[str] = ('Mechanician','Fighter','Pikeman','Archer','Knight','Atalanta','Priestess','Magician','Assassin','Shaman')) -> list[dict[str, Any]]:
    """Extract source-proven class config paths for playable classes.

    ``shared/character.h`` associates class IDs with logical ``.ini`` body
    configs, while ``itemhandlerstruct.h`` contains the class-specific head
    ``.inf`` arrays.  The shipped runtime stores the physical config payloads
    as ``.inx``; the logical->physical extension mapping is the same contract
    already used by the server bundle census.
    """
    wanted = {str(x).casefold(): str(x) for x in classes}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int]] = set()

    for path in iter_source_files(tree.root):
        try:
            text, _enc = read_source_text(path)
        except OSError:
            continue
        rel = source_rel(tree.root, path)

        for m in _CLASS_LITERAL_RE.finditer(text):
            # Source literals in commented-out migration rows are historical
            # evidence, not active class configuration.  Keep the active
            # reference contract fail-closed by skipping line comments.
            line_start = text.rfind('\n', 0, m.start()) + 1
            if '//' in text[line_start:m.start()]:
                continue
            cls = wanted.get(m.group('class').casefold())
            if not cls:
                continue
            literal = _norm(m.group('path'))
            logical = _logical_inx(literal)
            row = {
                'class': cls,
                'kind': _config_kind(cls, literal),
                'source_literal': literal,
                'logical_inx': logical,
                'source_id': tree.source_id,
                'source_file': rel,
                'source_line': _line_number(text, m.start()),
                'evidence': 'REFERENCE_CLASS_CONFIG_LITERAL',
            }
            key = (cls, row['kind'], logical.casefold(), rel, row['source_line'])
            if key not in seen:
                seen.add(key)
                rows.append(row)

        for block in _HEAD_BLOCK_RE.finditer(text):
            cls = wanted.get(block.group('class').casefold())
            if not cls:
                continue
            body = block.group('body')
            body_start = block.start('body')
            for hm in _QUOTED_HEAD_PATH_RE.finditer(body):
                literal = _norm(hm.group('path'))
                logical = _logical_inx(literal)
                row = {
                    'class': cls,
                    'kind': 'HEAD_CONFIG',
                    'source_literal': literal,
                    'logical_inx': logical,
                    'source_id': tree.source_id,
                    'source_file': rel,
                    'source_line': _line_number(text, body_start + hm.start()),
                    'evidence': 'REFERENCE_HEAD_MODEL_TABLE',
                }
                key = (cls, row['kind'], logical.casefold(), rel, row['source_line'])
                if key not in seen:
                    seen.add(key)
                    rows.append(row)

    # Collapse duplicate paths while retaining all source witnesses.
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row['class'], row['kind'], row['logical_inx'].casefold())
        dst = grouped.get(key)
        witness = {
            'source_id': row['source_id'],
            'source_file': row['source_file'],
            'source_line': row['source_line'],
            'source_literal': row['source_literal'],
            'evidence': row['evidence'],
        }
        if dst is None:
            dst = {
                'class': row['class'],
                'kind': row['kind'],
                'logical_inx': row['logical_inx'],
                'witnesses': [],
            }
            grouped[key] = dst
        if witness not in dst['witnesses']:
            dst['witnesses'].append(witness)

    out = list(grouped.values())
    out.sort(key=lambda x: (x['class'].casefold(), x['kind'], x['logical_inx'].casefold()))
    return out


def _resolve_exact(logical: str, target, donors: list) -> dict[str, Any]:
    logical = _norm(logical)
    p = target.resolve_exact(logical)
    if p is not None:
        return {
            'status': 'PRESENT_TARGET', 'logical_path': logical,
            'source_label': target.label, 'physical_path': str(p), 'match_mode': 'EXACT_RELATIVE_PATH',
            'candidates': [],
        }
    hits = []
    for donor in donors:
        p = donor.resolve_exact(logical)
        if p is not None:
            hits.append((donor, p))
    unique = {(d.label, str(p)): (d, p) for d, p in hits}
    vals = list(unique.values())
    if len(vals) == 1:
        d, p = vals[0]
        return {
            'status': 'RECOVERABLE_REFERENCE', 'logical_path': logical,
            'source_label': d.label, 'physical_path': str(p), 'match_mode': 'EXACT_RELATIVE_PATH',
            'candidates': [],
        }
    if vals:
        return {
            'status': 'CONFLICT', 'logical_path': logical, 'source_label': '', 'physical_path': '',
            'match_mode': 'MULTIPLE_REFERENCE_CANDIDATES',
            'candidates': [f'{d.label}:{p}' for d, p in vals],
        }
    return {
        'status': 'MISSING_UNKNOWN', 'logical_path': logical, 'source_label': '', 'physical_path': '',
        'match_mode': '', 'candidates': [],
    }


def _load_pairing(project_root: pathlib.Path) -> dict[str, dict[str, str]]:
    p = pathlib.Path(project_root) / 'data' / 'asset_registry' / 'inx_physical_pairing.csv'
    if not p.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with p.open('r', encoding='utf-8', errors='replace', newline='') as f:
        for row in csv.DictReader(f):
            logical = _norm(row.get('inx') or '')
            if logical:
                out[logical.casefold()] = dict(row)
    return out


def _asset_id(logical: str) -> str:
    return 'ASSET:' + _norm(logical).casefold()


def _motion_state_id(class_name: str, root: str, state: str) -> str:
    return f'MOTION_STATE:{class_name}:{_norm(root).casefold()}:{state.casefold()}'


def audit_class_motion_contract(
    project_root: pathlib.Path,
    reference_tree: SourceTree,
    class_name: str,
    target,
    donors: list,
    graph,
    *,
    skill_contracts: Iterable[dict[str, Any]] = (),
    class_configs: Iterable[dict[str, Any]] | None = None,
    reference_motion_registry: dict[str, Any] | None = None,
    current_motion_registry: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed class motion contract from source config -> INX -> SMB.

    The routine does *not* assign a concrete MotionInfo record to a skill unless
    source evidence names it.  ``ANIMATIONTYPE_Skill`` is resolved only to the
    class-level ``SKILL`` motion state declared by the verified motion root.
    """
    all_cfgs = [x for x in (class_configs if class_configs is not None else parse_reference_class_configs(reference_tree, (class_name,))) if x['class'] == class_name]
    pairing = _load_pairing(project_root)
    sources_by_label = {target.label: target, **{d.label: d for d in donors}}

    config_rows: list[dict[str, Any]] = []
    root_rows: dict[str, dict[str, Any]] = {}
    root_counts = collections.Counter()
    body_root_counts = collections.Counter()
    config_status_counts = collections.Counter()
    link_status_counts = collections.Counter()
    parse_cache: dict[str, dict[str, Any]] = {}

    class_node = f'PLAYER_CLASS:{class_name}'

    for i, cfg in enumerate(all_cfgs, start=1):
        logical = cfg['logical_inx']
        resolution = _resolve_exact(logical, target, donors)
        config_status_counts[resolution['status']] += 1
        row = {**cfg, **resolution}
        config_node = _asset_id(logical)
        graph.ensure_node(
            config_node, 'ASSET', pathlib.PurePosixPath(logical).name,
            logical_path=logical, asset_role='PLAYER_CLASS_CONFIG_INX', config_kind=cfg['kind'],
            resolution={k: resolution[k] for k in ('status','source_label','physical_path','match_mode','candidates')},
        )
        evidence = cfg['witnesses'][0] if cfg.get('witnesses') else {}
        graph.connect(
            class_node, config_node, 'USES_CLASS_CONFIG',
            evidence=f"{evidence.get('source_id','REFERENCE')}:{evidence.get('source_file','')}:{evidence.get('source_line','')}",
            confidence=1.0, required=None, status=resolution['status'], config_kind=cfg['kind'],
        )

        if not resolution['physical_path']:
            row.update({'link_status': 'PHYSICAL_CONFIG_UNAVAILABLE', 'motion_root': '', 'motion_root_resolution': {}})
            config_rows.append(row)
            continue

        physical = pathlib.Path(resolution['physical_path'])
        cache_key = str(physical.resolve()).casefold()
        if cache_key not in parse_cache:
            try:
                parsed = inxcore.parse_inx(physical)
                link = verified_inx_link_target(physical)
                parse_cache[cache_key] = {'parsed': parsed, 'link': link, 'error': ''}
            except Exception as exc:
                parse_cache[cache_key] = {'parsed': None, 'link': None, 'error': f'{type(exc).__name__}:{exc}'}
        cached = parse_cache[cache_key]
        if cached['error']:
            link_status_counts['PARSE_ERROR'] += 1
            row.update({'link_status': 'PARSE_ERROR', 'parse_error': cached['error'], 'motion_root': '', 'motion_root_resolution': {}})
            config_rows.append(row)
            continue

        parsed = cached['parsed']
        link = cached['link'] or {}
        link_status = str(link.get('status') or 'UNKNOWN')
        root_logical = ''
        root_evidence = ''
        if link_status == 'VERIFIED' and link.get('target'):
            root_logical = _logical_inx(str(link['target']))
            root_evidence = 'INX_SPEEDSUM_LINK_CODE'
        elif int(parsed.get('motion_count', 0) or 0) > 0:
            root_logical = logical
            link_status = 'SELF_MOTION_OWNER'
            root_evidence = 'INX_MOTIONINFO_SELF_OWNER'
        link_status_counts[link_status] += 1

        root_resolution = _resolve_exact(root_logical, target, donors) if root_logical else {}
        row.update({
            'link_status': link_status,
            'link_file': str(link.get('link_file') or ''),
            'motion_root': root_logical,
            'motion_root_resolution': root_resolution,
        })
        config_rows.append(row)
        if not root_logical:
            continue

        root_counts[root_logical.casefold()] += 1
        if cfg['kind'] == 'BODY_BASE_CONFIG':
            body_root_counts[root_logical.casefold()] += 1
        graph.ensure_node(
            _asset_id(root_logical), 'ASSET', pathlib.PurePosixPath(root_logical).name,
            logical_path=root_logical, asset_role='PLAYER_CLASS_MOTION_INX',
            resolution={k: root_resolution.get(k) for k in ('status','source_label','physical_path','match_mode','candidates')},
        )
        graph.connect(
            config_node, _asset_id(root_logical), 'LINKS_MOTION_ROOT',
            evidence=root_evidence, confidence=1.0, required=None,
            status=str(root_resolution.get('status') or 'MISSING_UNKNOWN'), config_kind=cfg['kind'],
        )

        key = root_logical.casefold()
        if key in root_rows:
            continue
        root = {
            'logical_inx': root_logical,
            'resolution': root_resolution,
            'parse_status': 'NOT_PARSED',
            'motion_count': 0,
            'state_counts': {},
            'motion_states': [],
            'motion_smb': '',
            'motion_smb_resolution': {},
            'smb_validation': {},
        }
        root_rows[key] = root
        if not root_resolution.get('physical_path'):
            root['parse_status'] = 'PHYSICAL_ROOT_UNAVAILABLE'
            continue
        try:
            rp = pathlib.Path(root_resolution['physical_path'])
            rparsed = inxcore.parse_inx(rp)
            state_counts = collections.Counter(str(m.get('state_name') or '') for m in rparsed.get('motions', []))
            root.update({
                'parse_status': 'PASS',
                'motion_count': int(rparsed.get('motion_count', 0) or 0),
                'file_code': int(rparsed.get('file_code', 0) or 0),
                'state_counts': dict(state_counts),
                'motion_states': [
                    {
                        'index': int(m.get('index', 0)), 'state': int(m.get('state', 0)),
                        'state_name': str(m.get('state_name') or ''),
                        'start': int(m.get('start', 0)), 'end': int(m.get('end', 0)),
                        'event_frames': [int(x) for x in (m.get('event_frames') or [])],
                        'item_code_count': int(m.get('item_code_count', 0) or 0),
                        'item_code_list': [int(x) for x in (m.get('item_code_list') or [])],
                        'job_code_bit': int(m.get('job_code_bit', 0) or 0),
                        'skill_code_list': [int(x) for x in (m.get('skill_code_list') or [])],
                        'map_position': int(m.get('map_position', 0) or 0),
                        'repeat': int(m.get('repeat', 0)), 'key_code': int(m.get('key_code', 0)),
                        'motion_frame': int(m.get('motion_frame', 0)),
                        'encoding': str(m.get('encoding') or ''),
                        'decode_ok': bool(m.get('start_ok') and m.get('end_ok')),
                    }
                    for m in rparsed.get('motions', [])
                ],
            })
            for state_name, count in sorted(state_counts.items()):
                state_node = _motion_state_id(class_name, root_logical, state_name)
                indices = [int(m['index']) for m in rparsed['motions'] if str(m.get('state_name')) == state_name]
                graph.ensure_node(
                    state_node, 'MOTION_STATE', state_name,
                    class_name=class_name, motion_inx=root_logical, record_count=int(count), record_indices=indices,
                )
                graph.connect(
                    _asset_id(root_logical), state_node, 'DECLARES_MOTION_STATE',
                    evidence='INX_MOTIONINFO', confidence=1.0, required=None, status='SOURCE_PHYSICAL_PROVEN',
                    record_count=int(count), record_indices=indices,
                )
        except Exception as exc:
            root['parse_status'] = 'PARSE_ERROR'
            root['parse_error'] = f'{type(exc).__name__}:{exc}'
            continue

        prow = pairing.get(root_logical.casefold()) or {}
        motion_smb = _norm(prow.get('motion_smb') or '')
        if motion_smb:
            smb_resolution = _resolve_exact(motion_smb, target, donors)
            root['motion_smb'] = motion_smb
            root['motion_smb_resolution'] = smb_resolution
            graph.ensure_node(
                _asset_id(motion_smb), 'ASSET', pathlib.PurePosixPath(motion_smb).name,
                logical_path=motion_smb, asset_role='PLAYER_CLASS_MOTION_SMB',
                resolution={k: smb_resolution.get(k) for k in ('status','source_label','physical_path','match_mode','candidates')},
            )
            graph.connect(
                _asset_id(root_logical), _asset_id(motion_smb), 'PAIRS_MOTION_SMB',
                evidence='INX_PHYSICAL_PAIRING_CSV', confidence=1.0, required=None,
                status=str(smb_resolution.get('status') or 'MISSING_UNKNOWN'),
            )
            if smb_resolution.get('physical_path') and root['parse_status'] == 'PASS':
                try:
                    root['smb_validation'] = inxcore.validate_with_smb(rparsed, pathlib.Path(smb_resolution['physical_path']))
                except Exception as exc:
                    root['smb_validation'] = {'check': 'FAIL', 'error': f'{type(exc).__name__}:{exc}'}

        if progress and i % 100 == 0:
            progress(f'{class_name} motion configs {i}/{len(all_cfgs)}')

    # Prefer body-base links when determining the canonical class motion root.
    dominant_counts = body_root_counts or root_counts
    dominant_key = dominant_counts.most_common(1)[0][0] if dominant_counts else ''
    dominant = root_rows.get(dominant_key) if dominant_key else None
    dominant_logical = str((dominant or {}).get('logical_inx') or '')
    skill_state_count = int(((dominant or {}).get('state_counts') or {}).get('SKILL', 0) or 0)
    smb_check = str(((dominant or {}).get('smb_validation') or {}).get('check') or '')
    smb_resolution_status = str(((dominant or {}).get('motion_smb_resolution') or {}).get('status') or '')

    if not all_cfgs:
        state = 'SOURCE_CLASS_CONFIG_NOT_DISCOVERED'
    elif not body_root_counts:
        state = 'BODY_MOTION_ROOT_NOT_VERIFIED'
    elif not dominant or dominant.get('parse_status') != 'PASS':
        state = 'MOTION_ROOT_UNRESOLVED'
    elif skill_state_count <= 0:
        state = 'SKILL_MOTION_STATE_NOT_DECLARED'
    elif not dominant.get('motion_smb'):
        state = 'MOTION_SMB_NOT_PAIRED'
    elif smb_resolution_status not in {'PRESENT_TARGET', 'RECOVERABLE_REFERENCE'}:
        state = 'MOTION_SMB_UNAVAILABLE'
    elif smb_check == 'FAIL':
        state = 'MOTION_SMB_VALIDATION_FAILED'
    elif str((dominant.get('resolution') or {}).get('status')) == 'PRESENT_TARGET' and smb_resolution_status == 'PRESENT_TARGET':
        state = 'TARGET_CLASS_SKILL_MOTION_READY'
    else:
        state = 'CLASS_SKILL_MOTION_RECOVERABLE'


    # Resolve the exact MotionInfo records through the runtime's real semantic
    # chain: MotionInfo.SkillCodeList byte -> SkillDataCode[index] -> active
    # skill play code.  The physical INX bytes are authoritative; the EU table
    # is used only as a reference semantic registry, while the current Summit
    # table is audited independently for index drift.
    reference_motion_registry = dict(reference_motion_registry or {})
    current_motion_registry = dict(current_motion_registry or {})
    ref_entries = list(reference_motion_registry.get('entries') or [])
    cur_entries = list(current_motion_registry.get('entries') or [])
    ref_by_index = {int(x['index']): x for x in ref_entries if x.get('index') is not None}
    cur_by_index = {int(x['index']): x for x in cur_entries if x.get('index') is not None}
    skill_contracts = list(skill_contracts)
    max_contract_ordinal = max((int(x.get('class_ordinal') or 0) for x in skill_contracts), default=0)
    ref_class_entries_all = sorted(
        [x for x in ref_entries if str(x.get('class') or '') == class_name],
        key=lambda x: int(x.get('class_ordinal') or 0),
    )
    # SkillManager.h keeps generic JUMP/CONTATTACK rows immediately after the
    # 20 Shaman rows under the same comment section.  They are valid registry
    # entries but are not members of the 20-skill class catalog.  Bound the
    # class contract to the ordinals actually declared by shared/skill.h.
    ref_class_entries = [
        x for x in ref_class_entries_all
        if not max_contract_ordinal or int(x.get('class_ordinal') or 0) <= max_contract_ordinal
    ]
    ref_by_ordinal = {int(x.get('class_ordinal') or 0): x for x in ref_class_entries if int(x.get('class_ordinal') or 0) > 0}

    def _canon_skill_name(value: str) -> str:
        return re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())

    current_name_index = collections.defaultdict(list)
    for entry in cur_entries:
        current_name_index[_canon_skill_name(entry.get('name'))].append(int(entry.get('index') or 0))

    registry_alignment = []
    for expected in ref_class_entries:
        idx = int(expected.get('index') or 0)
        current = cur_by_index.get(idx)
        exp_name = str(expected.get('name') or '')
        current_name = str((current or {}).get('name') or '')
        if current is None:
            alignment = 'CURRENT_INDEX_MISSING'
        elif _canon_skill_name(current_name) == _canon_skill_name(exp_name):
            alignment = 'INDEX_NAME_ALIGNED'
        else:
            elsewhere = current_name_index.get(_canon_skill_name(exp_name), [])
            alignment = 'CURRENT_NAME_AT_DIFFERENT_INDEX' if elsewhere else 'INDEX_POINTS_TO_DIFFERENT_SKILL'
        registry_alignment.append({
            'reference_index': idx,
            'reference_name': exp_name,
            'reference_play_token': expected.get('play_token'),
            'reference_play_id': expected.get('play_id'),
            'class_ordinal': expected.get('class_ordinal'),
            'current_index_name': current_name,
            'current_index_play_token': (current or {}).get('play_token'),
            'current_index_play_id': (current or {}).get('play_id'),
            'current_name_indices': list(current_name_index.get(_canon_skill_name(exp_name), [])),
            'status': alignment,
        })

    dominant_skill_motions = [
        m for m in ((dominant or {}).get('motion_states') or [])
        if str(m.get('state_name') or '') == 'SKILL'
    ]
    skill_motion_bindings = []
    exact_binding_count = 0
    passive_count = 0
    active_expected_count = 0
    for skill in skill_contracts:
        ordinal = int(skill.get('class_ordinal') or 0)
        expected = ref_by_ordinal.get(ordinal)
        row = {
            'skill_id': str(skill.get('skill_id') or ''),
            'skill_name': str(skill.get('skill_name') or ''),
            'tier': skill.get('tier'),
            'tier_slot': skill.get('tier_slot'),
            'class_ordinal': ordinal,
            'reference_registry': expected or {},
            'matching_motion_indices': [],
            'matching_motion_records': [],
            'binding_status': 'REFERENCE_REGISTRY_ENTRY_NOT_FOUND',
            'current_runtime_registry_status': 'UNASSESSED',
            'current_runtime_selectability_certified': False,
        }
        if expected is None:
            skill_motion_bindings.append(row)
            continue
        expected_index = int(expected.get('index') or 0)
        play_id = expected.get('play_id')
        current_at_index = cur_by_index.get(expected_index)
        if current_at_index is None:
            row['current_runtime_registry_status'] = 'CURRENT_INDEX_MISSING'
        elif _canon_skill_name(current_at_index.get('name')) == _canon_skill_name(expected.get('name')):
            row['current_runtime_registry_status'] = 'INDEX_NAME_ALIGNED'
        else:
            row['current_runtime_registry_status'] = 'INDEX_POINTS_TO_DIFFERENT_SKILL'

        # Undefined/passive entries deliberately have no class SKILL motion.
        if play_id in {None, 0}:
            passive_count += 1
            row['binding_status'] = 'PASSIVE_NO_SKILL_MOTION_EXPECTED'
            skill_motion_bindings.append(row)
            continue

        active_expected_count += 1
        matches = [
            m for m in dominant_skill_motions
            if expected_index in set(int(x) for x in (m.get('skill_code_list') or []))
        ]
        row['matching_motion_indices'] = [int(m.get('index') or 0) for m in matches]
        row['matching_motion_records'] = [
            {
                'index': int(m.get('index') or 0),
                'motion_frame': int(m.get('motion_frame') or 0),
                'start': int(m.get('start') or 0),
                'end': int(m.get('end') or 0),
                'skill_code_list': [int(x) for x in (m.get('skill_code_list') or [])],
                'event_frames': [int(x) for x in (m.get('event_frames') or [])],
                'item_code_count': int(m.get('item_code_count') or 0),
                'item_code_list': [int(x) for x in (m.get('item_code_list') or [])],
                'job_code_bit': int(m.get('job_code_bit') or 0),
                'map_position': int(m.get('map_position') or 0),
            }
            for m in matches
        ]
        if len(matches) == 1:
            row['binding_status'] = 'REFERENCE_SKILLCODELIST_EXACT'
            exact_binding_count += 1
        elif len(matches) > 1:
            row['binding_status'] = 'REFERENCE_SKILLCODELIST_AMBIGUOUS'
        else:
            row['binding_status'] = 'REFERENCE_SKILLCODELIST_NOT_FOUND'
        skill_motion_bindings.append(row)

    alignment_counts = collections.Counter(x['status'] for x in registry_alignment)
    binding_counts = collections.Counter(x['binding_status'] for x in skill_motion_bindings)
    current_registry_class_count = sum(1 for x in cur_entries if str(x.get('class') or '') == class_name)
    if not ref_class_entries:
        motion_registry_status = 'REFERENCE_MOTION_REGISTRY_CLASS_NOT_FOUND'
    elif not dominant_skill_motions:
        motion_registry_status = 'PHYSICAL_SKILL_MOTION_RECORDS_NOT_FOUND'
    elif active_expected_count and exact_binding_count == active_expected_count:
        if current_registry_class_count == len(ref_class_entries) and not alignment_counts.get('INDEX_POINTS_TO_DIFFERENT_SKILL') and not alignment_counts.get('CURRENT_INDEX_MISSING'):
            motion_registry_status = 'REFERENCE_BINDINGS_EXACT_CURRENT_REGISTRY_STRUCTURALLY_ALIGNED'
        else:
            motion_registry_status = 'REFERENCE_BINDINGS_EXACT_CURRENT_RUNTIME_REGISTRY_DRIFT'
    elif exact_binding_count:
        motion_registry_status = 'REFERENCE_BINDINGS_PARTIAL'
    else:
        motion_registry_status = 'REFERENCE_BINDINGS_UNRESOLVED'

    active_bindings = [
        x for x in skill_motion_bindings
        if x.get('binding_status') != 'PASSIVE_NO_SKILL_MOTION_EXPECTED'
        and x.get('reference_registry')
    ]
    aligned_active_count = sum(
        1 for x in active_bindings
        if x.get('current_runtime_registry_status') == 'INDEX_NAME_ALIGNED'
    )
    if not active_bindings:
        runtime_motion_selectability_status = 'NO_ACTIVE_SKILL_MOTION_EXPECTATIONS'
    elif aligned_active_count == len(active_bindings):
        runtime_motion_selectability_status = 'CURRENT_REGISTRY_INDEX_NAMES_ALIGNED'
    elif aligned_active_count:
        runtime_motion_selectability_status = 'CURRENT_REGISTRY_PARTIAL_INDEX_ALIGNMENT'
    else:
        runtime_motion_selectability_status = 'CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES'

    # Add exact reference bindings to the graph without claiming that the
    # current Summit runtime can select them yet.
    if dominant_logical:
        for binding in skill_motion_bindings:
            if binding['binding_status'] != 'REFERENCE_SKILLCODELIST_EXACT':
                continue
            skill_node = f"SKILL:{class_name}:{binding['skill_id']}"
            for record in binding['matching_motion_records']:
                motion_node = f"MOTION_RECORD:{class_name}:{_norm(dominant_logical).casefold()}:{record['index']}"
                graph.ensure_node(
                    motion_node, 'MOTION_RECORD', f"{class_name} MotionInfo[{record['index']}]",
                    class_name=class_name, motion_inx=dominant_logical, state='SKILL',
                    **record,
                )
                graph.connect(
                    skill_node, motion_node, 'REFERENCE_RESOLVES_SKILL_MOTION_RECORD',
                    evidence='INX_SKILLCODELIST+REFERENCE_SKILL_REGISTRY',
                    confidence=1.0, required=None,
                    status='REFERENCE_EXACT_CURRENT_RUNTIME_NOT_CERTIFIED',
                    reference_registry_index=binding['reference_registry'].get('index'),
                    current_runtime_registry_status=binding['current_runtime_registry_status'],
                )

    # Resolve symbolic ANIMATIONTYPE_Skill to the class-level SKILL state as
    # the conservative baseline. Exact per-skill MotionInfo edges above are
    # emitted only when the physical SkillCodeList bytes prove them.
    requested_skills = []
    if dominant_logical and skill_state_count > 0:
        state_node = _motion_state_id(class_name, dominant_logical, 'SKILL')
        animation_node = 'ANIMATION_TOKEN:animationtype_skill'
        graph.ensure_node(animation_node, 'ANIMATION_TOKEN', 'ANIMATIONTYPE_Skill')
        graph.connect(
            animation_node, state_node, 'RESOLVES_TO_CLASS_MOTION_STATE',
            evidence='SOURCE_ANIMATION_TOKEN+INX_STATE_0x150', confidence=1.0,
            required=None, status='CLASS_STATE_PROVEN_RECORD_UNASSIGNED',
        )
        for skill in skill_contracts:
            if 'ANIMATIONTYPE_Skill' not in set(skill.get('animation_tokens') or []):
                continue
            requested_skills.append(str(skill.get('skill_name') or ''))
            skill_node = f"SKILL:{class_name}:{skill.get('skill_id')}"
            graph.connect(
                skill_node, state_node, 'REQUESTS_CLASS_MOTION_STATE',
                evidence='REFERENCE_HANDLER:ANIMATIONTYPE_Skill', confidence=1.0,
                required=None, status='CLASS_STATE_PROVEN_RECORD_UNASSIGNED',
                specific_motion_record_certified=False,
            )

    kind_counts = collections.Counter(x['kind'] for x in all_cfgs)
    target_kind_counts = collections.Counter(
        x['kind'] for x in config_rows if x.get('status') == 'PRESENT_TARGET'
    )
    missing_configs = [x['logical_inx'] for x in config_rows if x.get('status') == 'MISSING_UNKNOWN']
    recoverable_configs = [x['logical_inx'] for x in config_rows if x.get('status') == 'RECOVERABLE_REFERENCE']
    conflicts = [x['logical_inx'] for x in config_rows if x.get('status') == 'CONFLICT']

    roots_out = []
    for k, root in sorted(root_rows.items(), key=lambda kv: kv[0]):
        rr = dict(root)
        rr['linked_config_count'] = int(root_counts.get(k, 0))
        rr['body_base_link_count'] = int(body_root_counts.get(k, 0))
        roots_out.append(rr)

    return {
        'format': FORMAT,
        'class': class_name,
        'status': state,
        'source_config_count': len(all_cfgs),
        'source_config_kind_counts': dict(kind_counts),
        'target_config_kind_counts': dict(target_kind_counts),
        'config_status_counts': dict(config_status_counts),
        'link_status_counts': dict(link_status_counts),
        'missing_configs': missing_configs,
        'recoverable_configs': recoverable_configs,
        'conflict_configs': conflicts,
        'verified_motion_root_count': len(root_rows),
        'dominant_motion_root': dominant_logical,
        'dominant_motion_root_basis': 'BODY_BASE_CONFIG_LINK_MAJORITY' if body_root_counts else ('ALL_CLASS_CONFIG_LINK_MAJORITY' if root_counts else 'NONE'),
        'dominant_skill_motion_record_count': skill_state_count,
        'dominant_motion_smb': str((dominant or {}).get('motion_smb') or ''),
        'dominant_motion_smb_status': smb_resolution_status,
        'dominant_smb_validation': (dominant or {}).get('smb_validation') or {},
        'skills_requesting_animationtype_skill': sorted(set(x for x in requested_skills if x), key=str.casefold),
        'specific_skill_motion_record_certified': bool(active_expected_count and exact_binding_count == active_expected_count),
        'specific_skill_motion_record_certification_scope': 'REFERENCE_REGISTRY_PLUS_PHYSICAL_INX_SKILLCODELIST',
        'motion_registry_status': motion_registry_status,
        'runtime_motion_selectability_status': runtime_motion_selectability_status,
        'current_registry_aligned_active_skill_count': aligned_active_count,
        'current_registry_active_skill_count': len(active_bindings),
        'reference_motion_registry': {
            'status': reference_motion_registry.get('status'),
            'source_file': reference_motion_registry.get('source_file'),
            'registry_kind': reference_motion_registry.get('registry_kind'),
            'entry_count': reference_motion_registry.get('entry_count'),
            'class_entry_count': len(ref_class_entries),
            'class_section_entry_count': len(ref_class_entries_all),
            'class_contract_max_ordinal': max_contract_ordinal,
            'selector_witnesses': reference_motion_registry.get('selector_witnesses', []),
        },
        'current_motion_registry': {
            'status': current_motion_registry.get('status'),
            'source_file': current_motion_registry.get('source_file'),
            'registry_kind': current_motion_registry.get('registry_kind'),
            'entry_count': current_motion_registry.get('entry_count'),
            'class_entry_count': current_registry_class_count,
            'selector_witnesses': current_motion_registry.get('selector_witnesses', []),
        },
        'registry_alignment_counts': dict(alignment_counts),
        'registry_alignment': registry_alignment,
        'skill_motion_binding_counts': dict(binding_counts),
        'skill_motion_bindings': skill_motion_bindings,
        'active_skill_motion_expected_count': active_expected_count,
        'passive_skill_count': passive_count,
        'exact_skill_motion_binding_count': exact_binding_count,
        'roots': roots_out,
        'configs': config_rows,
        'hashes_calculated': 0,
        'client_modified': False,
        'server_modified': False,
        'notes': [
            'Logical .ini/.inf class configs are mapped to physical .inx using the same runtime contract as server bundle resolution.',
            'INX LinkFile targets are accepted only when the SpeedSum/link code verifies.',
            'ANIMATIONTYPE_Skill resolves conservatively to the class SKILL state; a specific MotionInfo record is certified only when physical INX SkillCodeList bytes match the reference runtime registry index.',
            'SetMotionFromCode runtime selection is audited as SkillCodeList -> SkillDataCode[index] -> play skill code; current/reference registry drift is reported separately.',
            'No hashes, copies, generation or client/server writes are performed.',
        ],
    }
