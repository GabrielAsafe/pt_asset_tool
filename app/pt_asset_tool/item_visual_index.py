from __future__ import annotations

import hashlib
import json
import os
import pathlib
from collections import defaultdict
from typing import Any, Iterable

from .item_runtime_catalog import item_runtime_catalog

FORMAT = "PT_ITEM_VISUAL_INDEX_V1"

ROLE_LABELS = {
    "ITEM_INVENTORY_IMAGE": "Inventário · imagem",
    "ITEM_GROUND_MODEL": "Chão · modelo",
    "ITEM_GROUND_TEXTURE": "Chão · textura",
    "ITEM_EQUIPPED_CONFIG": "Equipado · config",
    "ITEM_EQUIPPED_MODEL": "Equipado · modelo",
    "ITEM_EQUIPPED_TEXTURE": "Equipado · textura",
    "ITEM_SUPPORT": "Suporte / relacionado",
}
ROLE_ORDER = tuple(ROLE_LABELS)
IMAGE_EXTS = {".bmp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".webp"}
MODEL_EXTS = {".smd", ".ase"}
CONFIG_EXTS = {".inx", ".ini", ".inf"}


def _norm(value: str | pathlib.PurePath | None) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def _cf(value: str | pathlib.PurePath | None) -> str:
    return _norm(value).casefold()


def _stat_key(path: pathlib.Path | None) -> list[int]:
    if path is None:
        return [0, 0]
    try:
        st = pathlib.Path(path).stat()
        return [int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [0, 0]


def _load_json(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _split_note_paths(note: Any) -> list[str]:
    if not isinstance(note, str):
        return []
    return [_norm(x) for x in note.split(";") if _norm(x)]


def _resolve_reference(ref: str, *, source_path: str, by_path: dict[str, dict[str, Any]], by_basename: dict[str, list[str]]) -> str | None:
    raw = _norm(ref)
    if not raw:
        return None
    direct = by_path.get(raw.casefold())
    if direct:
        return str(direct.get("relative_path") or direct.get("path") or raw)
    # Runtime refs frequently omit extension or are relative to the model/config.
    source_parent = pathlib.PurePosixPath(source_path).parent
    candidates: list[str] = []
    if "/" not in raw:
        candidates.append(_norm(source_parent / raw))
    suffix = pathlib.PurePosixPath(raw).suffix.casefold()
    if not suffix:
        for ext in (".smd", ".smb", ".inx", ".ini", ".bmp", ".tga", ".dds"):
            candidates.append(raw + ext)
            if "/" not in raw:
                candidates.append(_norm(source_parent / (raw + ext)))
    for candidate in candidates:
        rec = by_path.get(candidate.casefold())
        if rec:
            return str(rec.get("relative_path") or rec.get("path") or candidate)
    # Unique basename is a safe final resolver for persisted-census evidence.
    base = pathlib.PurePosixPath(raw).name.casefold()
    matches = by_basename.get(base) or []
    if len(matches) == 1:
        return matches[0]
    return None


def _texture_signature(path: str, *, records: dict[str, dict[str, Any]], by_basename: dict[str, list[str]], graph_out: dict[str, list[dict[str, Any]]]) -> tuple[str, ...]:
    rec = records.get(path.casefold()) or {}
    refs: list[str] = []
    for ref in rec.get("texture_refs") or []:
        resolved = _resolve_reference(str(ref), source_path=path, by_path=records, by_basename=by_basename)
        if resolved:
            refs.append(resolved)
    # The enhancement dependency graph has already resolved many client-relative refs.
    for edge in graph_out.get(f"client:{_norm(path)}".casefold(), []):
        if str(edge.get("relation") or "") != "client_asset_reference":
            continue
        dst = str(edge.get("dst") or "")
        if not dst.casefold().startswith("client:"):
            continue
        target = _norm(dst.split(":", 1)[1])
        if pathlib.PurePosixPath(target).suffix.casefold() not in IMAGE_EXTS:
            continue
        rec2 = records.get(target.casefold())
        refs.append(str((rec2 or {}).get("relative_path") or target))
    return tuple(sorted({x.casefold(): x for x in refs}.values(), key=str.casefold))


def _graph_maps(graph: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        outgoing[str(edge.get("src") or "").casefold()].append(edge)
        incoming[str(edge.get("dst") or "").casefold()].append(edge)
    return outgoing, incoming


def _catalog_paths_for_item(code: str, relation: str, graph_out: dict[str, list[dict[str, Any]]]) -> list[str]:
    out: list[str] = []
    for edge in graph_out.get(f"item:{code}".casefold(), []):
        if str(edge.get("relation") or "") != relation:
            continue
        out.extend(_split_note_paths(edge.get("note")))
    return out


def _find_existing(path: str | None, records: dict[str, dict[str, Any]]) -> str | None:
    if not path:
        return None
    rec = records.get(_cf(path))
    return str(rec.get("relative_path") or rec.get("path")) if rec else None


def _same_stem_companions(path: str, records: dict[str, dict[str, Any]], exts: Iterable[str]) -> list[str]:
    p = pathlib.PurePosixPath(path)
    base = p.with_suffix("").as_posix()
    out = []
    for ext in exts:
        found = _find_existing(base + ext, records)
        if found:
            out.append(found)
    return out


def _default_role(path: str, *, inventory_icons: set[str], ground_models: set[str], ground_textures: set[str], equipped_models: set[str], equipped_configs: set[str], equipped_textures: set[str]) -> str:
    key = path.casefold()
    if key in inventory_icons:
        return "ITEM_INVENTORY_IMAGE"
    if key in ground_models:
        return "ITEM_GROUND_MODEL"
    if key in ground_textures:
        return "ITEM_GROUND_TEXTURE"
    if key in equipped_configs:
        return "ITEM_EQUIPPED_CONFIG"
    if key in equipped_models:
        return "ITEM_EQUIPPED_MODEL"
    if key in equipped_textures:
        return "ITEM_EQUIPPED_TEXTURE"
    return "ITEM_SUPPORT"


def build_item_visual_index(
    inventory: dict[str, Any],
    graph: dict[str, Any] | None,
    catalog_rows: Iterable[dict[str, Any]],
    *,
    runtime_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build item visual bundles from persisted census + enrichment graph.

    Runtime identities remain distinct. Bundles group only the visual representation
    when persisted evidence proves an exact non-empty texture dependency set.
    """
    graph = graph or {}
    records_list = [x for x in inventory.get("records") or [] if isinstance(x, dict)]
    records = {_cf(x.get("relative_path")): x for x in records_list if _norm(x.get("relative_path"))}
    by_basename: dict[str, list[str]] = defaultdict(list)
    for rec in records_list:
        rel = _norm(rec.get("relative_path"))
        if rel:
            by_basename[pathlib.PurePosixPath(rel).name.casefold()].append(rel)
    row_by_path = {_cf(x.get("path")): x for x in catalog_rows if isinstance(x, dict) and _norm(x.get("path"))}
    graph_out, graph_in = _graph_maps(graph)

    if runtime_entries is None:
        runtime_entries = list(item_runtime_catalog().get("entries") or [])

    item_rows: list[dict[str, Any]] = []
    for item in runtime_entries:
        code = str(item.get("code") or "").strip().upper()
        if not code:
            continue
        expected = item.get("expected_client_paths") or {}
        icons = _catalog_paths_for_item(code, "catalog_icon", graph_out)
        if not icons:
            found = _find_existing(expected.get("inventory_icon"), records)
            if found:
                icons = [found]
        ground_models = _catalog_paths_for_item(code, "catalog_drop_model", graph_out)
        if not ground_models:
            found = _find_existing(expected.get("drop_model_ase"), records)
            if found:
                ground_models = [found]
            else:
                # Source contracts use ASE; deployed clients frequently carry SMD.
                base = pathlib.PurePosixPath(str(expected.get("drop_model_ase") or "")).with_suffix("").as_posix()
                for ext in (".smd", ".ase", ".inx", ".smb"):
                    f = _find_existing(base + ext, records)
                    if f:
                        ground_models.append(f)
        texture_sets = [_texture_signature(p, records=records, by_basename=by_basename, graph_out=graph_out) for p in ground_models]
        texture_sets = [x for x in texture_sets if x]
        signature = tuple(sorted({v.casefold(): v for values in texture_sets for v in values}.values(), key=str.casefold))
        item_rows.append({
            "code": code,
            "numeric_code": item.get("numeric_code"),
            "dorp_item": item.get("dorp_item"),
            "inventory_icons": sorted(set(icons), key=str.casefold),
            "ground_models": sorted(set(ground_models), key=str.casefold),
            "ground_textures": list(signature),
            "texture_signature": tuple(x.casefold() for x in signature),
        })

    # Runtime item identity is never collapsed. Only a proven exact texture set
    # is allowed to share a visual bundle; otherwise each code has its own bundle.
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in item_rows:
        sig = item["texture_signature"]
        if sig:
            digest = hashlib.sha256("\n".join(sig).encode("utf-8")).hexdigest()[:16]
            key = f"ITEM_VISUAL|texset:{digest}"
        else:
            key = f"ITEM_VISUAL|runtime:{item['code'].casefold()}"
        buckets[key].append(item)

    models_by_signature: dict[tuple[str, ...], list[str]] = defaultdict(list)
    model_textures: dict[str, tuple[str, ...]] = {}
    for rec in records_list:
        rel = _norm(rec.get("relative_path"))
        if pathlib.PurePosixPath(rel).suffix.casefold() not in MODEL_EXTS:
            continue
        if "/dropitem/" in f"/{rel.casefold()}/":
            continue
        textures = _texture_signature(rel, records=records, by_basename=by_basename, graph_out=graph_out)
        if textures:
            sig = tuple(x.casefold() for x in textures)
            models_by_signature[sig].append(rel)
            model_textures[rel.casefold()] = textures

    # Resolve INX -> model only once. The older per-bundle scan multiplied the
    # cost by every runtime item and made the derived index unnecessarily heavy.
    inx_by_model: dict[str, list[str]] = defaultdict(list)
    for rec in records_list:
        rel = _norm(rec.get("relative_path"))
        if pathlib.PurePosixPath(rel).suffix.casefold() != ".inx":
            continue
        resolved_model = _resolve_reference(str(rec.get("model_ref") or ""), source_path=rel, by_path=records, by_basename=by_basename)
        if resolved_model:
            inx_by_model[resolved_model.casefold()].append(rel)

    bundles: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    by_runtime_code: dict[str, str] = {}
    for bundle_key, members in sorted(buckets.items()):
        runtime_codes = sorted({x["code"] for x in members}, key=str.casefold)
        inventory_icons = {p.casefold(): p for m in members for p in m["inventory_icons"]}
        ground_models = {p.casefold(): p for m in members for p in m["ground_models"]}
        ground_textures = {p.casefold(): p for m in members for p in m["ground_textures"]}
        signature = next((m["texture_signature"] for m in members if m["texture_signature"]), ())

        equipped_models: dict[str, str] = {}
        equipped_textures: dict[str, str] = {}
        equipped_configs: dict[str, str] = {}
        if signature:
            for model in models_by_signature.get(signature, []):
                equipped_models[model.casefold()] = model
                for tex in model_textures.get(model.casefold(), ()):
                    equipped_textures[tex.casefold()] = tex
                client_id = f"client:{model}".casefold()
                # Existing survey graph: configs/text files that reference this model.
                for edge in graph_in.get(client_id, []):
                    if str(edge.get("relation") or "") != "client_asset_reference":
                        continue
                    src = str(edge.get("src") or "")
                    if not src.casefold().startswith("client:"):
                        continue
                    candidate = _norm(src.split(":", 1)[1])
                    if pathlib.PurePosixPath(candidate).suffix.casefold() in CONFIG_EXTS and candidate.casefold() in records:
                        equipped_configs[candidate.casefold()] = str(records[candidate.casefold()].get("relative_path") or candidate)
                # Persisted INX parser proves the configured model reference.
                for rel in inx_by_model.get(model.casefold(), []):
                    equipped_configs[rel.casefold()] = rel
                    for sibling in _same_stem_companions(rel, records, (".ini",)):
                        equipped_configs[sibling.casefold()] = sibling

        all_paths_map: dict[str, str] = {}
        for mapping in (inventory_icons, ground_models, ground_textures, equipped_models, equipped_configs, equipped_textures):
            all_paths_map.update(mapping)

        role_sets = {
            "inventory_icons": set(inventory_icons),
            "ground_models": set(ground_models),
            "ground_textures": set(ground_textures),
            "equipped_models": set(equipped_models),
            "equipped_configs": set(equipped_configs),
            "equipped_textures": set(equipped_textures),
        }
        role_groups: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLE_ORDER}
        for path in sorted(all_paths_map.values(), key=str.casefold):
            automatic = _default_role(path, **role_sets)
            catalog_row = row_by_path.get(path.casefold()) or {}
            effective = str(catalog_row.get("role") or "").strip().upper()
            manual = effective if effective in ROLE_LABELS and effective != automatic else ""
            role = manual or automatic
            entry = {
                "path": path,
                "role": role,
                "role_label": ROLE_LABELS[role],
                "automatic_role": automatic,
                "automatic_role_label": ROLE_LABELS[automatic],
                "manual_override": bool(manual),
                "previewable": bool(catalog_row.get("previewable")),
                "ext": str(catalog_row.get("ext") or pathlib.PurePosixPath(path).suffix).lower(),
            }
            role_groups[role].append(entry)
            by_path[path.casefold()] = {
                "bundle_key": bundle_key,
                "runtime_codes": runtime_codes,
                **entry,
            }
        evidence = "EXACT_FULL_TEXTURE_DEPENDENCY_SET" if signature else "RUNTIME_ITEM_PATHS_ONLY"
        bundle = {
            "bundle_key": bundle_key,
            "runtime_codes": runtime_codes,
            "runtime_identity_count": len(runtime_codes),
            "evidence": evidence,
            "texture_signature": list(signature),
            "asset_count": len(all_paths_map),
            "roles": role_groups,
            "all_paths": sorted(all_paths_map.values(), key=str.casefold),
        }
        bundles.append(bundle)
        for code in runtime_codes:
            by_runtime_code[code.casefold()] = bundle_key

    bundle_map = {x["bundle_key"]: x for x in bundles}
    return {
        "format": FORMAT,
        "status": "PASS",
        "bundle_count": len(bundles),
        "runtime_item_count": len(item_rows),
        "bundles": bundles,
        "by_path": by_path,
        "by_runtime_code": by_runtime_code,
        "bundle_map": bundle_map,
        "role_labels": dict(ROLE_LABELS),
        "sources": {
            "runtime_registry": True,
            "enhancement_dependency_graph": bool(graph.get("edges")),
            "runtime_item_catalog": True,
            "manual_ui_state": True,
        },
    }


def cache_key(
    inventory_path: pathlib.Path,
    graph_path: pathlib.Path | None,
    *,
    state_revision: int,
    client_signature: str = "",
) -> dict[str, Any]:
    return {
        "client_signature": str(client_signature or ""),
        "inventory": _stat_key(inventory_path),
        "dependency_graph": _stat_key(graph_path),
        "ui_state_revision": int(state_revision),
    }


def load_or_build_item_visual_index(
    *,
    inventory_path: pathlib.Path,
    graph_path: pathlib.Path | None,
    cache_path: pathlib.Path,
    catalog_rows: Iterable[dict[str, Any]],
    state_revision: int,
    client_signature: str = "",
    runtime_entries: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    key = cache_key(inventory_path, graph_path, state_revision=state_revision, client_signature=client_signature)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cached = None
    if isinstance(cached, dict) and cached.get("format") == FORMAT and cached.get("cache_key") == key and isinstance(cached.get("index"), dict):
        return cached["index"], True

    inventory = _load_json(inventory_path)
    graph = _load_json(graph_path)
    index = build_item_visual_index(inventory, graph, catalog_rows, runtime_entries=runtime_entries)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"format": FORMAT, "cache_key": key, "index": index}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(tmp, cache_path)
    except Exception:
        pass
    return index, False
