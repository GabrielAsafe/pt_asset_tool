from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
from typing import Any, Iterable

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




def configured_blender_executable(project_root: pathlib.Path) -> str | None:
    """Return the machine-local Blender executable override, if configured."""
    cfg = load_config(project_root.resolve())
    for key in ("blender_executable", "blender_path"):
        value = cfg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def save_blender_executable(project_root: pathlib.Path, executable: pathlib.Path | str) -> pathlib.Path:
    """Persist one explicit Blender executable without machine-specific defaults."""
    project_root = project_root.resolve()
    raw = str(executable).strip()
    if not raw:
        raise ValueError("BLENDER_EXECUTABLE_EMPTY")
    candidate = pathlib.Path(raw).expanduser()
    if not candidate.is_file():
        raise FileNotFoundError(f"BLENDER_EXECUTABLE_NOT_FOUND:{candidate}")
    resolved = candidate.resolve()
    if not os.access(resolved, os.X_OK):
        raise PermissionError(f"BLENDER_EXECUTABLE_NOT_EXECUTABLE:{resolved}")
    path = config_path(project_root)
    current = load_config(project_root)
    current.update({"format": "PT_ASSET_APP_CONFIG_V1", "blender_executable": str(resolved)})
    current.pop("blender_path", None)
    return _atomic_write_json(path, current)


def clear_blender_executable(project_root: pathlib.Path) -> pathlib.Path:
    project_root = project_root.resolve()
    path = config_path(project_root)
    current = load_config(project_root)
    changed = False
    for key in ("blender_executable", "blender_path"):
        if key in current:
            current.pop(key, None)
            changed = True
    if changed:
        current.setdefault("format", "PT_ASSET_APP_CONFIG_V1")
        _atomic_write_json(path, current)
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


_DONOR_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DonorSpecValidationError(ValueError):
    """Validation error with line-level donor diagnostics for CLI/GUI callers."""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = list(issues)
        first = self.issues[0] if self.issues else {}
        super().__init__(str(first.get("message") or "Invalid donor specification"))


def _unwrap_donor_cli_form(text: str, side: str) -> tuple[str | None, str | None]:
    """Normalize one donor line.

    Accepted forms deliberately match what operators are likely to paste:
      LABEL=/path/with spaces
      'LABEL=/path/with spaces'
      --donor-client 'LABEL=/path/with spaces'
      --donor-server LABEL=/path
    """
    raw = str(text or "").strip()
    if not raw or raw.startswith("#"):
        return None, None
    expected_flag = "--donor-client" if side == "client" else "--donor-server"
    if raw.startswith("--donor-"):
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            return None, f"Aspas inválidas: {exc}."
        if len(parts) != 2 or parts[0] != expected_flag:
            return None, f"Use {expected_flag} 'LABEL=/caminho' ou apenas LABEL=/caminho."
        return parts[1].strip(), None
    # Accept a quoted bare spec as copied from shell commands.
    if raw[:1] in {"'", '"'}:
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            return None, f"Aspas inválidas: {exc}."
        if len(parts) != 1:
            return None, "A linha deve conter um único donor LABEL=/caminho."
        raw = parts[0]
    return raw, None


def validate_contract_donor_specs(
    donors: Iterable[str],
    side: str,
    *,
    require_existing: bool = True,
) -> dict[str, Any]:
    """Validate/normalize donor specs without persisting anything.

    Returns line-level issues suitable for the GUI and normalized LABEL=PATH
    strings suitable for CLI arguments and persistent config.
    """
    side = str(side or "").strip().lower()
    if side not in {"client", "server"}:
        raise ValueError(f"DONOR_SIDE_INVALID:{side}")
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for line_no, raw_value in enumerate(list(donors), 1):
        raw = str(raw_value or "")
        text, unwrap_error = _unwrap_donor_cli_form(raw, side)
        if text is None and unwrap_error is None:
            continue
        base = {"side": side, "line": line_no, "input": raw}
        if unwrap_error:
            issues.append({**base, "code": "DONOR_CLI_FORM_INVALID", "message": unwrap_error})
            continue
        assert text is not None
        if "=" not in text:
            issues.append({
                **base,
                "code": "DONOR_ROOT_FORMAT_INVALID",
                "message": "Falta '=' entre o label e o caminho.",
                "expected": "LABEL=/caminho/para/donor",
            })
            continue
        label_text, path_text = text.split("=", 1)
        label = label_text.strip().upper()
        path_raw = path_text.strip()
        if not label:
            issues.append({**base, "code": "DONOR_LABEL_EMPTY", "message": "O label antes de '=' está vazio."})
            continue
        if not _DONOR_LABEL_RE.fullmatch(label):
            issues.append({
                **base,
                "code": "DONOR_LABEL_INVALID",
                "message": "Label inválido. Use apenas letras, números, '_' ou '-'.",
                "label": label,
            })
            continue
        if not path_raw:
            issues.append({**base, "code": "DONOR_PATH_EMPTY", "message": "O caminho depois de '=' está vazio.", "label": label})
            continue
        if label in seen:
            issues.append({
                **base,
                "code": "DONOR_LABEL_DUPLICATE",
                "message": f"Label {label} já foi usado na linha {seen[label]}.",
                "label": label,
            })
            continue
        seen[label] = line_no
        try:
            path = pathlib.Path(path_raw).expanduser().resolve()
        except Exception as exc:
            issues.append({**base, "code": "DONOR_PATH_INVALID", "message": f"Caminho inválido: {exc}", "label": label, "path": path_raw})
            continue
        exists = path.is_dir()
        row = {
            **base,
            "label": label,
            "path": str(path),
            "exists": exists,
            "normalized": f"{label}={path}",
        }
        rows.append(row)
        if require_existing and not exists:
            issues.append({
                **base,
                "code": "DONOR_ROOT_NOT_FOUND",
                "message": f"O diretório não existe ou não é uma pasta: {path}",
                "label": label,
                "path": str(path),
            })
            continue
        normalized.append(f"{label}={path}")
    return {
        "ok": not issues,
        "side": side.upper(),
        "rows": rows,
        "issues": issues,
        "normalized": normalized,
        "accepted_formats": [
            "LABEL=/caminho/para/donor",
            f"{'--donor-client' if side == 'client' else '--donor-server'} 'LABEL=/caminho/para/donor'",
        ],
    }


def save_contract_source_config(
    project_root: pathlib.Path,
    source_root: pathlib.Path | None,
    reference_source_root: pathlib.Path | None,
    donor_clients: Iterable[str],
    donor_servers: Iterable[str],
) -> dict[str, Any]:
    """Validate and persist the complete Source Evidence configuration atomically.

    This intentionally performs one atomic JSON replacement so a valid request
    cannot leave roots and donor lists from different saves.
    """
    source_root = source_root.expanduser().resolve() if source_root is not None else None
    reference_source_root = reference_source_root.expanduser().resolve() if reference_source_root is not None else None
    issues: list[dict[str, Any]] = []
    if source_root is not None and not source_root.is_dir():
        issues.append({"field": "source_root", "code": "SOURCE_ROOT_NOT_DIRECTORY", "message": f"Source Summit não existe ou não é uma pasta: {source_root}"})
    if reference_source_root is not None and not reference_source_root.is_dir():
        issues.append({"field": "reference_source_root", "code": "REFERENCE_SOURCE_ROOT_NOT_DIRECTORY", "message": f"Source EU de referência não existe ou não é uma pasta: {reference_source_root}"})
    client_validation = validate_contract_donor_specs(donor_clients, "client", require_existing=True)
    server_validation = validate_contract_donor_specs(donor_servers, "server", require_existing=True)
    issues.extend(client_validation["issues"])
    issues.extend(server_validation["issues"])
    if issues:
        raise DonorSpecValidationError(issues)

    current = load_config(project_root)
    current["format"] = "PT_ASSET_APP_CONFIG_V1"
    if source_root is None:
        current.pop("source_root", None)
    else:
        current["source_root"] = str(source_root)
    if reference_source_root is None:
        current.pop("reference_source_root", None)
    else:
        current["reference_source_root"] = str(reference_source_root)

    def rows(specs: list[str]) -> list[dict[str, str]]:
        out = []
        for spec in specs:
            label, path = spec.split("=", 1)
            out.append({"label": label, "path": path})
        return out

    current["contract_donor_clients"] = rows(client_validation["normalized"])
    current["contract_donor_servers"] = rows(server_validation["normalized"])
    path = _atomic_write_json(config_path(project_root.resolve()), current)
    return {
        "path": path,
        "source_root": str(source_root) if source_root is not None else None,
        "reference_source_root": str(reference_source_root) if reference_source_root is not None else None,
        "donor_clients": list(client_validation["normalized"]),
        "donor_servers": list(server_validation["normalized"]),
        "client_validation": client_validation,
        "server_validation": server_validation,
    }


def _configured_contract_donors(project_root: pathlib.Path, key: str) -> list[str]:
    cfg = load_config(project_root)
    raw = cfg.get(key)
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


def configured_contract_donor_clients(project_root: pathlib.Path) -> list[str]:
    """Return explicitly persisted read-only donor roots as LABEL=PATH strings."""
    return _configured_contract_donors(project_root, "contract_donor_clients")


def configured_contract_donor_servers(project_root: pathlib.Path) -> list[str]:
    """Return explicitly persisted read-only donor server roots."""
    return _configured_contract_donors(project_root, "contract_donor_servers")


def _save_contract_donors(project_root: pathlib.Path, key: str, donors: Iterable[str], side: str) -> pathlib.Path:
    validation = validate_contract_donor_specs(donors, side, require_existing=True)
    if validation["issues"]:
        raise DonorSpecValidationError(validation["issues"])
    rows = []
    for spec in validation["normalized"]:
        label, path = spec.split("=", 1)
        rows.append({"label": label, "path": path})
    cfg_path = config_path(project_root.resolve())
    current = load_config(project_root)
    current["format"] = "PT_ASSET_APP_CONFIG_V1"
    current[key] = rows
    return _atomic_write_json(cfg_path, current)


def save_contract_donor_clients(project_root: pathlib.Path, donors: list[str]) -> pathlib.Path:
    """Persist validated read-only client donors; accepts bare or CLI-form specs."""
    return _save_contract_donors(project_root, "contract_donor_clients", donors, "client")


def save_contract_donor_servers(project_root: pathlib.Path, donors: list[str]) -> pathlib.Path:
    """Persist validated read-only server donors; accepts bare or CLI-form specs."""
    return _save_contract_donors(project_root, "contract_donor_servers", donors, "server")

