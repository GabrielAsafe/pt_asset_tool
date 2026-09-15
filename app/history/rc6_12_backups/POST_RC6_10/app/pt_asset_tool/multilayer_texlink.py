from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import struct
import zipfile

from .utils import norm_path

HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO = 556, 40, 2236
SV, SF, ST = 24, 36, 32
MAT_GROUP_SIZE, MATERIAL_SIZE = 88, 320
O_NV, O_NF, O_NT = 84, 88, 92
F_MATERIAL, F_TEX = 6, 32
T_HTEX, T_NEXT = 24, 28

# smRead3d.cpp source mapping. TextureStageState stores the D3DTOP code
# parsed from BS_* material script tokens; zero means no explicit BS_* token.
STAGE_OP_NAMES = {
    0: "DEFAULT",
    1: "D3DTOP_DISABLE",
    2: "D3DTOP_SELECTARG1",
    3: "D3DTOP_SELECTARG2",
    4: "D3DTOP_MODULATE",
    5: "D3DTOP_MODULATE2X",
    6: "D3DTOP_MODULATE4X",
    7: "D3DTOP_ADD",
    8: "D3DTOP_ADDSIGNED",
    9: "D3DTOP_ADDSIGNED2X",
    10: "D3DTOP_SUBTRACT",
}

# Exact index order of szMapFormScript[] in smRead3d.cpp.
FORM_NAMES = {
    0: "FS_NONE",
    1: "FS_FORMX",
    2: "FS_FORMY",
    3: "FS_FORMZ",
    4: "FS_SCROLL",
    5: "FS_REFLEX",
    6: "FS_SCROLL2",
    7: "FS_SCROLL3",
    8: "FS_SCROLL4",
    9: "FS_SCROLL5",
    10: "FS_SCROLL6",
    11: "FS_SCROLL7",
    12: "FS_SCROLL8",
    13: "FS_SCROLL9",
    14: "FS_SCROLL10",
    15: "FS_SCROLLSLOW1",
    16: "FS_SCROLLSLOW2",
    17: "FS_SCROLLSLOW3",
    18: "FS_SCROLLSLOW4",
}


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin1", "replace")


def _split_nul_strings(block: bytes) -> list[str]:
    parts = block.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return [x.decode("latin1", "replace") for x in parts]


def _parse_materials(data: bytes) -> list[dict]:
    mat_count = _i32(data, 28)
    mat_file = _i32(data, 32)
    first_obj = _i32(data, 36)
    if mat_count < 0 or not SH <= mat_file <= first_obj <= len(data):
        raise ValueError("invalid material region")
    if mat_count == 0:
        return []
    if mat_file + MAT_GROUP_SIZE > first_obj:
        raise ValueError("material group truncated")
    if _i32(data, mat_file + 8) != mat_count:
        raise ValueError("material count mismatch")

    cursor = mat_file + MAT_GROUP_SIZE
    rows = []
    for mid in range(mat_count):
        end = cursor + MATERIAL_SIZE
        if end > first_obj:
            raise ValueError(f"material {mid} block truncated")
        raw = data[cursor:end]
        tc = _i32(raw, 4)
        ac = _i32(raw, 304)
        if not 0 <= tc <= 8 or not 0 <= ac <= 32:
            raise ValueError(f"material {mid}: invalid texture counters {tc}/{ac}")
        row = {
            "id": mid,
            "InUse": _i32(raw, 0),
            "TextureCounter": tc,
            "TextureStageState": [_i32(raw, 40 + 4*i) for i in range(8)],
            "TextureFormState": [_i32(raw, 72 + 4*i) for i in range(8)],
            "ReformTexture": _i32(raw, 104),
            "TextureType": _i32(raw, 112),
            "BlendType": _i32(raw, 116),
            "Shade": _i32(raw, 120),
            "TwoSide": _i32(raw, 124),
            "SelfIllum": struct.unpack_from("<f", raw, 148)[0],
            "UseState": _i32(raw, 164),
            "AnimTexCounter": ac,
            "textures": [],
            "anim_textures": [],
        }
        cursor = end
        if row["InUse"]:
            if cursor + 4 > first_obj:
                raise ValueError(f"material {mid}: missing string length")
            strlen = _i32(data, cursor)
            cursor += 4
            if strlen < 0 or cursor + strlen > first_obj:
                raise ValueError(f"material {mid}: invalid string length {strlen}")
            strings = _split_nul_strings(data[cursor:cursor+strlen])
            cursor += strlen
            expected = 2 * (tc + ac)
            if len(strings) != expected:
                raise ValueError(f"material {mid}: string count {len(strings)} != {expected}")
            k = 0
            for _ in range(tc):
                row["textures"].append({"Name": strings[k], "NameA": strings[k+1]})
                k += 2
            for _ in range(ac):
                row["anim_textures"].append({"Name": strings[k], "NameA": strings[k+1]})
                k += 2
        rows.append(row)
    if cursor != first_obj:
        raise ValueError(f"material region did not close: {cursor} != {first_obj}")
    return rows


def _classify_profile(mat: dict, *, uv_distinct: bool) -> str:
    if int(mat.get("TextureCounter") or 0) < 2:
        return "SINGLE_STAGE"
    tex = [norm_path(x.get("Name") or "") for x in mat.get("textures", [])[:2]]
    op = list(mat.get("TextureStageState") or [])[:2]
    form = list(mat.get("TextureFormState") or [])[:2]
    same = len(tex) >= 2 and tex[0].lower() == tex[1].lower()
    stage1_name = pathlib.PurePosixPath(tex[1]).name.lower() if len(tex) > 1 else ""

    if len(op) > 1 and len(form) > 1 and op[1] == 7 and form[1] == 5:
        return "REFLEX_ADD"
    if uv_distinct and len(form) > 1 and form[0] == 0 and form[1] == 0:
        if "light" in stage1_name:
            return "SECOND_UV_LIGHTMAP_MODULATE"
        return "SECOND_UV_MODULATE"
    if same and any(int(x) != 0 for x in form):
        return "SAME_TEXTURE_DYNAMIC_FORM"
    if same and all(int(x) == 0 for x in form) and all(int(x) == 0 for x in op):
        return "DUPLICATE_TEXTURE_DEFAULT_STAGE"
    return "GENERIC_TWO_STAGE"


def parse_multilayer_semantics(path: pathlib.Path) -> dict:
    p = pathlib.Path(path)
    data = p.read_bytes()
    if len(data) < SH or not data.startswith(HEADER):
        raise ValueError("not SMD Model data Ver 0.62")
    obj_count, mat_count = struct.unpack_from("<ii", data, 24)
    materials = _parse_materials(data)
    if len(materials) != mat_count:
        raise ValueError("material parser count mismatch")

    objects = []
    runtime_bases = []
    htexture_errors = []
    stage_index_errors = []
    inert_zero_texture_texlink_faces = []
    material_usage: dict[int, dict] = {}
    total_faces = 0
    total_multilayer = 0
    uv_distinct_faces = 0

    for oi in range(obj_count):
        info = SH + oi * SI
        if info + SI > len(data):
            raise ValueError(f"object info {oi} truncated")
        info_name = _cstr(data[info:info+32])
        start = _i32(data, info + 36)
        if start < 0 or start + SO > len(data):
            raise ValueError(f"object {oi} header out of bounds")
        raw = data[start:start+SO]
        node_name = _cstr(raw[172:204]) or info_name
        nv, nf, nt = struct.unpack_from("<iii", raw, O_NV)
        texbase = _u32(raw, 12)
        if min(nv, nf, nt) < 0:
            raise ValueError(f"negative counts in {node_name}")
        face_base = start + SO + nv * SV
        tex_base_file = face_base + nf * SF
        if tex_base_file + nt * ST > len(data):
            raise ValueError(f"TexLink block out of bounds in {node_name}")

        obj_faces = []
        obj_multi = 0
        for fi in range(nf):
            fo = face_base + fi * SF
            verts = list(struct.unpack_from("<3H", data, fo))
            mid = struct.unpack_from("<H", data, fo + F_MATERIAL)[0]
            if not 0 <= mid < len(materials):
                raise ValueError(f"face material id out of range: object={node_name} face={fi} material={mid}")
            ptr = _u32(data, fo + F_TEX)
            delta = ptr - texbase
            if delta < 0 or delta % ST:
                raise ValueError(f"invalid first TexLink pointer: {node_name}:{fi}")
            ti = delta // ST
            chain = []
            seen = set()
            while True:
                if ti in seen or not 0 <= ti < nt:
                    raise ValueError(f"invalid/cyclic TexLink chain: {node_name}:{fi}")
                seen.add(ti)
                to = tex_base_file + ti * ST
                us = struct.unpack_from("<3f", data, to)
                vs = struct.unpack_from("<3f", data, to + 12)
                htex = _u32(data, to + T_HTEX)
                nxt = _u32(data, to + T_NEXT)
                stage_index = len(chain)
                # Source proof: AddTexLink receives &smMaterial[mid].smTexture[tcnt].
                # Therefore hTexture points to material_base + mid*sizeof(smMATERIAL)
                # + offsetof(smTexture=8) + stage*4.
                runtime_base = int(htex) - (mid * MATERIAL_SIZE + 8 + stage_index * 4)
                runtime_bases.append(runtime_base)
                chain.append({
                    "texlink_index": ti,
                    "file_offset": to,
                    "stage_index": stage_index,
                    "u": list(us),
                    "v": list(vs),
                    "uv": [[float(us[j]), float(vs[j])] for j in range(3)],
                    "hTexture": int(htex),
                    "next": int(nxt),
                    "runtime_material_array_base_candidate": runtime_base,
                })
                if nxt == 0:
                    break
                nd = nxt - texbase
                if nd < 0 or nd % ST:
                    raise ValueError(f"invalid NextTex pointer: {node_name}:{fi}")
                ti = nd // ST
                if len(chain) > 8:
                    raise ValueError(f"TexLink chain too deep: {node_name}:{fi}")

            mat = materials[mid]
            tc = int(mat.get("TextureCounter") or 0)
            anim_tc = int(mat.get("AnimTexCounter") or 0)
            if len(chain) > tc:
                # Source/runtime proof for a narrow legacy case:
                # smRead3d can leave one TexLink attached to a face whose material
                # has no renderable textures. smRENDER3D::RenderD3D() returns
                # immediately when TextureCounter==0 && AnimTexCounter==0, so the
                # link is inert and is not a material texture stage. Accept only
                # the exact single-link / zero-counter shape; all other depth
                # overruns remain fail-closed.
                if tc == 0 and anim_tc == 0 and len(chain) == 1:
                    inert_zero_texture_texlink_faces.append({
                        "object": node_name, "face": fi, "material": mid,
                        "depth": 1, "TextureCounter": 0, "AnimTexCounter": 0,
                        "hTexture": int(chain[0]["hTexture"]),
                    })
                else:
                    stage_index_errors.append({
                        "object": node_name, "face": fi, "material": mid,
                        "depth": len(chain), "TextureCounter": tc,
                        "AnimTexCounter": anim_tc,
                    })
            if len(chain) > 1:
                obj_multi += 1
                total_multilayer += 1
                if any(
                    max(abs(chain[0]["uv"][j][k] - chain[1]["uv"][j][k]) for j in range(3) for k in range(2)) > 1e-7
                    for _ in [0]
                ):
                    uv_distinct_faces += 1
            mu = material_usage.setdefault(mid, {
                "material_id": mid,
                "face_count": 0,
                "chain_depth_histogram": collections.Counter(),
                "uv_distinct_multilayer_faces": 0,
            })
            mu["face_count"] += 1
            mu["chain_depth_histogram"][len(chain)] += 1
            if len(chain) > 1 and max(abs(chain[0]["uv"][j][k] - chain[1]["uv"][j][k]) for j in range(3) for k in range(2)) > 1e-7:
                mu["uv_distinct_multilayer_faces"] += 1
            obj_faces.append({"index": fi, "vertices": verts, "material_id": mid, "chain": chain})
        total_faces += nf
        objects.append({
            "index": oi,
            "name": node_name,
            "vertices": nv,
            "faces": nf,
            "texlinks": nt,
            "multilayer_faces": obj_multi,
            "face_rows": obj_faces,
        })

    base_counter = collections.Counter(runtime_bases)
    runtime_base = base_counter.most_common(1)[0][0] if base_counter else None
    if runtime_base is not None:
        for obj in objects:
            for face in obj["face_rows"]:
                mid = face["material_id"]
                for link in face["chain"]:
                    expected = runtime_base + mid * MATERIAL_SIZE + 8 + link["stage_index"] * 4
                    if link["hTexture"] != expected:
                        htexture_errors.append({
                            "object": obj["name"], "face": face["index"], "material": mid,
                            "stage": link["stage_index"], "actual": link["hTexture"], "expected": expected,
                        })

    used_materials = []
    profile_counts = collections.Counter()
    for mid, usage in sorted(material_usage.items()):
        mat = materials[mid]
        hist = dict(sorted(usage["chain_depth_histogram"].items()))
        max_depth = max(hist) if hist else 0
        if max_depth < 2:
            continue
        uv_distinct = bool(usage["uv_distinct_multilayer_faces"])
        profile = _classify_profile(mat, uv_distinct=uv_distinct)
        profile_counts[profile] += 1
        textures = []
        for si, tex in enumerate(mat.get("textures", [])):
            textures.append({
                "stage_index": si,
                "name": norm_path(tex.get("Name") or ""),
                "name_a": norm_path(tex.get("NameA") or ""),
                "stage_state": int(mat["TextureStageState"][si]),
                "stage_state_name": STAGE_OP_NAMES.get(int(mat["TextureStageState"][si]), f"D3DTOP_{int(mat['TextureStageState'][si])}"),
                "form_state": int(mat["TextureFormState"][si]),
                "form_state_name": FORM_NAMES.get(int(mat["TextureFormState"][si]), f"FS_{int(mat['TextureFormState'][si])}"),
            })
        used_materials.append({
            "material_id": mid,
            "face_count": usage["face_count"],
            "chain_depth_histogram": {str(k): v for k, v in hist.items()},
            "uv_distinct_multilayer_faces": usage["uv_distinct_multilayer_faces"],
            "TextureCounter": mat["TextureCounter"],
            "TextureStageState": mat["TextureStageState"][:mat["TextureCounter"]],
            "TextureFormState": mat["TextureFormState"][:mat["TextureCounter"]],
            "ReformTexture": mat["ReformTexture"],
            "BlendType": mat["BlendType"],
            "TwoSide": mat["TwoSide"],
            "profile": profile,
            "textures": textures,
        })

    return {
        "format": "PT_MULTILAYER_TEXLINK_SEMANTICS_V1",
        "path": str(p),
        "sha256": hashlib.sha256(data).hexdigest(),
        "object_count": obj_count,
        "material_count": mat_count,
        "total_faces": total_faces,
        "multilayer_faces": total_multilayer,
        "singlelayer_faces": total_faces - total_multilayer,
        "uv_distinct_multilayer_faces": uv_distinct_faces,
        "max_layers": max((len(face["chain"]) for obj in objects for face in obj["face_rows"]), default=0),
        "runtime_material_array_base": runtime_base,
        "runtime_material_array_base_candidate_count": len(base_counter),
        "htexture_slot_mapping": "SMATERIAL_SM_TEXTURE_SLOT_EXACT" if not htexture_errors else "FAIL",
        "htexture_mapping_errors": htexture_errors,
        "stage_index_errors": stage_index_errors,
        "inert_zero_texture_texlink_faces": inert_zero_texture_texlink_faces,
        "profile_counts": dict(sorted(profile_counts.items())),
        "mixed_chain_depth_material_count": sum(1 for m in used_materials if len(m["chain_depth_histogram"]) > 1),
        "multilayer_materials": used_materials,
        "materials": materials,
        "objects": objects,
        "source_semantics": "PASS" if not htexture_errors and not stage_index_errors else "FAIL",
        "client_modified": False,
    }


def compact_semantics(report: dict) -> dict:
    return {
        "format": report["format"],
        "path": report["path"],
        "sha256": report["sha256"],
        "object_count": report["object_count"],
        "material_count": report["material_count"],
        "total_faces": report["total_faces"],
        "multilayer_faces": report["multilayer_faces"],
        "singlelayer_faces": report["singlelayer_faces"],
        "uv_distinct_multilayer_faces": report["uv_distinct_multilayer_faces"],
        "max_layers": report["max_layers"],
        "runtime_material_array_base": report["runtime_material_array_base"],
        "htexture_slot_mapping": report["htexture_slot_mapping"],
        "htexture_mapping_error_count": len(report["htexture_mapping_errors"]),
        "stage_index_error_count": len(report["stage_index_errors"]),
        "inert_zero_texture_texlink_face_count": len(report.get("inert_zero_texture_texlink_faces") or []),
        "inert_zero_texture_texlink_face_sample": (report.get("inert_zero_texture_texlink_faces") or [])[:16],
        "profile_counts": report["profile_counts"],
        "mixed_chain_depth_material_count": report.get("mixed_chain_depth_material_count", 0),
        "multilayer_materials": report["multilayer_materials"],
        "source_semantics": report["source_semantics"],
        "client_modified": False,
    }


def audit_multilayer_semantics_corpus(records: list[dict], resolver, bundle: str | None = None, per_profile: int = 2) -> dict:
    candidates = []
    for r in records:
        if r.get("kind") != "SMD_MODEL_062":
            continue
        try:
            if int(r.get("total_faces") or 0) > 0 and int(r.get("total_texlinks") or 0) > int(r.get("total_faces") or 0):
                candidates.append(r)
        except Exception:
            pass

    rows = []
    errors = []
    profile_files: dict[str, list[dict]] = collections.defaultdict(list)
    op_hist = collections.Counter()
    form_hist = collections.Counter()
    mixed_depth_material_files = 0
    mapping_fail_files = 0
    stage_index_fail_files = 0
    source_semantics_fail_files = 0
    inert_zero_texture_texlink_faces_total = 0

    for rec in sorted(candidates, key=lambda r: norm_path(r.get("relative_path") or "").lower()):
        rel = norm_path(rec.get("relative_path") or "")
        try:
            physical = resolver.resolve(rel)
            rep = parse_multilayer_semantics(physical)
            row = {
                "relative_path": rel,
                "category": rec.get("category_hint") or "UNKNOWN",
                "mode": "RIGID" if int(rec.get("physique_objects") or 0) == int(rec.get("object_count") or 0) else "STATIC",
                "profile_counts": rep["profile_counts"],
                "htexture_slot_mapping": rep["htexture_slot_mapping"],
                "htexture_mapping_error_count": len(rep["htexture_mapping_errors"]),
                "htexture_mapping_error_sample": rep["htexture_mapping_errors"][:16],
                "stage_index_error_count": len(rep["stage_index_errors"]),
                "stage_index_error_sample": rep["stage_index_errors"][:16],
                "inert_zero_texture_texlink_face_count": len(rep.get("inert_zero_texture_texlink_faces") or []),
                "inert_zero_texture_texlink_face_sample": (rep.get("inert_zero_texture_texlink_faces") or [])[:16],
                "source_semantics": rep["source_semantics"],
                "multilayer_faces": rep["multilayer_faces"],
                "total_faces": rep["total_faces"],
                "max_layers": rep["max_layers"],
                "multilayer_materials": rep["multilayer_materials"],
                "texture_refs": [norm_path(x) for x in (rec.get("texture_refs") or [])],
            }
            for m in rep["multilayer_materials"]:
                for t in m["textures"]:
                    op_hist[(t["stage_index"], t["stage_state"], t["stage_state_name"])] += m["face_count"]
                    form_hist[(t["stage_index"], t["form_state"], t["form_state_name"])] += m["face_count"]
                if len(m["chain_depth_histogram"]) > 1:
                    mixed_depth_material_files += 1
                profile_files[m["profile"]].append(row)
            inert_zero_texture_texlink_faces_total += len(rep.get("inert_zero_texture_texlink_faces") or [])
            if rep["htexture_mapping_errors"]:
                mapping_fail_files += 1
            if rep["stage_index_errors"]:
                stage_index_fail_files += 1
            if rep["source_semantics"] != "PASS":
                source_semantics_fail_files += 1
            rows.append(row)
        except Exception as exc:
            errors.append({"relative_path": rel, "error": f"{type(exc).__name__}: {exc}"})

    selected: list[dict] = []
    seen = set()
    # Always retain semantic failures in the generated representative bundle.
    # This makes a corpus-level fail reproducible instead of selecting only
    # otherwise-successful profile representatives.
    for r in rows:
        if r.get("source_semantics") == "PASS":
            continue
        k = r["relative_path"].lower()
        if k not in seen:
            selected.append(r)
            seen.add(k)

    for profile in sorted(profile_files):
        choices = sorted(profile_files[profile], key=lambda r: (r["mode"], r["category"], -r["multilayer_faces"], r["relative_path"].lower()))
        for r in choices:
            k = r["relative_path"].lower()
            if k in seen:
                continue
            selected.append(r)
            seen.add(k)
            if sum(1 for x in selected if profile in x["profile_counts"]) >= per_profile:
                break

    bundle_path = None
    if bundle:
        bp = pathlib.Path(bundle).expanduser().resolve()
        bp.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": "PT_MULTILAYER_TEXLINK_SEMANTIC_REPS_V1",
            "profiles": sorted(profile_files),
            "selected": selected,
        }
        with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            copied = set()
            for r in selected:
                rel = r["relative_path"]
                try:
                    src = resolver.resolve(rel)
                    zf.write(src, arcname="client/" + rel)
                    copied.add(rel.lower())
                except Exception:
                    pass
                names = []
                for m in r["multilayer_materials"]:
                    for t in m.get("textures") or []:
                        if t.get("name"):
                            names.append(t["name"])
                for tex in names:
                    key = tex.lower()
                    if key in copied:
                        continue
                    try:
                        src = resolver.resolve(tex)
                        zf.write(src, arcname="client/" + tex)
                        copied.add(key)
                    except Exception:
                        pass
        bundle_path = str(bp)

    profile_counts = {k: len({r["relative_path"].lower() for r in v}) for k, v in sorted(profile_files.items())}
    return {
        "format": "PT_MULTILAYER_TEXLINK_SEMANTIC_CORPUS_AUDIT_V1",
        "status": "PASS" if len(rows) == len(candidates) and not errors else "FAIL",
        "candidate_files_expected": len(candidates),
        "physical_files_audited": len(rows),
        "scan_errors": errors,
        "htexture_mapping_fail_files": mapping_fail_files,
        "stage_index_fail_files": stage_index_fail_files,
        "source_semantics_fail_files": source_semantics_fail_files,
        "inert_zero_texture_texlink_faces": inert_zero_texture_texlink_faces_total,
        "semantic_failures": [
            {
                "relative_path": r["relative_path"],
                "htexture_mapping_error_count": r["htexture_mapping_error_count"],
                "stage_index_error_count": r["stage_index_error_count"],
            }
            for r in rows if r.get("source_semantics") != "PASS"
        ],
        "mixed_chain_depth_same_material_occurrences": mixed_depth_material_files,
        "semantic_profile_file_counts": profile_counts,
        "stage_state_usage": [
            {"stage_index": k[0], "code": k[1], "name": k[2], "face_uses": v}
            for k, v in sorted(op_hist.items())
        ],
        "form_state_usage": [
            {"stage_index": k[0], "code": k[1], "name": k[2], "face_uses": v}
            for k, v in sorted(form_hist.items())
        ],
        "representatives": [r["relative_path"] for r in selected],
        "two_stage_semantics_complete_candidate": (
            len(rows) == len(candidates) and not errors and source_semantics_fail_files == 0
        ),
        "bundle": bundle_path,
        "rows": rows,
    }
