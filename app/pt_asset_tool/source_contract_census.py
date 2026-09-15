from __future__ import annotations

import collections
import json
import pathlib
from typing import Any, Callable

from .contract_graph import ContractGraph
from .source_catalog import require_source_trees, source_tree_summary
from .source_evidence import scan_source_evidence, parse_reference_skill_catalog


FORMAT = 'PT_ASSET_SOURCE_CONTRACT_CENSUS_V2'


def _ext(value: str) -> str:
    return pathlib.PurePosixPath(value).suffix.casefold() or '[no_ext]'


def _class_skill_coverage(ev: dict[str, Any], class_name: str) -> dict[str, Any]:
    by_layer: dict[str, set[str]] = collections.defaultdict(set)
    for row in ev.get('class_skill_mentions', []):
        if row.get('class') != class_name:
            continue
        by_layer[str(row.get('layer') or 'UNKNOWN')].add(str(row.get('skill_name') or ''))
    return {
        layer: sorted((x for x in names if x), key=str.casefold)
        for layer, names in sorted(by_layer.items())
    }


def audit_source_contracts(
    project_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None,
    reference_source_root: str | pathlib.Path | None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    current, reference = require_source_trees(
        project_root,
        source_root=source_root,
        reference_source_root=reference_source_root,
        require_current=True,
        require_reference=True,
    )
    assert current is not None and reference is not None

    if progress:
        progress('scan current source')
    cur = scan_source_evidence(current)
    if progress:
        progress('scan EU reference source')
    ref = scan_source_evidence(reference)

    graph = ContractGraph()

    # Sound symbol/code/path relations are strong source evidence.
    for source_id, ev in ((current.source_id, cur), (reference.source_id, ref)):
        symbol_to_code = ev.get('sound_symbol_to_code', {})
        symbol_to_path = ev.get('sound_symbol_to_path', {})
        for symbol, code in symbol_to_code.items():
            sn = f'SOUND_SYMBOL:{symbol}'
            graph.ensure_node(sn, 'SOUND_SYMBOL', symbol, code=code)
            path = symbol_to_path.get(symbol)
            if path:
                an = 'ASSET:' + str(path).casefold()
                graph.ensure_node(an, 'ASSET', pathlib.PurePosixPath(path).name, logical_path=path, asset_role='AUDIO')
                graph.connect(sn, an, 'RESOLVES_TO_AUDIO', evidence=source_id, confidence=1.0, required=None, status='SOURCE_PROVEN')

    # Source-proven runtime templates become reusable contract rules.
    relation_counts = collections.Counter()
    relation_rows = []
    for source_id, ev in ((current.source_id, cur), (reference.source_id, ref)):
        for row in ev.get('format_relations', []):
            relation_counts[str(row.get('relation'))] += 1
            relation_rows.append(dict(row))
            rid = f"RULE:{row.get('relation')}:{str(row.get('template') or row.get('extension') or '').casefold()}"
            graph.ensure_node(rid, 'CONTRACT_RULE', str(row.get('relation')), **{k: v for k, v in row.items() if k not in {'relation'}})

    reference_handler_files = sorted({
        str(x.get('source_file') or '')
        for x in ref.get('skill_cases', [])
        if x.get('class') in {'Assassin', 'Shaman'}
    }, key=str.casefold)

    # A file-name comparison is only a coarse migration indicator; it is not a
    # source merge recommendation.  Store it separately from graph confidence.
    current_source_basenames = collections.Counter(
        pathlib.PurePosixPath(str(rel)).name.casefold()
        for rel in cur.get('source_files', [])
    )
    handler_presence = []
    for rel in reference_handler_files:
        base = pathlib.PurePosixPath(rel).name.casefold()
        handler_presence.append({
            'reference_file': rel,
            'basename': pathlib.PurePosixPath(rel).name,
            'detected_in_current_source': bool(current_source_basenames.get(base)),
        })

    literal_counts = {}
    for name, ev in (('current', cur), ('reference', ref)):
        c = collections.Counter(_ext(str(x.get('value') or '')) for x in ev.get('literal_refs', []))
        literal_counts[name] = dict(sorted(c.items()))

    skill_catalog = parse_reference_skill_catalog(reference, ('Assassin', 'Shaman'))
    job_summary = {
        'current_max_jobs': cur.get('max_jobs', {}),
        'current_assassin_shaman_jobs': [x for x in cur.get('jobs', []) if str(x.get('name', '')).casefold().startswith(('ass', 'sham'))],
        'reference_assassin_shaman_skill_count': len(skill_catalog),
        'class_source_coverage': {
            class_name: {
                'current': _class_skill_coverage(cur, class_name),
                'reference': _class_skill_coverage(ref, class_name),
            }
            for class_name in ('Assassin', 'Shaman')
        },
    }

    out_dir = project_root / 'pt_build' / 'asset_contracts'
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / 'source_contract_graph.json'
    report_path = out_dir / 'source_contract_census.json'
    graph_path.write_text(json.dumps(graph.to_dict(metadata={
        'current_source': source_tree_summary(current),
        'reference_source': source_tree_summary(reference),
    }), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    result = {
        'format': FORMAT,
        'status': 'PASS',
        'current_source': source_tree_summary(current),
        'reference_source': source_tree_summary(reference),
        'literal_extension_counts': literal_counts,
        'sound_symbol_count': {
            'current': len(cur.get('sound_symbol_to_code', {})),
            'reference': len(ref.get('sound_symbol_to_code', {})),
        },
        'resolved_sound_path_count': {
            'current': sum(bool(v) for v in cur.get('sound_symbol_to_path', {}).values()),
            'reference': sum(bool(v) for v in ref.get('sound_symbol_to_path', {}).values()),
        },
        'format_relation_counts': dict(relation_counts),
        'format_relations': relation_rows,
        'player_class_source_summary': job_summary,
        'reference_handler_presence': handler_presence,
        'graph': str(graph_path),
        'report': str(report_path),
        'hashes_calculated': 0,
        'source_modified': False,
        'client_modified': False,
        'server_modified': False,
        'generation_authorized': False,
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
