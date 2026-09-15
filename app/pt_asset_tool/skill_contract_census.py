from __future__ import annotations

import collections
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .contract_graph import ContractGraph
from .resolver import ClientResolver
from .source_catalog import SourceTree, require_source_trees, source_tree_summary
from .source_evidence import PLAYER_CLASSES, parse_reference_skill_catalog, parse_skill_motion_registry, scan_source_evidence
from .player_class_motion_contract import audit_class_motion_contract, parse_reference_class_configs


FORMAT = 'PT_ASSET_PLAYER_CLASS_CONTRACT_CENSUS_V2'
TARGET_CLASSES = PLAYER_CLASSES

# The EU source groups Assassin/Shaman sound IDs into contiguous reserved
# blocks.  We anchor the family to source symbols rather than hard-coding the
# numeric values so the evidence follows the reference source when codes move.
CLASS_SOUND_RANGE_ANCHORS = {
    'Assassin': ('SKILL_SOUND_STINGGER', 'SKILL_SOUND_STORM'),
    'Shaman': ('SKILL_SOUND_DARK_BOLT1', 'SKILL_SOUND_G_NAIL2'),
}


@dataclass
class PhysicalResolution:
    status: str
    logical_path: str
    source_label: str = ''
    physical_path: str = ''
    match_mode: str = ''
    candidates: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'status': self.status,
            'logical_path': self.logical_path,
            'source_label': self.source_label,
            'physical_path': self.physical_path,
            'match_mode': self.match_mode,
            'candidates': list(self.candidates or []),
        }


class PhysicalSource:
    def __init__(self, label: str, root: pathlib.Path):
        self.label = label
        self.root = pathlib.Path(root).expanduser().resolve()
        self.resolver = ClientResolver(self.root)
        self._basename: dict[str, list[pathlib.Path]] | None = None

    @property
    def basename_index(self) -> dict[str, list[pathlib.Path]]:
        if self._basename is None:
            out: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
            for p in self.resolver.index.values():
                out[p.name.casefold()].append(p)
            # Include case-collision files not represented by resolver.index.
            for paths in self.resolver.collisions.values():
                for p in paths:
                    if p not in out[p.name.casefold()]:
                        out[p.name.casefold()].append(p)
            self._basename = out
        return self._basename

    def resolve_exact(self, logical: str) -> pathlib.Path | None:
        try:
            return self.resolver.resolve(logical, required=False)
        except RuntimeError:
            return None

    def resolve_basename(self, basename: str) -> tuple[pathlib.Path | None, list[pathlib.Path]]:
        hits = list(self.basename_index.get(pathlib.PurePosixPath(basename).name.casefold(), []))
        hits.sort(key=lambda p: p.as_posix().casefold())
        return (hits[0] if len(hits) == 1 else None), hits

    def rel(self, p: pathlib.Path) -> str:
        return pathlib.Path(p).relative_to(self.root).as_posix()


def _parse_donor_specs(values: Iterable[str] | None) -> list[tuple[str, pathlib.Path]]:
    out: list[tuple[str, pathlib.Path]] = []
    for raw in values or []:
        raw = str(raw)
        if '=' not in raw:
            raise ValueError(f'DONOR_SPEC_REQUIRES_LABEL_EQUALS_PATH:{raw}')
        label, path = raw.split('=', 1)
        label = label.strip()
        p = pathlib.Path(path.strip()).expanduser().resolve()
        if not label:
            raise ValueError(f'DONOR_LABEL_EMPTY:{raw}')
        if not p.is_dir():
            raise FileNotFoundError(f'DONOR_ROOT_NOT_FOUND:{label}:{p}')
        out.append((label, p))
    return out


def _asset_node_id(logical: str) -> str:
    return 'ASSET:' + logical.replace('\\', '/').casefold()


def _skill_node_id(class_name: str, skill_id: str) -> str:
    return f'SKILL:{class_name}:{skill_id}'


def _class_node_id(class_name: str) -> str:
    return f'PLAYER_CLASS:{class_name}'


def _resolve_asset(
    logical: str,
    target: PhysicalSource,
    donors: list[PhysicalSource],
    *,
    basename_only: bool = False,
) -> PhysicalResolution:
    logical = logical.replace('\\', '/')
    if not basename_only:
        p = target.resolve_exact(logical)
        if p is not None:
            return PhysicalResolution('PRESENT_TARGET', logical, target.label, str(p), 'EXACT_RELATIVE_PATH')
    bp, bh = target.resolve_basename(pathlib.PurePosixPath(logical).name)
    if basename_only and bp is not None:
        return PhysicalResolution('PRESENT_TARGET', logical, target.label, str(bp), 'UNIQUE_BASENAME')
    if basename_only and len(bh) > 1:
        return PhysicalResolution('CONFLICT', logical, target.label, '', 'AMBIGUOUS_BASENAME', [str(x) for x in bh])

    donor_hits: list[tuple[PhysicalSource, pathlib.Path, str]] = []
    for donor in donors:
        p = None if basename_only else donor.resolve_exact(logical)
        if p is not None:
            donor_hits.append((donor, p, 'EXACT_RELATIVE_PATH'))
            continue
        bp, bh = donor.resolve_basename(pathlib.PurePosixPath(logical).name)
        if bp is not None:
            donor_hits.append((donor, bp, 'UNIQUE_BASENAME'))
        elif len(bh) > 1:
            for x in bh:
                donor_hits.append((donor, x, 'AMBIGUOUS_BASENAME'))

    unique = {(d.label, str(p)): (d, p, mode) for d, p, mode in donor_hits}
    vals = list(unique.values())
    if len(vals) == 1:
        donor, p, mode = vals[0]
        return PhysicalResolution('RECOVERABLE_REFERENCE', logical, donor.label, str(p), mode)
    if vals:
        return PhysicalResolution('CONFLICT', logical, '', '', 'MULTIPLE_REFERENCE_CANDIDATES', [f'{d.label}:{p}' for d, p, _ in vals])
    return PhysicalResolution('MISSING_UNKNOWN', logical)


def _part_dependency_closure(
    root_resolution: PhysicalResolution,
    target: PhysicalSource,
    donors: list[PhysicalSource],
    *,
    max_depth: int = 8,
) -> list[dict[str, Any]]:
    if not root_resolution.physical_path or not root_resolution.physical_path.casefold().endswith('.part'):
        return []
    try:
        # Existing parser is deliberately reused instead of adding another .part grammar.
        from pt_part_tool import analyze_bytes
    except Exception:
        return []

    queue: list[tuple[pathlib.Path, int, str]] = [(pathlib.Path(root_resolution.physical_path), 0, root_resolution.logical_path)]
    visited: set[str] = set()
    out: list[dict[str, Any]] = []
    while queue:
        physical, depth, parent = queue.pop(0)
        key = str(physical.resolve()).casefold()
        if key in visited or depth >= max_depth:
            continue
        visited.add(key)
        try:
            analysis = analyze_bytes(physical.read_bytes(), physical.name)
        except Exception as exc:
            out.append({'parent': parent, 'status': 'PARSE_ERROR', 'physical_path': str(physical), 'error': str(exc)})
            continue
        for ref in analysis.references:
            logical = str(ref.get('normalized') or '').replace('\\', '/')
            if not logical:
                continue
            resolved = _resolve_asset(logical, target, donors, basename_only=('/' not in logical))
            row = {'parent': parent, 'depth': depth + 1, 'reference': logical, **resolved.to_dict()}
            out.append(row)
            if logical.casefold().endswith('.part') and resolved.physical_path:
                queue.append((pathlib.Path(resolved.physical_path), depth + 1, logical))
    return out


def _runtime_class_state(class_name: str, current_evidence: dict[str, Any]) -> dict[str, Any]:
    """Describe whether a playable job is enabled in the *current* runtime.

    The first generalized 10-class audit treated absence of a modern per-class
    handler file as proof that a class implementation was missing.  That was a
    false negative for the eight established legacy jobs, whose gameplay logic
    is distributed across older loaders/ASM/shared switches.  A live job-table
    slot inside MAX_JOBNUM is therefore authoritative evidence that the class
    is enabled; handler discovery is retained as a separate coverage signal.
    """
    jobs = [x for x in current_evidence.get('jobs', []) if class_name.casefold() in str(x.get('name', '')).casefold()]
    max_jobs = current_evidence.get('max_jobs', {})
    enabled = int(max_jobs.get('MAX_JOBNUM', 0) or 0)
    capacity = int(max_jobs.get('MAX_JOB_CAPACITY', enabled) or enabled)
    slots = sorted({int(x.get('slot')) for x in jobs if x.get('slot') is not None})
    slot = slots[0] if slots else None
    handler_cases = [x for x in current_evidence.get('skill_cases', []) if x.get('class') == class_name]
    if slot is not None and enabled and slot > enabled:
        state = 'RUNTIME_DISABLED_BY_MAX_JOBNUM'
    elif slot is not None and (not enabled or slot <= enabled):
        state = 'RUNTIME_JOB_ENABLED'
    elif handler_cases:
        state = 'RUNTIME_SOURCE_PRESENT'
    else:
        state = 'RUNTIME_JOB_NOT_DETECTED'
    return {
        'status': state,
        'job_slots': slots,
        'max_jobnum': enabled,
        'max_job_capacity': capacity,
        'handler_skill_case_count': len(handler_cases),
        'handler_detection_status': 'HANDLER_SKILL_CASES_DETECTED' if handler_cases else 'HANDLER_SKILL_CASES_NOT_DETECTED',
        'job_rows': jobs,
    }


def _class_audio_family(class_name: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = CLASS_SOUND_RANGE_ANCHORS.get(class_name)
    if not anchors:
        return []
    symbol_to_code = evidence.get('sound_symbol_to_code', {})
    start = symbol_to_code.get(anchors[0])
    end = symbol_to_code.get(anchors[1])
    if start is None or end is None:
        return []
    if int(start) > int(end):
        start, end = end, start
    out = []
    for raw_code, path in evidence.get('sound_code_to_path', {}).items():
        try:
            code = int(str(raw_code), 16) if str(raw_code).lower().startswith('0x') else int(raw_code)
        except (TypeError, ValueError):
            continue
        if int(start) <= code <= int(end) and path:
            out.append({
                'code': code,
                'code_hex': f'0x{code:04X}',
                'path': str(path),
                'range_start_symbol': anchors[0],
                'range_end_symbol': anchors[1],
            })
    out.sort(key=lambda x: x['code'])
    return out


def _source_skill_coverage(class_name: str, skill_names: Iterable[str], evidence: dict[str, Any]) -> dict[str, Any]:
    expected = {str(x) for x in skill_names}
    by_layer: dict[str, set[str]] = collections.defaultdict(set)
    rows = []
    for row in evidence.get('class_skill_mentions', []):
        if row.get('class') != class_name:
            continue
        name = str(row.get('skill_name') or '')
        if name not in expected:
            continue
        layer = str(row.get('layer') or 'UNKNOWN')
        by_layer[layer].add(name)
        rows.append(row)

    client = by_layer.get('CLIENT_RUNTIME', set())
    server = by_layer.get('SERVER_RUNTIME', set())
    any_source = set().union(*by_layer.values()) if by_layer else set()
    missing_client = sorted(expected - client, key=str.casefold)
    missing_server = sorted(expected - server, key=str.casefold)
    return {
        'expected_skill_count': len(expected),
        'client_runtime_skill_count': len(client),
        'server_runtime_skill_count': len(server),
        'any_class_source_skill_count': len(any_source),
        'client_runtime_skills': sorted(client, key=str.casefold),
        'server_runtime_skills': sorted(server, key=str.casefold),
        'missing_from_client_runtime_source': missing_client,
        'missing_from_server_runtime_source': missing_server,
        'evidence_rows': rows,
    }


def _reference_contract_state(reference_coverage: dict[str, Any]) -> str:
    expected = int(reference_coverage.get('expected_skill_count', 0) or 0)
    client = int(reference_coverage.get('client_runtime_skill_count', 0) or 0)
    server = int(reference_coverage.get('server_runtime_skill_count', 0) or 0)
    if expected and client >= expected and server >= expected:
        return 'REFERENCE_CLIENT_SERVER_SOURCE_COMPLETE'
    if expected and server >= expected:
        return 'REFERENCE_SERVER_COMPLETE_CLIENT_PARTIAL'
    if client or server:
        return 'REFERENCE_RUNTIME_SOURCE_PARTIAL'
    return 'REFERENCE_RUNTIME_SOURCE_NOT_DETECTED'


def _migration_state(runtime_state: dict[str, Any], current_coverage: dict[str, Any], reference_coverage: dict[str, Any]) -> str:
    runtime_status = str(runtime_state.get('status') or '')
    if runtime_status == 'RUNTIME_DISABLED_BY_MAX_JOBNUM':
        return 'RUNTIME_BLOCKED_MAX_JOBNUM'
    cur_any = int(current_coverage.get('any_class_source_skill_count', 0) or 0)
    ref_any = int(reference_coverage.get('any_class_source_skill_count', 0) or 0)
    # A currently enabled job is already runtime evidence.  Source-coverage
    # drift against the EU tree is still valuable, but it is discovery debt,
    # not proof that the working legacy class is absent.
    if runtime_status == 'RUNTIME_JOB_ENABLED':
        if ref_any and cur_any == 0:
            return 'RUNTIME_CLASS_ENABLED_HANDLER_DISCOVERY_INCOMPLETE'
        if cur_any < ref_any:
            return 'RUNTIME_CLASS_ENABLED_SOURCE_PARTIAL'
        return 'RUNTIME_CLASS_SOURCE_AT_REFERENCE_LEVEL'
    if ref_any and cur_any == 0:
        return 'RUNTIME_CLASS_IMPLEMENTATION_MISSING'
    if cur_any < ref_any:
        return 'RUNTIME_CLASS_IMPLEMENTATION_PARTIAL'
    return 'RUNTIME_CLASS_SOURCE_AT_REFERENCE_LEVEL'


def audit_player_class_contracts(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None,
    reference_source_root: str | pathlib.Path | None,
    donor_clients: Iterable[str] | None = None,
    classes: Iterable[str] = TARGET_CLASSES,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    current_tree, reference_tree = require_source_trees(
        project_root,
        source_root=source_root,
        reference_source_root=reference_source_root,
        require_current=True,
        require_reference=True,
    )
    assert current_tree is not None and reference_tree is not None

    wanted = tuple(dict.fromkeys(classes))
    unknown = [x for x in wanted if x not in TARGET_CLASSES]
    if unknown:
        raise ValueError(f'UNSUPPORTED_PLAYER_CLASS:{unknown}; supported={TARGET_CLASSES}')

    if progress:
        progress('parsing reference skill catalog')
    skills = [x for x in parse_reference_skill_catalog(reference_tree, wanted) if x['class'] in wanted]
    if progress:
        progress('scanning EU reference source evidence')
    reference_ev = scan_source_evidence(reference_tree, skill_catalog=skills)
    reference_handler_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    infrastructure_handler_aliases = {
        'SKILLMANAGERHANDLER', 'TIMERSKILLHANDLER', 'SETTINGSHANDLER',
        'DAMAGEHANDLER', 'CHARACTERGAME', 'ITEMHANDLER', 'QUESTGAME',
        'PARTYHANDLER', 'SOUNDHANDLER',
    }
    for case in reference_ev.get('skill_cases', []):
        cls = str(case.get('class') or '')
        skill_name = str(case.get('skill_name') or '')
        if not cls or not skill_name:
            continue
        for delegate in case.get('delegates', []):
            token = str(delegate or '').strip()
            if not token or token.upper() in infrastructure_handler_aliases:
                continue
            reference_handler_owners[token.casefold()].add((cls, skill_name))
    reference_handler_aliases = {
        key: next(iter(owners))
        for key, owners in reference_handler_owners.items()
        if len(owners) == 1
    }
    if progress:
        progress('scanning current source evidence')
    current_ev = scan_source_evidence(
        current_tree, skill_catalog=skills, skill_handler_aliases=reference_handler_aliases,
    )

    # Some working Summit client trees dispatch visual/audio work through
    # generic helper functions rather than a function/case whose identifier
    # contains the skill name.  Bridge those *current client runtime* calls
    # back to a T5 skill only when the asset identity is unambiguous:
    #   1) exact token/path/sound identity is unique to one reference T5 skill;
    #      or
    #   2) the current asset name itself contains one unique canonical T5 skill
    #      alias (e.g. RisingSlash1.part -> RisingSlash).
    # The current source call remains the runtime authority.  Reference source
    # is used only for unique attribution; reference-only assets are never
    # promoted by this bridge.
    tier_by_skill = {
        (str(row.get('class') or ''), str(row.get('skill_name') or '')): int(row.get('tier') or 0)
        for row in skills
    }
    t5_alias_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for (cls, skill_name), tier in tier_by_skill.items():
        if tier == 5:
            key = ''.join(ch for ch in skill_name.casefold() if ch.isalnum())
            if key:
                t5_alias_owners[key].add((cls, skill_name))
    # Historical handler spellings are also safe name aliases when the EU
    # reference maps that handler uniquely to one T5 skill.  This catches
    # long-lived spellings such as SesmicImpactHandler -> SeismicImpact while
    # still requiring an actual current-client asset call before attribution.
    for handler_key, owner in reference_handler_aliases.items():
        if tier_by_skill.get(owner) != 5:
            continue
        alias = ''.join(ch for ch in str(handler_key).casefold() if ch.isalnum())
        if alias.startswith('c') and len(alias) > 1:
            alias = alias[1:]
        if alias.endswith('handler'):
            alias = alias[:-7]
        if len(alias) >= 6:
            t5_alias_owners[alias].add(owner)

    ref_token_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    ref_part_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    ref_part_basename_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    ref_sound_symbol_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    ref_sound_code_owners: dict[int, set[tuple[str, str]]] = collections.defaultdict(set)
    ref_sound_path_owners: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for case in reference_ev.get('skill_cases', []):
        owner = (str(case.get('class') or ''), str(case.get('skill_name') or ''))
        if tier_by_skill.get(owner) != 5 or str(case.get('layer') or '') != 'CLIENT_RUNTIME':
            continue
        for token in case.get('effect_tokens', []):
            token = str(token or '').strip()
            if token:
                ref_token_owners[token.casefold()].add(owner)
        for logical in case.get('particle_literals', []):
            logical = str(logical or '').replace('\\', '/').strip()
            if logical:
                ref_part_owners[logical.casefold()].add(owner)
                ref_part_basename_owners[pathlib.PurePosixPath(logical).name.casefold()].add(owner)
        for sound in case.get('sounds', []):
            symbol = str(sound.get('symbol') or '').strip()
            code = sound.get('code')
            path = str(sound.get('path') or '').replace('\\', '/').strip()
            if symbol:
                ref_sound_symbol_owners[symbol.casefold()].add(owner)
            if isinstance(code, int):
                ref_sound_code_owners[code].add(owner)
            if path:
                ref_sound_path_owners[path.casefold()].add(owner)

    def _name_alias_owners(value: str) -> set[tuple[str, str]]:
        key = ''.join(ch for ch in str(value).casefold() if ch.isalnum())
        out: set[tuple[str, str]] = set()
        for alias, owners in t5_alias_owners.items():
            # Short aliases are too collision-prone for an authorization bridge.
            if len(alias) >= 6 and alias in key:
                out.update(owners)
        return out

    target = PhysicalSource('SUMMIT_CLIENT', client_root)
    donors = [PhysicalSource(label, root) for label, root in _parse_donor_specs(donor_clients)]
    # Preload hints need the same conservative physical resolver as contract
    # assets, but they never create runtime edges. Build indexes once here.
    _ = target.resolver.index
    for d in donors:
        _ = d.resolver.index

    bridged_cases: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    preload_hints: list[dict[str, Any]] = []
    seen_preload_hints: set[tuple[str, str, str, str]] = set()
    existing_current_token_calls: set[tuple[str, str, str, str]] = set()
    existing_current_part_calls: set[tuple[str, str, str, str]] = set()
    existing_current_sound_calls: set[tuple[str, str, str, str]] = set()
    for case in current_ev.get('skill_cases', []):
        owner = (str(case.get('class') or ''), str(case.get('skill_name') or ''))
        rel = str(case.get('source_file') or '')
        if not owner[0] or not owner[1] or str(case.get('layer') or '') != 'CLIENT_RUNTIME':
            continue
        for token in case.get('effect_tokens', []):
            existing_current_token_calls.add((owner[0], owner[1].casefold(), rel, str(token).casefold()))
        for logical in case.get('particle_literals', []):
            existing_current_part_calls.add((owner[0], owner[1].casefold(), rel, str(logical).replace('\\', '/').casefold()))
        for sound in case.get('sounds', []):
            skey = str(sound.get('path') or sound.get('symbol') or sound.get('code') or '').casefold()
            if skey:
                existing_current_sound_calls.add((owner[0], owner[1].casefold(), rel, skey))

    for probe in current_ev.get('runtime_asset_call_probes', []):
        if str(probe.get('layer') or '') != 'CLIENT_RUNTIME':
            continue
        rel = str(probe.get('source_file') or '')
        line = int(probe.get('source_line') or 0)
        function = str(probe.get('function') or '')

        def ensure_case(owner: tuple[str, str], basis: str) -> dict[str, Any]:
            key = (owner[0], owner[1], rel, line, basis)
            row = bridged_cases.get(key)
            if row is None:
                row = {
                    'class': owner[0], 'skill_name': owner[1], 'sounds': [],
                    'effect_tokens': [], 'particle_literals': [], 'animations': [], 'delegates': [],
                    'source_id': current_tree.source_id, 'source_file': rel, 'source_line': line,
                    'scope_basis': basis, 'layer': 'CLIENT_RUNTIME', 'function': function,
                }
                bridged_cases[key] = row
            return row

        for token in probe.get('effect_tokens', []):
            token = str(token or '').strip()
            owners = set(ref_token_owners.get(token.casefold(), ()))
            basis = 'CURRENT_CLIENT_REFERENCE_UNIQUE_EFFECT_TOKEN'
            if not owners:
                owners = _name_alias_owners(token)
                basis = 'CURRENT_CLIENT_ASSET_NAME_SKILL_ALIAS'
            if len(owners) == 1:
                owner = next(iter(owners))
                if (owner[0], owner[1].casefold(), rel, token.casefold()) in existing_current_token_calls:
                    continue
                row = ensure_case(owner, basis)
                if token not in row['effect_tokens']:
                    row['effect_tokens'].append(token)

        for logical in probe.get('particle_literals', []):
            logical = str(logical or '').replace('\\', '/').strip()
            owners = set(ref_part_owners.get(logical.casefold(), ()))
            if not owners:
                owners = set(ref_part_basename_owners.get(pathlib.PurePosixPath(logical).name.casefold(), ()))
            basis = 'CURRENT_CLIENT_REFERENCE_UNIQUE_PARTICLE_LITERAL'
            if not owners:
                owners = _name_alias_owners(pathlib.PurePosixPath(logical).name)
                basis = 'CURRENT_CLIENT_ASSET_NAME_SKILL_ALIAS'
            if len(owners) == 1:
                owner = next(iter(owners))
                if (owner[0], owner[1].casefold(), rel, logical.casefold()) in existing_current_part_calls:
                    continue
                row = ensure_case(owner, basis)
                if logical not in row['particle_literals']:
                    row['particle_literals'].append(logical)

        for logical in probe.get('particle_preload_literals', []):
            logical = str(logical or '').replace('\\', '/').strip()
            owners = set(ref_part_owners.get(logical.casefold(), ()))
            if not owners:
                owners = set(ref_part_basename_owners.get(pathlib.PurePosixPath(logical).name.casefold(), ()))
            basis = 'CURRENT_CLIENT_PRELOAD_REFERENCE_UNIQUE_PARTICLE_LITERAL'
            if not owners:
                owners = _name_alias_owners(pathlib.PurePosixPath(logical).name)
                basis = 'CURRENT_CLIENT_PRELOAD_ASSET_NAME_SKILL_ALIAS'
            if len(owners) == 1:
                owner = next(iter(owners))
                pkey = (owner[0], owner[1].casefold(), rel, logical.casefold())
                if pkey in seen_preload_hints:
                    continue
                seen_preload_hints.add(pkey)
                resolution = _resolve_asset(logical, target, donors, basename_only=False)
                preload_hints.append({
                    'class': owner[0], 'skill_name': owner[1], 'logical_path': logical,
                    'source_id': current_tree.source_id, 'source_file': rel, 'source_line': line,
                    'function': function, 'scope_basis': basis, 'layer': 'CLIENT_RUNTIME',
                    'resolution': resolution.to_dict(),
                    'authorization': 'DIAGNOSTIC_ONLY_PRELOAD_IS_NOT_ACTIVATION',
                })

        for sound in probe.get('sounds', []):
            symbol = str(sound.get('symbol') or '').strip()
            code = sound.get('code')
            path = str(sound.get('path') or '').replace('\\', '/').strip()

            # A globally-unique sound identity in the reference is not enough
            # to attribute an arbitrary current client call to a T5 skill.
            # Common UI/gameplay sounds can be reused all over the client and
            # would otherwise create false skill bindings (e.g. potion sounds).
            # Require current call-site/asset context that independently names
            # the T5 skill, then use the reference identity only as a
            # consistency check.
            alias_owners = _name_alias_owners(pathlib.PurePosixPath(path).name if path else symbol)
            if not alias_owners:
                alias_owners.update(_name_alias_owners(function))
            if not alias_owners:
                alias_owners.update(_name_alias_owners(pathlib.PurePosixPath(rel).stem))

            identity_owners: set[tuple[str, str]] = set()
            if symbol:
                identity_owners.update(ref_sound_symbol_owners.get(symbol.casefold(), ()))
            if isinstance(code, int):
                identity_owners.update(ref_sound_code_owners.get(code, ()))
            if path:
                identity_owners.update(ref_sound_path_owners.get(path.casefold(), ()))

            owners: set[tuple[str, str]] = set(alias_owners)
            basis = 'CURRENT_CLIENT_ASSET_NAME_SKILL_ALIAS'
            if owners and identity_owners:
                owners = owners & identity_owners
                basis = 'CURRENT_CLIENT_CONTEXT_REFERENCE_SOUND'
            if len(owners) == 1:
                owner = next(iter(owners))
                skey = str(path or symbol or code or '').casefold()
                if skey and (owner[0], owner[1].casefold(), rel, skey) in existing_current_sound_calls:
                    continue
                row = ensure_case(owner, basis)
                if sound not in row['sounds']:
                    row['sounds'].append(sound)

    if bridged_cases:
        existing_case_keys = {
            (str(x.get('class') or ''), str(x.get('skill_name') or '').casefold(),
             str(x.get('source_file') or ''), int(x.get('source_line') or 0),
             str(x.get('scope_basis') or ''))
            for x in current_ev.get('skill_cases', [])
        }
        for row in bridged_cases.values():
            key = (
                str(row.get('class') or ''), str(row.get('skill_name') or '').casefold(),
                str(row.get('source_file') or ''), int(row.get('source_line') or 0),
                str(row.get('scope_basis') or ''),
            )
            if key not in existing_case_keys:
                current_ev.setdefault('skill_cases', []).append(row)
                existing_case_keys.add(key)
                current_ev.setdefault('class_skill_mentions', []).append({
                    'class': row['class'], 'skill_name': row['skill_name'], 'layer': 'CLIENT_RUNTIME',
                    'source_id': current_tree.source_id, 'source_file': row['source_file'],
                    'source_line': row['source_line'], 'scope_basis': row['scope_basis'],
                })
                for token in row.get('effect_tokens', []):
                    current_ev.setdefault('effect_tokens', []).append({
                        'class': row['class'], 'skill_name': row['skill_name'], 'token': token,
                        'source_file': row['source_file'], 'source_line': row['source_line'],
                        'scope_basis': row['scope_basis'],
                    })
    reference_sound_symbol_to_code = {
        str(k): int(v) for k, v in (reference_ev.get('sound_symbol_to_code') or {}).items()
        if str(k) and isinstance(v, int)
    }
    reference_sound_symbol_to_path = {
        str(k): str(v) for k, v in (reference_ev.get('sound_symbol_to_path') or {}).items()
        if str(k) and str(v)
    }
    if progress:
        progress('parsing motion skill registries')
    current_motion_registry = parse_skill_motion_registry(current_tree)
    reference_motion_registry = parse_skill_motion_registry(reference_tree)
    # Parse all class config literals once.  The all-class audit otherwise
    # rescans the full reference source tree once per class.
    reference_class_configs = parse_reference_class_configs(reference_tree, wanted)
    configs_by_class = collections.defaultdict(list)
    for cfg in reference_class_configs:
        configs_by_class[cfg['class']].append(cfg)

    graph = ContractGraph()
    class_reports: list[dict[str, Any]] = []
    motion_reports: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    status_counts = collections.Counter()

    ref_cases_by_key: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for case in reference_ev.get('skill_cases', []):
        ref_cases_by_key[(str(case.get('class')), str(case.get('skill_name')))].append(case)
    current_cases_by_key: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for case in current_ev.get('skill_cases', []):
        current_cases_by_key[(str(case.get('class')), str(case.get('skill_name')))].append(case)
    current_probes_by_key: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for probe in current_ev.get('skill_alias_probes', []):
        current_probes_by_key[(str(probe.get('class')), str(probe.get('skill_name')))].append(probe)

    ref_parts_by_class = reference_ev.get('class_parts', {})

    for class_name in wanted:
        class_node = _class_node_id(class_name)
        runtime_state = _runtime_class_state(class_name, current_ev)
        graph.ensure_node(class_node, 'PLAYER_CLASS', class_name, **runtime_state)
        class_skill_rows = [x for x in skills if x['class'] == class_name]
        class_skill_names = [x['skill_name'] for x in class_skill_rows]
        current_coverage = _source_skill_coverage(class_name, class_skill_names, current_ev)
        reference_coverage = _source_skill_coverage(class_name, class_skill_names, reference_ev)
        reference_contract_state = _reference_contract_state(reference_coverage)
        migration_state = _migration_state(runtime_state, current_coverage, reference_coverage)
        class_assets: list[dict[str, Any]] = []
        skill_contract_rows: list[dict[str, Any]] = []

        for skill in class_skill_rows:
            skill_node = _skill_node_id(class_name, skill['skill_id'])
            graph.ensure_node(
                skill_node, 'SKILL', skill['skill_name'],
                class_name=class_name, tier=skill['tier'], skill_id=skill['skill_id'], button_base=skill['button_base'],
            )
            graph.connect(
                class_node, skill_node, 'HAS_SKILL',
                evidence=f"{skill['source_id']}:{skill['source_file']}:{skill['source_line']}",
                confidence=1.0, required=True, status='REFERENCE_PROVEN',
            )

            expectations: list[tuple[str, str, bool, str]] = []
            if skill['button_normal']:
                expectations.append(('SKILL_BUTTON_NORMAL', skill['button_normal'], False, 'REFERENCE_SKILL_TABLE'))
            if skill['button_hover']:
                expectations.append(('SKILL_BUTTON_HOVER', skill['button_hover'], False, 'REFERENCE_SKILL_TABLE'))
            if skill['explicit_tga']:
                expectations.append(('SKILL_TIMER_TGA', skill['explicit_tga'], True, 'REFERENCE_SKILL_TABLE_EXPLICIT_TGA'))

            # Direct sound/effect/animation evidence from both the current Summit
            # source and the EU reference. Current runtime evidence is authoritative
            # for reachability; reference evidence remains useful for migration gaps.
            current_runtime_cases = [
                case for case in current_cases_by_key.get((class_name, skill['skill_name']), [])
                if str(case.get('layer') or 'CLIENT_RUNTIME') in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}
            ]
            current_alias_probes = [
                probe for probe in current_probes_by_key.get((class_name, skill['skill_name']), [])
                if str(probe.get('layer') or '') in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}
            ]
            graph.ensure_node(
                skill_node, 'SKILL', skill['skill_name'],
                current_runtime_case_count=len(current_runtime_cases),
                current_runtime_case_evidence=[
                    {
                        'source_file': str(case.get('source_file') or ''),
                        'source_line': int(case.get('source_line') or 0),
                        'scope_basis': str(case.get('scope_basis') or ''),
                        'effect_token_count': len(case.get('effect_tokens') or []),
                        'particle_literal_count': len(case.get('particle_literals') or []),
                    }
                    for case in current_runtime_cases
                ],
                current_skill_alias_probe_count=len(current_alias_probes),
                current_skill_alias_probes=[
                    {
                        'source_file': str(probe.get('source_file') or ''),
                        'source_line': int(probe.get('source_line') or 0),
                        'function': str(probe.get('function') or ''),
                        'has_runtime_effect_evidence': bool(probe.get('has_runtime_effect_evidence')),
                        'has_runtime_audio_evidence': bool(probe.get('has_runtime_audio_evidence')),
                        'sound_count': len(probe.get('sounds') or []),
                    }
                    for probe in current_alias_probes
                ],
            )
            combined_cases = [
                ('CURRENT_HANDLER', case) for case in current_runtime_cases
            ] + [
                ('REFERENCE_HANDLER', case)
                for case in ref_cases_by_key.get((class_name, skill['skill_name']), [])
                if str(case.get('layer') or 'CLIENT_RUNTIME') in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}
            ]
            resolved_effect_tokens: set[str] = set()
            for evidence_kind, case in combined_cases:
                for sound in case.get('sounds', []):
                    sound_path = str(sound.get('path') or '')
                    sound_symbol = str(sound.get('symbol') or '')
                    sound_code = sound.get('code')
                    sound_evidence = f"{evidence_kind}:{case['source_file']}:{case['source_line']}"
                    # A current SkillPlaySound symbol may resolve through the EU/reference
                    # sound table only when the numeric code is identical.  The current
                    # call remains the runtime authority; the reference contributes only
                    # the code->WAV mapping.
                    if (not sound_path and evidence_kind == 'CURRENT_HANDLER' and sound_symbol
                            and isinstance(sound_code, int)
                            and reference_sound_symbol_to_code.get(sound_symbol) == sound_code
                            and reference_sound_symbol_to_path.get(sound_symbol)):
                        sound_path = reference_sound_symbol_to_path[sound_symbol]
                        sound_evidence += ':REFERENCE_SOUND_CODE_MATCH'
                    if sound_path:
                        expectations.append(('SKILL_AUDIO', sound_path, False, sound_evidence))
                    elif sound_symbol:
                        graph.ensure_node('SOUND_SYMBOL:' + sound_symbol, 'SOUND_SYMBOL', sound_symbol, code=sound_code)
                        graph.connect(
                            skill_node, 'SOUND_SYMBOL:' + sound_symbol, 'PLAYS_SOUND',
                            evidence=f"{case['source_id']}:{case['source_file']}:{case['source_line']}",
                            confidence=1.0, required=None,
                            status='CURRENT_RUNTIME_SYMBOL_UNRESOLVED' if evidence_kind == 'CURRENT_HANDLER' else 'SOURCE_PROVEN_SYMBOLIC',
                        )
                for token in case.get('effect_tokens', []):
                    token = str(token).strip()
                    if not token:
                        continue
                    token_node = f'EFFECT_TOKEN:{token.casefold()}'
                    graph.ensure_node(token_node, 'EFFECT_TOKEN', token)
                    graph.connect(
                        skill_node, token_node, 'USES_EFFECT_TOKEN',
                        evidence=f"{case['source_id']}:{case['source_file']}:{case['source_line']}",
                        confidence=1.0, required=None,
                        status='CURRENT_RUNTIME_TOKEN' if evidence_kind == 'CURRENT_HANDLER' else 'REFERENCE_PROVEN_SYMBOLIC',
                    )
                    # HoNewParticleResMgr::LoadScript strips directory+extension and
                    # registers the basename; HoNewParticleMgr::Start looks up that
                    # same token with FindScript.  Therefore TOKEN -> <token>.part is
                    # a proven runtime resolution rule, while physical selection still
                    # fails closed when donors are ambiguous.
                    token_key = token.casefold()
                    if token_key not in resolved_effect_tokens:
                        resolved_effect_tokens.add(token_key)
                        part_logical = token + '.part'
                        resolution = _resolve_asset(part_logical, target, donors, basename_only=True)
                        part_node = _asset_node_id(part_logical)
                        graph.ensure_node(
                            part_node, 'ASSET', token + '.part',
                            logical_path=part_logical, asset_role='EFFECT_PARTICLE_SCRIPT', resolution=resolution.to_dict(),
                        )
                        graph.connect(
                            token_node, part_node, 'RESOLVES_PARTICLE_SCRIPT',
                            evidence='HoNewParticleResMgr::LoadScript basename registry + HoNewParticleMgr::Start/FindScript',
                            confidence=1.0, required=True, status=resolution.status,
                        )
                        status_counts[resolution.status] += 1
                        part_row = {
                            'class': class_name, 'tier': skill['tier'], 'skill_id': skill['skill_id'],
                            'skill_name': skill['skill_name'], 'role': 'EFFECT_PARTICLE_SCRIPT',
                            'evidence': 'CURRENT_RUNTIME_PARTICLE_REGISTRY' if evidence_kind == 'CURRENT_HANDLER' else 'REFERENCE_PARTICLE_REGISTRY',
                            **resolution.to_dict(),
                        }
                        class_assets.append(part_row)
                        asset_rows.append(part_row)
                        if resolution.physical_path:
                            closure = _part_dependency_closure(resolution, target, donors)
                            part_row['dependency_count'] = len(closure)
                            part_row['dependency_status_counts'] = dict(collections.Counter(x.get('status') for x in closure))
                            for dep in closure:
                                dep_logical = str(dep.get('reference') or '')
                                if not dep_logical:
                                    continue
                                dep_node = _asset_node_id(dep_logical)
                                graph.ensure_node(
                                    dep_node, 'ASSET', pathlib.PurePosixPath(dep_logical).name,
                                    logical_path=dep_logical, asset_role='PARTICLE_DEPENDENCY',
                                    resolution={k: dep.get(k) for k in ('status','source_label','physical_path','match_mode','candidates')},
                                )
                                graph.connect(
                                    part_node, dep_node, 'TRANSITIVE_REFERENCE',
                                    evidence='PT_PARTICLE_PART_READONLY_V2', confidence=1.0,
                                    required=True, status=str(dep.get('status') or 'EVIDENCE_ONLY'), depth=dep.get('depth'),
                                )
                for particle_literal in case.get('particle_literals', []):
                    logical = str(particle_literal or '').strip()
                    if logical:
                        expectations.append((
                            'SKILL_PARTICLE', logical, False,
                            f"{evidence_kind}:{case['source_file']}:{case['source_line']}",
                        ))
                for animation in case.get('animations', []):
                    animation_node = f'ANIMATION_TOKEN:{str(animation).casefold()}'
                    graph.ensure_node(animation_node, 'ANIMATION_TOKEN', str(animation))
                    graph.connect(
                        skill_node, animation_node, 'USES_ANIMATION_TYPE',
                        evidence=f"{case['source_id']}:{case['source_file']}:{case['source_line']}",
                        confidence=1.0, required=None, status='SOURCE_PROVEN_SYMBOLIC',
                    )
                for delegate in case.get('delegates', []):
                    delegate_node = f'HANDLER:{str(delegate).casefold()}'
                    graph.ensure_node(delegate_node, 'RUNTIME_HANDLER', str(delegate))
                    graph.connect(
                        skill_node, delegate_node, 'DELEGATES_TO_HANDLER',
                        evidence=f"{case['source_id']}:{case['source_file']}:{case['source_line']}",
                        confidence=1.0, required=None, status='SOURCE_PROVEN_SYMBOLIC',
                    )

            # Class LoadParticle literals can be tied to a skill when the filename
            # contains the skill name (Alas/Inpes/Migal are real reference examples).
            skill_tokens = {skill['skill_name'].casefold(), skill['skill_name'].replace('Advent', '').casefold()}
            for part in ref_parts_by_class.get(class_name, []):
                stem = pathlib.PurePosixPath(str(part.get('value') or '')).stem.casefold()
                if any(tok and tok in stem for tok in skill_tokens):
                    expectations.append((
                        'SKILL_PARTICLE', str(part['value']), False,
                        f"REFERENCE_HANDLER:{part['source_file']}:{part['line']}",
                    ))

            seen_expectations: set[tuple[str, str]] = set()
            for role, logical, basename_only, evidence in expectations:
                ek = (role, logical.casefold())
                if ek in seen_expectations:
                    continue
                seen_expectations.add(ek)
                resolution = _resolve_asset(logical, target, donors, basename_only=basename_only)
                status_counts[resolution.status] += 1
                asset_node = _asset_node_id(logical)
                graph.ensure_node(
                    asset_node, 'ASSET', pathlib.PurePosixPath(logical).name,
                    logical_path=logical, asset_role=role, resolution=resolution.to_dict(),
                )
                required = True if role in {'SKILL_BUTTON_NORMAL', 'SKILL_BUTTON_HOVER'} else None
                graph.connect(
                    skill_node, asset_node, 'REQUIRES_ASSET', evidence=evidence,
                    confidence=1.0 if evidence.startswith('REFERENCE_') else 0.95,
                    required=required, status=resolution.status,
                )
                row = {
                    'class': class_name,
                    'tier': skill['tier'],
                    'skill_id': skill['skill_id'],
                    'skill_name': skill['skill_name'],
                    'role': role,
                    'evidence': evidence,
                    **resolution.to_dict(),
                }
                class_assets.append(row)
                asset_rows.append(row)

                if role == 'SKILL_PARTICLE' and resolution.physical_path:
                    closure = _part_dependency_closure(resolution, target, donors)
                    row['dependency_count'] = len(closure)
                    row['dependency_status_counts'] = dict(collections.Counter(x.get('status') for x in closure))
                    for dep in closure:
                        dep_logical = str(dep.get('reference') or '')
                        if not dep_logical:
                            continue
                        dep_node = _asset_node_id(dep_logical)
                        graph.ensure_node(
                            dep_node, 'ASSET', pathlib.PurePosixPath(dep_logical).name,
                            logical_path=dep_logical, asset_role='PARTICLE_DEPENDENCY', resolution={k: dep.get(k) for k in (
                                'status', 'source_label', 'physical_path', 'match_mode', 'candidates'
                            )},
                        )
                        graph.connect(
                            asset_node, dep_node, 'TRANSITIVE_REFERENCE',
                            evidence='PT_PARTICLE_PART_READONLY_V2', confidence=1.0,
                            required=None, status=str(dep.get('status') or 'EVIDENCE_ONLY'), depth=dep.get('depth'),
                        )

        # The reference source contains a class-reserved sound family that is
        # broader than the explicit SkillPlaySound calls visible in C++ handlers.
        # Audit every WAV in that proven range; keep it class-level when the exact
        # skill binding is not source-proven.
        class_audio_inventory = _class_audio_family(class_name, reference_ev)
        already_audio = {
            str(x.get('logical_path') or '').casefold()
            for x in class_assets if x.get('role') == 'SKILL_AUDIO'
        }
        for audio in class_audio_inventory:
            logical = str(audio['path'])
            if logical.casefold() in already_audio:
                continue
            resolution = _resolve_asset(logical, target, donors, basename_only=False)
            status_counts[resolution.status] += 1
            asset_node = _asset_node_id(logical)
            graph.ensure_node(
                asset_node, 'ASSET', pathlib.PurePosixPath(logical).name,
                logical_path=logical, asset_role='CLASS_AUDIO', resolution=resolution.to_dict(),
                sound_code=audio['code'], sound_code_hex=audio['code_hex'],
            )
            graph.connect(
                class_node, asset_node, 'HAS_CLASS_AUDIO_FAMILY',
                evidence=f"REFERENCE_SOUND_RANGE:{audio['range_start_symbol']}:{audio['range_end_symbol']}",
                confidence=1.0, required=None, status=resolution.status,
                sound_code=audio['code'], sound_code_hex=audio['code_hex'],
            )
            row = {
                'class': class_name,
                'tier': None,
                'skill_id': '',
                'skill_name': '',
                'role': 'CLASS_AUDIO',
                'evidence': f"REFERENCE_SOUND_RANGE:{audio['range_start_symbol']}:{audio['range_end_symbol']}",
                'sound_code': audio['code'],
                'sound_code_hex': audio['code_hex'],
                **resolution.to_dict(),
            }
            class_assets.append(row)
            asset_rows.append(row)

        for skill in class_skill_rows:
            direct_cases = [
                case for case in ref_cases_by_key.get((class_name, skill['skill_name']), [])
                if str(case.get('layer') or 'CLIENT_RUNTIME') in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}
            ]
            current_direct_cases = [
                case for case in current_cases_by_key.get((class_name, skill['skill_name']), [])
                if str(case.get('layer') or 'CLIENT_RUNTIME') in {'CLIENT_RUNTIME', 'SERVER_RUNTIME'}
            ]
            roles = sorted({
                x['role'] for x in class_assets if x['skill_id'] == skill['skill_id']
            })
            effect_tokens = sorted({
                str(token)
                for case in direct_cases
                for token in case.get('effect_tokens', [])
            }, key=str.casefold)
            current_effect_tokens = sorted({
                str(token)
                for case in current_direct_cases
                for token in case.get('effect_tokens', [])
            }, key=str.casefold)
            animations = sorted({
                str(token)
                for case in direct_cases
                for token in case.get('animations', [])
            }, key=str.casefold)
            current_animations = sorted({
                str(token)
                for case in current_direct_cases
                for token in case.get('animations', [])
            }, key=str.casefold)
            delegates = sorted({
                str(token)
                for case in direct_cases
                for token in case.get('delegates', [])
            }, key=str.casefold)
            sounds = sorted({
                str(sound.get('path') or sound.get('symbol') or sound.get('code') or '')
                for case in direct_cases
                for sound in case.get('sounds', [])
                if sound.get('path') or sound.get('symbol') or sound.get('code') is not None
            }, key=str.casefold)
            current_sounds = sorted({
                str(sound.get('path') or sound.get('symbol') or sound.get('code') or '')
                for case in current_direct_cases
                for sound in case.get('sounds', [])
                if sound.get('path') or sound.get('symbol') or sound.get('code') is not None
            }, key=str.casefold)
            skill_contract_rows.append({
                'skill_id': skill['skill_id'],
                'skill_name': skill['skill_name'],
                'tier': skill['tier'],
                'tier_slot': skill.get('tier_slot'),
                'class_ordinal': skill.get('class_ordinal'),
                'reference_client_runtime_mentioned': skill['skill_name'] in set(reference_coverage['client_runtime_skills']),
                'reference_server_runtime_mentioned': skill['skill_name'] in set(reference_coverage['server_runtime_skills']),
                'current_client_runtime_mentioned': skill['skill_name'] in set(current_coverage['client_runtime_skills']),
                'current_server_runtime_mentioned': skill['skill_name'] in set(current_coverage['server_runtime_skills']),
                'asset_roles_discovered': roles,
                'direct_sound_evidence': sounds,
                'current_direct_sound_evidence': current_sounds,
                'effect_tokens': effect_tokens,
                'current_effect_tokens': current_effect_tokens,
                'animation_tokens': animations,
                'current_animation_tokens': current_animations,
                'delegated_handlers': delegates,
                'reference_case_count': len(direct_cases),
                'current_case_count': len(current_direct_cases),
            })

        if progress:
            progress(f'{class_name} building class motion contract')
        motion_contract = audit_class_motion_contract(
            project_root, reference_tree, class_name, target, donors, graph,
            skill_contracts=skill_contract_rows,
            class_configs=configs_by_class.get(class_name, ()),
            reference_motion_registry=reference_motion_registry,
            current_motion_registry=current_motion_registry,
            progress=progress,
        )
        # Reference-registry drift is a migration blocker for jobs that are
        # not enabled yet (Assassin/Shaman in the current Summit tree), but it
        # is not a blocker for an already-running legacy job.  Those classes
        # prove their selectability by the current runtime itself.
        raw_registry_status = str(motion_contract.get('runtime_motion_selectability_status') or '')
        if runtime_state.get('status') == 'RUNTIME_JOB_ENABLED' and raw_registry_status in {
            'CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES',
            'CURRENT_REGISTRY_PARTIAL_INDEX_ALIGNMENT',
        }:
            motion_contract['runtime_motion_selectability_effective_status'] = 'CURRENT_RUNTIME_ESTABLISHED_REFERENCE_DRIFT_NONBLOCKING'
            motion_contract['reference_registry_drift_nonblocking'] = True
        else:
            motion_contract['runtime_motion_selectability_effective_status'] = raw_registry_status
            motion_contract['reference_registry_drift_nonblocking'] = False
        motion_reports.append(motion_contract)
        graph.ensure_node(
            class_node, 'PLAYER_CLASS', class_name,
            motion_contract_status=motion_contract.get('status'),
            dominant_motion_root=motion_contract.get('dominant_motion_root'),
            dominant_motion_smb=motion_contract.get('dominant_motion_smb'),
        )

        class_counts = collections.Counter(x['status'] for x in class_assets)
        role_counts: dict[str, dict[str, int]] = {}
        for role in sorted({x['role'] for x in class_assets}):
            role_counts[role] = dict(collections.Counter(x['status'] for x in class_assets if x['role'] == role))

        proven_assets_complete = all(
            x['status'] == 'PRESENT_TARGET'
            for x in class_assets
            if x['role'] in {'SKILL_BUTTON_NORMAL', 'SKILL_BUTTON_HOVER'}
        )
        if migration_state == 'RUNTIME_BLOCKED_MAX_JOBNUM':
            overall = migration_state
        elif migration_state in {'RUNTIME_CLASS_IMPLEMENTATION_MISSING', 'RUNTIME_CLASS_IMPLEMENTATION_PARTIAL'}:
            overall = migration_state
        elif not proven_assets_complete:
            overall = 'PROVEN_REQUIRED_ASSETS_INCOMPLETE'
        elif reference_contract_state != 'REFERENCE_CLIENT_SERVER_SOURCE_COMPLETE':
            # Enabled legacy classes may use source layouts that the modern
            # handler scanner cannot fully attribute.  Report partial discovery
            # without downgrading them to "implementation missing".
            overall = 'RUNTIME_ESTABLISHED_CONTRACT_DISCOVERY_PARTIAL' if runtime_state.get('status') == 'RUNTIME_JOB_ENABLED' else 'CONTRACT_DISCOVERY_PARTIAL'
        else:
            overall = 'PROVEN_CONTRACT_COMPLETE'

        class_reports.append({
            'class': class_name,
            'skill_count': len(class_skill_rows),
            'overall_status': overall,
            'runtime_source': runtime_state,
            'source_contract': {
                'reference_state': reference_contract_state,
                'migration_state': migration_state,
                'current': current_coverage,
                'reference': reference_coverage,
            },
            'class_audio_inventory': {
                'reference_sound_count': len(class_audio_inventory),
                'range_anchor_symbols': list(CLASS_SOUND_RANGE_ANCHORS.get(class_name, ())),
                'paths': [x['path'] for x in class_audio_inventory],
            },
            'motion_contract': motion_contract,
            'asset_expectation_count': len(class_assets),
            'asset_status_counts': dict(class_counts),
            'role_status_counts': role_counts,
            'proven_required_assets_complete': proven_assets_complete,
            # Backward-compatible name retained, but deliberately scoped to
            # proven required assets.  It MUST NOT be interpreted as class completeness.
            'complete_for_proven_required_assets': proven_assets_complete,
            'skill_contracts': skill_contract_rows,
        })

    out_dir = project_root / 'pt_build' / 'asset_contracts'
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / 'player_class_contract_graph.json'
    result_path = out_dir / 'player_class_contract_census.json'
    motion_path = out_dir / 'player_class_motion_contracts.json'

    metadata = {
        'target_client_root': str(client_root),
        'current_source': source_tree_summary(current_tree),
        'reference_source': source_tree_summary(reference_tree),
        'donor_clients': [{'label': d.label, 'root': str(d.root)} for d in donors],
        'classes': list(wanted),
        'current_runtime_asset_call_probe_count': len(current_ev.get('runtime_asset_call_probes', [])),
        'current_client_asset_call_probe_count': sum(
            1 for x in current_ev.get('runtime_asset_call_probes', [])
            if str(x.get('layer') or '') == 'CLIENT_RUNTIME'
        ),
        'current_server_asset_call_probe_count': sum(
            1 for x in current_ev.get('runtime_asset_call_probes', [])
            if str(x.get('layer') or '') == 'SERVER_RUNTIME'
        ),
        'current_runtime_asset_call_probes': current_ev.get('runtime_asset_call_probes', []),
        'current_runtime_audio_call_probe_count': len(current_ev.get('runtime_audio_call_probes', [])),
        'current_client_audio_call_probe_count': sum(
            1 for x in current_ev.get('runtime_audio_call_probes', [])
            if str(x.get('layer') or '') == 'CLIENT_RUNTIME'
        ),
        'current_client_unresolved_audio_call_probe_count': sum(
            1 for x in current_ev.get('runtime_audio_call_probes', [])
            if str(x.get('layer') or '') == 'CLIENT_RUNTIME' and not bool(x.get('resolved_identity'))
        ),
        'current_runtime_audio_call_probes': current_ev.get('runtime_audio_call_probes', []),
        'current_runtime_effect_call_probe_count': len(current_ev.get('runtime_effect_call_probes', [])),
        'current_client_effect_call_probe_count': sum(
            1 for x in current_ev.get('runtime_effect_call_probes', [])
            if str(x.get('layer') or '') == 'CLIENT_RUNTIME'
        ),
        'current_client_unresolved_effect_call_probe_count': sum(
            1 for x in current_ev.get('runtime_effect_call_probes', [])
            if str(x.get('layer') or '') == 'CLIENT_RUNTIME' and not bool(x.get('resolved_token'))
        ),
        'current_runtime_effect_call_probes': current_ev.get('runtime_effect_call_probes', []),
        'current_client_particle_preload_hint_count': len(preload_hints),
        'current_t5_particle_preload_hints': preload_hints,
        'current_t5_asset_bridge_case_count': len(bridged_cases),
    }
    graph_path.write_text(json.dumps(graph.to_dict(metadata=metadata), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    motion_payload = {
        'format': 'PT_ASSET_PLAYER_CLASS_MOTION_CONTRACTS_V1',
        'status': 'PASS',
        'classes': motion_reports,
        'hashes_calculated': 0,
        'client_modified': False,
        'server_modified': False,
    }
    motion_path.write_text(json.dumps(motion_payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    result = {
        'format': FORMAT,
        'status': 'PASS',
        'target_client_root': str(client_root),
        'source_roots': metadata,
        'class_count': len(class_reports),
        'skill_count': len(skills),
        'asset_expectation_count': len(asset_rows),
        'asset_status_counts': dict(status_counts),
        'classes': class_reports,
        'assets': asset_rows,
        'graph': str(graph_path),
        'motion_report': str(motion_path),
        'motion_registries': {
            'current': {
                'status': current_motion_registry.get('status'),
                'source_file': current_motion_registry.get('source_file'),
                'registry_kind': current_motion_registry.get('registry_kind'),
                'entry_count': current_motion_registry.get('entry_count'),
                'class_counts': current_motion_registry.get('class_counts', {}),
            },
            'reference': {
                'status': reference_motion_registry.get('status'),
                'source_file': reference_motion_registry.get('source_file'),
                'registry_kind': reference_motion_registry.get('registry_kind'),
                'entry_count': reference_motion_registry.get('entry_count'),
                'class_counts': reference_motion_registry.get('class_counts', {}),
            },
        },
        'report': str(result_path),
        'hashes_calculated': 0,
        'client_modified': False,
        'server_modified': False,
        'production_authorized': False,
        'generation_authorized': False,
        'notes': [
            'Reference-source edges prove relationships, not mandatory runtime requirements unless required=true.',
            'Buttons are treated as proven required UI assets; TGA/audio/particle requirements remain evidence-backed but fail-closed until runtime necessity is certified.',
            'No asset is copied or generated by this audit.',
            'Class completeness is never inferred from asset presence alone; overall_status also considers active current-source migration and reference-source discovery coverage.',
            'Archived/build/dependency source directories are excluded from active runtime evidence.',
            'Player-class motion contracts follow source-proven class configs through verified INX LinkFile targets into MotionInfo state and paired SMB; per-skill MotionInfo record assignment remains fail-closed.',
        ],
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
