from __future__ import annotations

from .runtime_paths import invocation_label

import collections
import pathlib
from typing import Any

from .motion_core import enrich_motions, load_motion_system, resolve_asset_motion_context
from .semantic_path import semantic_group_for_path

FORMAT = "PT_ANIMATION_CERTIFICATION_PLAN_V1"
CORE_STATE_ORDER = ("STAND", "WALK", "RUN", "ATTACK", "DAMAGE", "DEAD", "FALLDOWN", "SKILL")


def _quoted(value: str) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def build_animation_certification_plan(
    project_root: pathlib.Path,
    registry,
    resolver,
    *,
    category: str | None = None,
    context_limit: int = 0,
    motions_per_context: int = 3,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Plan representative human Blender animation certification jobs.

    This function does not open Blender and does not add certifications.  It
    turns already-proven physical INX/SMB contexts into a deterministic review
    queue so visual gates cover semantic groups/layouts/motion states instead
    of relying on ad-hoc asset selection.
    """
    category_q = str(category or "").strip().upper()
    evaluator, inxcore = load_motion_system(pathlib.Path(project_root))
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    for asset in registry.assets:
        if not asset.animation_binding_ready:
            continue
        group = semantic_group_for_path(asset.primary_path, asset.category)
        if category_q and group != category_q:
            continue
        physical = registry.physical_dependency_status(asset)
        if not physical.get("animation_binding_ready_physical"):
            continue
        try:
            ctx = resolve_asset_motion_context(asset, resolver, require_physical=True)
        except Exception as exc:
            unresolved.append({
                "asset": asset.primary_path,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue
        key = (str(ctx["motion_inx"]).casefold(), str(ctx["motion_smb"]).casefold())
        row = contexts.setdefault(key, {
            "motion_inx": ctx["motion_inx"],
            "motion_smb": ctx["motion_smb"],
            "inx_path": pathlib.Path(ctx["inx_path"]),
            "smb_path": pathlib.Path(ctx["smb_path"]),
            "assets": [],
            "groups": set(),
        })
        row["assets"].append(asset.primary_path)
        row["groups"].add(group)

    parsed_contexts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in contexts.values():
        try:
            inx = inxcore.parse_inx(row["inx_path"])
            smb = evaluator.parse_smb(row["smb_path"])
            validation = inxcore.validate_with_smb(inx, row["smb_path"])
            if validation.get("check") != "PASS":
                raise RuntimeError(f"INX/SMB validation={validation.get('errors')}")
            motions = enrich_motions(inx, smb)
            active = [m for m in motions if m.get("active_container")]
            active_by_state: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
            for motion in active:
                active_by_state[str(motion.get("state_name") or "UNKNOWN")].append(motion)
            states = list(active_by_state)
            ordered_states = [s for s in CORE_STATE_ORDER if s in active_by_state]
            ordered_states += sorted((s for s in states if s not in CORE_STATE_ORDER), key=str.casefold)
            parsed_contexts.append({
                **row,
                "layout": str((inx.get("layout") or {}).get("name") or "UNKNOWN"),
                "active_motion_count": len(active),
                "states": ordered_states,
                "active_by_state": active_by_state,
            })
        except Exception as exc:
            failures.append({
                "motion_inx": row["motion_inx"],
                "motion_smb": row["motion_smb"],
                "assets": row["assets"],
                "error": f"{type(exc).__name__}: {exc}",
            })

    # Prefer semantic/layout diversity before additional contexts of the same kind.
    def context_key(row: dict[str, Any]):
        group = sorted(row["groups"])[0] if row["groups"] else "OTHER"
        group_rank = {"CHARACTER": 0, "NPC": 1, "MONSTER": 2}.get(group, 9)
        layout_rank = {"LEGACY_120": 0, "MODERN_172": 1}.get(row["layout"], 9)
        return (group_rank, layout_rank, str(row["motion_inx"]).casefold(), str(row["motion_smb"]).casefold())

    parsed_contexts.sort(key=context_key)
    if context_limit and int(context_limit) > 0:
        parsed_contexts = parsed_contexts[: int(context_limit)]

    queue: list[dict[str, Any]] = []
    state_coverage: collections.Counter[str] = collections.Counter()
    group_coverage: collections.Counter[str] = collections.Counter()
    layout_coverage: collections.Counter[str] = collections.Counter()
    max_motions = max(1, int(motions_per_context))
    for context_index, row in enumerate(parsed_contexts, start=1):
        assets = sorted(row["assets"], key=str.casefold)
        representative = assets[0]
        group = semantic_group_for_path(representative, "")
        states = list(row["states"])
        # Select complementary review motions: idle, locomotion, attack/damage,
        # then whatever else is present. This makes small plans cover more failure modes.
        preferred = []
        for state in ("STAND", "WALK", "RUN", "ATTACK", "DAMAGE", "SKILL", "DEAD", "FALLDOWN"):
            if state in states and state not in preferred:
                preferred.append(state)
        preferred += [s for s in states if s not in preferred]
        selected_states = preferred[:max_motions]
        head = "auto" if group == "CHARACTER" else "none"
        layout_coverage[row["layout"]] += 1
        group_coverage[group] += 1
        for state in selected_states:
            motion = row["active_by_state"][state][0]
            state_coverage[state] += 1
            queue.append({
                "review_id": f"ANIM-{context_index:03d}-{int(motion['index']):03d}",
                "asset": representative,
                "semantic_group": group,
                "motion_inx": row["motion_inx"],
                "motion_smb": row["motion_smb"],
                "inx_layout": row["layout"],
                "motion_index": int(motion["index"]),
                "motion_state": state,
                "motion_frame_slot": int(motion.get("motion_frame") or 0),
                "head": head,
                "load_actions": "core",
                "human_gates": ["VISUAL_RIG", "VISUAL_ANIMATION", "VISUAL_TEXTURE_MATERIAL"],
                "command": (
                    f"{invocation_label()} validate animation {_quoted(representative)} "
                    f"--motion {state} --load-actions core --head {head}"
                ),
                "client_write": False,
            })

    return {
        "format": FORMAT,
        "status": "PASS" if not failures else "PARTIAL",
        "scope": "HUMAN_BLENDER_CERTIFICATION_QUEUE_NO_AUTOMATIC_PROMOTION",
        "category_filter": category_q or None,
        "registry_context_count": len(contexts),
        "planned_context_count": len(parsed_contexts),
        "review_count": len(queue),
        "motions_per_context": max_motions,
        "semantic_group_coverage": dict(sorted(group_coverage.items())),
        "inx_layout_coverage": dict(sorted(layout_coverage.items())),
        "motion_state_coverage": dict(sorted(state_coverage.items())),
        "queue": queue,
        "failure_sample": failures[: max(0, int(sample_limit))],
        "unresolved_sample": unresolved[: max(0, int(sample_limit))],
        "automatic_visual_certification": False,
        "automatic_runtime_certification": False,
        "client_modified": False,
    }
