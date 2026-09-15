from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
import re
from typing import Any

from .config import Settings
from .semantic_census import CERTIFIED_WRITERS, POLICY_FILES
from .utils import sha256_file

FORMAT = "PT_OFFICIAL_CONTAINER_CHARACTER_REFERENCE_ATLAS_V1"
RELEASE = "0.9.4"
ASSET_EXTS = {".smd", ".smb", ".inx", ".inf", ".bmp", ".tga", ".png", ".jpg"}
MODEL_CONFIG_EXTS = {".smd", ".smb", ".inx", ".inf"}
CONTAINER_NAME_RE = re.compile(r"^(?:[bcfl]data\d+|setfile\.lst)$", re.I)
CONTAINER_EXTS = {".pkg", ".gpk", ".cab", ".part"}
ASCII_REF_RE = re.compile(rb"[A-Za-z0-9_./\\():\[\]-]{2,240}\.(?:smd|smb|inx|inf|bmp|tga|png|jpg)", re.I)
CHAR_MARKERS = ("/char/", "/character/", "/player/", "/tm", "/mf")
NOISE_MARKERS = ("/sinimage/items/", "/sinimage/assaeffect/", "/sinimage/effect/", "/sinimage/petdata/")


def _sha(p: pathlib.Path) -> str:
    return sha256_file(p)


def _parse_donor_spec(spec: str) -> tuple[str, pathlib.Path]:
    if "=" in spec:
        name, raw = spec.split("=", 1)
        return name.strip(), pathlib.Path(raw.strip()).expanduser().resolve()
    p = pathlib.Path(spec).expanduser().resolve()
    return p.name, p


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    out = {}
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().lower()):
        if p.is_file():
            try:
                st = p.stat(); out[p.relative_to(root).as_posix()] = (int(st.st_size), int(st.st_mtime_ns))
            except OSError:
                pass
    return out


def _guard_snapshot(root: pathlib.Path) -> dict[str, Any]:
    writers = {}
    for rel, expected in CERTIFIED_WRITERS.items():
        p = root / rel; actual = _sha(p) if p.is_file() else None
        writers[rel] = {"expected": expected, "actual": actual, "pass": actual == expected}
    policies = {}
    for rel in POLICY_FILES:
        p = root / rel; policies[rel] = _sha(p) if p.is_file() else None
    return {"writers": writers, "policies": policies}


def _is_container(p: pathlib.Path) -> bool:
    return bool(CONTAINER_NAME_RE.match(p.name)) or p.suffix.lower() in CONTAINER_EXTS


def _normalize(raw: str) -> str:
    s = raw.replace("\\", "/").strip("\x00 \t\r\n\"")
    s = re.sub(r"^[^A-Za-z0-9]+", "", s)
    s = re.sub(r"/+", "/", s)
    return s


def _utf16_ascii_candidates(data: bytes) -> list[tuple[int, str]]:
    out = []
    # Extract conservative UTF-16LE ASCII runs, then retain only asset refs.
    pat = re.compile(rb"(?:[A-Za-z0-9_./\\():\[\]-]\x00){2,240}(?:\.\x00(?:s\x00m\x00d\x00|s\x00m\x00b\x00|i\x00n\x00x\x00|i\x00n\x00f\x00|b\x00m\x00p\x00|t\x00g\x00a\x00|p\x00n\x00g\x00|j\x00p\x00g\x00))", re.I)
    for m in pat.finditer(data):
        raw = m.group(0)
        off = m.start()
        # A single-byte ASCII field immediately followed by NUL + UTF-16LE can
        # make the final ASCII character look like the first UTF-16 code unit
        # (e.g. `...smd\0c\0h\0...` -> `dchar/...`). Drop that contaminated
        # leading code unit when the byte immediately before it is non-NUL.
        if off > 0 and len(raw) >= 4 and data[off - 1] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./\\():[]-" and raw[1] == 0:
            raw = raw[2:]
            off += 2
        try:
            txt = raw.decode("utf-16le", errors="ignore")
        except Exception:
            continue
        txt = _normalize(txt)
        if txt:
            out.append((off, txt))
    return out


def _scan_refs(path: pathlib.Path, max_unique: int = 50000) -> list[dict[str, Any]]:
    refs: dict[tuple[str, str], dict[str, Any]] = {}
    overlap = b""; base_offset = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(2 * 1024 * 1024)
            if not chunk: break
            data = overlap + chunk
            origin = base_offset - len(overlap)
            for m in ASCII_REF_RE.finditer(data):
                txt = _normalize(m.group(0).decode("latin-1", errors="ignore"))
                if not txt: continue
                key=(txt.lower(),"ASCII")
                refs.setdefault(key,{"ref":txt,"encoding":"ASCII","first_offset":max(0,origin+m.start())})
            for off, txt in _utf16_ascii_candidates(data):
                key=(txt.lower(),"UTF16LE")
                refs.setdefault(key,{"ref":txt,"encoding":"UTF16LE","first_offset":max(0,origin+off)})
            if len(refs) >= max_unique: break
            overlap = data[-2048:]
            base_offset += len(chunk)
    return sorted(refs.values(), key=lambda r:(r["ref"].lower(),r["encoding"]))


def _path_variants(ref: str) -> list[str]:
    s = _normalize(ref).lstrip("/")
    variants = [s]
    low=s.lower()
    for marker in ("image/", "char/", "game/", "effect/", "sound/"):
        idx=low.find(marker)
        if idx>=0: variants.append(s[idx:])
    # Some official refs begin with data roots/drives; suffixes are useful for exact filesystem checks.
    parts=s.split("/")
    for n in range(2, min(len(parts),8)+1): variants.append("/".join(parts[-n:]))
    seen=[]
    for v in variants:
        if v and v.lower() not in {x.lower() for x in seen}: seen.append(v)
    return seen


def _strong_character_ref(ref: str) -> bool:
    lo="/"+_normalize(ref).lower().lstrip("/")
    if any(n in lo for n in NOISE_MARKERS): return False
    return any(m in lo for m in CHAR_MARKERS)


def _build_summit_index(client: pathlib.Path) -> dict[str, Any]:
    by_base: dict[str,list[str]] = collections.defaultdict(list)
    paths: set[str] = set()
    for p in client.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in ASSET_EXTS: continue
        rel=p.relative_to(client).as_posix(); paths.add(rel.lower()); by_base[p.name.lower()].append(rel)
    return {"paths":paths,"by_base":by_base}


def _ref_record(refrow: dict[str,Any], summit: dict[str,Any]) -> dict[str,Any]:
    ref=refrow["ref"]; ext=pathlib.PurePosixPath(ref).suffix.lower(); base=pathlib.PurePosixPath(ref).name.lower()
    exact=[]
    for v in _path_variants(ref):
        if v.lower() in summit["paths"]: exact.append(v)
    basename_hits=summit["by_base"].get(base,[])
    strong=_strong_character_ref(ref)
    noise=any(n in ("/"+ref.lower().lstrip("/")) for n in NOISE_MARKERS)
    if exact: overlap="SUMMIT_EXACT_PATH_REFERENCE"
    elif basename_hits: overlap="SUMMIT_BASENAME_REFERENCE"
    else: overlap="DONOR_REFERENCE_ONLY"
    signal="STRONG_CHARACTER_PATH" if strong else ("KNOWN_NONCHAR_ASSET_TREE" if noise else "UNRESOLVED_MODEL_CONFIG_REFERENCE")
    return {**refrow,"extension":ext,"signal":signal,"summit_overlap":overlap,"summit_exact_variants":exact[:10],"summit_basename_candidates":basename_hits[:20],"summit_basename_candidate_count":len(basename_hits)}


def _scan_donor(name:str, root:pathlib.Path, summit_idx:dict[str,Any]) -> dict[str,Any]:
    if not root.is_dir(): raise FileNotFoundError(root)
    before=_snapshot(root)
    containers=[]; all_records=[]; errors=[]
    for p in sorted(root.rglob("*"), key=lambda x:x.as_posix().lower()):
        if not p.is_file() or not _is_container(p): continue
        rel=p.relative_to(root).as_posix()
        try:
            refs=_scan_refs(p)
            recs=[_ref_record(r,summit_idx) for r in refs if pathlib.PurePosixPath(r["ref"]).suffix.lower() in ASSET_EXTS]
            all_records.extend({"container":rel,**r} for r in recs)
            counts=collections.Counter(r["signal"] for r in recs)
            overlaps=collections.Counter(r["summit_overlap"] for r in recs)
            containers.append({"relative_path":rel,"size":p.stat().st_size,"sha256":_sha(p),"reference_count":len(recs),"signal_counts":dict(counts),"overlap_counts":dict(overlaps),"strong_character_reference_sample":[r for r in recs if r["signal"]=="STRONG_CHARACTER_PATH"][:100]})
        except Exception as exc:
            errors.append({"relative_path":rel,"error":f"{type(exc).__name__}:{exc}"})
    after=_snapshot(root)
    strong=[r for r in all_records if r["signal"]=="STRONG_CHARACTER_PATH"]
    unresolved=[r for r in all_records if r["signal"]=="UNRESOLVED_MODEL_CONFIG_REFERENCE" and r["extension"] in MODEL_CONFIG_EXTS]
    donor_only_strong=[r for r in strong if r["summit_overlap"]=="DONOR_REFERENCE_ONLY"]
    prefix=collections.Counter()
    for r in strong:
        pp=pathlib.PurePosixPath(r["ref"]); parts=pp.parts
        key="/".join(parts[:-1][:4]) if len(parts)>1 else "<root>"; prefix[key]+=1
    ext=collections.Counter(r["extension"] for r in strong)
    enc=collections.Counter(r["encoding"] for r in all_records)
    return {"name":name,"root":str(root),"read_only":before==after,"container_count":len(containers),"scan_errors":errors,"reference_count":len(all_records),"strong_character_reference_count":len(strong),"strong_character_donor_only_count":len(donor_only_strong),"unresolved_model_config_reference_count":len(unresolved),"encoding_counts":dict(enc),"strong_character_extension_counts":dict(ext),"strong_character_prefix_counts_top":dict(prefix.most_common(30)),"strong_character_donor_only_refs":donor_only_strong[:1000],"strong_character_refs":strong[:3000],"unresolved_model_config_sample":unresolved[:300],"containers":containers}


def _compare(a:dict[str,Any], b:dict[str,Any]) -> dict[str,Any]:
    def keyset(d): return {r["ref"].lower() for r in d["strong_character_refs"]}
    A=keyset(a); B=keyset(b)
    return {"first":a["name"],"second":b["name"],"strong_refs_common_count":len(A&B),"strong_refs_only_first":sorted(A-B)[:500],"strong_refs_only_second":sorted(B-A)[:500]}


def _write_csv(path:pathlib.Path, donors:list[dict[str,Any]]):
    fields=["donor","container","ref","encoding","first_offset","extension","signal","summit_overlap","summit_basename_candidate_count"]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for d in donors:
            for r in d["strong_character_refs"]:
                w.writerow({k:(d["name"] if k=="donor" else r.get(k,"")) for k in fields})


def run(root:pathlib.Path, output:pathlib.Path, donor_specs:list[str]) -> dict[str,Any]:
    root=root.resolve(); settings=Settings.discover(root)
    guards_before=_guard_snapshot(root)
    if not all(x["pass"] for x in guards_before["writers"].values()): raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH")
    summit_before=_snapshot(settings.client_root)
    summit_idx=_build_summit_index(settings.client_root)
    donors=[]
    for spec in donor_specs:
        name,path=_parse_donor_spec(spec); donors.append(_scan_donor(name,path,summit_idx))
    comparisons=[]
    for i in range(len(donors)):
        for j in range(i+1,len(donors)): comparisons.append(_compare(donors[i],donors[j]))
    guards_after=_guard_snapshot(root); summit_after=_snapshot(settings.client_root)
    if guards_after!=guards_before: raise RuntimeError("PRODUCTION_GUARD_CHANGED_DURING_READ_ONLY_CONTAINER_ATLAS")
    if summit_before!=summit_after: raise RuntimeError("SUMMIT_CLIENT_CHANGED_DURING_READ_ONLY_CONTAINER_ATLAS")
    if not all(d["read_only"] for d in donors): raise RuntimeError("DONOR_CHANGED_DURING_READ_ONLY_CONTAINER_ATLAS")
    output.parent.mkdir(parents=True,exist_ok=True); csvp=output.with_suffix('.csv'); mdp=output.with_suffix('.md')
    strong=sum(d["strong_character_reference_count"] for d in donors); donor_only=sum(d["strong_character_donor_only_count"] for d in donors)
    report={"format":FORMAT,"status":"PASS","release_version":RELEASE,"client_and_donors_read_only":True,"summit_client_root":str(settings.client_root),"donors":donors,"comparisons":comparisons,"summary":{"strong_character_reference_count":strong,"strong_character_donor_only_count":donor_only,"direct_v093_player_like_effects_not_used_as_body_candidates":True},"decision":{"transplant_write_authorized":False,"new_class_claimed":False,"next_on_pass":"use strong donor-only char/model/config references to recover the exact official body/head package entries; if container records expose offsets/index structure, build read-only extractor for one family before Blender transplant preview"},"guards":{"certified_writer_hashes_valid":True,"writer_modules_modified":False,"production_policies_modified":False,"policy_sha256":guards_after["policies"]},"outputs":{"json":str(output),"csv":str(csvp),"markdown":str(mdp)}}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _write_csv(csvp,donors)
    lines=["# Official Container Character Reference Atlas V0.9.4","","Read-only scan of cdata/bdata/fdata/ldata/setfile/package containers. Direct Sinimage item/effect SMDs are not treated as player bodies.",""]
    for d in donors:
        lines += [f"## {d['name']}",f"- Containers: {d['container_count']}",f"- Strong character refs: {d['strong_character_reference_count']}",f"- Donor-only strong refs: {d['strong_character_donor_only_count']}",f"- UTF-16/ASCII encodings: {d['encoding_counts']}",""]
    mdp.write_text("\n".join(lines),encoding="utf-8")
    return report


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--output',required=True); ap.add_argument('--donor',action='append',required=True); a=ap.parse_args(argv)
    out=pathlib.Path(a.output)
    try:
        r=run(pathlib.Path(a.root),out,list(a.donor))
        compact={"format":r["format"],"status":r["status"],"release_version":r["release_version"],"client_and_donors_read_only":r["client_and_donors_read_only"],"donors":[{k:d[k] for k in ("name","root","read_only","container_count","reference_count","strong_character_reference_count","strong_character_donor_only_count","encoding_counts","strong_character_extension_counts","strong_character_prefix_counts_top")} for d in r["donors"]],"comparisons":r["comparisons"],"summary":r["summary"],"decision":r["decision"],"guards":r["guards"],"outputs":r["outputs"]}
        print(json.dumps(compact,ensure_ascii=False,indent=2)); print(f"official_container_character_atlas=PASS strong_refs={r['summary']['strong_character_reference_count']} donor_only={r['summary']['strong_character_donor_only_count']} read_only=true"); return 0
    except Exception as exc:
        fail={"format":FORMAT,"status":"FAIL","release_version":RELEASE,"error":f"{type(exc).__name__}:{exc}","client_and_donors_read_only":True,"transplant_write_authorized":False}; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(fail,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(fail,ensure_ascii=False,indent=2)); return 2

if __name__=='__main__': raise SystemExit(main())
