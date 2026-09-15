from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import shutil
import time
import uuid
import zipfile
from typing import Any, Callable, Iterable

from .general_asset_census import audit_general_asset_census
from .superset_aggregation import parse_labeled_roots

FORMAT = "PT_ASSET_GENERAL_CLOSED_BUNDLE_RECOVERY_V1"
RECOVER_STATES = {"ROOT", "RECOVER_SAME_DONOR"}


class RecoveryApplyRolledBackError(RuntimeError):
    def __init__(self, message: str, rolled_back_member_count: int) -> None:
        super().__init__(message)
        self.rolled_back_member_count = int(rolled_back_member_count)


def _norm(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.lstrip("./")


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    rel = pathlib.PurePosixPath(_norm(value))
    if not str(rel) or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"RECOVERY_RELATIVE_PATH_INVALID:{value}")
    return rel


def _parse_expected_roots(values: Iterable[str] | None) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for raw in values or []:
        text = str(raw or "").strip()
        if not text or ":" not in text:
            raise ValueError(f"EXPECTED_ROOT_FORMAT_INVALID:{text}; use CLIENT:path or SERVER:path")
        side, rel = text.split(":", 1)
        side = side.strip().upper()
        if side not in {"CLIENT", "SERVER"}:
            raise ValueError(f"EXPECTED_ROOT_SIDE_INVALID:{side}")
        normalized = _norm(rel)
        _safe_rel(normalized)
        key = (side, normalized.casefold())
        if key in out:
            raise ValueError(f"EXPECTED_ROOT_DUPLICATE:{side}:{normalized}")
        out.add(key)
    return out


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"RECOVERY_REPORT_NOT_FOUND:{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"RECOVERY_REPORT_INVALID:{path}")
    return data


def _closed_scope(bundle_report: dict[str, Any]) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    rows = [x for x in (bundle_report.get("rows") or []) if isinstance(x, dict)]
    scope: set[tuple[str, str]] = set()
    for row in rows:
        side = str(row.get("side") or "").upper()
        root = _norm(row.get("root_path") or "")
        status = str(row.get("status") or "").upper()
        if side not in {"CLIENT", "SERVER"} or not root:
            raise ValueError("RECOVERY_BUNDLE_ROW_INVALID")
        if status != "CLOSED":
            raise RuntimeError(f"RECOVERY_BUNDLE_NOT_CLOSED:{side}:{root}:{status}")
        scope.add((side, root.casefold()))
    return scope, rows


def _matching_dirs(parent: pathlib.Path, name: str) -> list[pathlib.Path]:
    if not parent.is_dir():
        return []
    try:
        return [p for p in parent.iterdir() if p.is_dir() and p.name.casefold() == name.casefold()]
    except OSError:
        return []


def _case_preserving_destination(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path:
    """Reuse existing casing; when aliases collide, an exact spelling is authoritative."""
    current = root.resolve()
    parts = list(rel.parts)
    for i, part in enumerate(parts):
        final = i == len(parts) - 1
        if final:
            return current / part
        matches = _matching_dirs(current, part)
        chosen = part
        if len(matches) == 1:
            chosen = matches[0].name
        elif len(matches) > 1:
            exact = [p for p in matches if p.name == part]
            if len(exact) == 1:
                chosen = exact[0].name
            else:
                aliases = ",".join(sorted(p.name for p in matches))
                raise RuntimeError(f"TARGET_CASE_COLLISION_DIR:{current}:{part}:{aliases}")
        current = current / chosen
    return current


def _casefold_existing_files(root: pathlib.Path, rel: pathlib.PurePosixPath) -> list[pathlib.Path]:
    """Find existing case-insensitive file variants across every colliding parent branch."""
    parents = [root.resolve()]
    for part in rel.parts[:-1]:
        next_parents: list[pathlib.Path] = []
        for parent in parents:
            next_parents.extend(_matching_dirs(parent, part))
        parents = next_parents
        if not parents:
            return []
    matches: list[pathlib.Path] = []
    for parent in parents:
        try:
            matches.extend(p for p in parent.iterdir() if p.is_file() and p.name.casefold() == rel.name.casefold())
        except OSError:
            continue
    return matches


def _casefold_existing_file(root: pathlib.Path, rel: pathlib.PurePosixPath) -> pathlib.Path | None:
    matches = _casefold_existing_files(root, rel)
    if len(matches) > 1:
        rendered = ",".join(sorted(str(p) for p in matches))
        raise RuntimeError(f"TARGET_CASE_COLLISION_FILE:{root.resolve()}:{rel.as_posix()}:{rendered}")
    return matches[0] if matches else None


def _physical_relative(source: pathlib.Path, donor_root: pathlib.Path, logical_path: str) -> pathlib.PurePosixPath:
    try:
        rel = source.resolve().relative_to(donor_root.resolve())
    except Exception as exc:
        raise RuntimeError(f"SOURCE_OUTSIDE_SELECTED_DONOR:{source}:{donor_root}") from exc
    rel_posix = pathlib.PurePosixPath(rel.as_posix())
    logical = _safe_rel(logical_path)
    if rel_posix.as_posix().casefold() != logical.as_posix().casefold():
        raise RuntimeError(
            f"SOURCE_LOGICAL_PATH_MISMATCH:{source}:{logical.as_posix()}:{rel_posix.as_posix()}"
        )
    return rel_posix


def _build_transactions(
    bundle_rows: list[dict[str, Any]],
    *,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    donor_clients: list[tuple[str, pathlib.Path]],
    donor_servers: list[tuple[str, pathlib.Path]],
) -> list[dict[str, Any]]:
    donor_maps = {
        "CLIENT": {label.upper(): root.resolve() for label, root in donor_clients},
        "SERVER": {label.upper(): root.resolve() for label, root in donor_servers},
    }
    target_roots = {"CLIENT": client_root.resolve(), "SERVER": server_root.resolve()}
    tx: list[dict[str, Any]] = []
    seen_dest: set[tuple[str, str]] = set()
    for bundle in bundle_rows:
        side = str(bundle.get("side") or "").upper()
        root_path = _norm(bundle.get("root_path") or "")
        donor_label = str(bundle.get("donor_label") or bundle.get("selected_source") or "").upper()
        if donor_label not in donor_maps.get(side, {}):
            raise RuntimeError(f"SELECTED_DONOR_NOT_CONFIGURED:{side}:{donor_label}:{root_path}")
        donor_root = donor_maps[side][donor_label]
        target_root = target_roots[side]
        for member in bundle.get("members") or []:
            if not isinstance(member, dict):
                continue
            state = str(member.get("state") or "").upper()
            if state not in RECOVER_STATES:
                continue
            logical = _norm(member.get("logical_path") or "")
            source = pathlib.Path(str(member.get("physical_path") or ""))
            if not source.is_file():
                raise FileNotFoundError(f"RECOVERY_SOURCE_MISSING:{side}:{logical}:{source}")
            rel = _physical_relative(source, donor_root, logical)
            existing = _casefold_existing_file(target_root, rel)
            if existing is not None:
                raise RuntimeError(f"RECOVERY_TARGET_ALREADY_EXISTS:{side}:{rel.as_posix()}:{existing}")
            dest = _case_preserving_destination(target_root, rel)
            try:
                dest.resolve().relative_to(target_root)
            except Exception as exc:
                raise RuntimeError(f"RECOVERY_DEST_OUTSIDE_TARGET:{dest}:{target_root}") from exc
            dkey = (side, rel.as_posix().casefold())
            if dkey in seen_dest:
                raise RuntimeError(f"RECOVERY_DEST_DUPLICATE:{side}:{rel.as_posix()}")
            seen_dest.add(dkey)
            tx.append({
                "side": side,
                "bundle_root": root_path,
                "donor_label": donor_label,
                "logical_path": logical,
                "relative_path": rel.as_posix(),
                "source_path": str(source.resolve()),
                "target_path": str(dest),
                "state": state,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            })
    if not tx:
        raise RuntimeError("RECOVERY_NO_MEMBERS_TO_MATERIALIZE")
    return tx


def _write_transactions(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "side", "bundle_root", "donor_label", "logical_path", "relative_path",
        "source_path", "target_path", "state", "size", "sha256",
        "staged_path", "staged_verified", "written", "postwrite_verified",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _stage_transactions(project: pathlib.Path, tx: list[dict[str, Any]]) -> pathlib.Path:
    stage_root = project / "pt_build" / "general_asset_recovery" / "staging"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    for row in tx:
        rel = pathlib.PurePosixPath(str(row["relative_path"]))
        staged = stage_root / str(row["side"]).casefold() / pathlib.Path(*rel.parts)
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pathlib.Path(str(row["source_path"])), staged)
        if staged.stat().st_size != int(row["size"]) or _sha256(staged) != row["sha256"]:
            raise RuntimeError(f"RECOVERY_STAGE_VERIFY_FAILED:{row['side']}:{row['relative_path']}")
        row["staged_path"] = str(staged)
        row["staged_verified"] = True
        row["written"] = False
        row["postwrite_verified"] = False
    return stage_root


def _fsync_file(path: pathlib.Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def _cleanup_empty_dirs(paths: list[pathlib.Path], roots: set[pathlib.Path]) -> None:
    for start in sorted(set(paths), key=lambda p: len(p.parts), reverse=True):
        p = start
        while p not in roots:
            try:
                p.rmdir()
            except OSError:
                break
            p = p.parent


def _preflight_target_writability(tx: list[dict[str, Any]], client_root: pathlib.Path, server_root: pathlib.Path) -> None:
    roots = {"CLIENT": client_root.resolve(), "SERVER": server_root.resolve()}
    checked: set[pathlib.Path] = set()
    for row in tx:
        target = pathlib.Path(str(row["target_path"]))
        root = roots[str(row["side"])]
        parent = target.parent
        cursor = parent
        while cursor != root and not cursor.exists():
            cursor = cursor.parent
        if not cursor.exists() or not cursor.is_dir():
            raise RuntimeError(f"RECOVERY_TARGET_PARENT_INVALID:{cursor}:target={target}")
        if cursor in checked:
            continue
        checked.add(cursor)
        if not os.access(cursor, os.W_OK | os.X_OK):
            raise PermissionError(f"RECOVERY_TARGET_PARENT_NOT_WRITABLE:{cursor}:target={target}")


def _apply_transactions(tx: list[dict[str, Any]], client_root: pathlib.Path, server_root: pathlib.Path) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    roots = {client_root.resolve(), server_root.resolve()}
    written: list[pathlib.Path] = []
    created_dirs: list[pathlib.Path] = []
    temp_paths: list[pathlib.Path] = []
    token = uuid.uuid4().hex[:12]
    try:
        # Recheck the complete create-only precondition immediately before the first write.
        for row in tx:
            target = pathlib.Path(str(row["target_path"]))
            if target.exists():
                raise RuntimeError(f"RECOVERY_TARGET_APPEARED_AFTER_PREFLIGHT:{target}")
            rel = pathlib.PurePosixPath(str(row["relative_path"]))
            root = client_root if row["side"] == "CLIENT" else server_root
            existing = _casefold_existing_file(root.resolve(), rel)
            if existing is not None:
                raise RuntimeError(f"RECOVERY_TARGET_CASE_VARIANT_APPEARED:{existing}")

        _preflight_target_writability(tx, client_root, server_root)

        for row in tx:
            target = pathlib.Path(str(row["target_path"]))
            parent = target.parent
            missing_chain = []
            cursor = parent
            root = client_root.resolve() if row["side"] == "CLIENT" else server_root.resolve()
            while cursor != root and not cursor.exists():
                missing_chain.append(cursor)
                cursor = cursor.parent
            parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(missing_chain)
            tmp = parent / f".{target.name}.pt-recovery-{token}.tmp"
            temp_paths.append(tmp)
            shutil.copyfile(pathlib.Path(str(row["staged_path"])), tmp)
            _fsync_file(tmp)
            if tmp.stat().st_size != int(row["size"]) or _sha256(tmp) != row["sha256"]:
                raise RuntimeError(f"RECOVERY_TMP_VERIFY_FAILED:{target}")
            os.replace(tmp, target)
            written.append(target)
            if target.stat().st_size != int(row["size"]) or _sha256(target) != row["sha256"]:
                raise RuntimeError(f"RECOVERY_POSTWRITE_VERIFY_FAILED:{target}")
            row["written"] = True
            row["postwrite_verified"] = True
        return written, created_dirs
    except Exception as exc:
        for tmp in temp_paths:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        rolled_back_count = len(written)
        for path in reversed(written):
            try:
                path.unlink()
            except OSError:
                pass
        _cleanup_empty_dirs(created_dirs, roots)
        if rolled_back_count:
            for row in tx:
                if row.get("written"):
                    row["written"] = False
                    row["postwrite_verified"] = False
            raise RecoveryApplyRolledBackError(str(exc), rolled_back_count) from exc
        raise


def _rollback_written(written: list[pathlib.Path], created_dirs: list[pathlib.Path], client_root: pathlib.Path, server_root: pathlib.Path) -> None:
    for path in reversed(written):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    _cleanup_empty_dirs(created_dirs, {client_root.resolve(), server_root.resolve()})


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status", "census_state", "candidate_count", "recoverable_reachable_candidate_count",
        "reachable_donor_conflict_count", "reachable_hard_conflict_count", "missing_reachable_no_donor_count",
        "recovery_bundle_root_count", "recovery_bundle_closed_root_count", "recovery_bundle_review_root_count",
        "recovery_bundle_incomplete_root_count", "strong_client_path_count", "strong_server_path_count",
    ]
    return {k: result.get(k) for k in keys}


def recover_closed_general_asset_bundles(
    project: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None = None,
    reference_source_root: str | pathlib.Path | None = None,
    donor_clients: Iterable[str] | None = None,
    donor_servers: Iterable[str] | None = None,
    expected_roots: Iterable[str] | None = None,
    apply: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project).resolve()
    client = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve()
    expected = _parse_expected_roots(expected_roots)
    if apply and not expected:
        raise RuntimeError("RECOVERY_APPLY_REQUIRES_EXPECTED_ROOTS")

    donor_client_values = list(donor_clients or [])
    donor_server_values = list(donor_servers or [])
    donor_client_roots = parse_labeled_roots(donor_client_values)
    donor_server_roots = parse_labeled_roots(donor_server_values)
    out_dir = project / "pt_build" / "general_asset_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "result.json"
    tx_path = out_dir / "transactions.tsv"
    bundle_path = out_dir / "reports_bundle.zip"

    result: dict[str, Any] = {
        "format": FORMAT,
        "status": "RUNNING",
        "state": "PREFLIGHT",
        "generated_at": time.time(),
        "apply_requested": bool(apply),
        "client_root": str(client),
        "server_root": str(server),
        "expected_roots": [f"{s}:{p}" for s, p in sorted(expected)],
        "policy": {
            "fresh_census_required": True,
            "scope_must_equal_expected_roots": True,
            "closed_bundles_only": True,
            "create_only_no_overwrite": True,
            "same_selected_donor_lineage_only": True,
            "atomic_file_replace": True,
            "rollback_on_write_or_post_census_failure": True,
            "broad_client_write_authorized": False,
            "broad_server_write_authorized": False,
            "production_authorized": False,
        },
        "transactions": [],
        "rollback_performed": False,
    }

    written: list[pathlib.Path] = []
    created_dirs: list[pathlib.Path] = []
    try:
        if progress:
            progress("fresh general census preflight")
        pre = audit_general_asset_census(
            project, client, server,
            source_root=source_root,
            reference_source_root=reference_source_root,
            donor_clients=donor_client_values,
            donor_servers=donor_server_values,
            progress=(lambda m: progress(f"census: {m}")) if progress else None,
        )
        result["pre_census"] = _summary(pre)
        if pre.get("status") != "PASS":
            raise RuntimeError("RECOVERY_PREFLIGHT_CENSUS_FAILED")
        if int(pre.get("reachable_donor_conflict_count") or 0) or int(pre.get("reachable_hard_conflict_count") or 0):
            raise RuntimeError("RECOVERY_PREFLIGHT_REACHABLE_CONFLICT")
        bundle_report = _load_json(project / "pt_build" / "general_asset_census" / "recovery_bundles.json")
        actual_scope, bundle_rows = _closed_scope(bundle_report)
        if not actual_scope:
            raise RuntimeError("RECOVERY_PREFLIGHT_NO_CLOSED_BUNDLES")
        if expected and actual_scope != expected:
            expected_text = sorted(f"{s}:{p}" for s, p in expected)
            actual_text = sorted(f"{s}:{p}" for s, p in actual_scope)
            raise RuntimeError(f"RECOVERY_SCOPE_CHANGED:expected={expected_text}:actual={actual_text}")
        if int(pre.get("recoverable_reachable_candidate_count") or 0) != len(actual_scope):
            raise RuntimeError("RECOVERY_SCOPE_COUNT_MISMATCH")
        if int(pre.get("recovery_bundle_closed_root_count") or 0) != len(actual_scope):
            raise RuntimeError("RECOVERY_CLOSED_COUNT_MISMATCH")
        if int(pre.get("recovery_bundle_review_root_count") or 0) or int(pre.get("recovery_bundle_incomplete_root_count") or 0):
            raise RuntimeError("RECOVERY_NON_CLOSED_BUNDLE_PRESENT")

        if progress:
            progress(f"scope locked: {len(actual_scope)} closed bundles")
        tx = _build_transactions(
            bundle_rows,
            client_root=client,
            server_root=server,
            donor_clients=donor_client_roots,
            donor_servers=donor_server_roots,
        )
        result["scope_roots"] = [
            f"{str(x.get('side') or '').upper()}:{_norm(x.get('root_path') or '')}" for x in bundle_rows
        ]
        result["planned_member_count"] = len(tx)
        result["planned_client_member_count"] = sum(1 for x in tx if x["side"] == "CLIENT")
        result["planned_server_member_count"] = sum(1 for x in tx if x["side"] == "SERVER")

        if progress:
            progress(f"staging {len(tx)} members under pt_build")
        stage_root = _stage_transactions(project, tx)
        result["staging_root"] = str(stage_root)
        result["staged_member_count"] = len(tx)
        result["transactions"] = tx
        _write_transactions(tx_path, tx)

        if not apply:
            result.update({
                "status": "PASS",
                "state": "STAGED_ONLY",
                "written_member_count": 0,
                "target_client_modified": False,
                "target_server_modified": False,
            })
        else:
            if progress:
                progress("applying create-only recovery transaction")
            written, created_dirs = _apply_transactions(tx, client, server)
            _write_transactions(tx_path, tx)
            result["written_member_count"] = len(written)
            result["target_client_modified"] = any(x["side"] == "CLIENT" and x.get("written") for x in tx)
            result["target_server_modified"] = any(x["side"] == "SERVER" and x.get("written") for x in tx)

            if progress:
                progress("post-write general census verification")
            post = audit_general_asset_census(
                project, client, server,
                source_root=source_root,
                reference_source_root=reference_source_root,
                donor_clients=donor_client_values,
                donor_servers=donor_server_values,
                progress=(lambda m: progress(f"post-census: {m}")) if progress else None,
            )
            result["post_census"] = _summary(post)
            post_ok = (
                post.get("status") == "PASS"
                and int(post.get("reachable_donor_conflict_count") or 0) == 0
                and int(post.get("reachable_hard_conflict_count") or 0) == 0
                and int(post.get("recoverable_reachable_candidate_count") or 0) == 0
                and int(post.get("recovery_bundle_root_count") or 0) == 0
            )
            if not post_ok:
                _rollback_written(written, created_dirs, client, server)
                result["rollback_performed"] = True
                result["target_client_modified"] = False
                result["target_server_modified"] = False
                result["written_member_count"] = 0
                raise RuntimeError("RECOVERY_POST_CENSUS_VERIFY_FAILED_ROLLED_BACK")
            result.update({"status": "PASS", "state": "APPLIED_VERIFIED"})

    except RecoveryApplyRolledBackError as exc:
        result["rollback_performed"] = True
        result["rolled_back_member_count"] = exc.rolled_back_member_count
        result["written_member_count"] = 0
        result.update({
            "status": "FAIL",
            "state": "ROLLED_BACK",
            "error": f"{type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__}:{exc}",
            "target_client_modified": False,
            "target_server_modified": False,
        })
    except Exception as exc:
        if written and not result.get("rollback_performed") and result.get("state") != "APPLIED_VERIFIED":
            _rollback_written(written, created_dirs, client, server)
            result["rollback_performed"] = True
        result.update({
            "status": "FAIL",
            "state": "ROLLED_BACK" if result.get("rollback_performed") else "ABORTED_NO_WRITE",
            "error": f"{type(exc).__name__}:{exc}",
            "target_client_modified": False if result.get("rollback_performed") else result.get("target_client_modified", False),
            "target_server_modified": False if result.get("rollback_performed") else result.get("target_server_modified", False),
        })
    finally:
        result["report"] = str(report_path)
        result["transactions_tsv"] = str(tx_path)
        result["reports_bundle"] = str(bundle_path)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if result.get("transactions"):
            _write_transactions(tx_path, result["transactions"])
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(report_path, arcname="general_asset_recovery/result.json")
            if tx_path.is_file():
                z.write(tx_path, arcname="general_asset_recovery/transactions.tsv")
            gc_result = project / "pt_build" / "general_asset_census" / "result.json"
            gc_bundles = project / "pt_build" / "general_asset_census" / "recovery_bundles.json"
            gc_candidates = project / "pt_build" / "general_asset_census" / "candidates.tsv"
            gc_t5_assets = project / "pt_build" / "general_asset_census" / "t5_asset_readiness.json"
            if gc_result.is_file():
                z.write(gc_result, arcname="post_or_pre_census/result.json")
            if gc_bundles.is_file():
                z.write(gc_bundles, arcname="post_or_pre_census/recovery_bundles.json")
            if gc_candidates.is_file():
                z.write(gc_candidates, arcname="post_or_pre_census/candidates.tsv")
            if gc_t5_assets.is_file():
                z.write(gc_t5_assets, arcname="post_or_pre_census/t5_asset_readiness.json")

    return result
