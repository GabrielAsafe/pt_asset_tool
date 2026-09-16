from __future__ import annotations

import json
import os
import pathlib
from typing import Any

CONFIG_FILENAME = "pt_asset_app_config.json"
STATE_RELATIVE_DIR = pathlib.Path("pt_build") / "state"


def config_path(project_root: pathlib.Path) -> pathlib.Path:
    """Return the machine-local configuration path.

    Configuration is runtime state and must never be shipped as part of a
    release snapshot.  Keeping it under ``pt_build/state`` also makes a fresh
    checkout deterministic: no developer-specific absolute paths are loaded.
    """
    return project_root.resolve() / STATE_RELATIVE_DIR / CONFIG_FILENAME


def load_config(project_root: pathlib.Path) -> dict[str, Any]:
    path = config_path(project_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: pathlib.Path, data: dict[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def save_client_root(project_root: pathlib.Path, client_root: pathlib.Path) -> pathlib.Path:
    project_root = project_root.resolve()
    client_root = client_root.expanduser().resolve()
    if not client_root.is_dir():
        raise FileNotFoundError(f"CLIENT_ROOT_NOT_FOUND:{client_root}")
    path = config_path(project_root)
    current = load_config(project_root)
    current.update({
        "format": "PT_ASSET_APP_CONFIG_V1",
        "client_root": str(client_root),
    })
    return _atomic_write_json(path, current)


def clear_client_root(project_root: pathlib.Path) -> pathlib.Path:
    path = config_path(project_root)
    current = load_config(project_root)
    if "client_root" in current:
        current.pop("client_root", None)
        current.setdefault("format", "PT_ASSET_APP_CONFIG_V1")
        _atomic_write_json(path, current)
    return path


def candidate_client_roots_with_source(project_root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    project_root = project_root.resolve()
    parent = project_root.parent
    candidates: list[tuple[pathlib.Path, str]] = []

    env = os.environ.get("PT_CLIENT_ROOT")
    if env:
        candidates.append((pathlib.Path(env).expanduser(), "PT_CLIENT_ROOT"))

    cfg = load_config(project_root)
    configured = cfg.get("client_root")
    if isinstance(configured, str) and configured.strip():
        candidates.append((pathlib.Path(configured).expanduser(), "PERSISTENT_CONFIG"))

    # Project-relative layouts (legacy + standalone project folder).
    candidates.extend([
        (project_root.parent / "Summit Tale Client Full" / "cliente", "LEGACY_PARENT_LAYOUT"),
        (project_root / "Summit Tale Client Full" / "cliente", "PROJECT_LAYOUT"),
        (project_root / "client", "PROJECT_CLIENT_DIR"),
        (project_root / "cliente", "PROJECT_CLIENTE_DIR"),
        (parent.parent / "client", "WORKSPACE_CLIENT_DIR"),
        (parent.parent / "cliente", "WORKSPACE_CLIENTE_DIR"),
        (parent / "summit" / "Summit Tale Client Full" / "cliente", "SIBLING_SUMMIT_LAYOUT"),
    ])

    # Shallow sibling discovery keeps the tool relocatable without scanning the disk.
    try:
        for sibling in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            if sibling.is_dir():
                candidates.append((sibling / "Summit Tale Client Full" / "cliente", f"SIBLING_DISCOVERY:{sibling.name}"))
    except OSError:
        pass

    out: list[tuple[pathlib.Path, str]] = []
    seen: set[str] = set()
    for p, source in candidates:
        try:
            rp = p.resolve()
        except OSError:
            rp = p.absolute()
        key = str(rp)
        if key not in seen:
            seen.add(key)
            out.append((rp, source))
    return out


def candidate_client_roots(project_root: pathlib.Path) -> list[pathlib.Path]:
    return [p for p, _ in candidate_client_roots_with_source(project_root)]


def resolve_client_root(project_root: pathlib.Path) -> tuple[pathlib.Path, str]:
    for p, source in candidate_client_roots_with_source(project_root):
        if p.is_dir():
            return p, source
    raise FileNotFoundError(
        "CLIENT_ROOT_NOT_FOUND; run `python3 pt_asset.py config set-client-root PATH`, "
        "use --client-root, or set PT_CLIENT_ROOT"
    )


def discover_client_root(project_root: pathlib.Path) -> pathlib.Path:
    return resolve_client_root(project_root)[0]


def save_server_root(project_root: pathlib.Path, server_root: pathlib.Path) -> pathlib.Path:
    project_root = project_root.resolve()
    server_root = server_root.expanduser().resolve()
    if not server_root.is_dir():
        raise FileNotFoundError(f"SERVER_ROOT_NOT_FOUND:{server_root}")
    path = config_path(project_root)
    current = load_config(project_root)
    current.update({
        "format": "PT_ASSET_APP_CONFIG_V1",
        "server_root": str(server_root),
    })
    return _atomic_write_json(path, current)


def clear_server_root(project_root: pathlib.Path) -> pathlib.Path:
    path = config_path(project_root)
    current = load_config(project_root)
    if "server_root" in current:
        current.pop("server_root", None)
        current.setdefault("format", "PT_ASSET_APP_CONFIG_V1")
        _atomic_write_json(path, current)
    return path


def candidate_server_roots_with_source(project_root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    project_root = project_root.resolve()
    parent = project_root.parent
    candidates: list[tuple[pathlib.Path, str]] = []

    env = os.environ.get("PT_SERVER_ROOT")
    if env:
        candidates.append((pathlib.Path(env).expanduser(), "PT_SERVER_ROOT"))

    cfg = load_config(project_root)
    configured = cfg.get("server_root")
    if isinstance(configured, str) and configured.strip():
        candidates.append((pathlib.Path(configured).expanduser(), "PERSISTENT_CONFIG"))

    candidates.extend([
        (project_root / "Servidor", "PROJECT_SERVIDOR_DIR"),
        (parent / "Servidor", "PARENT_SERVIDOR_DIR"),
        (parent.parent / "Servidor", "WORKSPACE_SERVIDOR_DIR"),
        (parent / "summit" / "Servidor", "SIBLING_SUMMIT_LAYOUT"),
    ])

    try:
        for sibling in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            if sibling.is_dir():
                candidates.append((sibling / "Servidor", f"SIBLING_DISCOVERY:{sibling.name}"))
    except OSError:
        pass

    out: list[tuple[pathlib.Path, str]] = []
    seen: set[str] = set()
    for candidate, source in candidates:
        try:
            rp = candidate.resolve()
        except OSError:
            rp = candidate.absolute()
        key = str(rp)
        if key not in seen:
            seen.add(key)
            out.append((rp, source))
    return out


def resolve_server_root(project_root: pathlib.Path) -> tuple[pathlib.Path, str]:
    for p, source in candidate_server_roots_with_source(project_root):
        if p.is_dir():
            return p, source
    raise FileNotFoundError(
        "SERVER_ROOT_NOT_FOUND; run `python3 pt_asset.py config set-server-root PATH`, "
        "use --server-root, or set PT_SERVER_ROOT"
    )


def discover_server_root(project_root: pathlib.Path) -> pathlib.Path:
    return resolve_server_root(project_root)[0]


def _save_readonly_root(project_root: pathlib.Path, key: str, value: pathlib.Path) -> pathlib.Path:
    project_root = project_root.resolve()
    value = value.expanduser().resolve()
    if not value.is_dir():
        raise FileNotFoundError(f"{key.upper()}_NOT_FOUND:{value}")
    path = config_path(project_root)
    current = load_config(project_root)
    current.update({
        "format": "PT_ASSET_APP_CONFIG_V1",
        key: str(value),
    })
    return _atomic_write_json(path, current)


def _clear_readonly_root(project_root: pathlib.Path, key: str) -> pathlib.Path:
    path = config_path(project_root)
    current = load_config(project_root)
    if key in current:
        current.pop(key, None)
        current.setdefault("format", "PT_ASSET_APP_CONFIG_V1")
        _atomic_write_json(path, current)
    return path


def save_source_root(project_root: pathlib.Path, source_root: pathlib.Path) -> pathlib.Path:
    """Persist the current Summit C/C++ source root used only as read-only evidence."""
    return _save_readonly_root(project_root, "source_root", source_root)


def clear_source_root(project_root: pathlib.Path) -> pathlib.Path:
    return _clear_readonly_root(project_root, "source_root")


def save_reference_source_root(project_root: pathlib.Path, source_root: pathlib.Path) -> pathlib.Path:
    """Persist the EU/reference C/C++ source root used only as read-only evidence."""
    return _save_readonly_root(project_root, "reference_source_root", source_root)


def clear_reference_source_root(project_root: pathlib.Path) -> pathlib.Path:
    return _clear_readonly_root(project_root, "reference_source_root")


def configured_contract_donor_clients(project_root: pathlib.Path) -> list[str]:
    """Return explicitly persisted read-only donor roots as LABEL=PATH strings.

    Fresh installations intentionally have no implicit donor roots.  A donor is
    external evidence and must be selected by the user or supplied on the CLI.
    """
    cfg = load_config(project_root)
    raw = cfg.get("contract_donor_clients")
    out: list[str] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            path = str(row.get("path") or "").strip()
            if label and path:
                out.append(f"{label}={path}")
    return out

def save_contract_donor_clients(project_root: pathlib.Path, donors: list[str]) -> pathlib.Path:
    """Persist validated read-only donor roots. Input is a list of LABEL=PATH strings."""
    project_root = project_root.resolve()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in donors:
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"DONOR_ROOT_FORMAT_INVALID:{text}")
        label, path_text = text.split("=", 1)
        label = label.strip().upper()
        if not label or any(not (c.isalnum() or c in "_-") for c in label):
            raise ValueError(f"DONOR_LABEL_INVALID:{label}")
        path = pathlib.Path(path_text.strip()).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"DONOR_ROOT_NOT_FOUND:{label}:{path}")
        if label in seen:
            raise ValueError(f"DONOR_LABEL_DUPLICATE:{label}")
        seen.add(label)
        rows.append({"label": label, "path": str(path)})
    cfg_path = config_path(project_root)
    current = load_config(project_root)
    current["format"] = "PT_ASSET_APP_CONFIG_V1"
    current["contract_donor_clients"] = rows
    return _atomic_write_json(cfg_path, current)


def configured_contract_donor_servers(project_root: pathlib.Path) -> list[str]:
    """Return explicitly persisted read-only donor server roots.

    No developer-specific server paths are guessed on a fresh installation.
    """
    cfg = load_config(project_root)
    raw = cfg.get("contract_donor_servers")
    out: list[str] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            path = str(row.get("path") or "").strip()
            if label and path:
                out.append(f"{label}={path}")
    return out

def save_contract_donor_servers(project_root: pathlib.Path, donors: list[str]) -> pathlib.Path:
    """Persist validated read-only donor server roots. Input is LABEL=PATH."""
    project_root = project_root.resolve()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in donors:
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"DONOR_SERVER_ROOT_FORMAT_INVALID:{text}")
        label, path_text = text.split("=", 1)
        label = label.strip().upper()
        if not label or any(not (c.isalnum() or c in "_-") for c in label):
            raise ValueError(f"DONOR_SERVER_LABEL_INVALID:{label}")
        path = pathlib.Path(path_text.strip()).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"DONOR_SERVER_ROOT_NOT_FOUND:{label}:{path}")
        if label in seen:
            raise ValueError(f"DONOR_SERVER_LABEL_DUPLICATE:{label}")
        seen.add(label)
        rows.append({"label": label, "path": str(path)})
    cfg_path = config_path(project_root)
    current = load_config(project_root)
    current["format"] = "PT_ASSET_APP_CONFIG_V1"
    current["contract_donor_servers"] = rows
    return _atomic_write_json(cfg_path, current)
