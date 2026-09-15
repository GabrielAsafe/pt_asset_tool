from __future__ import annotations

import csv
import json
import os
import pathlib
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .aggregation import HashCache, build_player_class_aggregation
from .skill_contract_census import TARGET_CLASSES
from .server_lifecycle import (
    ASSET_MAP_METADATA, ASSET_MAP_METADATA_REVIEW, ASSET_SHARED_3D, ASSET_SHARED_VISUAL,
    ASSET_STATIC, CONFIG_REVIEW, UNKNOWN_REVIEW, classify_server_path as classify_server_lifecycle_path,
)

CLIENT_RUNTIME_SUFFIXES = {
    '.smd', '.smb', '.inx',
    '.bmp', '.tga', '.dds', '.png', '.jpg', '.jpeg', '.gif',
    '.wav', '.ogg', '.mp3', '.mid', '.bgm',
    '.part', '.sin', '.msg', '.lua', '.fnt', '.zif',
    '.ini', '.inf', '.txt', '.dat', '.tbl', '.lst', '.csv', '.xml', '.json', '.bin', '.map', '.res',
    '.fon', '.ttf',
}
AUTHORING_SUFFIXES = {'.ase', '.max', '.4ase', '.psd', '.blend'}
TOOLING_SUFFIXES = {
    '.exe', '.dll', '.ocx', '.pdb', '.lib', '.exp', '.idb', '.reg', '.bat', '.cmd', '.sh',
    '.cpp', '.cc', '.c', '.cxx', '.h', '.hpp', '.inl', '.obj', '.o', '.a', '.so',
}
ARCHIVE_SUFFIXES = {'.zip', '.rar', '.7z', '.gz', '.bz2', '.xz', '.tar'}
NOISE_SUFFIXES = {'.log', '.bak', '.tmp', '.old', '.dmp'}
NON_DEPLOYABLE_NAMES = {'thumbs.db', 'desktop.ini'}

@dataclass(frozen=True)
class TreeFile:
    label: str
    root: pathlib.Path
    physical: pathlib.Path
    relative: str
    canonical_relative: str
    category: str
    deployability: str
    reason: str


def _norm(value: str) -> str:
    value = str(value or '').strip().replace('\\', '/')
    while '//' in value:
        value = value.replace('//', '/')
    return value.lstrip('./')


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    rel = pathlib.PurePosixPath(_norm(value))
    if not rel.parts or rel.is_absolute() or any(x in {'', '.', '..'} for x in rel.parts):
        raise ValueError(f'UNSAFE_SUPERSET_PATH:{value}')
    return rel


def parse_labeled_roots(values: Iterable[str] | None) -> list[tuple[str, pathlib.Path]]:
    out: list[tuple[str, pathlib.Path]] = []
    seen: set[str] = set()
    for raw in values or []:
        text = str(raw or '').strip()
        if not text:
            continue
        if '=' not in text:
            raise ValueError(f'DONOR_ROOT_FORMAT_INVALID:{text}')
        label, path_text = text.split('=', 1)
        label = label.strip().upper()
        if not label or any(not (c.isalnum() or c in '_-') for c in label):
            raise ValueError(f'DONOR_LABEL_INVALID:{label}')
        path = pathlib.Path(path_text.strip()).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f'DONOR_ROOT_NOT_FOUND:{label}:{path}')
        if label in seen:
            raise ValueError(f'DONOR_LABEL_DUPLICATE:{label}')
        seen.add(label)
        out.append((label, path))
    return out


def classify_client_path(rel: str) -> tuple[str, str, str]:
    rel = _norm(rel)
    p = pathlib.PurePosixPath(rel)
    name = p.name.casefold()
    suffix = p.suffix.casefold()
    if name in NON_DEPLOYABLE_NAMES:
        return 'NOISE', 'EXCLUDE', 'NON_DEPLOYABLE_NAME'
    if suffix in NOISE_SUFFIXES:
        return 'NOISE', 'EXCLUDE', 'NOISE_SUFFIX'
    if suffix in TOOLING_SUFFIXES:
        return 'TOOLING_OR_BINARY', 'EXCLUDE', 'TOOLING_SUFFIX'
    if suffix in ARCHIVE_SUFFIXES:
        return 'ARCHIVE', 'REFERENCE_ONLY', 'ARCHIVE_SUFFIX'
    if suffix in AUTHORING_SUFFIXES:
        return 'AUTHORING_SOURCE', 'REFERENCE_ONLY', 'AUTHORING_SUFFIX'
    if suffix in {'.smd', '.smb', '.inx'}:
        return 'MODEL_OR_MOTION', 'RUNTIME', 'KNOWN_RUNTIME_ASSET'
    if suffix in {'.bmp', '.tga', '.dds', '.png', '.jpg', '.jpeg', '.gif'}:
        return 'TEXTURE_OR_UI', 'RUNTIME', 'KNOWN_RUNTIME_ASSET'
    if suffix in {'.wav', '.ogg', '.mp3', '.mid', '.bgm'}:
        return 'AUDIO', 'RUNTIME', 'KNOWN_RUNTIME_ASSET'
    if suffix == '.part' or (suffix == '.lua' and rel.casefold().startswith('effect/')):
        return 'EFFECT', 'RUNTIME', 'KNOWN_RUNTIME_ASSET'
    if suffix == '.fnt' and '/fonts/' in ('/' + rel.casefold()):
        return 'UI_DATA', 'RUNTIME', 'FONT_RUNTIME_DATA'
    if suffix == '.zif' and '/items/animation/' in ('/' + rel.casefold()):
        return 'ITEM_DATA', 'RUNTIME', 'ITEM_ANIMATION_CONTAINER'
    if suffix in {'.fx', '.sct', '.pkg'}:
        return 'UNKNOWN', 'REFERENCE_ONLY', 'RUNTIME_ROLE_PATH_DEPENDENT_REVIEW'
    if suffix in CLIENT_RUNTIME_SUFFIXES:
        return 'CLIENT_DATA', 'RUNTIME', 'KNOWN_RUNTIME_DATA'
    return 'UNKNOWN', 'REFERENCE_ONLY', 'UNKNOWN_EXTENSION_FAIL_CLOSED'


def normalize_server_relative(rel: str) -> tuple[str | None, str]:
    rel = _norm(rel)
    low = rel.casefold()
    if low.startswith('game-server/'):
        return rel[len('game-server/'):], 'STRIP_GAME_SERVER_PREFIX'
    if low.startswith('login-server/'):
        # Summit's exact login-server namespace has not yet been source-proven.
        # Preserve these files as reference evidence instead of guessing a target path.
        return None, 'LOGIN_SERVER_NAMESPACE_UNMAPPED'
    pfx = 'GameServer/OpenItem - Copia/'
    if low.startswith(pfx.casefold()):
        return 'GameServer/OpenItem/' + rel[len(pfx):], 'NORMALIZE_OPENITEM_COPY'
    return rel, 'IDENTITY'


def classify_server_path(rel: str | None, original_rel: str) -> tuple[str, str, str]:
    """Map the authoritative server lifecycle policy into superset actions.

    The generic superset must never maintain its own weaker lifecycle model: that
    previously allowed persistence/security/runtime-integrity state to fall through
    to ``SERVER_DATA/RUNTIME`` and become recovery candidates.
    """
    if rel is None:
        return 'SERVER_REFERENCE_NAMESPACE', 'REFERENCE_ONLY', 'UNMAPPED_NAMESPACE'
    classification = classify_server_lifecycle_path(rel)
    lifecycle = classification.lifecycle
    reason = f'{classification.reason};{classification.write_policy}'
    if lifecycle in {ASSET_STATIC, ASSET_MAP_METADATA, ASSET_SHARED_3D}:
        return lifecycle, 'RUNTIME', reason
    if lifecycle in {ASSET_MAP_METADATA_REVIEW, ASSET_SHARED_VISUAL, CONFIG_REVIEW, UNKNOWN_REVIEW}:
        return lifecycle, 'REFERENCE_ONLY', reason
    # Every other lifecycle class is hard-excluded by the authoritative policy.
    return lifecycle, 'EXCLUDE', reason


def _walk_tree(label: str, root: pathlib.Path, *, side: str, progress: Callable[[str], None] | None = None) -> list[TreeFile]:
    rows: list[TreeFile] = []
    count = 0
    for base, dirs, files in os.walk(root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            physical = pathlib.Path(base) / name
            try:
                rel = physical.relative_to(root).as_posix()
            except ValueError:
                continue
            if side == 'client':
                canonical = rel
                category, deployability, reason = classify_client_path(rel)
            else:
                normalized, nreason = normalize_server_relative(rel)
                canonical = normalized or rel
                category, deployability, reason = classify_server_path(normalized, rel)
                reason = f'{reason};{nreason}'
            rows.append(TreeFile(label, root, physical, rel, canonical, category, deployability, reason))
            count += 1
            if progress and count % 5000 == 0:
                progress(f'indexed {label}: {count:,} files')
    return rows


def _target_index(root: pathlib.Path, *, side: str, progress: Callable[[str], None] | None = None) -> dict[str, list[TreeFile]]:
    label = 'SUMMIT_CLIENT' if side == 'client' else 'SUMMIT_SERVER'
    rows = _walk_tree(label, root, side=side, progress=progress)
    out: dict[str, list[TreeFile]] = defaultdict(list)
    for row in rows:
        out[row.canonical_relative.casefold()].append(row)
    return out


def _archive_variant(
    src: pathlib.Path,
    archive_root: pathlib.Path,
    label: str,
    rel: str,
) -> pathlib.Path:
    safe = _safe_rel(rel)
    dst = archive_root / label / pathlib.Path(*safe.parts)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def _write_tsv(path: pathlib.Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter='\t', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def _report_bundle(out_dir: pathlib.Path, names: Iterable[str]) -> pathlib.Path:
    bundle = out_dir / 'reports_bundle.zip'
    if bundle.exists():
        bundle.unlink()
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            p = out_dir / name
            if p.is_file():
                z.write(p, arcname=name)
    return bundle


def build_tree_superset(
    project_root: pathlib.Path,
    target_root: pathlib.Path,
    donor_roots: Iterable[str],
    *,
    side: str,
    materialize: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if side not in {'client', 'server'}:
        raise ValueError(f'INVALID_SUPERSET_SIDE:{side}')
    project_root = pathlib.Path(project_root).resolve()
    target_root = pathlib.Path(target_root).expanduser().resolve()
    if not target_root.is_dir():
        raise FileNotFoundError(f'TARGET_{side.upper()}_ROOT_NOT_FOUND:{target_root}')
    donors = parse_labeled_roots(donor_roots)
    if not donors:
        raise FileNotFoundError(f'NO_{side.upper()}_DONOR_ROOTS_CONFIGURED')

    kind = f'{side}_superset'
    out_dir = project_root / 'pt_build' / 'aggregate' / kind / 'all'
    overlay_dir = out_dir / f'{side}_overlay'
    variants_dir = out_dir / 'reference_variants'
    reference_only_dir = out_dir / 'reference_only'
    build_root = (project_root / 'pt_build' / 'aggregate').resolve()
    if out_dir.exists():
        resolved = out_dir.resolve()
        if build_root not in resolved.parents:
            raise RuntimeError(f'SUPERSET_OUTPUT_ESCAPE:{resolved}')
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if materialize:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        variants_dir.mkdir(parents=True, exist_ok=True)
        reference_only_dir.mkdir(parents=True, exist_ok=True)

    if progress:
        progress(f'indexing Summit {side} target')
    target = _target_index(target_root, side=side, progress=progress)
    if progress:
        progress(f'target canonical paths: {len(target):,}')

    donor_index: dict[str, list[TreeFile]] = defaultdict(list)
    donor_counts: dict[str, int] = {}
    for label, root in donors:
        if progress:
            progress(f'indexing donor {label}')
        rows = _walk_tree(label, root, side=side, progress=progress)
        donor_counts[label] = len(rows)
        for row in rows:
            donor_index[row.canonical_relative.casefold()].append(row)

    cache = HashCache()
    plan: list[dict[str, Any]] = []
    try:
        priority = {label: i for i, (label, _) in enumerate(donors)}
        keys = sorted(donor_index)
        for idx, key in enumerate(keys, start=1):
            candidates = donor_index[key]
            canonical = candidates[0].canonical_relative
            target_rows = target.get(key, [])
            row: dict[str, Any] = {
                'canonical_path': canonical,
                'action': '',
                'category': candidates[0].category,
                'deployability': candidates[0].deployability,
                'reason': candidates[0].reason,
                'selected_source': '',
                'selected_path': '',
                'selected_sha256': '',
                'selected_size': '',
                'target_path': target_rows[0].relative if len(target_rows) == 1 else '',
                'donor_candidate_count': len(candidates),
                'distinct_hash_count': '',
                'variant_count': 0,
                'staged_path': '',
                'staged_verified': '',
                'archive_count': 0,
            }

            if len(target_rows) > 1:
                row.update(action='TARGET_CASE_COLLISION', reason='MULTIPLE_TARGET_PATHS_SAME_CASEFOLD')
                plan.append(row)
                continue
            if target_rows:
                # Existing Summit content wins.  Generic superset does not spend
                # hashes comparing donor variants for paths already present.
                row.update(action='KEEP_TARGET', category=target_rows[0].category, deployability='TARGET')
                plan.append(row)
                continue

            # Multiple path spellings inside one donor are unsafe on the Windows
            # runtime namespace even when Linux can represent both.
            by_label: dict[str, list[TreeFile]] = defaultdict(list)
            for c in candidates:
                by_label[c.label].append(c)
            source_case_collision = any(len(v) > 1 for v in by_label.values())

            # The canonical category/deployability is selected by donor priority.
            candidates_sorted = sorted(candidates, key=lambda c: (priority.get(c.label, 9999), c.label.casefold(), c.relative.casefold()))
            preferred_meta = candidates_sorted[0]
            row['category'] = preferred_meta.category
            row['deployability'] = preferred_meta.deployability
            row['reason'] = preferred_meta.reason

            if preferred_meta.deployability == 'EXCLUDE':
                row.update(action='EXCLUDE_NON_DEPLOYABLE')
                plan.append(row)
                continue

            hashed: list[tuple[TreeFile, str]] = []
            for c in candidates:
                if not c.physical.is_file():
                    continue
                hashed.append((c, cache.sha256(c.physical)))
            groups: dict[str, list[TreeFile]] = defaultdict(list)
            for c, h in hashed:
                groups[h].append(c)
            row['distinct_hash_count'] = len(groups)

            if not groups:
                row.update(action='SOURCE_FILE_MISSING', reason='NO_LIVE_DONOR_CANDIDATES')
                plan.append(row)
                continue

            if source_case_collision and len(groups) > 1:
                row.update(action='DONOR_CASE_COLLISION', reason='SAME_CASEFOLD_PATH_MULTIPLE_CONTENTS_IN_ONE_DONOR')
                if materialize:
                    archived = 0
                    for c, _h in hashed:
                        _archive_variant(c.physical, variants_dir / 'case_collisions', c.label, c.relative)
                        archived += 1
                    row['archive_count'] = archived
                plan.append(row)
                continue

            # Choose preferred source from priority, but preserve every distinct
            # content variant when the target is missing.
            all_live = [c for c, _h in hashed]
            selected = sorted(all_live, key=lambda c: (priority.get(c.label, 9999), c.label.casefold(), c.relative.casefold()))[0]
            selected_hash = cache.sha256(selected.physical)
            row.update(
                selected_source=selected.label,
                selected_path=str(selected.physical),
                selected_sha256=selected_hash,
                selected_size=selected.physical.stat().st_size,
                variant_count=sum(len(v) for v in groups.values()) if len(groups) > 1 else 0,
            )

            if preferred_meta.deployability == 'REFERENCE_ONLY':
                row['action'] = 'ARCHIVE_REFERENCE_ONLY'
                if materialize:
                    archived = 0
                    # Preserve one representative for each content hash/source pair.
                    for h, members in groups.items():
                        for c in members:
                            _archive_variant(c.physical, reference_only_dir / c.category, c.label, c.relative)
                            archived += 1
                    row['archive_count'] = archived
                plan.append(row)
                continue

            if len(groups) == 1:
                row['action'] = 'RECOVER_DEDUPED' if len(hashed) > 1 else 'RECOVER'
                row['reason'] = 'MISSING_TARGET_IDENTICAL_DONORS' if len(hashed) > 1 else 'MISSING_TARGET_SINGLE_DONOR'
            else:
                row['action'] = 'RECOVER_PREFERRED_VARIANT'
                row['reason'] = 'MISSING_TARGET_DONOR_VARIANTS_PREFERRED_BY_PRIORITY'

            if materialize:
                safe = _safe_rel(canonical)
                dst = overlay_dir / pathlib.Path(*safe.parts)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise RuntimeError(f'SUPERSET_STAGING_COLLISION:{canonical}')
                shutil.copy2(selected.physical, dst)
                row['staged_path'] = str(dst)
                row['staged_verified'] = cache.sha256(dst) == selected_hash
                if len(groups) > 1:
                    archived = 0
                    for c, h in hashed:
                        _archive_variant(c.physical, variants_dir, c.label, c.relative)
                        archived += 1
                    row['archive_count'] = archived
            plan.append(row)
            if progress and idx % 2500 == 0:
                progress(f'planned {idx:,}/{len(keys):,} donor paths')

        counts = Counter(r['action'] for r in plan)
        categories = Counter(r['category'] for r in plan)
        selected_sources = Counter(r['selected_source'] for r in plan if r.get('selected_source'))
        hard_actions = {'TARGET_CASE_COLLISION', 'DONOR_CASE_COLLISION', 'SOURCE_FILE_MISSING'}
        hard = [r for r in plan if r['action'] in hard_actions]
        recovery_actions = {'RECOVER', 'RECOVER_DEDUPED', 'RECOVER_PREFERRED_VARIANT'}
        bad_stage = [r for r in plan if r['action'] in recovery_actions and materialize and not r.get('staged_verified')]
        state = 'REVIEW_REQUIRED' if hard or bad_stage else 'READY_STAGING'

        columns = [
            'action', 'canonical_path', 'target_path', 'category', 'deployability', 'reason',
            'selected_source', 'selected_path', 'selected_sha256', 'selected_size',
            'donor_candidate_count', 'distinct_hash_count', 'variant_count', 'archive_count',
            'staged_path', 'staged_verified',
        ]
        _write_tsv(out_dir / 'provenance.tsv', plan, columns)
        _write_tsv(out_dir / 'recover.tsv', [r for r in plan if r['action'] in recovery_actions], columns)
        _write_tsv(out_dir / 'variants.tsv', [r for r in plan if r['action'] == 'RECOVER_PREFERRED_VARIANT'], columns)
        _write_tsv(out_dir / 'reference_only.tsv', [r for r in plan if r['action'] == 'ARCHIVE_REFERENCE_ONLY'], columns)
        _write_tsv(out_dir / 'excluded.tsv', [r for r in plan if r['action'] == 'EXCLUDE_NON_DEPLOYABLE'], columns)
        _write_tsv(out_dir / 'review.tsv', hard, columns)

        manifest = {
            'format': 'PT_ASSET_TREE_SUPERSET_V1',
            'status': 'PASS',
            'side': side.upper(),
            'aggregate_state': state,
            'target_root': str(target_root),
            'donor_roots': [{'label': label, 'root': str(root)} for label, root in donors],
            'donor_file_counts': donor_counts,
            'target_canonical_path_count': len(target),
            'donor_canonical_path_count': len(donor_index),
            'plan_row_count': len(plan),
            'action_counts': dict(counts),
            'category_counts': dict(categories),
            'selected_source_counts': dict(selected_sources),
            'hard_review_count': len(hard),
            'staging_hash_failure_count': len(bad_stage),
            'materialized': materialize,
            'overlay_root': str(overlay_dir) if materialize else '',
            'reference_variants_root': str(variants_dir) if materialize else '',
            'reference_only_root': str(reference_only_dir) if materialize else '',
            'target_modified': False,
            'hash_cache': str(cache.path),
            'hash_stats': {
                'cache_hits': cache.stats.cache_hits,
                'legacy_cache_hits': cache.stats.legacy_cache_hits,
                'calculated': cache.stats.calculated,
                'bytes_read': cache.stats.bytes_read,
            },
            'notes': [
                'Existing Summit paths always win in the generic superset; donor content for an existing path is not silently substituted.',
                'Only target-missing runtime/data files are materialized in the overlay.',
                'Authoring/archive/unknown client files are preserved as reference-only evidence, not promoted to runtime.',
                'Distinct donor variants for a missing path choose configured donor priority while archiving every live variant.',
                'No target client/server/source file is modified.',
            ],
        }
        (out_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        validation = {
            'format': 'PT_ASSET_TREE_SUPERSET_VALIDATION_V1',
            'status': 'PASS' if not bad_stage else 'FAIL',
            'aggregate_state': state,
            'side': side.upper(),
            'recovery_count': sum(counts[x] for x in recovery_actions),
            'preferred_variant_count': counts.get('RECOVER_PREFERRED_VARIANT', 0),
            'reference_only_count': counts.get('ARCHIVE_REFERENCE_ONLY', 0),
            'excluded_count': counts.get('EXCLUDE_NON_DEPLOYABLE', 0),
            'hard_review_count': len(hard),
            'hard_review_action_counts': dict(Counter(r['action'] for r in hard)),
            'staging_hash_failure_count': len(bad_stage),
            'target_modified': False,
        }
        (out_dir / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        bundle = _report_bundle(out_dir, [
            'manifest.json', 'validation.json', 'provenance.tsv', 'recover.tsv', 'variants.tsv',
            'reference_only.tsv', 'excluded.tsv', 'review.tsv',
        ])
        return {
            'format': manifest['format'],
            'status': 'PASS',
            'side': side.upper(),
            'aggregate_state': state,
            'action_counts': dict(counts),
            'category_counts': dict(categories),
            'hard_review_count': len(hard),
            'staging_hash_failure_count': len(bad_stage),
            'overlay_root': manifest['overlay_root'],
            'manifest': str(out_dir / 'manifest.json'),
            'validation': str(out_dir / 'validation.json'),
            'reports_bundle': str(bundle),
            'target_modified': False,
            'hash_stats': manifest['hash_stats'],
        }
    finally:
        cache.close()


def build_client_superset(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    donor_clients: Iterable[str],
    *,
    materialize: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return build_tree_superset(project_root, client_root, donor_clients, side='client', materialize=materialize, progress=progress)


def build_server_superset(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    donor_servers: Iterable[str],
    *,
    materialize: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    return build_tree_superset(project_root, server_root, donor_servers, side='server', materialize=materialize, progress=progress)


def _class_recovery_coverage(class_manifest_path: pathlib.Path, generic_client_recover_tsv: pathlib.Path, client_root: pathlib.Path) -> dict[str, Any]:
    class_manifest = json.loads(class_manifest_path.read_text(encoding='utf-8'))
    generic_paths: set[str] = set()
    if generic_client_recover_tsv.is_file():
        with generic_client_recover_tsv.open('r', encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f, delimiter='\t'):
                p = _norm(row.get('canonical_path') or '')
                if p:
                    generic_paths.add(p.casefold())
    missing: list[str] = []
    expected = 0
    for row in class_manifest.get('rows') or []:
        if row.get('action') not in {'RECOVER', 'RECOVER_DEDUPED', 'RECOVER_PREFERRED_VARIANT'}:
            continue
        expected += 1
        rel = _norm(row.get('target_relative_path') or row.get('logical_path') or '')
        if not rel:
            missing.append(str(row.get('logical_path') or ''))
            continue
        # Generic superset either stages it because target lacks it, or target now
        # already had it at the time of the class audit (class audit would KEEP in that case).
        if rel.casefold() not in generic_paths and not (client_root / pathlib.Path(*_safe_rel(rel).parts)).is_file():
            missing.append(rel)
    return {
        'expected_class_recoveries': expected,
        'covered_by_generic_superset_or_target': expected - len(missing),
        'uncovered_count': len(missing),
        'uncovered_paths': missing[:200],
        'check': 'PASS' if not missing else 'FAIL',
    }


def build_summit_superset(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None,
    reference_source_root: str | pathlib.Path | None,
    donor_clients: Iterable[str],
    donor_servers: Iterable[str],
    materialize: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    server_root = pathlib.Path(server_root).resolve()
    out_dir = project_root / 'pt_build' / 'aggregate' / 'summit' / 'all'
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def p(msg: str):
        if progress:
            progress(msg)

    p('auditing 10-class contract plan (no duplicate class overlay)')
    class_result = build_player_class_aggregation(
        project_root,
        client_root,
        source_root=source_root,
        reference_source_root=reference_source_root,
        donor_clients=donor_clients,
        classes=TARGET_CLASSES,
        materialize=False,
        progress=(lambda msg: p('classes: ' + msg)),
    )
    p('building generic client superset')
    client_result = build_client_superset(
        project_root, client_root, donor_clients,
        materialize=materialize,
        progress=(lambda msg: p('client: ' + msg)),
    )
    p('building generic server superset')
    server_result = build_server_superset(
        project_root, server_root, donor_servers,
        materialize=materialize,
        progress=(lambda msg: p('server: ' + msg)),
    )

    class_manifest = pathlib.Path(class_result['manifest'])
    client_recover = pathlib.Path(client_result['manifest']).parent / 'recover.tsv'
    coverage = _class_recovery_coverage(class_manifest, client_recover, client_root)
    runtime_ready = bool(class_result.get('runtime_ready'))
    asset_ready = (
        class_result.get('core_unresolved_count', 0) == 0
        and client_result.get('hard_review_count', 0) == 0
        and server_result.get('hard_review_count', 0) == 0
        and coverage['check'] == 'PASS'
        and client_result.get('staging_hash_failure_count', 0) == 0
        and server_result.get('staging_hash_failure_count', 0) == 0
    )
    state = 'ASSET_SUPERSET_READY_RUNTIME_BLOCKED' if asset_ready and not runtime_ready else ('READY' if asset_ready else 'REVIEW_REQUIRED')

    summary = {
        'format': 'PT_ASSET_SUMMIT_SUPERSET_V1',
        'status': 'PASS',
        'aggregate_state': state,
        'asset_superset_ready': asset_ready,
        'runtime_ready': runtime_ready,
        'client_root': str(client_root),
        'server_root': str(server_root),
        'player_classes': class_result,
        'client_superset': client_result,
        'server_superset': server_result,
        'class_recovery_coverage': coverage,
        'target_client_modified': False,
        'target_server_modified': False,
        'notes': [
            'This combined run stages missing donor assets but never writes the live client/server.',
            'Player-class contracts remain the authoritative core check; the generic client superset adds supplemental donor assets.',
            'Server runtime/log/state trees are excluded from aggregation.',
            'Runtime/source migration blockers are reported separately from asset-superset readiness.',
        ],
    }
    (out_dir / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    validation = {
        'format': 'PT_ASSET_SUMMIT_SUPERSET_VALIDATION_V1',
        'status': 'PASS' if asset_ready else 'FAIL',
        'aggregate_state': state,
        'asset_superset_ready': asset_ready,
        'runtime_ready': runtime_ready,
        'class_core_unresolved_count': class_result.get('core_unresolved_count', 0),
        'class_optional_review_count': class_result.get('optional_review_count', 0),
        'client_hard_review_count': client_result.get('hard_review_count', 0),
        'server_hard_review_count': server_result.get('hard_review_count', 0),
        'class_recovery_coverage': coverage,
        'target_client_modified': False,
        'target_server_modified': False,
    }
    (out_dir / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # One small artifact for the next feedback cycle; component report bundles are
    # nested inside without any staged game/server assets.
    bundle = out_dir / 'reports_bundle.zip'
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(out_dir / 'manifest.json', arcname='summit/manifest.json')
        z.write(out_dir / 'validation.json', arcname='summit/validation.json')
        for prefix, result in (('player_classes', class_result), ('client_superset', client_result), ('server_superset', server_result)):
            for key in ('manifest', 'validation'):
                raw = result.get(key)
                if raw and pathlib.Path(raw).is_file():
                    z.write(pathlib.Path(raw), arcname=f'{prefix}/{pathlib.Path(raw).name}')
            if prefix == 'player_classes':
                base = pathlib.Path(class_result['manifest']).parent
                for name in ('provenance.tsv','recover.tsv','variants.tsv','optional_gaps.tsv','conflicts.tsv','missing.tsv'):
                    pth = base / name
                    if pth.is_file(): z.write(pth, arcname=f'{prefix}/{name}')
            else:
                base = pathlib.Path(result['manifest']).parent
                for name in ('provenance.tsv','recover.tsv','variants.tsv','reference_only.tsv','excluded.tsv','review.tsv'):
                    pth = base / name
                    if pth.is_file(): z.write(pth, arcname=f'{prefix}/{name}')

    return {
        'format': summary['format'],
        'status': 'PASS',
        'aggregate_state': state,
        'asset_superset_ready': asset_ready,
        'runtime_ready': runtime_ready,
        'client_overlay_root': client_result.get('overlay_root'),
        'server_overlay_root': server_result.get('overlay_root'),
        'class_core_unresolved_count': class_result.get('core_unresolved_count', 0),
        'class_optional_review_count': class_result.get('optional_review_count', 0),
        'client_action_counts': client_result.get('action_counts'),
        'server_action_counts': server_result.get('action_counts'),
        'class_recovery_coverage': coverage,
        'manifest': str(out_dir / 'manifest.json'),
        'validation': str(out_dir / 'validation.json'),
        'reports_bundle': str(bundle),
        'target_client_modified': False,
        'target_server_modified': False,
    }
