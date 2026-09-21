from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
import time
from typing import Any

from .server_bundle_census import _ci_resolve, _decode_text, _extract_refs, _logical_inx
from .server_field_editor import stage_spc_native
from .server_lifecycle import classify_server_path

FORMAT = "PT_ASSET_NEW_CHARACTER_PIPELINE_V1"
TX_FORMAT = "PT_ASSET_NEW_CHARACTER_TRANSACTION_V1"
ROLES = {"NPC", "MONSTER", "PLAYER_VISUAL"}
APPLY_CONFIRM = "APPLY NEW CHARACTER BUNDLE"
RESTORE_CONFIRM = "RESTORE NEW CHARACTER BUNDLE"
_ALLOWED_CLIENT_PREFIXES = ("char/", "image/", "effect/", "field/", "wav/", "weapons/", "cselect/", "startimage/", "res/", "game/")
_ALLOWED_CLIENT_SUFFIXES = {".ini", ".inx", ".smd", ".smb", ".ase", ".part", ".bmp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".wav", ".ogg", ".mp3", ".mid", ".bgm", ".zif", ".zhoon"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    if not text or text in {".", ".."}:
        raise ValueError("CHARACTER_ID_REQUIRED")
    return text


def _norm_rel(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/").lstrip("/")
    rel = pathlib.PurePosixPath(text)
    if not rel.parts or any(p in {"", ".", ".."} for p in rel.parts):
        raise ValueError(f"INVALID_RELATIVE_PATH:{value}")
    return rel.as_posix()


def _workspace(project_root: pathlib.Path, character_id: str) -> pathlib.Path:
    root = pathlib.Path(project_root).resolve() / "pt_build" / "new_character" / _safe_id(character_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _default_definition(role: str, character_id: str, donor_definition: str | None = None, server_root: pathlib.Path | None = None) -> str | None:
    cid = _safe_id(character_id)
    if role == "NPC":
        # The source snapshot proves the character-config grammar, while deployed
        # server corpora may use either .npc or .inf for NPC definitions. Prefer the
        # donor suffix, then the dominant live convention, instead of hardcoding one.
        if donor_definition:
            suffix = pathlib.PurePosixPath(str(donor_definition)).suffix.casefold()
            if suffix in {".npc", ".inf"}:
                return f"GameServer/NPC/{cid}{suffix}"
        if server_root is not None:
            npc_dir = pathlib.Path(server_root) / "GameServer" / "NPC"
            counts = {ext: 0 for ext in (".npc", ".inf")}
            if npc_dir.is_dir():
                for item in npc_dir.rglob("*"):
                    if item.is_file() and item.suffix.casefold() in counts:
                        counts[item.suffix.casefold()] += 1
            if counts[".inf"] > counts[".npc"]:
                return f"GameServer/NPC/{cid}.inf"
        return f"GameServer/NPC/{cid}.npc"
    if role == "MONSTER":
        return f"GameServer/Monster/{cid}.inf"
    return None


def _client_overlay_contains(overlay: pathlib.Path | None, rel: str) -> pathlib.Path | None:
    if overlay is None:
        return None
    p = overlay / pathlib.PurePosixPath(rel)
    return p if p.is_file() else None


def _model_resolution(client_root: pathlib.Path, server_root: pathlib.Path | None, client_overlay: pathlib.Path | None, model_ref: str) -> dict[str, Any]:
    logical = _norm_rel(model_ref)
    inx = _logical_inx(logical)
    candidates = [logical]
    if inx and inx.casefold() != logical.casefold():
        candidates.append(inx)
    hits: list[dict[str, str]] = []
    for rel in candidates:
        op = _client_overlay_contains(client_overlay, rel)
        if op:
            hits.append({"root": "CLIENT_OVERLAY", "path": str(op), "logical": rel})
        cp = _ci_resolve(client_root, rel, want_dir=False)
        if cp:
            hits.append({"root": "CLIENT", "path": str(cp), "logical": rel})
        if server_root is not None:
            sp = _ci_resolve(server_root, rel, want_dir=False)
            if sp:
                hits.append({"root": "SERVER", "path": str(sp), "logical": rel})
    return {"reference": logical, "logical_inx": inx, "resolved": bool(hits), "hits": hits}


def _character_config_directive(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("//"):
        return None
    # The source parser accepts CP949 Korean tokens plus Brazilian aliases for
    # name/chat.  Keep matching deliberately narrow so unrelated lines are not
    # rewritten just because they contain a familiar filename.
    token = stripped.split(None, 1)[0]
    rest = stripped[len(token):].strip()
    mapping = {
        "*j_name": "NAME",
        "*이름": "NAME",
        "*모양파일": "MODEL_FILE",
        "*공격속도": "ATTACK_SPEED",
    }
    kind = mapping.get(token.casefold())
    return (kind, rest) if kind else None


def _first_config_value(rest: str) -> str | None:
    text = str(rest or "").strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end >= 1 else None
    return text.split(None, 1)[0]


def _analyze_character_definition(data: bytes) -> dict[str, Any]:
    text, encoding = _decode_text(data)
    names: list[str] = []
    models: list[str] = []
    attacks: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        parsed = _character_config_directive(line)
        if not parsed:
            continue
        kind, rest = parsed
        if kind == "NAME":
            value = _first_config_value(rest)
            if value: names.append(value)
            else: errors.append(f"NAME_VALUE_MISSING:{line_no}")
        elif kind == "MODEL_FILE":
            value = _first_config_value(rest)
            if value: models.append(value.replace("\\", "/"))
            else: errors.append(f"MODEL_FILE_VALUE_MISSING:{line_no}")
        elif kind == "ATTACK_SPEED":
            values = re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)', rest)
            valid = len(values) >= 2
            attacks.append({"line": line_no, "values": values[:2], "valid_two_value_contract": valid})
            if not valid:
                errors.append(f"ATTACK_SPEED_REQUIRES_TWO_FLOATS:{line_no}")
    return {
        "encoding": encoding,
        "name_values": names,
        "effective_name": names[-1] if names else None,
        "model_file_values": models,
        "effective_model_file": models[-1] if models else None,
        "attack_speed_directives": attacks,
        "errors": errors,
        "status": "PASS" if not errors and bool(names) and bool(models) else "BLOCKED",
    }


def _replace_directive_value(line: str, new_value: str) -> str:
    lead = line[: len(line) - len(line.lstrip())]
    stripped = line.strip()
    token = stripped.split(None, 1)[0]
    return f'{lead}{token} "{new_value}"'


def _patch_definition(data: bytes, display_name: str, model_ini: str) -> tuple[bytes, dict[str, Any]]:
    text, encoding = _decode_text(data)
    newline = "\r\n" if "\r\n" in text else "\n"
    had_terminal_newline = text.endswith(("\n", "\r"))
    name_changed = False
    model_changed = False
    out_lines: list[str] = []
    for line in text.splitlines():
        parsed = _character_config_directive(line)
        if parsed:
            kind, _rest = parsed
            if kind == "NAME" and not name_changed:
                line = _replace_directive_value(line, display_name)
                name_changed = True
            elif kind == "MODEL_FILE" and not model_changed:
                replacement = model_ini.replace("/", "\\")
                line = _replace_directive_value(line, replacement)
                model_changed = True
        out_lines.append(line)
    text = newline.join(out_lines) + (newline if had_terminal_newline else "")
    try:
        encoded = text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"DEFINITION_TEXT_NOT_ENCODABLE:{encoding}:{exc}") from exc
    analysis = _analyze_character_definition(encoded)
    expected_model = _norm_rel(model_ini).casefold()
    actual_model = str(analysis.get("effective_model_file") or "").replace("\\", "/").lstrip("/").casefold()
    roundtrip_ok = (
        name_changed
        and model_changed
        and str(analysis.get("effective_name") or "") == str(display_name)
        and actual_model == expected_model
        and analysis.get("status") == "PASS"
    )
    refs = _extract_refs(text)
    return encoded, {
        "encoding": encoding,
        "name_directive_updated": name_changed,
        "model_reference_updated": model_changed,
        "definition_analysis": analysis,
        "identity_roundtrip_ok": roundtrip_ok,
        "zhoon_references": [r for r in refs if pathlib.PurePosixPath(r).suffix.casefold() == ".zhoon"],
    }


def _model_cache_freshness(client_root: pathlib.Path, overlay: pathlib.Path | None, model_ini: str) -> dict[str, Any]:
    logical = _norm_rel(model_ini)
    suffix = pathlib.PurePosixPath(logical).suffix.casefold()
    if suffix == ".inx":
        return {"status": "PASS", "policy": "DIRECT_INX_REFERENCE", "source": logical, "cache": logical}
    if suffix not in {".ini", ".inf"}:
        return {"status": "PASS", "policy": "NO_INX_CONTRACT", "source": logical, "cache": None}
    cache = _logical_inx(logical)
    if not cache or cache.casefold() == logical.casefold():
        return {"status": "PASS", "policy": "NO_SEPARATE_INX", "source": logical, "cache": cache}
    overlay_source = _client_overlay_contains(overlay, logical)
    overlay_cache = _client_overlay_contains(overlay, cache)
    live_cache = _ci_resolve(client_root, cache, want_dir=False)
    if overlay_source and overlay_cache:
        return {"status": "BLOCKED", "policy": "CACHE_FRESHNESS_UNPROVEN", "source": logical, "cache": cache, "reason": "overlay contains changed model config and INX; regenerate/certify INX instead of carrying an opaque stale cache"}
    if overlay_source and live_cache:
        return {"status": "BLOCKED", "policy": "LIVE_STALE_CACHE_COLLISION", "source": logical, "cache": cache, "live_cache": str(live_cache), "reason": "new model config would coexist with an old INX at the same logical identity"}
    return {"status": "PASS", "policy": "NO_STALE_CACHE_COLLISION", "source": logical, "cache": cache, "overlay_source": bool(overlay_source), "overlay_cache": bool(overlay_cache), "live_cache": str(live_cache) if live_cache else None}


def _stage_monster_spm(server_root: pathlib.Path, source_rel: str, display_name: str, weight: int) -> tuple[bytes, dict[str, Any]]:
    source = _ci_resolve(server_root, source_rel, want_dir=False)
    if source is None:
        raise FileNotFoundError(source_rel)
    raw = source.read_bytes()
    text, encoding = _decode_text(raw)
    newline = "\r\n" if "\r\n" in text else "\n"
    actor_line = f'*ACTOR "{display_name}" {int(weight)}'
    lines = text.splitlines()
    if any(display_name.casefold() in x.casefold() and x.strip().upper().startswith("*ACTOR") for x in lines):
        raise ValueError("SPM_ACTOR_ALREADY_PRESENT")
    last_actor = -1
    for i, line in enumerate(lines):
        head = line.strip().split(None, 1)[0].upper() if line.strip() else ""
        if head in {"*ACTOR", "*BOSS_ACTOR", "*출연자", "*출연자두목"}:
            last_actor = i
    insert_at = last_actor + 1 if last_actor >= 0 else len(lines)
    lines.insert(insert_at, actor_line)
    out = newline.join(lines)
    if text.endswith(("\n", "\r")):
        out += newline
    try:
        data = out.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"SPM_TEXT_NOT_ENCODABLE:{encoding}:{exc}") from exc
    return data, {"encoding": encoding, "inserted_line": actor_line, "insert_index": insert_at}


def _copy_client_overlay(source_root: pathlib.Path, dest_root: pathlib.Path) -> list[dict[str, Any]]:
    source_root = pathlib.Path(source_root).resolve()
    if not source_root.is_dir():
        raise ValueError(f"CLIENT_OVERLAY_NOT_DIRECTORY:{source_root}")
    files: list[dict[str, Any]] = []
    for p in sorted(source_root.rglob("*"), key=lambda x: x.as_posix().casefold()):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(source_root).as_posix()
        low = rel.casefold()
        suffix = p.suffix.casefold()
        if not low.startswith(_ALLOWED_CLIENT_PREFIXES) or suffix not in _ALLOWED_CLIENT_SUFFIXES:
            raise ValueError(f"CLIENT_OVERLAY_PATH_NOT_ALLOWED:{rel}")
        target = dest_root / pathlib.PurePosixPath(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        files.append({"side": "CLIENT", "path": rel, "source": str(p), "staged": str(target), "sha256": _sha256_file(target), "size": target.stat().st_size})
    return files


def plan_new_character(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
    *,
    role: str,
    character_id: str,
    display_name: str,
    model_ini: str,
    donor_definition: str | None = None,
    target_definition: str | None = None,
    field_path: str | None = None,
    client_overlay: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    role = str(role or "").strip().upper()
    if role not in ROLES:
        raise ValueError(f"UNSUPPORTED_CHARACTER_ROLE:{role}")
    cid = _safe_id(character_id)
    if not str(display_name or "").strip():
        raise ValueError("DISPLAY_NAME_REQUIRED")
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    overlay = pathlib.Path(client_overlay).expanduser().resolve() if client_overlay else None
    model = _model_resolution(client_root, server, overlay, model_ini)
    donor_def = _norm_rel(donor_definition) if donor_definition else None
    target_def = _norm_rel(target_definition) if target_definition else _default_definition(role, cid, donor_def, server)
    field = _norm_rel(field_path) if field_path else None

    checks: list[dict[str, Any]] = []
    checks.append({"check": "MODEL_PACKAGE_RESOLUTION", "status": "PASS" if model["resolved"] else "BLOCKED", "detail": model})
    freshness = _model_cache_freshness(client_root, overlay, model_ini)
    checks.append({"check": "MODEL_CACHE_FRESHNESS", "status": freshness["status"], "detail": freshness})
    if role in {"NPC", "MONSTER"}:
        if server is None or not server.is_dir():
            checks.append({"check": "SERVER_ROOT", "status": "BLOCKED", "detail": "server root required"})
        if not donor_def:
            checks.append({"check": "DONOR_DEFINITION", "status": "BLOCKED", "detail": "donor definition required for file-based behavior/template"})
        else:
            donor_hit = _ci_resolve(server, donor_def, want_dir=False) if server else None
            checks.append({"check": "DONOR_DEFINITION", "status": "PASS" if donor_hit else "BLOCKED", "detail": str(donor_hit) if donor_hit else donor_def})
        existing = _ci_resolve(server, target_def, want_dir=False) if (server and target_def) else None
        checks.append({"check": "TARGET_IDENTITY_FREE", "status": "PASS" if not existing else "BLOCKED", "detail": str(existing) if existing else target_def})
        expected_suffix = ".spc" if role == "NPC" else ".spm"
        if not field:
            checks.append({"check": "PLACEMENT_FIELD", "status": "BLOCKED", "detail": f"{expected_suffix} field path required to add entity to game"})
        else:
            hit = _ci_resolve(server, field, want_dir=False) if server else None
            status = "PASS" if hit and pathlib.PurePosixPath(field).suffix.casefold() == expected_suffix else "BLOCKED"
            checks.append({"check": "PLACEMENT_FIELD", "status": status, "detail": str(hit) if hit else field})
    else:
        checks.append({"check": "PLAYER_CODE_BOUNDARY", "status": "REVIEW", "detail": "visual/assets can be staged; class/job registration, select-slot, stats/skills/network remain code-owned"})

    blockers = [x for x in checks if x["status"] == "BLOCKED"]
    return {
        "format": FORMAT,
        "action": "PLAN",
        "status": "BLOCKED" if blockers else "PASS",
        "role": role,
        "character_id": cid,
        "display_name": str(display_name),
        "model_ini": _norm_rel(model_ini),
        "donor_definition": donor_def,
        "target_definition": target_def,
        "field_path": field,
        "client_overlay": str(overlay) if overlay else None,
        "checks": checks,
        "blocker_count": len(blockers),
        "code_boundary": [
            "player class/job enum and creation/select flow",
            "base stats/skills/progression",
            "network/runtime protocol fields",
            "hardcoded gameplay behavior not represented by donor definition/config",
        ] if role == "PLAYER_VISUAL" else [
            "new bespoke AI/quest/shop/gameplay behavior beyond file-based donor semantics",
        ],
        "production_authorized": False,
    }


def stage_new_character(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
    *,
    role: str,
    character_id: str,
    display_name: str,
    model_ini: str,
    donor_definition: str | None = None,
    target_definition: str | None = None,
    field_path: str | None = None,
    client_overlay: str | pathlib.Path | None = None,
    x: int = 0,
    y: int = 0,
    z: int = 0,
    ax: int = 0,
    ay: int = 0,
    az: int = 0,
    state: int = 0,
    actor_weight: int = 100,
    template_index: int | None = None,
    slot_index: int | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    plan = plan_new_character(
        project_root, client_root, server,
        role=role, character_id=character_id, display_name=display_name, model_ini=model_ini,
        donor_definition=donor_definition, target_definition=target_definition, field_path=field_path,
        client_overlay=client_overlay,
    )
    if plan["status"] == "BLOCKED":
        raise ValueError("NEW_CHARACTER_PLAN_BLOCKED:" + ",".join(x["check"] for x in plan["checks"] if x["status"] == "BLOCKED"))

    cid = plan["character_id"]
    role = plan["role"]
    ws = _workspace(project_root, cid)
    # Replace the previous draft atomically at directory granularity.
    draft = ws / "draft"
    if draft.exists():
        shutil.rmtree(draft)
    client_out = draft / "client"
    server_out = draft / "server"
    client_out.mkdir(parents=True, exist_ok=True)
    server_out.mkdir(parents=True, exist_ok=True)
    staged_files: list[dict[str, Any]] = []
    stage_notes: list[str] = []

    if client_overlay:
        staged_files.extend(_copy_client_overlay(pathlib.Path(client_overlay).expanduser(), client_out))

    if role in {"NPC", "MONSTER"}:
        assert server is not None
        donor_rel = str(plan["donor_definition"])
        donor = _ci_resolve(server, donor_rel, want_dir=False)
        if donor is None:
            raise FileNotFoundError(donor_rel)
        patched, patch_detail = _patch_definition(donor.read_bytes(), str(display_name), str(plan["model_ini"]))
        target_def = str(plan["target_definition"])
        target = server_out / pathlib.PurePosixPath(target_def)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched)
        staged_files.append({"side": "SERVER", "path": target_def, "source": str(donor), "staged": str(target), "sha256": _sha256_file(target), "size": target.stat().st_size, "operation": "CLONE_PATCH_DEFINITION", "detail": patch_detail})
        if not patch_detail.get("identity_roundtrip_ok"):
            raise ValueError("DEFINITION_ROUNDTRIP_CONTRACT_FAILED:" + "|".join((patch_detail.get("definition_analysis") or {}).get("errors") or ["identity/model mismatch"]))
        if patch_detail.get("zhoon_references"):
            stage_notes.append("DONOR_ZHOON_LOCALIZATION_REUSED_REVIEW")

        field_rel = str(plan["field_path"])
        if role == "NPC":
            field_draft = stage_spc_native(
                project_root, server, field_rel,
                slot_index=slot_index,
                record_name=str(display_name), model_ini=str(plan["model_ini"]), server_npc=target_def,
                x=int(x), y=int(y), z=int(z), ax=int(ax), ay=int(ay), az=int(az), state=int(state),
            )
            src = pathlib.Path(field_draft["draft"])
            out = server_out / pathlib.PurePosixPath(field_rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            staged_files.append({"side": "SERVER", "path": field_rel, "source": field_draft["source"], "staged": str(out), "sha256": _sha256_file(out), "size": out.stat().st_size, "operation": "SPC_NATIVE_ABI_INSERT", "detail": field_draft.get("detail") or {}})
        else:
            effective_name = str((patch_detail.get("definition_analysis") or {}).get("effective_name") or "")
            if effective_name != str(display_name):
                raise ValueError("MONSTER_EFFECTIVE_IDENTITY_MISMATCH")
            spm_data, spm_detail = _stage_monster_spm(server, field_rel, effective_name, int(actor_weight))
            out = server_out / pathlib.PurePosixPath(field_rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(spm_data)
            staged_files.append({"side": "SERVER", "path": field_rel, "source": str(_ci_resolve(server, field_rel, want_dir=False)), "staged": str(out), "sha256": _sha256_file(out), "size": out.stat().st_size, "operation": "SPM_ADD_ACTOR", "detail": spm_detail})

    manifest = {
        **plan,
        "action": "STAGE",
        "status": "PASS",
        "stage_status": "READY_FOR_ASSET_TEST_ONLY" if role == "PLAYER_VISUAL" else "READY_FOR_PUBLISH",
        "workspace": str(ws),
        "draft_root": str(draft),
        "staged_files": staged_files,
        "staged_file_count": len(staged_files),
        "stage_notes": stage_notes,
        "runtime_review_required": True,
        "server_write_authorized": False,
        "client_write_authorized": False,
        "production_authorized": False,
        "created_at": time.time(),
    }
    manifest_path = ws / "manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _load_manifest(project_root: pathlib.Path, character_id: str) -> tuple[pathlib.Path, dict[str, Any]]:
    path = _workspace(project_root, character_id) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"NEW_CHARACTER_MANIFEST_NOT_FOUND:{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("NEW_CHARACTER_MANIFEST_INVALID")
    return path, data


def _validate_publish_path(side: str, rel: str) -> None:
    rel = _norm_rel(rel)
    low = rel.casefold()
    if side == "CLIENT":
        if not low.startswith(_ALLOWED_CLIENT_PREFIXES) or pathlib.PurePosixPath(rel).suffix.casefold() not in _ALLOWED_CLIENT_SUFFIXES:
            raise ValueError(f"CLIENT_PUBLISH_PATH_NOT_ALLOWED:{rel}")
        return
    c = classify_server_path(rel)
    if c.write_policy in {"BLOCKED_PERSISTENCE", "BLOCKED_STATE", "BLOCKED_RUNTIME_INTEGRITY", "FORENSICS_ONLY", "EXCLUDED_TOOLING"}:
        raise ValueError(f"SERVER_PUBLISH_PATH_BLOCKED:{rel}:{c.write_policy}")
    allowed = (
        low.startswith("gameserver/monster/") and low.endswith(".inf")
        or low.startswith("gameserver/npc/") and pathlib.PurePosixPath(low).suffix in {".npc", ".inf"}
        or low.startswith("gameserver/field/") and pathlib.PurePosixPath(low).suffix in {".spm", ".spp", ".spc"}
        or "/name/" in low and low.endswith(".zhoon")
    )
    if not allowed:
        raise ValueError(f"SERVER_PUBLISH_PATH_NOT_WHITELISTED:{rel}")


def _atomic_copy(source: pathlib.Path, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def publish_new_character(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
    character_id: str,
    *,
    confirm: str,
) -> dict[str, Any]:
    if confirm != APPLY_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{APPLY_CONFIRM}")
    project_root = pathlib.Path(project_root).resolve()
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    _manifest_path, manifest = _load_manifest(project_root, character_id)
    if manifest.get("stage_status") not in {"READY_FOR_PUBLISH", "READY_FOR_ASSET_TEST_ONLY"}:
        raise ValueError("NEW_CHARACTER_STAGE_NOT_PUBLISHABLE")
    files = list(manifest.get("staged_files") or [])
    if not files:
        raise ValueError("NEW_CHARACTER_NO_STAGED_FILES")
    if any(str(x.get("side")) == "SERVER" for x in files) and (server is None or not server.is_dir()):
        raise ValueError("SERVER_ROOT_REQUIRED_FOR_PUBLISH")

    ws = _workspace(project_root, character_id)
    tx_root = ws / "transactions" / (time.strftime("%Y%m%d_%H%M%S") + "_" + hashlib.sha1(os.urandom(16)).hexdigest()[:8])
    backup_root = tx_root / "backup"
    tx_root.mkdir(parents=True, exist_ok=True)
    tx_files: list[dict[str, Any]] = []

    # Preflight every path/hash before first write.
    for row in files:
        side = str(row.get("side") or "").upper()
        rel = _norm_rel(str(row.get("path") or ""))
        _validate_publish_path(side, rel)
        staged = pathlib.Path(str(row.get("staged") or ""))
        if not staged.is_file():
            raise FileNotFoundError(f"STAGED_FILE_NOT_FOUND:{staged}")
        sha = _sha256_file(staged)
        if row.get("sha256") and sha != row.get("sha256"):
            raise ValueError(f"STAGED_FILE_DRIFT:{rel}")
        root = client_root if side == "CLIENT" else server
        assert root is not None
        target = root / pathlib.PurePosixPath(rel)
        tx_files.append({
            "side": side, "path": rel, "staged": str(staged), "staged_sha256": sha,
            "target": str(target), "target_existed": target.is_file(),
            "original_sha256": _sha256_file(target) if target.is_file() else None,
        })

    applied: list[dict[str, Any]] = []
    try:
        for row in tx_files:
            target = pathlib.Path(row["target"])
            if row["target_existed"]:
                backup = backup_root / row["side"].lower() / pathlib.PurePosixPath(row["path"])
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                row["backup"] = str(backup)
                row["backup_sha256"] = _sha256_file(backup)
            else:
                row["backup"] = None
                row["backup_sha256"] = None
            _atomic_copy(pathlib.Path(row["staged"]), target)
            actual = _sha256_file(target)
            if actual != row["staged_sha256"]:
                raise RuntimeError(f"POST_WRITE_HASH_MISMATCH:{row['path']}")
            row["deployed_sha256"] = actual
            applied.append(row)
    except Exception:
        for row in reversed(applied):
            target = pathlib.Path(row["target"])
            if row.get("backup"):
                _atomic_copy(pathlib.Path(row["backup"]), target)
            elif target.exists():
                target.unlink()
        raise

    tx = {
        "format": TX_FORMAT,
        "state": "APPLIED_VERIFIED",
        "character_id": manifest.get("character_id"),
        "role": manifest.get("role"),
        "display_name": manifest.get("display_name"),
        "manifest": manifest.get("manifest"),
        "files": tx_files,
        "file_count": len(tx_files),
        "runtime_review_required": True,
        "code_boundary": manifest.get("code_boundary") or [],
        "created_at": time.time(),
        "client_modified": any(x["side"] == "CLIENT" for x in tx_files),
        "server_modified": any(x["side"] == "SERVER" for x in tx_files),
        "production_authorized": False,
    }
    tx_path = tx_root / "transaction.json"
    tx["transaction_manifest"] = str(tx_path)
    tx_path.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ws / "latest_transaction.txt").write_text(str(tx_path) + "\n", encoding="utf-8")
    return tx


def _latest_tx(project_root: pathlib.Path, character_id: str) -> tuple[pathlib.Path, dict[str, Any]]:
    ws = _workspace(project_root, character_id)
    marker = ws / "latest_transaction.txt"
    if not marker.is_file():
        raise FileNotFoundError("NEW_CHARACTER_TRANSACTION_NOT_FOUND")
    path = pathlib.Path(marker.read_text(encoding="utf-8").strip())
    if not path.is_file():
        raise FileNotFoundError(f"NEW_CHARACTER_TRANSACTION_NOT_FOUND:{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != TX_FORMAT:
        raise ValueError("NEW_CHARACTER_TRANSACTION_INVALID")
    return path, data


def restore_new_character(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path | None,
    character_id: str,
    *,
    confirm: str,
) -> dict[str, Any]:
    if confirm != RESTORE_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{RESTORE_CONFIRM}")
    client_root = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve() if server_root is not None else None
    tx_path, tx = _latest_tx(project_root, character_id)
    if tx.get("state") != "APPLIED_VERIFIED":
        raise ValueError(f"NEW_CHARACTER_TRANSACTION_NOT_ACTIVE:{tx.get('state')}")
    files = list(tx.get("files") or [])

    # Full drift preflight before touching either root.
    for row in files:
        root = client_root if row.get("side") == "CLIENT" else server
        if root is None:
            raise ValueError("SERVER_ROOT_REQUIRED_FOR_RESTORE")
        target = root / pathlib.PurePosixPath(str(row.get("path") or ""))
        if not target.is_file():
            raise ValueError(f"RESTORE_DRIFT_TARGET_MISSING:{row.get('path')}")
        if _sha256_file(target) != row.get("deployed_sha256"):
            raise ValueError(f"RESTORE_DRIFT_DETECTED:{row.get('path')}")
        if row.get("backup"):
            backup = pathlib.Path(row["backup"])
            if not backup.is_file() or _sha256_file(backup) != row.get("backup_sha256"):
                raise ValueError(f"RESTORE_BACKUP_INVALID:{row.get('path')}")

    for row in reversed(files):
        root = client_root if row.get("side") == "CLIENT" else server
        assert root is not None
        target = root / pathlib.PurePosixPath(str(row.get("path") or ""))
        if row.get("backup"):
            _atomic_copy(pathlib.Path(row["backup"]), target)
            if _sha256_file(target) != row.get("original_sha256"):
                raise RuntimeError(f"RESTORE_VERIFY_FAILED:{row.get('path')}")
        else:
            target.unlink()

    tx["state"] = "RESTORED_VERIFIED"
    tx["restored_at"] = time.time()
    tx["client_modified"] = any(x.get("side") == "CLIENT" for x in files)
    tx["server_modified"] = any(x.get("side") == "SERVER" for x in files)
    tx_path.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tx


def new_character_status(project_root: pathlib.Path, character_id: str) -> dict[str, Any]:
    ws = _workspace(project_root, character_id)
    manifest = None
    tx = None
    mp = ws / "manifest.json"
    if mp.is_file():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            manifest = {"status": "INVALID_MANIFEST", "manifest": str(mp)}
    try:
        _p, tx = _latest_tx(project_root, character_id)
    except Exception:
        tx = None
    return {
        "format": FORMAT,
        "action": "STATUS",
        "character_id": _safe_id(character_id),
        "workspace": str(ws),
        "manifest": manifest,
        "latest_transaction": tx,
        "can_publish": bool(manifest and manifest.get("stage_status") in {"READY_FOR_PUBLISH", "READY_FOR_ASSET_TEST_ONLY"} and (not tx or tx.get("state") != "APPLIED_VERIFIED")),
        "can_restore": bool(tx and tx.get("state") == "APPLIED_VERIFIED"),
    }
