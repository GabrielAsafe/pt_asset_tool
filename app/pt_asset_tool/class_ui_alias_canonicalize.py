from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import time
from typing import Any, Iterable

from .class_ui_alias_audit import UI_ALIAS_GROUPS, audit_class_ui_aliases

FORMAT = "PT_ASSET_CLASS_UI_ALIAS_CANONICALIZE_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _nearest_existing_parent(path: pathlib.Path) -> pathlib.Path:
    cur = path.parent
    while not cur.exists() and cur != cur.parent:
        cur = cur.parent
    return cur


def canonicalize_class_ui_alias_only(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
    *,
    expected_group: str,
    expected_paths: Iterable[str],
    apply: bool = False,
) -> dict[str, Any]:
    """Create missing canonical UI files from alias-only files.

    Safety contract:
    - fresh alias audit immediately before planning;
    - only rows currently classified ALIAS_ONLY are eligible;
    - --apply requires an exact non-empty expected path set;
    - target is create-only and must not exist;
    - source must resolve under one configured alias root for the selected group;
    - duplicate/conflict rows are never written or deleted;
    - bytes are staged and SHA-256 verified before and after os.replace;
    - all created targets are rolled back on failure;
    - post-audit must show zero expected paths still ALIAS_ONLY and each becomes
      DUPLICATE_IDENTICAL; conflicts may remain REVIEW_REQUIRED and are untouched.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    out_dir = project / "pt_build" / "class_ui_alias_canonicalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "result.json"

    expected_group = str(expected_group or "").strip()
    expected = {str(x).replace("\\", "/").strip() for x in expected_paths if str(x).strip()}

    spec = next((x for x in UI_ALIAS_GROUPS if x["id"] == expected_group), None)
    if spec is None:
        raise ValueError(f"CLASS_UI_ALIAS_UNKNOWN_GROUP:{expected_group}")
    if not bool(spec.get("recovery_enabled", True)):
        raise ValueError(f"CLASS_UI_ALIAS_RECOVERY_DISABLED_BY_PROJECT_POLICY:{expected_group}")

    fresh = audit_class_ui_aliases(project, client)
    group_rows = [x for x in fresh.get("rows", []) if x.get("group") == expected_group]
    eligible = [x for x in group_rows if x.get("state") == "ALIAS_ONLY"]
    actual = {str(x.get("canonical_logical_path") or "") for x in eligible}

    if apply and not expected:
        raise ValueError("CLASS_UI_ALIAS_APPLY_REQUIRES_EXPECTED_PATHS")
    if expected and expected != actual:
        missing = sorted(expected - actual, key=str.casefold)
        extra = sorted(actual - expected, key=str.casefold)
        raise ValueError(
            "CLASS_UI_ALIAS_SCOPE_MISMATCH:"
            + json.dumps({"missing_from_fresh_scope": missing, "unexpected_fresh_scope": extra}, ensure_ascii=False)
        )

    planned: list[dict[str, Any]] = []
    alias_roots = [client / str(x) for x in spec["alias_roots"]]
    canonical_root = client / str(spec["canonical_root"])

    for row in eligible:
        aliases = list(row.get("alias_files") or [])
        if len(aliases) != 1:
            raise ValueError(f"CLASS_UI_ALIAS_SOURCE_AMBIGUOUS:{row.get('canonical_logical_path')}")
        a = aliases[0]
        src = pathlib.Path(str(a.get("physical_path") or "")).resolve()
        dst = client / str(row.get("canonical_logical_path") or "")
        if not _within(src, client) or not any(_within(src, ar) for ar in alias_roots):
            raise ValueError(f"CLASS_UI_ALIAS_SOURCE_OUTSIDE_ALIAS_ROOT:{src}")
        if not _within(dst, canonical_root):
            raise ValueError(f"CLASS_UI_ALIAS_TARGET_OUTSIDE_CANONICAL_ROOT:{dst}")
        if dst.exists():
            raise FileExistsError(f"CLASS_UI_ALIAS_TARGET_EXISTS:{dst}")
        if not src.is_file():
            raise FileNotFoundError(f"CLASS_UI_ALIAS_SOURCE_MISSING:{src}")
        src_sha = _sha256(src)
        if src_sha != str(a.get("sha256") or ""):
            raise ValueError(f"CLASS_UI_ALIAS_SOURCE_HASH_DRIFT:{src}")
        planned.append({
            "group": expected_group,
            "relative_path": row.get("relative_path"),
            "source": str(src),
            "target": str(dst),
            "sha256": src_sha,
            "size": src.stat().st_size,
        })

    conflicts = [x for x in group_rows if x.get("state") == "DUPLICATE_CONFLICT"]
    result: dict[str, Any] = {
        "format": FORMAT,
        "status": "PASS",
        "state": "PLAN_READY" if not apply else "APPLY_PENDING",
        "generated_at": time.time(),
        "client_root": str(client),
        "group": expected_group,
        "planned_count": len(planned),
        "planned": planned,
        "conflict_count": len(conflicts),
        "conflicts_untouched": [x.get("canonical_logical_path") for x in conflicts],
        "apply_requested": bool(apply),
        "written_count": 0,
        "rollback_performed": False,
        "policy": {
            "create_only": True,
            "overwrite_existing": False,
            "delete_alias_files": False,
            "touch_duplicate_identical": False,
            "touch_duplicate_conflict": False,
            "expected_scope_exact_match_required": True,
        },
        "report": str(report_path),
    }

    if not apply:
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    # Preflight all target parents before staging anything.
    for row in planned:
        dst = pathlib.Path(row["target"])
        parent = _nearest_existing_parent(dst)
        if not os.access(parent, os.W_OK | os.X_OK):
            raise PermissionError(f"CLASS_UI_ALIAS_TARGET_PARENT_NOT_WRITABLE:{parent}")

    stage_root = out_dir / "stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[pathlib.Path, pathlib.Path, str, int]] = []
    for row in planned:
        src = pathlib.Path(row["source"])
        dst = pathlib.Path(row["target"])
        rel = dst.relative_to(client)
        stage = stage_root / rel
        stage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, stage)
        if _sha256(stage) != row["sha256"] or stage.stat().st_size != row["size"]:
            raise IOError(f"CLASS_UI_ALIAS_STAGE_VERIFY_FAILED:{stage}")
        staged.append((stage, dst, row["sha256"], row["size"]))

    created: list[pathlib.Path] = []
    try:
        for stage, dst, sha, size in staged:
            if dst.exists():
                raise FileExistsError(f"CLASS_UI_ALIAS_TARGET_APPEARED_DURING_APPLY:{dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.pt-ui-canonicalize-", dir=str(dst.parent))
            os.close(fd)
            tmp = pathlib.Path(tmp_name)
            try:
                shutil.copyfile(stage, tmp)
                if _sha256(tmp) != sha or tmp.stat().st_size != size:
                    raise IOError(f"CLASS_UI_ALIAS_TEMP_VERIFY_FAILED:{tmp}")
                os.replace(tmp, dst)
            finally:
                if tmp.exists():
                    tmp.unlink()
            created.append(dst)
            if _sha256(dst) != sha or dst.stat().st_size != size:
                raise IOError(f"CLASS_UI_ALIAS_POSTWRITE_VERIFY_FAILED:{dst}")
    except Exception:
        for dst in reversed(created):
            try:
                dst.unlink()
            except FileNotFoundError:
                pass
        result["rollback_performed"] = bool(created)
        result["state"] = "APPLY_FAILED_ROLLED_BACK" if created else "APPLY_FAILED_NO_WRITE"
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise

    post = audit_class_ui_aliases(project, client)
    post_rows = {
        str(x.get("canonical_logical_path") or ""): x
        for x in post.get("rows", [])
        if x.get("group") == expected_group
    }
    bad_post = []
    for path in sorted(expected, key=str.casefold):
        row = post_rows.get(path)
        if row is None or row.get("state") != "DUPLICATE_IDENTICAL":
            bad_post.append({"path": path, "state": None if row is None else row.get("state")})
    if bad_post:
        for dst in reversed(created):
            try:
                dst.unlink()
            except FileNotFoundError:
                pass
        result["rollback_performed"] = True
        result["state"] = "POST_AUDIT_FAILED_ROLLED_BACK"
        result["post_audit_failures"] = bad_post
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("CLASS_UI_ALIAS_POST_AUDIT_FAILED:" + json.dumps(bad_post, ensure_ascii=False))

    result.update({
        "state": "APPLIED_VERIFIED",
        "written_count": len(created),
        "written": [str(x) for x in created],
        "post_alias_only_count": sum(
            1 for x in post.get("rows", [])
            if x.get("group") == expected_group and x.get("state") == "ALIAS_ONLY"
        ),
        "post_duplicate_identical_count": sum(
            1 for x in post.get("rows", [])
            if x.get("group") == expected_group and x.get("state") == "DUPLICATE_IDENTICAL"
        ),
        "post_duplicate_conflict_count": sum(
            1 for x in post.get("rows", [])
            if x.get("group") == expected_group and x.get("state") == "DUPLICATE_CONFLICT"
        ),
        "post_state": post.get("state"),
    })
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
