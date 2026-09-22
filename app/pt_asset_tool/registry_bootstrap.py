from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import re
import struct
import tempfile
from typing import Any

from .rare_rigid_preview import parse_inx_model_groups
from .ui_catalog import infer_semantics
from .utils import norm_path

FORMAT = "PT_ASSET_REGISTRY_V3"
PAIRING_FIELDS = [
    "inx", "model_ref", "model_smd", "model_family", "motion_ref", "motion_smb",
    "motion_family", "high", "default", "low", "model_resolved", "motion_required",
    "motion_resolved",
]
MODEL_HEADER = b"SMD Model data Ver 0.62"
STAGE_HEADER = b"SMD Stage data Ver 0.72"
SMD_HEADER_SIZE = 556
SMD_INFO_SIZE = 40
SMD_OBJECT_SIZE = 2236
SMD_VERTEX_SIZE = 24
SMD_FACE_SIZE = 36
SMD_TEXLINK_SIZE = 32
SMD_ROT_SIZE = 20
SMD_POS_SIZE = 16
SMD_SCALE_SIZE = 16
SMD_MATRIX_SIZE = 64


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signature_update(h: "hashlib._Hash", rel: str, size: int, mtime_ns: int) -> None:
    h.update(rel.encode("utf-8", errors="surrogateescape"))
    h.update(b"\0")
    h.update(str(int(size)).encode("ascii"))
    h.update(b"\0")
    h.update(str(int(mtime_ns)).encode("ascii"))
    h.update(b"\n")


def _records_signature(records: list[dict[str, Any]]) -> dict[str, Any]:
    h = hashlib.sha256()
    total_bytes = 0
    max_mtime_ns = 0
    rows = sorted(records, key=lambda r: str(r.get("relative_path") or "").casefold())
    for row in rows:
        rel = str(row.get("relative_path") or "")
        size = int(row.get("size") or 0)
        mtime_ns = int(row.get("mtime_ns") or 0)
        total_bytes += size
        max_mtime_ns = max(max_mtime_ns, mtime_ns)
        _signature_update(h, rel, size, mtime_ns)
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "max_mtime_ns": max_mtime_ns,
        "stat_sha256": h.hexdigest(),
    }


def _client_stat_signature(client_root: pathlib.Path) -> dict[str, Any]:
    h = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    max_mtime_ns = 0
    rows: list[tuple[str, int, int]] = []
    for base, dirs, files in os.walk(client_root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        b = pathlib.Path(base)
        for name in files:
            path = b / name
            try:
                st = path.stat()
            except OSError:
                # A disappearing/inaccessible file changes the observable tree and
                # should force a rebuild rather than silently trusting old state.
                return {"status": "UNSTABLE", "stat_sha256": None}
            rel = path.relative_to(client_root).as_posix()
            rows.append((rel, int(st.st_size), int(st.st_mtime_ns)))
    rows.sort(key=lambda x: x[0].casefold())
    for rel, size, mtime_ns in rows:
        file_count += 1
        total_bytes += size
        max_mtime_ns = max(max_mtime_ns, mtime_ns)
        _signature_update(h, rel, size, mtime_ns)
    return {
        "status": "PASS",
        "file_count": file_count,
        "total_bytes": total_bytes,
        "max_mtime_ns": max_mtime_ns,
        "stat_sha256": h.hexdigest(),
    }


def _name_shape(names: list[str]) -> str:
    """Return a conservative object-name family shape used by rigid discovery.

    The historical survey reduced numeric suffixes to ``#``.  Rebuilding this
    from the current client preserves that useful hint without carrying a
    machine-generated inventory in the package.
    """
    for name in names:
        value = str(name or "").strip()
        if value:
            return re.sub(r"\d+", "#", value)
    return ""


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _cstr(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("latin1", errors="replace")


def _category(rel: str, ext: str) -> str:
    semantic, _role = infer_semantics(rel, ext)
    return {
        "MONSTER": "MOB_MONSTER",
        "NPC": "NPC",
        "CHARACTER": "CHARACTER",
        "MAP": "MAP_STAGE",
        "EFFECT": "EFFECT",
        "ITEM": "WEAPON_ITEM",
        "UI": "UI",
        "AUDIO": "AUDIO",
        "MOTION": "MOTION",
        "MODEL": "MODEL",
        "TEXTURE": "TEXTURE",
        "CONFIG": "CONFIG",
    }.get(semantic, semantic or "UNKNOWN")


def _read_material_texture_refs(data: bytes) -> list[str]:
    # Material string decoding already has a strict implementation in the active
    # Model0.62 parser.  Keep registry bootstrap independent from face semantics.
    try:
        from .multilayer_texlink import _parse_materials
        materials = _parse_materials(data)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for mat in materials:
        for tex in list(mat.get("textures") or []) + list(mat.get("anim_textures") or []):
            name = norm_path(str(tex.get("Name") or ""))
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                out.append(name)
    return out


def _inspect_model062(path: pathlib.Path, data: bytes) -> dict[str, Any]:
    row: dict[str, Any] = {"kind": "SMD_MODEL_062", "header": "SMD Model data Ver 0.62", "issues": []}
    try:
        if len(data) < SMD_HEADER_SIZE:
            raise ValueError("header truncated")
        obj_count = _i32(data, 24)
        mat_count = _i32(data, 28)
        mat_file = _i32(data, 32)
        first_obj = _i32(data, 36)
        tmframe_count = _i32(data, 40)
        if not 0 <= obj_count <= 10000:
            raise ValueError(f"invalid object_count={obj_count}")
        if not 0 <= mat_count <= 10000:
            raise ValueError(f"invalid material_count={mat_count}")
        objects = []
        total_vertices = total_faces = total_texlinks = physique_objects = 0
        object_names: list[str] = []
        for idx in range(obj_count):
            info = SMD_HEADER_SIZE + idx * SMD_INFO_SIZE
            if info + SMD_INFO_SIZE > len(data):
                raise ValueError(f"object info truncated index={idx}")
            info_name = _cstr(data[info:info + 32])
            length = _i32(data, info + 32)
            start = _i32(data, info + 36)
            if start < 0 or length < SMD_OBJECT_SIZE or start + length > len(data):
                raise ValueError(f"object bounds invalid index={idx}")
            raw = data[start:start + SMD_OBJECT_SIZE]
            node_name = _cstr(raw[172:204]) or info_name
            nv, nf, nt = (_i32(raw, 84), _i32(raw, 88), _i32(raw, 92))
            nr, np, ns = (_i32(raw, 684), _i32(raw, 688), _i32(raw, 692))
            if min(nv, nf, nt, nr, np, ns) < 0:
                raise ValueError(f"negative object count index={idx}")
            physique = _u32(raw, 16) != 0
            expected_end = (
                start + SMD_OBJECT_SIZE + nv * SMD_VERTEX_SIZE + nf * SMD_FACE_SIZE
                + nt * SMD_TEXLINK_SIZE + nr * SMD_ROT_SIZE + np * SMD_POS_SIZE
                + ns * SMD_SCALE_SIZE + nr * SMD_MATRIX_SIZE + (nv * 32 if physique else 0)
            )
            bounds_ok = expected_end == start + length
            objects.append({
                "index": idx, "name": info_name, "length": length, "obj_file_point": start,
                "node_name": node_name, "nVertex": nv, "nFace": nf, "nTexLink": nt,
                "physique_ptr": int(_u32(raw, 16)), "bounds_ok": bounds_ok,
            })
            total_vertices += nv
            total_faces += nf
            total_texlinks += nt
            physique_objects += int(physique)
            object_names.append(node_name)
            if not bounds_ok:
                row["issues"].append(f"OBJECT_LENGTH_MISMATCH:{node_name}")
        row.update({
            "structural_valid": not row["issues"],
            "objects": objects,
            "object_count": obj_count,
            "material_count": mat_count,
            "total_vertices": total_vertices,
            "total_faces": total_faces,
            "total_texlinks": total_texlinks,
            "physique_objects": physique_objects,
            "texture_refs": _read_material_texture_refs(data),
            "mat_file_point": mat_file,
            "first_obj_info_point": first_obj,
            "tmframe_count": tmframe_count,
            "object_names": object_names,
            "name_shape": _name_shape(object_names),
        })
        if obj_count > 0 and physique_objects == obj_count:
            family = "SMD_MODEL_062_RIGID_PHYSIQUE"
        elif obj_count > 0 and physique_objects == 0:
            family = "SMD_MODEL_062_STATIC"
        elif obj_count > 0:
            family = "SMD_MODEL_062_MIXED_PHYSIQUE"
        else:
            family = "SMD_MODEL_062_VARIANT_OR_DAMAGED"
        row["compatibility_family"] = family
        row["compatibility_tier"] = "A_REUSE_CORE_NOW" if family != "SMD_MODEL_062_VARIANT_OR_DAMAGED" else "REVIEW"
    except Exception as exc:
        row.update({
            "structural_valid": False,
            "compatibility_family": "SMD_MODEL_062_VARIANT_OR_DAMAGED",
            "compatibility_tier": "REVIEW",
        })
        row["issues"].append(f"{type(exc).__name__}: {exc}")
    row["sha256"] = _sha256_bytes(data)
    return row


def _inspect_stage072(path: pathlib.Path, data: bytes) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": "SMD_STAGE_072",
        "header": "SMD Stage data Ver 0.72",
        "compatibility_family": "STAGE_072_MAP_SEPARATE",
        "compatibility_tier": "A_REUSE_CORE_NOW",
        "issues": [],
        "sha256": _sha256_bytes(data),
    }
    try:
        from .stage072_corpus import parse_stage072
        parsed = parse_stage072(path, include_payload=False)
        counts = parsed.get("counts") or {}
        refs: list[str] = []
        seen: set[str] = set()
        for mat in parsed.get("materials") or []:
            for key in ("textures", "anim_textures"):
                for tex in mat.get(key) or []:
                    value = norm_path(str(tex.get("Name") if isinstance(tex, dict) else tex or ""))
                    if value and value.casefold() not in seen:
                        seen.add(value.casefold()); refs.append(value)
        row.update({
            "structural_valid": parsed.get("full_parse") == "PASS",
            "object_count": int((parsed.get("file_header") or {}).get("ObjCounter_raw") or 0),
            "material_count": int(counts.get("materials") or 0),
            "total_vertices": int(counts.get("vertices") or 0),
            "total_faces": int(counts.get("faces") or 0),
            "total_texlinks": int(counts.get("texlinks") or 0),
            "texture_refs": refs,
            "stage_profile": str(parsed.get("profile") or ""),
        })
        errors = parsed.get("errors") or {}
        if parsed.get("full_parse") != "PASS":
            row["issues"].append("STAGE072_FULL_PARSE_FAIL")
            for key, values in errors.items():
                if values:
                    row["issues"].append(f"{key}:{len(values)}")
    except Exception as exc:
        row.update({"structural_valid": False})
        row["issues"].append(f"{type(exc).__name__}: {exc}")
    return row


def _inspect_inx(path: pathlib.Path, data: bytes) -> dict[str, Any]:
    size = len(data)
    if size not in {67084, 95268}:
        return {
            "kind": "INX_UNKNOWN", "issues": [f"unsupported size={size}"],
            "compatibility_family": "INX_OTHER", "compatibility_tier": "REVIEW",
        }
    model_ref = _cstr(data[0:64])
    motion_ref = _cstr(data[64:128])
    submodel_ref = _cstr(data[128:192])
    groups_raw = parse_inx_model_groups(path)
    groups = {
        key: {"count": int(value.get("count") or 0), "names": list(value.get("active") or [])}
        for key, value in groups_raw.items()
    }
    return {
        "kind": "INX_MODELINFO_GROUPS", "issues": [], "model_ref": model_ref,
        "motion_ref": motion_ref, "submodel_ref": submodel_ref, "groups": groups,
        "compatibility_family": "INX_MODELINFO_FIXED_GROUP_LAYOUT",
        "compatibility_tier": "A_REUSE_CORE_NOW",
    }


def _inspect_bmp(data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"issues": []}
    if len(data) < 18:
        return {**out, "kind": "BMP_UNKNOWN", "compatibility_family": "BMP_OTHER", "compatibility_tier": "REVIEW"}
    try:
        dib = _u32(data, 14)
        if len(data) >= 54 and dib in {40, 52, 56, 64, 108, 124}:
            width, height = _i32(data, 18), _i32(data, 22)
            planes, bpp = _u16(data, 26), _u16(data, 28)
            compression = _u32(data, 30)
            out.update({"width": width, "height": height, "planes": planes, "bpp": bpp, "dib_size": dib, "compression": compression})
            if data[:2] == b"BM":
                out["kind"] = "BMP_STANDARD"
                out["compatibility_family"] = "BMP_STANDARD_32BPP" if bpp == 32 else "BMP_STANDARD_24BPP"
                out["compatibility_tier"] = "A_REUSE_CORE_NOW"
            else:
                out["kind"] = "BMP_PRISTON_PREFIX14"
                out["prefix14_hex"] = data[:14].hex()
                out["compatibility_family"] = "BMP_PROTECTED_PREFIX14_VARIANT"
                out["compatibility_tier"] = "A_REUSE_CORE_NOW"
            return out
    except Exception as exc:
        out["issues"].append(f"{type(exc).__name__}: {exc}")
    out.update({"kind": "BMP_UNKNOWN", "compatibility_family": "BMP_OTHER", "compatibility_tier": "REVIEW"})
    return out


def _inspect_tga(data: bytes) -> dict[str, Any]:
    if len(data) < 18:
        return {"kind": "TGA_UNKNOWN", "compatibility_family": "TGA_NONSTANDARD_OR_PROTECTED", "compatibility_tier": "REVIEW"}
    image_type = data[2]
    width, height = _u16(data, 12), _u16(data, 14)
    bpp = data[16]
    standard = image_type in {1, 2, 3, 9, 10, 11} and width > 0 and height > 0 and bpp in {8, 16, 24, 32}
    return {
        "kind": "TGA_STANDARD" if standard else "TGA_UNKNOWN",
        "image_type": image_type, "width": width, "height": height, "bpp": bpp,
        "compatibility_family": "TGA_STANDARD" if standard else "TGA_NONSTANDARD_OR_PROTECTED",
        "compatibility_tier": "A_REUSE_CORE_NOW" if standard else "REVIEW",
    }


def inspect_client_file(client_root: pathlib.Path, path: pathlib.Path) -> dict[str, Any]:
    rel = path.relative_to(client_root).as_posix()
    ext = path.suffix.lower()
    size = path.stat().st_size
    st = path.stat()
    row: dict[str, Any] = {
        "path": str(path.resolve()), "relative_path": rel, "basename": path.name,
        "extension": ext, "size": size, "mtime_ns": int(st.st_mtime_ns),
        "category_hint": _category(rel, ext),
    }
    if ext in {".smd", ".inx"}:
        data = path.read_bytes()
    elif ext == ".smb":
        with path.open("rb") as fh:
            data = fh.read(len(MODEL_HEADER))
    elif ext in {".bmp", ".tga"}:
        with path.open("rb") as fh:
            data = fh.read(256)
    elif ext == ".ase":
        with path.open("rb") as fh:
            data = fh.read(8 * 1024 * 1024)
    else:
        data = b""
    if ext == ".smd":
        if data.startswith(MODEL_HEADER):
            row.update(_inspect_model062(path, data))
        elif data.startswith(STAGE_HEADER):
            row.update(_inspect_stage072(path, data))
        else:
            row.update({"kind": "SMD_UNKNOWN", "compatibility_family": "SMD_OTHER", "compatibility_tier": "REVIEW", "issues": []})
    elif ext == ".smb":
        model = data.startswith(MODEL_HEADER)
        row.update({"kind": "SMB_BIPED_LIKELY" if model else "SMB_UNKNOWN", "compatibility_family": "SMB_BIPED_SKELETON_MOTION" if model else "SMB_OTHER_OR_LOW_SIGNAL", "compatibility_tier": "A_REUSE_CORE_NOW" if model else "REVIEW", "issues": []})
    elif ext == ".inx":
        try:
            row.update(_inspect_inx(path, data))
        except Exception as exc:
            row.update({"kind": "INX_UNKNOWN", "compatibility_family": "INX_OTHER", "compatibility_tier": "REVIEW", "issues": [f"{type(exc).__name__}: {exc}"]})
    elif ext == ".bmp":
        row.update(_inspect_bmp(data))
    elif ext == ".tga":
        row.update(_inspect_tga(data))
    elif ext == ".ase":
        text = data[:8 * 1024 * 1024].decode("latin1", errors="ignore")
        row.update({
            "kind": "ASE_TEXT", "compatibility_family": "ASE_CHARACTER_PHYSIQUE" if "*PHYSIQUE" in text.upper() else "ASE_STATIC_GEOMETRY",
            "compatibility_tier": "REFERENCE", "issues": [],
        })
    elif ext == ".ini":
        row.update({"kind": "INI_TEXT", "compatibility_family": "INI_TEXT_CONFIG", "compatibility_tier": "REFERENCE", "issues": []})
    else:
        row.update({"kind": (ext[1:].upper() + "_FILE") if ext else "FILE", "compatibility_family": "SUPPORT_FILE", "compatibility_tier": "REFERENCE", "issues": []})
    return row


def _runtime_ref(ref: str, suffix: str) -> str:
    value = norm_path(ref)
    if not value:
        return ""
    p = pathlib.PurePosixPath(value)
    return p.with_suffix(suffix).as_posix()


def _pairing_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_rel = {norm_path(r.get("relative_path") or "").casefold(): r for r in records}
    rows: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("kind") != "INX_MODELINFO_GROUPS":
            continue
        model_ref = str(rec.get("model_ref") or "")
        motion_ref = str(rec.get("motion_ref") or "")
        model_guess = _runtime_ref(model_ref, ".smd") if model_ref else ""
        motion_guess = _runtime_ref(motion_ref, ".smb") if motion_ref else ""
        model_rec = by_rel.get(model_guess.casefold()) if model_guess else None
        motion_rec = by_rel.get(motion_guess.casefold()) if motion_guess else None
        groups = rec.get("groups") or {}
        rows.append({
            "inx": norm_path(rec.get("relative_path") or ""),
            "model_ref": model_ref,
            "model_smd": norm_path(model_rec.get("relative_path")) if model_rec else model_guess,
            "model_family": str(model_rec.get("compatibility_family") or "") if model_rec else "",
            "motion_ref": motion_ref,
            "motion_smb": norm_path(motion_rec.get("relative_path")) if motion_rec else motion_guess,
            "motion_family": str(motion_rec.get("compatibility_family") or "") if motion_rec else "",
            "high": ",".join((groups.get("high") or {}).get("names") or []),
            "default": ",".join((groups.get("default") or {}).get("names") or []),
            "low": ",".join((groups.get("low") or {}).get("names") or []),
            "model_resolved": bool(model_rec),
            "motion_required": bool(motion_ref),
            "motion_resolved": bool(motion_rec),
        })
    rows.sort(key=lambda x: str(x["inx"]).casefold())
    return rows


def _atomic_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_runtime_registry(client_root: pathlib.Path, inventory_path: pathlib.Path, pairing_path: pathlib.Path) -> dict[str, Any]:
    client_root = pathlib.Path(client_root).expanduser().resolve()
    if not client_root.is_dir():
        raise FileNotFoundError(f"client root does not exist: {client_root}")
    records: list[dict[str, Any]] = []
    for base, dirs, files in os.walk(client_root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        b = pathlib.Path(base)
        for name in files:
            path = b / name
            try:
                records.append(inspect_client_file(client_root, path))
            except (OSError, ValueError, struct.error) as exc:
                rel = path.relative_to(client_root).as_posix()
                records.append({
                    "path": str(path.resolve()), "relative_path": rel, "basename": path.name,
                    "extension": path.suffix.lower(), "size": path.stat().st_size if path.exists() else None,
                    "category_hint": _category(rel, path.suffix.lower()), "kind": "UNREADABLE_OR_UNSUPPORTED",
                    "compatibility_family": "UNRESOLVED", "compatibility_tier": "REVIEW",
                    "issues": [f"{type(exc).__name__}: {exc}"],
                })
    records.sort(key=lambda r: str(r.get("relative_path") or "").casefold())
    inventory = {
        "format": FORMAT,
        "tool": "PT_ASSET_RUNTIME_REGISTRY_BOOTSTRAP_V2",
        "canonical_client_root": str(client_root),
        "roots": [str(client_root)],
        "client_modified": False,
        "records": records,
    }
    _atomic_text(inventory_path, json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
    meta_path = inventory_path.parent / "registry_meta.json"
    signature = _records_signature(records)
    _atomic_text(meta_path, json.dumps({
        "format": FORMAT,
        "client_root": str(client_root),
        "record_count": len(records),
        "client_signature": signature,
    }, ensure_ascii=False, indent=2) + "\n")
    pairs = _pairing_rows(records)
    pairing_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{pairing_path.name}.", suffix=".tmp", dir=str(pairing_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=PAIRING_FIELDS)
            writer.writeheader()
            writer.writerows(pairs)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, pairing_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {
        "format": FORMAT, "status": "PASS", "client_root": str(client_root),
        "inventory": str(inventory_path), "pairing": str(pairing_path),
        "record_count": len(records), "pairing_count": len(pairs), "client_modified": False,
    }


def ensure_runtime_registry(client_root: pathlib.Path, inventory_path: pathlib.Path, pairing_path: pathlib.Path, *, force: bool = False, verify_signature: bool = True) -> dict[str, Any]:
    client_root = pathlib.Path(client_root).expanduser().resolve()
    inventory_path = pathlib.Path(inventory_path)
    pairing_path = pathlib.Path(pairing_path)
    meta_path = inventory_path.parent / "registry_meta.json"
    if not force and inventory_path.is_file() and pairing_path.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        saved_root = pathlib.Path(str(meta.get("client_root") or "")).expanduser() if meta.get("client_root") else None
        if meta.get("format") == FORMAT and saved_root is not None:
            try:
                same_root = saved_root.resolve() == client_root
            except OSError:
                same_root = False
            if same_root:
                saved_signature = meta.get("client_signature") or {}
                # The UI hot path deliberately trusts the persisted registry snapshot.
                # A full stat signature walks every client file, which duplicated the
                # catalog scan on every UI start. Explicit Reindex still performs the
                # strict physical refresh; CLI callers keep verify_signature=True.
                if not verify_signature and saved_signature.get("stat_sha256"):
                    return {
                        "format": FORMAT, "status": "READY_PERSISTED", "client_root": str(client_root),
                        "inventory": str(inventory_path), "pairing": str(pairing_path),
                        "record_count": int(meta.get("record_count") or 0),
                        "client_signature": saved_signature,
                        "signature_verified_now": False,
                        "client_modified": False,
                    }
                current_signature = _client_stat_signature(client_root)
                if (
                    current_signature.get("status") == "PASS"
                    and saved_signature.get("stat_sha256")
                    and current_signature.get("stat_sha256") == saved_signature.get("stat_sha256")
                ):
                    return {
                        "format": FORMAT, "status": "READY", "client_root": str(client_root),
                        "inventory": str(inventory_path), "pairing": str(pairing_path),
                        "record_count": int(meta.get("record_count") or 0),
                        "client_signature": current_signature,
                        "signature_verified_now": True,
                        "client_modified": False,
                    }
    return build_runtime_registry(client_root, inventory_path, pairing_path)
