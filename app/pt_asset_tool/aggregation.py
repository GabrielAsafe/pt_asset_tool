from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .skill_contract_census import TARGET_CLASSES, audit_player_class_contracts

FORMAT = 'PT_ASSET_AGGREGATION_PLAN_V2'
VALIDATION_FORMAT = 'PT_ASSET_AGGREGATION_VALIDATION_V2'

# Runtime/client payloads that must never be promoted by the aggregator even if
# a future evidence provider accidentally references them.  The contract graph
# should normally prevent these from appearing; this is a second fail-closed
# layer at materialization time.
NON_DEPLOYABLE_NAMES = {'thumbs.db', 'desktop.ini'}
NON_DEPLOYABLE_SUFFIXES = {'.log', '.bak'}


@dataclass
class HashStats:
    cache_hits: int = 0
    legacy_cache_hits: int = 0
    calculated: int = 0
    bytes_read: int = 0


class HashCache:
    """Persistent content hash cache shared across extracted releases.

    The primary DB lives under ~/.cache so a new FULL release does not throw
    away expensive hashes.  If the user's earlier Summit comparison cache is
    present, compatible rows are imported lazily on lookup.
    """

    def __init__(self):
        base = pathlib.Path(os.environ.get('XDG_CACHE_HOME') or (pathlib.Path.home() / '.cache'))
        self.path = base / 'pt_asset_tool' / 'asset_hashes.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS hashes (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                dev INTEGER NOT NULL,
                ino INTEGER NOT NULL,
                sha256 TEXT NOT NULL
            )
        ''')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_hash_inode ON hashes(dev, ino, size, mtime_ns)')
        self.db.commit()
        self.legacy_path = pathlib.Path.home() / '.cache' / 'summit_hash_cache.sqlite3'
        self.legacy = None
        if self.legacy_path.is_file() and self.legacy_path != self.path:
            try:
                self.legacy = sqlite3.connect(f'file:{self.legacy_path}?mode=ro', uri=True)
            except sqlite3.Error:
                self.legacy = None
        self.stats = HashStats()

    def close(self):
        try:
            self.db.commit()
            self.db.close()
        finally:
            if self.legacy is not None:
                self.legacy.close()

    def _stat(self, path: pathlib.Path):
        st = path.stat()
        return st, (str(path.resolve()), st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino)

    def _lookup_db(self, conn: sqlite3.Connection, key: tuple[Any, ...]) -> str | None:
        try:
            row = conn.execute('''
                SELECT sha256 FROM hashes
                WHERE path=? AND size=? AND mtime_ns=? AND dev=? AND ino=?
            ''', key).fetchone()
            return str(row[0]) if row else None
        except sqlite3.Error:
            return None

    def sha256(self, path: pathlib.Path) -> str:
        path = pathlib.Path(path)
        st, key = self._stat(path)
        h = self._lookup_db(self.db, key)
        if h:
            self.stats.cache_hits += 1
            return h
        if self.legacy is not None:
            h = self._lookup_db(self.legacy, key)
            if h:
                self.stats.legacy_cache_hits += 1
                self.db.execute(
                    'INSERT OR REPLACE INTO hashes(path,size,mtime_ns,dev,ino,sha256) VALUES(?,?,?,?,?,?)',
                    (*key, h),
                )
                self.db.commit()
                return h
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                digest.update(chunk)
                self.stats.bytes_read += len(chunk)
        h = digest.hexdigest()
        self.stats.calculated += 1
        self.db.execute(
            'INSERT OR REPLACE INTO hashes(path,size,mtime_ns,dev,ino,sha256) VALUES(?,?,?,?,?,?)',
            (*key, h),
        )
        self.db.commit()
        return h


def _norm(value: str) -> str:
    value = str(value or '').strip().replace('\\', '/')
    while '//' in value:
        value = value.replace('//', '/')
    return value.lstrip('./')


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    rel = pathlib.PurePosixPath(_norm(value))
    if not rel.parts or rel.is_absolute() or any(x in {'', '.', '..'} for x in rel.parts):
        raise ValueError(f'UNSAFE_AGGREGATE_TARGET_PATH:{value}')
    return rel


def _source_root_map(census: dict[str, Any]) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    target = census.get('target_client_root')
    if target:
        out['SUMMIT_CLIENT'] = pathlib.Path(target).expanduser().resolve()
    meta = census.get('source_roots') or {}
    for row in meta.get('donor_clients') or []:
        label = str(row.get('label') or '')
        root = str(row.get('root') or '')
        if label and root:
            out[label] = pathlib.Path(root).expanduser().resolve()
    return out


def _parse_candidate(value: str, source_roots: dict[str, pathlib.Path]) -> tuple[str, pathlib.Path] | None:
    text = str(value or '')
    # Prefer a known label prefix so colons inside a future platform path do not
    # make parsing ambiguous.
    for label in sorted(source_roots, key=len, reverse=True):
        prefix = label + ':'
        if text.startswith(prefix):
            return label, pathlib.Path(text[len(prefix):])
    # Target basename collisions historically stored raw paths without label.
    p = pathlib.Path(text)
    if p.is_absolute():
        for label, root in source_roots.items():
            try:
                p.resolve().relative_to(root)
                return label, p
            except Exception:
                pass
    return None


def _actual_relative_path(logical: str, source_label: str, physical: pathlib.Path, source_roots: dict[str, pathlib.Path]) -> str:
    logical = _norm(logical)
    # Exact logical paths are authoritative.  Basename-only references need the
    # donor/target relative path so the overlay does not invent a directory.
    if '/' in logical:
        return _safe_rel(logical).as_posix()
    root = source_roots.get(source_label)
    if root is None:
        raise ValueError(f'SOURCE_ROOT_UNKNOWN_FOR_BASENAME:{source_label}:{logical}')
    try:
        rel = physical.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f'PHYSICAL_OUTSIDE_SOURCE_ROOT:{source_label}:{physical}') from exc
    return _safe_rel(rel).as_posix()


def _graph_reachable_assets(graph: dict[str, Any], classes: Iterable[str]) -> tuple[set[str], list[dict[str, Any]]]:
    nodes = {str(n.get('node_id')): n for n in graph.get('nodes') or []}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get('edges') or []:
        outgoing[str(edge.get('source'))].append(edge)

    seeds = [f'PLAYER_CLASS:{c}' for c in classes]
    queue = deque(x for x in seeds if x in nodes)
    seen = set(queue)
    traversed: list[dict[str, Any]] = []
    while queue:
        src = queue.popleft()
        for edge in outgoing.get(src, []):
            target = str(edge.get('target') or '')
            traversed.append(edge)
            if target and target in nodes and target not in seen:
                seen.add(target)
                queue.append(target)
    asset_ids = {node_id for node_id in seen if (nodes.get(node_id) or {}).get('node_type') == 'ASSET'}
    return asset_ids, traversed


def _hash_candidate_group(
    candidates: list[tuple[str, pathlib.Path]],
    cache: HashCache,
) -> tuple[dict[str, list[tuple[str, pathlib.Path]]], list[dict[str, Any]]]:
    groups: dict[str, list[tuple[str, pathlib.Path]]] = defaultdict(list)
    rows = []
    for label, path in candidates:
        if not path.is_file():
            rows.append({'source_label': label, 'physical_path': str(path), 'status': 'SOURCE_FILE_MISSING'})
            continue
        h = cache.sha256(path)
        groups[h].append((label, path))
        rows.append({
            'source_label': label, 'physical_path': str(path), 'status': 'HASHED',
            'sha256': h, 'size': path.stat().st_size,
        })
    return groups, rows


def _choose_by_priority(
    candidates: list[tuple[str, pathlib.Path]],
    donor_priority: list[str],
) -> tuple[str, pathlib.Path]:
    rank = {label: i for i, label in enumerate(donor_priority)}
    return sorted(candidates, key=lambda x: (rank.get(x[0], 10_000), x[0].casefold(), str(x[1]).casefold()))[0]


def _class_report_map(census: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(x.get('class')): x for x in census.get('classes') or []}


def _asset_requirement_level(attrs: dict[str, Any]) -> str:
    """Classify aggregation expectations without turning every reference row
    into a hard runtime requirement.

    Character source tables enumerate a very large cosmetic/config corpus.
    Individual heads, costumes and seasonal variants are useful superset
    material, but a missing single variant must not make the playable class
    itself incomplete.  Core motion roots/containers and the proven skill UI
    buttons remain fail-closed.
    """
    role = str(attrs.get('asset_role') or '')
    kind = str(attrs.get('config_kind') or '')
    if role in {'SKILL_BUTTON_NORMAL', 'SKILL_BUTTON_HOVER', 'PLAYER_CLASS_MOTION_INX', 'PLAYER_CLASS_MOTION_SMB'}:
        return 'CORE_REQUIRED'
    if role == 'PLAYER_CLASS_CONFIG_INX':
        # Source character tables enumerate individual bodies/armours/heads.
        # No single variant is a class-core requirement; the verified motion
        # root reached through those configs is the actual core dependency.
        return 'OPTIONAL_VARIANT'
    return 'EVIDENCE_EXPECTED'


def _missing_action_for(requirement_level: str) -> str:
    if requirement_level == 'CORE_REQUIRED':
        return 'MISSING'
    if requirement_level == 'OPTIONAL_VARIANT':
        return 'OPTIONAL_MISSING'
    return 'EVIDENCE_MISSING'


def _runtime_blockers(census: dict[str, Any], classes: Iterable[str]) -> list[dict[str, Any]]:
    """Return only runtime blockers, not source-discovery differences.

    A class already enabled by the current job table is runtime-established.
    EU SkillDataCode index drift is informative for migration, but cannot be a
    blocker for the eight classes already running with the Summit registry.
    """
    cmap = _class_report_map(census)
    out = []
    for class_name in classes:
        row = cmap.get(class_name) or {}
        runtime = row.get('runtime_source') or {}
        motion = row.get('motion_contract') or {}
        runtime_status = str(runtime.get('status') or '')
        motion_status = str(motion.get('status') or '')
        registry_status = str(motion.get('runtime_motion_selectability_effective_status') or motion.get('runtime_motion_selectability_status') or '')
        reasons = []
        if runtime_status == 'RUNTIME_DISABLED_BY_MAX_JOBNUM':
            reasons.append('RUNTIME_DISABLED_BY_MAX_JOBNUM')
        elif runtime_status not in {'RUNTIME_JOB_ENABLED', 'RUNTIME_SOURCE_PRESENT'}:
            reasons.append(runtime_status or 'RUNTIME_STATUS_UNKNOWN')
        if motion_status not in {'TARGET_CLASS_SKILL_MOTION_READY', 'CLASS_SKILL_MOTION_RECOVERABLE'}:
            reasons.append(motion_status or 'MOTION_STATUS_UNKNOWN')
        # Only non-established/migrating jobs need to match the reference INX
        # registry before their imported skill motions can be selected.
        if runtime_status != 'RUNTIME_JOB_ENABLED' and registry_status in {
            'CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES',
            'CURRENT_REGISTRY_PARTIAL_INDEX_ALIGNMENT',
        }:
            reasons.append(registry_status)
        if reasons:
            out.append({
                'class': class_name,
                'overall_status': row.get('overall_status'),
                'runtime_status': runtime_status,
                'motion_status': motion_status,
                'runtime_motion_selectability_status': registry_status,
                'reasons': reasons,
            })
    return out


def build_player_class_aggregation(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None,
    reference_source_root: str | pathlib.Path | None,
    donor_clients: Iterable[str] | None = None,
    classes: Iterable[str] = TARGET_CLASSES,
    materialize: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Plan and optionally materialize a safe player-class client overlay.

    Nothing is written to the configured client/server roots.  Only missing,
    source-proven files are copied into ``pt_build/aggregate``.  Existing target
    files are represented as KEEP_TARGET manifest rows and conflicts stay
    unresolved.
    """
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    wanted = tuple(dict.fromkeys(str(x) for x in classes))
    unknown = [x for x in wanted if x not in TARGET_CLASSES]
    if unknown:
        raise ValueError(f'UNSUPPORTED_PLAYER_CLASS:{unknown}; supported={TARGET_CLASSES}')

    if progress:
        progress('building source-backed player-class contract graph')
    census = audit_player_class_contracts(
        project_root,
        client_root,
        source_root=source_root,
        reference_source_root=reference_source_root,
        donor_clients=donor_clients,
        classes=wanted,
        progress=(lambda m: progress('contract: ' + m)) if progress else None,
    )
    graph_path = pathlib.Path(census['graph'])
    graph = json.loads(graph_path.read_text(encoding='utf-8'))
    asset_ids, traversed_edges = _graph_reachable_assets(graph, wanted)
    nodes = {str(x.get('node_id')): x for x in graph.get('nodes') or []}
    source_roots = _source_root_map(census)
    donor_priority = [str(x.get('label')) for x in (census.get('source_roots') or {}).get('donor_clients') or []]

    selection = 'all' if set(wanted) == set(TARGET_CLASSES) else '__'.join(x.casefold() for x in wanted)
    out_dir = project_root / 'pt_build' / 'aggregate' / 'player_classes' / selection
    overlay_dir = out_dir / 'client_overlay'
    variant_dir = out_dir / 'reference_variants'
    if out_dir.exists():
        # Deterministic generated output only; never follows outside the build root.
        build_root = (project_root / 'pt_build' / 'aggregate').resolve()
        resolved = out_dir.resolve()
        if build_root not in resolved.parents:
            raise RuntimeError(f'AGGREGATE_OUTPUT_ESCAPE:{resolved}')
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if materialize:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        variant_dir.mkdir(parents=True, exist_ok=True)

    cache = HashCache()
    plan_rows: list[dict[str, Any]] = []
    dest_index: dict[str, dict[str, Any]] = {}
    try:
        if progress:
            progress(f'planning {len(asset_ids)} reachable assets')
        for num, asset_id in enumerate(sorted(asset_ids), start=1):
            node = nodes[asset_id]
            attrs = dict(node.get('attributes') or {})
            logical = _norm(attrs.get('logical_path') or node.get('label') or '')
            resolution = dict(attrs.get('resolution') or {})
            status = str(resolution.get('status') or 'MISSING_UNKNOWN')
            role = str(attrs.get('asset_role') or '')
            config_kind = str(attrs.get('config_kind') or '')
            requirement_level = _asset_requirement_level(attrs)
            row: dict[str, Any] = {
                'asset_node': asset_id,
                'logical_path': logical,
                'asset_role': role,
                'config_kind': config_kind,
                'requirement_level': requirement_level,
                'input_status': status,
                'action': '',
                'target_relative_path': '',
                'source_label': str(resolution.get('source_label') or ''),
                'source_path': str(resolution.get('physical_path') or ''),
                'source_sha256': '',
                'source_size': None,
                'resolution_mode': str(resolution.get('match_mode') or ''),
                'candidate_rows': [],
                'variant_archive': [],
                'variant_count': 0,
                'reason': '',
            }

            # Hard deny obviously non-deployable accidental edges.
            basename = pathlib.PurePosixPath(logical).name.casefold()
            suffix = pathlib.PurePosixPath(logical).suffix.casefold()
            if basename in NON_DEPLOYABLE_NAMES or suffix in NON_DEPLOYABLE_SUFFIXES:
                row.update(action='EXCLUDE_NON_DEPLOYABLE', reason='NON_DEPLOYABLE_GUARD')
                plan_rows.append(row)
                continue

            if status == 'PRESENT_TARGET':
                source = pathlib.Path(row['source_path']) if row['source_path'] else pathlib.Path()
                if not source.is_file():
                    row.update(action='ERROR_TARGET_MISSING', reason='RESOLUTION_STALE')
                else:
                    try:
                        row['target_relative_path'] = _actual_relative_path(logical, 'SUMMIT_CLIENT', source, source_roots)
                    except Exception as exc:
                        row.update(action='REVIEW_PATH', reason=str(exc))
                    else:
                        row.update(action='KEEP_TARGET', source_label='SUMMIT_CLIENT')
                plan_rows.append(row)
                continue

            if status == 'RECOVERABLE_REFERENCE':
                source = pathlib.Path(row['source_path']) if row['source_path'] else pathlib.Path()
                label = row['source_label']
                if not source.is_file():
                    row.update(action=_missing_action_for(requirement_level), reason='RECOVERY_SOURCE_MISSING')
                else:
                    try:
                        row['target_relative_path'] = _actual_relative_path(logical, label, source, source_roots)
                    except Exception as exc:
                        row.update(action='REVIEW_PATH', reason=str(exc))
                    else:
                        h = cache.sha256(source)
                        row.update(
                            action='RECOVER', source_sha256=h,
                            source_size=source.stat().st_size,
                            reason='SINGLE_REFERENCE_SOURCE',
                        )
                plan_rows.append(row)
                continue

            if status == 'CONFLICT':
                candidates = []
                for raw in resolution.get('candidates') or []:
                    parsed = _parse_candidate(str(raw), source_roots)
                    if parsed:
                        candidates.append(parsed)
                # Deduplicate same physical source rows.
                unique = {(label, str(path.resolve())): (label, path) for label, path in candidates}
                candidates = list(unique.values())
                groups, candidate_rows = _hash_candidate_group(candidates, cache)
                row['candidate_rows'] = candidate_rows
                if len(groups) == 1 and groups:
                    h, same = next(iter(groups.items()))
                    label, source = _choose_by_priority(same, donor_priority)
                    try:
                        dest = _actual_relative_path(logical, label, source, source_roots)
                    except Exception as exc:
                        row.update(action='REVIEW_PATH', reason=str(exc))
                    else:
                        row.update(
                            action='RECOVER_DEDUPED', target_relative_path=dest,
                            source_label=label, source_path=str(source), source_sha256=h,
                            source_size=source.stat().st_size,
                            reason='MULTIPLE_REFERENCES_IDENTICAL_SHA256',
                        )
                elif len(groups) > 1:
                    # For optional/cosmetic variants a same-path content split is
                    # expected across client lineages.  Build a deterministic
                    # runtime overlay from the configured donor priority, while
                    # archiving *all* variants side-by-side for provenance.  Core
                    # runtime assets remain fail-closed and unresolved.
                    if requirement_level != 'CORE_REQUIRED':
                        live = [pair for group in groups.values() for pair in group]
                        label, source = _choose_by_priority(live, donor_priority)
                        try:
                            dest = _actual_relative_path(logical, label, source, source_roots)
                        except Exception as exc:
                            row.update(action='REVIEW_PATH', reason=str(exc))
                        else:
                            h = cache.sha256(source)
                            row.update(
                                action='RECOVER_PREFERRED_VARIANT', target_relative_path=dest,
                                source_label=label, source_path=str(source), source_sha256=h,
                                source_size=source.stat().st_size,
                                variant_count=sum(len(v) for v in groups.values()),
                                reason='PREFERRED_DONOR_WITH_REFERENCE_VARIANTS',
                            )
                    else:
                        row.update(action='CONFLICT', reason='REFERENCE_CONTENT_VARIANTS')
                else:
                    row.update(action=_missing_action_for(requirement_level), reason='NO_LIVE_CONFLICT_CANDIDATES')
                plan_rows.append(row)
                continue

            row.update(action=_missing_action_for(requirement_level), reason='NO_REFERENCE_SOURCE')
            plan_rows.append(row)

            if progress and num % 250 == 0:
                progress(f'planned {num}/{len(asset_ids)} assets')

        # Detect target destination collisions after physical source selection.
        for row in plan_rows:
            dest = str(row.get('target_relative_path') or '')
            if not dest or row['action'] not in {'KEEP_TARGET', 'RECOVER', 'RECOVER_DEDUPED', 'RECOVER_PREFERRED_VARIANT'}:
                continue
            key = dest.casefold()
            prior = dest_index.get(key)
            if prior is None:
                dest_index[key] = row
                continue
            # Same graph node/path can be reached through multiple edges but rows
            # are already node-deduplicated.  A different source for same target
            # is a real collision and must be reviewed.
            if prior['asset_node'] != row['asset_node']:
                prior['action'] = 'CONFLICT_TARGET_PATH'
                prior['reason'] = f"TARGET_PATH_COLLISION_WITH:{row['asset_node']}"
                row['action'] = 'CONFLICT_TARGET_PATH'
                row['reason'] = f"TARGET_PATH_COLLISION_WITH:{prior['asset_node']}"

        if materialize:
            if progress:
                progress('materializing recoverable files into safe client overlay')
            for row in plan_rows:
                if row['action'] not in {'RECOVER', 'RECOVER_DEDUPED', 'RECOVER_PREFERRED_VARIANT'}:
                    continue
                rel = _safe_rel(row['target_relative_path'])
                src = pathlib.Path(row['source_path'])
                dst = overlay_dir.joinpath(*rel.parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise RuntimeError(f'AGGREGATE_STAGING_COLLISION:{rel.as_posix()}')
                shutil.copy2(src, dst)
                row['staged_path'] = str(dst)
                row['staged_sha256'] = cache.sha256(dst)
                row['staged_verified'] = row['staged_sha256'] == row['source_sha256']

                if row['action'] == 'RECOVER_PREFERRED_VARIANT':
                    archived = []
                    for cand in row.get('candidate_rows') or []:
                        if cand.get('status') != 'HASHED' or not cand.get('physical_path'):
                            continue
                        label = str(cand.get('source_label') or 'UNKNOWN')
                        csrc = pathlib.Path(str(cand['physical_path']))
                        if not csrc.is_file():
                            continue
                        try:
                            crel = _actual_relative_path(row['logical_path'], label, csrc, source_roots)
                        except Exception:
                            crel = _safe_rel(row['logical_path']).as_posix()
                        cdst = variant_dir / label / pathlib.PurePosixPath(crel)
                        cdst.parent.mkdir(parents=True, exist_ok=True)
                        if not cdst.exists():
                            shutil.copy2(csrc, cdst)
                        archived.append({
                            'source_label': label,
                            'source_path': str(csrc),
                            'sha256': str(cand.get('sha256') or cache.sha256(csrc)),
                            'archived_path': str(cdst),
                            'selected_for_runtime_overlay': label == row.get('source_label') and str(csrc) == row.get('source_path'),
                        })
                    row['variant_archive'] = archived

        action_counts = Counter(str(x['action']) for x in plan_rows)
        hard_unresolved_actions = {'CONFLICT', 'CONFLICT_TARGET_PATH', 'MISSING', 'REVIEW_PATH', 'ERROR_TARGET_MISSING'}
        hard_unresolved = [x for x in plan_rows if x['action'] in hard_unresolved_actions]
        optional_review_actions = {'OPTIONAL_MISSING', 'EVIDENCE_MISSING'}
        optional_review = [x for x in plan_rows if x['action'] in optional_review_actions]
        preferred_variants = [x for x in plan_rows if x['action'] == 'RECOVER_PREFERRED_VARIANT']
        recovery_actions = {'RECOVER','RECOVER_DEDUPED','RECOVER_PREFERRED_VARIANT'}
        bad_stage = [x for x in plan_rows if x['action'] in recovery_actions and materialize and not x.get('staged_verified')]
        runtime_blockers = _runtime_blockers(census, wanted)
        if hard_unresolved or bad_stage:
            aggregate_state = 'REVIEW_REQUIRED'
        elif optional_review or preferred_variants:
            aggregate_state = 'CORE_READY_STAGING_WITH_OPTIONAL_GAPS'
        else:
            aggregate_state = 'READY_STAGING'

        manifest = {
            'format': FORMAT,
            'status': 'PASS',
            'aggregate_state': aggregate_state,
            'entity_type': 'PLAYER_CLASS',
            'classes': list(wanted),
            'target_client_root': str(client_root),
            'source_roots': {k: str(v) for k, v in source_roots.items()},
            'donor_priority': donor_priority,
            'contract_report': census.get('report'),
            'contract_graph': census.get('graph'),
            'reachable_node_count': len(_graph_reachable_assets(graph, wanted)[0]),
            'traversed_edge_count': len(traversed_edges),
            'asset_count': len(plan_rows),
            'action_counts': dict(action_counts),
            'materialized': bool(materialize),
            'overlay_root': str(overlay_dir) if materialize else '',
            'reference_variants_root': str(variant_dir) if materialize else '',
            'core_unresolved_count': len(hard_unresolved),
            'optional_review_count': len(optional_review),
            'preferred_variant_count': len(preferred_variants),
            'ready_to_apply': not hard_unresolved and not bad_stage and bool(materialize),
            'runtime_ready': len(runtime_blockers) == 0,
            'runtime_blockers': runtime_blockers,
            'hash_cache': str(cache.path),
            'hash_stats': {
                'cache_hits': cache.stats.cache_hits,
                'legacy_cache_hits': cache.stats.legacy_cache_hits,
                'calculated': cache.stats.calculated,
                'bytes_read': cache.stats.bytes_read,
            },
            'client_modified': False,
            'server_modified': False,
            'rows': plan_rows,
            'notes': [
                'The client overlay contains only selected recoverable files absent from the Summit target; KEEP_TARGET files are not duplicated.',
                'No target client/server/source file is modified.',
                'Core requirements are fail-closed. Missing individual head/costume/seasonal configs are OPTIONAL_VARIANT gaps and do not block the playable class core.',
                'Different same-path optional donor variants use donor priority for the runtime overlay and every live variant is preserved under reference_variants/.',
                'Aggregation readiness and runtime/class migration readiness are separate states.',
            ],
        }
        manifest_path = out_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        # Human-friendly tabular provenance and review queues.
        columns = [
            'action','logical_path','target_relative_path','asset_role','config_kind','requirement_level','input_status',
            'source_label','source_path','source_sha256','source_size','variant_count','reason','staged_path',
        ]
        with (out_dir / 'provenance.tsv').open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=columns, delimiter='\t', extrasaction='ignore')
            w.writeheader(); w.writerows(plan_rows)
        for filename, predicate in (
            ('conflicts.tsv', lambda r: str(r['action']).startswith('CONFLICT') or r['action'] == 'REVIEW_PATH'),
            ('missing.tsv', lambda r: r['action'] in {'MISSING','ERROR_TARGET_MISSING'}),
            ('optional_gaps.tsv', lambda r: r['action'] in {'OPTIONAL_MISSING','EVIDENCE_MISSING'}),
            ('recover.tsv', lambda r: r['action'] in recovery_actions),
            ('variants.tsv', lambda r: r['action'] == 'RECOVER_PREFERRED_VARIANT'),
        ):
            with (out_dir / filename).open('w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=columns, delimiter='\t', extrasaction='ignore')
                w.writeheader(); w.writerows([r for r in plan_rows if predicate(r)])

        validation = {
            'format': VALIDATION_FORMAT,
            'status': 'PASS' if not bad_stage else 'FAIL',
            'aggregate_state': aggregate_state,
            'classes': list(wanted),
            'planned_asset_count': len(plan_rows),
            'core_unresolved_count': len(hard_unresolved),
            'core_unresolved_action_counts': dict(Counter(x['action'] for x in hard_unresolved)),
            # Backward-compatible fields now mean hard/core unresolved only.
            'unresolved_count': len(hard_unresolved),
            'unresolved_action_counts': dict(Counter(x['action'] for x in hard_unresolved)),
            'optional_review_count': len(optional_review),
            'optional_review_action_counts': dict(Counter(x['action'] for x in optional_review)),
            'preferred_variant_count': len(preferred_variants),
            'materialized_recovery_count': sum(1 for x in plan_rows if x['action'] in recovery_actions and x.get('staged_path')),
            'archived_reference_variant_count': sum(len(x.get('variant_archive') or []) for x in preferred_variants),
            'staging_hash_failure_count': len(bad_stage),
            'post_aggregate_contract_presence': {
                'present_or_staged': sum(1 for x in plan_rows if x['action'] in {'KEEP_TARGET', *recovery_actions}),
                'core_unresolved': len(hard_unresolved),
                'optional_or_evidence_gaps': len(optional_review),
                'excluded_non_deployable': action_counts.get('EXCLUDE_NON_DEPLOYABLE', 0),
            },
            'target_client_modified': False,
            'target_server_modified': False,
            'runtime_ready': len(runtime_blockers) == 0,
            'runtime_blockers': runtime_blockers,
        }
        validation_path = out_dir / 'validation.json'
        validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        return {
            'format': FORMAT,
            'status': 'PASS',
            'aggregate_state': aggregate_state,
            'classes': list(wanted),
            'asset_count': len(plan_rows),
            'action_counts': dict(action_counts),
            'unresolved_count': len(hard_unresolved),
            'core_unresolved_count': len(hard_unresolved),
            'optional_review_count': len(optional_review),
            'preferred_variant_count': len(preferred_variants),
            'materialized_recovery_count': validation['materialized_recovery_count'],
            'ready_to_apply': manifest['ready_to_apply'],
            'runtime_ready': manifest['runtime_ready'],
            'manifest': str(manifest_path),
            'validation': str(validation_path),
            'overlay_root': str(overlay_dir) if materialize else '',
            'provenance': str(out_dir / 'provenance.tsv'),
            'conflicts': str(out_dir / 'conflicts.tsv'),
            'missing': str(out_dir / 'missing.tsv'),
            'recover': str(out_dir / 'recover.tsv'),
            'optional_gaps': str(out_dir / 'optional_gaps.tsv'),
            'variants': str(out_dir / 'variants.tsv'),
            'reference_variants_root': str(variant_dir) if materialize else '',
            'hash_cache': str(cache.path),
            'hash_stats': manifest['hash_stats'],
            'client_modified': False,
            'server_modified': False,
        }
    finally:
        cache.close()
