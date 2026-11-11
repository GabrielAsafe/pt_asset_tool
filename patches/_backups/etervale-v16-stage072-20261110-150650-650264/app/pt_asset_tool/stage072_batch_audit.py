"""V13: exhaustive, resumable and non-destructive Stage0.72 map audit.

The default static pass checks every SMD Stage0.72 in the configured client,
including required textures and the V12 view/paint semantics. Optional
--blender performs native importer/transport checks and applies the V12 viewer
proxy in a disposable, unsaved Blender process. Painting itself remains a
human, Blender-UI task.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import time
from typing import Any

from .app_config import discover_client_root
from .resolver import ClientResolver
from .stage072_corpus import HEADER, parse_stage072
from .stage072_paint_policy import KNOWN_UNRECOVERABLE_TEXTURES, canonical_reference
from .stage072_texture_audit import _used_material_texture_refs, runtime_trailing_space_alias, serialized_reference_shape
from .stage072_view_axes import VIEW_AXIS_PROFILE, matrix3_determinant, to_blender_view_xyz
from .utils import atomic_write_json, append_jsonl

FORMAT = 'PT_ETERVALE_STAGE072_ALL_MAPS_V13'
VERSION = 1


def find_maps(client_root: Path) -> list[str]:
    """Discover by physical header, not by a name or legacy registry guess."""
    root = Path(client_root).resolve(strict=True)
    maps = []
    for path in root.rglob('*'):
        if path.is_symlink() or not path.is_file() or path.suffix.casefold() != '.smd':
            continue
        if root not in path.resolve().parents:
            continue
        with path.open('rb') as f:
            if f.read(len(HEADER)) != HEADER:
                continue
        maps.append(path.relative_to(root).as_posix())
    return sorted(maps, key=lambda x: (x.casefold(), x))


def _details(issue: dict) -> dict:
    return {k: issue[k] for k in ('reference', 'material', 'slot', 'kind', 'face_uses', 'classification', 'resolution', 'error') if k in issue}


def audit_map(root: Path, rel: str, resolver: ClientResolver, *, stage: int = 0) -> dict:
    if not 0 <= stage <= 7:
        raise ValueError('STAGE_RANGE_INVALID')
    root = root.resolve(strict=True)
    file = root.joinpath(*PurePosixPath(rel).parts)
    stat = file.stat()
    row: dict[str, Any] = {
        'asset': rel, 'audit_version': VERSION, 'client_root': str(root),
        'signature': {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
        'stage': stage, 'format': 'SMD_STAGE_072', 'parse': 'NOT_CHECKED',
        'view_policy': 'NOT_CHECKED', 'paint_policy': 'NOT_CHECKED',
        'blender': 'NOT_RUN', 'client_modified': False,
    }
    try:
        if file.is_symlink() or root not in file.resolve().parents:
            raise ValueError('STAGE_PATH_OUTSIDE_CLIENT_OR_SYMLINK')
        parsed = parse_stage072(file)
        if parsed.get('full_parse') != 'PASS':
            raise ValueError('STAGE072_PARSER_INCOMPLETE:' + str(parsed.get('errors', {}))[:600])
        row['parse'] = 'PASS'
        row['source_sha256'] = parsed.get('sha256')
        row['vertices'] = int((parsed.get('counts') or {}).get('vertices') or 0)
        row['faces'] = int((parsed.get('counts') or {}).get('faces') or 0)
        row['materials'] = int((parsed.get('counts') or {}).get('materials') or 0)
        row['lights'] = int((parsed.get('counts') or {}).get('lights') or 0)
        row['max_texlink_depth'] = int(parsed.get('max_texlink_depth') or 0)
        row['area_encoding'] = (parsed.get('area') or {}).get('encoding')
        row['uv_distinct_multilayer_faces'] = int(parsed.get('uv_distinct_multilayer_faces') or 0)
        bounds = parsed.get('bbox_fixed') or {}
        lo, hi = bounds.get('min'), bounds.get('max')
        if lo is None or hi is None:
            raise ValueError('STAGE072_BOUNDS_MISSING')
        dims = [float(hi[i] - lo[i]) / 256.0 for i in range(3)]
        det = matrix3_determinant()
        if det != -1.0 or to_blender_view_xyz((3, 5, 7)) != (3, 7, 5):
            raise ValueError('V12_VIEW_AXES_POLICY_INVALID')
        row['source_dims_xyz'] = dims
        row['blender_dims_xyz'] = [dims[0], dims[2], dims[1]]
        row['view_policy'] = 'PASS_STATIC_VIEW_BASIS_NOT_RENDERED'
        row['view_axis_profile'] = VIEW_AXIS_PROFILE
        row['view_determinant'] = det
        row['view_scale'] = min(1.0, 100.0 / max(1.0, *dims))

        affected = []
        known = []
        bad = []
        alias_rows = []
        seen = set()
        used = _used_material_texture_refs(parsed)
        for texture in used:
            logical = str(texture['logical'])
            classification = 'PRESENT'
            resolution = ''
            error = ''
            try:
                resolver.resolve(logical)
            except FileNotFoundError:
                alias = runtime_trailing_space_alias(logical)
                if alias:
                    try:
                        resolver.resolve(alias)
                    except FileNotFoundError:
                        classification = 'MISSING_CLIENT'
                    except Exception as exc:
                        classification, error = 'BLOCKED_RESOLVER_COLLISION', str(exc)[:1200]
                    else:
                        classification, resolution = 'RUNTIME_TRAILING_SPACE_ALIAS', alias
                elif serialized_reference_shape(logical) != 'FILE_LIKE_REFERENCE':
                    classification = 'INVALID_SERIALIZED_REFERENCE'
                else:
                    classification = 'MISSING_CLIENT'
            except Exception as exc:
                classification, error = 'BLOCKED_RESOLVER_COLLISION', f'{type(exc).__name__}: {exc}'[:1200]
            issue = {'reference': logical, 'material': texture['material_id'],
                     'kind': texture['kind'], 'slot': texture['slot'],
                     'face_uses': texture['face_uses'], 'classification': classification}
            if resolution:
                issue['resolution'] = resolution
            if error:
                issue['error'] = error
            # A documented Ricarten exception is tied to the original map,
            # target stage=0, and the exact logical reference. Do not convert
            # unrelated missing textures into a PASS.
            if (classification == 'MISSING_CLIENT' and
                rel.casefold() == 'field/ricarten/village-2.smd' and stage == 0 and
                canonical_reference(logical) in KNOWN_UNRECOVERABLE_TEXTURES):
                issue.update(classification='KNOWN_MISSING_UNPAINTABLE',
                             resolution='NO_SUBSTITUTE_OR_GAME_ASSET_CHANGE')
                classification = issue['classification']
            key = (logical.casefold(), issue['material'], issue['kind'], issue['slot'])
            if key in seen:
                continue
            seen.add(key)
            if classification == 'KNOWN_MISSING_UNPAINTABLE':
                known.append(issue)
            elif classification == 'RUNTIME_TRAILING_SPACE_ALIAS':
                alias_rows.append(issue)
            elif classification != 'PRESENT':
                bad.append(issue)
            if classification != 'PRESENT':
                affected.append(issue)

        row['texture_reference_count'] = len(seen)
        row['known_missing_count'] = len(known)
        row['missing_count'] = sum(x['classification'] == 'MISSING_CLIENT' for x in bad)
        row['invalid_reference_count'] = sum(x['classification'] == 'INVALID_SERIALIZED_REFERENCE' for x in bad)
        row['collision_count'] = sum(x['classification'] == 'BLOCKED_RESOLVER_COLLISION' for x in bad)
        row['runtime_alias_count'] = len(alias_rows)
        row['texture_issues'] = [_details(x) for x in affected]
        if row['collision_count']:
            row['paint_policy'] = 'BLOCKED_CASE_COLLISION'
        elif bad:
            row['paint_policy'] = 'REVIEW_UNRESOLVED_REFERENCES'
        elif row['max_texlink_depth'] <= stage:
            row['paint_policy'] = 'NOT_APPLICABLE_NO_TARGET_UV_LAYER'
        elif known:
            row['paint_policy'] = 'PASS_STATIC_WITH_KNOWN_UNPAINTABLE_NOT_BLENDER_TESTED'
        else:
            row['paint_policy'] = 'PASS_STATIC_CANDIDATE_NOT_BLENDER_TESTED'
        row['status'] = 'REVIEW_REQUIRED' if bad else ('PASS_STATIC_WITH_EXCEPTION' if known else 'PASS_STATIC')
        row['static_status'] = row['status']
    except Exception as exc:
        row.update({'status': 'FAIL_PARSE_OR_SOURCE', 'static_status': 'FAIL_PARSE_OR_SOURCE', 'parse': 'FAIL',
                    'error': f'{type(exc).__name__}: {exc}'[:1600]})
    return row


def _load_checkpoint(path: Path, stage: int) -> dict[str, dict]:
    output: dict[str, dict] = {}
    if not path.is_file():
        return output
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            obj = json.loads(line)
            if obj.get('stage') == stage and isinstance(obj.get('asset'), str):
                output[obj['asset']] = obj
        except (ValueError, TypeError):
            continue
    return output


def _still_current(row: dict, root: Path) -> bool:
    if row.get('audit_version') != VERSION or row.get('client_root') != str(root):
        return False
    try:
        st = (root / row['asset']).stat()
        return row.get('signature') == {'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    except (OSError, KeyError):
        return False


def _run_worker(project: Path, root: Path, rel: str, out: Path, timeout: int) -> tuple[str, dict]:
    """Isolate Blender failures and impose one-map deadline; never run GUI."""
    safe = hashlib.sha256(rel.encode('utf-8')).hexdigest()[:16]
    task = out / 'blender_tasks' / safe
    task.mkdir(parents=True, exist_ok=True)
    report = task / 'worker_result.json'
    report.unlink(missing_ok=True)
    args = [sys.executable, str(project / 'pt_stage072_batch_audit.py'),
            '--worker-preview', '--client-root', str(root), '--asset', rel,
            '--output', str(out), '--worker-report', str(report)]
    log = task / 'worker.log'
    print(f'STAGE072_BLENDER_START asset={rel} timeout={timeout}s log={log}', flush=True)
    started = time.monotonic()
    with log.open('wb') as stream:
        proc = subprocess.Popen(args, cwd=str(project), stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=(os.name != 'nt'))
        while True:
            remain = timeout - (time.monotonic() - started)
            if remain <= 0:
                if os.name != 'nt':
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait()
                return 'FAIL_BLENDER_TIMEOUT', {'error': f'worker exceeded {timeout}s', 'worker_log': str(log)}
            try:
                proc.wait(timeout=min(20.0, remain))
                break
            except subprocess.TimeoutExpired:
                print(f'STAGE072_BLENDER_RUNNING asset={rel} elapsed={int(time.monotonic()-started)}s log={log}', flush=True)
    if not report.is_file():
        return 'FAIL_BLENDER_WORKER', {'returncode': proc.returncode, 'worker_log': str(task / 'worker.log')}
    try:
        record = json.loads(report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 'FAIL_BLENDER_REPORT', {'returncode': proc.returncode}
    return str(record.get('status') or 'FAIL_BLENDER_REPORT'), record


def run_all(*, project: Path, client_root: Path, output: Path, stage: int = 0,
            blender: bool = False, limit: int = 0, fresh: bool = False,
            timeout: int = 360, quiet: bool = False) -> dict:
    project = project.resolve(strict=True)
    root = client_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('CLIENT_ROOT_NOT_DIRECTORY')
    if stage not in range(8):
        raise ValueError('STAGE_RANGE_INVALID')
    out = output.resolve()
    if out == root or root in out.parents:
        raise ValueError('REPORT_INSIDE_CLIENT_ROOT_REFUSED')
    out.mkdir(parents=True, exist_ok=True)
    files = find_maps(root)
    complete_size = len(files)
    if limit > 0:
        files = files[:limit]
    checkpoint = out / f'stage_{stage}_checkpoint.jsonl'
    existing = {} if fresh else _load_checkpoint(checkpoint, stage)
    if fresh:
        checkpoint.unlink(missing_ok=True)
    resolver = ClientResolver(root)
    resolver.build_index()
    results = []
    for index, rel in enumerate(files, 1):
        cached = existing.get(rel)
        valid_cache = bool(cached and _still_current(cached, root))
        needs_blender = bool(blender and valid_cache and (
            cached.get('collision_count') and cached.get('blender') != 'BLOCKED_TEXTURE_COLLISION' or
            cached.get('parse') == 'PASS' and not cached.get('collision_count')
            and cached.get('blender') != 'PASS_BLENDER_TRANSPORT_AND_VIEW'))
        if valid_cache and not needs_blender:
            row = dict(cached)
            resumed = True
        else:
            resumed = False
            row = (dict(cached) if valid_cache else audit_map(root, rel, resolver, stage=stage))
            row.setdefault('static_status', row.get('status'))
            row['status'] = row['static_status']  # discard previous Blender failure before retry
            row['audit_version'] = VERSION
            row['client_root'] = str(root)
            if blender and row.get('parse') == 'PASS' and not row.get('collision_count'):
                status, details = _run_worker(project, root, rel, out, max(30, int(timeout)))
                row['blender'] = status
                row['blender_evidence'] = details
                if status != 'PASS_BLENDER_TRANSPORT_AND_VIEW':
                    row['status'] = 'FAIL_BLENDER_RUNTIME'
            elif blender and row.get('collision_count'):
                row['blender'] = 'BLOCKED_TEXTURE_COLLISION'
            append_jsonl(checkpoint, row)
        results.append(row)
        if not quiet:
            print(f'[{index}/{len(files)}] {row["status"]} view={row.get("view_policy")} '
                  f'paint={row.get("paint_policy")} blender={row.get("blender")} '
                  f'{"[cached] " if resumed else ""}{rel}', flush=True)

    counts = dict(sorted(collections.Counter(x.get('status', 'UNKNOWN') for x in results).items()))
    paints = dict(sorted(collections.Counter(x.get('paint_policy', 'UNKNOWN') for x in results).items()))
    blenders = dict(sorted(collections.Counter(x.get('blender', 'UNKNOWN') for x in results).items()))
    unpassed = sum(x.get('status') in {'FAIL_PARSE_OR_SOURCE', 'FAIL_BLENDER_RUNTIME', 'REVIEW_REQUIRED'} for x in results)
    overall = 'FAIL_OR_REVIEW_REQUIRES_ACTION' if unpassed else (
        'PASS_HEADLESS_WITH_REVIEW_NOT_VISUAL_CERTIFIED' if blender else 'PASS_STATIC_NOT_BLENDER_OR_PAINT_CERTIFIED')
    summary = {
        'format': FORMAT, 'version': VERSION, 'status': overall,
        'stage': stage, 'project_root': str(project), 'client_root': str(root),
        'stage_files_discovered': complete_size, 'files_audited': len(results),
        'limited_scan': limit > 0, 'blender_executed': blender,
        'counts': counts, 'paint_counts': paints, 'blender_counts': blenders,
        'known_missing_total': sum(x.get('known_missing_count', 0) for x in results),
        'missing_total': sum(x.get('missing_count', 0) for x in results),
        'case_collision_total': sum(x.get('collision_count', 0) for x in results),
        'not_runtime_visual_certified': True, 'not_paint_ui_certified': True,
        'game_assets_modified': False,
        'report_file': str(out / f'stage_{stage}_summary.json'),
        'csv_file': str(out / f'stage_{stage}_maps.csv'),
        'checkpoint_file': str(checkpoint),
    }
    atomic_write_json(Path(summary['report_file']), dict(summary, rows=results))
    with Path(summary['csv_file']).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['asset','status','parse','view_policy','paint_policy','blender',
                'vertices','faces','materials','lights','max_texlink_depth','known_missing_count',
                'missing_count','collision_count','invalid_reference_count','runtime_alias_count','source_sha256'])
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, '') for k in writer.fieldnames})
    return summary


def worker_preview(*, project: Path, root: Path, rel: str, output: Path, report: Path) -> int:
    """Native Stage0.72 transport and view-proxy probe in one isolated worker."""
    from .certification import CertificationRegistry
    from .config import Settings
    from .registry import Asset
    from .utils import run_logged
    from .validation import ValidationContext, ValidationRunner
    digest = hashlib.sha256(rel.encode('utf-8')).hexdigest()[:16]
    asset = Asset(asset_id='STG-BATCH-' + digest.upper(), primary_path=rel,
                  basename=PurePosixPath(rel).name, extension='.smd', category='MAP_STAGE',
                  family='STAGE_072_MAP_SEPARATE', kind='SMD_STAGE_072', compatibility_tier='AUDIT_ONLY',
                  size=None, issues=[])
    settings = Settings(project_root=project, client_root=root, inventory=project / 'pt_build/state/asset_registry/asset_inventory.json',
                        pairing=project / 'pt_build/state/asset_registry/inx_physical_pairing.csv',
                        certifications_dir=output / 'certifications',
                        work_dir=output / 'preview_work')
    resolver = ClientResolver(root)
    cert = CertificationRegistry(settings.certifications_dir)
    result = {'status': 'FAIL_BLENDER_WORKER', 'asset': rel}
    try:
        preview = ValidationRunner(ValidationContext(settings, resolver, cert)).stage072_preview(asset)
        if preview.get('stage072_blender_transport') != 'PASS':
            raise RuntimeError('STAGE072_PREVIEW_TRANSPORT_NOT_PASS')
        test_dir = output / 'blender_tasks' / digest
        test_dir.mkdir(parents=True, exist_ok=True)
        check = test_dir / 'view_result.json'
        cmd = settings.blender_command() + ['--background', str(preview['preview_blend']),
            '--python-exit-code', '1', '--python', str(project / 'pt_asset_tool/blender/audit_stage072_view_batch.py'),
            '--', '--report', str(check)]
        run_logged(cmd, test_dir / '03_view_check.log')
        evidence = json.loads(check.read_text(encoding='utf-8'))
        if evidence.get('check') != 'PASS':
            raise RuntimeError('V12_VIEW_PROXY_CHECK_FAILED:' + str(evidence.get('errors')))
        result = {'status': 'PASS_BLENDER_TRANSPORT_AND_VIEW', 'asset': rel,
                  'transport_summary': preview['stage072_blender_transport'],
                  'view_report': str(check), 'view_evidence': evidence,
                  'preview_blend': preview['preview_blend']}
    except Exception as exc:
        result.update({'error': f'{type(exc).__name__}: {exc}'[:2000]})
    atomic_write_json(report, result)
    return 0 if result['status'] == 'PASS_BLENDER_TRANSPORT_AND_VIEW' else 2
