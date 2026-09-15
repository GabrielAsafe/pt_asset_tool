from __future__ import annotations

import hashlib
import json
import pathlib
import time
from typing import Any

FORMAT = "PT_ASSET_CLASS_UI_ALIAS_AUDIT_V1"

# Current project policy (2026-09-14): the active Mechanician skill-UI root is
# image/Sinimage/skill/Mechanician and the current source follows that root.
# Historical image/Sinimage/skill/Mecha is intentionally ignored by runtime
# alias/canonicalization gates.  Do not apply this mapping to player audio:
# wav/Effects/player/Mechanician is a separate, legitimate historical path.
UI_ALIAS_GROUPS = (
    {
        "id": "MECHANICIAN_SKILL_UI",
        "class": "Mechanician",
        "canonical_root": "image/Sinimage/skill/Mechanician",
        "alias_roots": (),
        "ignored_legacy_roots": ("image/Sinimage/skill/Mecha",),
        "recovery_enabled": False,
        "evidence": "CURRENT_PROJECT_POLICY_2026-09-14: active source/UI root is image/Sinimage/skill/Mechanician; Mecha is legacy ignored",
        "scope_note": "Skill UI only; historical Mecha is ignored and player audio Mechanician remains outside this group.",
    },
)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    if not root.is_dir():
        return {}
    out: dict[str, pathlib.Path] = {}
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix().casefold()):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        out.setdefault(rel.casefold(), p)
    return out


def audit_class_ui_aliases(
    project_root: str | pathlib.Path,
    client_root: str | pathlib.Path,
) -> dict[str, Any]:
    """Audit class skill-UI directory aliases without changing the client.

    The purpose is to prevent one logical class UI from being treated as two
    independent runtime roots.  Alias-only files are reported with a canonical
    destination, but no move/copy/delete authorization is implied.
    """
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    out_dir = project / "pt_build" / "class_ui_alias_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "result.json"

    groups: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for spec in UI_ALIAS_GROUPS:
        canonical_rel = str(spec["canonical_root"])
        canonical_root = client / canonical_rel
        canonical = _files(canonical_root)
        alias_maps: list[tuple[str, pathlib.Path, dict[str, pathlib.Path]]] = []
        for alias_rel in spec.get("alias_roots", ()):
            alias_root = client / str(alias_rel)
            alias_maps.append((str(alias_rel), alias_root, _files(alias_root)))

        ignored_legacy = []
        for legacy_rel in spec.get("ignored_legacy_roots", ()):
            legacy_root = client / str(legacy_rel)
            legacy_map = _files(legacy_root)
            ignored_legacy.append({
                "root": str(legacy_rel),
                "present": legacy_root.is_dir(),
                "file_count": len(legacy_map),
            })

        keys = set(canonical)
        for _rel, _root, amap in alias_maps:
            keys.update(amap)

        counts = {
            "CANONICAL_ONLY": 0,
            "ALIAS_ONLY": 0,
            "DUPLICATE_IDENTICAL": 0,
            "DUPLICATE_CONFLICT": 0,
        }
        alias_file_count = sum(len(amap) for _rel, _root, amap in alias_maps)

        for key in sorted(keys):
            cp = canonical.get(key)
            aliases = [(arel, amap[key]) for arel, _aroot, amap in alias_maps if key in amap]
            rel_display = None
            if cp is not None:
                rel_display = cp.relative_to(canonical_root).as_posix()
            elif aliases:
                alias_rel, ap = aliases[0]
                rel_display = ap.relative_to(client / alias_rel).as_posix()
            assert rel_display is not None

            c_hash = _sha256(cp) if cp is not None else None
            alias_rows = []
            for alias_rel, ap in aliases:
                alias_rows.append({
                    "alias_root": alias_rel,
                    "logical_path": ap.relative_to(client).as_posix(),
                    "physical_path": str(ap),
                    "sha256": _sha256(ap),
                    "size": ap.stat().st_size,
                })

            if cp is not None and alias_rows:
                same = all(a["sha256"] == c_hash and a["size"] == cp.stat().st_size for a in alias_rows)
                state = "DUPLICATE_IDENTICAL" if same else "DUPLICATE_CONFLICT"
            elif cp is not None:
                state = "CANONICAL_ONLY"
            else:
                state = "ALIAS_ONLY"
            counts[state] += 1

            row = {
                "group": spec["id"],
                "class": spec["class"],
                "relative_path": rel_display,
                "state": state,
                "canonical_logical_path": f"{canonical_rel}/{rel_display}",
                "canonical_physical_path": str(cp) if cp is not None else None,
                "canonical_sha256": c_hash,
                "canonical_size": cp.stat().st_size if cp is not None else None,
                "alias_files": alias_rows,
                "recommended_action": (
                    "KEEP_CANONICAL"
                    if state == "CANONICAL_ONLY"
                    else "REVIEW_REMOVE_REDUNDANT_ALIAS"
                    if state == "DUPLICATE_IDENTICAL"
                    else "REVIEW_CONFLICT_NO_WRITE"
                    if state == "DUPLICATE_CONFLICT"
                    else "REVIEW_CANONICALIZE_ALIAS_ONLY_NO_WRITE"
                ),
                "write_authorized": False,
            }
            rows.append(row)

        split_detected = alias_file_count > 0
        canonical_root_present = canonical_root.is_dir()
        groups.append({
            **spec,
            "canonical_root_present": canonical_root_present,
            "canonical_file_count": len(canonical),
            "alias_file_count": alias_file_count,
            "ignored_legacy_roots": ignored_legacy,
            "ignored_legacy_file_count": sum(int(x["file_count"]) for x in ignored_legacy),
            "split_detected": split_detected,
            "counts": counts,
            "review_required": (not canonical_root_present) or split_detected or counts["DUPLICATE_CONFLICT"] > 0,
        })

    total_counts = {
        state: sum(int(g["counts"].get(state, 0)) for g in groups)
        for state in ("CANONICAL_ONLY", "ALIAS_ONLY", "DUPLICATE_IDENTICAL", "DUPLICATE_CONFLICT")
    }
    review_required = any(bool(g["review_required"]) for g in groups)
    result = {
        "format": FORMAT,
        "status": "PASS",
        "state": "REVIEW_REQUIRED" if review_required else "CANONICAL",
        "generated_at": time.time(),
        "client_root": str(client),
        "group_count": len(groups),
        "review_group_count": sum(1 for g in groups if g["review_required"]),
        "split_group_count": sum(1 for g in groups if g["split_detected"]),
        "ignored_legacy_file_count": sum(int(g.get("ignored_legacy_file_count", 0)) for g in groups),
        "counts": total_counts,
        "groups": groups,
        "rows": rows,
        "policy": {
            "read_only": True,
            "client_write_authorized": False,
            "alias_cleanup_authorized": False,
            "canonicalization_is_report_only": True,
            "mechanician_skill_ui_is_canonical": True,
            "historical_mecha_is_ignored": True,
            "ignored_legacy_roots_are_not_write_sources": True,
            "player_audio_mechanician_is_not_an_alias": True,
        },
        "report": str(report_path),
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
