from __future__ import annotations

"""Candidate byte-preserving writer for Model0.62 static object-local keys.

Scope is deliberately preservation-first:
- existing ROT, POS or SCALE key only;
- frame/key counts, topology and every unrelated byte stay unchanged;
- segmented TmFrame layouts preserve their fixed-header frame tables while
  existing keys are patched in place;
- rotation edits rebuild the serialized cumulative TmPrevRot chain from the
  edited key onward using the client-compatible raw quaternion matrix rule.

This module is development evidence only and never authorizes client writes.
"""

import hashlib
import math
import os
import pathlib
import struct
import tempfile
from typing import Any

from .blender_workspace import asset_workspace_name
from .object_local import (
    parse_object_local_smd,
    SMD_OBJECT_SIZE,
    SMD_VERTEX_SIZE,
    SMD_FACE_SIZE,
    SMD_TEXLINK_SIZE,
    ROT_KEY_SIZE,
    POS_KEY_SIZE,
    SCALE_KEY_SIZE,
    PREVROT_SIZE,
    quat_to_matrix4_raw,
    matrix4_mul,
)

FORMAT = "PT_OBJECT_LOCAL_KEY_WRITER_CANDIDATE_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _array_offsets(obj: dict[str, Any]) -> tuple[int, int, int, int]:
    oi = int(obj["object_offset"])
    nv, nf, nt = int(obj["nVertex"]), int(obj["nFace"]), int(obj["nTexLink"])
    nr, np, ns = int(obj["nRot"]), int(obj["nPos"]), int(obj["nScale"])
    arr = oi + SMD_OBJECT_SIZE + nv*SMD_VERTEX_SIZE + nf*SMD_FACE_SIZE + nt*SMD_TEXLINK_SIZE
    pos_off = arr + nr*ROT_KEY_SIZE
    scale_off = pos_off + np*POS_KEY_SIZE
    prev_off = scale_off + ns*SCALE_KEY_SIZE
    return arr, pos_off, scale_off, prev_off


def _key_value_offset(obj: dict[str, Any], channel: str, key_index: int) -> tuple[int, int]:
    arr, pos_off, scale_off, _prev_off = _array_offsets(obj)
    nr, np, ns = int(obj["nRot"]), int(obj["nPos"]), int(obj["nScale"])
    channel = channel.upper()
    if channel == "ROT":
        if not 0 <= key_index < nr:
            raise IndexError(f"ROT key_index out of range: {key_index} / {nr}")
        return arr + key_index*ROT_KEY_SIZE + 4, 16
    if channel == "POS":
        if not 0 <= key_index < np:
            raise IndexError(f"POS key_index out of range: {key_index} / {np}")
        return pos_off + key_index*POS_KEY_SIZE + 4, 12
    if channel == "SCALE":
        if not 0 <= key_index < ns:
            raise IndexError(f"SCALE key_index out of range: {key_index} / {ns}")
        return scale_off + key_index*SCALE_KEY_SIZE + 4, 12
    raise ValueError("object-local candidate writer supports ROT, POS or SCALE")


def _pack_values(channel: str, values) -> bytes:
    channel = channel.upper()
    vals = tuple(float(x) for x in values)
    expected = 4 if channel == "ROT" else 3
    if len(vals) != expected or not all(math.isfinite(x) for x in vals):
        raise ValueError(f"object-local {channel} key value must be {expected} finite numbers")
    if channel == "ROT":
        norm = math.sqrt(sum(x*x for x in vals))
        if norm < 1e-8:
            raise ValueError("ROT candidate quaternion must be non-degenerate")
        return struct.pack("<4f", *vals)
    if channel == "POS":
        return struct.pack("<3f", *vals)
    if channel == "SCALE":
        raw=[]
        for value in vals:
            fixed=value*256.0
            rounded=round(fixed)
            if abs(fixed-rounded) > 1e-6:
                raise ValueError("SCALE candidate values must lie exactly on the 1/256 grid")
            if not -(2**31) <= rounded < 2**31:
                raise OverflowError("SCALE fixed-point value outside int32")
            raw.append(int(rounded))
        return struct.pack("<3i", *raw)
    raise ValueError(channel)


def _float32_matrix_bytes(matrix) -> tuple[bytes, tuple[tuple[float, ...], ...]]:
    flat=[float(matrix[r][c]) for r in range(4) for c in range(4)]
    packed=struct.pack("<16f", *flat)
    stored=struct.unpack("<16f", packed)
    return packed, tuple(tuple(float(stored[r*4+c]) for c in range(4)) for r in range(4))


def _rewrite_rotation_chain(after: bytearray, obj: dict[str, Any], key_index: int, values) -> tuple[set[int], bytes]:
    nr=int(obj["nRot"])
    if not 0 <= int(key_index) < nr:
        raise IndexError(f"ROT key_index out of range: {key_index} / {nr}")
    arr, _pos_off, _scale_off, prev_off = _array_offsets(obj)
    qoff=arr+int(key_index)*ROT_KEY_SIZE+4
    replacement=_pack_values("ROT", values)
    old_value=bytes(after[qoff:qoff+16])
    after[qoff:qoff+16]=replacement
    replacement_values=struct.unpack("<4f", replacement)

    previous=None
    if int(key_index) > 0:
        prev = obj["tm_prev_rot"][int(key_index)-1]["matrix"]
        previous=tuple(tuple(float(v) for v in row) for row in prev)

    allowed=set(range(qoff,qoff+16))
    for i in range(int(key_index), nr):
        q = replacement_values if i == int(key_index) else tuple(float(v) for v in obj["rot_keys"][i]["q_incremental_xyzw"])
        step=quat_to_matrix4_raw(q)
        matrix=step if i == 0 else matrix4_mul(previous, step)
        packed, previous=_float32_matrix_bytes(matrix)
        moff=prev_off+i*PREVROT_SIZE
        after[moff:moff+PREVROT_SIZE]=packed
        allowed.update(range(moff,moff+PREVROT_SIZE))
    return allowed, old_value


def patch_existing_object_local_key(
    source: str | pathlib.Path,
    output: str | pathlib.Path,
    *,
    object_index: int,
    channel: str,
    key_index: int,
    values,
    expected_source_sha256: str | None = None,
) -> dict[str, Any]:
    source = pathlib.Path(source).expanduser().resolve()
    output = pathlib.Path(output).expanduser().resolve()
    source_sha = _sha256(source)
    if expected_source_sha256 and source_sha.lower() != str(expected_source_sha256).lower():
        raise RuntimeError("object-local candidate source SHA256 drift")

    parsed_before = parse_object_local_smd(source, strict_v1=True)
    if not 0 <= int(object_index) < len(parsed_before["objects"]):
        raise IndexError(f"object_index out of range: {object_index}")
    obj = parsed_before["objects"][int(object_index)]
    channel = str(channel).upper()
    value_offset, value_size = _key_value_offset(obj, channel, int(key_index))
    replacement = _pack_values(channel, values)
    if len(replacement) != value_size:
        raise AssertionError("candidate key replacement size drift")

    before = source.read_bytes()
    after = bytearray(before)
    if channel == "ROT":
        allowed, old_value = _rewrite_rotation_chain(after, obj, int(key_index), values)
    else:
        old_value = bytes(after[value_offset:value_offset+value_size])
        after[value_offset:value_offset+value_size] = replacement
        allowed = set(range(value_offset, value_offset+value_size))

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpname = tempfile.mkstemp(prefix=output.name+".", suffix=".tmp", dir=str(output.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(after)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmpname, output)
    finally:
        try:
            os.unlink(tmpname)
        except FileNotFoundError:
            pass

    parsed_after = parse_object_local_smd(output, strict_v1=True)
    if len(before) != output.stat().st_size:
        raise RuntimeError("object-local candidate changed file size")
    changed = [i for i,(a,b) in enumerate(zip(before, output.read_bytes())) if a != b]
    outside = [i for i in changed if i not in allowed]
    if outside:
        raise RuntimeError(f"object-local candidate changed non-authorized bytes: {outside[:16]}")

    # Structural/hierarchy/key-count invariants must remain identical.
    invariants_before=[
        (x["name"],x["parent"],x["nVertex"],x["nFace"],x["nTexLink"],x["nRot"],x["nPos"],x["nScale"],x["TmFrameCnt"])
        for x in parsed_before["objects"]
    ]
    invariants_after=[
        (x["name"],x["parent"],x["nVertex"],x["nFace"],x["nTexLink"],x["nRot"],x["nPos"],x["nScale"],x["TmFrameCnt"])
        for x in parsed_after["objects"]
    ]
    if invariants_before != invariants_after:
        raise RuntimeError("object-local candidate structural invariants changed")

    target_after=parsed_after["objects"][int(object_index)]
    if channel == "ROT":
        semantic_after=list(target_after["rot_keys"][int(key_index)]["q_incremental_xyzw"])
    elif channel == "POS":
        semantic_after=list(target_after["pos_keys"][int(key_index)]["xyz"])
    else:
        semantic_after=list(target_after["scale_keys"][int(key_index)]["xyz"])

    return {
        "format": FORMAT,
        "status": "PASS",
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "source": str(source),
        "source_sha256": source_sha,
        "output": str(output),
        "output_sha256": _sha256(output),
        "object_index": int(object_index),
        "object_name": obj["name"],
        "channel": channel,
        "key_index": int(key_index),
        "frame": int((obj["rot_keys"] if channel == "ROT" else obj["pos_keys"] if channel == "POS" else obj["scale_keys"])[int(key_index)]["frame"]),
        "old_value_bytes": old_value.hex(),
        "new_value_bytes": replacement.hex(),
        "semantic_after": semantic_after,
        "allowed_byte_offset": value_offset,
        "allowed_byte_size": value_size,
        "authorized_byte_span_count": len(allowed),
        "tm_prev_rot_rebuilt_from_key": int(key_index) if channel == "ROT" else None,
        "changed_byte_count": len(changed),
        "all_non_authorized_bytes_byte_identical": not outside,
        "file_size_preserved": True,
        "structure_preserved": True,
        "segmented_tmframe_preserved": bool(int(obj.get("TmFrameCnt") or 0)),
        "rotation_candidate_writer_authorized": channel == "ROT",
        "key_insert_delete_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def audit_object_local_writer_corpus(project_root, registry, resolver, *, sample_limit: int = 25) -> dict[str, Any]:
    """Exercise candidate ROT/POS/SCALE edits across physical static Model0.62 assets.

    The client is opened read-only. Temporary candidate outputs live under
    ``pt_build/object_local_writer_audit`` and are removed after each row.
    Existing rotation keys are edited by rebuilding their TmPrevRot suffix.
    """
    import shutil

    project_root = pathlib.Path(project_root).resolve()
    work = project_root / "pt_build" / "object_local_writer_audit"
    work.mkdir(parents=True, exist_ok=True)
    rows=[]
    failures=[]
    physical_static=0
    strict_parse_pass=0
    editable_files=0
    rotation_only_files=0
    source_drift=[]

    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_STATIC":
            continue
        source = resolver.resolve(asset.primary_path, required=False)
        if source is None:
            continue
        source = pathlib.Path(source).resolve()
        physical_static += 1
        source_sha = _sha256(source)
        try:
            parsed = parse_object_local_smd(source, strict_v1=True)
            strict_parse_pass += 1
        except Exception as exc:
            rows.append({"asset":asset.primary_path,"status":"PARSE_SKIP","error":f"{type(exc).__name__}:{exc}"})
            continue

        choice=None
        for obj in parsed["objects"]:
            if obj["pos_keys"]:
                key=obj["pos_keys"][0]
                vals=list(key["xyz"]); vals[0]=float(vals[0])+0.125
                choice=(int(obj["index"]),"POS",0,vals)
                break
            if obj["scale_keys"]:
                key=obj["scale_keys"][0]
                vals=list(key["xyz"]); vals[0]=float(vals[0])+1.0/256.0
                choice=(int(obj["index"]),"SCALE",0,vals)
                break
            if obj["rot_keys"]:
                key=obj["rot_keys"][0]
                vals=list(key["q_incremental_xyzw"])
                # Deterministic small perturbation; preserve non-unit legacy magnitude.
                vals[0]=float(vals[0])+0.001
                choice=(int(obj["index"]),"ROT",0,vals)
                rotation_only_files += 1
                break
        if choice is None:
            continue

        editable_files += 1
        oi,channel,ki,vals=choice
        out = work / (asset_workspace_name(asset.primary_path)+"__audit.smd")
        try:
            result=patch_existing_object_local_key(
                source,out,object_index=oi,channel=channel,key_index=ki,values=vals,
                expected_source_sha256=source_sha,
            )
            ok=(
                result.get("status")=="PASS"
                and result.get("all_non_authorized_bytes_byte_identical") is True
                and result.get("structure_preserved") is True
                and result.get("production_authorized") is False
            )
            row={
                "asset":asset.primary_path,"status":"PASS" if ok else "FAIL",
                "channel":channel,"object_index":oi,"key_index":ki,
                "changed_byte_count":result.get("changed_byte_count"),
            }
            rows.append(row)
            if not ok:
                failures.append(row)
        except Exception as exc:
            row={"asset":asset.primary_path,"status":"FAIL","channel":channel,"error":f"{type(exc).__name__}:{exc}"}
            rows.append(row); failures.append(row)
        finally:
            try: out.unlink()
            except FileNotFoundError: pass
        if _sha256(source) != source_sha:
            source_drift.append(asset.primary_path)
        if sample_limit and editable_files >= int(sample_limit):
            break

    try:
        if not any(work.iterdir()):
            work.rmdir()
    except Exception:
        pass

    if failures or source_drift:
        status="FAIL"
    elif editable_files:
        status="PASS"
    else:
        status="EMPTY"
    return {
        "format":"PT_OBJECT_LOCAL_WRITER_CORPUS_AUDIT_V1",
        "status":status,
        "scope":"CANDIDATE_PT_BUILD_ONLY_EXISTING_ROT_POS_SCALE_KEYS",
        "physical_static_assets_scanned":physical_static,
        "strict_parser_pass_assets":strict_parse_pass,
        "editable_file_count":editable_files,
        "pass_count":sum(1 for x in rows if x.get("status")=="PASS"),
        "failure_count":len(failures),
        "rotation_only_file_count":rotation_only_files,
        "source_drift_count":len(source_drift),
        "failures":failures[:max(1,int(sample_limit or 25))],
        "rows":rows[:max(1,int(sample_limit or 25))],
        "production_authorized":False,
        "client_write_authorized":False,
        "client_modified":False,
    }
