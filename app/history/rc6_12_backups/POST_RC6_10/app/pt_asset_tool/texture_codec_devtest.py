from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
from typing import Any

from .rare_support import SHIP_BMP_FILES, build_ship_bmp_bytes, decode_ship_bmp_bytes
from .release_1_coverage import CONTENT_DOMAINS, content_domain

FORMAT = "PT_PROPRIETARY_TEXTURE_CODEC_AUTOMATED_DEVTEST_V1"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _representatives(registry, family: str, limit: int = 3, *, domain: str | None = None) -> list[Any]:
    rows = [
        asset for asset in registry.assets
        if asset.family == family and (domain is None or content_domain(asset) == domain)
    ]
    rows.sort(key=lambda asset: (int(asset.size or 0), asset.primary_path.casefold()))
    if not rows:
        return []
    idxs = [0, len(rows) // 2, len(rows) - 1]
    out: list[Any] = []
    seen: set[str] = set()
    for idx in idxs:
        asset = rows[idx]
        if asset.asset_id not in seen:
            out.append(asset)
            seen.add(asset.asset_id)
        if len(out) >= int(limit):
            break
    return out


def _family_domain_inventory(registry, families: tuple[str, ...]) -> dict[str, dict[str, int]]:
    out = {domain: {family: 0 for family in families} for domain in CONTENT_DOMAINS}
    for asset in registry.assets:
        if asset.family not in families:
            continue
        domain = content_domain(asset)
        if domain in out:
            out[domain][asset.family] += 1
    return out


def audit_proprietary_texture_codecs(project_root, registry, resolver, *, per_family: int = 3) -> dict[str, Any]:
    root = pathlib.Path(project_root).resolve()
    bmp = _load(root / "pt_character_texture_v1_4.py", "pt_release1_bmp_core")
    tga = _load(root / "pt_protected_tga_v1.py", "pt_release1_tga_core")
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    families = (
        "BMP_PROTECTED_PREFIX14_EXACT",
        "BMP_PROTECTED_PREFIX14_VARIANT",
        "TGA_NONSTANDARD_OR_PROTECTED",
    )
    family_domain_inventory = _family_domain_inventory(registry, families)

    for family in ("BMP_PROTECTED_PREFIX14_EXACT", "BMP_PROTECTED_PREFIX14_VARIANT"):
        for domain in CONTENT_DOMAINS:
            for asset in _representatives(registry, family, per_family, domain=domain):
                try:
                    path = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
                    raw = path.read_bytes()
                    before = _sha(raw)
                    info = bmp.inspect_bmp_bytes(raw)
                    editable = bmp.decode_editable(raw, info)
                    p0 = int(info["pixel_offset"])
                    p1 = int(info["pixel_end"])
                    if p1 <= p0:
                        raise RuntimeError("empty BMP pixel payload")
                    changed = bytearray(editable)
                    changed[p0] ^= 0x01
                    rebuilt, _binfo, _einfo = bmp.build_game_bytes(raw, bytes(changed))
                    if rebuilt == raw:
                        raise RuntimeError("BMP pixel edit not observed")
                    if rebuilt[:p0] != raw[:p0] or rebuilt[p1:] != raw[p1:]:
                        raise RuntimeError("BMP non-pixel bytes changed")
                    decoded = bmp.decode_editable(rebuilt, bmp.inspect_bmp_bytes(rebuilt))
                    if decoded[p0:p1] != bytes(changed)[p0:p1]:
                        raise RuntimeError("BMP rebuild/decode pixel mismatch")
                    if _sha(path.read_bytes()) != before:
                        raise RuntimeError("source BMP drift")
                    rows.append({
                        "logical": asset.primary_path,
                        "family": family,
                        "domain": domain,
                        "status": "PASS",
                        "width": info.get("width"),
                        "height": info.get("height"),
                        "pixel_bytes": info.get("pixel_bytes"),
                        "candidate_pixel_edit_observed": True,
                    })
                except Exception as exc:
                    failures.append({
                        "logical": asset.primary_path,
                        "family": family,
                        "domain": domain,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

    # Exact second protected BMP family used by chrselect ships. This family is
    # an additional global codec gate; it is intentionally not used to satisfy
    # a content-domain cell unless the registry itself attributes that family.
    for logical in SHIP_BMP_FILES:
        try:
            path = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            raw = path.read_bytes()
            before = _sha(raw)
            editable, meta = decode_ship_bmp_bytes(raw)
            changed = bytearray(editable)
            changed[54] ^= 0x01
            rebuilt, _bmeta = build_ship_bmp_bytes(raw, bytes(changed))
            if rebuilt == raw or rebuilt[:54] != raw[:54] or rebuilt[-2:] != raw[-2:]:
                raise RuntimeError("ship BMP candidate preservation failure")
            if _sha(path.read_bytes()) != before:
                raise RuntimeError("source ship BMP drift")
            rows.append({
                "logical": logical,
                "family": "BMP_SHIP_DIB40_PROTECTED_EXACT",
                "domain": None,
                "status": "PASS",
                "width": meta.get("width"),
                "height": meta.get("height"),
                "pixel_bytes": meta.get("pixel_bytes"),
                "candidate_pixel_edit_observed": True,
            })
        except Exception as exc:
            failures.append({
                "logical": logical,
                "family": "BMP_SHIP_DIB40_PROTECTED_EXACT",
                "domain": None,
                "error": f"{type(exc).__name__}: {exc}",
            })

    for domain in CONTENT_DOMAINS:
        for asset in _representatives(registry, "TGA_NONSTANDARD_OR_PROTECTED", per_family, domain=domain):
            try:
                path = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
                raw = path.read_bytes()
                before = _sha(raw)
                info = tga.inspect_bytes(raw)
                if not info.get("protected"):
                    skipped.append({
                        "logical": asset.primary_path,
                        "family": asset.family,
                        "domain": domain,
                        "reason": "NOT_PROTECTED_TGA_MEMBER",
                        "classification": info,
                    })
                    continue
                editable, _ = tga.decode_bytes(raw)
                einfo = tga.inspect_bytes(editable)
                body0 = int(einfo.get("payload_start") or (18 + int(einfo["fields"].get("id_length") or 0)))
                body1 = int(einfo.get("payload_end") or len(editable))
                if body1 <= body0:
                    raise RuntimeError("empty protected TGA editable payload")
                changed = bytearray(editable)
                changed[body0] ^= 0x01
                rebuilt, _, _ = tga.build_bytes(raw, bytes(changed))
                if rebuilt == raw:
                    raise RuntimeError("TGA body edit not observed")
                if rebuilt[:18] != raw[:18] or rebuilt[body1:] != raw[body1:]:
                    raise RuntimeError("TGA protected header/container suffix changed")
                decoded, _ = tga.decode_bytes(rebuilt)
                if decoded != bytes(changed):
                    raise RuntimeError("TGA rebuild/decode mismatch")
                if _sha(path.read_bytes()) != before:
                    raise RuntimeError("source TGA drift")
                rows.append({
                    "logical": asset.primary_path,
                    "family": asset.family,
                    "domain": domain,
                    "status": "PASS",
                    "mode": info.get("mode"),
                    "width": info["fields"].get("width"),
                    "height": info["fields"].get("height"),
                    "candidate_body_edit_observed": True,
                })
            except Exception as exc:
                failures.append({
                    "logical": asset.primary_path,
                    "family": asset.family,
                    "domain": domain,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    passed_pairs = {
        (str(row.get("domain")), str(row.get("family")))
        for row in rows if row.get("domain") in CONTENT_DOMAINS
    }
    failed_pairs = {
        (str(row.get("domain")), str(row.get("family")))
        for row in failures if row.get("domain") in CONTENT_DOMAINS
    }
    domain_summary: dict[str, Any] = {}
    for domain in CONTENT_DOMAINS:
        present = [family for family, count in family_domain_inventory[domain].items() if int(count) > 0]
        required = set(present)
        passed = {family for d, family in passed_pairs if d == domain}
        failed = {family for d, family in failed_pairs if d == domain}
        missing = sorted(required - passed)
        domain_summary[domain] = {
            "present_families": sorted(present),
            "family_asset_counts": {family: int(family_domain_inventory[domain][family]) for family in present},
            "passed_families": sorted(passed & required),
            "failed_families": sorted(failed & required),
            "missing_family_witnesses": missing,
            "status": "PASS" if required and not missing and not failed else ("NOT_PRESENT" if not required else "FAIL"),
        }
    pass_domains = sorted(domain for domain, summary in domain_summary.items() if summary["status"] == "PASS")

    result = {
        "format": FORMAT,
        "status": "PASS" if rows and not failures and all(
            summary["status"] in {"PASS", "NOT_PRESENT"} for summary in domain_summary.values()
        ) else "FAIL",
        "pass_count": len(rows),
        "failure_count": len(failures),
        "skip_count": len(skipped),
        "rows": rows,
        "failures": failures,
        "skipped": skipped,
        "domain_summary": domain_summary,
        "pass_domains": pass_domains,
        "scope": "REPRESENTATIVE_PROPRIETARY_DECODE_EDIT_REBUILD_NO_CLIENT_WRITE",
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    out = root / "pt_build" / "devtest" / "texture_codec_auto" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result



EXACT_REGRESSION_FORMAT = "PT_PROPRIETARY_TEXTURE_EXACT_REGRESSION_V1"

def audit_proprietary_texture_exact_regressions(project_root, registry, resolver, logical_paths) -> dict[str, Any]:
    """Exercise exact historical protected-texture failures in temp memory only.

    This gate exists so a fixed outlier cannot disappear from a representative
    sample on the next registry revision.  It never writes either source root.
    """
    root = pathlib.Path(project_root).resolve()
    tga = _load(root / "pt_protected_tga_v1.py", "pt_exact_regression_tga_core")
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    requested = [str(x).replace("\\", "/").strip("/") for x in logical_paths]
    for logical in requested:
        try:
            asset = registry.resolve(logical)
            if str(asset.family or "") != "TGA_NONSTANDARD_OR_PROTECTED":
                raise RuntimeError(f"exact regression is not protected-TGA family: {asset.family}")
            path = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
            raw = path.read_bytes()
            before = _sha(raw)
            info = tga.inspect_bytes(raw)
            if not info.get("protected"):
                raise RuntimeError("registry protected TGA is not physically protected")
            editable, _ = tga.decode_bytes(raw)
            einfo = tga.inspect_bytes(editable)
            body0 = int(einfo.get("payload_start") or (18 + int((einfo.get("fields") or {}).get("id_length") or 0)))
            body1 = int(einfo.get("payload_end") or len(editable))
            if body1 <= body0:
                raise RuntimeError("empty protected TGA editable payload")
            changed = bytearray(editable)
            changed[body0] ^= 0x01
            rebuilt, _binfo, _einfo = tga.build_bytes(raw, bytes(changed))
            if rebuilt == raw:
                raise RuntimeError("protected TGA witness edit was not observed")
            decoded, _ = tga.decode_bytes(rebuilt)
            if decoded != bytes(changed):
                raise RuntimeError("protected TGA exact regression decode/rebuild mismatch")
            if _sha(path.read_bytes()) != before:
                raise RuntimeError("source protected TGA changed during regression")
            rows.append({
                "logical": asset.primary_path,
                "family": asset.family,
                "status": "PASS",
                "mode": info.get("mode") or info.get("protection_mode"),
                "has_footer": info.get("has_footer"),
                "width": (info.get("fields") or {}).get("width"),
                "height": (info.get("fields") or {}).get("height"),
            })
        except Exception as exc:
            failures.append({"logical": logical, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
    result = {
        "format": EXACT_REGRESSION_FORMAT,
        "status": "PASS" if requested and len(rows) == len(requested) and not failures else ("EMPTY" if not requested else "FAIL"),
        "requested": requested,
        "pass_count": len(rows),
        "failure_count": len(failures),
        "rows": rows,
        "failures": failures,
        "scope": "EXACT_HISTORICAL_PROTECTED_TEXTURE_DECODE_EDIT_REBUILD_NO_SOURCE_WRITE",
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    out = root / "pt_build" / "devtest" / "texture_codec_exact_regressions" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

CORPUS_FORMAT = "PT_PROPRIETARY_TEXTURE_PHYSICAL_CORPUS_AUDIT_V1"

def audit_proprietary_texture_physical_corpus(project_root, registry, resolver, *, failure_sample_limit: int = 100, progress: bool = False) -> dict[str, Any]:
    """Read-only decode/classification gate for every registry proprietary BMP/TGA.

    The representative codec gate performs an actual pixel/body edit and rebuild.
    This corpus gate ensures no shipped member of the supported registry families
    is silently outside the decoder before a content domain is marked ready.
    """
    root=pathlib.Path(project_root).resolve()
    bmp=_load(root / "pt_character_texture_v1_4.py", "pt_release1_bmp_corpus_core")
    tga=_load(root / "pt_protected_tga_v1.py", "pt_release1_tga_corpus_core")
    families=("BMP_PROTECTED_PREFIX14_EXACT","BMP_PROTECTED_PREFIX14_VARIANT","TGA_NONSTANDARD_OR_PROTECTED")
    rows=[]; failures=[]
    by_domain={d:{"asset_count":0,"pass_count":0,"fail_count":0,"family_counts":{},"family_fail_counts":{}} for d in CONTENT_DOMAINS}
    candidates = [
        asset for asset in registry.assets
        if str(asset.family or "") in families and content_domain(asset) in by_domain
    ]
    total = len(candidates)
    if progress:
        print(f"[release-1-auto] TEXTURE_CORPUS begin assets={total}", flush=True)
    for index, asset in enumerate(candidates, 1):
        family=str(asset.family or "")
        domain=content_domain(asset)
        if progress and (index == 1 or index % 100 == 0 or index == total):
            print(f"[release-1-auto] TEXTURE_CORPUS {index}/{total} {domain} {family} {asset.primary_path}", flush=True)
        summary=by_domain[domain]; summary["asset_count"] += 1
        summary["family_counts"][family]=int(summary["family_counts"].get(family,0))+1
        try:
            path=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
            raw=path.read_bytes()
            if family.startswith("BMP_PROTECTED_PREFIX14"):
                info=bmp.inspect_bmp_bytes(raw)
                if bool(info.get("standard")):
                    raise RuntimeError("registry protected BMP classified as standard")
                editable=bmp.decode_editable(raw,info)
                einfo=bmp.inspect_bmp_bytes(editable)
                if not bool(einfo.get("standard")):
                    raise RuntimeError("decoded BMP is not standard")
                for key in ("width","height","bpp","pixel_bytes"):
                    if int(einfo.get(key) or 0) != int(info.get(key) or 0):
                        raise RuntimeError(f"BMP decode structural mismatch {key}")
                meta={"width":info.get("width"),"height":info.get("height"),"bpp":info.get("bpp")}
            else:
                info=tga.inspect_bytes(raw)
                editable,_=tga.decode_bytes(raw)
                einfo=tga.inspect_bytes(editable)
                if bool(einfo.get("protected")):
                    raise RuntimeError("decoded TGA remains protected")
                for key in ("width","height","pixel_depth","image_type"):
                    if int((einfo.get("fields") or {}).get(key) or 0) != int((info.get("fields") or {}).get(key) or 0):
                        raise RuntimeError(f"TGA decode structural mismatch {key}")
                meta={"protected":bool(info.get("protected")),"mode":info.get("protection_mode"),"width":(info.get("fields") or {}).get("width"),"height":(info.get("fields") or {}).get("height")}
            summary["pass_count"] += 1
            rows.append({"logical":asset.primary_path,"domain":domain,"family":family,"status":"PASS",**meta})
        except Exception as exc:
            summary["fail_count"] += 1
            summary["family_fail_counts"][family]=int(summary["family_fail_counts"].get(family,0))+1
            row={"logical":asset.primary_path,"domain":domain,"family":family,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
            failures.append(row); rows.append(row)
    pass_domains=[]
    for domain,summary in by_domain.items():
        count=int(summary.get("asset_count") or 0); fail=int(summary.get("fail_count") or 0)
        summary["status"]="PASS" if count and not fail and int(summary.get("pass_count") or 0)==count else ("NOT_PRESENT" if not count else "FAIL")
        if summary["status"]=="PASS": pass_domains.append(domain)
    return {
        "format":CORPUS_FORMAT,
        "status":"PASS" if rows and not failures else ("EMPTY" if not rows else "FAIL"),
        "asset_count":len(rows),"pass_count":sum(1 for x in rows if x.get("status")=="PASS"),"failure_count":len(failures),
        "pass_domains":sorted(pass_domains),"by_domain":by_domain,
        "failure_sample":failures[:max(0,int(failure_sample_limit))],
        "scope":"CORPUS_WIDE_READ_ONLY_DECODE_CLASSIFICATION",
        "production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
