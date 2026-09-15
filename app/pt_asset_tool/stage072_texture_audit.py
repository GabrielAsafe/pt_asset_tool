from __future__ import annotations

import json
import pathlib
import zipfile

from .stage072_corpus import parse_stage072
from .utils import norm_path


def _candidate_rows(records: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for r in records:
        if str(r.get("kind") or "") != "SMD_STAGE_072":
            continue
        rel = norm_path(r.get("relative_path") or r.get("path") or "")
        if not rel:
            continue
        key = rel.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"relative_path": rel, "record": r})
    rows.sort(key=lambda x: x["relative_path"].lower())
    return rows


def _used_material_texture_refs(parsed: dict) -> list[dict]:
    """Return serialized textures belonging to face-referenced materials.

    This is intentionally source-faithful. Both base and animated texture names
    are retained because SMTEX_TYPE_ANIMATION reads smAnimTexture[] at runtime,
    while MULTIMIX reads smTexture[]. Historical materials unused by any face
    remain outside this gate.
    """
    used_ids = {
        int(mid) for mid, count in (parsed.get("material_face_counts") or {}).items()
        if int(count or 0) > 0
    }
    refs = []
    for mat in parsed.get("materials") or []:
        mid = int(mat.get("id") or 0)
        if mid not in used_ids:
            continue
        face_uses = int((parsed.get("material_face_counts") or {}).get(str(mid)) or 0)
        for kind, rows in (
            ("BASE", list(mat.get("textures") or [])),
            ("ANIM", list(mat.get("anim_textures") or [])),
        ):
            for slot, row in enumerate(rows):
                logical = norm_path(row.get("Name") or "")
                if not logical:
                    continue
                refs.append({
                    "material_id": mid,
                    "face_uses": face_uses,
                    "kind": kind,
                    "slot": slot,
                    "logical": logical,
                    "texture_type": int(mat.get("TextureType") or 0),
                })
    return refs


def runtime_trailing_space_alias(logical: str) -> str | None:
    """Return the narrow Win32-compat candidate used by V0.6.2.

    Only trailing ASCII spaces in the *final filename component* are removed.
    No basename guessing, directory relocation, extension guessing, or general
    whitespace stripping is allowed.
    """
    logical = norm_path(logical)
    if not logical or "/" not in logical:
        base = logical
        prefix = ""
    else:
        prefix, base = logical.rsplit("/", 1)
        prefix += "/"
    trimmed = base.rstrip(" ")
    if trimmed == base or not trimmed:
        return None
    return prefix + trimmed


def serialized_reference_shape(logical: str) -> str:
    logical = norm_path(logical)
    base = logical.rsplit("/", 1)[-1] if logical else ""
    if not base:
        return "SERIALIZED_DIRECTORY_ONLY"
    # 0xCC is the classic MSVC debug-fill byte and occurs literally in three
    # physical Stage0.72 texture strings in this corpus. Treat the evidence as
    # an invalid serialized filename, not as a filename that should be guessed.
    if any(ord(ch) == 0xCC for ch in logical):
        return "SERIALIZED_MSVC_DEBUG_FILL_0XCC"
    if runtime_trailing_space_alias(logical):
        return "SERIALIZED_TRAILING_ASCII_SPACE"
    return "FILE_LIKE_REFERENCE"


def _resolve_or_none(resolver, logical: str):
    try:
        return resolver.resolve(logical), None
    except FileNotFoundError as exc:
        return None, exc


def audit_stage072_texture_presence(records: list[dict], resolver, *, bundle: str | None = None) -> dict:
    candidates = _candidate_rows(records)
    rows = []
    scan_errors = []
    unique_refs: dict[str, dict] = {}

    # Build once so collision semantics remain identical to normal client
    # resolution, including exact-case preference and case-collision guards.
    _ = resolver.index

    for item in candidates:
        rel = item["relative_path"]
        try:
            source = resolver.resolve(rel)
            parsed = parse_stage072(source)
            if parsed.get("full_parse") != "PASS":
                raise RuntimeError("Stage0.72 source parser did not pass")
            refs = _used_material_texture_refs(parsed)
            file_exact_missing = []
            file_runtime_alias = []
            file_invalid = []
            file_client_missing = []
            exact_present = 0

            for ref in refs:
                logical = ref["logical"]
                key = logical.lower()
                agg = unique_refs.setdefault(key, {
                    "logical": logical,
                    "exact_present": False,
                    "runtime_present": False,
                    "classification": None,
                    "shape": serialized_reference_shape(logical),
                    "runtime_alias": None,
                    "files": set(),
                    "materials": set(),
                    "slots": set(),
                    "face_uses_sum": 0,
                    "resolved_paths": set(),
                    "runtime_alias_resolved_paths": set(),
                })
                agg["files"].add(rel)
                agg["materials"].add((rel, int(ref["material_id"])))
                agg["slots"].add((ref["kind"], int(ref["slot"])))
                agg["face_uses_sum"] += int(ref["face_uses"])

                try:
                    physical = resolver.resolve(logical)
                except FileNotFoundError:
                    shape = serialized_reference_shape(logical)
                    alias = runtime_trailing_space_alias(logical)
                    if alias:
                        try:
                            alias_physical = resolver.resolve(alias)
                        except FileNotFoundError:
                            classification = "CLIENT_FILE_MISSING_TRAILING_SPACE_REFERENCE"
                            agg["runtime_alias"] = alias
                            file_client_missing.append({**ref, "classification": classification, "runtime_alias": alias})
                        except Exception as exc:
                            raise RuntimeError(
                                f"texture runtime-alias resolver error for {logical} -> {alias}: "
                                f"{type(exc).__name__}: {exc}"
                            ) from exc
                        else:
                            classification = "RUNTIME_TRAILING_SPACE_ALIAS_PRESENT"
                            agg["runtime_alias"] = alias
                            agg["runtime_present"] = True
                            agg["runtime_alias_resolved_paths"].add(str(alias_physical))
                            file_runtime_alias.append({**ref, "classification": classification, "runtime_alias": alias, "resolved": str(alias_physical)})
                    elif shape in {"SERIALIZED_DIRECTORY_ONLY", "SERIALIZED_MSVC_DEBUG_FILL_0XCC"}:
                        classification = shape
                        file_invalid.append({**ref, "classification": classification})
                    else:
                        classification = "CLIENT_FILE_MISSING"
                        file_client_missing.append({**ref, "classification": classification})
                    agg["classification"] = classification
                    file_exact_missing.append({**ref, "classification": classification, "runtime_alias": agg.get("runtime_alias")})
                except Exception as exc:
                    # Case collisions and other resolver failures are not the
                    # same as an absent shipped file; keep them hard-fail.
                    raise RuntimeError(
                        f"texture resolver error for {logical}: {type(exc).__name__}: {exc}"
                    ) from exc
                else:
                    exact_present += 1
                    agg["exact_present"] = True
                    agg["runtime_present"] = True
                    agg["classification"] = "EXACT_CLIENT_FILE_PRESENT"
                    agg["resolved_paths"].add(str(physical))

            rows.append({
                "relative_path": rel,
                "texture_reference_occurrences": len(refs),
                "exact_present_reference_occurrences": exact_present,
                "exact_missing_reference_occurrences": len(file_exact_missing),
                "runtime_alias_reference_occurrences": len(file_runtime_alias),
                "serialized_invalid_reference_occurrences": len(file_invalid),
                "client_missing_reference_occurrences": len(file_client_missing),
                "exact_missing_references": file_exact_missing,
                "runtime_alias_references": file_runtime_alias,
                "serialized_invalid_references": file_invalid,
                "client_missing_references": file_client_missing,
            })
        except Exception as exc:
            scan_errors.append({"relative_path": rel, "error": f"{type(exc).__name__}: {exc}"})
            rows.append({"relative_path": rel, "scan": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

    unique_rows = []
    for _key, agg in sorted(unique_refs.items()):
        unique_rows.append({
            "logical": agg["logical"],
            "exact_present": bool(agg["exact_present"]),
            "runtime_present": bool(agg["runtime_present"]),
            "classification": agg["classification"],
            "shape": agg["shape"],
            "runtime_alias": agg["runtime_alias"],
            "files": sorted(agg["files"], key=str.lower),
            "materials": [
                {"file": f, "material_id": mid}
                for f, mid in sorted(agg["materials"], key=lambda x: (x[0].lower(), x[1]))
            ],
            "slots": [
                {"kind": kind, "slot": slot}
                for kind, slot in sorted(agg["slots"], key=lambda x: (x[0], x[1]))
            ],
            "face_uses_sum": int(agg["face_uses_sum"]),
            "resolved_paths": sorted(agg["resolved_paths"]),
            "runtime_alias_resolved_paths": sorted(agg["runtime_alias_resolved_paths"]),
        })

    exact_missing = [x for x in unique_rows if not x["exact_present"]]
    aliases = [x for x in exact_missing if x["classification"] == "RUNTIME_TRAILING_SPACE_ALIAS_PRESENT"]
    invalid = [x for x in exact_missing if str(x["classification"]).startswith("SERIALIZED_")]
    client_missing = [x for x in exact_missing if str(x["classification"]).startswith("CLIENT_FILE_MISSING")]
    unclassified = [x for x in exact_missing if x["classification"] not in {
        "RUNTIME_TRAILING_SPACE_ALIAS_PRESENT",
        "SERIALIZED_DIRECTORY_ONLY",
        "SERIALIZED_MSVC_DEBUG_FILL_0XCC",
        "CLIENT_FILE_MISSING",
        "CLIENT_FILE_MISSING_TRAILING_SPACE_REFERENCE",
    }]

    expected = len(candidates)
    audited = len(rows)
    status = "PASS" if expected > 0 and audited == expected and not scan_errors else "FAIL"

    bundle_path = None
    if bundle:
        bp = pathlib.Path(bundle).expanduser()
        if not bp.is_absolute():
            bp = pathlib.Path.cwd() / bp
        bp = bp.resolve()
        bp.parent.mkdir(parents=True, exist_ok=True)
        affected_files = sorted({f for x in exact_missing for f in x["files"]}, key=str.lower)
        with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for rel in affected_files:
                physical = resolver.resolve(rel, required=False)
                if physical is not None:
                    zf.write(physical, arcname=f"client/{rel}")
            zf.writestr(
                "STAGE072_TEXTURE_REFERENCE_CLASSIFICATION.json",
                json.dumps(exact_missing, ensure_ascii=False, indent=2) + "\n",
            )
        bundle_path = str(bp)

    exact_missing_files = {f for x in exact_missing for f in x["files"]}
    alias_files = {f for x in aliases for f in x["files"]}
    invalid_files = {f for x in invalid for f in x["files"]}
    client_missing_files = {f for x in client_missing for f in x["files"]}

    return {
        "format": "PT_STAGE072_TEXTURE_REFERENCE_AUDIT_V2",
        "status": status,
        "candidate_files_expected": expected,
        "physical_files_audited": audited,
        "scan_errors": scan_errors,
        "face_material_scoped_texture_reference_occurrences": sum(int(r.get("texture_reference_occurrences") or 0) for r in rows),
        "unique_face_material_scoped_texture_references": len(unique_rows),
        "exact_present_unique_texture_references": sum(bool(x["exact_present"]) for x in unique_rows),
        "exact_missing_unique_texture_references": len(exact_missing),
        "runtime_alias_present_unique_texture_references": len(aliases),
        "serialized_invalid_unique_texture_references": len(invalid),
        "client_missing_unique_texture_references": len(client_missing),
        "unclassified_unique_texture_references": len(unclassified),
        "files_with_exact_missing_references": len(exact_missing_files),
        "files_with_runtime_alias_references": len(alias_files),
        "files_with_serialized_invalid_references": len(invalid_files),
        "files_with_missing_client_textures": len(client_missing_files),
        # Backward-compatible names retain the literal/exact-path meaning.
        "present_unique_texture_references": sum(bool(x["exact_present"]) for x in unique_rows),
        "missing_unique_texture_references": len(exact_missing),
        "missing_references": exact_missing,
        "texture_presence_complete_candidate": bool(status == "PASS" and not client_missing and not invalid),
        "texture_reference_classification_complete_candidate": bool(status == "PASS" and not unclassified),
        "transport_policy": {
            "exact_client_file": "use exact serialized logical path",
            "trailing_ascii_space_alias": "allowed only when removing trailing ASCII space from the final component resolves an exact physical client file; SMD string remains unchanged",
            "serialized_directory_or_0xCC_name": "preserve serialized reference; report invalid historical texture name; structural transport may continue with incomplete material preview",
            "missing_client_file": "preserve logical texture reference and allow structural Blender transport; preview material remains incomplete",
            "decode_or_load_error_for_existing_file": "fail closed",
            "substitution_by_filename_guess": "forbidden",
            "client_modified": False,
        },
        "sourcecode_runtime_note": (
            "smMATERIAL_GROUP::LoadFile preserves serialized texture strings; texture creation can fail without aborting material-group load. "
            "V0.6.2 additionally distinguishes literal malformed names and a narrowly proven trailing-space path alias from genuine client-file absence."
        ),
        "bundle": bundle_path,
        "rows": rows,
    }
