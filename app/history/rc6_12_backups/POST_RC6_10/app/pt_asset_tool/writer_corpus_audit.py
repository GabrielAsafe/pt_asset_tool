from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
import signal
import struct
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Iterable

from .inx_writer import patch_motion, validate_noop_roundtrip
from .smb_writer import first_editable_key, patch_key, validate_track_roundtrip
from .animation_source_regression import audit_animation_source_regression
from .motion_core import resolve_asset_motion_context, load_motion_system, enrich_motions

INX_FORMAT = "PT_INX_WRITER_CORPUS_AUDIT_V1"
SMB_FORMAT = "PT_SMB_WRITER_CORPUS_AUDIT_V1"
INX_EDIT_FORMAT = "PT_INX_WRITER_EDIT_CORPUS_AUDIT_V1"
SMB_EDIT_FORMAT = "PT_SMB_WRITER_EDIT_CORPUS_AUDIT_V1"
MOTION_SEMANTIC_EDIT_FORMAT = "PT_MOTION_WRITER_SEMANTIC_EDIT_CORPUS_V1"
DEFAULT_PREFIXES = ("char/npc", "char/monster")


def _adjacent_distinct_float32(value: float) -> float:
    """Return a finite adjacent float32 that is guaranteed to change bytes.

    Fixed decimal deltas such as +0.25 can quantize back to the original value
    for large legacy coordinates.  Writer probes need a real serialized edit,
    so move exactly one representable float32 step while staying finite.
    """
    f = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    if not math.isfinite(f):
        raise ValueError(f"cannot perturb non-finite float32: {f}")
    bits = struct.unpack("<I", struct.pack("<f", f))[0]
    if bits == 0x80000000:  # -0.0: bits-1 is a NaN; use the nearest negative subnormal
        candidate_bits = 0x80000001
    elif bits == 0x7F7FFFFF:  # max positive finite -> step downward
        candidate_bits = bits - 1
    elif bits == 0xFF7FFFFF:  # max negative finite -> step toward zero
        candidate_bits = bits - 1
    elif bits & 0x80000000:
        candidate_bits = bits - 1  # negative: numerically upward / toward +inf
    else:
        candidate_bits = bits + 1  # non-negative: numerically upward
    candidate = struct.unpack("<f", struct.pack("<I", candidate_bits))[0]
    if not math.isfinite(candidate) or candidate == f:
        raise RuntimeError(f"failed to choose distinct finite float32 for {f}")
    return float(candidate)


def _safe_prefix(root: pathlib.Path, prefix: str) -> pathlib.Path:
    root = pathlib.Path(root).resolve()
    rel = pathlib.PurePosixPath(str(prefix).replace("\\", "/").strip("/"))
    if any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe corpus prefix: {prefix}")
    path = (root / pathlib.Path(*rel.parts)).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"corpus prefix escapes client root: {prefix}")
    return path


def _files(client_root: pathlib.Path, suffix: str, prefixes: Iterable[str]) -> list[pathlib.Path]:
    root = pathlib.Path(client_root).resolve()
    out: dict[str, pathlib.Path] = {}
    for raw in prefixes:
        base = _safe_prefix(root, raw)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.casefold() == suffix.casefold():
                out[str(path.resolve())] = path.resolve()
    return [out[key] for key in sorted(out, key=str.casefold)]


def _explicit_files(client_root: pathlib.Path, suffix: str, logical_paths: Iterable[str]) -> list[pathlib.Path]:
    """Resolve an explicit logical corpus without broad directory inference.

    Release 1.0 coverage is content-domain aware.  Several semantic domains
    intentionally share physical folders (for example weapon/effect assets), so
    a prefix-only writer audit can prove the wrong domain.  Exact logical paths
    let the caller exercise precisely the files attributed to a matrix cell.
    """
    root = pathlib.Path(client_root).resolve()
    out: dict[str, pathlib.Path] = {}
    for raw in logical_paths:
        rel = pathlib.PurePosixPath(str(raw).replace("\\", "/").strip("/"))
        if not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            raise ValueError(f"unsafe logical corpus path: {raw}")
        path = (root / pathlib.Path(*rel.parts)).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"logical corpus path escapes client root: {raw}")
        if path.is_file() and path.suffix.casefold() == suffix.casefold():
            out[str(path)] = path
    return [out[key] for key in sorted(out, key=str.casefold)]


def _explicit_request_logicals(suffix: str, logical_paths: Iterable[str]) -> list[str]:
    wanted = str(suffix).casefold()
    out: dict[str, str] = {}
    for raw in logical_paths:
        rel = pathlib.PurePosixPath(str(raw).replace("\\", "/").strip("/"))
        if not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            raise ValueError(f"unsafe logical corpus path: {raw}")
        logical = rel.as_posix()
        if pathlib.PurePosixPath(logical).suffix.casefold() != wanted:
            continue
        out[logical.casefold()] = logical
    return [out[k] for k in sorted(out)]


def _explicit_missing(root: pathlib.Path, requested: list[str], paths: list[pathlib.Path]) -> list[str]:
    found = {_logical(root, p).casefold() for p in paths}
    return [logical for logical in requested if logical.casefold() not in found]


def _logical(root: pathlib.Path, path: pathlib.Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def audit_inx_writer_corpus(
    client_root: pathlib.Path,
    *,
    prefixes: Iterable[str] = DEFAULT_PREFIXES,
    logical_paths: Iterable[str] | None = None,
    sample_limit: int = 50,
) -> dict[str, Any]:
    root = pathlib.Path(client_root).resolve()
    requested = _explicit_request_logicals(".inx", logical_paths) if logical_paths is not None else []
    paths = _explicit_files(root, ".inx", requested) if logical_paths is not None else _files(root, ".inx", prefixes)
    missing_requested = _explicit_missing(root, requested, paths) if logical_paths is not None else []
    layouts: collections.Counter[str] = collections.Counter()
    failures: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []
    variant_files = variant_records = noncanonical_start = noncanonical_end = 0
    passed = 0
    for path in paths:
        try:
            row = validate_noop_roundtrip(path)
        except Exception as exc:
            failures.append({"path": _logical(root, path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        layouts[str(row.get("layout") or "UNKNOWN")] += 1
        if row.get("status") != "PASS":
            failures.append({
                "path": _logical(root, path),
                "layout": row.get("layout"),
                "changed_byte_count": row.get("changed_byte_count"),
            })
            continue
        passed += 1
        vr = int(row.get("semantic_variant_record_count") or 0)
        if vr:
            variant_files += 1
            variant_records += vr
            noncanonical_start += int(row.get("noncanonical_start_encoding_count") or 0)
            noncanonical_end += int(row.get("noncanonical_end_encoding_count") or 0)
            if len(variants) < max(0, int(sample_limit)):
                variants.append({
                    "path": _logical(root, path),
                    "layout": row.get("layout"),
                    "variant_records": vr,
                    "noncanonical_start": int(row.get("noncanonical_start_encoding_count") or 0),
                    "noncanonical_end": int(row.get("noncanonical_end_encoding_count") or 0),
                })
    total = len(paths)
    return {
        "format": INX_FORMAT,
        "status": "PASS" if total and not failures and passed == total and not missing_requested else ("EMPTY" if not total and not requested else "FAIL"),
        "scope": "READ_ONLY_CANDIDATE_WRITER_EVIDENCE",
        "client_root": str(root),
        "prefixes": [str(x) for x in prefixes],
        "explicit_logical_paths": logical_paths is not None,
        "requested_file_count": len(requested) if logical_paths is not None else None,
        "missing_requested_files": missing_requested,
        "file_count": total,
        "pass_count": passed,
        "fail_count": len(failures),
        "layout_counts": dict(sorted(layouts.items())),
        "semantic_variant_file_count": variant_files,
        "semantic_variant_record_count": variant_records,
        "noncanonical_start_encoding_count": noncanonical_start,
        "noncanonical_end_encoding_count": noncanonical_end,
        "variant_sample": variants,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "production_authorized": False,
        "client_modified": False,
    }


def audit_smb_writer_corpus(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    *,
    prefixes: Iterable[str] = DEFAULT_PREFIXES,
    logical_paths: Iterable[str] | None = None,
    sample_limit: int = 50,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    root = pathlib.Path(client_root).resolve()
    requested = _explicit_request_logicals(".smb", logical_paths) if logical_paths is not None else []
    paths = _explicit_files(root, ".smb", requested) if logical_paths is not None else _files(root, ".smb", prefixes)
    missing_requested = _explicit_missing(root, requested, paths) if logical_paths is not None else []
    failures: list[dict[str, Any]] = []
    external_parent: list[dict[str, Any]] = []
    external_parent_count = 0
    passed = 0
    rewritten: collections.Counter[str] = collections.Counter()
    for path in paths:
        try:
            row = validate_track_roundtrip(project_root, path)
        except Exception as exc:
            failures.append({"path": _logical(root, path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if row.get("status") != "PASS":
            failures.append({
                "path": _logical(root, path),
                "changed_byte_count": row.get("changed_byte_count"),
            })
            continue
        passed += 1
        for key, value in (row.get("rewritten_records") or {}).items():
            rewritten[str(key)] += int(value or 0)
        if not bool(row.get("hierarchy_closed", True)):
            external_parent_count += 1
            if len(external_parent) < max(0, int(sample_limit)):
                external_parent.append({
                    "path": _logical(root, path),
                    "missing_parent_names": list(row.get("missing_parent_names") or []),
                })
    total = len(paths)
    return {
        "format": SMB_FORMAT,
        "status": "PASS" if total and not failures and passed == total and not missing_requested else ("EMPTY" if not total and not requested else "FAIL"),
        "scope": "READ_ONLY_CANDIDATE_WRITER_EVIDENCE",
        "client_root": str(root),
        "prefixes": [str(x) for x in prefixes],
        "explicit_logical_paths": logical_paths is not None,
        "requested_file_count": len(requested) if logical_paths is not None else None,
        "missing_requested_files": missing_requested,
        "file_count": total,
        "pass_count": passed,
        "fail_count": len(failures),
        "rewritten_record_counts": dict(sorted(rewritten.items())),
        "external_parent_file_count": external_parent_count,
        "external_parent_sample": external_parent,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "hierarchy_note": "writer layout proof may preserve support SMBs with external parents; animation evaluation still requires a closed hierarchy",
        "production_authorized": False,
        "client_modified": False,
    }


def _sha_path(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_inx_writer_edit_corpus(
    client_root: pathlib.Path,
    *,
    prefixes: Iterable[str] = DEFAULT_PREFIXES,
    logical_paths: Iterable[str] | None = None,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Exercise one allowlisted existing MotionInfo edit per INX in temp output.

    This proves edit/reparse/allowlist behavior only.  The semantic edit is not
    installed into the client and does not grant production authorization.
    """
    import pt_inx_motion_core_v2 as inxcore

    root = pathlib.Path(client_root).resolve()
    requested = _explicit_request_logicals(".inx", logical_paths) if logical_paths is not None else []
    paths = _explicit_files(root, ".inx", requested) if logical_paths is not None else _files(root, ".inx", prefixes)
    missing_requested = _explicit_missing(root, requested, paths) if logical_paths is not None else []
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    edited = 0
    layouts: collections.Counter[str] = collections.Counter()
    with tempfile.TemporaryDirectory(prefix="pt_inx_edit_corpus_") as td:
        td_root = pathlib.Path(td)
        for index, path in enumerate(paths):
            source_sha = _sha_path(path)
            try:
                parsed = inxcore.parse_inx(path)
                motions = list(parsed.get("motions") or [])
                if not motions:
                    skipped.append({"path": _logical(root, path), "reason": "NO_MOTIONINFO_RECORDS"})
                    continue
                motion = motions[0]
                repeat = int(motion.get("repeat") or 0) ^ 1
                out = td_root / f"{index:05d}_{path.name}"
                result = patch_motion(path, out, motion=int(motion["index"]), repeat=repeat)
                if result.get("status") != "PASS" or not result.get("allowed_offsets_only") or not result.get("file_size_preserved"):
                    raise RuntimeError("candidate edit contract did not pass")
                if _sha_path(path) != source_sha:
                    raise RuntimeError("source INX changed during edit corpus audit")
                edited += 1
                layouts[str(result.get("layout") or "UNKNOWN")] += 1
            except Exception as exc:
                failures.append({"path": _logical(root, path), "error": f"{type(exc).__name__}: {exc}"})
    total = len(paths)
    return {
        "format": INX_EDIT_FORMAT,
        "status": "PASS" if total and not failures and edited + len(skipped) == total and not missing_requested else ("EMPTY" if not total and not requested else "FAIL"),
        "scope": "TEMP_OUTPUT_EDIT_PROBE_NO_CLIENT_WRITE",
        "client_root": str(root),
        "prefixes": [str(x) for x in prefixes],
        "explicit_logical_paths": logical_paths is not None,
        "requested_file_count": len(requested) if logical_paths is not None else None,
        "missing_requested_files": missing_requested,
        "file_count": total,
        "edited_file_count": edited,
        "no_editable_record_count": len(skipped),
        "fail_count": len(failures),
        "layout_counts": dict(sorted(layouts.items())),
        "skip_sample": skipped[: max(0, int(sample_limit))],
        "failure_sample": failures[: max(0, int(sample_limit))],
        "production_authorized": False,
        "client_modified": False,
    }


def audit_smb_writer_edit_corpus(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    *,
    prefixes: Iterable[str] = DEFAULT_PREFIXES,
    logical_paths: Iterable[str] | None = None,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Exercise one existing key edit per editable SMB in temporary output."""
    project_root = pathlib.Path(project_root).resolve()
    root = pathlib.Path(client_root).resolve()
    requested = _explicit_request_logicals(".smb", logical_paths) if logical_paths is not None else []
    paths = _explicit_files(root, ".smb", requested) if logical_paths is not None else _files(root, ".smb", prefixes)
    missing_requested = _explicit_missing(root, requested, paths) if logical_paths is not None else []
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    track_counts: collections.Counter[str] = collections.Counter()
    edited = 0
    with tempfile.TemporaryDirectory(prefix="pt_smb_edit_corpus_") as td:
        td_root = pathlib.Path(td)
        for index, path in enumerate(paths):
            source_sha = _sha_path(path)
            try:
                key = first_editable_key(project_root, path)
                if key is None:
                    skipped.append({"path": _logical(root, path), "reason": "NO_EDITABLE_EXISTING_KEY"})
                    continue
                out = td_root / f"{index:05d}_{path.name}"
                values = list(key.get("values") or [])
                track = str(key["track"])
                kwargs: dict[str, Any] = {}
                if track == "scale":
                    x = int(values[0]) if values else 0
                    kwargs["x"] = x - 1 if x >= 2**31 - 1 else x + 1
                else:
                    x = float(values[0]) if values else 0.0
                    kwargs["x"] = _adjacent_distinct_float32(x)
                result = patch_key(
                    project_root, path, out, bone=key["bone"], track=track,
                    key_index=int(key["key_index"]), **kwargs,
                )
                if result.get("status") != "PASS" or not result.get("allowed_offsets_only") or not result.get("file_size_preserved"):
                    raise RuntimeError("candidate SMB edit contract did not pass")
                if _sha_path(path) != source_sha:
                    raise RuntimeError("source SMB changed during edit corpus audit")
                edited += 1
                track_counts[track] += 1
            except Exception as exc:
                failures.append({"path": _logical(root, path), "error": f"{type(exc).__name__}: {exc}"})
    total = len(paths)
    return {
        "format": SMB_EDIT_FORMAT,
        "status": "PASS" if total and not failures and edited + len(skipped) == total and not missing_requested else ("EMPTY" if not total and not requested else "FAIL"),
        "scope": "TEMP_OUTPUT_EDIT_PROBE_NO_CLIENT_WRITE",
        "client_root": str(root),
        "prefixes": [str(x) for x in prefixes],
        "explicit_logical_paths": logical_paths is not None,
        "requested_file_count": len(requested) if logical_paths is not None else None,
        "missing_requested_files": missing_requested,
        "file_count": total,
        "edited_file_count": edited,
        "no_editable_key_file_count": len(skipped),
        "fail_count": len(failures),
        "track_counts": dict(sorted(track_counts.items())),
        "skip_sample": skipped[: max(0, int(sample_limit))],
        "failure_sample": failures[: max(0, int(sample_limit))],
        "production_authorized": False,
        "client_modified": False,
    }



def _registry_motion_contexts(registry, resolver) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return unique physically-resolved INX/SMB contexts without guessing paths."""
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for asset in registry.assets:
        if not getattr(asset, "animation_binding_ready", False):
            continue
        try:
            physical = registry.physical_dependency_status(asset)
            if not physical.get("animation_binding_ready_physical"):
                unresolved.append({
                    "asset": asset.primary_path,
                    "reason": "MISSING_PHYSICAL_DEPENDENCY",
                    "missing": list(physical.get("missing") or []),
                })
                continue
            ctx = resolve_asset_motion_context(asset, resolver, require_physical=True)
        except Exception as exc:
            unresolved.append({
                "asset": asset.primary_path,
                "reason": "MOTION_CONTEXT_RESOLUTION_FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        key = (str(ctx["motion_inx"]).casefold(), str(ctx["motion_smb"]).casefold())
        row = contexts.setdefault(key, {
            "motion_inx": ctx["motion_inx"],
            "motion_smb": ctx["motion_smb"],
            "inx_path": pathlib.Path(ctx["inx_path"]),
            "smb_path": pathlib.Path(ctx["smb_path"]),
            "assets": [],
        })
        row["assets"].append(asset.primary_path)
    return sorted(contexts.values(), key=lambda x: (str(x["motion_inx"]).casefold(), str(x["motion_smb"]).casefold())), unresolved


def _semantic_inx_edit(project_root: pathlib.Path, inx: pathlib.Path, smb: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    """Shift one existing active motion start by one frame and re-evaluate source-side."""
    evaluator, inxcore = load_motion_system(project_root)
    parsed = inxcore.parse_inx(inx)
    smb_parsed = evaluator.parse_smb(smb)
    motions = enrich_motions(parsed, smb_parsed)
    preferred = ("STAND", "WALK", "ATTACK", "DAMAGE", "SKILL", "RUN", "DEAD")
    active = [m for m in motions if m.get("active_container") and int(m.get("end", 0)) - int(m.get("start", 0)) >= 2]
    active.sort(key=lambda m: (preferred.index(m.get("state_name")) if m.get("state_name") in preferred else len(preferred), int(m["index"])))
    if not active:
        return {"status": "SKIP", "reason": "NO_ACTIVE_MOTION_WITH_EDITABLE_SPAN"}
    motion = active[0]
    patched = patch_motion(inx, output, motion=int(motion["index"]), start=int(motion["start"]) + 1)
    semantic = audit_animation_source_regression(project_root, output, smb, mode="all")
    if patched.get("status") != "PASS" or semantic.get("status") != "PASS":
        raise RuntimeError("edited INX did not pass candidate writer + source animation sanity")
    return {
        "status": "PASS",
        "motion_index": int(motion["index"]),
        "state": motion.get("state_name"),
        "old_start": int(motion["start"]),
        "new_start": int(motion["start"]) + 1,
        "changed_byte_count": int(patched.get("changed_byte_count") or 0),
        "allowlisted_offsets_only": bool(patched.get("allowed_offsets_only")),
        "source_animation_status": semantic.get("status"),
        "audited_motion_count": int(semantic.get("audited_motion_count") or 0),
    }


def _semantic_smb_edit(project_root: pathlib.Path, inx: pathlib.Path, smb: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    """Edit one existing SMB key in a temp copy and re-evaluate the INX context."""
    key = first_editable_key(project_root, smb)
    if key is None:
        return {"status": "SKIP", "reason": "NO_EDITABLE_EXISTING_KEY"}
    if not key.get("hierarchy_closed", True):
        # Binary preservation is already tested for external-parent support SMBs,
        # but source pose evaluation deliberately requires a closed hierarchy.
        return {"status": "SKIP", "reason": "EXTERNAL_PARENT_SUPPORT_SMB", "missing_parent_names": key.get("missing_parent_names") or []}
    values = list(key.get("values") or [])
    track = str(key["track"])
    if track == "scale":
        old = int(values[0]) if values else 0
        new = old - 1 if old >= 2**31 - 1 else old + 1
        kwargs: dict[str, Any] = {"x": new}
    else:
        old = float(values[0]) if values else 0.0
        kwargs = {"x": _adjacent_distinct_float32(old)}
    patched = patch_key(
        project_root, smb, output,
        bone=key["bone"], track=track, key_index=int(key["key_index"]), **kwargs,
    )
    semantic = audit_animation_source_regression(project_root, inx, output, mode="all")
    if patched.get("status") != "PASS" or semantic.get("status") != "PASS":
        raise RuntimeError("edited SMB did not pass candidate writer + source animation sanity")
    return {
        "status": "PASS",
        "bone": key["bone"],
        "track": track,
        "key_index": int(key["key_index"]),
        "frame": int(key["frame"]),
        "changed_byte_count": int(patched.get("changed_byte_count") or 0),
        "allowlisted_offsets_only": bool(patched.get("allowed_offsets_only")),
        "source_animation_status": semantic.get("status"),
        "audited_motion_count": int(semantic.get("audited_motion_count") or 0),
    }


class _MotionSemanticTimeout(TimeoutError):
    pass


@contextmanager
def _motion_semantic_timeout(seconds: float):
    """Best-effort POSIX wall timeout for one semantic writer operation.

    The Release 1 external gate currently runs on Linux.  Where SIGALRM is not
    available (or the caller is not the main thread), this degrades to no timer
    rather than weakening source-integrity checks.
    """
    seconds = float(seconds or 0)
    if seconds <= 0 or not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        yield
        return
    old_handler = None
    old_timer = (0.0, 0.0)
    armed = False

    def _raise_timeout(signum, frame):  # pragma: no cover - frame is interpreter supplied
        raise _MotionSemanticTimeout(f"semantic writer operation exceeded {seconds:g}s")

    try:
        old_handler = signal.getsignal(signal.SIGALRM)
        old_timer = signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        armed = True
    except (ValueError, OSError):
        # signal.signal() is main-thread-only.  Direct library users on other
        # threads still get the audit, just without the watchdog.
        if old_timer and old_timer[0] > 0:
            try:
                signal.setitimer(signal.ITIMER_REAL, *old_timer)
            except Exception:
                pass
        yield
        return
    try:
        yield
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
            if old_timer and old_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, *old_timer)


def _motion_context_key(ctx: dict[str, Any]) -> str:
    raw = f"{str(ctx.get('motion_inx') or '').casefold()}\0{str(ctx.get('motion_smb') or '').casefold()}"
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()


def _load_motion_semantic_checkpoint(path: pathlib.Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not pathlib.Path(path).is_file():
        return {}
    entries: dict[str, dict[str, Any]] = {}
    try:
        with pathlib.Path(path).open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    # A killed process may leave one incomplete final line.  All
                    # earlier complete checkpoints remain valid.
                    continue
                if row.get("format") != "PT_MOTION_SEMANTIC_CHECKPOINT_V1":
                    continue
                key = str(row.get("context_key") or "")
                if key:
                    entries[key] = row
    except Exception:
        return {}
    return entries


def _append_motion_semantic_checkpoint(path: pathlib.Path | None, entry: dict[str, Any]) -> None:
    if path is None:
        return
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(entry)
    payload["format"] = "PT_MOTION_SEMANTIC_CHECKPOINT_V1"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        fh.flush()


def _write_motion_semantic_in_progress(path: pathlib.Path | None, payload: dict[str, Any] | None) -> None:
    if path is None:
        return
    path = pathlib.Path(path)
    marker = path.with_name(path.name + ".in_progress.json")
    if payload is None:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_name(marker.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(marker)


def _checkpoint_row_reusable(entry: dict[str, Any] | None, *, inx_sha: str, smb_sha: str) -> bool:
    if not isinstance(entry, dict):
        return False
    row = entry.get("row")
    if not isinstance(row, dict):
        return False
    if entry.get("inx_sha256") != inx_sha or entry.get("smb_sha256") != smb_sha:
        return False
    if str(row.get("source_integrity") or "") != "PASS":
        return False
    # FAIL/TIMEOUT rows are deliberately retried on --resume.  Only completed
    # PASS/SKIP semantic evidence is reusable for byte-identical sources.
    for key in ("inx_edit", "smb_edit"):
        if str((row.get(key) or {}).get("status") or "") == "FAIL":
            return False
    return True


def audit_motion_writer_semantic_edit_corpus(
    project_root: pathlib.Path,
    registry,
    resolver,
    *,
    pair_limit: int = 0,
    sample_limit: int = 50,
    progress: bool = False,
    operation_timeout_seconds: float = 120.0,
    checkpoint_path: pathlib.Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Prove candidate INX/SMB edits remain source-side evaluable.

    This is stronger than a reparse/byte-allowlist probe, but deliberately weaker
    than Blender visual or game-runtime certification. All edits are temporary.

    Each INX and SMB semantic operation has an independent watchdog on POSIX so
    one pathological physical context cannot stall the entire Release 1 gate.
    Completed PASS/SKIP rows can be checkpointed and reused on --resume only when
    both original source SHA-256 values still match exactly.
    """
    project_root = pathlib.Path(project_root).resolve()
    checkpoint_path = pathlib.Path(checkpoint_path).resolve() if checkpoint_path is not None else None
    contexts, unresolved = _registry_motion_contexts(registry, resolver)
    selected = contexts[: int(pair_limit)] if pair_limit and pair_limit > 0 else contexts
    from .release_1_coverage import CONTENT_DOMAINS, content_domain
    asset_domains = {
        str(asset.primary_path or "").replace("\\", "/").casefold(): content_domain(asset)
        for asset in registry.assets
    }
    rows: list[dict[str, Any]] = []
    resumed_contexts = 0
    checkpoint_entries = _load_motion_semantic_checkpoint(checkpoint_path) if resume else {}
    if progress:
        print(
            f"[release-1-auto] MOTION_SEMANTIC begin contexts={len(selected)} total={len(contexts)} "
            f"timeout={float(operation_timeout_seconds):g}s resume_checkpoint={bool(checkpoint_entries)}",
            flush=True,
        )
    with tempfile.TemporaryDirectory(prefix="pt_motion_semantic_edit_") as td:
        td_root = pathlib.Path(td)
        for index, ctx in enumerate(selected):
            inx = pathlib.Path(ctx["inx_path"])
            # PT_RC6_1_2_MOTION_BUDGET
            _pt_ctx_budget = min(float(operation_timeout_seconds), float(__import__('os').environ.get('PT_ASSET_MOTION_CONTEXT_BUDGET_SEC', operation_timeout_seconds)))
            _pt_ctx_deadline = __import__('time').monotonic() + _pt_ctx_budget
            def _pt_ctx_remaining():
                return max(0.05, min(float(operation_timeout_seconds), _pt_ctx_deadline - __import__('time').monotonic()))

            smb = pathlib.Path(ctx["smb_path"])
            inx_sha = _sha_path(inx)
            smb_sha = _sha_path(smb)
            context_key = _motion_context_key(ctx)
            cached = checkpoint_entries.get(context_key)
            if resume and _checkpoint_row_reusable(cached, inx_sha=inx_sha, smb_sha=smb_sha):
                row = dict(cached["row"])
                rows.append(row)
                resumed_contexts += 1
                if progress:
                    print(
                        f"[release-1-auto] MOTION_SEMANTIC {index + 1}/{len(selected)} RESUME "
                        f"inx={row.get('motion_inx')} smb={row.get('motion_smb')}",
                        flush=True,
                    )
                continue

            label = f"{ctx.get('motion_inx')} + {ctx.get('motion_smb')}"
            if progress:
                print(
                    f"[release-1-auto] MOTION_SEMANTIC {index + 1}/{len(selected)} START {label}",
                    flush=True,
                )
            _write_motion_semantic_in_progress(checkpoint_path, {
                "format": "PT_MOTION_SEMANTIC_IN_PROGRESS_V1",
                "index": index + 1,
                "total": len(selected),
                "motion_inx": ctx.get("motion_inx"),
                "motion_smb": ctx.get("motion_smb"),
                "inx_sha256": inx_sha,
                "smb_sha256": smb_sha,
                "timeout_seconds_per_writer": float(_pt_ctx_remaining()),
            })
            started = time.monotonic()
            row: dict[str, Any] = {
                "motion_inx": ctx["motion_inx"],
                "motion_smb": ctx["motion_smb"],
                "asset_count": len(ctx["assets"]),
                "assets": list(ctx["assets"]),
                "domains": sorted({
                    asset_domains.get(str(x).replace("\\", "/").casefold(), "")
                    for x in ctx["assets"]
                    if asset_domains.get(str(x).replace("\\", "/").casefold(), "") in CONTENT_DOMAINS
                }),
            }
            try:
                with _motion_semantic_timeout(_pt_ctx_remaining()):
                    inx_result = _semantic_inx_edit(project_root, inx, smb, td_root / f"{index:04d}_edit.inx")
                row["inx_edit"] = inx_result
            except _MotionSemanticTimeout as exc:
                row["inx_edit"] = {
                    "status": "FAIL", "reason": "TIMEOUT", "error": str(exc),
                    "timeout_seconds": float(_pt_ctx_remaining()),
                }
            except Exception as exc:
                row["inx_edit"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
            try:
                with _motion_semantic_timeout(_pt_ctx_remaining()):
                    smb_result = _semantic_smb_edit(project_root, inx, smb, td_root / f"{index:04d}_edit.smb")
                row["smb_edit"] = smb_result
            except _MotionSemanticTimeout as exc:
                row["smb_edit"] = {
                    "status": "FAIL", "reason": "TIMEOUT", "error": str(exc),
                    "timeout_seconds": float(_pt_ctx_remaining()),
                }
            except Exception as exc:
                row["smb_edit"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
            if _sha_path(inx) != inx_sha or _sha_path(smb) != smb_sha:
                row["source_integrity"] = "FAIL"
            else:
                row["source_integrity"] = "PASS"
            row["elapsed_seconds"] = round(time.monotonic() - started, 6)
            rows.append(row)
            entry = {
                "context_key": context_key,
                "inx_sha256": inx_sha,
                "smb_sha256": smb_sha,
                "row": row,
            }
            _append_motion_semantic_checkpoint(checkpoint_path, entry)
            checkpoint_entries[context_key] = entry
            _write_motion_semantic_in_progress(checkpoint_path, None)
            if progress:
                print(
                    f"[release-1-auto] MOTION_SEMANTIC {index + 1}/{len(selected)} DONE "
                    f"inx={(row.get('inx_edit') or {}).get('status')} "
                    f"smb={(row.get('smb_edit') or {}).get('status')} "
                    f"source={row.get('source_integrity')} elapsed={row.get('elapsed_seconds')}s",
                    flush=True,
                )

    _write_motion_semantic_in_progress(checkpoint_path, None)
    failures: list[dict[str, Any]] = []
    for row in rows:
        for writer, key in (("INX", "inx_edit"), ("SMB", "smb_edit")):
            result = row.get(key) or {}
            if str(result.get("status") or "") == "FAIL":
                failures.append({
                    "motion_inx": row.get("motion_inx"), "motion_smb": row.get("motion_smb"),
                    "writer": writer, "error": result.get("error"), "reason": result.get("reason"),
                })
        if str(row.get("source_integrity") or "") != "PASS":
            failures.append({
                "motion_inx": row.get("motion_inx"), "motion_smb": row.get("motion_smb"),
                "writer": "SOURCE", "error": "SOURCE_CHANGED_DURING_TEMP_EDIT_AUDIT",
            })

    inx_pass = sum(str((row.get("inx_edit") or {}).get("status") or "") == "PASS" for row in rows)
    smb_pass = sum(str((row.get("smb_edit") or {}).get("status") or "") == "PASS" for row in rows)
    inx_skip = sum(str((row.get("inx_edit") or {}).get("status") or "") == "SKIP" for row in rows)
    smb_skip = sum(str((row.get("smb_edit") or {}).get("status") or "") == "SKIP" for row in rows)
    timeout_count = sum(
        str((row.get(key) or {}).get("reason") or "") == "TIMEOUT"
        for row in rows for key in ("inx_edit", "smb_edit")
    )
    complete_selection = len(selected) == len(contexts)
    by_domain: dict[str, dict[str, Any]] = {
        d: {
            "context_count": 0,
            "inx_semantic_edit_pass": 0,
            "inx_semantic_edit_skip": 0,
            "smb_semantic_edit_pass": 0,
            "smb_semantic_edit_skip": 0,
            "failed_context_count": 0,
            "unresolved_asset_count": 0,
        }
        for d in CONTENT_DOMAINS
    }
    for row in rows:
        failed_row = (
            str(row.get("source_integrity") or "PASS") != "PASS"
            or str((row.get("inx_edit") or {}).get("status") or "") == "FAIL"
            or str((row.get("smb_edit") or {}).get("status") or "") == "FAIL"
        )
        for domain in row.get("domains") or []:
            if domain not in by_domain:
                continue
            summary = by_domain[domain]
            summary["context_count"] += 1
            if failed_row:
                summary["failed_context_count"] += 1
            for key, prefix in (("inx_edit", "inx_semantic_edit"), ("smb_edit", "smb_semantic_edit")):
                state = str((row.get(key) or {}).get("status") or "")
                if state == "PASS":
                    summary[prefix + "_pass"] += 1
                elif state == "SKIP":
                    summary[prefix + "_skip"] += 1
    for row in unresolved:
        domain = asset_domains.get(str(row.get("asset") or "").replace("\\", "/").casefold(), "")
        if domain in by_domain:
            by_domain[domain]["unresolved_asset_count"] += 1
    pass_domains: list[str] = []
    for domain, summary in by_domain.items():
        count = int(summary["context_count"])
        unresolved_count = int(summary["unresolved_asset_count"])
        failed_count = int(summary["failed_context_count"])
        if not count and not unresolved_count:
            summary["status"] = "NOT_PRESENT"
        elif unresolved_count or failed_count or not complete_selection:
            summary["status"] = "FAIL"
        else:
            summary["status"] = "PASS"
            pass_domains.append(domain)

    status = (
        "PASS"
        if selected and complete_selection and not unresolved and not failures
        else ("EMPTY" if not selected and not contexts and not unresolved else "FAIL")
    )
    return {
        "format": MOTION_SEMANTIC_EDIT_FORMAT,
        "status": status,
        "scope": "TEMP_EDIT_SOURCE_SIDE_SEMANTIC_SANITY_NOT_BLENDER_OR_RUNTIME_CERTIFICATION",
        "registry_motion_contexts": len(contexts),
        "audited_contexts": len(rows),
        "corpus_complete": complete_selection and len(rows) == len(selected),
        "selection_limited": not complete_selection,
        "pair_limit": int(pair_limit),
        "inx_semantic_edit_pass": int(inx_pass),
        "inx_semantic_edit_skip": int(inx_skip),
        "smb_semantic_edit_pass": int(smb_pass),
        "smb_semantic_edit_skip": int(smb_skip),
        "fail_count": len(failures),
        "timeout_count": int(timeout_count),
        "operation_timeout_seconds": float(operation_timeout_seconds),
        "checkpoint_path": str(checkpoint_path) if checkpoint_path is not None else None,
        "resumed_contexts": int(resumed_contexts),
        "unresolved_physical_assets": len(unresolved),
        "by_domain": by_domain,
        "pass_domains": sorted(pass_domains),
        "rows": rows,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "unresolved_sample": unresolved[: max(0, int(sample_limit))],
        "visual_certification": False,
        "blender_pose_space_certification": False,
        "game_runtime_certification": False,
        "production_authorized": False,
        "client_modified": False,
    }
