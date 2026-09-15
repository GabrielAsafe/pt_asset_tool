from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_edit import _workspace_root
from .rare_rigid_large_production import (
    POLICY_REL as SINGLE_POLICY_REL,
    load_and_validate_policy as load_and_validate_single_policy,
    write_promoted as write_single_promoted,
)
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_cross_object_live_writer_candidate import (
    CANDIDATE_TEST,
    write_at_dragon_cross_object_candidate_workspace,
)

RELEASE_VERSION = '0.8.30'
POLICY_FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_PRODUCTION_POLICY_V1'
POLICY_REL = pathlib.Path('pt_build/rare_rigid_cross_object_production_policy_v0830.json')
MANUAL_REL = pathlib.Path('pt_build/rare_rigid_cross_object_manual_candidate_v0828/at_dragon.smd/manual_write_result.json')
LIVE_REL = pathlib.Path('pt_build/rare_rigid_cross_object_live_writer_candidate_workflow_v0826.json')
PROMOTED_TEST = 'RARE_RIGID_ARTIST_GUARDED_CROSS_OBJECT_TRANSACTION_WRITE'
PROMOTED_SCOPE = 'AT_DRAGON_CROSS_OBJECT_EXACT_TWO_OR_THREE_OBJECTS_EXACTLY_TWO_VERTICES_EACH_INTERIOR_ATOMIC_TRANSACTION'
ALLOWED_OBJECT_COUNTS = (2, 3)
VERTICES_PER_OBJECT = 2
MAX_TOTAL_CHANGED = 8


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    import json
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(pathlib.Path(root) / rel) for rel in EXPECTED_WRITER_HASHES}


def load_and_validate_cross_policy(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    # Cross-object authorization is additive and may never weaken the already-certified
    # V0.8.21 single-object policy.
    single = load_and_validate_single_policy(root)
    p = root / POLICY_REL
    if not p.is_file():
        raise RuntimeError(f'CROSS_OBJECT_PRODUCTION_POLICY_MISSING:{p}')
    policy = _json(p)
    checks = [
        policy.get('format') == POLICY_FORMAT,
        policy.get('status') == 'PASS',
        policy.get('release_version') == RELEASE_VERSION,
        policy.get('cross_object_production_authorized') is True,
        policy.get('logical') == TARGET,
        list(policy.get('allowed_object_counts') or []) == list(ALLOWED_OBJECT_COUNTS),
        int(policy.get('vertices_per_object', -1)) == VERTICES_PER_OBJECT,
        int(policy.get('max_total_changed_vertices', -1)) == MAX_TOTAL_CHANGED,
        policy.get('interior_only') is True,
        policy.get('extent_bounds_changes_authorized') is False,
        policy.get('topology_authorized') is False,
        policy.get('more_than_3_objects_authorized') is False,
        policy.get('other_vertices_per_object_shapes_authorized') is False,
        policy.get('more_than_8_total_vertices_authorized') is False,
        policy.get('manual_artist_proof') is True,
        policy.get('live_writer_candidate_proof') is True,
        policy.get('writer_hashes') == EXPECTED_WRITER_HASHES,
        int(single.get('production_max_vertices', -1)) == 8,
        single.get('single_object_only') is True,
    ]
    if not all(checks):
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_NOT_STRICT_PASS')
    if _writer_hashes(root) != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_WRITER_HASH_MISMATCH')
    manual = root / MANUAL_REL
    live = root / LIVE_REL
    if not manual.is_file() or _sha256(manual) != policy.get('manual_report_sha256'):
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_MANUAL_EVIDENCE_MISMATCH')
    if not live.is_file() or _sha256(live) != policy.get('live_report_sha256'):
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_LIVE_EVIDENCE_MISMATCH')
    single_path = root / SINGLE_POLICY_REL
    if not single_path.is_file() or _sha256(single_path) != policy.get('single_object_policy_sha256'):
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_SINGLE_POLICY_MISMATCH')
    return policy


class _CrossObjectProductionCertificationProxy:
    def __init__(self, backing: CertificationRegistry):
        self.backing = backing
        self.directory = backing.directory
        self.path = backing.path

    def records(self) -> list[dict]:
        return self.backing.records()

    def add(self, **kwargs: Any) -> dict:
        test = str(kwargs.get('test') or '')
        metadata = dict(kwargs.get('metadata') or {})
        object_count = int(metadata.get('object_count', -1))
        total = int(metadata.get('artist_changed_vertices', -1))
        per = metadata.get('per_object_changed_vertex_indices') or {}
        strict_shape = (
            test == CANDIDATE_TEST
            and object_count in ALLOWED_OBJECT_COUNTS
            and total == object_count * VERTICES_PER_OBJECT
            and total <= MAX_TOTAL_CHANGED
            and sorted(len(v) for v in per.values()) == [VERTICES_PER_OBJECT] * object_count
        )
        if not strict_shape:
            raise RuntimeError('CROSS_OBJECT_PRODUCTION_CERTIFICATION_SHAPE_NOT_AUTHORIZED')
        metadata.update({
            'candidate_only': False,
            'production_authorized': True,
            'promotion_release': RELEASE_VERSION,
            'original_candidate_test': test,
            'original_candidate_write_scope': metadata.get('write_scope'),
            'write_scope': PROMOTED_SCOPE,
            'allowed_object_counts': list(ALLOWED_OBJECT_COUNTS),
            'vertices_per_object': VERTICES_PER_OBJECT,
            'max_total_changed_vertices': MAX_TOTAL_CHANGED,
        })
        kwargs['test'] = PROMOTED_TEST
        kwargs['metadata'] = metadata
        notes = str(kwargs.get('notes') or '')
        kwargs['notes'] = (notes + ' V0.8.30 promoted exact cross-object production shape.').strip()
        return self.backing.add(**kwargs)


def write_cross_object_promoted(
    root: pathlib.Path,
    logical: str,
    output: pathlib.Path | None = None,
    *,
    workspace_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    if logical.lower() not in {TARGET.lower(), 'at_dragon.smd'}:
        raise RuntimeError(f'CROSS_OBJECT_PROMOTED_WRITER_ONLY_AT_DRAGON:{logical}')
    policy = load_and_validate_cross_policy(root)
    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    cert = CertificationRegistry(settings.certifications_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if _sha256(source) != policy.get('client_source_sha256'):
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_POLICY_CLIENT_SOURCE_HASH_MISMATCH')

    work = pathlib.Path(workspace_root).resolve() if workspace_root is not None else _workspace_root(root).resolve()
    final = pathlib.Path(output).expanduser() if output is not None else (work / 'output' / 'at_dragon_guarded_edit.smd')
    if not final.is_absolute():
        final = (root / final).resolve()
    proxy = _CrossObjectProductionCertificationProxy(cert)
    result = write_at_dragon_cross_object_candidate_workspace(
        reg, resolver, proxy, settings,
        project_root=root, workspace_root=work, output=final,
    )
    object_count = int(result.get('object_count', -1))
    total = int(result.get('artist_changed_vertices', -1))
    per = result.get('per_object_changed_vertex_indices') or {}
    if object_count not in ALLOWED_OBJECT_COUNTS:
        raise RuntimeError(f'CROSS_OBJECT_PRODUCTION_OBJECT_COUNT_NOT_AUTHORIZED:{object_count}')
    if total != object_count * VERTICES_PER_OBJECT or total > MAX_TOTAL_CHANGED:
        raise RuntimeError(f'CROSS_OBJECT_PRODUCTION_VERTEX_SHAPE_NOT_AUTHORIZED:{object_count}:{total}')
    if sorted(len(v) for v in per.values()) != [VERTICES_PER_OBJECT] * object_count:
        raise RuntimeError('CROSS_OBJECT_PRODUCTION_PER_OBJECT_VERTEX_SHAPE_NOT_AUTHORIZED')
    result.update({
        'candidate_only': False,
        'production_authorized': True,
        'cross_object_live_write_authorized': True,
        'promotion_release': RELEASE_VERSION,
        'production_cross_object_policy': str(root / POLICY_REL),
        'production_single_object_max_vertices': 8,
        'production_cross_object_allowed_object_counts': list(ALLOWED_OBJECT_COUNTS),
        'production_cross_object_vertices_per_object': VERTICES_PER_OBJECT,
        'production_cross_object_max_total_changed_vertices': MAX_TOTAL_CHANGED,
        'candidate_certification_test': PROMOTED_TEST,
        'candidate_write_scope': PROMOTED_SCOPE,
    })
    return result


def write_production_dispatch(root: pathlib.Path, logical: str, output: pathlib.Path | None = None, *, workspace_root: pathlib.Path | None = None) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    # Preserve the V0.8.21 single-object path exactly.  Only an explicit multi-object
    # extraction rejection is eligible for the V0.8.30 cross-object path.
    try:
        return write_single_promoted(root, logical, output, workspace_root=workspace_root)
    except Exception as exc:
        if 'MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED' not in str(exc):
            raise
    load_and_validate_cross_policy(root)
    return write_cross_object_promoted(root, logical, output, workspace_root=workspace_root)
