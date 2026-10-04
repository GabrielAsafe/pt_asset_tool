from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from .legacy_name_catalog import load_name_catalog
from .source_catalog import configured_source_roots
from .contract_graph import ContractGraph

CANONICAL_SOURCE_SCHEMA = "summit.canonical-source/v1"
BUILD_SCHEMA = "summit.canonical-content-build/v1"
CATALOG_FORMAT = "PT_ASSET_SEMANTIC_CATALOG_V2"
CANONICAL_PROVIDER_FORMAT = "PT_ASSET_SUMMIT_CANONICAL_PROVIDER_V1"

PACK_FILENAMES = (
    "text_resources.sres",
    "definitions_client.scfg",
    "definitions_server.scfg",
    "localization.sloc",
    "gameplay_config.sgcf",
    "gameplay_reference.sgrf",
    "field_runtime.sfld",
    "maps_client.smap",
    "maps_server.smap",
    "coin_shop.scsp",
)

DEFINITION_FAMILIES = {"open_item_definition", "monster_definition", "npc_definition"}
TEXT_RESOURCE_FAMILIES = {"generic_text", "ini_config", "localization_resource", "message_catalog", "monster_definition", "npc_definition", "open_item_definition", "sin_resource"}
CANONICAL_FINGERPRINT_FAMILIES = ("text", "stage_spawns", "stage_start_points", "fixed_npcs", "maps", "item_profiles", "gameplay_reference", "commerce", "model_configs", "equipment_sets", "head_cosmetics", "world_story", "world_phases", "covenant_altars", "gameplay_balance")


EXTENDED_CANONICAL_DOMAINS = (
    {"id": "coin_shop", "kind": "COIN_SHOP_CATALOG", "path": "canonical/commerce/coin_shop.json", "runtime": "COMPILED", "description": "Premium Coin/Time static catalog; wallet state remains DB-backed."},
    {"id": "npc_shop_overrides", "kind": "NPC_SHOP_OVERRIDES", "path": "canonical/commerce/npc_shop_overrides.json", "runtime": "DEFINITION_COMPILE_INPUT", "description": "Semantic suppress/add overlay for NPC vendor inventories."},
    {"id": "model_configs", "kind": "MODEL_CONFIG", "path": "canonical/model_configs/models", "runtime": "AUTHORING_SOURCE", "description": "Structured model-config authority; legacy INX remains derived/cache compatibility."},
    {"id": "equipment_sets", "kind": "EQUIPMENT_SETS", "path": "canonical/equipment_sets/equipment_sets.json", "runtime": "SERVICE_INPUT", "description": "Server-authoritative equipment set definitions."},
    {"id": "head_cosmetics", "kind": "HEAD_COSMETICS", "path": "canonical/head_cosmetics/head_cosmetics.json", "runtime": "MILESTONE_PENDING", "description": "Head/mask cosmetic definitions and asset references."},
    {"id": "world_story", "kind": "WORLD_STORY", "path": "canonical/world_story/campaigns.json", "runtime": "MILESTONE_PENDING", "description": "Collective/global story campaigns and phase objectives."},
    {"id": "world_phases", "kind": "WORLD_PHASES", "path": "canonical/world_phases/world_phases.json", "runtime": "MILESTONE_PENDING", "description": "World phase -> map/spawn/NPC/gate reconciliation definitions."},
    {"id": "covenant_altars", "kind": "COVENANT_ALTARS", "path": "canonical/covenant_altars/placement_plan.json", "runtime": "MILESTONE_PENDING", "description": "Covenant altar placements and interaction authoring."},
    {"id": "experience_balance", "kind": "EXPERIENCE_BALANCE", "path": "canonical/gameplay_balance/experience.json", "runtime": "MILESTONE_PENDING", "description": "Canonical experience/party progression tuning."},
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _safe_rel(root: pathlib.Path, path: pathlib.Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _nested_values(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for v in value.values():
            yield v
            yield from _nested_values(v)
    elif isinstance(value, list):
        for v in value:
            yield v
            yield from _nested_values(v)


def _resource_family(doc: dict[str, Any]) -> str:
    candidates = [
        doc.get("family"),
        doc.get("resource_family"),
        doc.get("kind"),
        doc.get("type"),
        (doc.get("semantic") or {}).get("family") if isinstance(doc.get("semantic"), dict) else None,
        doc.get("schema"),
    ]
    aliases = {
        "openitemdefinition": "open_item_definition",
        "openitem": "open_item_definition",
        "itemdefinition": "open_item_definition",
        "monsterdefinition": "monster_definition",
        "npcdefinition": "npc_definition",
        "localizationresource": "localization_resource",
        "messagecatalog": "message_catalog",
        "iniconfig": "ini_config",
        "generictext": "generic_text",
        "sinresource": "sin_resource",
    }
    for raw in candidates:
        if raw is None:
            continue
        text = str(raw).strip().casefold()
        if text in DEFINITION_FAMILIES or text in {
            "localization_resource", "message_catalog", "ini_config", "generic_text", "sin_resource"
        }:
            return text
        nk = _norm_key(text)
        if nk in aliases:
            return aliases[nk]
        for alias_key, value in aliases.items():
            if alias_key in nk:
                return value
    return "unknown"


def _semantic(doc: dict[str, Any]) -> dict[str, Any]:
    value = doc.get("semantic")
    return value if isinstance(value, dict) else {}


def _fields(doc: dict[str, Any]) -> dict[str, Any]:
    value = _semantic(doc).get("fields")
    return value if isinstance(value, dict) else {}


def _lookup_field(doc: dict[str, Any], *names: str) -> Any:
    fields = _fields(doc)
    by_norm = {_norm_key(k): v for k, v in fields.items()}
    for name in names:
        n = _norm_key(name)
        if n in by_norm:
            return by_norm[n]
    for name in names:
        for mapping in (doc, _semantic(doc)):
            if name in mapping:
                return mapping.get(name)
            by_norm2 = {_norm_key(k): v for k, v in mapping.items()}
            n = _norm_key(name)
            if n in by_norm2:
                return by_norm2[n]
    return None


def _first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return _first_scalar(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("value", "text", "name", "code", "id"):
            if key in value:
                return _first_scalar(value[key])
        return None
    return value


def canonical_id_for_doc(doc: dict[str, Any], family: str | None = None) -> str:
    family = family or _resource_family(doc)
    semantic = _semantic(doc)
    names = ["canonical_id", "resource_id", "id"]
    if family == "open_item_definition":
        names = ["canonical_id", "item_id", *names]
    elif family == "monster_definition":
        names = ["canonical_id", "monster_id", *names]
    elif family == "npc_definition":
        names = ["canonical_id", "npc_id", *names]
    for mapping in (doc, semantic):
        normalized = {_norm_key(k): v for k, v in mapping.items()}
        for name in names:
            if _norm_key(name) in normalized:
                value = _first_scalar(normalized[_norm_key(name)])
                if value not in (None, ""):
                    return str(value).strip()
    return ""


def _code_for_doc(doc: dict[str, Any]) -> str:
    value = _first_scalar(_lookup_field(doc, "code", "item_code", "runtime_code"))
    return str(value or "").strip()


def _canonical_name(doc: dict[str, Any]) -> str:
    value = _first_scalar(_lookup_field(doc, "name", "display_name", "title"))
    return str(value or "").strip()


def _pathish(doc: dict[str, Any], *keys: str) -> str | None:
    for mapping in (doc, _semantic(doc), doc.get("source") if isinstance(doc.get("source"), dict) else {}):
        normalized = {_norm_key(k): v for k, v in mapping.items()}
        for key in keys:
            value = normalized.get(_norm_key(key))
            if isinstance(value, str) and value.strip():
                return value.replace("\\", "/").strip()
    return None


def _extract_profile_membership(doc: Any) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    codes: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                nk = _norm_key(k)
                if nk in {"canonicalid", "itemid", "resourceid"} and isinstance(v, (str, int)):
                    ids.add(str(v).strip().casefold())
                elif nk in {"code", "itemcode", "runtimecode"} and isinstance(v, (str, int)):
                    codes.add(str(v).strip().upper())
                else:
                    walk(v, nk)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str):
            if key in {"codes", "itemcodes"}:
                codes.add(value.strip().upper())
            elif key in {"canonicalids", "itemids"}:
                ids.add(value.strip().casefold())

    walk(doc)
    return ids, codes


def _dir_fingerprint(root: pathlib.Path) -> dict[str, Any]:
    files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix().casefold()) if root.is_dir() else []
    h = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
        rows.append({"path": rel, "sha256": digest, "bytes": path.stat().st_size})
    return {"sha256": h.hexdigest(), "files": len(rows), "file_hashes": rows}


def canonical_family_fingerprints_at(canonical_root: pathlib.Path) -> dict[str, dict[str, Any]]:
    root = pathlib.Path(canonical_root)
    out: dict[str, dict[str, Any]] = {}
    for name in CANONICAL_FINGERPRINT_FAMILIES:
        path = root / name
        if path.exists():
            fp = _dir_fingerprint(path)
            out[name] = {"sha256": fp["sha256"], "files": fp["files"]}
    return out


def canonical_file_hash_inventory_at(canonical_root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(canonical_root)
    files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix().casefold()) if root.is_dir() else []
    rows: list[dict[str, Any]] = []
    h = hashlib.sha256()
    total_bytes = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        size = path.stat().st_size
        total_bytes += size
        h.update(rel.encode("utf-8")); h.update(b"\0"); h.update(digest.encode("ascii")); h.update(b"\n")
        rows.append({"path": rel, "sha256": digest, "bytes": size})
    return {"sha256": h.hexdigest(), "files": len(rows), "bytes": total_bytes, "rows": rows}


def _declared_pack_hashes(build: Any) -> dict[str, str]:
    found: dict[str, str] = {}

    def walk(value: Any, context: str = "") -> None:
        if isinstance(value, dict):
            normalized = {_norm_key(k): v for k, v in value.items()}
            sha = normalized.get("sha256") or normalized.get("hash")
            pathish = normalized.get("path") or normalized.get("file") or normalized.get("filename") or normalized.get("name") or context
            if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha.strip()):
                candidate = pathlib.PurePosixPath(str(pathish).replace("\\", "/")).name
                if candidate in PACK_FILENAMES:
                    found[candidate] = sha.strip().lower()
            for k, v in value.items():
                candidate = pathlib.PurePosixPath(str(k).replace("\\", "/")).name
                if candidate in PACK_FILENAMES and isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{64}", v.strip()):
                    found[candidate] = v.strip().lower()
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, context)

    walk(build)
    return found


@dataclass(frozen=True)
class CanonicalDocument:
    path: pathlib.Path
    relative_path: str
    family: str
    canonical_id: str
    sha256: str
    data: dict[str, Any]


class SummitCanonicalContentProvider:
    """Read-only authority adapter for Summit Content/canonical.

    The provider deliberately fails closed if the authority manifests are absent
    or use an unknown schema. Writers live in canonical_authoring.py and consume
    this provider rather than maintaining a parallel catalog snapshot.
    """

    def __init__(self, source_root: pathlib.Path | str):
        self.source_root = pathlib.Path(source_root).expanduser().resolve()
        self.content_root = self.source_root / "Content"
        self.canonical_root = self.content_root / "canonical"
        self.packs_root = self.content_root / "packs"
        self.canonical_source_path = self.content_root / "CANONICAL_SOURCE.json"
        self.build_path = self.content_root / "BUILD.json"
        if not self.source_root.is_dir():
            raise FileNotFoundError(f"SUMMIT_SOURCE_ROOT_NOT_FOUND:{self.source_root}")
        if not self.canonical_source_path.is_file():
            raise FileNotFoundError(f"CANONICAL_SOURCE_MANIFEST_NOT_FOUND:{self.canonical_source_path}")
        if not self.build_path.is_file():
            raise FileNotFoundError(f"CANONICAL_BUILD_MANIFEST_NOT_FOUND:{self.build_path}")
        self.canonical_source = _json(self.canonical_source_path)
        self.build = _json(self.build_path)
        if not isinstance(self.canonical_source, dict):
            raise ValueError("CANONICAL_SOURCE_MANIFEST_NOT_OBJECT")
        if not isinstance(self.build, dict):
            raise ValueError("CANONICAL_BUILD_MANIFEST_NOT_OBJECT")
        source_schema = str(self.canonical_source.get("schema") or "").strip()
        build_schema = str(self.build.get("schema") or "").strip()
        if source_schema != CANONICAL_SOURCE_SCHEMA:
            raise ValueError(f"CANONICAL_SOURCE_SCHEMA_UNSUPPORTED:{source_schema or '[missing]'}")
        if build_schema != BUILD_SCHEMA:
            raise ValueError(f"CANONICAL_BUILD_SCHEMA_UNSUPPORTED:{build_schema or '[missing]'}")
        if not self.canonical_root.is_dir():
            raise FileNotFoundError(f"CANONICAL_ROOT_NOT_FOUND:{self.canonical_root}")

    @classmethod
    def from_project(cls, project_root: pathlib.Path, source_root: pathlib.Path | str | None = None) -> "SummitCanonicalContentProvider":
        if source_root is not None:
            return cls(source_root)
        trees = configured_source_roots(pathlib.Path(project_root), source_root=source_root)
        current = next((x for x in trees if x.source_id == "CURRENT_SOURCE"), None)
        if current is None:
            raise FileNotFoundError("CURRENT_SOURCE_ROOT_NOT_CONFIGURED")
        return cls(current.root)

    @classmethod
    def try_from_project(cls, project_root: pathlib.Path, source_root: pathlib.Path | str | None = None) -> "SummitCanonicalContentProvider | None":
        # Absence of a canonical manifest means legacy mode.  Once the manifest is
        # present, however, malformed/unknown canonical metadata is an explicit
        # fail-closed condition: callers must not silently fall back to a legacy
        # authoritative writer.
        if source_root is not None:
            root = pathlib.Path(source_root).expanduser().resolve()
        else:
            trees = configured_source_roots(pathlib.Path(project_root))
            current = next((x for x in trees if x.source_id == "CURRENT_SOURCE"), None)
            if current is None:
                return None
            root = current.root
        if not (root / "Content" / "CANONICAL_SOURCE.json").is_file():
            return None
        return cls(root)

    @property
    def canonical_mode(self) -> bool:
        return True

    def relative_to_source(self, path: pathlib.Path) -> str:
        return _safe_rel(self.source_root, path)

    def iter_text_documents(self) -> Iterator[CanonicalDocument]:
        root = self.canonical_root / "text"
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*.json"), key=lambda p: p.as_posix().casefold()):
            try:
                data = _json(path)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            family = _resource_family(data)
            yield CanonicalDocument(
                path=path,
                relative_path=_safe_rel(self.content_root, path),
                family=family,
                canonical_id=canonical_id_for_doc(data, family),
                sha256=sha256_file(path),
                data=data,
            )

    def text_documents(self, family: str | None = None) -> list[CanonicalDocument]:
        rows = list(self.iter_text_documents())
        if family is None:
            return rows
        target = str(family).strip().casefold()
        return [x for x in rows if x.family == target]

    def text_resource_documents(self) -> list[CanonicalDocument]:
        return [x for x in self.iter_text_documents() if x.family in TEXT_RESOURCE_FAMILIES]

    def text_metadata_documents(self) -> list[CanonicalDocument]:
        return [x for x in self.iter_text_documents() if x.family not in TEXT_RESOURCE_FAMILIES]

    def gameplay_config_documents(self) -> list[CanonicalDocument]:
        return [
            x for x in self.text_documents("ini_config")
            if str(x.data.get("selection_reason") or "").casefold() == "immutable_gameplay_config"
        ]

    def declared_family_fingerprints(self) -> dict[str, dict[str, Any]]:
        families = self.canonical_source.get("families")
        if not isinstance(families, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for name, row in families.items():
            if not isinstance(row, dict):
                continue
            out[str(name)] = {
                "sha256": row.get("sha256"),
                "files": row.get("files"),
                "bytes": row.get("bytes"),
            }
        return out

    def find_definition(self, canonical_id: str) -> CanonicalDocument:
        target = str(canonical_id or "").strip().casefold()
        if not target:
            raise ValueError("CANONICAL_ID_REQUIRED")
        matches = [x for x in self.iter_text_documents() if x.family in DEFINITION_FAMILIES and x.canonical_id.casefold() == target]
        if not matches:
            raise KeyError(f"CANONICAL_DEFINITION_NOT_FOUND:{canonical_id}")
        if len(matches) != 1:
            raise ValueError(f"CANONICAL_DEFINITION_ID_AMBIGUOUS:{canonical_id}:{len(matches)}")
        return matches[0]

    def item_profiles(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for profile in ("client", "server"):
            path = self.canonical_root / "item_profiles" / f"{profile}.items.json"
            if path.is_file():
                out[profile] = {"path": _safe_rel(self.content_root, path), "sha256": sha256_file(path), "data": _json(path)}
        return out

    def map_profiles(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for profile in ("client", "server"):
            path = self.canonical_root / "maps" / f"{profile}.maps.json"
            if path.is_file():
                out[profile] = {"path": _safe_rel(self.content_root, path), "sha256": sha256_file(path), "data": _json(path)}
        return out

    def extended_domains(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for spec in EXTENDED_CANONICAL_DOMAINS:
            rel = pathlib.PurePosixPath(str(spec["path"]))
            path = self.content_root / pathlib.Path(*rel.parts)
            row = dict(spec)
            row["present"] = path.exists()
            row["is_directory"] = path.is_dir()
            if path.is_file():
                row["sha256"] = sha256_file(path)
                try:
                    doc = _json(path)
                    row["schema"] = doc.get("schema") if isinstance(doc, dict) else None
                    row["entries"] = _extended_domain_entry_count(doc)
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}:{exc}"
            elif path.is_dir():
                docs = sorted(path.rglob("*.json"), key=lambda p: p.as_posix().casefold())
                row["documents"] = len(docs)
                row["entries"] = len(docs)
            rows.append(row)
        return rows

    def canonical_family_fingerprints(self) -> dict[str, dict[str, Any]]:
        # Keep the provider result compact and directly comparable with staged
        # fingerprints used by the two-phase publish drift gates.
        return canonical_family_fingerprints_at(self.canonical_root)

    def pack_freshness(self) -> dict[str, Any]:
        declared = _declared_pack_hashes(self.build)
        rows = []
        stale = []
        for name in PACK_FILENAMES:
            path = self.packs_root / name
            actual = sha256_file(path) if path.is_file() else None
            expected = declared.get(name)
            if not path.is_file():
                state = "MISSING"
            elif expected is None:
                state = "UNDECLARED"
            elif actual == expected:
                state = "FRESH"
            else:
                state = "STALE"
            if state != "FRESH":
                stale.append(name)
            rows.append({"pack": name, "path": _safe_rel(self.source_root, path), "expected_sha256": expected, "actual_sha256": actual, "state": state})
        overall = "FRESH" if rows and all(x["state"] == "FRESH" for x in rows) else ("UNKNOWN" if rows and all(x["state"] == "UNDECLARED" for x in rows) else "STALE")
        return {"status": overall, "packs": rows, "stale_or_unverified": stale, "declared_pack_hashes": declared}

    def localization_publish_gate(self, *, run_validator: bool = False) -> dict[str, Any]:
        validator = self.source_root / "tools" / "content_port" / "validate_legacy_localization_bridge.py"
        if not validator.is_file():
            return {
                "editing": "ENABLED", "preview_validation": "ENABLED", "production_publish": "BLOCKED",
                "reason": "LEGACY_LOCALIZATION_BRIDGE_NOT_PROVEN", "validator": str(validator), "validator_present": False,
            }
        if not run_validator:
            return {
                "editing": "ENABLED", "preview_validation": "ENABLED", "production_publish": "BLOCKED",
                "reason": "LEGACY_LOCALIZATION_BRIDGE_VALIDATOR_NOT_RUN", "validator": str(validator), "validator_present": True,
            }
        proc = subprocess.run(
            [sys.executable, str(validator), "--source-root", str(self.source_root)],
            cwd=self.source_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )
        ok = proc.returncode == 0 and ("RESULT=PASS" in proc.stdout or '"status": "PASS"' in proc.stdout or '"status":"PASS"' in proc.stdout)
        return {
            "editing": "ENABLED", "preview_validation": "ENABLED", "production_publish": "ENABLED" if ok else "BLOCKED",
            "reason": None if ok else "LEGACY_LOCALIZATION_BRIDGE_VALIDATOR_FAIL",
            "validator": str(validator), "validator_present": True, "returncode": proc.returncode, "output": proc.stdout[-12000:],
        }

    def status(self) -> dict[str, Any]:
        families = self.canonical_family_fingerprints()
        declared_families = self.declared_family_fingerprints()
        file_inventory = canonical_file_hash_inventory_at(self.canonical_root)
        text_docs = self.text_resource_documents()
        metadata_docs = self.text_metadata_documents()
        counts: dict[str, int] = {}
        for doc in text_docs:
            counts[doc.family] = counts.get(doc.family, 0) + 1
        gameplay_configs = self.gameplay_config_documents()
        gameplay_entries = sum(len(((x.data.get("semantic") or {}).get("entries") or [])) for x in gameplay_configs)
        return {
            "format": CANONICAL_PROVIDER_FORMAT,
            "status": "PASS",
            "canonical_mode": True,
            "source_root": str(self.source_root),
            "content_root": str(self.content_root),
            "canonical_source_schema": self.canonical_source.get("schema"),
            "build_schema": self.build.get("schema"),
            "canonical_source_sha256": sha256_file(self.canonical_source_path),
            "build_manifest_sha256": sha256_file(self.build_path),
            "family_fingerprints": {k: {"sha256": v["sha256"], "files": v["files"]} for k, v in families.items()},
            "computed_family_fingerprints": {k: {"sha256": v["sha256"], "files": v["files"]} for k, v in families.items()},
            "declared_family_fingerprints": declared_families,
            "canonical_file_inventory": {k: file_inventory[k] for k in ("sha256", "files", "bytes")},
            "canonical_metadata_documents": len(metadata_docs),
            "gameplay_config": {"documents": len(gameplay_configs), "entries": gameplay_entries},
            "definition_counts": {
                "items": counts.get("open_item_definition", 0),
                "monsters": counts.get("monster_definition", 0),
                "npcs": counts.get("npc_definition", 0),
            },
            "text_family_counts": dict(sorted(counts.items())),
            "map_profiles": {k: {"path": v["path"], "sha256": v["sha256"]} for k, v in self.map_profiles().items()},
            "item_profiles": {k: {"path": v["path"], "sha256": v["sha256"]} for k, v in self.item_profiles().items()},
            "extended_domains": self.extended_domains(),
            "build_freshness": self.pack_freshness(),
            "localization": self.localization_publish_gate(run_validator=False),
            "dynamic_field_policy": "APPEND_AFTER_STATIC_CATALOG",
        }


def _extended_domain_entry_count(doc: Any) -> int | None:
    if not isinstance(doc, dict):
        return None
    for key in ("sets", "cosmetics", "campaigns", "worlds", "placements", "altars", "entries"):
        value = doc.get(key)
        if isinstance(value, list):
            return len(value)
    shops = doc.get("shops")
    if isinstance(shops, dict):
        return sum(len(v) for v in shops.values() if isinstance(v, list))
    overrides = doc.get("overrides")
    if isinstance(overrides, list):
        return len(overrides)
    return None


def extended_content_browser(provider: SummitCanonicalContentProvider, *, q: str = "") -> dict[str, Any]:
    needle = str(q or "").strip().casefold()
    rows = provider.extended_domains()
    if needle:
        rows = [row for row in rows if needle in json.dumps(row, ensure_ascii=False).casefold()]
    return {
        "format": "PT_ASSET_CANONICAL_EXTENDED_DOMAINS_V1",
        "authority": "SUMMIT_CANONICAL_SOURCE",
        "rows": rows,
        "total": len(rows),
        "authoring_note": "Use canonical stage with the row kind; MODEL_CONFIG accepts canonical_id or explicit path.",
    }


def canonical_mode_status(project_root: pathlib.Path, source_root: pathlib.Path | str | None = None) -> dict[str, Any]:
    try:
        provider = SummitCanonicalContentProvider.from_project(pathlib.Path(project_root), source_root)
    except FileNotFoundError as exc:
        return {"active": False, "status": "NOT_CONFIGURED", "detail": str(exc)}
    except (ValueError, json.JSONDecodeError) as exc:
        return {"active": False, "status": "INVALID", "detail": str(exc)}
    return {"active": True, "status": "PASS", **provider.status()}


def _overlay_index() -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    data = load_name_catalog()
    by_id: dict[str, dict[str, Any]] = {}
    for key in ("items", "mobs", "npcs", "maps", "spawn_stages"):
        for row in data.get(key) or []:
            cid = str(row.get("canonical_id") or "").strip()
            if cid:
                by_id[cid.casefold()] = row
    ambiguous = set()
    for row in data.get("ambiguous") or []:
        ambiguous.add((str(row.get("category") or "").casefold(), _norm_key(row.get("display_name"))))
    return by_id, ambiguous


def _profile_memberships(provider: SummitCanonicalContentProvider) -> dict[str, tuple[set[str], set[str]]]:
    out: dict[str, tuple[set[str], set[str]]] = {}
    for profile, row in provider.item_profiles().items():
        out[profile] = _extract_profile_membership(row["data"])
    return out


def _definition_row(doc: CanonicalDocument, overlay: dict[str, Any] | None, memberships: dict[str, tuple[set[str], set[str]]]) -> dict[str, Any]:
    data = doc.data
    cid = doc.canonical_id
    code = _code_for_doc(data)
    canonical_name = _canonical_name(data)
    overlay_name = str((overlay or {}).get("display_name") or "").strip()
    display_name = overlay_name or canonical_name
    warning = None
    if not display_name:
        display_name = f"{code or 'UNKNOWN'} — {cid or pathlib.PurePosixPath(doc.relative_path).stem}"
        warning = "MISSING_DISPLAY_NAME"
    category = {"open_item_definition": "ITEM", "monster_definition": "MONSTER", "npc_definition": "NPC"}.get(doc.family, doc.family.upper())
    row = {
        "category": category,
        "family": doc.family,
        "canonical_id": cid,
        "display_name": display_name,
        "canonical_name": canonical_name or None,
        "display_alias": overlay_name or None,
        "display_name_source": "LEGACY_PT_BR_ALIAS_OVERLAY" if overlay_name else ("CANONICAL" if canonical_name else "FALLBACK"),
        "display_warning": warning,
        "code": code or None,
        "logical_path": _pathish(data, "runtime_path", "legacy_path", "linked_file", "source_path"),
        "canonical_path": doc.relative_path,
        "canonical_sha256": doc.sha256,
        "schema": data.get("schema"),
        "source": copy.deepcopy(data.get("source")),
        "compatibility": copy.deepcopy(data.get("compatibility")),
        "unknown_tokens_present": "unknown_tokens" in _semantic(data),
        "visible_name_ambiguous": False,
    }
    if category == "ITEM":
        for profile in ("client", "server"):
            ids, codes = memberships.get(profile, (set(), set()))
            row[f"in_{profile}_profile"] = cid.casefold() in ids or (bool(code) and code.upper() in codes)
    if overlay:
        for key in ("internal_name", "linked_asset", "level", "model_file", "effect_sound", "english_name", "localization_quality", "confidence", "method", "source_url"):
            if key in overlay and row.get(key) in (None, ""):
                row[key] = overlay.get(key)
        row["visible_name_ambiguous"] = bool((overlay or {}).get("visible_name_ambiguous", False))
    row["display"] = f"{display_name} — {code} — {cid}" if code else f"{display_name} — {cid}"
    return row


def _map_rows(provider: SummitCanonicalContentProvider, overlay_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile, entry in provider.map_profiles().items():
        data = entry["data"]
        candidates: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for key in ("maps", "entries", "fields"):
                if isinstance(data.get(key), list):
                    candidates = [x for x in data[key] if isinstance(x, dict)]
                    break
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]
        for map_doc in candidates:
            cid = canonical_id_for_doc(map_doc, "map") or str(map_doc.get("map_id") or "").strip()
            overlay = overlay_by_id.get(cid.casefold()) if cid else None
            canonical_name = str(_first_scalar(_lookup_field(map_doc, "name", "display_name")) or "").strip()
            display_name = str((overlay or {}).get("display_name") or canonical_name or cid or "Unnamed map")
            field_code = _first_scalar(_lookup_field(map_doc, "legacy_field_code", "field_code", "code"))
            dynamic_cfg = data.get("legacy_dynamic_field") if isinstance(data, dict) else None
            dynamic_code = _first_scalar(_lookup_field(dynamic_cfg, "field_code", "dynamic_field_code", "code")) if isinstance(dynamic_cfg, dict) else None
            rows.append({
                "category": "MAP",
                "canonical_id": cid,
                "profile": profile.upper(),
                "display_name": display_name,
                "display_alias": (overlay or {}).get("display_name") if overlay else None,
                "field_code": field_code,
                "dynamic_field_code": dynamic_code,
                "dynamic_reserved_entry": dynamic_code is not None and str(field_code) == str(dynamic_code),
                "canonical_path": entry["path"],
                "canonical_sha256": entry["sha256"],
                "data": copy.deepcopy(map_doc),
                "display": f"{display_name} — {profile.upper()} — field {field_code}",
            })
    return rows


def query_canonical_resources(
    provider: SummitCanonicalContentProvider, *, q: str = "", family: str = "", limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    query = str(q or "").strip().casefold()
    target_family = str(family or "").strip().casefold()
    rows: list[dict[str, Any]] = []
    typed_families = {"open_item_definition", "monster_definition", "npc_definition", "localization_resource", "ini_config"}
    for doc in provider.text_resource_documents():
        if target_family and doc.family != target_family:
            continue
        name = _canonical_name(doc.data)
        hay = " ".join((doc.canonical_id, doc.family, doc.relative_path, name)).casefold()
        if query and query not in hay:
            continue
        writer = None
        if doc.family == "open_item_definition": writer = "ITEM"
        elif doc.family == "monster_definition": writer = "MONSTER"
        elif doc.family == "npc_definition": writer = "NPC"
        elif doc.family == "localization_resource": writer = "LOCALIZATION"
        elif doc.family == "ini_config" and str(doc.data.get("selection_reason") or "").casefold() == "immutable_gameplay_config": writer = "GAMEPLAY_CONFIG"
        rows.append({
            "canonical_id": doc.canonical_id, "family": doc.family, "canonical_path": doc.relative_path,
            "sha256": doc.sha256, "schema": doc.data.get("schema"), "display_name": name or None,
            "authoring_kind": writer, "read_only": doc.family not in typed_families or writer is None,
        })
    total = len(rows)
    lo = max(0, int(offset)); hi = lo + max(1, min(1000, int(limit)))
    return {"status": "PASS", "total": total, "offset": lo, "limit": hi-lo, "rows": rows[lo:hi], "authority": "SUMMIT_CANONICAL_SOURCE"}


def gameplay_config_browser(provider: SummitCanonicalContentProvider, *, q: str = "", limit: int = 100) -> dict[str, Any]:
    query = str(q or "").strip().casefold()
    rows: list[dict[str, Any]] = []
    total_entries = 0
    for doc in provider.gameplay_config_documents():
        entries = ((doc.data.get("semantic") or {}).get("entries") or [])
        entry_count = len(entries) if isinstance(entries, list) else 0
        total_entries += entry_count
        legacy_path = str(((doc.data.get("source") or {}).get("legacy_path") or ""))
        probe = f"{doc.canonical_id} {doc.relative_path} {legacy_path}".casefold()
        if query and query not in probe:
            continue
        rows.append({
            "canonical_id": doc.canonical_id, "canonical_path": doc.relative_path,
            "legacy_path": legacy_path or None, "sha256": doc.sha256,
            "entry_count": entry_count, "authoring_kind": "GAMEPLAY_CONFIG",
            "authority": "CANONICAL_GAMEPLAY_CONFIG",
        })
        if len(rows) >= max(1, min(1000, int(limit))):
            break
    return {
        "status": "PASS", "authority": "SUMMIT_CANONICAL_SOURCE",
        "documents": len(provider.gameplay_config_documents()), "entries": total_entries, "rows": rows,
    }


def localization_browser(
    provider: SummitCanonicalContentProvider, *, locale: str = "pt-BR", q: str = "", limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    loc_root = provider.canonical_root / "text" / "localization"
    report_path = loc_root / "report.json"
    report = _json(report_path) if report_path.is_file() else {}
    locales = (report.get("locales") or {}) if isinstance(report, dict) else {}
    requested = str(locale or "pt-BR").strip()
    available = list(locales) if isinstance(locales, dict) else []
    if available and requested not in available:
        folded = {x.casefold(): x for x in available}
        requested = folded.get(requested.casefold(), requested)
    path = loc_root / f"{requested}.json"
    if not path.is_file():
        raise KeyError(f"CANONICAL_LOCALIZATION_LOCALE_NOT_FOUND:{locale}")
    data = _json(path)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("CANONICAL_LOCALIZATION_ENTRIES_LIST_REQUIRED")
    query = str(q or "").strip().casefold()
    rows = []
    for idx, row in enumerate(entries):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        text = str(row.get("text") or "")
        source = str(row.get("source") or "")
        quality = str(row.get("quality") or "")
        if query and query not in f"{key} {text} {source} {quality}".casefold():
            continue
        rows.append({"index": idx, "key": key, "text": text, "quality": quality or None, "source": source or None})
    total = len(rows)
    lo = max(0, int(offset)); hi = lo + max(1, min(1000, int(limit)))
    return {
        "status": "PASS", "authority": "SUMMIT_CANONICAL_SOURCE", "pack": "localization.sloc",
        "locale": requested, "available_locales": available, "canonical_path": _safe_rel(provider.content_root, path),
        "catalog_sha256": sha256_file(path), "report": report, "publish_gate": provider.localization_publish_gate(run_validator=False),
        "total": total, "offset": lo, "limit": hi-lo, "rows": rows[lo:hi],
    }


def gameplay_reference_browser(provider: SummitCanonicalContentProvider, *, q: str = "", limit: int = 500) -> dict[str, Any]:
    root = provider.canonical_root / "gameplay_reference"
    query = str(q or "").strip().casefold()
    rows: list[dict[str, Any]] = []
    quest_count = 0
    supported_runtime_bindings = 0
    total_runtime_bindings = 0
    mix_recipe_count = 0
    if root.is_dir():
        for path in sorted(root.rglob("*.json"), key=lambda p: p.as_posix().casefold()):
            try:
                data = _json(path)
            except Exception:
                continue
            rel = _safe_rel(provider.content_root, path)
            text = json.dumps(data, ensure_ascii=False, sort_keys=True) if isinstance(data, (dict, list)) else str(data)
            name = path.stem
            probe = (rel + " " + text[:20000]).casefold()
            kind = "REFERENCE"
            if "quest" in probe or "codex" in probe:
                kind = "QUEST_CODEX"
            elif "mix" in probe or "recipe" in probe or "craft" in probe:
                kind = "MIX_GUIDE"

            count = None
            supported = None
            if isinstance(data, dict):
                if kind == "QUEST_CODEX":
                    quest_lists = [
                        value for key, value in data.items()
                        if key != "bindings" and isinstance(value, list) and "quest" in str(key).casefold()
                    ]
                    if quest_lists:
                        count = sum(len(value) for value in quest_lists)
                        quest_count = max(quest_count, count)
                    bindings = data.get("bindings")
                    if isinstance(bindings, list):
                        total_runtime_bindings = max(total_runtime_bindings, len(bindings))
                        supported = sum(1 for row in bindings if isinstance(row, dict) and row.get("supported") is True)
                        supported_runtime_bindings = max(supported_runtime_bindings, supported)
                elif kind == "MIX_GUIDE" and isinstance(data.get("recipes"), list):
                    count = len(data["recipes"])
                    mix_recipe_count = max(mix_recipe_count, count)
                if count is None:
                    for key in ("quests", "recipes", "entries", "items", "records"):
                        if isinstance(data.get(key), list):
                            count = len(data[key]); break

            if query and query not in probe:
                continue
            row = {
                "kind": kind, "name": name, "canonical_path": rel, "sha256": sha256_file(path),
                "schema": data.get("schema") if isinstance(data, dict) else None, "entry_count": count,
                "authority": "REFERENCE_ONLY", "quest_runtime_authority": False,
            }
            if supported is not None:
                row["supported_runtime_bindings"] = supported
                row["runtime_bindings"] = len(data.get("bindings") or [])
            rows.append(row)
            if len(rows) >= max(1, min(2000, int(limit))):
                break
    return {
        "status": "PASS", "authority": "REFERENCE_ONLY", "quest_runtime_authority": False,
        "summary": {
            "quest_codex": {
                "quests": quest_count, "runtime_bindings": total_runtime_bindings,
                "supported_runtime_bindings": supported_runtime_bindings, "authority": "REFERENCE_ONLY",
            },
            "mix_guide": {"recipes": mix_recipe_count, "authority": "REFERENCE_ONLY"},
        },
        "rows": rows, "count": len(rows),
    }


def compare_map_profiles(provider: SummitCanonicalContentProvider, canonical_id: str) -> dict[str, Any]:
    target = str(canonical_id or "").strip().casefold()
    if not target:
        raise ValueError("CANONICAL_MAP_ID_REQUIRED")
    rows = [r for r in _map_rows(provider, {}) if str(r.get("canonical_id") or "").casefold() == target]
    by_profile = {str(r.get("profile") or "").upper(): r for r in rows}
    if not by_profile:
        raise KeyError(f"CANONICAL_MAP_NOT_FOUND:{canonical_id}")
    client = by_profile.get("CLIENT"); server = by_profile.get("SERVER")
    differences: list[dict[str, Any]] = []
    if client and server:
        a = client.get("data") if isinstance(client.get("data"), dict) else {}
        b = server.get("data") if isinstance(server.get("data"), dict) else {}
        for key in sorted(set(a) | set(b), key=str.casefold):
            if a.get(key) != b.get(key):
                differences.append({"field": key, "client": copy.deepcopy(a.get(key)), "server": copy.deepcopy(b.get(key))})
    return {
        "status": "PASS", "canonical_id": canonical_id, "client": client, "server": server,
        "profiles_present": sorted(by_profile), "differences": differences,
        "profiles_must_remain_separate": True,
        "dynamic_field_policy": "APPEND_AFTER_STATIC_CATALOG",
        "dynamic_field_codes": {k: v.get("dynamic_field_code") for k, v in by_profile.items()},
    }


def build_canonical_contract_graph(provider: SummitCanonicalContentProvider, *, include_documents: bool = True) -> dict[str, Any]:
    """Build authority/compile/profile edges for the canonical content pipeline.

    These edges describe source-of-truth and build relationships, not inferred
    runtime requirements.  They are therefore safe to use in audits without
    turning historical/legacy evidence into a second authority.
    """
    g = ContractGraph()
    g.ensure_node("canonical:source", "CANONICAL_SOURCE", "Summit Content/canonical", schema=CANONICAL_SOURCE_SCHEMA)
    g.ensure_node("canonical:build", "BUILD_MANIFEST", "Content/BUILD.json", schema=BUILD_SCHEMA)
    family_to_packs = {
        "text": ["text_resources.sres", "definitions_client.scfg", "definitions_server.scfg", "localization.sloc", "gameplay_config.sgcf"],
        "item_profiles": ["definitions_client.scfg", "definitions_server.scfg"],
        "gameplay_reference": ["gameplay_reference.sgrf"],
        "stage_spawns": ["field_runtime.sfld"],
        "stage_start_points": ["field_runtime.sfld"],
        "fixed_npcs": ["field_runtime.sfld"],
        "commerce": ["coin_shop.scsp", "definitions_client.scfg", "definitions_server.scfg"],
        "maps:client": ["maps_client.smap"],
        "maps:server": ["maps_server.smap"],
    }
    for family in ("text", "item_profiles", "gameplay_reference", "stage_spawns", "stage_start_points", "fixed_npcs", "commerce", "model_configs", "equipment_sets", "head_cosmetics", "world_story", "world_phases", "covenant_altars", "gameplay_balance"):
        node = f"canonical:family:{family}"
        g.ensure_node(node, "CANONICAL_FAMILY", family, path=f"Content/canonical/{family}")
        g.connect("canonical:source", node, "DECLARES_AUTHORITY_FOR", evidence="CANONICAL_SOURCE.json + Content/canonical tree", confidence=1.0, required=True, status="AUTHORITATIVE")
        for pack in family_to_packs.get(family, []):
            pnode = f"canonical:pack:{pack}"
            g.ensure_node(pnode, "COMPILED_PACK", pack, path=f"Content/packs/{pack}")
            g.connect(node, pnode, "COMPILES_TO", evidence="tools/content_port canonical build pipeline", confidence=1.0, required=True, status="SOURCE_PROVEN")
            g.connect("canonical:build", pnode, "DECLARES_HASH_FOR", evidence="Content/BUILD.json", confidence=1.0, required=True, status="HASH_GATED")
    for profile in ("client", "server"):
        node = f"canonical:map_profile:{profile}"
        pack = f"maps_{profile}.smap"
        g.ensure_node(node, "CANONICAL_MAP_PROFILE", profile.upper(), path=f"Content/canonical/maps/{profile}.maps.json")
        g.ensure_node(f"canonical:pack:{pack}", "COMPILED_PACK", pack, path=f"Content/packs/{pack}")
        g.connect("canonical:source", node, "DECLARES_PROFILE_AUTHORITY_FOR", evidence=f"canonical/maps/{profile}.maps.json", confidence=1.0, required=True, status="AUTHORITATIVE")
        g.connect(node, f"canonical:pack:{pack}", "COMPILES_TO", evidence=f"compile_canonical_maps.py --profile {profile}", confidence=1.0, required=True, status="SOURCE_PROVEN")
        g.connect("canonical:build", f"canonical:pack:{pack}", "DECLARES_HASH_FOR", evidence="Content/BUILD.json", confidence=1.0, required=True, status="HASH_GATED")
    if include_documents:
        definition_nodes_by_id: dict[str, str] = {}
        definition_nodes_by_code: dict[str, str] = {}
        for doc in provider.iter_text_documents():
            if not doc.canonical_id:
                continue
            node = f"canonical:document:{doc.canonical_id}"
            code = _code_for_doc(doc.data)
            g.ensure_node(node, "CANONICAL_DOCUMENT", doc.canonical_id, family=doc.family, path=doc.relative_path, sha256=doc.sha256, code=code or None)
            g.connect("canonical:family:text", node, "CONTAINS", evidence=doc.relative_path, confidence=1.0, required=True, status="AUTHORITATIVE")
            runtime_path = _pathish(doc.data, "runtime_path")
            linked_file = _pathish(doc.data, "linked_file")
            for relation, pathish in (("DECLARES_RUNTIME_PATH", runtime_path), ("LINKS_FILE", linked_file)):
                if pathish:
                    pnode = "runtime:path:" + str(pathish).replace("\\", "/").casefold()
                    g.ensure_node(pnode, "RUNTIME_PATH", str(pathish), path=str(pathish))
                    g.connect(node, pnode, relation, evidence=doc.relative_path, confidence=1.0, required=None, status="SOURCE_PROVEN")
            if doc.family in DEFINITION_FAMILIES:
                definition_nodes_by_id[doc.canonical_id.casefold()] = node
                if code:
                    definition_nodes_by_code[code.upper()] = node
            if doc.family == "open_item_definition":
                for profile in ("client", "server"):
                    g.connect(node, f"canonical:pack:definitions_{profile}.scfg", "DEFINITION_COMPILES_TO", evidence=f"compile_definitions.py --item-profile {profile}.items.json", confidence=1.0, required=None, status="PROFILE_GATED")
            elif doc.family in {"monster_definition", "npc_definition"}:
                for profile in ("client", "server"):
                    g.connect(node, f"canonical:pack:definitions_{profile}.scfg", "DEFINITION_COMPILES_TO", evidence="compile_definitions.py", confidence=1.0, required=True, status="SOURCE_PROVEN")

        for profile, entry in provider.item_profiles().items():
            pnode = f"canonical:item_profile:{profile}"
            g.ensure_node(pnode, "ITEM_PROFILE", profile.upper(), path=entry["path"], sha256=entry["sha256"])
            g.connect("canonical:source", pnode, "DECLARES_PROFILE_AUTHORITY_FOR", evidence=entry["path"], confidence=1.0, required=True, status="AUTHORITATIVE")
            ids, codes = _extract_profile_membership(entry["data"])
            for cid in sorted(ids):
                target = definition_nodes_by_id.get(cid)
                if target:
                    g.connect(pnode, target, "INCLUDES_ITEM", evidence=entry["path"], confidence=1.0, required=True, status="PROFILE_GATED")
            for code in sorted(codes):
                target = definition_nodes_by_code.get(code)
                if target:
                    g.connect(pnode, target, "INCLUDES_ITEM_CODE", evidence=entry["path"], confidence=1.0, required=True, status="PROFILE_GATED")

        for family in ("stage_spawns", "stage_start_points", "fixed_npcs"):
            root = provider.canonical_root / family
            fnode = f"canonical:family:{family}"
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.json"), key=lambda p: p.as_posix().casefold()):
                try:
                    data = _json(path)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                cid = canonical_id_for_doc(data, family) or str(data.get("stage_id") or data.get("map_id") or data.get("id") or path.stem)
                node = f"canonical:{family}:{cid}"
                rel = _safe_rel(provider.content_root, path)
                g.ensure_node(node, "CANONICAL_DOCUMENT", cid, family=family, path=rel, sha256=sha256_file(path))
                g.connect(fnode, node, "CONTAINS", evidence=rel, confidence=1.0, required=True, status="AUTHORITATIVE")
                g.connect(node, "canonical:pack:field_runtime.sfld", "COMPILES_TO", evidence="compile_field_runtime.py", confidence=1.0, required=True, status="SOURCE_PROVEN")
                for refkey in ("stage_id", "map_id", "field_code", "runtime_path", "linked_file"):
                    value = _first_scalar(_lookup_field(data, refkey))
                    if value not in (None, ""):
                        rnode = f"canonical:ref:{refkey}:{str(value).casefold()}"
                        g.ensure_node(rnode, "CANONICAL_REFERENCE", str(value), reference_key=refkey)
                        g.connect(node, rnode, "REFERENCES", evidence=rel, confidence=1.0, required=None, status="SOURCE_PROVEN")

        for row in _map_rows(provider, {}):
            cid = str(row.get("canonical_id") or "")
            profile = str(row.get("profile") or "").lower()
            node = f"canonical:map:{profile}:{cid}"
            g.ensure_node(node, "CANONICAL_MAP", cid, profile=profile.upper(), field_code=row.get("field_code"), path=row.get("canonical_path"))
            g.connect(f"canonical:map_profile:{profile}", node, "CONTAINS", evidence=str(row.get("canonical_path")), confidence=1.0, required=True, status="AUTHORITATIVE")
            g.connect(node, f"canonical:pack:maps_{profile}.smap", "COMPILES_TO", evidence=f"compile_maps.py {profile}.maps.json", confidence=1.0, required=True, status="SOURCE_PROVEN")
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            for refkey in ("stage_id", "stage", "runtime_path", "linked_file", "field_code"):
                value = _first_scalar(_lookup_field(data, refkey))
                if value not in (None, ""):
                    rnode = f"canonical:ref:{refkey}:{str(value).casefold()}"
                    g.ensure_node(rnode, "CANONICAL_REFERENCE", str(value), reference_key=refkey)
                    g.connect(node, rnode, "REFERENCES", evidence=str(row.get("canonical_path")), confidence=1.0, required=None, status="SOURCE_PROVEN")
    g.ensure_node("canonical:map_dynamic_append", "MAP_DYNAMIC_POLICY", "Dynamic field appends after static catalog", strategy="append_after_static")
    g.connect("canonical:source", "canonical:map_dynamic_append", "DECLARES_DYNAMIC_FIELD_POLICY", evidence="canonical map profile contract", confidence=1.0, required=True, status="AUTHORITATIVE")
    return g.to_dict(metadata={
        "authority": "SUMMIT_CANONICAL_SOURCE",
        "source_root": str(provider.source_root),
        "source_fingerprint": sha256_file(provider.canonical_source_path),
        "profile_collapse_forbidden": True,
    })


def build_semantic_catalog_v2(provider: SummitCanonicalContentProvider) -> dict[str, Any]:
    overlay_by_id, _ambiguous = _overlay_index()
    memberships = _profile_memberships(provider)
    items: list[dict[str, Any]] = []
    mobs: list[dict[str, Any]] = []
    npcs: list[dict[str, Any]] = []
    missing_display: list[str] = []
    text_resources: list[dict[str, Any]] = []
    for doc in provider.text_resource_documents():
        text_resources.append({
            "canonical_id": doc.canonical_id,
            "family": doc.family,
            "canonical_path": doc.relative_path,
            "sha256": doc.sha256,
            "schema": doc.data.get("schema"),
            "display_name": _canonical_name(doc.data) or None,
        })
        if doc.family not in DEFINITION_FAMILIES:
            continue
        overlay = overlay_by_id.get(doc.canonical_id.casefold()) if doc.canonical_id else None
        row = _definition_row(doc, overlay, memberships)
        if row.get("display_warning") == "MISSING_DISPLAY_NAME":
            missing_display.append(doc.canonical_id)
        if doc.family == "open_item_definition":
            items.append(row)
        elif doc.family == "monster_definition":
            mobs.append(row)
        elif doc.family == "npc_definition":
            npcs.append(row)
    maps = _map_rows(provider, overlay_by_id)
    status = provider.status()
    unique_map_ids = {str(x.get("canonical_id") or "").casefold() for x in maps if x.get("canonical_id")}
    spawn_root = provider.canonical_root / "stage_spawns"
    spawn_count = sum(1 for p in spawn_root.rglob("*.json") if p.is_file()) if spawn_root.is_dir() else 0
    return {
        "format": CATALOG_FORMAT,
        "title": "PT Asset Tool Semantic Catalog V2 — Summit Canonical Source",
        "generated_from": "Summit Content/canonical/** + priston_asset_name_map_v1.json display overlay",
        "important_correction": "Canonical source defines existence/identity; legacy name map is display/ambiguity/migration overlay only.",
        "status": "PASS",
        "authority": "SUMMIT_CANONICAL_SOURCE",
        "source_root": str(provider.source_root),
        "source_fingerprint": status["canonical_source_sha256"],
        "build_manifest_fingerprint": status["build_manifest_sha256"],
        "build_freshness": status["build_freshness"],
        "alias_overlay": "priston_asset_name_map_v1.json",
        "alias_overlay_role": ["display_alias", "pt-BR friendly names", "ambiguity metadata", "migration aid"],
        "counts": {
            "items": len(items), "mobs": len(mobs), "npcs": len(npcs),
            "maps": len(unique_map_ids),
            "maps_client": sum(1 for x in maps if x.get("profile") == "CLIENT"),
            "maps_server": sum(1 for x in maps if x.get("profile") == "SERVER"),
            "spawn_stages": spawn_count,
            "text_resources": len(text_resources), "missing_display_names": len(missing_display),
            "gameplay_configs": status.get("gameplay_config", {}).get("documents", 0),
            "gameplay_config_entries": status.get("gameplay_config", {}).get("entries", 0),
        },
        "items": items,
        "mobs": mobs,
        "npcs": npcs,
        "maps": maps,
        "text_resources": text_resources,
        "missing_display_name_ids": missing_display,
        "dynamic_field_policy": "APPEND_AFTER_STATIC_CATALOG",
        "localization": status["localization"],
        "reference_content": {"quest_codex": "REFERENCE_ONLY", "mix_guide": "REFERENCE_ONLY"},
        "contract_graph": build_canonical_contract_graph(provider, include_documents=False),
    }
