from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any


def app_project_root(project_root: Path) -> Path:
    """Normalize either repository root or app root to the active app directory.

    The UI process runs with ``project_root`` pointing at ``.../pt_asset_tool/app``.
    Patch/CLI helpers may instead pass the repository root.  Legacy workspace
    code must accept both without ever producing ``app/app/pt_build``.
    """
    root = Path(project_root).expanduser().resolve()
    if (root / "pt_asset.py").is_file() and (root / "pt_asset_tool").is_dir():
        return root
    app = root / "app"
    if (app / "pt_asset.py").is_file() and (app / "pt_asset_tool").is_dir():
        return app.resolve()
    return root


def legacy_build_root(project_root: Path) -> Path:
    return app_project_root(project_root) / "pt_build"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def legacy_bucket(name: str) -> int:
    """Bucket used by MudarNome/Level Editor and the DataServer stores.

    Native evidence upper-cases ASCII bytes, sums them in an 8-bit register and
    therefore returns sum & 0xff (0..255).
    """
    total = 0
    for ch in str(name):
        o = ord(ch.upper())
        if o > 0x7F:
            # The legacy tools are ANSI/ASCII oriented.  Keeping only the low byte
            # matches the native char arithmetic better than Unicode case folding.
            o &= 0xFF
        total = (total + o) & 0xFF
    return total


def item_distributor_bucket(name: str) -> int:
    """Exact ItemDistributor VB bucket semantics.

    Its loop subtracts 256 only while total > 256, so an exact multiple may
    return 256 rather than 0.  This oddity is retained for compatibility.
    """
    total = sum(ord(ch.upper()) for ch in str(name))
    while total > 256:
        total -= 256
    return total


def dataserver_path(server_root: Path, store: str, key: str, suffix: str) -> Path:
    return Path(server_root) / "DataServer" / store / str(legacy_bucket(key)) / f"{key}{suffix}"


def find_casefold_child(parent: Path, name: str) -> Path | None:
    direct = parent / name
    if direct.exists():
        return direct
    if not parent.is_dir():
        return None
    target = name.casefold()
    try:
        for p in parent.iterdir():
            if p.name.casefold() == target:
                return p
    except OSError:
        return None
    return None


def backup_file(path: Path, backup_root: Path, *, label: str) -> Path | None:
    path = Path(path)
    if not path.is_file():
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    root = Path(backup_root) / label / ts
    root.mkdir(parents=True, exist_ok=True)
    dst = root / path.name
    n = 1
    while dst.exists():
        dst = root / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.copy2(path, dst)
    return dst


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    if newline is not None:
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    atomic_write_bytes(path, text.encode(encoding))


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(Path(path), json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
