from __future__ import annotations
import csv, hashlib, json, os, pathlib, signal, subprocess, tempfile
from datetime import datetime, timezone
from typing import Iterable


def norm_path(value: str | pathlib.Path | None) -> str:
    # Client/model strings sometimes serialize repeated Windows separators
    # (e.g. Effect\\ObjAnimationData\\Test\\TEST1.tga).  Physical client
    # paths contain a single separator, so canonicalize repeated slashes before
    # case-sensitive/case-insensitive resolver lookup.
    out = str(value or "").replace("\\", "/").lstrip("./")
    while "//" in out:
        out = out.replace("//", "/")
    return out


def low_path(value: str | pathlib.Path | None) -> str:
    return norm_path(value).lower()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_id(namespace: str, logical_path: str) -> str:
    raw = f"{namespace}:{low_path(logical_path)}".encode("utf-8")
    return "AST-" + hashlib.sha1(raw).hexdigest()[:12].upper()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def atomic_write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpname = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = pathlib.Path(tmpname)
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def append_jsonl(path: pathlib.Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def truth(value) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "y"}


def run_logged(
    cmd: list[str], log: pathlib.Path, cwd: pathlib.Path | None = None, *,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess:
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(x) for x in cmd]
    if timeout_seconds is None or float(timeout_seconds) <= 0:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    else:
        child = subprocess.Popen(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
        )
        try:
            stdout, _ = child.communicate(timeout=float(timeout_seconds))
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except Exception:
                    child.kill()
            else:
                child.kill()
            stdout, _ = child.communicate()
            log.write_text(stdout or "", encoding="utf-8")
            raise TimeoutError(
                f"command timeout after {float(timeout_seconds):g}s; log={log}; command={argv[:4]}"
            )
        proc = subprocess.CompletedProcess(argv, child.returncode, stdout=stdout, stderr=None)
    log.write_text(proc.stdout or "", encoding="utf-8")
    if proc.returncode:
        lines=(proc.stdout or "").splitlines()
        tail=" | ".join(lines[-12:])
        if len(tail) > 1600:
            tail=tail[-1600:]
        raise RuntimeError(f"command failed rc={proc.returncode}; log={log}; tail={tail}")
    return proc
