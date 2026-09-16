from __future__ import annotations
import importlib.util, json, pathlib, types


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod




# Minimal INX header reader used by registry-time config-only binding.
# Kept here so AssetRegistry can use the same runtime keyword semantics without
# loading the full legacy SMB evaluator.
_INX_LINK_LAYOUTS = {
    95268: {"motion_size": 172},
    67084: {"motion_size": 120},
}
_INX_OFF_MOTIONINFO = 0x18C
_INX_MOTION_INFO_MAX = 512

def _inx_u32(data: bytes, off: int) -> int:
    import struct
    return struct.unpack_from("<I", data, off)[0]

def inx_speed_sum(text: str) -> int:
    raw=text.encode("latin1")
    sum2=dwsum=cnt=0
    for ch in raw:
        if ch == 0:
            break
        value=ch-0x20 if 97 <= ch <= 122 else ch
        sum2=(sum2 + value*(cnt+1)) & 0xffffffff
        dwsum=(dwsum + value*(cnt*cnt)) & 0xffffffff
        cnt += 1
    return ((dwsum << 24) | (cnt << 16) | sum2) & 0xffffffff

def _inx_reconstruct_codes(file_type_kw: int, link_kw: int, has_link: bool):
    dword=lambda v: v & 0xffffffff
    if has_link:
        file_code=dword((link_kw&0xFF000000)|((file_type_kw&0xFF000000)>>8)|(link_kw&0x0000FF00)|((file_type_kw&0x0000FF00)>>8))
        link_code=dword(((file_type_kw&0xFF)<<24)|((link_kw&0xFF)<<16)|((link_kw&0x00FF0000)>>8)|((file_type_kw&0x00FF0000)>>16))
        return file_code, link_code
    return dword(((file_type_kw&0xFF000000)>>16)|((file_type_kw&0x00FF0000)<<8)|((file_type_kw&0x0000FF00)>>8)|((file_type_kw&0xFF)<<16)), None

def parse_inx_link_header(path: pathlib.Path) -> dict:
    """Read the canonical INX file/link identity fields only.

    Real player config INX files store a linked root path ending in ``.in``.
    The final ``x`` is omitted from the serialized C string, while ``link_code``
    is calculated from the full ``.inx`` path.  Callers must still verify that
    the reconstructed target exists and that its own ``file_code`` matches.
    """
    import struct
    path=pathlib.Path(path)
    size=path.stat().st_size
    layout=_INX_LINK_LAYOUTS.get(size)
    if not layout:
        raise ValueError(f"unsupported INX size={size}; known={sorted(_INX_LINK_LAYOUTS)}")
    motion_count_off=_INX_OFF_MOTIONINFO + _INX_MOTION_INFO_MAX*layout["motion_size"]
    with path.open("rb") as f:
        f.seek(motion_count_off)
        tail=f.read(4+4+4+64)
    if len(tail) < 76:
        raise ValueError("truncated INX identity tail")
    motion_count=struct.unpack_from("<I",tail,0)[0]
    file_type_kw=struct.unpack_from("<I",tail,4)[0]
    link_kw=struct.unpack_from("<I",tail,8)[0]
    raw=tail[12:76].split(b"\0",1)[0]
    link_file=raw.decode("latin1","replace")
    file_code,link_code=_inx_reconstruct_codes(file_type_kw,link_kw,bool(link_file))
    return {
        "file_size": size,
        "motion_count": motion_count,
        "file_code": file_code,
        "link_code": link_code,
        "link_file": link_file,
    }

def verified_inx_link_target(path: pathlib.Path) -> dict:
    """Return a cryptographically-coded logical target for an INX link.

    The runtime's SpeedSum-style code is used as the integrity check.  No
    basename, directory, or class-name heuristic participates in the result.
    """
    info=parse_inx_link_header(path)
    raw=str(info.get("link_file") or "")
    code=info.get("link_code")
    if not raw or code is None:
        return {**info, "status":"NO_LINK", "target":""}
    candidates=[]
    low=raw.casefold()
    if low.endswith(".in"):
        candidates.append(raw+"x")
    elif low.endswith(".ini"):
        candidates.append(raw[:-1]+"x")
    elif low.endswith(".inx"):
        candidates.append(raw)
    else:
        candidates.append(raw)
    matched=[c for c in candidates if inx_speed_sum(c)==int(code)]
    if len(matched) != 1:
        return {**info, "status":"LINK_CODE_MISMATCH", "target":"", "candidate_targets":candidates}
    return {**info, "status":"VERIFIED", "target":matched[0]}

def _load_evaluator_without_cli(path: pathlib.Path):
    source=path.read_text(encoding="utf-8")
    stripped=source.rstrip()
    if not stripped.endswith("main()"):
        raise RuntimeError(f"unexpected evaluator footer; refusing unsafe import: {path}")
    source=stripped[:-len("main()")]+"\n"
    mod=types.ModuleType("pt_legacy_motion_eval_safe")
    mod.__file__=str(path)
    exec(compile(source,str(path),"exec"),mod.__dict__)
    return mod

def load_smb_evaluator(root: pathlib.Path):
    """Load only the legacy SMB evaluator/parser without importing its CLI."""
    root = pathlib.Path(root)
    evaluator = _load_evaluator_without_cli(root / "pt_asset_tool/legacy_runtime/pt_smb_motion_evaluator_v1.py")
    _legacy_slerp = evaluator.quaternion_slerp_source

    def _slerp_null_is_identity(ax, ay, az, aw, bx, by, bz, bw, alpha):
        if ax == 0.0 and ay == 0.0 and az == 0.0 and aw == 0.0:
            aw = 1.0
        return _legacy_slerp(ax, ay, az, aw, bx, by, bz, bw, alpha)

    evaluator.quaternion_slerp_source = _slerp_null_is_identity
    evaluator.pt_null_quaternion_semantics = "IDENTITY"
    return evaluator


def _flatten_numeric_matrix(value):
    """Flatten legacy matrix payloads without assuming flat vs row-major storage."""
    if value is None:
        return []
    out=[]
    def walk(v):
        if isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        else:
            out.append(float(v))
    walk(value)
    return out


def smb_skeleton_signature(smb: dict, precision: int = 6) -> dict:
    """Return stable topology+bind signatures for the skeleton embedded in an SMB.

    Animation payload is intentionally excluded. Root bones in the legacy parser
    may expose ``parent_index=None``; that is canonicalized to -1. If a non-root
    bone omits the numeric parent index, its parent name is used to recover the
    hierarchy. Matrix payloads are accepted both flat and nested.
    """
    import hashlib
    bones = smb.get("bones") or []
    names=[str(b.get("name") or "") for b in bones]
    name_to_index={n.casefold():i for i,n in enumerate(names) if n}

    def parent_of(b):
        raw=b.get("parent_index")
        if raw not in (None, ""):
            return int(raw)
        pname=str(b.get("parent_name") or "").strip()
        if pname and pname.casefold() in name_to_index:
            return int(name_to_index[pname.casefold()])
        return -1

    topo=[]
    bind=[]
    roots=[]
    for i,b in enumerate(bones):
        name=names[i]
        parent_name=str(b.get("parent_name") or "")
        parent_index=parent_of(b)
        topo.append([i, name.casefold(), parent_index, parent_name.casefold()])
        tm=b.get("tm")
        if tm in (None, []):
            # Some dialects keep the same bind information in tminvert/tmrotate.
            # Keep those fields separate in the signature instead of fabricating
            # a matrix. This is identity evidence only; it is never used to pose.
            matrix_source={
                "tm": [],
                "tminvert": _flatten_numeric_matrix(b.get("tminvert")),
                "tmrotate": _flatten_numeric_matrix(b.get("tmrotate")),
            }
            vals=matrix_source
        else:
            vals=_flatten_numeric_matrix(tm)

        def norm_seq(seq):
            out=[]
            for v in seq:
                fv=float(v)
                if abs(fv) < 0.5 * (10 ** (-precision)):
                    fv=0.0
                out.append(round(fv, precision))
            return out

        if isinstance(vals, dict):
            bind_value={k:norm_seq(v) for k,v in vals.items()}
        else:
            bind_value=norm_seq(vals)
        bind.append([i, name.casefold(), parent_index, bind_value])
        if parent_index < 0:
            roots.append(name)

    tm_sort=[]
    for x in (smb.get("tm_sort") or []):
        if x in (None, ""):
            continue
        tm_sort.append(int(x))
    topo_blob=json.dumps({"bones":topo,"tm_sort":tm_sort}, ensure_ascii=False, separators=(",",":"), sort_keys=True).encode("utf-8")
    bind_blob=json.dumps({"bones":bind,"tm_sort":tm_sort}, ensure_ascii=False, separators=(",",":"), sort_keys=True).encode("utf-8")
    return {
        "bone_count": len(bones),
        "topology_signature": hashlib.sha256(topo_blob).hexdigest(),
        "skeleton_signature": hashlib.sha256(bind_blob).hexdigest(),
        "root_bones": roots,
    }


def load_motion_system(root: pathlib.Path):
    root = pathlib.Path(root)
    evaluator = load_smb_evaluator(root)
    inxcore = _load(root / "pt_inx_motion_core_v2.py", "pt_inx_motion_core_v2_runtime")
    return evaluator, inxcore


def enrich_motions(inx_parsed: dict, smb: dict) -> list[dict]:
    out=[]
    for src in inx_parsed["motions"]:
        m=dict(src)
        mf=int(m.get("motion_frame") or 0)
        if mf <= 0:
            m["active_container"] = False
            out.append(m); continue
        slot=mf-1
        if not 0 <= slot < len(smb["header_frames"]):
            raise RuntimeError(f"motion[{m['index']}] slot={slot} outside SMB TmFrameCounter={len(smb['header_frames'])}")
        container=smb["header_frames"][slot]
        base=container["start"]//160
        m.update({
            "active_container": True,
            "slot": slot,
            "global_start": int(m["start"])+base,
            "global_end": int(m["end"])+base,
        })
        m["engine_start"]=m["global_start"]*160
        m["engine_end"]=m["global_end"]*160
        if m["engine_end"] > container["end"]:
            raise RuntimeError(f"motion[{m['index']}] engine_end={m['engine_end']} > container_end={container['end']}")
        if m["global_end"] <= m["global_start"]:
            m["active_container"] = False
        out.append(m)
    return out


def action_name(m: dict) -> str:
    return f"PT_{m['state_name']}_{int(m['index']):03d}"


def select_motion(motions: list[dict], selector: str = "auto") -> dict:
    active=[m for m in motions if m.get("active_container")]
    if not active:
        raise RuntimeError("INX has no active motion with SMB container")
    q=str(selector or "auto").strip()
    if q.lower()=="auto":
        for state in ("STAND","WALK","RUN","ATTACK","DAMAGE","DEAD"):
            hit=next((m for m in active if m.get("state_name")==state),None)
            if hit: return hit
        return active[0]
    if q.isdigit():
        idx=int(q); hit=next((m for m in active if int(m["index"])==idx),None)
        if not hit: raise RuntimeError(f"active motion index not found: {idx}")
        return hit
    uq=q.upper()
    exact=[m for m in active if str(m.get("state_name","")).upper()==uq]
    if exact: return exact[0]
    contains=[m for m in active if uq in str(m.get("state_name","")).upper()]
    if len(contains)==1: return contains[0]
    raise RuntimeError(f"motion selector not found/ambiguous: {selector}")


def core_motion_subset(motions: list[dict]) -> list[dict]:
    active=[m for m in motions if m.get("active_container")]
    picked=[]; seen=set()
    for state in ("STAND","WALK","RUN","ATTACK","DAMAGE","DEAD","FALLDOWN","SKILL"):
        m=next((x for x in active if x.get("state_name")==state),None)
        if m and m["index"] not in seen:
            picked.append(m); seen.add(m["index"])
    return picked or active[:1]


def _flatten4(m):
    return [float(m[r][c]) for r in range(4) for c in range(4)]


_STAND_BIND_LOCAL_GUARD_BONES = ("Bip01 Neck", "Bip01 Head")


def _apply_monbagon_stand_bind_local_guard(results, smb, smb_path: pathlib.Path, motion: dict):
    """Stabilize only the previously observed bad STAND neck/head chain.

    V0.2.8 proved that rebasing the whole STAND container is wrong: it made
    the visual deformation worse even though Source Direct and Blender agreed.
    Keep the original/global source pose for every other bone and every other
    motion. For Monbagon STAND only, reconstruct Neck and Head at their bind
    local relationship to the *current* parent. This removes malformed local
    animation on that two-bone chain while still following the animated torso.

    Source matrices are row-major / row-vector style, so:
        bind_local = bind_child @ inverse(bind_parent)
        current_child = bind_local @ current_parent
    """
    if str(motion.get("state_name", "")).upper() != "STAND":
        return results, []
    if "monbagon" not in pathlib.Path(smb_path).name.lower():
        return results, []

    bones=smb["bones"]
    name_to_index={str(b.get("name", "")): i for i,b in enumerate(bones)}
    mats=[_mat4(v) for v in results]
    binds=[_mat4(b["tm"]) for b in bones]
    applied=[]
    for name in _STAND_BIND_LOCAL_GUARD_BONES:
        idx=name_to_index.get(name)
        if idx is None:
            continue
        parent_index=int(bones[idx].get("parent_index", -1))
        if parent_index < 0 or parent_index >= len(mats):
            continue
        bind_local=_matmul(binds[idx], _matinv(binds[parent_index]))
        mats[idx]=_matmul(bind_local, mats[parent_index])
        applied.append(name)
    return [_flatten4(m) for m in mats], applied


def _smb_track_key_counts(smb: dict) -> dict[str, int]:
    return {
        "rot": sum(len(b.get("rot") or []) for b in smb.get("bones") or []),
        "pos": sum(len(b.get("pos") or []) for b in smb.get("bones") or []),
        "scale": sum(len(b.get("scale") or []) for b in smb.get("bones") or []),
    }


def build_bake_payload(root: pathlib.Path, inx: pathlib.Path, smb_path: pathlib.Path, *, selector="auto", load_actions="core", fps=30) -> dict:
    evaluator, inxcore=load_motion_system(root)
    smb=evaluator.parse_smb(pathlib.Path(smb_path))
    parsed=inxcore.parse_inx(pathlib.Path(inx))
    validation=inxcore.validate_with_smb(parsed, pathlib.Path(smb_path))
    if validation["check"] != "PASS":
        raise RuntimeError(f"INX/SMB validation failed: {validation['errors']}")
    motions=enrich_motions(parsed, smb)
    selected=select_motion(motions, selector)
    active=[m for m in motions if m.get("active_container")]
    if load_actions == "selected": chosen=[selected]
    elif load_actions == "core": chosen=core_motion_subset(motions)
    elif load_actions == "all": chosen=active
    else: raise ValueError("load_actions must be selected/core/all")
    if selected["index"] not in {m["index"] for m in chosen}:
        chosen=[selected]+chosen
    actions=[]
    for m in chosen:
        frames=[]
        guard_bones=[]
        for bf, logical in enumerate(range(m["global_start"], m["global_end"]), start=1):
            engine=logical*160
            results, _, _, stats=evaluator.evaluate_pose(smb, engine, m["engine_end"])
            results, applied=_apply_monbagon_stand_bind_local_guard(results, smb, smb_path, m)
            if applied:
                guard_bones=applied
            frames.append({"frame":bf,"engine_frame":engine,"matrices":results})
        actions.append({
            "name": action_name(m), "index":m["index"], "state":m["state"], "state_name":m["state_name"],
            "repeat":m["repeat"], "motion_frame":m["motion_frame"], "global_start":m["global_start"],
            "global_end":m["global_end"], "engine_start":m["engine_start"], "engine_end":m["engine_end"],
            "frame_count":len(frames), "frames":frames,
            "source_pose_reference":"GLOBAL_BIND",
            "pose_guard":"MONBAGON_STAND_BIND_LOCAL_V1" if guard_bones else "NONE",
            "pose_guard_bones":guard_bones,
        })
    bones=[{"name":b["name"],"parent":b["parent_name"],"bind_tm":b["tm"]} for b in smb["bones"]]
    return {
        "format":"PT_ASSET_MOTION_BAKE_V1", "inx":str(inx), "smb":str(smb_path), "fps":int(fps),
        "selected_action":action_name(selected), "selected_motion_index":selected["index"],
        "load_actions":load_actions, "motion_count":parsed["motion_count"], "active_motion_count":len(active),
        "actions":actions, "bones":bones, "tm_sort":list(smb["tm_sort"]),
        "quaternion_null_semantics":"IDENTITY",
        "source_pose_reference_policy":"GLOBAL_BIND",
        "pose_guard_policy":"MONBAGON_STAND_BIND_LOCAL_V1",
        "track_key_counts": _smb_track_key_counts(smb),
        "client_modified":False,
    }



def build_standalone_smb_bake_payload(
    root: pathlib.Path, smb_path: pathlib.Path, *, fps: int = 30,
    max_actions: int = 4, max_frames_per_action: int = 120,
) -> dict:
    """Build a Blender pose payload directly from existing SMB containers.

    Standalone EFFECT/MAP skeletons often have no INX MotionInfo.  Their SMB
    TmFrame containers are still authoritative animation data, so this path
    evaluates those containers directly instead of inventing motion states or
    a synthetic INX.  Sampling is deterministic and bounded for devtest use.
    """
    root = pathlib.Path(root)
    smb_path = pathlib.Path(smb_path).resolve()
    evaluator = load_smb_evaluator(root)
    smb = evaluator.parse_smb(smb_path)
    active = [
        dict(row) for row in (smb.get("header_frames") or [])
        if int(row.get("end") or 0) > int(row.get("start") or 0)
    ]
    if not active:
        raise RuntimeError(f"standalone SMB has no active TmFrame containers: {smb_path}")
    actions = []
    for container in active[: max(1, int(max_actions))]:
        slot = int(container.get("slot") or 0)
        start = int(container["start"]); end = int(container["end"])
        logical_start = start // 160
        logical_end = end // 160
        logical_frames = list(range(logical_start, logical_end))
        if not logical_frames:
            logical_frames = [logical_start]
        limit = max(1, int(max_frames_per_action))
        if len(logical_frames) > limit:
            # Evenly-spaced deterministic sample including both ends.
            last = len(logical_frames) - 1
            idxs = sorted({round(i * last / (limit - 1)) for i in range(limit)}) if limit > 1 else [0]
            logical_frames = [logical_frames[i] for i in idxs]
        frames = []
        for scene_frame, logical in enumerate(logical_frames, start=1):
            engine = int(logical) * 160
            results, _, _, _stats = evaluator.evaluate_pose(smb, engine, end)
            frames.append({
                "frame": scene_frame, "engine_frame": engine,
                "matrices": results,
            })
        name = f"PT_SMB_SLOT_{slot:02d}"
        actions.append({
            "name": name, "index": slot, "state": 0,
            "state_name": f"SMB_SLOT_{slot:02d}", "repeat": 0,
            "motion_frame": slot + 1,
            "global_start": logical_start, "global_end": logical_end,
            "engine_start": start, "engine_end": end,
            "frame_count": len(frames), "frames": frames,
            "source_pose_reference": "GLOBAL_BIND",
            "pose_guard": "NONE", "pose_guard_bones": [],
        })
    bones = [{"name":b["name"], "parent":b["parent_name"], "bind_tm":b["tm"]} for b in smb["bones"]]
    return {
        "format": "PT_ASSET_MOTION_BAKE_V1",
        "source_mode": "STANDALONE_SMB_TMFRAME",
        "inx": "", "smb": str(smb_path), "fps": int(fps),
        "selected_action": actions[0]["name"],
        "selected_motion_index": actions[0]["index"],
        "load_actions": "smb_containers",
        "motion_count": len(active), "active_motion_count": len(active),
        "actions": actions, "bones": bones, "tm_sort": list(smb["tm_sort"]),
        "quaternion_null_semantics": "IDENTITY",
        "source_pose_reference_policy": "GLOBAL_BIND",
        "pose_guard_policy": "NONE",
        "track_key_counts": _smb_track_key_counts(smb),
        "client_modified": False,
    }

def write_payload(path: pathlib.Path, data: dict):
    path=pathlib.Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")


def _mat4(values):
    if len(values) != 16:
        raise ValueError("matrix must contain 16 values")
    return [list(map(float, values[i:i+4])) for i in range(0, 16, 4)]


def _matmul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _matinv(a):
    aug=[list(map(float,row))+[1.0 if r==c else 0.0 for c in range(4)] for r,row in enumerate(a)]
    for c in range(4):
        pivot=max(range(c,4), key=lambda r: abs(aug[r][c]))
        if abs(aug[pivot][c]) < 1e-12:
            raise ValueError("singular matrix")
        if pivot != c:
            aug[c], aug[pivot] = aug[pivot], aug[c]
        d=aug[c][c]
        aug[c]=[x/d for x in aug[c]]
        for r in range(4):
            if r == c: continue
            f=aug[r][c]
            if f:
                aug[r]=[aug[r][j]-f*aug[c][j] for j in range(8)]
    return [row[4:] for row in aug]


def _rigid_quality(m):
    # Source matrices are row-major. Assess the upper-left 3x3 basis without
    # assuming whether basis vectors are stored in rows or columns: use rows,
    # which is invariant enough for scale/shear detection on orthogonal matrices.
    v=[m[i][:3] for i in range(3)]
    norms=[sum(x*x for x in q) ** 0.5 for q in v]
    scale_dev=max(abs(x-1.0) for x in norms)
    dots=[]
    for i,j in ((0,1),(0,2),(1,2)):
        dots.append(abs(sum(v[i][k]*v[j][k] for k in range(3))))
    orth=max(dots)
    a,b,c=v
    det=(a[0]*(b[1]*c[2]-b[2]*c[1])
         -a[1]*(b[0]*c[2]-b[2]*c[0])
         +a[2]*(b[0]*c[1]-b[1]*c[0]))
    return {"scale_dev":scale_dev,"orth_error":orth,"det":det,"det_dev":abs(abs(det)-1.0)}


def prepare_motion_source_audit(root: pathlib.Path, inx: pathlib.Path, smb_path: pathlib.Path) -> dict:
    """Parse one INX/SMB context and precompute invariants exactly once.

    Corpus-level source regression may audit tens or hundreds of motions from the
    same files.  The legacy path reparsed both files and inverted every bind
    matrix once per selected motion.  This prepared context preserves the exact
    evaluator and matrix math while removing that repeated setup.
    """
    evaluator, inxcore=load_motion_system(root)
    smb=evaluator.parse_smb(pathlib.Path(smb_path))
    parsed=inxcore.parse_inx(pathlib.Path(inx))
    motions=enrich_motions(parsed, smb)
    bind=[_mat4(b["tm"]) for b in smb["bones"]]
    return {
        "evaluator":evaluator,
        "inxcore":inxcore,
        "smb":smb,
        "parsed":parsed,
        "motions":motions,
        "active":[m for m in motions if m.get("active_container")],
        "bind_inv":[_matinv(x) for x in bind],
        "names":[b["name"] for b in smb["bones"]],
        # Populated by corpus-level callers only for pose keys that repeat.
        "pose_cache_keys":set(),
        "pose_cache":{},
    }


def analyze_prepared_motion(prepared: dict, motion: dict) -> dict:
    """Analyze one motion using a context returned by prepare_motion_source_audit."""
    evaluator=prepared["evaluator"]
    smb=prepared["smb"]
    bind_inv=prepared["bind_inv"]
    names=prepared["names"]
    m=motion
    worst={"score":-1.0}
    first=None; last=None
    frames=0
    bone_worst={}
    for bf, logical in enumerate(range(m["global_start"], m["global_end"]), start=1):
        engine=logical*160
        pose_key=(int(engine),int(m["engine_end"]))
        cache_keys=prepared.get("pose_cache_keys") or set()
        pose_cache=prepared.get("pose_cache") if isinstance(prepared.get("pose_cache"),dict) else {}
        if pose_key in cache_keys and pose_key in pose_cache:
            results=pose_cache[pose_key]
        else:
            results, _, _, _=evaluator.evaluate_pose(smb, engine, m["engine_end"])
            if pose_key in cache_keys:
                # Store only the transform list used below; diagnostics from the
                # evaluator are not consumed by this source-rigidity audit.
                pose_cache[pose_key]=results
        frames += 1
        # Exact-rigid frames legitimately have score==0 for every bone. Start
        # below the metric domain so the first zero-score bone becomes a valid
        # witness instead of leaving frame_info=None.
        frame_max=-1.0
        frame_info=None
        for i, vals in enumerate(results):
            cur=_mat4(vals)
            delta=_matmul(cur, bind_inv[i])
            q=_rigid_quality(delta)
            score=max(q["scale_dev"],q["orth_error"],q["det_dev"])
            if score > frame_max:
                frame_max=score; frame_info=(i,q)
            prev=bone_worst.get(i)
            if prev is None or score > prev[0]:
                bone_worst[i]=(score,bf,engine,q)
        if first is None: first=frame_max
        last=frame_max
        if frame_max > worst.get("score",-1):
            i,q=frame_info
            worst={"score":frame_max,"frame":bf,"engine_frame":engine,"bone":names[i],**q}
    tops=sorted(bone_worst.items(),key=lambda kv:kv[1][0],reverse=True)[:10]
    return {
        "index":int(m["index"]),"state":m["state_name"],"repeat":int(m["repeat"]),
        "motion_frame":int(m["motion_frame"]),"global_start":int(m["global_start"]),"global_end":int(m["global_end"]),
        "engine_start":int(m["engine_start"]),"engine_end":int(m["engine_end"]),"frames":frames,
        "first_frame_rigidity_score":first,"last_frame_rigidity_score":last,
        "worst_rigidity":worst,
        "top_bones":[{"bone":names[i],"score":v[0],"frame":v[1],"engine_frame":v[2],**v[3]} for i,v in tops],
    }


def audit_motion_source(root: pathlib.Path, inx: pathlib.Path, smb_path: pathlib.Path, selector="STAND", *, include_reference_states: bool = True) -> dict:
    prepared=prepare_motion_source_audit(root, inx, smb_path)
    motions=prepared["motions"]
    selected=select_motion(motions, selector)
    active=prepared["active"]

    # Direct diagnostics keep WALK/ATTACK comparison by default. Corpus-level
    # callers that already iterate every chosen motion can disable these
    # references to avoid evaluating WALK/ATTACK again for every selected row.
    references = [x for x in active if x.get("state_name") in ("WALK", "ATTACK")] if include_reference_states else []
    picked=[]; seen=set()
    for m in [selected] + references:
        if m["index"] in seen: continue
        seen.add(m["index"]); picked.append(m)
    return {
        "format":"PT_SOURCE_MOTION_AUDIT_V1",
        "selected_motion_index":int(selected["index"]),
        "selected_state":selected["state_name"],
        "bone_count":len(prepared["names"]),
        "motions":[analyze_prepared_motion(prepared,m) for m in picked],
        "interpretation":{
            "rigidity_score":"max(scale deviation, basis non-orthogonality, |abs(det)-1|) on current*inverse(bind)",
            "near_zero":"source transforms remain rigid; investigate segment/keyframe semantics rather than matrix scale/shear",
            "large":"source evaluator is producing scale/shear/non-rigid matrices"
        },
        "client_modified":False,
    }



def _pose_diff(a, b):
    """Matrix-space delta metric; intentionally layout-agnostic."""
    worst={"score":-1.0}
    total=0.0; count=0
    for i,(ma,mb) in enumerate(zip(a,b)):
        vals=[float(x)-float(y) for x,y in zip(ma,mb)]
        score=sum(x*x for x in vals) ** 0.5
        total += score*score; count += 1
        if score > worst["score"]:
            worst={"score":score,"bone_index":i}
    return worst, ((total/max(count,1)) ** 0.5)


def _frame_like_value(obj):
    if not isinstance(obj, dict): return None
    for k,v in obj.items():
        lk=str(k).lower()
        if ("frame" in lk or "time" in lk) and isinstance(v,(int,float)):
            return {"field":str(k),"value":v}
    return None


def _key_sequences(obj, path="", depth=0):
    """Find likely keyframe arrays without relying on a specific legacy parser schema."""
    if depth > 5: return []
    out=[]
    if isinstance(obj, dict):
        for k,v in obj.items():
            child=f"{path}.{k}" if path else str(k)
            out.extend(_key_sequences(v,child,depth+1))
    elif isinstance(obj, (list,tuple)):
        if obj and isinstance(obj[0],dict):
            probes=[_frame_like_value(x) for x in obj[:min(len(obj),8)]]
            if any(x is not None for x in probes):
                frames=[]
                for item in obj:
                    fv=_frame_like_value(item)
                    if fv is not None:
                        frames.append(fv)
                out.append({
                    "path":path,"length":len(obj),"frame_samples":frames[:12],
                    "first":frames[0] if frames else None,"last":frames[-1] if frames else None,
                })
        # Do not recurse through long scalar/matrix arrays. Recurse only into
        # structured short arrays, which is where parser key records live.
        if len(obj) <= 64:
            for i,v in enumerate(obj):
                if isinstance(v,(dict,list,tuple)):
                    out.extend(_key_sequences(v,f"{path}[{i}]",depth+1))
    return out


def audit_motion_segments(root: pathlib.Path, inx: pathlib.Path, smb_path: pathlib.Path, selector="STAND") -> dict:
    evaluator, inxcore=load_motion_system(root)
    smb=evaluator.parse_smb(pathlib.Path(smb_path))
    parsed=inxcore.parse_inx(pathlib.Path(inx))
    motions=enrich_motions(parsed,smb)
    selected=select_motion(motions,selector)
    active=[m for m in motions if m.get("active_container")]
    names=[b["name"] for b in smb["bones"]]

    def eval_at(logical,end_engine):
        results,_,_,stats=evaluator.evaluate_pose(smb,int(logical)*160,int(end_engine))
        return results,stats

    def boundary(m):
        points=[]
        for logical in range(int(m["global_start"])-2,int(m["global_start"])+3):
            pose,stats=eval_at(logical,m["engine_end"])
            points.append((logical,pose,stats))
        for logical in range(int(m["global_end"])-2,int(m["global_end"])+3):
            if any(x[0]==logical for x in points): continue
            pose,stats=eval_at(logical,m["engine_end"])
            points.append((logical,pose,stats))
        points.sort(key=lambda x:x[0])
        transitions=[]
        for (la,pa,_),(lb,pb,_) in zip(points,points[1:]):
            if lb != la+1: continue
            worst,rms=_pose_diff(pa,pb)
            transitions.append({"from":la,"to":lb,"engine_from":la*160,"engine_to":lb*160,
                                "worst_bone":names[worst["bone_index"]],"max_matrix_step":worst["score"],"rms_bone_step":rms})
        return transitions

    # Test whether frame_end materially changes a pose inside the selected
    # segment. This catches evaluators that use the passed segment end to pick
    # interpolation/wrap keys.
    mid=(int(selected["global_start"])+int(selected["global_end"])-1)//2
    probe_ends=[]
    end_candidates={
        "selected_end":int(selected["engine_end"]),
        "one_frame_before":int(selected["engine_end"])-160,
        "one_frame_after":int(selected["engine_end"])+160,
    }
    base,_=eval_at(mid,end_candidates["selected_end"])
    for label,endv in end_candidates.items():
        pose,_=eval_at(mid,endv)
        worst,rms=_pose_diff(base,pose)
        probe_ends.append({"label":label,"frame_end":endv,"max_diff_from_selected_end":worst["score"],
                           "worst_bone":names[worst["bone_index"]],"rms_bone_diff":rms})

    # Introspect likely raw key arrays for every bone, but emit only distinct
    # path/length/frame-range signatures plus bones whose signatures differ.
    sig_groups={}
    per_bone=[]
    for i,b in enumerate(smb["bones"]):
        seqs=_key_sequences(b)
        compact=[]
        for q in seqs:
            compact.append({"path":q["path"],"length":q["length"],"first":q["first"],"last":q["last"]})
        sig=json.dumps(compact,sort_keys=True,ensure_ascii=False)
        sig_groups.setdefault(sig,[]).append(names[i])
        per_bone.append((names[i],compact))
    key_layout_groups=[]
    for sig,bns in sig_groups.items():
        key_layout_groups.append({"bones":bns,"sequences":json.loads(sig)})

    compare=[]; seen=set()
    for m in [selected]+[x for x in active if x.get("state_name") in ("WALK","ATTACK")]:
        if m["index"] in seen: continue
        seen.add(m["index"])
        compare.append({
            "index":int(m["index"]),"state":m["state_name"],"motion_frame":int(m["motion_frame"]),
            "repeat":int(m["repeat"]),"global_start":int(m["global_start"]),"global_end":int(m["global_end"]),
            "engine_start":int(m["engine_start"]),"engine_end":int(m["engine_end"]),
            "boundary_steps":boundary(m),
        })

    return {
        "format":"PT_MOTION_SEGMENT_KEY_AUDIT_V1",
        "selected_motion_index":int(selected["index"]),"selected_state":selected["state_name"],
        "selected_frame_end_sensitivity":probe_ends,
        "motions":compare,
        "smb_top_level_keys":sorted(map(str,smb.keys())),
        "bone_record_keys":sorted(map(str,smb["bones"][0].keys())) if smb.get("bones") else [],
        "key_layout_groups":key_layout_groups,
        "interpretation":{
            "boundary_steps":"large discontinuity at start/end can indicate wrong segment bounds or cross-segment key selection",
            "frame_end_sensitivity":"non-zero differences show evaluate_pose semantics depend on the supplied motion end",
            "key_layout_groups":"raw parser key arrays grouped by bone layout; frame ranges reveal whether keys span multiple INX segments"
        },
        "client_modified":False,
    }


def smb_physique_closure_signature(smb: dict, used_indices: list[int], precision: int = 6) -> dict:
    """Signature only the bone closure that can deform a rigid-Physique mesh.

    ``used_indices`` are the source Physique bone indices referenced by the mesh.
    The signature includes those bones plus every ancestor needed to reproduce
    their world transforms. Unrelated branches are intentionally excluded.
    """
    import hashlib
    bones = smb.get("bones") or []
    names=[str(b.get("name") or "") for b in bones]
    name_to_index={n.casefold():i for i,n in enumerate(names) if n}

    def parent_of(i: int) -> int:
        b=bones[i]
        raw=b.get("parent_index")
        if raw not in (None, ""):
            try:
                return int(raw)
            except Exception:
                pass
        pname=str(b.get("parent_name") or "").strip()
        if pname and pname.casefold() in name_to_index:
            return int(name_to_index[pname.casefold()])
        return -1

    used=sorted({int(i) for i in used_indices})
    if not used:
        raise RuntimeError("Physique probe produced no weighted bone indices")
    bad=[i for i in used if i < 0 or i >= len(bones)]
    if bad:
        raise RuntimeError(f"Physique bone indices outside skeleton: {bad[:8]} bone_count={len(bones)}")

    closure=set(used)
    for start in used:
        cur=start
        seen=set()
        while 0 <= cur < len(bones) and cur not in seen:
            seen.add(cur)
            p=parent_of(cur)
            if p < 0:
                break
            closure.add(p)
            cur=p
    closure=sorted(closure)

    def norm_seq(seq):
        out=[]
        for v in seq:
            fv=float(v)
            if abs(fv) < 0.5 * (10 ** (-precision)):
                fv=0.0
            out.append(round(fv, precision))
        return out

    records=[]
    for i in closure:
        b=bones[i]
        p=parent_of(i)
        tm=b.get("tm")
        if tm in (None, []):
            bind_value={
                "tm": [],
                "tminvert": norm_seq(_flatten_numeric_matrix(b.get("tminvert"))),
                "tmrotate": norm_seq(_flatten_numeric_matrix(b.get("tmrotate"))),
            }
        else:
            bind_value=norm_seq(_flatten_numeric_matrix(tm))
        records.append({
            "index": i,
            "name": names[i].casefold(),
            "parent_index": p,
            "parent_name": (names[p].casefold() if 0 <= p < len(names) else str(b.get("parent_name") or "").casefold()),
            "weighted": i in used,
            "bind": bind_value,
        })

    topo_records=[{k:r[k] for k in ("index","name","parent_index","parent_name","weighted")} for r in records]
    topo_blob=json.dumps({"used_indices":used,"closure":topo_records}, ensure_ascii=False,
                         separators=(",",":"), sort_keys=True).encode("utf-8")
    blob=json.dumps({"used_indices":used,"closure":records}, ensure_ascii=False,
                    separators=(",",":"), sort_keys=True).encode("utf-8")
    return {
        "physique_topology_signature": hashlib.sha256(topo_blob).hexdigest(),
        "physique_subset_signature": hashlib.sha256(blob).hexdigest(),
        "used_bone_indices": used,
        "used_bone_names": [names[i] for i in used],
        "closure_indices": closure,
        "closure_bone_names": [names[i] for i in closure],
        "closure_bone_count": len(closure),
    }


_STRUCTURAL_BINDING_SOURCES = {
    "STRUCTURAL_GATE_UNIQUE",
    "SKELETON_SIGNATURE_UNIQUE",
    "GATE_FIRST_SKELETON_UNIQUE",
    "PHYSIQUE_SUBSET_EQUIVALENT",
}

def resolve_asset_motion_context(asset, resolver, *, require_physical: bool = True) -> dict:
    """Resolve one asset's authoritative motion INX/SMB pair.

    This is the shared backend form of the CLI animation context rule.  It
    deliberately relies on registry binding evidence and never guesses from
    folder or basename similarity.
    """
    if getattr(asset, "visual_mode", None) != "RIGID" or not getattr(asset, "animation_binding_ready", False):
        raise RuntimeError(
            f"resolved motion context required; skeleton binding={getattr(asset, 'binding_mode', '')}/"
            f"{getattr(asset, 'binding_source', '')} animation_binding_ready={getattr(asset, 'animation_binding_ready', False)}"
        )
    configs = list(getattr(asset, "configs", []) or [])
    if not configs:
        raise RuntimeError("resolved motion context has no config rows")
    cfg = next((x for x in configs if x.get("motion_smb")), configs[0])
    motion_inx = cfg.get("motion_inx") or (
        cfg.get("inx") if getattr(asset, "binding_source", "") not in _STRUCTURAL_BINDING_SOURCES else ""
    )
    if not motion_inx:
        raise RuntimeError("root skeleton is structurally bound, but root motion INX is not uniquely resolved")
    motion_smb = cfg.get("motion_smb")
    if not motion_smb:
        raise RuntimeError("resolved motion context has no motion SMB")
    inx_path = resolver.resolve(motion_inx, required=require_physical)
    smb_path = resolver.resolve(motion_smb, required=require_physical)
    if require_physical and (inx_path is None or smb_path is None):
        raise RuntimeError("resolved motion context has missing physical INX/SMB dependency")
    return {
        "config": dict(cfg),
        "motion_inx": str(motion_inx).replace("\\", "/"),
        "motion_smb": str(motion_smb).replace("\\", "/"),
        "inx_path": pathlib.Path(inx_path) if inx_path is not None else None,
        "smb_path": pathlib.Path(smb_path) if smb_path is not None else None,
    }
