from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from . import rare_rigid_edit as redit
from . import rare_rigid_multivertex as mv
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, PROBE_MAX
from .rare_rigid_multibone_bridge import TARGET

POLICY_FORMAT = "PT_RARE_RIGID_LARGE_PRODUCTION_POLICY_V1"
POLICY_REL = pathlib.Path("pt_build/rare_rigid_large_production_policy_v0821.json")
MANUAL_REL = pathlib.Path("pt_build/rare_rigid_large_manual_candidate_v0819/at_dragon.smd/manual_write_result.json")
PROMOTED_TEST = "RARE_RIGID_ARTIST_GUARDED_LARGE_TRANSACTION_WRITE"
PROMOTED_SCOPE = "AT_DRAGON_TWO_TO_EIGHT_CHANGED_MULTIBONE_BOUNDARY_VERTICES_SINGLE_OBJECT_INTERIOR_ATOMIC_TRANSACTION"
RELEASE_VERSION = "0.8.21"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_and_validate_policy(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    p = root / POLICY_REL
    if not p.is_file():
        raise RuntimeError(f"PRODUCTION_POLICY_MISSING:{p}")
    policy = _json(p)
    checks = [
        policy.get("format") == POLICY_FORMAT,
        policy.get("status") == "PASS",
        policy.get("production_authorized") is True,
        int(policy.get("production_max_vertices", -1)) == PROBE_MAX,
        policy.get("logical") == TARGET,
        policy.get("writer_hashes") == EXPECTED_WRITER_HASHES,
        policy.get("cross_object_blocked") is True,
        policy.get("nine_vertex_blocked") is True,
        policy.get("bounds_negative_blocked") is True,
        policy.get("manual_artist_proof") is True,
    ]
    if not all(checks):
        raise RuntimeError("PRODUCTION_POLICY_NOT_STRICT_PASS")
    if _writer_hashes(root) != EXPECTED_WRITER_HASHES:
        raise RuntimeError("PRODUCTION_POLICY_WRITER_HASH_MISMATCH")
    manual = root / MANUAL_REL
    if not manual.is_file() or _sha256(manual) != policy.get("manual_report_sha256"):
        raise RuntimeError("PRODUCTION_POLICY_MANUAL_EVIDENCE_MISMATCH")
    return policy


class _ProductionCertificationProxy:
    def __init__(self, backing: CertificationRegistry):
        self.backing = backing
        self.directory = backing.directory
        self.path = backing.path

    def records(self) -> list[dict]:
        return self.backing.records()

    def add(self, **kwargs: Any) -> dict:
        test = str(kwargs.get("test") or "")
        metadata = dict(kwargs.get("metadata") or {})
        n = int(metadata.get("artist_changed_vertices", -1))
        if test == "RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE" and 5 <= n <= PROBE_MAX:
            metadata.update({
                "production_authorized": True,
                "promotion_release": RELEASE_VERSION,
                "production_max_vertices": PROBE_MAX,
                "original_core_test": test,
                "original_core_write_scope": metadata.get("write_scope"),
                "write_scope": PROMOTED_SCOPE,
            })
            kwargs["test"] = PROMOTED_TEST
            kwargs["metadata"] = metadata
            notes = str(kwargs.get("notes") or "")
            kwargs["notes"] = (notes + " V0.8.21 promoted 5..8 production transaction.").strip()
        return self.backing.add(**kwargs)


@contextlib.contextmanager
def production_widening():
    old_edit = int(redit.MAX_TRANSACTION_VERTICES)
    old_mv = int(mv.MAX_TRANSACTION_VERTICES)
    if old_edit != 4 or old_mv != 4:
        raise RuntimeError(f"PRODUCTION_BASE_LIMIT_NOT_4:edit={old_edit}:mv={old_mv}")
    redit.MAX_TRANSACTION_VERTICES = PROBE_MAX
    mv.MAX_TRANSACTION_VERTICES = PROBE_MAX
    try:
        yield
    finally:
        redit.MAX_TRANSACTION_VERTICES = old_edit
        mv.MAX_TRANSACTION_VERTICES = old_mv


def write_promoted(root: pathlib.Path, logical: str, output: pathlib.Path | None = None, *, workspace_root: pathlib.Path | None = None) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    if logical.lower() not in {TARGET.lower(), "at_dragon.smd"}:
        raise RuntimeError(f"PROMOTED_WRITER_ONLY_AT_DRAGON:{logical}")
    policy = load_and_validate_policy(root)
    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    cert = CertificationRegistry(settings.certifications_dir)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if _sha256(source) != policy.get("client_source_sha256"):
        raise RuntimeError("PRODUCTION_POLICY_CLIENT_SOURCE_HASH_MISMATCH")

    proxy = _ProductionCertificationProxy(cert)
    with production_widening():
        result = redit.write_at_dragon_edit_workspace(
            reg, resolver, proxy, settings,
            project_root=root, output=output, workspace_root=workspace_root,
        )
        if int(redit.MAX_TRANSACTION_VERTICES) != PROBE_MAX or int(mv.MAX_TRANSACTION_VERTICES) != PROBE_MAX:
            raise RuntimeError("PRODUCTION_WIDENING_NOT_ACTIVE_DURING_WRITE")
    if int(redit.MAX_TRANSACTION_VERTICES) != 4 or int(mv.MAX_TRANSACTION_VERTICES) != 4:
        raise RuntimeError("PRODUCTION_LIMIT_NOT_RESTORED")

    n = int(result.get("artist_changed_vertices", -1))
    if not (1 <= n <= PROBE_MAX):
        raise RuntimeError(f"PROMOTED_RESULT_COUNT_{n}_OUTSIDE_1_{PROBE_MAX}")
    result["production_authorized"] = True
    result["production_live_writer_max_vertices"] = PROBE_MAX
    result["production_policy"] = str(root / POLICY_REL)
    result["promotion_release"] = RELEASE_VERSION
    result["max_transaction_vertices_authorized"] = PROBE_MAX
    if n >= 5:
        result["write_scope"] = PROMOTED_SCOPE
        result["certification_test"] = PROMOTED_TEST

    report_path = result.get("report")
    if isinstance(report_path, str) and pathlib.Path(report_path).is_file():
        pathlib.Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
