"""Read-only NPC/Monster in-game names from an Etervale World Catalog SQLite DB.

The native model directory is *not* an NPC identity. Many NPC definitions may
reference the same model, so never collapse them or silently choose one name.
No source-content JSON, Summit, or production DB writes are used.
"""
from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
from urllib.parse import quote
from typing import Any

CONFIG_FORMAT = "PT_ETERVALE_ENTITY_NAME_DB_V1"
REQUIRED = {"npcs": {"id", "model", "key"}, "npc_texts": {"npc_id", "language", "name"},
            "monsters": {"id", "model", "key"}, "monster_texts": {"monster_id", "language", "name"}}


def config_path(project_root: Path) -> Path:
    return Path(project_root) / "pt_build" / "state" / "etervale_entity_names_db.json"


def configured_path(project_root: Path) -> Path | None:
    try:
        data = json.loads(config_path(project_root).read_text(encoding="utf-8"))
        if data.get("format") == CONFIG_FORMAT and isinstance(data.get("sqlite_path"), str) and data["sqlite_path"]:
            return Path(data["sqlite_path"]).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        pass
    return None


def _connection(path: Path) -> sqlite3.Connection:
    # Explicit read-only open. Never create a missing DB or run a migration.
    db = sqlite3.connect("file:" + quote(str(path.resolve()), safe="/") + "?mode=ro", uri=True, timeout=1)
    db.execute("PRAGMA query_only=ON")
    return db


def _has_world_catalog(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return False
    try:
        with closing(_connection(path)) as db:
            for table, columns in REQUIRED.items():
                actual = {str(x[1]).lower() for x in db.execute(f'PRAGMA table_info("{table}")')}
                if not columns.issubset(actual):
                    return False
        return True
    except (OSError, sqlite3.Error):
        return False


def discover_candidates(server_root: Path | None) -> list[Path]:
    if server_root is None:
        return []
    server_root = Path(server_root).resolve()
    game_root = server_root.parent.parent if server_root.name.casefold() == "gameserver" else server_root.parent
    folders = (server_root, server_root / "Database", server_root / "database", game_root,
               game_root / "Database", game_root / "database", game_root / "data")
    found: set[Path] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for extension in ("*.sqlite", "*.sqlite3", "*.db"):
            for path in sorted(folder.glob(extension)):
                resolved = path.resolve()
                if resolved not in found and _has_world_catalog(resolved):
                    found.add(resolved)
    return sorted(found, key=lambda p: str(p).casefold())


def discover_path(server_root: Path | None) -> Path | None:
    candidates = discover_candidates(server_root)
    return candidates[0] if len(candidates) == 1 else None


def source_status(project_root: Path, server_root: Path | None = None) -> dict[str, Any]:
    explicit = configured_path(project_root)
    candidates = [] if explicit else discover_candidates(server_root)
    selected = explicit if explicit else candidates[0] if len(candidates) == 1 else None
    valid = bool(selected and _has_world_catalog(selected))
    return {
        "format": CONFIG_FORMAT,
        "status": "READY_READ_ONLY_SQLITE" if valid else (
            "INVALID_SQLITE_SCHEMA_OR_PATH" if explicit else
            "AMBIGUOUS_WORLD_SQLITE_SELECT_EXPLICIT" if len(candidates) > 1 else "NOT_CONFIGURED"),
        "path": str(selected) if selected else "",
        "source": "EXPLICIT_SQLITE" if explicit else ("AUTO_DISCOVERED_SQLITE" if selected else "NONE"),
        "candidate_count": len(candidates),
        "candidates": [str(p) for p in candidates[:8]],
        "readonly": True, "game_assets_modified": False,
        "note": "Names come from existing World Catalog tables; model directories may represent several NPCs. PostgreSQL is not supported by this UI reader.",
    }


def save_path(project_root: Path, raw_path: str) -> dict[str, Any]:
    raw_path = str(raw_path or "").strip()
    if raw_path:
        path = Path(raw_path).expanduser().resolve()
        if not _has_world_catalog(path):
            raise ValueError("ETERVALE_WORLD_SQLITE_SCHEMA_OR_PATH_INVALID")
    else:
        path = None
    config = config_path(project_root)
    config.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": CONFIG_FORMAT, "sqlite_path": str(path) if path else ""}
    fd, name = tempfile.mkstemp(prefix=".entity-names-", dir=str(config.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, config)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return source_status(project_root)


def _folder_token(model: str, group: str) -> str:
    path = str(model or "").replace("\\", "/").strip().strip("/")
    parts = PurePosixPath(path).parts
    kind = "npc" if group == "NPC" else "monster"
    for i, part in enumerate(parts[:-1]):
        if part.casefold() == kind:
            return parts[i + 1].casefold()
    if not parts:
        return ""
    # Some imported model values are bare directory codes; do not take a
    # stem from an arbitrary deep path without the corresponding group token.
    if len(parts) == 1:
        return PurePosixPath(parts[0]).stem.casefold()
    return ""


def _name_rows(db: sqlite3.Connection, table: str, text_table: str, owner: str) -> list[tuple]:
    return list(db.execute(
        f'SELECT e.model,e.key,t.language,t.name FROM "{table}" e '
        f'LEFT JOIN "{text_table}" t ON t."{owner}"=e.id '
        'ORDER BY e.id,t.language'
    ))


def read_names(path: Path) -> dict[tuple[str, str], list[str]]:
    if not _has_world_catalog(path):
        raise ValueError("ETERVALE_WORLD_SQLITE_SCHEMA_OR_PATH_INVALID")
    chosen: dict[tuple[str, str, str], tuple[int, str]] = {}
    with closing(_connection(path)) as db:
        for group, table, texts, owner in (("NPC", "npcs", "npc_texts", "npc_id"),
                                            ("MONSTER", "monsters", "monster_texts", "monster_id")):
            for model, key, language, name in _name_rows(db, table, texts, owner):
                token = _folder_token(model, group)
                if not token:
                    continue
                label = str(name or "").strip()
                if not label:
                    continue  # Never display an invented key as an in-game name.
                lang = str(language or "").lower()
                priority = 0 if lang == "en" else (1 if lang in ("pt-br", "pt") else 2)
                identity = (group, token, str(key))
                if identity not in chosen or priority < chosen[identity][0]:
                    chosen[identity] = (priority, label)
    grouped: dict[tuple[str, str], set[str]] = {}
    for (group, token, _), (_, label) in chosen.items():
        grouped.setdefault((group, token), set()).add(label)
    return {key: sorted(names, key=str.casefold) for key, names in grouped.items()}


def annotate(entities: list[dict[str, Any]], names: dict[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
    result = []
    for entity in entities:
        group = str(entity.get("semantic_group") or "").upper()
        folder = str(entity.get("folder_root") or "").replace("\\", "/").rstrip("/")
        parts = PurePosixPath(folder).parts
        if group not in {"NPC", "MONSTER"} or len(parts) < 3 or parts[0].casefold() != "char" or parts[1].casefold() != group.casefold():
            result.append(entity)
            continue
        labels = names.get((group, parts[2].casefold()), [])
        if not labels:
            result.append(entity)
            continue
        copy = dict(entity)
        copy["in_game_names"] = labels
        copy["in_game_name_count"] = len(labels)
        copy["in_game_name_source"] = "WORLD_CATALOG_SQLITE_READ_ONLY"
        # Keep code and folder identity stable; a shared model is not a single NPC.
        copy["_search_text"] = " ".join([
            str(entity.get("_search_text") or ""),
            str(entity.get("display_name") or ""),
            str(entity.get("folder_root") or ""),
            " ".join(str(x) for x in (entity.get("role_counts") or {})),
            " ".join(str(x) for x in (entity.get("all_paths") or [])),
            " ".join(labels),
        ]).casefold()
        result.append(copy)
    return result
