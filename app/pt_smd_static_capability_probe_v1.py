#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO = 556, 40, 2236
SV, SF, ST, SR, SP, SS, SM = 24, 36, 32, 20, 16, 16, 64
O_PHYS, O_NV, O_NF, O_NT = 16, 84, 88, 92
O_NAME, O_NR, O_NP, O_NS = 172, 684, 688, 692
F_TEX, T_NEXT = 32, 28

def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]

def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

def cstr(b):
    return b.split(b"\0", 1)[0].decode("latin1", "replace")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smd", required=True)
    ap.add_argument("--report")
    a = ap.parse_args()

    p = Path(a.smd).expanduser().resolve()
    b = p.read_bytes()
    if len(b) < SH or not b.startswith(HEADER):
        raise ValueError("not SMD Model data Ver 0.62")

    n, mat_count = struct.unpack_from("<ii", b, 24)
    infos = []
    for idx in range(n):
        off = SH + idx * SI
        name = cstr(b[off : off + 32])
        length, start = struct.unpack_from("<ii", b, off + 32)
        infos.append((idx, name, length, start))

    rows = []
    for idx, name, length, start in infos:
        raw = b[start : start + SO]
        node = cstr(raw[O_NAME : O_NAME + 32])
        nv, nf, nt = struct.unpack_from("<iii", raw, O_NV)
        nr, np, ns = struct.unpack_from("<iii", raw, O_NR)
        phys = u32(raw, O_PHYS) != 0

        v = start + SO
        f = v + nv * SV
        t = f + nf * SF
        r = t + nt * ST
        pos = r + nr * SR
        scale = pos + np * SP
        prev = scale + ns * SS
        end = prev + nr * SM + (nv * 32 if phys else 0)

        blockers = []
        if node != name:
            blockers.append("NODE_NAME_MISMATCH")
        if end != start + length:
            blockers.append("SERIALIZED_LENGTH_MISMATCH")
        if phys:
            blockers.append("HAS_PHYSIQUE_NOT_STATIC")
        if nr or np or ns:
            blockers.append(f"OBJECT_LOCAL_ANIMATION:{nr}/{np}/{ns}")
        if not 3 <= nv <= 30000:
            blockers.append(f"VERTEX_COUNT:{nv}")
        if not 1 <= nf <= 30000:
            blockers.append(f"FACE_COUNT:{nf}")

        texbase = u32(raw, 12)
        used_texlinks = []
        for fi in range(max(0, nf)):
            off = f + fi * SF
            a0, a1, a2, _mat = struct.unpack_from("<4H", b, off)
            if max(a0, a1, a2) >= nv:
                blockers.append(f"FACE_INDEX_OOB:{fi}")
                continue
            ptr = u32(b, off + F_TEX)
            delta = ptr - texbase
            if delta < 0 or delta % ST:
                blockers.append(f"BAD_TEX_PTR:{fi}")
                continue
            ti = delta // ST
            if not 0 <= ti < nt:
                blockers.append(f"TEX_OOB:{fi}")
                continue
            used_texlinks.append(ti)
            if u32(b, t + ti * ST + T_NEXT) != 0:
                blockers.append(f"MULTILAYER_TEXLINK:{fi}")

        blockers = list(dict.fromkeys(blockers))
        rows.append({
            "index": idx,
            "name": name,
            "vertices": nv,
            "faces": nf,
            "texlinks": nt,
            "material_count_header": mat_count,
            "physique": phys,
            "rot_keys": nr,
            "pos_keys": np,
            "scale_keys": ns,
            "referenced_texlinks": len(set(used_texlinks)),
            "static_edit_v1_ready": not blockers,
            "blockers": blockers,
        })

    ready = [x["name"] for x in rows if x["static_edit_v1_ready"]]
    blocked = [x["name"] for x in rows if not x["static_edit_v1_ready"]]
    result = {
        "tool": "PT_SMD_STATIC_CAPABILITY_PROBE_V1",
        "smd": str(p),
        "sha256": hashlib.sha256(b).hexdigest(),
        "object_count": n,
        "material_count": mat_count,
        "ready_objects": ready,
        "blocked_objects": blocked,
        "objects": rows,
        "client_modified": False,
        "static_capability_probe_check": "PASS",
    }

    rp = (
        Path(a.report).expanduser().resolve()
        if a.report else p.with_suffix(".static_capability.json")
    )
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("PT_SMD_STATIC_CAPABILITY_PROBE_V1")
    print(f"objects={n}")
    print(f"ready_count={len(ready)}")
    print(f"blocked_count={len(blocked)}")
    print(f"ready_objects={ready}")
    print(f"blocked_objects={blocked}")
    print(f"report={rp}")
    print("client_modified=False")
    print("static_capability_probe_check=PASS")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"static_capability_probe_check=FAIL: {type(exc).__name__}: {exc}")
        raise
