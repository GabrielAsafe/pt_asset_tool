from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_cross_object_production import (
    POLICY_REL as CROSS_POLICY_REL,
    load_and_validate_cross_policy,
    write_production_dispatch as write_pre_extent_dispatch,
)
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_multibone_extent_live_writer_candidate import (
    CANDIDATE_TEST,
    EXACT_BOUND_FIELD_SHAPES,
    write_at_dragon_multibone_outward_extent_candidate_workspace,
)
from .rare_rigid_edit import _workspace_root

RELEASE_VERSION = '0.8.36'
POLICY_FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_PRODUCTION_POLICY_V1'
POLICY_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_production_policy_v0836.json')
MANUAL_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_manual_candidate_v0835/at_dragon.smd/manual_write_result.json')
LIVE_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_live_writer_candidate_workflow_v0833.json')
SAVED_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_saved_blender_workflow_v0832.json')
PROMOTED_TEST = 'RARE_RIGID_ARTIST_GUARDED_MULTIBONE_OUTWARD_EXTENT_WRITE'
PROMOTED_SCOPE = 'AT_DRAGON_ONE_OBJECT_EXACTLY_ONE_VERTEX_MULTIBONE_OUTWARD_EXTENT_EXACT_PROVEN_BOUND_FIELD_SHAPES_MONOTONIC_ONLY'
ALLOWED_TARGET_KINDS = ('maxX', 'maxZ', 'maxY', 'dBound', 'Bound')
ALLOWED_FIELD_SHAPES = {
    'maxX': frozenset({'maxX'}),
    'maxZ': frozenset({'maxZ'}),
    'maxY': frozenset({'maxY'}),
    'dBound': frozenset({'dBound'}),
    'Bound': frozenset({'maxY', 'dBound', 'Bound'}),
}


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


def load_and_validate_extent_policy(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    cross = load_and_validate_cross_policy(root)
    p = root / POLICY_REL
    if not p.is_file():
        raise RuntimeError(f'MULTIBONE_EXTENT_PRODUCTION_POLICY_MISSING:{p}')
    policy = _json(p)
    serialized_shapes = policy.get('allowed_bound_field_shapes') or {}
    normalized_shapes = {str(k): frozenset(str(x) for x in v) for k, v in serialized_shapes.items()}
    checks = [
        policy.get('format') == POLICY_FORMAT,
        policy.get('status') == 'PASS',
        policy.get('release_version') == RELEASE_VERSION,
        policy.get('logical') == TARGET,
        policy.get('multibone_outward_extent_production_authorized') is True,
        policy.get('one_object_only') is True,
        policy.get('exactly_one_changed_vertex') is True,
        list(policy.get('allowed_target_kinds') or []) == list(ALLOWED_TARGET_KINDS),
        normalized_shapes == ALLOWED_FIELD_SHAPES,
        policy.get('monotonic_expansion_only') is True,
        policy.get('multibone_affected_normals_required') is True,
        policy.get('extent_contraction_authorized') is False,
        policy.get('multi_vertex_extent_authorized') is False,
        policy.get('cross_object_extent_authorized') is False,
        policy.get('topology_authorized') is False,
        policy.get('manual_artist_proof') is True,
        policy.get('live_writer_candidate_proof') is True,
        policy.get('saved_blender_candidate_proof') is True,
        policy.get('writer_hashes') == EXPECTED_WRITER_HASHES,
        cross.get('cross_object_production_authorized') is True,
    ]
    if not all(checks):
        raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_POLICY_NOT_STRICT_PASS')
    if _writer_hashes(root) != EXPECTED_WRITER_HASHES:
        raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_POLICY_WRITER_HASH_MISMATCH')

    evidence = [
        (MANUAL_REL, 'manual_report_sha256', 'MANUAL'),
        (LIVE_REL, 'live_report_sha256', 'LIVE'),
        (SAVED_REL, 'saved_report_sha256', 'SAVED'),
        (SINGLE_POLICY_REL, 'single_object_policy_sha256', 'SINGLE_POLICY'),
        (CROSS_POLICY_REL, 'cross_object_policy_sha256', 'CROSS_POLICY'),
    ]
    for rel, key, label in evidence:
        ep = root / rel
        if not ep.is_file() or _sha256(ep) != policy.get(key):
            raise RuntimeError(f'MULTIBONE_EXTENT_PRODUCTION_POLICY_{label}_EVIDENCE_MISMATCH')
    return policy


class _MultiboneExtentProductionCertificationProxy:
    def __init__(self, backing: CertificationRegistry):
        self.backing = backing
        self.directory = backing.directory
        self.path = backing.path

    def records(self) -> list[dict]:
        return self.backing.records()

    def add(self, **kwargs: Any) -> dict:
        test = str(kwargs.get('test') or '')
        metadata = dict(kwargs.get('metadata') or {})
        kind = str(metadata.get('target_bound_kind') or '')
        changed = frozenset(str(x) for x in (metadata.get('changed_bound_fields') or []))
        strict_shape = (
            test == CANDIDATE_TEST
            and kind in ALLOWED_TARGET_KINDS
            and changed == ALLOWED_FIELD_SHAPES.get(kind)
            and int(metadata.get('affected_bone_count', 0)) >= 2
            and metadata.get('all_non_authorized_bytes_byte_identical') is True
            and metadata.get('bound_window_non_field_bytes_byte_identical') is True
            and metadata.get('atomic_output_replace') is True
        )
        if not strict_shape:
            raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_CERTIFICATION_SHAPE_NOT_AUTHORIZED')
        metadata.update({
            'candidate_only': False,
            'production_authorized': True,
            'promotion_release': RELEASE_VERSION,
            'original_candidate_test': test,
            'original_candidate_write_scope': metadata.get('write_scope'),
            'write_scope': PROMOTED_SCOPE,
            'one_object_only': True,
            'exactly_one_changed_vertex': True,
            'allowed_target_kinds': list(ALLOWED_TARGET_KINDS),
            'monotonic_expansion_only': True,
            'extent_contraction_authorized': False,
            'multi_vertex_extent_authorized': False,
            'cross_object_extent_authorized': False,
            'topology_authorized': False,
        })
        kwargs['test'] = PROMOTED_TEST
        kwargs['metadata'] = metadata
        notes = str(kwargs.get('notes') or '')
        kwargs['notes'] = (notes + ' V0.8.36 promoted exact one-vertex multi-bone outward extent field-shape.').strip()
        return self.backing.add(**kwargs)


def write_extent_promoted(
    root: pathlib.Path,
    logical: str,
    output: pathlib.Path | None = None,
    *,
    workspace_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    if logical.lower() not in {TARGET.lower(), 'at_dragon.smd'}:
        raise RuntimeError(f'MULTIBONE_EXTENT_PROMOTED_WRITER_ONLY_AT_DRAGON:{logical}')
    policy = load_and_validate_extent_policy(root)
    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    cert = CertificationRegistry(settings.certifications_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if _sha256(source) != policy.get('client_source_sha256'):
        raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_POLICY_CLIENT_SOURCE_HASH_MISMATCH')

    work = pathlib.Path(workspace_root).resolve() if workspace_root is not None else _workspace_root(root).resolve()
    final = pathlib.Path(output).expanduser() if output is not None else (work / 'output' / 'at_dragon_guarded_edit.smd')
    if not final.is_absolute():
        final = (root / final).resolve()
    proxy = _MultiboneExtentProductionCertificationProxy(cert)
    result = write_at_dragon_multibone_outward_extent_candidate_workspace(
        reg, resolver, proxy, settings,
        project_root=root, workspace_root=work, output=final,
    )
    kind = str(result.get('target_bound_kind') or '')
    fields = frozenset(str(x) for x in (result.get('changed_bound_fields') or []))
    if int(result.get('artist_changed_vertices', -1)) != 1:
        raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_REQUIRES_EXACTLY_ONE_CHANGED_VERTEX')
    if kind not in ALLOWED_TARGET_KINDS or fields != ALLOWED_FIELD_SHAPES.get(kind):
        raise RuntimeError(f'MULTIBONE_EXTENT_PRODUCTION_FIELD_SHAPE_NOT_AUTHORIZED:{kind}:{sorted(fields)}')
    if int(result.get('affected_bone_count', 0)) < 2:
        raise RuntimeError('MULTIBONE_EXTENT_PRODUCTION_REQUIRES_MULTIBONE_NORMALS')
    result.update({
        'candidate_only': False,
        'production_authorized': True,
        'multibone_outward_extent_live_write_authorized': True,
        'promotion_release': RELEASE_VERSION,
        'production_extent_policy': str(root / POLICY_REL),
        'production_single_object_max_vertices': 8,
        'production_cross_object_allowed_shapes': ['2x2', '3x2'],
        'production_extent_allowed_target_kinds': list(ALLOWED_TARGET_KINDS),
        'candidate_certification_test': PROMOTED_TEST,
        'candidate_write_scope': PROMOTED_SCOPE,
    })
    return result


def write_production_dispatch(root: pathlib.Path, logical: str, output: pathlib.Path | None = None, *, workspace_root: pathlib.Path | None = None) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    # Keep all previously certified production paths authoritative.  Only the exact
    # outward-bound rejection is eligible for the additive V0.8.36 extent path.
    try:
        if workspace_root is None:
            return write_pre_extent_dispatch(root, logical, output)
        return write_pre_extent_dispatch(root, logical, output, workspace_root=workspace_root)
    except Exception as exc:
        if 'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' not in str(exc):
            raise
    load_and_validate_extent_policy(root)
    if workspace_root is None:
        return write_extent_promoted(root, logical, output)
    return write_extent_promoted(root, logical, output, workspace_root=workspace_root)
