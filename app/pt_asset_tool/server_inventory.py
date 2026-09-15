from __future__ import annotations

import collections
import json
import os
import pathlib
from typing import Any, Callable

from .server_lifecycle import classify_server_path

FORMAT = "PT_ASSET_SERVER_INVENTORY_V1"


def audit_server_inventory(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    progress_every: int = 10000,
    sample_limit: int = 12,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    server_root = pathlib.Path(server_root).resolve()
    report_dir = project_root / "pt_build" / "devtest" / "server_inventory"
    report_path = report_dir / "result.json"

    lifecycle_counts: collections.Counter[str] = collections.Counter()
    extension_counts: collections.Counter[str] = collections.Counter()
    samples: dict[str, list[str]] = collections.defaultdict(list)
    total_files = 0
    total_bytes = 0
    asset_candidate_files = 0
    design_visible_files = 0
    hard_excluded_files = 0
    layout_counts: collections.Counter[str] = collections.Counter()

    for base, dirs, files in os.walk(server_root):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            path = pathlib.Path(base) / name
            rel = path.relative_to(server_root).as_posix()
            c = classify_server_path(rel)
            total_files += 1
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            total_bytes += int(size)
            lifecycle_counts[c.lifecycle] += 1
            ext = path.suffix.casefold() or "[no_extension]"
            extension_counts[ext] += 1
            if ext == ".spp":
                layout_counts["SPP_SUMMIT_200x12" if size == 2400 else ("SPP_LEGACY_50x12" if size == 600 else "SPP_OTHER_SIZE")] += 1
            elif ext == ".spc":
                layout_counts["SPC_SUMMIT_100x504" if size == 50400 else "SPC_OTHER_SIZE"] += 1
            elif ext == ".inx":
                layout_counts["INX_MODERN_172" if size == 95268 else ("INX_LEGACY_120" if size == 67084 else "INX_OTHER_SIZE")] += 1
            asset_candidate_files += int(c.asset_candidate)
            design_visible_files += int(c.design_visible)
            hard_excluded_files += int(c.write_policy in {"BLOCKED_PERSISTENCE", "BLOCKED_STATE", "BLOCKED_RUNTIME_INTEGRITY", "FORENSICS_ONLY", "EXCLUDED_TOOLING"})
            if len(samples[c.lifecycle]) < sample_limit:
                samples[c.lifecycle].append(rel)
            if progress and progress_every > 0 and (total_files == 1 or total_files % progress_every == 0):
                progress(f"SERVER_INVENTORY {total_files} files")

    result = {
        "format": FORMAT,
        "status": "PASS" if server_root.is_dir() else "FAIL",
        "server_root": str(server_root),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "asset_candidate_files": asset_candidate_files,
        "design_visible_files": design_visible_files,
        "hard_excluded_files": hard_excluded_files,
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "extension_counts": dict(sorted(extension_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "layout_counts": dict(sorted(layout_counts.items())),
        "samples_by_lifecycle": dict(sorted(samples.items())),
        "policy": {
            "classification_basis": "PATH_PLUS_FORMAT_LIFECYCLE",
            "persistence_logs_security_are_not_assets": True,
            "inventory_is_read_only": True,
            "server_write_authorized": False,
        },
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
