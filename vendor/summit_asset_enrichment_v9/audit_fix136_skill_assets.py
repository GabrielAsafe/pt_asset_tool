#!/usr/bin/env python3
"""Fix 136 evidence-aware multi-source recursive skill-asset auditor.

V9 keeps the v8 safety model (never writes to the live client) and adds:
- explicit Fighter TF26 WarCry -> TF26 Roar donor alias;
- global reconciliation of divergent PART dependencies that share one runtime path;
- baseline-lineage protection for shared runtime texture collisions.

V8 added:
- donor lineage inference from assets already present in the target;
- known runtime/source path aliases (Mechanician <-> Mecha buttons);
- coherent PART-bundle dependency resolution;
- proven runtime destinations for basename-only timer TGAs from target peers;
- fuzzy near-match reporting for assets missing from every source;
- separate informational review vs actionable staging decisions.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from asset_common import CaseIndex, extract_text_refs, norm_key, norm_rel, sha256_file, write_csv

HERE = Path(__file__).resolve().parent
DEFAULT_INVENTORY = HERE / "audit_data/fix136/EU_SKILL_BUTTON_ASSETS.csv"
DEFAULT_EFFECTS = HERE / "audit_data/fix136/EU_SKILL_EFFECT_ASSET_LITERALS.csv"
DEFAULT_CONFIG = HERE / "fix136_paths.json"

MATCH_RANK = {
    "EXACT": 0,
    "RELATIVE": 0,
    "ALIAS_EXACT": 1,
    "SUFFIX": 2,
    "ALIAS_SUFFIX": 3,
    "BASENAME": 4,
}
ROOTISH_PREFIXES = {
    "char", "cselect", "effect", "field", "game", "image", "rain", "res",
    "sky", "startimage", "wav", "weapons",
}
PART_DEP_EXTS = {
    ".part", ".tga", ".bmp", ".dds", ".png", ".jpg", ".jpeg", ".ase",
    ".smd", ".smb", ".inx", ".wav", ".ogg", ".mp3", ".pkg",
}

# Source EU shared/skill.h uses "Mechanician", while the physical donor clients
# observed in Fix 136 store the button directory as "Mecha".  This is a known,
# narrow alias and must not turn into a generic directory-name substitution.
PATH_ALIASES = (
    ("image/Sinimage/skill/Mechanician/Button/", "image/Sinimage/skill/Mecha/Button/"),
    # shared/skill.h names Fighter slot TF26 as WarCry, while both observed donor
    # lineages store that exact Fighter/TF26 slot as Roar. Keep this deliberately
    # narrow so fuzzy names never become automatic substitutions.
    ("image/Sinimage/skill/Fighter/Button/TF26 WarCry",
     "image/Sinimage/skill/Fighter/Button/TF26 Roar"),
)


def clean_rel(value: str) -> str:
    """Normalize Windows/runtime paths while preserving a safe relative path."""
    value = norm_rel(value)
    parts: List[str] = []
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        if re.match(r"^[A-Za-z]:$", part):
            continue
        parts.append(part)
    return "/".join(parts)


def load_csv_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def json_dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def alias_paths(expected: str) -> List[str]:
    expected = clean_rel(expected)
    out: List[str] = []
    low = expected.casefold()
    for canonical, physical in PATH_ALIASES:
        c_low = canonical.casefold()
        if c_low in low:
            i = low.index(c_low)
            candidate = expected[:i] + physical + expected[i + len(canonical):]
            if norm_key(candidate) != norm_key(expected):
                out.append(clean_rel(candidate))
    return out


@dataclass
class SourceTree:
    label: str
    root: Path
    priority: int
    index: CaseIndex
    runtime_strip_prefixes: Tuple[str, ...] = ()


class MultiSourceResolver:
    def __init__(self, sources: Sequence[SourceTree]):
        self.sources = sorted(sources, key=lambda s: (s.priority, s.label.casefold()))
        self.by_label = {s.label: s for s in self.sources}
        self._hash_cache: Dict[Path, str] = {}

    def file_hash(self, path: Path) -> str:
        h = self._hash_cache.get(path)
        if h is None:
            h = sha256_file(path)
            self._hash_cache[path] = h
        return h

    def _row(self, source: SourceTree, p: Path, match_type: str, expected: str,
             matched_as: str = "") -> dict:
        return {
            "source_label": source.label,
            "source_priority": source.priority,
            "source_root": str(source.root),
            "match_type": match_type,
            "matched_as": matched_as or expected,
            "expected": expected,
            "source_rel": source.index.rel(p),
            "source_path": str(p),
            "size": p.stat().st_size,
            "sha256": self.file_hash(p),
        }

    def runtime_rel(self, source_label: str, source_rel: str) -> str:
        rel = clean_rel(source_rel)
        source = self.by_label.get(source_label)
        if not source:
            return rel
        for prefix in source.runtime_strip_prefixes:
            p = clean_rel(prefix)
            if not p:
                continue
            if norm_key(rel) == norm_key(p):
                return ""
            if norm_key(rel).startswith(norm_key(p) + "/"):
                return rel[len(p):].lstrip("/")
        return rel

    @staticmethod
    def _common_prefix_parts(a: str, b: str) -> int:
        aa = [x.casefold() for x in PurePosixPath(clean_rel(a)).parts]
        bb = [x.casefold() for x in PurePosixPath(clean_rel(b)).parts]
        n = 0
        for x, y in zip(aa, bb):
            if x != y:
                break
            n += 1
        return n

    def _candidate_score(self, r: dict, *, prefer_source: str = "",
                         parent_source_rel: str = "", dependency: bool = False) -> tuple:
        # Lower is better.  Lexical ordering is intentionally last and is NOT used
        # when deciding whether two candidates are structurally ambiguous.
        rank = MATCH_RANK[r["match_type"]]
        preferred = 0 if prefer_source and r["source_label"] == prefer_source else 1
        source = self.by_label.get(r["source_label"])
        rel = r["source_rel"]
        runtime_rel = self.runtime_rel(r["source_label"], rel)

        particle_family = 1
        proximity = 0
        if dependency and r["source_label"] == prefer_source:
            rr = "/" + norm_key(runtime_rel) + "/"
            # PART scripts in both observed lineages keep loose texture resources in
            # Effect/Particle more often than AssaEffect/NewEffect/ImageData.
            particle_family = 0 if "/effect/particle/" in rr and "/script/" not in rr else 1
            proximity = -self._common_prefix_parts(parent_source_rel, rel)

        structural = (
            rank,
            preferred,
            particle_family,
            proximity,
            int(r["source_priority"]),
            len(Path(rel).parts),
        )
        return structural + (rel.casefold(),)

    def candidates(self, expected: str, *, basename_only: bool = False,
                   prefer_source: str = "", parent_context: Optional[dict] = None) -> List[dict]:
        expected = clean_rel(expected)
        name = Path(expected).name
        out: List[dict] = []
        seen = set()
        parent_source = (parent_context or {}).get("source_label", "")
        parent_path_s = (parent_context or {}).get("source_path", "")
        parent_raw_ref = clean_rel((parent_context or {}).get("raw_ref", ""))
        parent_source_rel = (parent_context or {}).get("source_rel", "")
        dependency = bool(parent_context)

        for source in self.sources:
            # First try the literal raw ref relative to the selected physical PART.
            if parent_source and source.label == parent_source and parent_path_s and parent_raw_ref:
                parent_path = Path(parent_path_s)
                direct = parent_path.parent / parent_raw_ref
                try:
                    direct = direct.resolve()
                    direct.relative_to(source.root.resolve())
                    if direct.is_file():
                        key = (source.label, str(direct))
                        if key not in seen:
                            seen.add(key)
                            out.append(self._row(source, direct, "RELATIVE", expected, parent_raw_ref))
                except (OSError, ValueError):
                    pass

            if not basename_only:
                p = source.index.find(expected)
                if p:
                    key = (source.label, str(p))
                    if key not in seen:
                        seen.add(key)
                        out.append(self._row(source, p, "EXACT", expected))

                for p in source.index.find_suffix(expected):
                    key = (source.label, str(p))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(self._row(source, p, "SUFFIX", expected))

                for alias in alias_paths(expected):
                    p = source.index.find(alias)
                    if p:
                        key = (source.label, str(p))
                        if key not in seen:
                            seen.add(key)
                            out.append(self._row(source, p, "ALIAS_EXACT", expected, alias))
                    for p in source.index.find_suffix(alias):
                        key = (source.label, str(p))
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(self._row(source, p, "ALIAS_SUFFIX", expected, alias))

            for p in source.index.find_basename(name):
                key = (source.label, str(p))
                if key in seen:
                    continue
                seen.add(key)
                out.append(self._row(source, p, "BASENAME", expected))

        effective_prefer = prefer_source or parent_source
        out.sort(key=lambda r: self._candidate_score(
            r,
            prefer_source=effective_prefer,
            parent_source_rel=parent_source_rel,
            dependency=dependency,
        ))
        return out

    def structural_score(self, r: dict, *, prefer_source: str = "",
                         parent_source_rel: str = "", dependency: bool = False) -> tuple:
        return self._candidate_score(
            r, prefer_source=prefer_source, parent_source_rel=parent_source_rel,
            dependency=dependency,
        )[:-1]


def load_wanted(inventory: Path, effects: Path, tiers: Optional[set[int]] = None) -> List[dict]:
    """Build a unique logical asset list while retaining all EU references."""
    merged: Dict[Tuple[str, str], dict] = {}

    def add(category: str, expected: str, *, search_mode: str = "path", ref: str = "",
            cls: str = "", tier: str = "", skill_id: str = "", origin: str = ""):
        expected = clean_rel(expected)
        if not expected:
            return
        dedupe = Path(expected).name.casefold() if search_mode == "basename" else norm_key(expected)
        key = (search_mode, dedupe)
        row = merged.get(key)
        if row is None:
            row = {
                "asset_id": "",
                "category": category,
                "expected": expected,
                "search_mode": search_mode,
                "classes": set(),
                "tiers": set(),
                "skill_ids": set(),
                "origins": set(),
                "references": set(),
                "parent_asset": "",
                "depth": 0,
            }
            merged[key] = row
        if category not in row["category"].split("+"):
            row["category"] += "+" + category
        if cls:
            row["classes"].add(cls)
        if tier:
            row["tiers"].add(str(tier))
        if skill_id:
            row["skill_ids"].add(skill_id)
        if origin:
            row["origins"].add(origin)
        if ref:
            row["references"].add(ref)

    for r in load_csv_rows(inventory):
        tier_num = int(r["tier"])
        if tiers and tier_num not in tiers:
            continue
        common = dict(cls=r["class"], tier=r["tier"], skill_id=r["skill_id"], origin=f"{r.get('source','')}:{r.get('line','')}")
        add("button_normal", r["button_normal"], ref=r["button_base"], **common)
        add("button_hover", r["button_hover"], ref=r["button_base"], **common)
        if r.get("explicit_tga"):
            add("explicit_tga", r["explicit_tga"], search_mode="basename", ref=r["button_base"], **common)

    for r in load_csv_rows(effects):
        add("effect_literal", r["asset"], ref=r.get("type", ""), origin=f"{r.get('source','')}:{r.get('line','')}")

    rows = list(merged.values())
    rows.sort(key=lambda r: (r["category"], r["expected"].casefold()))
    for i, r in enumerate(rows, 1):
        r["asset_id"] = f"A{i:04d}"
        for k in ("classes", "tiers", "skill_ids", "origins", "references"):
            r[k] = " | ".join(sorted(r[k]))
    return rows


def build_sources(cfg: dict) -> Tuple[List[SourceTree], List[dict]]:
    trees: List[SourceTree] = []
    state = []
    for raw in cfg.get("sources", []):
        root = Path(os.path.expanduser(raw["root"]))
        exists = root.is_dir()
        strips = tuple(clean_rel(x) for x in raw.get("runtime_strip_prefixes", []) if clean_rel(x))
        state.append({
            "label": raw["label"], "root": str(root), "priority": int(raw.get("priority", 100)),
            "available": exists, "runtime_strip_prefixes": list(strips),
        })
        if exists:
            trees.append(SourceTree(
                raw["label"], root.resolve(), int(raw.get("priority", 100)),
                CaseIndex(root.resolve()), strips,
            ))
    return trees, state


def target_matches(target_index: Optional[CaseIndex], expected: str, search_mode: str) -> List[Path]:
    if target_index is None:
        return []
    if search_mode == "basename":
        return target_index.find_basename(Path(expected).name)
    p = target_index.find(expected)
    return [p] if p else []


def classify_with_candidates(asset: dict, candidates: List[dict], resolver: MultiSourceResolver,
                             target_index: Optional[CaseIndex]) -> dict:
    target = target_matches(target_index, asset["expected"], asset["search_mode"])
    target_hashes = sorted({resolver.file_hash(p) for p in target}) if target else []
    source_hashes = sorted({c["sha256"] for c in candidates})
    best = candidates[0] if candidates else None

    if target:
        if not candidates:
            status = "PRESENT_TARGET_ONLY"
        elif set(target_hashes) & set(source_hashes):
            status = "PRESENT_TARGET_IDENTICAL"
        else:
            status = "PRESENT_TARGET_CONFLICT"
    elif best:
        status = f"FOUND_{best['match_type']}"
    else:
        status = "MISSING_ALL_SOURCES"

    needs_review = False
    reasons = []
    if len(source_hashes) > 1:
        needs_review = True
        reasons.append(f"{len(source_hashes)} source SHA-256 variants")
    if best and best["match_type"] == "BASENAME":
        same_rank = [c for c in candidates if c["match_type"] == "BASENAME"]
        if len(same_rank) > 1 and len({c["sha256"] for c in same_rank}) > 1:
            needs_review = True
            reasons.append("basename fallback is ambiguous")
    if status == "PRESENT_TARGET_CONFLICT":
        needs_review = True
        reasons.append("target bytes differ from every located source candidate")

    row = dict(asset)
    row.update({
        "status": status,
        "target_hits": len(target),
        "target_rel": " | ".join(target_index.rel(p) for p in target[:8]) if target and target_index else "",
        "target_sha256": " | ".join(target_hashes),
        "candidate_count": len(candidates),
        "source_hash_variants": len(source_hashes),
        "needs_review": "YES" if needs_review else "NO",
        "review_reason": " | ".join(reasons),
        "selected_source": best["source_label"] if best else "",
        "selected_match": best["match_type"] if best else "",
        "selected_rel": best["source_rel"] if best else "",
        "selected_path": best["source_path"] if best else "",
        "selected_sha256": best["sha256"] if best else "",
        "selected_size": best["size"] if best else "",
        "runtime_dest": asset["expected"] if asset["search_mode"] == "path" else "",
        "resolution": "",
        "action": "",
        "action_reason": "",
    })
    return row


def classify_asset(asset: dict, resolver: MultiSourceResolver, target_index: Optional[CaseIndex]) -> Tuple[dict, List[dict]]:
    candidates = resolver.candidates(asset["expected"], basename_only=(asset["search_mode"] == "basename"))
    return classify_with_candidates(asset, candidates, resolver, target_index), candidates


def infer_baseline_source(rows: Sequence[dict], candidate_map: Dict[str, List[dict]]) -> Tuple[str, dict]:
    counts = Counter()
    comparable = 0
    for r in rows:
        if r.get("status") != "PRESENT_TARGET_IDENTICAL" or not r.get("target_sha256"):
            continue
        target_hashes = set(str(r["target_sha256"]).split(" | "))
        matched = {c["source_label"] for c in candidate_map.get(r["asset_id"], []) if c["sha256"] in target_hashes}
        if matched:
            comparable += 1
            for label in matched:
                counts[label] += 1
    if not counts:
        return "", {"counts": {}, "comparable": comparable, "confidence": 0.0}
    leader, lead_n = counts.most_common(1)[0]
    runner = counts.most_common(2)[1][1] if len(counts) > 1 else 0
    confidence = lead_n / max(1, comparable)
    # Require both volume and dominance.  This avoids overfitting tiny clients.
    accepted = lead_n >= 20 and confidence >= 0.75 and lead_n >= max(3 * runner, runner + 20)
    return (leader if accepted else ""), {
        "counts": dict(counts), "comparable": comparable,
        "leader": leader, "leader_hits": lead_n, "runner_up_hits": runner,
        "confidence": round(confidence, 6), "accepted": accepted,
    }


def choose_base_candidate(candidates: List[dict], baseline_source: str, resolver: MultiSourceResolver) -> Optional[dict]:
    if not candidates:
        return None
    # Structural match quality always wins.  Baseline lineage only breaks ties at
    # the same structural rank; this prevents old clients from defeating a unique
    # exact EU T5 asset merely because the target mostly descends from old.
    best_rank = min(MATCH_RANK[c["match_type"]] for c in candidates)
    tier = [c for c in candidates if MATCH_RANK[c["match_type"]] == best_rank]
    if baseline_source:
        baseline = [c for c in tier if c["source_label"] == baseline_source]
        if baseline:
            tier = baseline
    tier.sort(key=lambda c: (
        int(c["source_priority"]), len(Path(c["source_rel"]).parts),
        c["source_rel"].casefold(),
    ))
    return tier[0]


def update_selected(row: dict, best: Optional[dict]) -> None:
    row.update({
        "selected_source": best["source_label"] if best else "",
        "selected_match": best["match_type"] if best else "",
        "selected_rel": best["source_rel"] if best else "",
        "selected_path": best["source_path"] if best else "",
        "selected_sha256": best["sha256"] if best else "",
        "selected_size": best["size"] if best else "",
    })
    if best and not row.get("target_hits"):
        row["status"] = f"FOUND_{best['match_type']}"


def structurally_unique_best(candidates: List[dict], best: dict, resolver: MultiSourceResolver,
                             *, prefer_source: str = "", parent_source_rel: str = "",
                             dependency: bool = False) -> bool:
    relevant = [c for c in candidates if c["source_label"] == best["source_label"]]
    scores = [(resolver.structural_score(c, prefer_source=prefer_source,
                                         parent_source_rel=parent_source_rel,
                                         dependency=dependency), c)
              for c in relevant]
    if not scores:
        return False
    scores.sort(key=lambda x: x[0])
    top_score = scores[0][0]
    top = [c for score, c in scores if score == top_score]
    return len({c["sha256"] for c in top}) == 1


def resolve_base_actions(rows: List[dict], candidate_map: Dict[str, List[dict]],
                         resolver: MultiSourceResolver, baseline_source: str) -> None:
    for r in rows:
        cands = candidate_map.get(r["asset_id"], [])
        if int(r.get("target_hits") or 0) > 0:
            r["action"] = "KEEP_TARGET"
            if r["status"] == "PRESENT_TARGET_CONFLICT":
                r["resolution"] = "TARGET_PRESERVED_CONFLICT"
                r["action_reason"] = "target already exists; donor variants are informational and are not auto-overwritten"
            else:
                r["resolution"] = "TARGET_PRESENT"
                r["action_reason"] = "asset already present in target"
            continue
        if not cands:
            r["action"] = "MISSING"
            r["resolution"] = "NO_SOURCE_CANDIDATE"
            r["action_reason"] = "not found in any configured source"
            continue

        best = choose_base_candidate(cands, baseline_source, resolver)
        update_selected(r, best)
        if not best:
            r["action"] = "REVIEW"
            r["resolution"] = "NO_SELECTION"
            r["action_reason"] = "source candidates exist but none could be selected"
            continue

        # basename-only logical assets need a later destination inference pass.
        if r["search_mode"] == "basename":
            r["action"] = "PENDING_DESTINATION"
            r["resolution"] = "BASENAME_DESTINATION_PENDING"
            r["action_reason"] = "runtime directory must be proven from target peers or another path reference"
            continue

        source_variants = len({c["sha256"] for c in cands})
        unique_in_selected_source = structurally_unique_best(cands, best, resolver)
        if source_variants <= 1:
            r["action"] = "STAGE_SAFE"
            r["resolution"] = "UNIQUE_SOURCE_BYTES"
            r["action_reason"] = "single source byte variant; runtime destination is explicit"
        elif baseline_source and best["source_label"] == baseline_source and unique_in_selected_source:
            r["action"] = "STAGE_SAFE"
            if best["match_type"].startswith("ALIAS_"):
                r["resolution"] = "BASELINE_LINEAGE_KNOWN_ALIAS"
                r["action_reason"] = f"target lineage strongly matches {baseline_source}; known source alias; selected-source candidate is structurally unique"
            else:
                r["resolution"] = "BASELINE_LINEAGE"
                r["action_reason"] = f"target lineage strongly matches {baseline_source}; selected-source candidate is structurally unique"
        else:
            r["action"] = "REVIEW"
            r["resolution"] = "SOURCE_VARIANT_AMBIGUITY"
            r["action_reason"] = "multiple donor byte variants without sufficient target-lineage evidence for this selection"


def infer_basename_runtime_destinations(rows: List[dict], candidate_map: Dict[str, List[dict]],
                                        resolver: MultiSourceResolver, baseline_source: str) -> None:
    # Learn target directories from same category+class peers.  This is especially
    # useful for explicit TGAs, whose EU table intentionally stores basename only.
    peer_dirs: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r.get("search_mode") != "basename" or not r.get("target_rel"):
            continue
        key = (r.get("category", ""), r.get("classes", ""))
        for target_rel in str(r["target_rel"]).split(" | "):
            if target_rel:
                peer_dirs[key].add(PurePosixPath(clean_rel(target_rel)).parent.as_posix())

    for r in rows:
        if r.get("action") != "PENDING_DESTINATION":
            continue
        cands = candidate_map.get(r["asset_id"], [])
        best = choose_base_candidate(cands, baseline_source, resolver)
        update_selected(r, best)
        key = (r.get("category", ""), r.get("classes", ""))
        dirs = peer_dirs.get(key, set())
        if len(dirs) == 1 and best:
            parent = next(iter(dirs))
            r["runtime_dest"] = clean_rel(str(PurePosixPath(parent) / Path(r["expected"]).name))
            if len({c["sha256"] for c in cands}) <= 1:
                r["action"] = "STAGE_SAFE"
                r["resolution"] = "TARGET_PEER_DIRECTORY"
                r["action_reason"] = f"basename-only asset directory inferred from existing {r.get('classes') or r.get('category')} peers in target"
            elif baseline_source and best["source_label"] == baseline_source and structurally_unique_best(cands, best, resolver):
                r["action"] = "STAGE_SAFE"
                r["resolution"] = "TARGET_PEER_DIRECTORY_BASELINE"
                r["action_reason"] = "runtime directory inferred from target peers and donor bytes selected from target baseline lineage"
            else:
                r["action"] = "REVIEW"
                r["resolution"] = "BASENAME_BYTES_AMBIGUOUS"
                r["action_reason"] = "runtime directory is inferred, but donor byte variants remain ambiguous"
        else:
            r["action"] = "REVIEW"
            r["resolution"] = "BASENAME_DESTINATION_UNPROVEN"
            r["action_reason"] = "basename-only asset has no unique peer runtime directory in target"


def is_rootish(ref: str) -> bool:
    parts = PurePosixPath(clean_rel(ref)).parts
    return bool(parts and parts[0].casefold() in ROOTISH_PREFIXES)


def logical_part_dependency(parent_expected: str, ref: str) -> Tuple[str, str]:
    ref_clean = clean_rel(ref)
    if not ref_clean:
        return "", "basename"
    if "/" in ref_clean and is_rootish(ref_clean):
        return ref_clean, "path"
    if "/" in ref_clean:
        base = PurePosixPath(clean_rel(parent_expected)).parent
        return clean_rel(str(base / ref_clean)), "path"
    base = PurePosixPath(clean_rel(parent_expected)).parent
    if str(base) not in ("", "."):
        return clean_rel(str(base / ref_clean)), "path"
    return ref_clean, "basename"


def resolve_dependency_action(asset: dict, cands: List[dict], parent: dict,
                              resolver: MultiSourceResolver) -> None:
    if int(asset.get("target_hits") or 0) > 0:
        asset["action"] = "KEEP_TARGET"
        asset["resolution"] = "TARGET_PRESENT"
        asset["action_reason"] = "dependency already present in target"
        return
    if not cands or not asset.get("selected_path"):
        asset["action"] = "MISSING"
        asset["resolution"] = "NO_SOURCE_CANDIDATE"
        asset["action_reason"] = "dependency not found in any configured source"
        return

    best = cands[0]
    parent_source = parent.get("selected_source", "")
    same_bundle = bool(parent_source and best["source_label"] == parent_source)
    unique = structurally_unique_best(
        cands, best, resolver, prefer_source=parent_source,
        parent_source_rel=parent.get("selected_rel", ""), dependency=True,
    )

    # For exact/rootish logical refs the code/runtime path itself is authoritative.
    raw_ref = clean_rel(asset.get("references", ""))
    if "/" in raw_ref and is_rootish(raw_ref):
        asset["runtime_dest"] = clean_rel(raw_ref)
    elif best["match_type"] == "RELATIVE":
        # A literal relative ref that physically exists next to the donor PART maps
        # to the logical path derived from the parent runtime path.
        asset["runtime_dest"] = clean_rel(asset["expected"])
    else:
        # Loose PART resources are staged where the coherent donor client physically
        # stores them, not beside the script.  This avoids v7's Script/flare.tga bug.
        asset["runtime_dest"] = resolver.runtime_rel(best["source_label"], best["source_rel"])

    if not asset["runtime_dest"]:
        asset["action"] = "REVIEW"
        asset["resolution"] = "DEPENDENCY_DESTINATION_UNPROVEN"
        asset["action_reason"] = "could not derive a runtime-relative destination from the selected donor"
    elif same_bundle and unique:
        asset["action"] = "STAGE_SAFE"
        asset["resolution"] = "PART_BUNDLE_COHERENT"
        asset["action_reason"] = f"dependency selected from the same donor bundle as parent {parent.get('asset_id','')} with a unique structural best candidate"
    else:
        asset["action"] = "REVIEW"
        asset["resolution"] = "PART_BUNDLE_AMBIGUOUS"
        if not same_bundle:
            asset["action_reason"] = "best dependency candidate is not from the same donor as its parent PART"
        else:
            asset["action_reason"] = "multiple equally plausible dependency candidates remain inside the selected donor bundle"


def follow_part_dependencies(base_rows: List[dict], resolver: MultiSourceResolver,
                             target_index: Optional[CaseIndex], max_depth: int) -> Tuple[List[dict], List[dict]]:
    """Resolve transitive references from selected PART candidates breadth-first."""
    rows: List[dict] = []
    candidate_rows: List[dict] = []
    seen = {(r["search_mode"], norm_key(r["expected"])) for r in base_rows}
    queue = deque()
    for r in base_rows:
        if Path(r["expected"]).suffix.casefold() == ".part" and r.get("selected_path"):
            queue.append((r, 0))

    dep_seq = 1
    all_by_id = {r["asset_id"]: r for r in base_rows}
    while queue:
        parent, depth = queue.popleft()
        if depth >= max_depth:
            continue
        parent_path = Path(parent["selected_path"])
        if not parent_path.is_file():
            continue
        try:
            refs = extract_text_refs(parent_path)
        except OSError:
            continue
        for ref in refs:
            if Path(clean_rel(ref)).suffix.casefold() not in PART_DEP_EXTS:
                continue
            logical, mode = logical_part_dependency(parent["expected"], ref)
            if not logical:
                continue
            key = (mode, norm_key(logical) if mode == "path" else Path(logical).name.casefold())
            if key in seen:
                continue
            seen.add(key)
            asset = {
                "asset_id": f"D{dep_seq:04d}",
                "category": "part_dependency",
                "expected": logical,
                "search_mode": mode,
                "classes": parent.get("classes", ""),
                "tiers": parent.get("tiers", ""),
                "skill_ids": parent.get("skill_ids", ""),
                "origins": parent.get("selected_rel", ""),
                "references": ref,
                "parent_asset": parent["asset_id"],
                "depth": depth + 1,
            }
            dep_seq += 1
            parent_context = {
                "source_label": parent.get("selected_source", ""),
                "source_path": parent.get("selected_path", ""),
                "source_rel": parent.get("selected_rel", ""),
                "raw_ref": ref,
            }
            cands = resolver.candidates(
                logical,
                basename_only=(mode == "basename"),
                prefer_source=parent.get("selected_source", ""),
                parent_context=parent_context,
            )
            row = classify_with_candidates(asset, cands, resolver, target_index)
            resolve_dependency_action(row, cands, parent, resolver)
            rows.append(row)
            all_by_id[row["asset_id"]] = row
            for c in cands:
                candidate_rows.append({"asset_id": row["asset_id"], **c})
            if Path(logical).suffix.casefold() == ".part" and row.get("selected_path"):
                queue.append((row, depth + 1))
    return rows, candidate_rows


def _fuzzy_name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", Path(name).stem.casefold())



def reconcile_runtime_dest_collisions(rows: Sequence[dict], baseline_source: str) -> List[dict]:
    """Resolve multiple STAGE_SAFE rows that converge on one runtime destination.

    PART scripts from different lineages can legitimately reference the same loose
    texture basename while their donor clients contain different bytes.  One runtime
    path cannot hold both variants.  When the target lineage is strongly known and a
    unique baseline hash exists for that destination, preserve the baseline bytes
    globally.  Otherwise downgrade the colliding rows to REVIEW instead of letting
    staging order choose silently.
    """
    groups: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("action") != "STAGE_SAFE":
            continue
        dest = clean_rel(r.get("runtime_dest", ""))
        if dest:
            groups[norm_key(dest)].append(r)

    report: List[dict] = []
    for _, group in groups.items():
        hashes = {r.get("selected_sha256", "") for r in group if r.get("selected_sha256")}
        if len(hashes) <= 1:
            continue

        baseline_rows = [r for r in group if baseline_source and r.get("selected_source") == baseline_source]
        baseline_hashes = {r.get("selected_sha256", "") for r in baseline_rows if r.get("selected_sha256")}
        chosen = None
        resolution = "UNRESOLVED"
        if baseline_rows and len(baseline_hashes) == 1:
            chosen = baseline_rows[0]
            resolution = "BASELINE_LINEAGE_WINS"
            chosen_fields = (
                "selected_source", "selected_match", "selected_rel", "selected_path",
                "selected_sha256", "selected_size",
            )
            for r in group:
                if r.get("selected_sha256") != chosen.get("selected_sha256"):
                    for k in chosen_fields:
                        r[k] = chosen.get(k, "")
                    r["resolution"] = "SHARED_RUNTIME_BASELINE"
                    r["action"] = "STAGE_SAFE"
                    r["action_reason"] = (
                        f"shared runtime destination has divergent donor bytes; target baseline "
                        f"lineage {baseline_source} wins globally to avoid staging-order overwrite"
                    )
        else:
            for r in group:
                r["action"] = "REVIEW"
                r["resolution"] = "SHARED_RUNTIME_COLLISION"
                r["action_reason"] = (
                    "multiple STAGE_SAFE dependencies resolve to the same runtime destination "
                    "with different bytes and no unique baseline winner"
                )

        report.append({
            "runtime_dest": clean_rel(group[0].get("runtime_dest", "")),
            "asset_ids": " | ".join(r.get("asset_id", "") for r in group),
            "expected_refs": " | ".join(r.get("expected", "") for r in group),
            "sha256_variants": len(hashes),
            "resolution": resolution,
            "chosen_source": chosen.get("selected_source", "") if chosen else "",
            "chosen_path": chosen.get("selected_path", "") if chosen else "",
            "chosen_sha256": chosen.get("selected_sha256", "") if chosen else "",
        })
    return report

def find_near_matches(missing_rows: Sequence[dict], resolver: MultiSourceResolver,
                      per_source: int = 8, cutoff: float = 0.52) -> List[dict]:
    """Suggest filenames for true misses; suggestions are never auto-staged."""
    out = []
    for r in missing_rows:
        expected_name = Path(r["expected"]).name
        expected_ext = Path(expected_name).suffix.casefold()
        needle = _fuzzy_name_key(expected_name)
        if not needle:
            continue
        for source in resolver.sources:
            scored_names = []
            for base_name in source.index.basename.keys():
                if Path(base_name).suffix.casefold() != expected_ext:
                    continue
                hay = _fuzzy_name_key(base_name)
                if not hay:
                    continue
                score = difflib.SequenceMatcher(None, needle, hay).ratio()
                # Reward common code prefixes (TF26, R5, etc.) and substrings.
                prefix_bonus = 0.08 if needle[:3] and hay.startswith(needle[:3]) else 0.0
                substring_bonus = 0.08 if needle in hay or hay in needle else 0.0
                score = min(1.0, score + prefix_bonus + substring_bonus)
                if score >= cutoff:
                    scored_names.append((score, base_name))
            scored_names.sort(key=lambda x: (-x[0], x[1]))
            used = 0
            for score, base_name in scored_names:
                for p in source.index.find_basename(base_name):
                    out.append({
                        "asset_id": r["asset_id"],
                        "expected": r["expected"],
                        "source_label": source.label,
                        "source_rel": source.index.rel(p),
                        "source_path": str(p),
                        "candidate_name": p.name,
                        "similarity": f"{score:.4f}",
                        "size": p.stat().st_size,
                        "sha256": resolver.file_hash(p),
                    })
                    used += 1
                    if used >= per_source:
                        break
                if used >= per_source:
                    break
    return out


def safe_stage(rows: Sequence[dict], stage_dir: Path) -> List[dict]:
    """Create a separate evidence-approved patch tree; never touches live target."""
    log = []
    stage_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        selected = r.get("selected_path", "")
        runtime_dest = clean_rel(r.get("runtime_dest", ""))
        action = r.get("action", "")
        if not action:
            # Backward-compatible fallback for callers using classify_asset() directly.
            if int(r.get("target_hits") or 0) > 0:
                action = "KEEP_TARGET"
            elif not selected:
                action = "MISSING"
            elif r.get("needs_review") == "YES":
                action = "REVIEW"
            elif r.get("search_mode") == "basename" or not runtime_dest:
                action = "REVIEW"
            else:
                action = "STAGE_SAFE"
        result = "SKIP"
        detail = ""
        dest = ""
        if action == "KEEP_TARGET":
            detail = "already present in target"
        elif action == "MISSING":
            detail = "no source candidate"
        elif action != "STAGE_SAFE":
            detail = "candidate requires review"
        elif not selected:
            detail = "no selected source candidate"
        elif not runtime_dest:
            detail = "runtime destination is not proven"
        else:
            src = Path(selected)
            dst = stage_dir / runtime_dest
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                if sha256_file(dst) == r.get("selected_sha256"):
                    result = "PRESENT_STAGE_IDENTICAL"
                else:
                    result = "CONFLICT_STAGE"
                    detail = "stage destination already exists with different bytes"
            else:
                shutil.copyfile(src, dst)
                if sha256_file(dst) != r.get("selected_sha256"):
                    raise RuntimeError(f"staged SHA mismatch: {dst}")
                result = "STAGED"
            dest = str(dst)
        log.append({
            "asset_id": r.get("asset_id", ""), "expected": r.get("expected", ""),
            "runtime_dest": runtime_dest, "action": action,
            "resolution": r.get("resolution", ""),
            "source_path": selected, "source_sha256": r.get("selected_sha256", ""),
            "stage_path": dest, "result": result, "detail": detail,
        })
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix 136 v9: evidence-aware recursive multi-source EU skill asset audit")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    ap.add_argument("--effects", default=str(DEFAULT_EFFECTS))
    ap.add_argument("--out-dir", default="manifests/fix136_skill_assets")
    ap.add_argument("--target", default="", help="override target_client from config")
    ap.add_argument("--tier", type=int, action="append", help="limit central skill table to one/more tiers; effects are still audited")
    ap.add_argument("--max-part-depth", type=int, default=8)
    ap.add_argument("--no-part-closure", action="store_true")
    ap.add_argument("--stage-dir", default="", help="optional separate patch staging root; live client is never modified")
    args = ap.parse_args()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sources, source_state = build_sources(cfg)
    if not sources:
        print(json.dumps({"error": "none of the configured source roots is available", "sources": source_state}, ensure_ascii=False, indent=2))
        return 2

    target_root_s = args.target or cfg.get("target_client", "")
    target_root = Path(os.path.expanduser(target_root_s)).resolve() if target_root_s else None
    target_available = bool(target_root and target_root.is_dir())
    target_index = CaseIndex(target_root) if target_available and target_root else None

    tiers = set(args.tier) if args.tier else None
    wanted = load_wanted(Path(args.inventory), Path(args.effects), tiers)
    resolver = MultiSourceResolver(sources)
    rows: List[dict] = []
    candidates: List[dict] = []
    candidate_map: Dict[str, List[dict]] = defaultdict(list)
    for asset in wanted:
        row, cands = classify_asset(asset, resolver, target_index)
        rows.append(row)
        candidate_map[row["asset_id"]] = cands
        for c in cands:
            candidates.append({"asset_id": row["asset_id"], **c})

    baseline_source, baseline_evidence = infer_baseline_source(rows, candidate_map)
    resolve_base_actions(rows, candidate_map, resolver, baseline_source)
    infer_basename_runtime_destinations(rows, candidate_map, resolver, baseline_source)

    dep_rows: List[dict] = []
    dep_candidates: List[dict] = []
    if not args.no_part_closure:
        dep_rows, dep_candidates = follow_part_dependencies(rows, resolver, target_index, max(0, args.max_part_depth))
        rows.extend(dep_rows)
        candidates.extend(dep_candidates)
        for c in dep_candidates:
            candidate_map[c["asset_id"]].append({k: v for k, v in c.items() if k != "asset_id"})

    runtime_collisions = reconcile_runtime_dest_collisions(rows, baseline_source)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_fields = [
        "asset_id","category","expected","runtime_dest","search_mode","classes","tiers","skill_ids","origins","references","parent_asset","depth",
        "status","target_hits","target_rel","target_sha256","candidate_count","source_hash_variants","needs_review","review_reason",
        "selected_source","selected_match","selected_rel","selected_path","selected_sha256","selected_size",
        "resolution","action","action_reason",
    ]
    cand_fields = ["asset_id","source_label","source_priority","source_root","match_type","matched_as","expected","source_rel","source_path","size","sha256"]
    write_csv(out_dir / "fix136_asset_matrix.csv", rows, asset_fields)
    write_csv(out_dir / "fix136_all_candidates.csv", candidates, cand_fields)
    collision_fields = ["runtime_dest","asset_ids","expected_refs","sha256_variants","resolution","chosen_source","chosen_path","chosen_sha256"]
    write_csv(out_dir / "fix136_runtime_collisions.csv", runtime_collisions, collision_fields)

    missing = [r for r in rows if r["action"] == "MISSING"]
    actionable_review = [r for r in rows if r["action"] == "REVIEW"]
    informational_review = [r for r in rows if r.get("needs_review") == "YES"]
    (out_dir / "missing_assets.txt").write_text("\n".join(r["expected"] for r in missing) + ("\n" if missing else ""), encoding="utf-8")

    near = find_near_matches(missing, resolver)
    near_fields = ["asset_id","expected","source_label","source_rel","source_path","candidate_name","similarity","size","sha256"]
    write_csv(out_dir / "fix136_near_matches.csv", near, near_fields)

    source_hits = Counter(c["source_label"] for c in candidates)
    selected_hits = Counter(r["selected_source"] for r in rows if r.get("selected_source"))
    summary = {
        "config": str(cfg_path),
        "target": str(target_root) if target_root else "",
        "target_available": target_available,
        "sources": source_state,
        "base_assets": len(wanted),
        "part_dependencies_discovered": len(dep_rows),
        "total_assets": len(rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "categories": dict(Counter(r["category"] for r in rows)),
        "baseline_source": baseline_source,
        "baseline_evidence": baseline_evidence,
        "informational_review": len(informational_review),
        "actionable_review": len(actionable_review),
        "actions": dict(Counter(r["action"] for r in rows)),
        "missing_all_sources": len(missing),
        "near_match_suggestions": len(near),
        "runtime_collision_groups": len(runtime_collisions),
        "runtime_collisions_auto_resolved": sum(c["resolution"] == "BASELINE_LINEAGE_WINS" for c in runtime_collisions),
        "runtime_collisions_unresolved": sum(c["resolution"] == "UNRESOLVED" for c in runtime_collisions),
        "candidate_hits_by_source": dict(source_hits),
        "selected_by_source": dict(selected_hits),
        "outputs": {
            "matrix": str(out_dir / "fix136_asset_matrix.csv"),
            "candidates": str(out_dir / "fix136_all_candidates.csv"),
            "missing": str(out_dir / "missing_assets.txt"),
            "near_matches": str(out_dir / "fix136_near_matches.csv"),
            "runtime_collisions": str(out_dir / "fix136_runtime_collisions.csv"),
        },
    }

    if args.stage_dir:
        stage_log = safe_stage(rows, Path(args.stage_dir).expanduser().resolve())
        write_csv(out_dir / "fix136_stage_manifest.csv", stage_log,
                  ["asset_id","expected","runtime_dest","action","resolution","source_path","source_sha256","stage_path","result","detail"])
        summary["staging"] = dict(Counter(r["result"] for r in stage_log))
        summary["outputs"]["stage_manifest"] = str(out_dir / "fix136_stage_manifest.csv")

    json_dump(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
