from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import pathlib
import re
import struct
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .rare_outliers import MODEL062, MODEL062_ALT_MAGIC, _probe_bmp, _probe_ship_bmp_family, _probe_tga, _sourcecode_decrypt_bmp_header14
from .stage072_corpus import HEADER as STAGE072_HEADER
from .utils import norm_path, sha256_file

FORMAT = "PT_FULL_ASSET_SEMANTIC_CENSUS_V1"
UI_FORMAT = "PT_UI_ASSET_CATALOG_V1"
RELEASE = "0.9.0"
CERTIFIED_WRITERS = {
    "pt_asset_tool/rare_rigid_edit.py": "229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42",
    "pt_asset_tool/rare_rigid_multivertex.py": "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991",
    "pt_asset_tool/rare_rigid_multibone_bridge.py": "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0",
    "pt_asset_tool/rare_rigid_normal_bridge.py": "67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96",
}
POLICY_FILES = [
    "pt_build/rare_rigid_large_production_policy_v0821.json",
    "pt_build/rare_rigid_cross_object_production_policy_v0830.json",
    "pt_build/rare_rigid_multibone_outward_extent_production_policy_v0836.json",
]

ROLE_ORDER = [
    "UI", "PLAYER", "PLAYER_HEAD", "PLAYER_BODY", "MONSTER", "NPC", "EQUIPMENT",
    "ITEM", "MAP", "FRONTEND_SCENE", "EFFECT", "ANIMATION", "CONFIG", "AUDIO", "UNKNOWN",
]

@dataclass
class Classification:
    semantic_group: str
    semantic_role: str
    confidence: str
    evidence: list[str]


def _low_parts(rel: str) -> list[str]:
    return [x.lower() for x in pathlib.PurePosixPath(rel).parts]


def _tokens(rel: str) -> set[str]:
    return {x for x in re.split(r"[^a-z0-9]+", rel.lower()) if x}


def _ui_role(rel: str) -> tuple[str, list[str]] | None:
    lo = rel.lower().replace("\\", "/")
    parts = _low_parts(rel)
    if lo.startswith("startimage/"):
        if "loading" in parts:
            return "UI_LOADING", ["path:startimage", "path:loading"]
        name = pathlib.PurePosixPath(lo).name
        if any(x in name for x in ("server", "s_server")):
            return "UI_SERVER_SELECT", ["path:startimage", "name:server"]
        if any(x in name for x in ("login", "id_pw", "new", "exit", "logo")) or "opening" in parts:
            return "UI_LOGIN", ["path:startimage/opening"]
        return "UI_FRONTEND", ["path:startimage"]
    if lo.startswith("image/sinimage/"):
        if "/items/" in lo:
            if "/defense/" in lo: return "UI_ITEM_ICON_DEFENSE", ["path:Image/Sinimage/Items/Defense"]
            if "/weapon/" in lo: return "UI_ITEM_ICON_WEAPON", ["path:Image/Sinimage/Items/Weapon"]
            if "/accessory/" in lo: return "UI_ITEM_ICON_ACCESSORY", ["path:Image/Sinimage/Items/Accessory"]
            if "/premium/" in lo: return "UI_ITEM_ICON_PREMIUM", ["path:Image/Sinimage/Items/Premium"]
            if "/dropitem/" in lo: return "UI_ITEM_DROP_ART", ["path:Image/Sinimage/Items/DropItem"]
            return "UI_ITEM_ICON", ["path:Image/Sinimage/Items"]
        if "/inter/chat/" in lo: return "UI_CHAT", ["path:Image/Sinimage/Inter/Chat"]
        if "/inter/buttoninfo/" in lo: return "UI_TOOLTIP", ["path:Image/Sinimage/Inter/ButtonInfo"]
        if "/inter/skillicon/" in lo: return "UI_SKILL", ["path:Image/Sinimage/Inter/SkillIcon"]
        if "/inter/restart/" in lo: return "UI_RESPAWN", ["path:Image/Sinimage/Inter/ReStart"]
        if "/inter/singage/" in lo: return "UI_GAUGE", ["path:Image/Sinimage/Inter/sinGage"]
        if "/status/" in lo: return "UI_CHARACTER_STATUS", ["path:Image/Sinimage/Status"]
        if "/inter/" in lo:
            name = pathlib.PurePosixPath(lo).name
            if name.startswith("b") and any(x in name for x in ("inventory", "party", "quest", "skill", "status", "system")):
                return "UI_MAIN_BUTTON", ["path:Image/Sinimage/Inter", "name:main_button"]
            return "UI_HUD", ["path:Image/Sinimage/Inter"]
        return "UI_OTHER", ["path:Image/Sinimage"]
    return None


def classify_semantic(rel: str, ext: str, registry_hint: dict[str, Any] | None = None) -> Classification:
    lo = rel.lower().replace("\\", "/")
    parts = _low_parts(rel)
    toks = _tokens(rel)
    ev: list[str] = []

    ui = _ui_role(rel)
    if ui:
        role, e = ui
        return Classification("UI", role, "HIGH", e)

    if lo.startswith("game/maps/chrselect/"):
        return Classification("FRONTEND_SCENE", "CHARACTER_SELECT_SCENE", "HIGH", ["path:game/maps/chrselect"])
    if parts and (parts[0] in {"effect", "effects"} or "effect" in toks):
        return Classification("EFFECT", "EFFECT_ASSET", "HIGH" if parts and parts[0] in {"effect", "effects"} else "MEDIUM", ["path_or_name:effect"])
    if parts and (parts[0] in {"field", "maps", "map"} or lo.startswith("game/maps/")):
        return Classification("MAP", "MAP_ASSET", "HIGH", ["path:map_or_field"])
    if "monster" in toks or any(p.startswith("monster") for p in parts):
        return Classification("MONSTER", "MONSTER_ASSET", "HIGH", ["path_or_name:monster"])
    if "npc" in toks or any(p == "npc" or p.startswith("npc") for p in parts):
        return Classification("NPC", "NPC_ASSET", "HIGH", ["path_or_name:npc"])

    if any(x in toks for x in ("weapon", "armor", "armour", "shield", "boots", "gauntlet", "defense", "accessory")):
        subtype = next((x for x in ("weapon", "armor", "armour", "shield", "boots", "gauntlet", "defense", "accessory") if x in toks), "equipment")
        return Classification("EQUIPMENT", "EQUIPMENT_" + subtype.upper(), "MEDIUM", [f"path_or_name:{subtype}"])
    if "item" in toks or any(p in {"item", "items"} for p in parts):
        return Classification("ITEM", "ITEM_ASSET", "MEDIUM", ["path_or_name:item"])

    # Registry enrichment is stronger than basename-only guesses, but it still
    # does not by itself prove the runtime semantic role (player vs monster).
    if registry_hint:
        category = str(registry_hint.get("category") or "").upper()
        family = str(registry_hint.get("family") or "")
        if category == "CHARACTER" or (family.startswith("SMD_MODEL_062") and lo.startswith("char/")):
            ev = ["registry:CHARACTER"] if category == "CHARACTER" else ["registry:SMD_MODEL_062", "path:char"]
            return Classification("PLAYER", "CHARACTER_MODEL_CANDIDATE", "MEDIUM", ev)

    if lo.startswith("char/"):
        # Do not claim player/head/body from a filename alone.  The census marks
        # this as a character candidate so later binding/runtime gates can split it.
        if ext == ".smb":
            return Classification("ANIMATION", "CHARACTER_SKELETON_ANIMATION", "MEDIUM", ["path:char", "ext:smb"])
        if ext in {".inx", ".inf"}:
            return Classification("CONFIG", "CHARACTER_BINDING_CONFIG", "MEDIUM", ["path:char", f"ext:{ext[1:]}"])
        return Classification("PLAYER", "CHARACTER_ASSET_CANDIDATE", "MEDIUM", ["path:char"])

    if ext == ".smb":
        return Classification("ANIMATION", "ANIMATION_CONTAINER", "MEDIUM", ["ext:smb"])
    if ext in {".inx", ".inf", ".ini", ".cfg", ".txt", ".dat"}:
        return Classification("CONFIG", "CONFIG_OR_TABLE", "LOW", [f"ext:{ext[1:]}"])
    if ext in {".wav", ".ogg", ".mp3", ".mid"}:
        return Classification("AUDIO", "AUDIO_ASSET", "HIGH", [f"ext:{ext[1:]}"])
    return Classification("UNKNOWN", "UNKNOWN", "NONE", [])


def _parse_standard_bmp_header(head: bytes) -> dict[str, Any]:
    if len(head) < 30 or head[:2] != b"BM": return {}
    try:
        dib = struct.unpack_from("<I", head, 14)[0]
        if dib == 12 and len(head) >= 26:
            w,h = struct.unpack_from("<HH", head, 18)
            bpp = struct.unpack_from("<H", head, 24)[0]
        elif dib >= 40 and len(head) >= 30:
            w,h = struct.unpack_from("<ii", head, 18)
            bpp = struct.unpack_from("<H", head, 28)[0]
        else: return {"dib_size": dib}
        return {"dib_size": dib, "width": abs(int(w)), "height": abs(int(h)), "bpp": int(bpp)}
    except struct.error:
        return {}


def _parse_standard_tga_header(head: bytes) -> dict[str, Any]:
    if len(head) < 18: return {}
    try:
        image_type=head[2]; w=struct.unpack_from("<H",head,12)[0]; h=struct.unpack_from("<H",head,14)[0]; bpp=head[16]
    except Exception: return {}
    if image_type not in {1,2,3,9,10,11} or w <= 0 or h <= 0 or bpp not in {8,15,16,24,32}:
        return {}
    return {"image_type": image_type, "width": int(w), "height": int(h), "bpp": int(bpp)}


def physical_probe(path: pathlib.Path, rel: str) -> dict[str, Any]:
    ext = path.suffix.lower()
    out: dict[str, Any] = {"physical_family": "OTHER"}
    try:
        with path.open("rb") as f: head = f.read(1024)
    except OSError as exc:
        return {"physical_family": "IO_ERROR", "probe_error": f"{type(exc).__name__}:{exc}"}

    if ext == ".smd":
        if head.startswith(MODEL062): out["physical_family"] = "SMD_MODEL_062"
        elif head.startswith(STAGE072_HEADER): out["physical_family"] = "SMD_STAGE_072"
        elif head[:24] == MODEL062_ALT_MAGIC: out["physical_family"] = "SMD_MODEL_062_ALT_MAGIC_PROVEN_FAMILY"
        else: out["physical_family"] = "SMD_UNKNOWN"
        return out
    if ext == ".smb": out["physical_family"] = "SMB_ANIMATION_CONTAINER"; return out
    if ext == ".inx": out["physical_family"] = "INX_CONFIG"; return out
    if ext == ".inf": out["physical_family"] = "INF_CONFIG"; return out
    if ext == ".bmp":
        std=_parse_standard_bmp_header(head)
        if std:
            out.update(std); out["physical_family"]="BMP_STANDARD"; return out
        try:
            data=path.read_bytes()
            ship=_probe_ship_bmp_family(data)
            if ship:
                out["physical_family"]="BMP_SHIP_DIB40_PROTECTED_EXACT"
                out["width"]=ship.get("decoded_width"); out["height"]=ship.get("decoded_height"); out["bpp"]=ship.get("decoded_bpp")
                return out
            raw=_probe_bmp(data)
            cls=str(raw.get("classification") or "UNRESOLVED")
            if cls == "DIB_AFTER_PREFIX14" and len(data) >= 54:
                dec=_sourcecode_decrypt_bmp_header14(data)+data[14:54]
                dims=_parse_standard_bmp_header(dec)
                if dims:
                    out.update(dims); out["physical_family"]="BMP_PROTECTED_HEADER14"; return out
            out["physical_family"]="BMP_"+cls
            return out
        except Exception as exc:
            out["physical_family"]="BMP_UNRESOLVED"; out["probe_error"]=f"{type(exc).__name__}:{exc}"; return out
    if ext == ".tga":
        std=_parse_standard_tga_header(head)
        if std:
            out.update(std); out["physical_family"]="TGA_STANDARD_HEADER"; return out
        try:
            raw=_probe_tga(path.read_bytes())
            out["physical_family"]=str(raw.get("classification") or "TGA_UNRESOLVED")
            fields=raw.get("decoded_fields") or raw.get("direct_fields") or {}
            if isinstance(fields,dict):
                for k in ("width","height","pixel_depth"):
                    if k in fields: out["bpp" if k=="pixel_depth" else k]=fields[k]
            return out
        except Exception as exc:
            out["physical_family"]="TGA_UNRESOLVED"; out["probe_error"]=f"{type(exc).__name__}:{exc}"; return out
    if ext in {".wav", ".ogg", ".mp3", ".mid"}: out["physical_family"]="AUDIO"; return out
    if ext in {".exe", ".dll"}: out["physical_family"]="EXECUTABLE"; return out
    if ext in {".ini", ".cfg", ".txt", ".xml", ".json", ".csv"}: out["physical_family"]="TEXT_OR_CONFIG"; return out
    out["physical_family"] = ("EXT_" + ext[1:].upper()) if ext else "NO_EXTENSION"
    return out


def _variant_key(name: str) -> str:
    stem=pathlib.PurePosixPath(name).stem.lower()
    stem=re.sub(r"(?:[-_](?:on|off|sel|selected|hover|down|up|disable|disabled|active|normal))$", "", stem)
    stem=re.sub(r"[-_]\d+$", "", stem)
    stem=re.sub(r"[-_]+$", "", stem)
    return stem or pathlib.PurePosixPath(name).stem.lower()


def _state_hint(name: str) -> str:
    stem=pathlib.PurePosixPath(name).stem.lower()
    for key,label in (("hover","HOVER"),("selected","SELECTED"),("sel","SELECTED"),("disabled","DISABLED"),("disable","DISABLED"),("down","PRESSED"),("on","ON"),("off","OFF")):
        if re.search(rf"(?:^|[-_]){key}$", stem): return label
    if re.search(r"[-_]1$",stem) or stem.endswith("_"): return "VARIANT_1"
    if re.search(r"[-_]2$",stem): return "VARIANT_2"
    return "BASE_OR_UNKNOWN"


def _load_registry_enrichment(settings: Settings) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        from .resolver import ClientResolver
        from .registry import AssetRegistry
        if not settings.inventory.is_file() or not settings.pairing.is_file():
            return {}, {"available": False, "reason": "inventory_or_pairing_missing"}
        reg=AssetRegistry(settings.inventory, settings.pairing, resolver=ClientResolver(settings.client_root))
        out={}
        for a in reg.assets:
            out[a.primary_path.lower()]={
                "asset_id": a.asset_id, "category": a.category, "family": a.family, "kind": a.kind,
                "compatibility_tier": a.compatibility_tier, "binding_mode": a.binding_mode,
                "binding_source": a.binding_source, "binding_skeleton_smb": a.binding_skeleton_smb,
                "rigid_binding_ready": a.rigid_binding_ready, "animation_binding_ready": a.animation_binding_ready,
                "physique_mode": a.physique_mode,
            }
        return out, {"available": True, "asset_count": len(out)}
    except Exception as exc:
        return {}, {"available": False, "reason": f"{type(exc).__name__}:{exc}"}


def _snapshot_guards(root: pathlib.Path) -> dict[str, Any]:
    writers={}
    for rel,expected in CERTIFIED_WRITERS.items():
        p=root/rel
        actual=sha256_file(p) if p.is_file() else None
        writers[rel]={"expected":expected,"actual":actual,"pass":actual==expected}
    policies={}
    for rel in POLICY_FILES:
        p=root/rel
        policies[rel]=sha256_file(p) if p.is_file() else None
    return {"writers":writers,"policies":policies}


def _write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    fields=["relative_path","extension","size","physical_family","semantic_group","semantic_role","confidence","width","height","bpp","registry_category","registry_family","registry_kind","binding_mode","evidence"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            rr={k:r.get(k) for k in fields}; rr["evidence"]=" | ".join(r.get("evidence") or [])
            w.writerow(rr)


def _write_ui_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    fields=["relative_path","semantic_role","confidence","physical_family","width","height","bpp","variant_group","state_hint","size","evidence"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            rr={k:r.get(k) for k in fields}; rr["evidence"]=" | ".join(r.get("evidence") or [])
            w.writerow(rr)


def _write_markdown(path: pathlib.Path, report: dict[str, Any]) -> None:
    c=report["counts"]
    lines=["# Summit Tale — Semantic Asset Census V0.9.0","",f"Client files scanned: **{report['file_count']}**",f"Scan errors: **{len(report['scan_errors'])}**",f"UI candidates: **{report['ui']['file_count']}**",f"Unknown semantic role: **{c['by_group'].get('UNKNOWN',0)}**","","## Semantic groups","","| Group | Files |","|---|---:|"]
    for k,n in sorted(c["by_group"].items(),key=lambda kv:(-kv[1],kv[0])): lines.append(f"| {k} | {n} |")
    lines += ["","## UI roles","","| UI role | Files |","|---|---:|"]
    for k,n in sorted(report["ui"]["by_role"].items(),key=lambda kv:(-kv[1],kv[0])): lines.append(f"| {k} | {n} |")
    lines += ["","## Physical families","","| Family | Files |","|---|---:|"]
    for k,n in sorted(c["by_physical_family"].items(),key=lambda kv:(-kv[1],kv[0]))[:40]: lines.append(f"| {k} | {n} |")
    lines += ["","## Classification policy","","- Path/layout evidence is preferred over filename guessing.","- Registry binding evidence enriches SMD/INX/SMB records but does not silently prove player-vs-monster runtime semantics.","- `UNKNOWN` is a valid result and is retained for later targeted discovery.","- This audit is read-only and does not authorize any new writer.","- UI is catalogued separately so the next milestone can add preview/edit support without rescanning the client.",""]
    path.write_text("\n".join(lines),encoding="utf-8")


def run_census(root: pathlib.Path, output: pathlib.Path, client_root: pathlib.Path | None = None) -> dict[str, Any]:
    root=root.resolve(); settings=Settings.discover(root, client_root)
    client=settings.client_root
    if not client.is_dir(): raise FileNotFoundError(client)
    guards_before=_snapshot_guards(root)
    if not all(x["pass"] for x in guards_before["writers"].values()):
        bad=[k for k,v in guards_before["writers"].items() if not v["pass"]]
        raise RuntimeError("CERTIFIED_WRITER_HASH_MISMATCH:"+",".join(bad))
    registry, registry_meta=_load_registry_enrichment(settings)
    rows=[]; errors=[]
    for p in sorted(client.rglob("*"),key=lambda x:x.as_posix().lower()):
        if not p.is_file(): continue
        rel=p.relative_to(client).as_posix(); ext=p.suffix.lower(); rh=registry.get(rel.lower())
        try:
            st=p.stat(); probe=physical_probe(p,rel); sem=classify_semantic(rel,ext,rh)
            row={"relative_path":rel,"extension":ext,"size":st.st_size,"mtime_ns":st.st_mtime_ns,
                 **probe,"semantic_group":sem.semantic_group,"semantic_role":sem.semantic_role,"confidence":sem.confidence,"evidence":sem.evidence}
            if rh:
                row.update({"registry_asset_id":rh.get("asset_id"),"registry_category":rh.get("category"),"registry_family":rh.get("family"),"registry_kind":rh.get("kind"),"binding_mode":rh.get("binding_mode"),"binding_source":rh.get("binding_source"),"binding_skeleton_smb":rh.get("binding_skeleton_smb"),"rigid_binding_ready":rh.get("rigid_binding_ready"),"animation_binding_ready":rh.get("animation_binding_ready"),"physique_mode":rh.get("physique_mode")})
            rows.append(row)
        except Exception as exc:
            errors.append({"relative_path":rel,"error":f"{type(exc).__name__}:{exc}"})
    by_group=collections.Counter(r["semantic_group"] for r in rows)
    by_role=collections.Counter(r["semantic_role"] for r in rows)
    by_ext=collections.Counter(r["extension"] or "<none>" for r in rows)
    by_phys=collections.Counter(r["physical_family"] for r in rows)
    ui_rows=[]
    groups=collections.defaultdict(list)
    for r in rows:
        if r["semantic_group"]!="UI": continue
        rr=dict(r); rr["variant_group"]=_variant_key(pathlib.PurePosixPath(r["relative_path"]).name); rr["state_hint"]=_state_hint(pathlib.PurePosixPath(r["relative_path"]).name)
        ui_rows.append(rr); groups[(str(pathlib.PurePosixPath(r["relative_path"]).parent).lower(),rr["variant_group"])].append(r["relative_path"])
    ui_variant_groups=[{"directory":k[0],"variant_group":k[1],"count":len(v),"files":sorted(v,key=str.lower)} for k,v in groups.items() if len(v)>1]
    ui_variant_groups.sort(key=lambda x:(-x["count"],x["directory"],x["variant_group"]))

    guards_after=_snapshot_guards(root)
    writer_unchanged=guards_after["writers"]==guards_before["writers"]
    policies_unchanged=guards_after["policies"]==guards_before["policies"]
    if not writer_unchanged: raise RuntimeError("WRITER_CHANGED_DURING_READ_ONLY_CENSUS")
    if not policies_unchanged: raise RuntimeError("PRODUCTION_POLICY_CHANGED_DURING_READ_ONLY_CENSUS")

    output.parent.mkdir(parents=True,exist_ok=True)
    csv_path=output.with_suffix(".csv")
    md_path=output.with_suffix(".md")
    ui_json=output.with_name(output.stem+"_ui_catalog.json")
    ui_csv=output.with_name(output.stem+"_ui_catalog.csv")
    report={
        "format":FORMAT,"status":"PASS" if not errors else "PASS_WITH_SCAN_ERRORS","release_version":RELEASE,
        "client_root":str(client),"client_read_only":True,"file_count":len(rows),"scan_errors":errors,
        "registry_enrichment":registry_meta,
        "counts":{"by_group":dict(by_group),"by_role":dict(by_role),"by_extension":dict(by_ext),"by_physical_family":dict(by_phys)},
        "ui":{"file_count":len(ui_rows),"by_role":dict(collections.Counter(r["semantic_role"] for r in ui_rows)),"variant_group_count":len(ui_variant_groups)},
        "guards":{"certified_writer_hashes_valid":True,"writer_modules_modified":not writer_unchanged,"production_policies_modified":not policies_unchanged,"policy_sha256":guards_after["policies"]},
        "outputs":{"json":str(output),"csv":str(csv_path),"markdown":str(md_path),"ui_json":str(ui_json),"ui_csv":str(ui_csv)},
        "rows":rows,
        "policy":{"classification":"evidence-ranked; no filename-only runtime role claims","unknown":"retained rather than guessed","write":"read-only census; no new write authorization","next_on_pass":"use census to build New Character Visual pipeline and UI catalog/preview in priority order"},
    }
    ui_report={"format":UI_FORMAT,"status":"PASS","release_version":RELEASE,"client_root":str(client),"file_count":len(ui_rows),"by_role":report["ui"]["by_role"],"variant_groups":ui_variant_groups,"rows":ui_rows,"write_authorized":False}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    ui_json.write_text(json.dumps(ui_report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _write_csv(csv_path,rows); _write_ui_csv(ui_csv,ui_rows); _write_markdown(md_path,report)
    return report


def main(argv: list[str] | None = None) -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--client-root")
    a=ap.parse_args(argv)
    out=pathlib.Path(a.output)
    try:
        report=run_census(pathlib.Path(a.root),out,pathlib.Path(a.client_root) if a.client_root else None)
        summary={k:report[k] for k in ("format","status","release_version","client_root","client_read_only","file_count","registry_enrichment","counts","ui","guards","outputs","policy")}
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        print(f"semantic_asset_census={report['status']} files={report['file_count']} ui={report['ui']['file_count']} unknown={report['counts']['by_group'].get('UNKNOWN',0)} client_read_only=true")
        return 0 if report["status"].startswith("PASS") else 2
    except Exception as exc:
        fail={"format":FORMAT,"status":"FAIL","release_version":RELEASE,"error":f"{type(exc).__name__}:{exc}","client_read_only":True}
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(fail,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(fail,ensure_ascii=False,indent=2)); return 2

if __name__ == "__main__": raise SystemExit(main())
