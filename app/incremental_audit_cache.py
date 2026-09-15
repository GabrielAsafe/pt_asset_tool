from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import os
import pickle
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

CACHE_FORMAT = "PT_ASSET_INCREMENTAL_AUDIT_CACHE_V1"
CACHE_SCHEMA = 1


class IncrementalCacheError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class CachePolicy:
    mode: str = "strict"  # off | strict | trust-readonly
    cache_pass_only: bool = True

    @classmethod
    def from_env(cls) -> "CachePolicy":
        mode = os.environ.get("PT_ASSET_CACHE_MODE", "strict").strip().lower()
        if mode not in {"off", "strict", "trust-readonly"}:
            raise IncrementalCacheError(
                "PT_ASSET_CACHE_MODE must be off, strict, or trust-readonly"
            )
        return cls(mode=mode)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def code_fingerprint(app_dir: os.PathLike[str] | str) -> str:
    """Hash Python validator code only; never hashes game assets."""
    root = Path(app_dir).resolve()
    h = hashlib.sha256()
    ignored_parts = {"pt_build", "__pycache__", ".git"}
    for path in sorted(root.rglob("*.py")):
        if any(part in ignored_parts for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix().encode("utf-8")
        h.update(len(rel).to_bytes(4, "big"))
        h.update(rel)
        h.update(bytes.fromhex(_sha256_file(path)))
    return h.hexdigest()


def _stat_identity(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "device": int(st.st_dev),
        "inode": int(st.st_ino),
        "mtime_ns": int(st.st_mtime_ns),
        "size": int(st.st_size),
    }


def trusted_readonly_root_fingerprint(root: os.PathLike[str] | str) -> Dict[str, Any]:
    """
    O(1) root identity. This intentionally trusts the external invariant that
    the root was not modified outside PT Asset Tool. It does NOT inspect files.
    """
    p = Path(root).resolve()
    if not p.is_dir():
        raise IncrementalCacheError(f"root does not exist or is not a directory: {p}")
    data = _stat_identity(p)
    data.update({"mode": "trust-readonly", "recursive_scan": False})
    return data


def strict_root_fingerprint(root: os.PathLike[str] | str) -> Dict[str, Any]:
    """
    Metadata-only recursive fingerprint. Reads directory entries + stat data,
    never file contents. More conservative than trust-readonly, but still much
    cheaper than reparsing/hashing the full asset corpus.
    """
    p = Path(root).resolve()
    if not p.is_dir():
        raise IncrementalCacheError(f"root does not exist or is not a directory: {p}")
    h = hashlib.sha256()
    count = 0
    total_size = 0
    stack = [p]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise IncrementalCacheError(f"cannot scan {current}: {exc}") from exc
        entries.sort(key=lambda e: e.name)
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise IncrementalCacheError(f"cannot stat {entry.path}: {exc}") from exc
            rel = Path(entry.path).relative_to(p).as_posix()
            record = (
                rel,
                int(st.st_mode),
                int(st.st_size),
                int(st.st_mtime_ns),
                int(st.st_ino),
            )
            encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            h.update(len(encoded).to_bytes(4, "big"))
            h.update(encoded)
            count += 1
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                total_size += int(st.st_size)
    return {
        "path": str(p),
        "mode": "strict",
        "recursive_scan": True,
        "entry_count": count,
        "total_size": total_size,
        "metadata_sha256": h.hexdigest(),
    }


def root_fingerprint(root: os.PathLike[str] | str, policy: CachePolicy) -> Dict[str, Any]:
    if policy.mode == "trust-readonly":
        return trusted_readonly_root_fingerprint(root)
    if policy.mode == "strict":
        return strict_root_fingerprint(root)
    return {"path": str(Path(root).resolve()), "mode": "off"}


def result_status(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        status = value.get("status")
        return str(status).upper() if status is not None else None
    status = getattr(value, "status", None)
    return str(status).upper() if status is not None else None


def stable_arg_summary(args: Sequence[Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """A conservative, JSON-safe description used only in the cache key."""
    def conv(v: Any) -> Any:
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {str(k): conv(v[k]) for k in sorted(v, key=lambda x: str(x))}
        return {"type": type(v).__qualname__, "repr": repr(v)[:500]}

    return {"args": [conv(v) for v in args], "kwargs": {k: conv(kwargs[k]) for k in sorted(kwargs)}}


class GateCache:
    def __init__(
        self,
        cache_root: os.PathLike[str] | str,
        *,
        app_dir: os.PathLike[str] | str,
        policy: Optional[CachePolicy] = None,
    ) -> None:
        self.root = Path(cache_root).resolve()
        self.entries = self.root / "entries"
        self.entries.mkdir(parents=True, exist_ok=True)
        self.app_dir = Path(app_dir).resolve()
        self.policy = policy or CachePolicy.from_env()
        self._code_fp: Optional[str] = None

    @property
    def code_fp(self) -> str:
        if self._code_fp is None:
            self._code_fp = code_fingerprint(self.app_dir)
        return self._code_fp

    def _key_payload(
        self,
        gate_name: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
    ) -> Dict[str, Any]:
        return {
            "format": CACHE_FORMAT,
            "schema": CACHE_SCHEMA,
            "gate": gate_name,
            "code_sha256": self.code_fp,
            "policy": dataclasses.asdict(self.policy),
            "roots": {name: root_fingerprint(path, self.policy) for name, path in sorted(roots.items())},
            "call": stable_arg_summary(args, kwargs),
        }

    def cache_key(
        self,
        gate_name: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
    ) -> Tuple[str, Dict[str, Any]]:
        payload = self._key_payload(gate_name, args, kwargs, roots)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest(), payload

    def _paths(self, key: str) -> Tuple[Path, Path]:
        return self.entries / f"{key}.pickle", self.entries / f"{key}.json"

    def load(
        self,
        gate_name: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
    ) -> Optional[Any]:
        if self.policy.mode == "off":
            return None
        key, _ = self.cache_key(gate_name, args, kwargs, roots)
        data_path, meta_path = self._paths(key)
        if not data_path.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("format") != CACHE_FORMAT or meta.get("cache_key") != key:
                return None
            with data_path.open("rb") as fh:
                return pickle.load(fh)
        except Exception:
            return None

    def store(
        self,
        gate_name: str,
        value: Any,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
        *,
        source: str = "executed",
    ) -> bool:
        if self.policy.mode == "off":
            return False
        status = result_status(value)
        if self.policy.cache_pass_only and status != "PASS":
            return False
        key, payload = self.cache_key(gate_name, args, kwargs, roots)
        data_path, meta_path = self._paths(key)
        fd, tmp = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=str(self.entries))
        try:
            with os.fdopen(fd, "wb") as fh:
                pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, data_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        meta = {
            "format": CACHE_FORMAT,
            "cache_key": key,
            "gate": gate_name,
            "status": status,
            "source": source,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "key_payload": payload,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return True

    def warm_from_json_report(
        self,
        gate_name: str,
        report_path: os.PathLike[str] | str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
    ) -> Optional[Any]:
        p = Path(report_path)
        if not p.is_file():
            return None
        try:
            value = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if result_status(value) != "PASS":
            return None
        self.store(gate_name, value, args, kwargs, roots, source=f"report:{p}")
        return value

    def call(
        self,
        gate_name: str,
        func: Callable[..., Any],
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        roots: Mapping[str, os.PathLike[str] | str],
        *,
        warm_reports: Sequence[os.PathLike[str] | str] = (),
    ) -> Any:
        cached = self.load(gate_name, args, kwargs, roots)
        if cached is not None:
            print(f"[incremental-cache] HIT  gate={gate_name} mode={self.policy.mode}")
            return cached
        for report in warm_reports:
            warmed = self.warm_from_json_report(gate_name, report, args, kwargs, roots)
            if warmed is not None:
                print(f"[incremental-cache] WARM gate={gate_name} report={report}")
                return warmed
        print(f"[incremental-cache] MISS gate={gate_name} mode={self.policy.mode}")
        value = func(*args, **dict(kwargs))
        if self.store(gate_name, value, args, kwargs, roots):
            print(f"[incremental-cache] SAVE gate={gate_name} status=PASS")
        return value


def infer_root_from_call(func: Callable[..., Any], args: Sequence[Any], kwargs: Mapping[str, Any], fallback: Optional[str] = None) -> Optional[str]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **dict(kwargs))
        for name, value in bound.arguments.items():
            lname = name.lower()
            if "server_root" in lname or lname in {"root", "server"}:
                if isinstance(value, (str, os.PathLike)):
                    return str(value)
    except Exception:
        pass
    return fallback
