from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import shutil
import struct
import zipfile

from .utils import norm_path

HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO = 556, 40, 2236
SV, SF, ST = 24, 36, 32
O_NV, O_NF, O_NT = 84, 88, 92
F_TEX = 32
T_NEXT = 28


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin1", "replace")


def _mode(record: dict) -> str:
    try:
        oc = int(record.get("object_count") or 0)
        pc = int(record.get("physique_objects") or 0)
    except Exception:
        return "UNKNOWN"
    if oc > 0 and pc == oc:
        return "RIGID"
    if oc > 0 and pc == 0:
        return "STATIC"
    if oc > 0 and 0 < pc < oc:
        return "MIXED"
    return "UNKNOWN"


def _candidate(record: dict) -> bool:
    if record.get("kind") != "SMD_MODEL_062":
        return False
    try:
        faces = int(record.get("total_faces") or 0)
        links = int(record.get("total_texlinks") or 0)
    except Exception:
        return False
    return faces > 0 and links > faces


def parse_texlink_file(path: pathlib.Path) -> dict:
    p = pathlib.Path(path)
    b = p.read_bytes()
    if len(b) < SH or not b.startswith(HEADER):
        raise ValueError("not SMD Model data Ver 0.62")

    obj_count, mat_count = struct.unpack_from("<ii", b, 24)
    if obj_count < 1 or obj_count > 10000:
        raise ValueError(f"invalid object count: {obj_count}")

    infos = []
    for idx in range(obj_count):
        off = SH + idx * SI
        if off + SI > len(b):
            raise ValueError(f"object info OOB: {idx}")
        name = _cstr(b[off:off + 32])
        length, start = struct.unpack_from("<ii", b, off + 32)
        infos.append((idx, name, length, start))

    rows = []
    total_faces = 0
    total_links = 0
    total_multilayer_faces = 0
    chain_hist = collections.Counter()
    invalid_chain_count = 0
    cycles = 0
    htexture_stride = collections.Counter()
    uv_difference_faces = 0
    max_layers = 0

    for idx, info_name, length, start in infos:
        if start < 0 or start + SO > len(b):
            raise ValueError(f"object header OOB: {idx}:{info_name}")
        raw = b[start:start + SO]
        node_name = _cstr(raw[172:204])
        nv, nf, nt = struct.unpack_from("<iii", raw, O_NV)
        texbase = _u32(raw, 12)
        if min(nv, nf, nt) < 0:
            raise ValueError(f"negative counts in object {idx}:{info_name}: {nv}/{nf}/{nt}")

        v = start + SO
        f = v + nv * SV
        t = f + nf * SF
        end_tex = t + nt * ST
        if end_tex > len(b):
            raise ValueError(f"texlink block OOB: {idx}:{info_name}")

        obj_hist = collections.Counter()
        obj_multilayer = 0
        obj_invalid = 0
        obj_cycles = 0
        obj_max = 0
        obj_uv_diff = 0
        obj_stride = collections.Counter()

        for fi in range(nf):
            face_off = f + fi * SF
            if face_off + SF > len(b):
                raise ValueError(f"face OOB: {idx}:{fi}")
            ptr = _u32(b, face_off + F_TEX)
            delta = ptr - texbase
            if delta < 0 or delta % ST:
                obj_invalid += 1
                obj_hist[0] += 1
                continue
            ti = delta // ST
            if not (0 <= ti < nt):
                obj_invalid += 1
                obj_hist[0] += 1
                continue

            chain = []
            seen = set()
            bad = False
            while True:
                if ti in seen:
                    obj_cycles += 1
                    bad = True
                    break
                if not (0 <= ti < nt):
                    obj_invalid += 1
                    bad = True
                    break
                seen.add(ti)
                toff = t + ti * ST
                uvs = struct.unpack_from("<6f", b, toff)
                htex = _u32(b, toff + 24)
                nxt = _u32(b, toff + T_NEXT)
                chain.append((ti, uvs, htex))
                if nxt == 0:
                    break
                nd = nxt - texbase
                if nd < 0 or nd % ST:
                    obj_invalid += 1
                    bad = True
                    break
                ti = nd // ST
                if len(chain) > 16:
                    obj_invalid += 1
                    bad = True
                    break

            depth = len(chain) if not bad else 0
            obj_hist[depth] += 1
            obj_max = max(obj_max, depth)
            if depth > 1:
                obj_multilayer += 1
                first_uv = chain[0][1]
                if any(max(abs(a - b) for a, b in zip(first_uv, x[1])) > 1e-7 for x in chain[1:]):
                    obj_uv_diff += 1
                for a, c in zip(chain, chain[1:]):
                    obj_stride[int(c[2]) - int(a[2])] += 1

        total_faces += nf
        total_links += nt
        total_multilayer_faces += obj_multilayer
        invalid_chain_count += obj_invalid
        cycles += obj_cycles
        uv_difference_faces += obj_uv_diff
        max_layers = max(max_layers, obj_max)
        chain_hist.update(obj_hist)
        htexture_stride.update(obj_stride)
        rows.append({
            "index": idx,
            "name": node_name or info_name,
            "vertices": nv,
            "faces": nf,
            "texlinks": nt,
            "multilayer_faces": obj_multilayer,
            "chain_depth_histogram": {str(k): v for k, v in sorted(obj_hist.items())},
            "max_layers": obj_max,
            "uv_different_multilayer_faces": obj_uv_diff,
            "invalid_chains": obj_invalid,
            "cycles": obj_cycles,
            "htexture_stride_histogram": {str(k): v for k, v in sorted(obj_stride.items())},
        })

    return {
        "path": str(p),
        "sha256": hashlib.sha256(b).hexdigest(),
        "object_count": obj_count,
        "material_count": mat_count,
        "total_faces": total_faces,
        "total_texlinks": total_links,
        "multilayer_faces": total_multilayer_faces,
        "singlelayer_faces": max(0, total_faces - total_multilayer_faces),
        "chain_depth_histogram": {str(k): v for k, v in sorted(chain_hist.items())},
        "max_layers": max_layers,
        "uv_different_multilayer_faces": uv_difference_faces,
        "invalid_chain_count": invalid_chain_count,
        "cycle_count": cycles,
        "htexture_stride_histogram": {str(k): v for k, v in sorted(htexture_stride.items())},
        "objects": rows,
    }


def _copy_into_bundle(zf: zipfile.ZipFile, physical: pathlib.Path, arc: str):
    zf.write(physical, arcname=arc)


def _select_representatives(rows: list[dict], per_profile: int) -> list[dict]:
    selected = []
    seen = set()

    def add_group(keyfn, predicate=lambda r: True):
        groups = collections.defaultdict(list)
        for r in rows:
            if predicate(r):
                groups[keyfn(r)].append(r)
        for key in sorted(groups, key=lambda x: str(x)):
            group = sorted(
                groups[key],
                key=lambda r: (
                    r.get("invalid_chain_count", 0),
                    -r.get("multilayer_faces", 0),
                    r.get("relative_path", "").lower(),
                ),
            )
            for r in group[:per_profile]:
                rp = r["relative_path"].lower()
                if rp not in seen:
                    selected.append(r)
                    seen.add(rp)

    # Preserve category/mode coverage, plus partial-vs-full coverage and every
    # observed maximum layer depth.  These are evidence profiles, not binding
    # heuristics.
    add_group(lambda r: (r["category"], r["mode"]))
    add_group(lambda r: "FULL" if r["multilayer_faces"] == r["total_faces"] else "PARTIAL")
    add_group(lambda r: r["max_layers"])
    add_group(lambda r: "INVALID" if r["invalid_chain_count"] or r["cycle_count"] else "VALID")
    return selected


def audit_multilayer_texlink_corpus(records: list[dict], resolver, bundle: str | None = None, per_profile: int = 2) -> dict:
    candidates = [r for r in records if _candidate(r)]
    rows = []
    scan_errors = []

    for record in sorted(candidates, key=lambda r: norm_path(r.get("relative_path") or "").lower()):
        rel = norm_path(record.get("relative_path") or "")
        try:
            physical = resolver.resolve(rel)
            parsed = parse_texlink_file(physical)
            inv_faces = int(record.get("total_faces") or 0)
            inv_links = int(record.get("total_texlinks") or 0)
            row = {
                "relative_path": rel,
                "category": record.get("category_hint") or "UNKNOWN",
                "mode": _mode(record),
                "inventory_faces": inv_faces,
                "inventory_texlinks": inv_links,
                "inventory_extra_texlinks": inv_links - inv_faces,
                "texture_refs": [norm_path(x) for x in (record.get("texture_refs") or [])],
                **{k: v for k, v in parsed.items() if k not in {"path", "objects"}},
                "objects": parsed["objects"],
            }
            row["inventory_physical_counts_match"] = (
                row["total_faces"] == inv_faces and row["total_texlinks"] == inv_links
            )
            rows.append(row)
        except Exception as exc:
            scan_errors.append({
                "relative_path": rel,
                "error": f"{type(exc).__name__}: {exc}",
            })

    tag_counts = collections.Counter()
    category_counts = collections.Counter()
    mode_counts = collections.Counter()
    depth_counts = collections.Counter()
    stride_counts = collections.Counter()
    full_coverage = 0
    partial_coverage = 0
    valid_files = 0
    uv_distinct_files = 0

    for r in rows:
        category_counts[r["category"]] += 1
        mode_counts[r["mode"]] += 1
        depth_counts[r["max_layers"]] += 1
        for k, v in r.get("htexture_stride_histogram", {}).items():
            stride_counts[int(k)] += int(v)
        if r["multilayer_faces"] == r["total_faces"]:
            full_coverage += 1
            tag_counts["FULL_FACE_MULTILAYER"] += 1
        else:
            partial_coverage += 1
            tag_counts["PARTIAL_FACE_MULTILAYER"] += 1
        if r["uv_different_multilayer_faces"]:
            uv_distinct_files += 1
            tag_counts["DISTINCT_UV_STAGE"] += 1
        if r["max_layers"] == 2:
            tag_counts["TWO_LAYER"] += 1
        elif r["max_layers"] > 2:
            tag_counts["THREE_PLUS_LAYER"] += 1
        if r["invalid_chain_count"]:
            tag_counts["INVALID_CHAIN"] += 1
        if r["cycle_count"]:
            tag_counts["CHAIN_CYCLE"] += 1
        if not r["invalid_chain_count"] and not r["cycle_count"] and r["inventory_physical_counts_match"]:
            valid_files += 1

    selected = _select_representatives(rows, max(1, int(per_profile)))
    selected_paths = [r["relative_path"] for r in selected]

    bundle_path = None
    if bundle:
        bp = pathlib.Path(bundle).expanduser().resolve()
        bp.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": "PT_MULTILAYER_TEXLINK_REPS_V1",
            "source_audit_status": "PASS" if len(rows) + len(scan_errors) == len(candidates) else "FAIL",
            "selected": [],
            "audit_summary": {},
        }
        with zipfile.ZipFile(bp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            copied_tex = set()
            for r in selected:
                rel = r["relative_path"]
                physical = resolver.resolve(rel)
                arc_smd = "PT_MULTILAYER_TEXLINK_REPS/client/" + rel
                _copy_into_bundle(zf, physical, arc_smd)
                item = {
                    "relative_path": rel,
                    "category": r["category"],
                    "mode": r["mode"],
                    "max_layers": r["max_layers"],
                    "multilayer_faces": r["multilayer_faces"],
                    "total_faces": r["total_faces"],
                    "textures": [],
                }
                for tex in r.get("texture_refs") or []:
                    try:
                        tp = resolver.resolve(tex, required=False)
                    except Exception:
                        tp = None
                    if tp is None:
                        continue
                    key = norm_path(tex).lower()
                    if key not in copied_tex:
                        _copy_into_bundle(zf, tp, "PT_MULTILAYER_TEXLINK_REPS/client/" + norm_path(tex))
                        copied_tex.add(key)
                    item["textures"].append(norm_path(tex))
                manifest["selected"].append(item)
            # manifest filled below once summary exists
            pass
        bundle_path = str(bp)

    complete = (
        len(rows) == len(candidates)
        and not scan_errors
        and valid_files == len(candidates)
        and all(int(r.get("max_layers") or 0) == 2 for r in rows)
    )

    result = {
        "format": "PT_MULTILAYER_TEXLINK_PHYSICAL_CORPUS_AUDIT_V1",
        "status": "PASS" if len(rows) + len(scan_errors) == len(candidates) else "FAIL",
        "candidate_files_expected": len(candidates),
        "physical_files_audited": len(rows),
        "valid_chain_files": valid_files,
        "scan_errors": scan_errors,
        "tag_counts": dict(sorted(tag_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "max_layer_depth_counts": {str(k): v for k, v in sorted(depth_counts.items())},
        "htexture_stride_histogram": {str(k): v for k, v in sorted(stride_counts.items())},
        "full_face_multilayer_files": full_coverage,
        "partial_face_multilayer_files": partial_coverage,
        "distinct_uv_stage_files": uv_distinct_files,
        "three_plus_layer_files": sum(1 for r in rows if r["max_layers"] > 2),
        "invalid_chain_files": sum(1 for r in rows if r["invalid_chain_count"]),
        "cycle_files": sum(1 for r in rows if r["cycle_count"]),
        "inventory_physical_count_mismatch_files": sum(1 for r in rows if not r["inventory_physical_counts_match"]),
        "representatives": selected_paths,
        "multilayer_two_stage_complete_candidate": complete,
        "rows": rows,
    }

    if bundle:
        bp = pathlib.Path(bundle).expanduser().resolve()
        # Rewrite zip to add the final manifest without disturbing already
        # copied members.
        manifest = {
            "format": "PT_MULTILAYER_TEXLINK_REPS_V1",
            "source_audit_status": result["status"],
            "selected": [
                {
                    "relative_path": r["relative_path"],
                    "category": r["category"],
                    "mode": r["mode"],
                    "max_layers": r["max_layers"],
                    "multilayer_faces": r["multilayer_faces"],
                    "total_faces": r["total_faces"],
                    "texture_refs": r.get("texture_refs") or [],
                }
                for r in selected
            ],
            "audit_summary": {k: v for k, v in result.items() if k != "rows"},
        }
        with zipfile.ZipFile(bp, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "PT_MULTILAYER_TEXLINK_REPS/manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        result["bundle"] = bundle_path

    return result
