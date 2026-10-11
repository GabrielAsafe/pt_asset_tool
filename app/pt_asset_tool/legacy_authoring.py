from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shlex
import struct
import time
from typing import Any

from .asset_bundle_deploy import (
    APPLY_CONFIRM,
    RESTORE_CONFIRM,
    publish_asset_bundle,
    restore_asset_bundle,
)
from .asset_compiler import (
    BUNDLE_BUILD_FORMAT,
    BUNDLE_RECIPE_FORMAT,
    RECIPE_FORMAT,
    _CHARACTER_CORE_FIELDS,
    _CHARACTER_MONSTER_FIELDS,
    _CHARACTER_NPC_FIELDS,
    _ITEM_FIELD_SPECS,
    _item_values,
    _typed_values,
    _source_token,
    _legacy_line,
    compile_asset_bundle,
)
from .item_runtime_catalog import lookup_item_runtime
from .summit_canonical import SummitCanonicalContentProvider
from .legacy_management_contracts import classify_item_code
from .legacy_name_catalog import public_authoring_name_catalog, semantic_binding_for_spec, semantic_matches_for_path, semantic_related_bindings_for_spec
from .server_field_editor import (
    SPC_FILE_SIZE,
    SPC_RECORD_COUNT,
    SPC_RECORD_SIZE,
    SPP_FILE_SIZE,
    SPP_RECORD_COUNT,
    SPP_RECORD_SIZE,
    _inspect_spc,
    _inspect_spp,
    _inspect_spm,
    build_spc_record,
)

FORMAT = "PT_LEGACY_AUTHORING_V1"
PATCH_KINDS = {"LEGACY_TEXT_PATCH", "LEGACY_SPM_PATCH", "LEGACY_SPP_PATCH", "LEGACY_SPC_PATCH"}
SUPPORTED = {"ITEM", "MONSTER", "NPC", "SPM", "SPP", "SPC"}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rel(value: str) -> pathlib.PurePosixPath:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    p = pathlib.PurePosixPath(text)
    if not p.parts or any(x in {"", ".", ".."} for x in p.parts):
        raise ValueError("INVALID_LOGICAL_PATH")
    return p


def _ci_file(root: pathlib.Path, logical: str) -> pathlib.Path | None:
    root = pathlib.Path(root).resolve()
    rel = _safe_rel(logical)
    cur = root
    for part in rel.parts:
        direct = cur / part
        if direct.exists():
            cur = direct
            continue
        if not cur.is_dir():
            return None
        matches = [x for x in cur.iterdir() if x.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        cur = matches[0]
    try:
        cur.resolve().relative_to(root)
    except Exception:
        return None
    return cur.resolve() if cur.is_file() else None


def _decode_text(raw: bytes) -> tuple[str, str, str]:
    for enc in ("utf-8-sig", "cp949", "cp1252", "latin1"):
        try:
            text = raw.decode(enc)
            newline = "\r\n" if b"\r\n" in raw else ("\r" if b"\r" in raw and b"\n" not in raw else "\n")
            return text, enc, newline
        except UnicodeDecodeError:
            pass
    raise ValueError("LEGACY_TEXT_ENCODING_UNRESOLVED")


def _expected_prefix(kind: str) -> str:
    return {"ITEM": "GameServer/OpenItem/", "MONSTER": "GameServer/Monster/", "NPC": "GameServer/NPC/", "SPM": "GameServer/Field/", "SPP": "GameServer/Field/", "SPC": "GameServer/Field/"}[kind]


def _validate_kind_path(kind: str, logical: str) -> pathlib.PurePosixPath:
    kind = str(kind).upper()
    if kind not in SUPPORTED:
        raise ValueError(f"LEGACY_AUTHORING_KIND_UNSUPPORTED:{kind}")
    rel = _safe_rel(logical)
    low = rel.as_posix().casefold()
    if not low.startswith(_expected_prefix(kind).casefold()):
        raise ValueError(f"LEGACY_AUTHORING_PATH_OUTSIDE_KIND:{kind}:{rel.as_posix()}")
    suffix = rel.suffix.casefold()
    expected = {"ITEM": ".txt", "MONSTER": ".inf", "NPC": ".npc", "SPM": ".spm", "SPP": ".spp", "SPC": ".spc"}[kind]
    if suffix != expected:
        raise ValueError(f"LEGACY_AUTHORING_SUFFIX_INVALID:{kind}:{suffix}:{expected}")
    return rel


def _token_maps(kind: str) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    if kind == "ITEM":
        specs = dict(_ITEM_FIELD_SPECS)
        registry = "item_tokens"
    else:
        specs = dict(_CHARACTER_CORE_FIELDS)
        if kind == "MONSTER":
            specs.update(_CHARACTER_MONSTER_FIELDS)
        elif kind == "NPC":
            specs.update(_CHARACTER_NPC_FIELDS)
        registry = "character_tokens"
    token_to_field: dict[str, str] = {}
    for field, (name, _type) in specs.items():
        token_to_field[_source_token(registry, name)] = field
    return specs, token_to_field


def _parse_words(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except Exception:
        return text.split()


def _inspect_text_definition(kind: str, raw: bytes) -> dict[str, Any]:
    text, enc, newline = _decode_text(raw)
    specs, token_to_field = _token_maps(kind)
    recognized: dict[str, list[list[str]]] = {}
    unknown: list[str] = []
    repeated: dict[str, list[list[str]]] = {"dialogs": [], "drops": [], "extra_drops": [], "jobs": [], "random_jobs": [], "shops": []}
    registry = "item_tokens" if kind == "ITEM" else "character_tokens"
    special: dict[str, tuple[str, str]] = {}
    if kind == "ITEM":
        special = {
            _source_token(registry, "UniqueColor"): ("unique_color", "single"),
            _source_token(registry, "Job"): ("jobs", "repeated"),
            _source_token(registry, "JobRandom"): ("random_jobs", "repeated"),
            _source_token(registry, "LinkedFile"): ("linked_file", "single"),
        }
    else:
        special = {
            _source_token(registry, "Dialog"): ("dialogs", "repeated"),
            _source_token(registry, "LinkedFile"): ("linked_file", "single"),
        }
        if kind == "MONSTER":
            special.update({
                _source_token(registry, "FallItem"): ("drops", "repeated"),
                _source_token(registry, "ExtraFallItem"): ("extra_drops", "repeated"),
            })
        if kind == "NPC":
            for name in ("SellWeapon", "SellDefence", "SellEtc"):
                special[_source_token(registry, name)] = ("shops", "repeated")
    for original in text.splitlines():
        s = original.strip()
        if not s or s.startswith("//") or s.startswith("#") or s.startswith(";"):
            continue
        parts = s.split(None, 1)
        head = parts[0]
        tail = parts[1] if len(parts) > 1 else ""
        if head in token_to_field:
            recognized.setdefault(token_to_field[head], []).append(_parse_words(tail))
        elif head in special:
            name, mode = special[head]
            values = _parse_words(tail)
            if mode == "repeated":
                repeated.setdefault(name, []).append(values)
            else:
                recognized.setdefault(name, []).append(values)
        else:
            unknown.append(original)
    return {
        "encoding": enc,
        "newline": newline.replace("\r", "\\r").replace("\n", "\\n"),
        "recognized": recognized,
        "repeated": repeated,
        "unknown_line_count": len(unknown),
        "unknown_sample": unknown[:30],
        "raw_text": text,
        "field_count": len(specs),
    }


def inspect_authoring(project_root: pathlib.Path, server_root: pathlib.Path, client_root: pathlib.Path | None, kind: str, logical: str) -> dict[str, Any]:
    kind = str(kind).upper()
    rel = _validate_kind_path(kind, logical)
    source = _ci_file(pathlib.Path(server_root), rel.as_posix())
    if source is None:
        return {
            "format": FORMAT, "status": "NEW", "kind": kind, "logical_path": rel.as_posix(),
            "exists": False, "source": None, "source_sha256": None, "detail": None,
            "semantic_catalog_matches": semantic_matches_for_path(rel.as_posix()),
            "create_authorized": True, "edit_authorized": False,
        }
    raw = source.read_bytes()
    if kind in {"ITEM", "MONSTER", "NPC"}:
        detail = _inspect_text_definition(kind, raw)
        if kind == "ITEM":
            codes = detail["recognized"].get("code") or []
            code = str(codes[0][0]) if codes and codes[0] else None
            detail["runtime_item_contract"] = lookup_item_runtime(code) if code else None
            detail["legacy_category"] = classify_item_code(code) if code else None
    elif kind == "SPM":
        detail = _inspect_spm(raw)
    elif kind == "SPP":
        detail = _inspect_spp(raw)
    else:
        detail = _inspect_spc(raw)
    return {
        "format": FORMAT, "status": detail.get("status", "PASS"), "kind": kind,
        "logical_path": rel.as_posix(), "exists": True, "source": str(source),
        "source_sha256": _sha_bytes(raw), "source_size": len(raw), "detail": detail,
        "semantic_catalog_matches": semantic_matches_for_path(rel.as_posix()),
        "create_authorized": False, "edit_authorized": detail.get("status", "PASS") == "PASS",
    }


def _line_head(line: str) -> str:
    s = line.strip()
    return s.split(None, 1)[0] if s else ""


def _replace_token(lines: list[str], token: str, new_lines: list[str]) -> list[str]:
    indexes = [i for i, x in enumerate(lines) if _line_head(x) == token]
    if indexes:
        first = indexes[0]
        out = [x for i, x in enumerate(lines) if i not in set(indexes)]
        for offset, row in enumerate(new_lines):
            out.insert(first + offset, row)
        return out
    if new_lines:
        # insert before trailing blank lines to preserve EOF layout as much as possible
        at = len(lines)
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        return lines[:at] + new_lines + lines[at:]
    return lines


def _field_line(kind: str, field: str, value: Any) -> str | None:
    specs, _ = _token_maps(kind)
    if field not in specs:
        raise ValueError(f"LEGACY_AUTHORING_FIELD_UNKNOWN:{kind}:{field}")
    token_name, ftype = specs[field]
    vals = _item_values(ftype, value) if kind == "ITEM" else _typed_values(ftype, value)
    if vals is None:
        return None
    return _legacy_line(_source_token("item_tokens" if kind == "ITEM" else "character_tokens", token_name), vals)


def _patch_text(kind: str, raw: bytes, patch: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    text, enc, newline = _decode_text(raw)
    lines = text.splitlines()
    changes: list[dict[str, Any]] = []
    set_fields = patch.get("set") or {}
    if not isinstance(set_fields, dict):
        raise ValueError("LEGACY_AUTHORING_SET_MUST_BE_OBJECT")
    specs, _ = _token_maps(kind)
    for field, value in set_fields.items():
        field = str(field)
        if field not in specs:
            raise ValueError(f"LEGACY_AUTHORING_FIELD_UNKNOWN:{kind}:{field}")
        token_name, _ftype = specs[field]
        token = _source_token("item_tokens" if kind == "ITEM" else "character_tokens", token_name)
        row = _field_line(kind, field, value)
        before = [x for x in lines if _line_head(x) == token]
        lines = _replace_token(lines, token, [row] if row is not None else [])
        after = [x for x in lines if _line_head(x) == token]
        if before != after:
            changes.append({"field": field, "before": before, "after": after})

    if kind == "ITEM":
        registry = "item_tokens"
        if "jobs" in patch:
            token = _source_token(registry, "Job")
            values = patch.get("jobs") or []
            if isinstance(values, str): values = [values]
            rows = [_legacy_line(token, [str(x) for x in values])] if values else []
            lines = _replace_token(lines, token, rows); changes.append({"field": "jobs", "after": rows})
        if "random_jobs" in patch:
            token = _source_token(registry, "JobRandom")
            values = patch.get("random_jobs") or []
            if isinstance(values, str): values = [values]
            rows = [_legacy_line(token, [str(x) for x in values])] if values else []
            lines = _replace_token(lines, token, rows); changes.append({"field": "random_jobs", "after": rows})
        if "unique_color" in patch:
            token = _source_token(registry, "UniqueColor")
            vals = patch.get("unique_color")
            rows = [] if vals is None or vals is False else [_legacy_line(token, list(vals))]
            lines = _replace_token(lines, token, rows); changes.append({"field": "unique_color", "after": rows})
        if "linked_file" in patch:
            token = _source_token(registry, "LinkedFile")
            val = str(patch.get("linked_file") or "").strip()
            rows = [_legacy_line(token, [val])] if val else []
            lines = _replace_token(lines, token, rows); changes.append({"field": "linked_file", "after": rows})
    else:
        registry = "character_tokens"
        if "dialogs" in patch:
            token = _source_token(registry, "Dialog")
            vals = patch.get("dialogs") or []
            if isinstance(vals, str): vals = [vals]
            rows = [_legacy_line(token, [str(x)]) for x in vals]
            lines = _replace_token(lines, token, rows); changes.append({"field": "dialogs", "after": rows})
        if kind == "NPC" and "shops" in patch:
            shops = patch.get("shops") or {}
            if not isinstance(shops, dict): raise ValueError("NPC_SHOPS_MUST_BE_OBJECT")
            for key, token_name in {"weapon":"SellWeapon", "defence":"SellDefence", "etc":"SellEtc"}.items():
                if key not in shops: continue
                vals = shops.get(key) or []
                if not isinstance(vals, list) or len(vals) > 32: raise ValueError(f"NPC_SHOP_ITEMS_RANGE:{key}:0..32")
                token = _source_token(registry, token_name)
                rows = [_legacy_line(token, [str(x) for x in vals])] if vals else []
                lines = _replace_token(lines, token, rows); changes.append({"field": f"shops.{key}", "after": rows})
        if kind == "MONSTER" and "drops" in patch:
            token = _source_token(registry, "FallItem")
            rows: list[str] = []
            for idx, drop in enumerate(patch.get("drops") or []):
                if not isinstance(drop, dict): raise ValueError(f"MONSTER_DROP_OBJECT_REQUIRED:{idx}")
                pct = int(drop.get("percentage", 0))
                if "money" in drop:
                    pair = drop["money"]
                    if not isinstance(pair, (list, tuple)) or len(pair) not in {1, 2}: raise ValueError(f"MONSTER_DROP_MONEY_VALUES_REQUIRED:{idx}:1..2")
                    vals = [pct, _source_token(registry, "Money"), *[int(x) for x in pair]]
                elif bool(drop.get("none")):
                    vals = [pct, _source_token(registry, "NoItem")]
                else:
                    items = drop.get("items") or []
                    if not isinstance(items, list) or not 1 <= len(items) <= 32: raise ValueError(f"MONSTER_DROP_ITEMS_RANGE:{idx}:1..32")
                    vals = [pct, *map(str, items)]
                rows.append(_legacy_line(token, vals))
            lines = _replace_token(lines, token, rows); changes.append({"field": "drops", "after": rows})
        if kind == "MONSTER" and "extra_drops" in patch:
            token = _source_token(registry, "ExtraFallItem")
            rows = []
            for idx, drop in enumerate(patch.get("extra_drops") or []):
                if not isinstance(drop, dict) or not drop.get("item"): raise ValueError(f"MONSTER_EXTRA_DROP_INVALID:{idx}")
                rows.append(_legacy_line(token, [int(drop.get("percentage", 0)), str(drop["item"])]))
            lines = _replace_token(lines, token, rows); changes.append({"field": "extra_drops", "after": rows})
        if "linked_file" in patch:
            token = _source_token(registry, "LinkedFile")
            val = str(patch.get("linked_file") or "").strip()
            rows = [_legacy_line(token, [val])] if val else []
            lines = _replace_token(lines, token, rows); changes.append({"field": "linked_file", "after": rows})

    if not changes:
        raise ValueError("LEGACY_AUTHORING_PATCH_EMPTY")
    out_text = newline.join(lines) + (newline if text.endswith(("\n", "\r")) else "")
    data = out_text.encode(enc)
    return data, {"writer": "LEGACY_TEXT_SOURCE_PRESERVING_PATCH", "kind": kind, "encoding": enc, "change_count": len(changes), "changes": changes}


def _patch_spm(raw: bytes, patch: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    text, enc, newline = _decode_text(raw)
    lines = text.splitlines()
    action = str(patch.get("action") or "").upper()
    name = str(patch.get("name") or "").strip()
    actor_tokens = {_source_token("character_tokens", "Actor") if False else "*ACTOR", "*출연자"}
    # PriTaTor/Summit files use English or Korean directive aliases. Keep existing dialect.
    actor_heads = {"*ACTOR", "*출연자"}
    boss_heads = {"*BOSS_ACTOR", "*출연자두목"}
    def head(x: str) -> str: return _line_head(x).upper()
    def actor_name(x: str) -> str | None:
        s=x.strip(); parts=s.split(None,1)
        if len(parts)<2:return None
        vals=_parse_words(parts[1]); return vals[0] if vals else None
    if action == "ADD_ACTOR":
        if not name: raise ValueError("SPM_ACTOR_NAME_REQUIRED")
        if any(actor_name(x) and actor_name(x).casefold()==name.casefold() for x in lines if head(x) in actor_heads):
            raise ValueError("SPM_ACTOR_ALREADY_PRESENT")
        if sum(1 for x in lines if head(x) in actor_heads) >= 50: raise ValueError("SPM_ACTOR_LIMIT_REACHED:50")
        weight=int(patch.get("weight") or 100)
        if weight<=0: raise ValueError("SPM_ACTOR_WEIGHT_MUST_BE_POSITIVE")
        at=max([i for i,x in enumerate(lines) if head(x) in actor_heads|boss_heads],default=len(lines)-1)+1
        lines.insert(at,f'*ACTOR "{name}" {weight}')
    elif action == "REMOVE_ACTOR":
        before=len(lines); lines=[x for x in lines if not (head(x) in actor_heads and actor_name(x) and actor_name(x).casefold()==name.casefold())]
        if len(lines)==before: raise ValueError("SPM_ACTOR_NOT_FOUND")
    elif action == "ADD_BOSS":
        master=str(patch.get("master") or name).strip(); slave=str(patch.get("slave") or "").strip()
        if not master or not slave: raise ValueError("SPM_BOSS_MASTER_SLAVE_REQUIRED")
        if sum(1 for x in lines if head(x) in boss_heads) >= 16: raise ValueError("SPM_BOSS_LIMIT_REACHED:16")
        for x in lines:
            if head(x) in boss_heads:
                vals=_parse_words(x.strip().split(None,1)[1] if len(x.strip().split(None,1))>1 else "")
                if vals and str(vals[0]).casefold()==master.casefold(): raise ValueError("SPM_BOSS_ALREADY_PRESENT")
        count=int(patch.get("slave_count") or 0); hours=[int(x) for x in (patch.get("hours") or [])]
        if count<0: raise ValueError("SPM_BOSS_SLAVE_COUNT_NEGATIVE")
        if any(not 0<=x<=255 for x in hours): raise ValueError("SPM_BOSS_HOUR_OUT_OF_BYTE_RANGE")
        tail="".join(f" {x}" for x in hours)
        lines.append(f'*BOSS_ACTOR "{master}" "{slave}" {count}{tail}')
    elif action == "REMOVE_BOSS":
        master=str(patch.get("master") or name).strip(); before=len(lines); out=[]
        for x in lines:
            remove=False
            if head(x) in boss_heads:
                vals=_parse_words(x.strip().split(None,1)[1] if len(x.strip().split(None,1))>1 else "")
                remove=bool(vals and str(vals[0]).casefold()==master.casefold())
            if not remove: out.append(x)
        lines=out
        if len(lines)==before: raise ValueError("SPM_BOSS_NOT_FOUND")
    elif action == "SET_DIRECTIVE":
        directive=str(patch.get("directive") or "").upper()
        mapping={"MAX_ACTOR_POS":"*MAX_ACTOR_POS","MAX_ACTOR":"*MAX_ACTOR","DELAY":"*DELAY"}
        if directive not in mapping: raise ValueError("SPM_DIRECTIVE_INVALID")
        token=mapping[directive]
        vals=patch.get("values")
        if not isinstance(vals,list): vals=[vals] if vals is not None else []
        new=token+(" "+" ".join(str(x) for x in vals) if vals else "")
        indexes=[i for i,x in enumerate(lines) if head(x)==token]
        if indexes:
            first=indexes[0]; lines=[x for i,x in enumerate(lines) if i not in set(indexes)]; lines.insert(first,new)
        else: lines.append(new)
    else:
        raise ValueError("SPM_PATCH_ACTION_INVALID")
    data=(newline.join(lines)+(newline if text.endswith(("\n","\r")) else "")).encode(enc)
    return data,{"writer":"LEGACY_SPM_STRUCTURED_PATCH","action":action,"encoding":enc,"parsed":_inspect_spm(data)}


def _patch_spp(raw: bytes, patch: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if len(raw)!=SPP_FILE_SIZE: raise ValueError("SPP_NON_CANONICAL_LAYOUT")
    edits=patch.get("records") or patch.get("edits") or []
    if not isinstance(edits,list) or not edits: raise ValueError("SPP_EDITS_REQUIRED")
    data=bytearray(raw); applied=[]; seen=set()
    for row in edits:
        idx=int(row["index"])
        if not 0<=idx<SPP_RECORD_COUNT or idx in seen: raise ValueError(f"SPP_INDEX_INVALID:{idx}")
        seen.add(idx); before=list(struct.unpack_from("<iii",data,idx*SPP_RECORD_SIZE)); after=[int(row.get("state",0)),int(row.get("x",0)),int(row.get("z",0))]
        struct.pack_into("<iii",data,idx*SPP_RECORD_SIZE,*after); applied.append({"index":idx,"before":before,"after":after})
    return bytes(data),{"writer":"LEGACY_SPP_RECORD_PATCH","applied":applied,"parsed":_inspect_spp(bytes(data))}


def _patch_spc(raw: bytes, patch: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if len(raw)!=SPC_FILE_SIZE: raise ValueError("SPC_NON_CANONICAL_LAYOUT")
    action=str(patch.get("action") or "ADD").upper(); idx=int(patch.get("index",-1)); data=bytearray(raw)
    records=_inspect_spc(raw).get("records") or []
    if action=="ADD":
        if idx<0:
            idx=next((r["index"] for r in records if r.get("blank")), -1)
        if idx<0 or idx>=SPC_RECORD_COUNT: raise ValueError("SPC_FREE_SLOT_REQUIRED")
        if records[idx].get("runtime_active"): raise ValueError("SPC_SLOT_ALREADY_ACTIVE")
        row=dict(patch.get("record") or {}); rec=build_spc_record(row,record_encoding=str(patch.get("record_encoding") or "cp949"))
        data[idx*SPC_RECORD_SIZE:(idx+1)*SPC_RECORD_SIZE]=rec
    elif action=="REMOVE":
        if not 0<=idx<SPC_RECORD_COUNT or not records[idx].get("runtime_active"): raise ValueError("SPC_ACTIVE_SLOT_REQUIRED")
        data[idx*SPC_RECORD_SIZE:(idx+1)*SPC_RECORD_SIZE]=b"\0"*SPC_RECORD_SIZE
    elif action=="REPLACE":
        if not 0<=idx<SPC_RECORD_COUNT or not records[idx].get("runtime_active"): raise ValueError("SPC_ACTIVE_SLOT_REQUIRED")
        row=dict(patch.get("record") or {}); rec=build_spc_record(row,record_encoding=str(patch.get("record_encoding") or "cp949"))
        data[idx*SPC_RECORD_SIZE:(idx+1)*SPC_RECORD_SIZE]=rec
    else: raise ValueError("SPC_PATCH_ACTION_INVALID")
    return bytes(data),{"writer":"LEGACY_SPC_NATIVE_PATCH","action":action,"index":idx,"parsed":_inspect_spc(bytes(data))}


def _write_patch_bundle(project_root: pathlib.Path, kind: str, rel: pathlib.PurePosixPath, source: pathlib.Path, data: bytes, writer: dict[str, Any]) -> dict[str, Any]:
    root_base=pathlib.Path(project_root).resolve()/"pt_build"/"asset_compiler"/"bundles"
    stamp=time.strftime("%Y%m%d_%H%M%S")
    digest=_sha_bytes(data)[:10]
    run_id=f"{stamp}_legacy_{kind.lower()}_{digest}"
    root=root_base/run_id; overlay=root/"overlay"; staged=overlay/"server"/pathlib.Path(*rel.parts)
    staged.parent.mkdir(parents=True,exist_ok=True); staged.write_bytes(data)
    source_raw=source.read_bytes()
    manifest={
        "format":BUNDLE_BUILD_FORMAT,"status":"PASS","run_id":run_id,"bundle_id":run_id,"bundle_type":"LEGACY_AUTHORING",
        "asset_count":1,"assets":[{
            "kind":{"ITEM":"LEGACY_TEXT_PATCH","MONSTER":"LEGACY_TEXT_PATCH","NPC":"LEGACY_TEXT_PATCH","SPM":"LEGACY_SPM_PATCH","SPP":"LEGACY_SPP_PATCH","SPC":"LEGACY_SPC_PATCH"}[kind],
            "contract_id":None,"target_side":"SERVER","logical_output":rel.as_posix(),"output":str(staged),"size":len(data),"sha256":_sha_bytes(data),
            "writer":writer,"target_evidence":{"policy":"PATCH_EXISTING","exists":True,"path":str(source),"sha256":_sha_bytes(source_raw)},
        }],
        "overlay_root":str(overlay),"warnings":[],"scope":"PT_BUILD_LEGACY_AUTHORING_OVERLAY_ONLY","client_modified":False,"server_modified":False,"target_write_authorized":False,
    }
    manifest_path=root/"manifest.json"; manifest["manifest"]=str(manifest_path); root.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest


def _attach_semantic_binding(
    manifest: dict[str, Any],
    binding: dict[str, Any] | None,
    related: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    related = list(related or [])
    if binding:
        manifest["authoring_semantic_binding"] = binding
    if related:
        manifest["authoring_semantic_related_bindings"] = related
    if not binding and not related:
        return manifest
    for asset in manifest.get("assets") or []:
        if isinstance(asset, dict):
            if binding:
                asset["authoring_semantic_binding"] = binding
            if related:
                asset["authoring_semantic_related_bindings"] = related
    manifest_path = manifest.get("manifest")
    if manifest_path:
        p = pathlib.Path(str(manifest_path))
        if p.is_file():
            p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _create_bundle_recipe(kind: str, logical: str, spec: dict[str, Any]) -> dict[str, Any]:
    cid={"ITEM":"item.definition.txt","MONSTER":"character.monster.inf","NPC":"character.npc.npc","SPM":"field.spawn.spm","SPP":"field.startpoints.spp","SPC":"field.fixed_npc.spc"}[kind]
    payload=dict(spec.get("payload") or {})
    if kind in {"ITEM","MONSTER","NPC"} and "fields" not in payload:
        payload={"fields":dict(spec.get("fields") or {}),**{k:v for k,v in spec.items() if k in {"dialogs","shops","drops","extra_drops","jobs","random_jobs","unique_color","linked_file"}}}
    return {
        "format":BUNDLE_RECIPE_FORMAT,"id":str(spec.get("id") or pathlib.PurePosixPath(logical).stem),"bundle_type":"CUSTOM",
        "assets":[{"format":RECIPE_FORMAT,"id":"legacy_authoring_asset","contract_id":cid,"target_side":"SERVER","output":logical,"target_policy":"CREATE_NEW","payload":payload}],
        "payload":{},
    }


def stage_authoring(project_root: pathlib.Path, server_root: pathlib.Path, client_root: pathlib.Path | None, spec: dict[str, Any]) -> dict[str, Any]:
    canonical_provider = SummitCanonicalContentProvider.try_from_project(pathlib.Path(project_root))
    if canonical_provider is not None:
        raise ValueError("LEGACY_AUTHORITATIVE_WRITER_DISABLED_IN_CANONICAL_MODE:use canonical authoring")
    kind=str(spec.get("kind") or "").upper(); logical=str(spec.get("path") or spec.get("logical_path") or "")
    rel=_validate_kind_path(kind,logical); mode=str(spec.get("mode") or "EDIT").upper()
    spec = dict(spec)
    spec["kind"] = kind
    spec["mode"] = mode
    spec["path"] = rel.as_posix()
    semantic_binding = semantic_binding_for_spec(kind, spec)
    semantic_related_bindings = semantic_related_bindings_for_spec(kind, spec)
    source=_ci_file(pathlib.Path(server_root),rel.as_posix())
    if mode=="CREATE":
        if source is not None: raise ValueError("LEGACY_AUTHORING_CREATE_TARGET_EXISTS")
        recipe=_create_bundle_recipe(kind,rel.as_posix(),spec)
        manifest=compile_asset_bundle(project_root,recipe,client_root=client_root,server_root=server_root)
        manifest=_attach_semantic_binding(manifest, semantic_binding, semantic_related_bindings)
        return {"format":FORMAT,"status":"STAGED","mode":"CREATE","kind":kind,"manifest":manifest,"spec":spec,"semantic_binding":semantic_binding,"semantic_related_bindings":semantic_related_bindings}
    if mode!="EDIT": raise ValueError("LEGACY_AUTHORING_MODE_INVALID")
    if source is None: raise FileNotFoundError(f"LEGACY_AUTHORING_SOURCE_NOT_FOUND:{rel.as_posix()}")
    raw=source.read_bytes(); expected=str(spec.get("expected_sha256") or "").strip().lower()
    if expected and expected!=_sha_bytes(raw): raise ValueError("LEGACY_AUTHORING_SOURCE_DRIFT")
    patch=spec.get("patch") if isinstance(spec.get("patch"),dict) else spec
    if kind in {"ITEM","MONSTER","NPC"}:
        data,writer=_patch_text(kind,raw,patch)
        if kind == "ITEM":
            parsed = _inspect_text_definition("ITEM", data)
            codes = parsed.get("recognized", {}).get("code") or []
            code = str(codes[0][0]) if codes and codes[0] else ""
            runtime = lookup_item_runtime(code) if code else None
            if not runtime or runtime.get("status") != "SOURCE_VERIFIED":
                raise ValueError(f"ITEM_CODE_NOT_IN_RUNTIME_TABLE:{code}")
            writer["code_identity_status"] = "SOURCE_VERIFIED"
            writer["runtime_item_contract"] = runtime
    elif kind=="SPM": data,writer=_patch_spm(raw,patch)
    elif kind=="SPP": data,writer=_patch_spp(raw,patch)
    else: data,writer=_patch_spc(raw,patch)
    if data==raw: raise ValueError("LEGACY_AUTHORING_NO_CHANGE")
    manifest=_write_patch_bundle(pathlib.Path(project_root),kind,rel,source,data,writer)
    manifest=_attach_semantic_binding(manifest, semantic_binding, semantic_related_bindings)
    return {"format":FORMAT,"status":"STAGED","mode":"EDIT","kind":kind,"manifest":manifest,"spec":spec,"semantic_binding":semantic_binding,"semantic_related_bindings":semantic_related_bindings}


def publish_authoring(project_root: pathlib.Path, client_root: pathlib.Path, server_root: pathlib.Path, manifest: str | pathlib.Path, *, confirm: str) -> dict[str, Any]:
    if SummitCanonicalContentProvider.try_from_project(pathlib.Path(project_root)) is not None:
        raise ValueError("LEGACY_AUTHORITATIVE_PUBLISH_DISABLED_IN_CANONICAL_MODE:use canonical two-phase publish")
    return publish_asset_bundle(project_root,client_root,server_root,manifest,confirm=confirm)


def restore_authoring(project_root: pathlib.Path, client_root: pathlib.Path, server_root: pathlib.Path, manifest: str | pathlib.Path, *, confirm: str) -> dict[str, Any]:
    return restore_asset_bundle(project_root,client_root,server_root,manifest,confirm=confirm)



def authoring_workspace_guide(*, server_root: pathlib.Path | None = None, client_root: pathlib.Path | None = None, project_root: pathlib.Path | None = None) -> dict[str, Any]:
    """User-facing task guide for the Python-native legacy authoring surface.

    This deliberately describes what the current Python writers actually need.
    Historical executables are provenance only and never appear as prerequisites.
    """
    server_ready = bool(server_root is not None and pathlib.Path(server_root).is_dir())
    client_ready = bool(client_root is not None and pathlib.Path(client_root).is_dir())
    canonical_provider = SummitCanonicalContentProvider.try_from_project(pathlib.Path(project_root)) if project_root is not None else None
    canonical_mode = canonical_provider is not None

    def req(key: str, label: str, detail: str, *, required: bool = True, status: str | None = None) -> dict[str, Any]:
        row = {"key": key, "label": label, "detail": detail, "required": required}
        if status is not None:
            row["status"] = status
        return row

    common = [
        req("server_root", "Servidor configurado", "A raiz do servidor precisa apontar para a árvore que contém GameServer/.", status="READY" if server_ready else "MISSING"),
        req("stage_first", "Stage antes de publicar", "Toda alteração é gerada primeiro em pt_build; o target real não é escrito durante o stage."),
        req("publish_gate", "Publicação armada", "Depois de revisar o manifest, a publicação exige ARM ASSET DEPLOY e cria backup/hash/transação."),
        req("runtime_review", "Validação no jogo", "O writer prova formato e transação; comportamento de gameplay ainda precisa ser observado no runtime."),
        req("semantic_catalog", "Catálogo semântico", "Em canonical mode, Summit Content/canonical é autoridade de identidade/campos/paths; o mapa V2.9 é somente overlay de nomes/ambiguidade." if canonical_mode else "A criação/edição pode selecionar nomes visíveis e persistir a identidade canônica (canonical_id), sem colapsar códigos runtime reutilizados."),
    ]
    domains = {
        "ITEM": {
            "title": "Item — criar/editar",
            "summary": "Cria ou edita GameServer/OpenItem/*.txt. Criar aqui significa uma nova definição OpenItem para um código runtime já conhecido.",
            "create_scope": "OPENITEM_FOR_EXISTING_RUNTIME_CODE",
            "hard_block": "Registrar um código sITEM totalmente novo ainda não está implementado/certificado.",
            "path_example": "GameServer/OpenItem/WA121.txt",
            "required_fields": ["name", "code"],
            "requirements": common + [
                req("runtime_code", "Código sITEM existente", "O campo code deve existir no catálogo runtime source-verificado; a identidade de authoring é canonical_id porque um mesmo code pode representar definições distintas."),
                req("semantic_item", "Nome → definição canônica", "Selecione pelo nome visível/canonical_id para preencher OpenItem, code e linked asset sem perder variantes quest/event."),
                req("name", "Nome do item", "Campo Name da definição OpenItem."),
                req("logical_path", "Path OpenItem", "Novo target sob GameServer/OpenItem/ com extensão .txt."),
                req("client_visual", "Ícone / drop model", "Recomendado para closure visual: ItemFilePath/DorpItem devem resolver para os assets esperados no client.", required=False, status="READY" if client_ready else "CLIENT_NOT_CONFIGURED"),
            ],
            "optional": ["stats e requisitos", "jobs / random jobs", "unique color", "linked file"],
        },
        "MONSTER": {
            "title": "Monstro — criar/editar",
            "summary": "Cria ou edita GameServer/Monster/*.inf usando o schema Python source-backed.",
            "path_example": "GameServer/Monster/NewMonster.inf",
            "required_fields": ["name", "model_file"],
            "requirements": common + [
                req("name", "Nome do monstro", "Campo Name da definição Monster; o catálogo mapeia nome visível → definição/modelo canônico."),
                req("model_file", "ModelFile", "Path/config de modelo consumido pelo runtime; precisa existir/ser validado no fluxo client para um monstro completo."),
                req("logical_path", "Path Monster", "Novo target sob GameServer/Monster/ com extensão .inf."),
                req("spawn", "Placement/spawn", "Criar a definição não coloca o monstro no mundo. Em canonical mode, edite stage_spawns JSON; SPM é import/compare only." if canonical_mode else "Criar a definição não coloca o monstro no mundo. Use o SPM do mapa para adicionar actor/boss.", required=False),
            ],
            "optional": ["level/life/stats", "experience", "drops e money drops", "extra drops", "dialogs", "linked file", "race/nature/skills"],
        },
        "NPC": {
            "title": "NPC — criar/editar",
            "summary": "Cria ou edita GameServer/NPC/*.npc. Placement fixo no mapa é uma etapa SPC separada.",
            "path_example": "GameServer/NPC/NewNPC.npc",
            "required_fields": ["name", "model_file"],
            "requirements": common + [
                req("name", "Nome do NPC", "Campo Name da definição NPC; o catálogo mapeia nome visível → definição/modelo canônico."),
                req("model_file", "ModelFile", "Config/modelo usado pelo NPC no client/runtime."),
                req("logical_path", "Path NPC", "Novo target sob GameServer/NPC/ com extensão .npc."),
                req("placement", "Placement fixo", "Em canonical mode, edite fixed_npcs JSON; SPC é import/compare only." if canonical_mode else "Para aparecer fixo em um Field, adicione depois um record em GameServer/Field/*.spc.", required=False),
            ],
            "optional": ["dialogs", "shops weapon/defence/etc", "warehouse", "aging/mix/refining", "teleport/event flags"],
        },
        "MAP": {
            "title": "Mapa / Field — criar/editar",
            "summary": "O Legacy Authoring cobre os arquivos server-side do Field. A geometria Stage do client é outro pipeline.",
            "hard_block": "Esta tela não cria a geometria/Stage visual do mapa; ela edita SPM/SPP/SPC do GameServer/Field.",
            "requirements": common + [
                req("map_catalog", "Mapa → Stage/Field", "O seletor resolve nome do mapa, field_code, stage/spawn e os targets SPM/SPP/SPC. Ex.: Ricarten → village-2."),
                req("spm", "Spawns", "Canonical stage_spawns JSON por monster_id; SPM fica import/read/compare only." if canonical_mode else "Actors, bosses, MAX_ACTOR, MAX_ACTOR_POS e DELAY. Mobs podem ser inseridos pelo catálogo sem digitar o nome interno."),
                req("spp", "Start points", "Canonical stage_start_points JSON por slot/state/x/z; SPP fica import/read/compare only." if canonical_mode else "Arquivo binário canônico de 200 records x 12 bytes; cada record usa state, x e z."),
                req("spc", "NPCs fixos", "Canonical fixed_npcs JSON por npc_id/slot/state/transform; SPC fica import/read/compare only." if canonical_mode else "Arquivo binário canônico de 100 records x 504 bytes; NPCs podem ser escolhidos no catálogo para preencher name/model_ini/server_npc."),
                req("client_stage", "Stage/client geometry", "Valide/crie a parte visual pelo pipeline Stage 0.72, fora do Legacy Authoring.", required=False, status="READY" if client_ready else "CLIENT_NOT_CONFIGURED"),
            ],
            "subtypes": {
                "SPM": {"label": "SPM · Spawns", "path_example": "GameServer/Field/field.spm"},
                "SPP": {"label": "SPP · Start points", "path_example": "GameServer/Field/field.spp"},
                "SPC": {"label": "SPC · NPCs fixos", "path_example": "GameServer/Field/field.spc"},
            },
        },
    }
    semantic = public_authoring_name_catalog()
    return {
        "format": "PT_LEGACY_AUTHORING_WORKSPACE_GUIDE_V2",
        "status": "PASS",
        "semantic_catalog": {
            "format": semantic.get("format"),
            "title": semantic.get("title"),
            "counts": semantic.get("counts"),
            "important_correction": semantic.get("important_correction"),
            "identity_policy": "CANONICAL_ID_PRIMARY_RUNTIME_CODE_SECONDARY",
        },
        "server_root_configured": server_ready,
        "client_root_configured": client_ready,
        "domains": domains,
        "workflow": ["escolher tarefa", "ver requisitos", "inspect/create", "stage", "revisar manifest", "publish", "runtime review", "restore se necessário"],
        "legacy_executable_required": False,
        "canonical_mode": canonical_mode,
        "legacy_authoritative_write": not canonical_mode,
    }

def authoring_capabilities(project_root: pathlib.Path | None = None) -> dict[str, Any]:
    semantic = public_authoring_name_catalog()
    canonical_provider = SummitCanonicalContentProvider.try_from_project(pathlib.Path(project_root)) if project_root is not None else None
    canonical_mode = canonical_provider is not None
    return {
        "format":FORMAT,"status":"PASS",
        "semantic_catalog": {
            "enabled": True,
            "format": semantic.get("format"),
            "counts": semantic.get("counts"),
            "canonical_id_is_primary_authoring_identity": True,
            "runtime_code_may_have_multiple_definitions": True,
            "ambiguous_visible_names_are_not_collapsed": True,
        },
        "kinds":{
            "ITEM":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"runtime_code_boundary":True,"features":["OpenItem fields","jobs","unique color","linked file"],"canonical_replacement":"ITEM" if canonical_mode else None},
            "MONSTER":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"features":["stats","experience","drops","money drops","extra drops","dialogs","linked file"],"canonical_replacement":"MONSTER" if canonical_mode else None},
            "NPC":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"features":["flags","dialogs","shops","linked file"],"canonical_replacement":"NPC" if canonical_mode else None},
            "SPM":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"features":["actors","remove actor","boss actors","remove boss","spawn hours","max actor","delay"],"canonical_replacement":"STAGE_SPAWN" if canonical_mode else None},
            "SPP":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"features":["start point records"],"canonical_replacement":"STAGE_START_POINT" if canonical_mode else None},
            "SPC":{"create":not canonical_mode,"edit":not canonical_mode,"inspect":True,"features":["add","replace","remove fixed NPC records"],"canonical_replacement":"FIXED_NPC" if canonical_mode else None},
        },
        "canonical_mode":canonical_mode,"legacy_authoritative_write":not canonical_mode,
        "publish_confirmation":APPLY_CONFIRM,"restore_confirmation":RESTORE_CONFIRM,
        "legacy_executable_required":False,
        "blocked":["new runtime sITEM code registration","userdata/warehouse mutation","unproved native ItemEditor binary internals"],
    }
