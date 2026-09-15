from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

FORMAT = "PT_CHARACTER_PROFILE_REGISTRY_V1"


@dataclass(frozen=True)
class CharacterProfile:
    profile_id: str
    profile_version: int
    display_name: str
    owner_name: str
    model_smd: str
    skeleton_smb: str
    model_info_inx: str
    roundtrip_target: str
    lod_groups: dict[str, list[str]]
    known_mesh_objects: list[str]
    geometry_status: dict[str, Any]
    components: list[dict[str, Any]]
    source_path: pathlib.Path
    raw: dict[str, Any]

    def lod(self, name: str) -> list[str]:
        q = str(name).strip().lower()
        if q == "all":
            out: list[str] = []
            for tier in ("high", "default", "low"):
                out.extend(self.lod_groups.get(tier, []))
            return list(dict.fromkeys(out))
        if q not in {"high", "default", "low"}:
            raise ValueError("LOD must be high, default, low or all")
        return list(self.lod_groups.get(q, []))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "display_name": self.display_name,
            "owner_name": self.owner_name,
            "model_smd": self.model_smd,
            "skeleton_smb": self.skeleton_smb,
            "model_info_inx": self.model_info_inx,
            "roundtrip_target": self.roundtrip_target,
            "lod_groups": self.lod_groups,
            "known_mesh_objects": self.known_mesh_objects,
            "geometry_status": self.geometry_status,
            "components": self.components,
            "source_path": str(self.source_path),
        }


def _load_one(path: pathlib.Path) -> CharacterProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["profile_id", "model_smd", "skeleton_smb", "model_info_inx", "roundtrip_target", "lod_groups", "known_mesh_objects"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValueError(f"profile {path.name} missing required fields: {missing}")
    lod_groups = {tier: list((data.get("lod_groups") or {}).get(tier) or []) for tier in ("high", "default", "low")}
    known = list(data.get("known_mesh_objects") or [])
    known_set = set(known)
    unknown_lod = sorted({obj for rows in lod_groups.values() for obj in rows if obj not in known_set})
    if unknown_lod:
        raise ValueError(f"profile {path.name} LOD objects absent from known_mesh_objects: {unknown_lod}")
    if not str(data["roundtrip_target"]).replace("\\", "/").lower().endswith(".smd"):
        raise ValueError(f"profile {path.name} roundtrip_target is not SMD")
    return CharacterProfile(
        profile_id=str(data["profile_id"]),
        profile_version=int(data.get("profile_version") or 1),
        display_name=str(data.get("display_name") or data["profile_id"]),
        owner_name=str(data.get("owner_name") or ""),
        model_smd=str(data["model_smd"]),
        skeleton_smb=str(data["skeleton_smb"]),
        model_info_inx=str(data["model_info_inx"]),
        roundtrip_target=str(data["roundtrip_target"]).replace("\\", "/"),
        lod_groups=lod_groups,
        known_mesh_objects=known,
        geometry_status=dict(data.get("geometry_status") or {}),
        components=list(data.get("components") or []),
        source_path=path.resolve(),
        raw=data,
    )


class CharacterProfileRegistry:
    def __init__(self, directory: pathlib.Path):
        self.directory = pathlib.Path(directory).resolve()
        if not self.directory.is_dir():
            raise FileNotFoundError(self.directory)
        profiles = [_load_one(path) for path in sorted(self.directory.glob("*.json"), key=lambda p: p.name.lower())]
        by_id: dict[str, CharacterProfile] = {}
        for profile in profiles:
            key = profile.profile_id.casefold()
            if key in by_id:
                raise ValueError(f"duplicate canonical profile_id: {profile.profile_id}")
            by_id[key] = profile
        self._by_id = by_id

    def list(self) -> list[CharacterProfile]:
        return sorted(self._by_id.values(), key=lambda p: (p.owner_name.casefold(), p.profile_id.casefold()))

    def get(self, profile_id: str) -> CharacterProfile:
        key = str(profile_id).casefold()
        if key not in self._by_id:
            raise KeyError(f"character profile not found: {profile_id}")
        return self._by_id[key]

    def match_asset(self, logical_path: str) -> list[dict[str, Any]]:
        """Return profiles with explicit path evidence for a client asset.

        Matching is exact (case-insensitive) against the profile roundtrip target
        and component roundtrip targets. Basename similarity is intentionally not
        used here because it is not sufficient identity evidence.
        """
        q = str(logical_path or "").replace("\\", "/").strip("/").casefold()
        if not q:
            return []
        out=[]
        for profile in self.list():
            roles=[]
            if profile.roundtrip_target.replace("\\", "/").strip("/").casefold() == q:
                roles.append("PROFILE_MODEL")
            for component in profile.components:
                target = str(component.get("roundtrip_target") or "").replace("\\", "/").strip("/")
                if target and target.casefold() == q:
                    roles.append(str(component.get("role") or "COMPONENT").upper())
            if not roles:
                continue
            out.append({
                "profile_id": profile.profile_id,
                "display_name": profile.display_name,
                "owner_name": profile.owner_name,
                "roles": list(dict.fromkeys(roles)),
                "lod_groups": profile.lod_groups,
                "geometry_status": profile.geometry_status,
                "roundtrip_target": profile.roundtrip_target,
                "evidence": "EXACT_PROFILE_PATH",
            })
        return out

    @staticmethod
    def _basename_candidates(resolver, basename: str) -> list[pathlib.Path]:
        q = str(basename or "").strip().casefold()
        if not q:
            return []
        return sorted(
            [path for path in resolver.index.values() if path.name.casefold() == q],
            key=lambda path: path.as_posix().casefold(),
        )

    def verify(self, profile_id: str, resolver, *, asset_registry=None, sha256_func=None) -> dict[str, Any]:
        """Verify a canonical profile against the currently configured client.

        This is provenance/readiness validation only.  A profile being present
        and hash-matched does not authorize geometry or client writers.
        """
        import hashlib

        profile = self.get(profile_id)
        if sha256_func is None:
            def sha256_func(path):
                h = hashlib.sha256()
                with pathlib.Path(path).open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        h.update(chunk)
                return h.hexdigest()

        rows = []
        failures = []
        for index, component in enumerate(profile.components):
            role = str(component.get("role") or f"component_{index}")
            required = bool(component.get("required", False))
            target = str(component.get("roundtrip_target") or "").replace("\\", "/")
            discovered_by = "ROUNDTRIP_TARGET" if target else ""
            physical = resolver.resolve(target, required=False) if target else None
            candidates = []
            if physical is None and component.get("discover_client_by_basename"):
                candidates = self._basename_candidates(resolver, component["discover_client_by_basename"])
                if len(candidates) == 1:
                    physical = candidates[0]
                    target = physical.relative_to(resolver.client_root).as_posix()
                    discovered_by = "UNIQUE_BASENAME"
                elif len(candidates) > 1:
                    discovered_by = "AMBIGUOUS_BASENAME"
            if physical is None and not target and component.get("local_source"):
                candidates = self._basename_candidates(resolver, component["local_source"])
                if len(candidates) == 1:
                    physical = candidates[0]
                    target = physical.relative_to(resolver.client_root).as_posix()
                    discovered_by = "UNIQUE_LOCAL_SOURCE_BASENAME"
                elif len(candidates) > 1:
                    discovered_by = "AMBIGUOUS_LOCAL_SOURCE_BASENAME"

            expected_size = component.get("verified_client_size")
            expected_sha = str(component.get("verified_client_sha256") or "").lower()
            status = "PASS"
            reason = "PRESENT"
            actual_size = None
            actual_sha = ""
            if physical is None:
                status = "FAIL" if required else "SKIP"
                reason = "REQUIRED_COMPONENT_UNRESOLVED" if required else "OPTIONAL_COMPONENT_UNRESOLVED"
            else:
                actual_size = physical.stat().st_size
                if expected_size not in (None, "") and int(expected_size) != int(actual_size):
                    status = "FAIL"
                    reason = "SIZE_MISMATCH"
                if expected_sha:
                    actual_sha = str(sha256_func(physical)).lower()
                    if actual_sha != expected_sha:
                        status = "FAIL"
                        reason = "SHA256_MISMATCH"
                    elif reason == "PRESENT":
                        reason = "HASH_MATCH"
                elif reason == "PRESENT":
                    reason = "PRESENT_UNPINNED"
            row = {
                "role": role,
                "required": required,
                "logical_path": target or None,
                "physical_path": str(physical) if physical is not None else None,
                "discovered_by": discovered_by or None,
                "candidate_count": len(candidates),
                "status": status,
                "reason": reason,
                "expected_size": int(expected_size) if expected_size not in (None, "") else None,
                "actual_size": actual_size,
                "expected_sha256": expected_sha or None,
                "actual_sha256": actual_sha or None,
            }
            rows.append(row)
            if status == "FAIL":
                failures.append({"role": role, "reason": reason, "logical_path": target or None})

        target_physical = resolver.resolve(profile.roundtrip_target, required=False)
        if target_physical is None:
            failures.append({"role": "roundtrip_target", "reason": "ROUNDTRIP_TARGET_UNRESOLVED", "logical_path": profile.roundtrip_target})

        semantic_evidence = {
            "status": "SKIP",
            "reason": "ASSET_REGISTRY_NOT_PROVIDED",
            "target_registry_asset": None,
            "family": None,
            "binding_skeleton_match": None,
            "model_info_inx_match": None,
            "lod_groups_match": None,
            "matching_inx": [],
        }
        if asset_registry is not None:
            try:
                asset = asset_registry.resolve(profile.roundtrip_target)
            except Exception as exc:
                semantic_evidence.update({
                    "status": "FAIL",
                    "reason": f"TARGET_NOT_IN_ASSET_REGISTRY:{type(exc).__name__}",
                })
                failures.append({
                    "role": "semantic_profile",
                    "reason": "ROUNDTRIP_TARGET_NOT_IN_ASSET_REGISTRY",
                    "logical_path": profile.roundtrip_target,
                })
            else:
                cfgs = list(getattr(asset, "configs", []) or [])
                profile_lods = {
                    tier: list(profile.lod_groups.get(tier, []))
                    for tier in ("high", "default", "low")
                }
                matching_cfgs = [
                    c for c in cfgs
                    if {
                        tier: list((c.get("lod_groups") or {}).get(tier, []) or [])
                        for tier in ("high", "default", "low")
                    } == profile_lods
                ]
                profile_inx = str(profile.model_info_inx or "").replace("\\", "/").strip("/")
                if "/" in profile_inx:
                    inx_cfgs = [
                        c for c in cfgs
                        if str(c.get("inx") or "").replace("\\", "/").strip("/").casefold() == profile_inx.casefold()
                    ]
                    inx_match_evidence = "EXACT_ASSOCIATED_INX_PATH"
                else:
                    inx_cfgs = [
                        c for c in cfgs
                        if pathlib.PurePosixPath(str(c.get("inx") or "").replace("\\", "/")).name.casefold() == profile_inx.casefold()
                    ]
                    inx_match_evidence = "UNIQUE_ASSOCIATED_INX_BASENAME"
                inx_match = len(inx_cfgs) == 1
                exact_context_cfgs = [c for c in matching_cfgs if c in inx_cfgs]
                lod_match = len(exact_context_cfgs) == 1
                skeleton_name = pathlib.PurePosixPath(str(profile.skeleton_smb).replace("\\", "/")).name.casefold()
                selected_skeleton_name = ""
                if len(exact_context_cfgs) == 1:
                    selected_skeleton_name = pathlib.PurePosixPath(str(exact_context_cfgs[0].get("motion_smb") or "").replace("\\", "/")).name.casefold()
                skeleton_match = bool(skeleton_name and selected_skeleton_name and skeleton_name == selected_skeleton_name)
                semantic_failures = []
                if not inx_match:
                    semantic_failures.append("MODEL_INFO_INX_MISMATCH")
                if not lod_match:
                    semantic_failures.append("LOD_GROUPS_NOT_CONFIRMED_BY_SELECTED_INX")
                if not skeleton_match:
                    semantic_failures.append("SKELETON_MISMATCH")
                semantic_evidence = {
                    "status": "PASS" if not semantic_failures else "FAIL",
                    "reason": "EXACT_ASSET_UNIQUE_INX_LOD_SKELETON_MATCH" if not semantic_failures else ",".join(semantic_failures),
                    "target_registry_asset": getattr(asset, "asset_id", None),
                    "family": getattr(asset, "family", None),
                    "binding_skeleton_match": skeleton_match,
                    "profile_skeleton_smb": profile.skeleton_smb,
                    "registry_skeleton_smb": exact_context_cfgs[0].get("motion_smb") if len(exact_context_cfgs) == 1 else None,
                    "model_info_inx_match": inx_match,
                    "model_info_match_evidence": inx_match_evidence,
                    "profile_model_info_inx": profile.model_info_inx,
                    "registry_config_inx": sorted(str(c.get("inx")) for c in cfgs if c.get("inx")),
                    "lod_groups_match": lod_match,
                    "matching_inx": sorted(str(c.get("inx")) for c in exact_context_cfgs if c.get("inx")),
                }
                for reason in semantic_failures:
                    failures.append({
                        "role": "semantic_profile",
                        "reason": reason,
                        "logical_path": profile.roundtrip_target,
                    })
        return {
            "format": "PT_CHARACTER_PROFILE_VERIFY_V1",
            "status": "PASS" if not failures else "FAIL",
            "profile": profile.to_dict(),
            "roundtrip_target_present": target_physical is not None,
            "components": rows,
            "semantic_evidence": semantic_evidence,
            "failures": failures,
            "geometry_status": profile.geometry_status,
            "authoring_authorized": False,
            "client_modified": False,
        }

    def summary(self) -> dict[str, Any]:
        profiles = self.list()
        return {
            "format": FORMAT,
            "status": "PASS",
            "directory": str(self.directory),
            "profile_count": len(profiles),
            "profiles": [
                {
                    "profile_id": p.profile_id,
                    "display_name": p.display_name,
                    "owner_name": p.owner_name,
                    "roundtrip_target": p.roundtrip_target,
                    "lod_counts": {tier: len(p.lod_groups.get(tier, [])) for tier in ("high", "default", "low")},
                    "geometry_status": p.geometry_status,
                }
                for p in profiles
            ],
        }
