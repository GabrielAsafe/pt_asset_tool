from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pt_asset_tool.stage072_corpus import parse_stage072
from pt_asset_tool.blender.write_stage072_uv import _scan as scan_uv
from pt_asset_tool.blender.write_stage072_geometry import _scan as scan_geometry


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--smd", required=True)
    p.add_argument("--witness", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--expected-source-sha256", required=True)
    return p.parse_args(argv)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    a = _args()
    smd = pathlib.Path(a.smd).expanduser().resolve()
    source_sha = _sha(smd)
    if source_sha.lower() != str(a.expected_source_sha256).lower():
        raise RuntimeError("source sha256 drift")
    parsed = parse_stage072(smd, include_payload=True)
    if parsed.get("full_parse") != "PASS":
        raise RuntimeError("Stage0.72 source parser is not PASS")

    uv_changes, uv_errors = scan_uv(parsed)
    geometry_changes, geometry_errors = scan_geometry(parsed)

    # Each strict scanner intentionally treats the other edit family as a
    # collateral edit. Exactly one scanner must therefore accept a non-empty set.
    uv_ok = bool(uv_changes) and not uv_errors
    geometry_ok = bool(geometry_changes) and not geometry_errors
    if uv_ok and geometry_ok:
        raise RuntimeError("ambiguous saved edit: both UV and geometry strict modes accepted")
    if not uv_ok and not geometry_ok:
        if not uv_changes and not geometry_changes and not uv_errors and not geometry_errors:
            raise RuntimeError("saved Blend contains no supported Stage0.72 edit")
        raise RuntimeError(
            "saved Blend does not satisfy a strict Stage0.72 candidate mode: "
            f"uv_errors={uv_errors[:6]} geometry_errors={geometry_errors[:6]}"
        )

    if uv_ok:
        mode = "UV_ONLY"
        witness = {
            "format": "PT_STAGE072_SAVED_EDIT_WITNESS_V1",
            "source": str(smd),
            "source_sha256": source_sha,
            "edit_mode": mode,
            "uv_edits": uv_changes,
            "geometry_edit_policy": "FORBIDDEN",
        }
        edit_count = len(uv_changes)
    else:
        normalized = []
        for raw in geometry_changes:
            edit = dict(raw)
            changed = [int(x) for x in (edit.get("changed_components") or [])]
            if not changed or any(x not in {0,1,2} for x in changed):
                raise RuntimeError(f"geometry candidate invalid changed components: {changed}")
            vi = int(edit["vertex_index"])
            incident = [
                fi for fi, face in enumerate(parsed["payload"]["faces"])
                if vi in [int(x) for x in face["vertices"]]
            ]
            edit["incident_faces"] = incident
            edit["incident_face_count"] = len(incident)
            edit["delta_raw"] = [int(edit["after_raw"][i]) - int(edit["before_raw"][i]) for i in range(3)]
            edit["delta_world"] = [x / 256.0 for x in edit["delta_raw"]]
            normalized.append(edit)
        mode = "GEOMETRY_GRID_MULTI"
        witness = {
            "format": "PT_STAGE072_SAVED_EDIT_WITNESS_V1",
            "source": str(smd),
            "source_sha256": source_sha,
            "edit_mode": mode,
            "geometry_edits": normalized,
            "uv_edit_policy": "FORBIDDEN",
            "topology_edit_policy": "FORBIDDEN",
        }
        edit_count = len(normalized)

    wp = pathlib.Path(a.witness).expanduser().resolve()
    rp = pathlib.Path(a.report).expanduser().resolve()
    wp.parent.mkdir(parents=True, exist_ok=True)
    rp.parent.mkdir(parents=True, exist_ok=True)
    wp.write_text(json.dumps(witness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "format": "PT_STAGE072_SAVED_EDIT_EXTRACT_V1",
        "status": "PASS",
        "source": str(smd),
        "source_sha256": source_sha,
        "edit_mode": mode,
        "edit_count": edit_count,
        "witness": str(wp),
        "uv_scan_change_count": len(uv_changes),
        "uv_scan_errors": uv_errors,
        "geometry_scan_change_count": len(geometry_changes),
        "geometry_scan_errors": geometry_errors,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
