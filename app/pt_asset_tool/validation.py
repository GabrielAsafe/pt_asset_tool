from __future__ import annotations
import json, os, pathlib, shutil, subprocess
from dataclasses import dataclass
from .certification import CertificationRegistry
from .config import Settings
from .registry import Asset
from .resolver import ClientResolver
from .texture_overlay import (
    prepare_texture_overlay, prepare_stage072_texture_overlay,
    classify_stage072_texture_transport_failures,
)
from .motion_core import build_bake_payload, write_payload
from .static_roundtrip import compare_static_roundtrip
from .object_local import compact_report, parse_object_local_smd
from .multilayer_texlink import compact_semantics, parse_multilayer_semantics
from .texlink_roundtrip import compare_texlink_roundtrip
from .stage072_corpus import parse_stage072
from .stage072_roundtrip import compare_stage072_uv_roundtrip
from .stage072_geometry import (
    CURRENT_MODEL as STAGE072_CURRENT_NORMAL_MODEL,
    SUPPORTED_SOURCE_NORMAL_MODELS as STAGE072_SUPPORTED_GEOMETRY_NORMAL_MODELS,
    compare_stage072_geometry_roundtrip,
    select_stage072_geometry_witness,
)
from .stage072_normals import analyze_stage072_normals
from .utils import run_logged, sha256_file
from .blender_workspace import blender_edit_root, write_workspace_info
from .authoring import (
    authoring_plan, build_selected_authoring_context, build_standalone_rigid_authoring_context, write_workspace_manifest, verify_workspace_manifest,
)
from .rigid_model_info import config_semantic_signature, audit_rigid_model_info_contexts, lod_node_coverage, effective_lod_node_coverage, lod_model_info_configs


@dataclass
class ValidationContext:
    settings: Settings
    resolver: ClientResolver
    certifications: CertificationRegistry




def rigid_model_info_options(asset: Asset) -> list[dict]:
    """Return explicit registry-proven INX choices usable by rigid import.

    Multiple INX files can point at the same SMD/skeleton while carrying
    different LOD node sets.  The UI/CLI must surface those choices instead of
    silently treating the first config as authoritative.
    """
    out=[]
    for cfg in asset.configs:
        if not cfg.get("inx"):
            continue
        groups=cfg.get("lod_groups") or {}
        if not any(groups.get(tier) for tier in ("high","default","low")):
            continue
        normalized_groups = {tier:list(groups.get(tier) or []) for tier in ("high","default","low")}
        out.append({
            "inx": str(cfg.get("inx") or "").replace("\\", "/"),
            "motion_smb": str(cfg.get("motion_smb") or "").replace("\\", "/"),
            "skeleton_resolved": bool(cfg.get("motion_smb")),
            "lod_groups": normalized_groups,
            "available_lods": [tier for tier in ("high","default","low") if groups.get(tier)],
            "lod_node_coverage": {
                tier: lod_node_coverage(asset, cfg, tier)
                for tier in ("high", "default", "low") if normalized_groups.get(tier)
            },
        })
    out.sort(key=lambda x:x["inx"].casefold())
    return out


def _config_semantic_signature(cfg: dict) -> tuple:
    # Backward-compatible local alias for focused tests/internal callers.
    return config_semantic_signature(cfg)


def _config_import_signature(cfg: dict, lod: str) -> tuple:
    return (str(lod), config_semantic_signature(cfg))


class ValidationRunner:
    def __init__(self, ctx: ValidationContext):
        self.ctx = ctx
        self.root = ctx.settings.project_root

    def _asset_workdir(self, asset: Asset, test: str) -> pathlib.Path:
        return self.ctx.settings.work_dir / asset.asset_id / test.lower()

    def structural(self, asset: Asset) -> dict:
        src = self.ctx.resolver.resolve(asset.primary_path)
        work = self._asset_workdir(asset, "STRUCTURAL")
        work.mkdir(parents=True, exist_ok=True)
        source_sha = sha256_file(src)
        result = {"asset_id": asset.asset_id, "asset": asset.primary_path, "source_sha256": source_sha}

        if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            if not asset.rigid_binding_ready:
                raise RuntimeError(f"rigid asset has no unambiguous skeleton binding: binding={asset.binding_mode}")
            smb = self.ctx.resolver.resolve(asset.binding_skeleton_smb)
            structural_report = work / "character_structural.json"
            run_logged([
                "python3", str(self.root / "pt_character_structural_gate_v2.py"),
                "--smd", str(src), "--smb", str(smb), "--report", str(structural_report)
            ], work / "character_structural.log")
            inx_rows = []
            for i, cfg in enumerate(asset.configs):
                if not cfg.get("motion_smb"):
                    continue
                motion_inx = cfg.get("motion_inx") or (cfg.get("inx") if asset.binding_source not in {"STRUCTURAL_GATE_UNIQUE", "SKELETON_SIGNATURE_UNIQUE", "GATE_FIRST_SKELETON_UNIQUE", "PHYSIQUE_SUBSET_EQUIVALENT"} else "")
                if not motion_inx:
                    continue
                inx = self.ctx.resolver.resolve(motion_inx)
                motion = self.ctx.resolver.resolve(cfg["motion_smb"])
                rp = work / f"inx_{i:03d}.json"
                run_logged([
                    "python3", str(self.root / "pt_inx_motion_core_v2.py"),
                    "--inx", str(inx), "--smb", str(motion), "--report", str(rp)
                ], work / f"inx_{i:03d}.log")
                inx_rows.append(json.loads(rp.read_text(encoding="utf-8")))
            result.update({"mode": "RIGID", "binding_mode": asset.binding_mode, "binding_source": asset.binding_source,
                "binding_root_models": asset.binding_root_models,
                "structural_report": str(structural_report), "inx_checks": len(inx_rows), "check": "PASS"})

        elif asset.family == "SMD_MODEL_062_STATIC":
            rp = work / "static_capability.json"
            run_logged([
                "python3", str(self.root / "pt_smd_static_capability_probe_v1.py"),
                "--smd", str(src), "--report", str(rp)
            ], work / "static_capability.log")
            probe = json.loads(rp.read_text(encoding="utf-8"))
            result.update({
                "mode": "STATIC", "static_capability": probe,
                "authoring_ready_v1": bool(probe.get("ready_objects")) and not probe.get("blocked_objects"),
                "check": "PASS",
            })
        else:
            raise RuntimeError(f"no structural validator wired yet for family {asset.family}")

        (work / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STRUCTURAL", layer="AUTOMATIC", result="PASS", source_sha256=source_sha,
            metadata={"workdir": str(work), "mode": result.get("mode")},
        )
        return result

    def _select_rigid_lod(self, asset: Asset, requested: str, *, model_info: str | None = None, require_unambiguous: bool = False, require_motion_smb: bool = True) -> tuple[str, dict]:
        configs = ([x for x in asset.configs if x.get("motion_smb") and x.get("inx")]
                   if require_motion_smb else lod_model_info_configs(asset))
        if not configs:
            reason = " with motion_smb" if require_motion_smb else " with LOD/model groups"
            raise RuntimeError(f"rigid asset has no INX model-info configuration{reason}")
        if model_info:
            q = str(model_info).replace("\\", "/").strip("/").casefold()
            exact = [x for x in configs if str(x.get("inx") or "").replace("\\", "/").strip("/").casefold() == q]
            if not exact:
                choices = [str(x.get("inx")) for x in configs]
                raise RuntimeError(f"requested model-info INX is not associated with this asset: {model_info}; choices={choices}")
            configs = exact

        choices=[]
        for cfg in configs:
            groups = cfg.get("lod_groups") or {}
            if requested != "auto":
                if groups.get(requested):
                    choices.append((requested,cfg))
                continue
            actual = next((lod for lod in ("default","high","low") if groups.get(lod)), None)
            if actual:
                choices.append((actual,cfg))
        if not choices:
            available = sorted({lod for cfg in configs for lod in ("high","default","low") if (cfg.get("lod_groups") or {}).get(lod)})
            raise RuntimeError(f"requested LOD '{requested}' has no active INX nodes; available={available}")

        if require_unambiguous and model_info is None and len(choices) > 1:
            sigs={_config_import_signature(cfg,lod) for lod,cfg in choices}
            if len(sigs) > 1:
                opts=[str(cfg.get("inx")) for _lod,cfg in choices]
                raise RuntimeError(
                    "AMBIGUOUS_MODEL_INFO_CONFIG: multiple INX configurations produce different skeleton/LOD node sets; "
                    f"choose --model-info explicitly; choices={opts}"
                )
        return choices[0]

    def _preflight_rigid_import(
        self, asset: Asset, requested_lod: str, *, model_info: str | None = None,
        require_unambiguous: bool = False,
    ) -> tuple[str, dict, dict]:
        actual_lod, cfg = self._select_rigid_lod(
            asset, requested_lod, model_info=model_info, require_unambiguous=require_unambiguous
        )
        coverage = effective_lod_node_coverage(asset, cfg, actual_lod)
        if coverage.get("status") == "FAIL":
            inx = str(cfg.get("inx") or "").replace("\\", "/")
            raise RuntimeError(
                "MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES: "
                f"model-info={inx} lod={actual_lod} missing={coverage.get('missing_nodes')}; "
                "generic import remains fail-closed for this context"
            )
        return actual_lod, cfg, coverage

    def _preflight_explicit_skeleton_lod_import(
        self, asset: Asset, requested_lod: str, *, model_info: str | None, skeleton_logical: str,
        require_unambiguous: bool = False,
    ) -> dict:
        """Bind an INX LOD context to an explicit structurally-proven SMB.

        Equipment/model-info INX files often carry LOD groups without a
        ``motion_smb``.  The LOD config remains useful when a skeleton is proven
        independently.  This path never guesses a skeleton and never overrides
        an INX config that already names a different SMB.
        """
        actual_lod, cfg = self._select_rigid_lod(
            asset, requested_lod, model_info=model_info,
            require_unambiguous=require_unambiguous, require_motion_smb=False,
        )
        logical = str(skeleton_logical or "").replace("\\", "/").strip("/")
        if not logical:
            raise RuntimeError("explicit skeleton LOD import requires --skeleton")
        cfg_smb = str(cfg.get("motion_smb") or "").replace("\\", "/").strip("/")
        bound_smb = str(asset.binding_skeleton_smb or "").replace("\\", "/").strip("/")
        if cfg_smb and cfg_smb.casefold() != logical.casefold():
            raise RuntimeError("explicit --skeleton conflicts with the selected model-info motion_smb")
        if not cfg_smb and bound_smb and bound_smb.casefold() != logical.casefold():
            raise RuntimeError("explicit --skeleton conflicts with the resolved asset skeleton binding")
        coverage = effective_lod_node_coverage(asset, cfg, actual_lod)
        if coverage.get("status") != "PASS":
            raise RuntimeError(
                "MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES: "
                f"model-info={cfg.get('inx')} lod={actual_lod} missing={coverage.get('missing_nodes')}; "
                "generic import remains fail-closed for this context"
            )
        source = pathlib.Path(self.ctx.resolver.resolve(asset.primary_path, required=True)).resolve()
        skeleton = pathlib.Path(self.ctx.resolver.resolve(logical, required=True)).resolve()
        model_info_path = pathlib.Path(self.ctx.resolver.resolve(cfg.get("inx"), required=True)).resolve()
        work = self._asset_workdir(asset, "RIGID_EXPLICIT_SKELETON_LOD_PREFLIGHT")
        work.mkdir(parents=True, exist_ok=True)
        report = work / "structural.json"
        run_logged([
            "python3", str(self.root / "pt_character_structural_gate_v2.py"),
            "--smd", str(source), "--smb", str(skeleton), "--report", str(report),
        ], work / "structural.log")
        data = json.loads(report.read_text(encoding="utf-8"))
        status = str(data.get("result") or data.get("check") or data.get("status") or "")
        if status != "PASS":
            raise RuntimeError(
                "EXPLICIT_SKELETON_LOD_STRUCTURAL_MISMATCH: "
                f"asset={asset.primary_path} skeleton={logical}; structural gate did not PASS"
            )
        return {
            "source": source, "skeleton": skeleton, "skeleton_logical": logical,
            "model_info": model_info_path, "model_info_logical": str(cfg.get("inx") or "").replace("\\", "/"),
            "structural_report": report, "structural": data,
            "lod": actual_lod, "cfg": cfg, "lod_node_coverage": coverage,
        }

    def _preflight_standalone_rigid_import(self, asset: Asset, skeleton_logical: str) -> dict:
        if asset.kind != "SMD_MODEL_062" or asset.family not in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
            raise RuntimeError("--skeleton standalone context requires rigid/mixed Model0.62")
        usable = [cfg for cfg in asset.configs if cfg.get("inx") and cfg.get("motion_smb")]
        usable_lod = [
            cfg for cfg in usable
            if any((cfg.get("lod_groups") or {}).get(name) or [] for name in ("high", "default", "low"))
        ]
        if usable_lod:
            raise RuntimeError("--skeleton cannot bypass an asset with a usable model-info+LOD context; use --model-info/--profile")
        logical = str(skeleton_logical or "").replace("\\", "/").strip("/")
        if not logical:
            raise RuntimeError("standalone rigid import requires an explicit --skeleton logical client path")
        if usable:
            bound = str(asset.binding_skeleton_smb or "").replace("\\", "/").strip("/")
            if not bound or bound.casefold() != logical.casefold():
                raise RuntimeError("--skeleton for an INX-bound no-LOD asset must exactly match the resolved binding skeleton")
        source = pathlib.Path(self.ctx.resolver.resolve(asset.primary_path, required=True)).resolve()
        skeleton = pathlib.Path(self.ctx.resolver.resolve(logical, required=True)).resolve()
        work = self._asset_workdir(asset, "RIGID_STANDALONE_PREFLIGHT")
        work.mkdir(parents=True, exist_ok=True)
        report = work / "structural.json"
        run_logged([
            "python3", str(self.root / "pt_character_structural_gate_v2.py"),
            "--smd", str(source), "--smb", str(skeleton), "--report", str(report),
        ], work / "structural.log")
        data = json.loads(report.read_text(encoding="utf-8"))
        status = str(data.get("result") or data.get("check") or data.get("status") or "")
        if status != "PASS":
            raise RuntimeError(
                "STANDALONE_RIGID_SKELETON_STRUCTURAL_MISMATCH: "
                f"asset={asset.primary_path} skeleton={logical}; structural gate did not PASS"
            )
        plan = authoring_plan(asset, source)
        nodes = [
            str(row.get("name")) for row in ((plan.get("source_analysis") or {}).get("objects") or [])
            if bool(row.get("physique")) and str(row.get("name") or "")
        ]
        if not nodes:
            raise RuntimeError("standalone rigid source has no Physique objects")
        return {
            "source": source, "skeleton": skeleton, "skeleton_logical": logical,
            "structural_report": report, "structural": data, "selected_nodes": nodes,
        }

    def _prepare_standalone_rigid_blend(
        self, asset: Asset, work: pathlib.Path, client_root: pathlib.Path, preflight: dict,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        source = pathlib.Path(preflight["source"]).resolve()
        skeleton = pathlib.Path(preflight["skeleton"]).resolve()
        pristine = work / "pristine_import.blend"
        importer = self.root / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(importer), "--",
            "--smd", str(source), "--skeleton", str(skeleton),
            "--client-root", str(client_root), "--out", str(pristine), "--no-pack",
        ], work / "01_import.log")
        return source, pristine

    def _prepare_explicit_skeleton_lod_blend(
        self, asset: Asset, work: pathlib.Path, client_root: pathlib.Path, preflight: dict,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        source = pathlib.Path(preflight["source"]).resolve()
        pristine = work / "pristine_import.blend"
        importer = self.root / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py"
        cmd = self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(importer), "--",
            "--smd", str(source), "--skeleton", str(preflight["skeleton"]),
            "--model-info", str(preflight["model_info"]), "--lod", str(preflight["lod"]),
            "--client-root", str(client_root), "--out", str(pristine), "--no-pack",
        ]
        if (preflight.get("lod_node_coverage") or {}).get("selection_mode") == "SINGLE_TIER_FULL_CONTAINER":
            cmd.append("--single-tier-full-container")
        run_logged(cmd, work / "01_import.log")
        return source, pristine

    def _texture_overlay(self, asset: Asset, work: pathlib.Path) -> tuple[pathlib.Path, dict]:
        overlay, report = prepare_texture_overlay(
            asset=asset, resolver=self.ctx.resolver, root=self.root, work=work
        )
        if asset.textures:
            self.ctx.certifications.add(
                asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="TEXTURE_PREPARE", layer="AUTOMATIC", result="PASS" if report["ready"] else "FAIL",
                source_sha256=sha256_file(self.ctx.resolver.resolve(asset.primary_path)),
                metadata={"report": str(work / "texture_overlay_report.json"), "overlay": str(overlay)},
            )
        return overlay, report

    def _prepare_rigid_blend(
        self, asset: Asset, lod: str, work: pathlib.Path, client_root: pathlib.Path, *,
        model_info: str | None = None, require_unambiguous: bool = False,
        preselected: tuple[str, dict, dict] | None = None,
    ) -> tuple[pathlib.Path, pathlib.Path, str, dict]:
        src = self.ctx.resolver.resolve(asset.primary_path)
        if not asset.rigid_binding_ready:
            raise RuntimeError(f"asset cannot use rigid Blender importer without unambiguous skeleton binding: binding={asset.binding_mode}")
        if preselected is None:
            actual_lod, cfg, _coverage = self._preflight_rigid_import(
                asset, lod, model_info=model_info, require_unambiguous=require_unambiguous
            )
        else:
            actual_lod, cfg, _coverage = preselected
        inx = self.ctx.resolver.resolve(cfg["inx"])
        skeleton_logical = str(cfg.get("motion_smb") or asset.binding_skeleton_smb or "").replace("\\", "/")
        if not skeleton_logical:
            raise RuntimeError("selected rigid model-info has no skeleton SMB")
        smb = self.ctx.resolver.resolve(skeleton_logical)
        pristine = work / "pristine_import.blend"
        cmd = self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"), "--",
            "--smd", str(src), "--skeleton", str(smb), "--model-info", str(inx),
            "--lod", actual_lod, "--client-root", str(client_root),
            "--out", str(pristine), "--no-pack",
        ]
        if (_coverage or {}).get("selection_mode") == "SINGLE_TIER_FULL_CONTAINER":
            cmd.append("--single-tier-full-container")
        run_logged(cmd, work / "01_import.log")
        return src, pristine, actual_lod, cfg

    def _prepare_static_blend(self, asset: Asset, work: pathlib.Path, client_root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str]:
        src = self.ctx.resolver.resolve(asset.primary_path)
        pristine = work / "pristine_import.blend"
        cmd = self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1",
            "--python", str(self.root / "pt_smd_blender_import_v4_generic.py"), "--",
            "--smd", str(src), "--client-root", str(client_root),
            "--out", str(pristine), "--no-pack",
        ]
        run_logged(cmd, work / "01_import.log")
        return src, pristine, "default"

    def blender_import_workspace(
        self, asset: Asset, lod: str = "auto", reset: bool = False, model_info: str | None = None,
        selection_basis: dict | None = None, skeleton: str | None = None,
        motion: str = "STAND", load_actions: str = "all", fps: int = 30,
    ) -> dict:
        """Prepare a reusable Blender workspace for a supported asset.

        This is an import/edit workspace only.  It never writes the source client
        and it does not imply that a generic writer exists for the asset.  Existing
        workspaces are reused by default so reopening an asset cannot silently
        overwrite artist edits; ``reset=True`` rebuilds the workspace explicitly.
        """
        workspace = blender_edit_root(self.root, "generic_import", asset.primary_path)
        blend = workspace / "imported.blend"
        summary = workspace / "import_summary.json"

        load_actions = str(load_actions or "all").strip().lower()
        if load_actions not in {"all", "selected", "none"}:
            raise ValueError("load_actions must be all/selected/none for generic import")
        motion = str(motion or "STAND").strip() or "STAND"

        def _materialize_authoring_texture_overlay(overlay_root: pathlib.Path) -> dict:
            """Replace read-only overlay symlinks with pt_build-owned files.

            Blender continues using the same paths, but Save can now persist paint
            without ever following a symlink into the real client.
            """
            copied = 0
            regular = 0
            failed = []
            if not overlay_root.is_dir():
                return {"status":"SKIP","copied_symlinks":0,"regular_files":0,"failures":[]}
            for p in sorted(overlay_root.rglob("*")):
                try:
                    if p.is_symlink():
                        target = p.resolve(strict=True)
                        data_src = target
                        p.unlink()
                        shutil.copy2(data_src, p)
                        copied += 1
                    elif p.is_file():
                        regular += 1
                except Exception as exc:
                    failed.append({"path":str(p),"error":f"{type(exc).__name__}:{exc}"})
            if failed:
                raise RuntimeError(f"authoring texture overlay materialization failed: {failed[:8]}")
            return {
                "status":"PASS",
                "copied_symlinks":copied,
                "regular_files":regular,
                "failures":[],
                "client_modified":False,
            }

        def attach_rigid_actions_to_workspace() -> dict:
            """Build a separate animation preview from the stable paint blend.

            The paint/edit blend never receives Actions or PT_AFF helper bones.
            The animation preview references the same pt_build texture overlay.
            """
            if load_actions == "none":
                return {
                    "status":"SKIP","reason":"LOAD_ACTIONS_NONE","load_actions":"none",
                    "actions_loaded":[],"selected_action":None,
                    "preview_blend":None,"paint_supported":True,
                }
            if asset.visual_mode != "RIGID" or not asset.animation_binding_ready:
                return {
                    "status":"SKIP","reason":"ANIMATION_BINDING_NOT_READY","load_actions":load_actions,
                    "actions_loaded":[],"selected_action":None,
                    "preview_blend":None,"paint_supported":True,
                }

            cfg = next((x for x in asset.configs if x.get("motion_smb")), asset.configs[0])
            motion_inx = cfg.get("motion_inx") or (
                cfg.get("inx")
                if asset.binding_source not in {
                    "STRUCTURAL_GATE_UNIQUE","SKELETON_SIGNATURE_UNIQUE",
                    "GATE_FIRST_SKELETON_UNIQUE","PHYSIQUE_SUBSET_EQUIVALENT",
                } else ""
            )
            if not motion_inx:
                raise RuntimeError("authoring animation preview cannot resolve a unique root motion INX")
            inx = pathlib.Path(self.ctx.resolver.resolve(motion_inx))
            smb = pathlib.Path(self.ctx.resolver.resolve(cfg["motion_smb"]))
            payload_mode = "all" if load_actions == "all" else "selected"
            payload = build_bake_payload(
                self.root, inx, smb, selector=motion, load_actions=payload_mode, fps=fps
            )
            payload_path = workspace / "animation_preview_payload.json"
            write_payload(payload_path, payload)

            preview_blend = workspace / "animation_preview.blend"
            state_path = workspace / "animation_preview_state.json"
            source_sha = sha256_file(pathlib.Path(self.ctx.resolver.resolve(asset.primary_path)))
            inx_sha = sha256_file(inx)
            smb_sha = sha256_file(smb)
            paint_blend_sha = sha256_file(blend)
            desired = [x["name"] for x in payload["actions"]]

            try:
                old_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
            except Exception:
                old_state = {}

            preview_exists = preview_blend.is_file()
            preview_current_sha = sha256_file(preview_blend) if preview_exists else None
            preview_recorded_sha = old_state.get("preview_blend_sha256")
            preview_user_modified = bool(
                preview_exists and preview_recorded_sha and preview_current_sha != preview_recorded_sha
            )
            base_changed = old_state.get("paint_blend_sha256") not in {None, paint_blend_sha}

            exact_reuse = (
                old_state.get("format") == "PT_RIGID_ANIMATION_PREVIEW_STATE_V2"
                and old_state.get("asset_id") == asset.asset_id
                and old_state.get("source_sha256") == source_sha
                and old_state.get("inx_sha256") == inx_sha
                and old_state.get("smb_sha256") == smb_sha
                and old_state.get("load_actions") == load_actions
                and set(old_state.get("actions_loaded") or []) == set(desired)
                and not base_changed
                and preview_exists
            )

            if exact_reuse:
                run_logged(
                    self.ctx.settings.blender_command() + [
                        "--background", str(preview_blend), "--python-exit-code", "1",
                        "--python", str(self.root / "pt_asset_tool/blender/select_animation_action.py"), "--",
                        "--action", str(payload["selected_action"]), "--out", str(preview_blend),
                    ],
                    workspace / "animation_preview_select_action.log",
                )
                new_sha = sha256_file(preview_blend)
                old_state["selected_action"] = payload["selected_action"]
                old_state["preview_blend_sha256"] = new_sha
                old_state["preview_user_modified_before_select"] = preview_user_modified
                state_path.write_text(json.dumps(old_state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                return {
                    "status":"PASS","reused":True,"load_actions":load_actions,
                    "actions_loaded":desired,"selected_action":payload["selected_action"],
                    "preview_blend":str(preview_blend),"paint_blend":str(blend),
                    "shared_texture_overlay":str(workspace / "texture_overlay_client"),
                    "paint_supported_in_preview":False,
                    "paint_supported_in_authoring":True,
                    "live_guard":False,
                }

            if preview_user_modified and base_changed:
                raise RuntimeError(
                    "ANIMATION_PREVIEW_HAS_USER_EDITS_AND_PAINT_BASE_CHANGED: "
                    "preview rebuild would overwrite animation edits; preserve/export the preview first"
                )

            tmp_blend = workspace / "animation_preview.tmp.blend"
            report = workspace / "animation_preview_bake_report.json"
            run_logged(
                self.ctx.settings.blender_command() + [
                    "--background", str(blend), "--python-exit-code", "1",
                    "--python", str(self.root / "pt_asset_tool/blender/bake_actions.py"), "--",
                    "--payload", str(payload_path), "--out", str(tmp_blend), "--report", str(report),
                ],
                workspace / "animation_preview_bake.log",
            )
            os.replace(tmp_blend, preview_blend)
            run_logged(
                self.ctx.settings.blender_command() + [
                    "--background", str(preview_blend), "--python-exit-code", "1",
                    "--python", str(self.root / "pt_asset_tool/blender/prepare_animation_workspace.py"), "--",
                    "--out", str(preview_blend), "--action", str(payload["selected_action"]),
                ],
                workspace / "animation_preview_prepare.log",
            )
            preview_sha = sha256_file(preview_blend)
            state = {
                "format":"PT_RIGID_ANIMATION_PREVIEW_STATE_V2",
                "asset_id":asset.asset_id,"asset":asset.primary_path,
                "source_sha256":source_sha,
                "inx":str(inx),"inx_sha256":inx_sha,
                "smb":str(smb),"smb_sha256":smb_sha,
                "load_actions":load_actions,
                "actions_loaded":desired,
                "selected_action":payload["selected_action"],
                "paint_blend":str(blend),
                "paint_blend_sha256":paint_blend_sha,
                "preview_blend":str(preview_blend),
                "preview_blend_sha256":preview_sha,
                "shared_texture_overlay":str(workspace / "texture_overlay_client"),
                "paint_supported_in_preview":False,
                "paint_supported_in_authoring":True,
                "live_guard":False,
                "client_modified":False,
            }
            state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            return {
                "status":"PASS","reused":False,"load_actions":load_actions,
                "actions_loaded":desired,"selected_action":payload["selected_action"],
                "preview_blend":str(preview_blend),"paint_blend":str(blend),
                "shared_texture_overlay":state["shared_texture_overlay"],
                "paint_supported_in_preview":False,
                "paint_supported_in_authoring":True,
                "live_guard":False,
            }

        # RC6.18.5 migration: RC6.18.4 placed Actions/helper bones directly
        # into imported.blend.  Preserve that combined file, then rebuild a clean
        # paint blend.  Never silently delete the legacy file.
        split_migration = False
        legacy_state_path = workspace / "animation_authoring_state.json"
        if blend.is_file() and legacy_state_path.is_file():
            try:
                legacy_state = json.loads(legacy_state_path.read_text(encoding="utf-8"))
            except Exception:
                legacy_state = {}
            if legacy_state.get("format") == "PT_RIGID_AUTHORING_ANIMATION_STATE_V1":
                legacy_blend = workspace / "legacy_combined_animation_workspace_rc6_18_4.blend"
                if not legacy_blend.exists():
                    shutil.copy2(blend, legacy_blend)
                legacy_state_copy = workspace / "animation_authoring_state.rc6_18_4_legacy.json"
                if not legacy_state_copy.exists():
                    shutil.copy2(legacy_state_path, legacy_state_copy)
                overlay_now = workspace / "texture_overlay_client"
                overlay_backup = workspace / "texture_overlay_client.rc6_18_4_backup"
                if overlay_now.is_dir() and not overlay_backup.exists():
                    shutil.copytree(overlay_now, overlay_backup, symlinks=False)
                blend.unlink()
                legacy_state_path.unlink()
                split_migration = True
                print(
                    "authoring_split_migration=PASS "
                    f"legacy_blend={legacy_blend} clean_paint_rebuild=true"
                )

        # A reset is destructive to the existing artist workspace.  Resolve and
        # validate the requested rigid context before deleting anything so an
        # unsupported INX/LOD choice cannot erase a previously valid workspace.
        rigid_preflight = None
        standalone_preflight = None
        explicit_skeleton_lod_preflight = None
        is_rigid = asset.kind == "SMD_MODEL_062" and asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE"
        is_mixed = asset.kind == "SMD_MODEL_062" and asset.family == "SMD_MODEL_062_MIXED_PHYSIQUE"
        if (is_rigid or is_mixed) and (reset or not blend.is_file()):
            if skeleton and model_info:
                explicit_skeleton_lod_preflight = self._preflight_explicit_skeleton_lod_import(
                    asset, lod, model_info=model_info, skeleton_logical=skeleton, require_unambiguous=True
                )
            elif skeleton:
                standalone_preflight = self._preflight_standalone_rigid_import(asset, skeleton)
            elif is_mixed:
                raise RuntimeError("mixed-Physique generic import requires explicit --skeleton until a real authoritative binding is available")
            else:
                rigid_preflight = self._preflight_rigid_import(
                    asset, lod, model_info=model_info, require_unambiguous=True
                )

        if reset and workspace.exists():
            shutil.rmtree(workspace)

        if blend.is_file() and not reset:
            info = write_workspace_info(
                workspace, workflow="generic_import", logical=asset.primary_path,
                extra={
                    "family": asset.family, "kind": asset.kind,
                    "reused_existing": True, "build_supported": False,
                },
            )
            manifest = workspace / "authoring_manifest.json"
            provenance = verify_workspace_manifest(manifest) if manifest.is_file() else {
                "format": "PT_ASSET_AUTHORING_WORKSPACE_VERIFY_V1",
                "status": "UNKNOWN",
                "errors": ["LEGACY_WORKSPACE_PROVENANCE_MISSING"],
                "build_authorized": False,
                "client_write_authorized": False,
                "client_modified": False,
            }
            if asset.family in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
                if provenance.get("status") != "PASS":
                    raise RuntimeError(
                        "EXISTING_RIGID_WORKSPACE_CONTEXT_UNVERIFIED: reimport with --reset before reuse"
                    )
                existing_context = dict(provenance.get("selected_context") or {})
                existing_model_info = str((existing_context.get("model_info_inx") or {}).get("logical") or "").replace("\\", "/").strip("/")
                existing_lod = str(existing_context.get("lod") or "")
                if model_info:
                    requested_model_info = str(model_info).replace("\\", "/").strip("/")
                    if requested_model_info.casefold() != existing_model_info.casefold():
                        raise RuntimeError(
                            "EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH: requested --model-info differs from the saved workspace; reimport with --reset"
                        )
                if skeleton:
                    requested_skeleton = str(skeleton).replace("\\", "/").strip("/")
                    existing_skeleton = str((existing_context.get("skeleton_smb") or {}).get("logical") or "").replace("\\", "/").strip("/")
                    if requested_skeleton.casefold() != existing_skeleton.casefold():
                        raise RuntimeError(
                            "EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH: requested --skeleton differs from the saved workspace; reimport with --reset"
                        )
                if lod != "auto" and existing_lod != "standalone" and str(lod) != existing_lod:
                    raise RuntimeError(
                        "EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH: requested --lod differs from the saved workspace; reimport with --reset"
                    )
                if selection_basis is not None:
                    existing_basis = existing_context.get("selection_basis")
                    if dict(existing_basis or {}) != dict(selection_basis):
                        raise RuntimeError(
                            "EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH: requested profile/selection basis differs from the saved workspace; reimport with --reset"
                        )
            animation_authoring = attach_rigid_actions_to_workspace()
            result = {
                "format": "PT_GENERIC_BLENDER_IMPORT_V1", "status": "READY",
                "asset": asset.primary_path, "family": asset.family, "kind": asset.kind,
                "workspace": str(workspace), "blend": str(blend),
                "workspace_info": str(info), "authoring_manifest": str(manifest) if manifest.is_file() else None,
                "workspace_provenance": provenance, "selected_context": provenance.get("selected_context"),
                "animation_authoring": animation_authoring,
                "split_workspace": True,
                "paint_blend": str(blend),
                "animation_blend": animation_authoring.get("preview_blend"),
                "reused_existing": True,
                "build_supported": False, "client_modified": False,
            }
            summary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return result

        workspace.mkdir(parents=True, exist_ok=True)
        selected_context = None
        if asset.kind == "SMD_STAGE_072":
            preview = self.stage072_preview(asset)
            source_blend = pathlib.Path(preview["preview_blend"]).resolve()
            shutil.copy2(source_blend, blend)
            actual_lod = "stage"
            mode = "STAGE072"
            source = self.ctx.resolver.resolve(asset.primary_path)
            import_meta = {"source_preview_blend": str(source_blend)}
        elif asset.kind == "SMD_MODEL_062" and asset.family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
            # Structural validation is the gate for generic Model0.62 import.
            overlay_root, texture_report = self._texture_overlay(asset, workspace)
            texture_authoring_materialization = _materialize_authoring_texture_overlay(overlay_root)
            if asset.family in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
                if skeleton and model_info:
                    if explicit_skeleton_lod_preflight is None:
                        explicit_skeleton_lod_preflight = self._preflight_explicit_skeleton_lod_import(
                            asset, lod, model_info=model_info, skeleton_logical=skeleton, require_unambiguous=True
                        )
                    source, prepared = self._prepare_explicit_skeleton_lod_blend(
                        asset, workspace, overlay_root, explicit_skeleton_lod_preflight
                    )
                    actual_lod = explicit_skeleton_lod_preflight["lod"]
                    selected_cfg = explicit_skeleton_lod_preflight["cfg"]
                    mode = "RIGID_EXPLICIT_SKELETON_LOD"
                elif skeleton:
                    if standalone_preflight is None:
                        standalone_preflight = self._preflight_standalone_rigid_import(asset, skeleton)
                    source, prepared = self._prepare_standalone_rigid_blend(asset, workspace, overlay_root, standalone_preflight)
                    actual_lod = "standalone"
                    selected_cfg = None
                    mode = "MIXED" if asset.family == "SMD_MODEL_062_MIXED_PHYSIQUE" else "RIGID_STANDALONE"
                else:
                    self.structural(asset)
                    if not asset.rigid_binding_ready:
                        raise RuntimeError(
                            "generic Blender import requires a resolved rigid skeleton binding or explicit --skeleton context; "
                            f"binding={asset.binding_mode}/{asset.binding_source}"
                        )
                    source, prepared, actual_lod, selected_cfg = self._prepare_rigid_blend(
                        asset, lod, workspace, overlay_root, model_info=model_info, require_unambiguous=True,
                        preselected=rigid_preflight,
                    )
                    mode = "RIGID"
            else:
                self.structural(asset)
                source, prepared, actual_lod = self._prepare_static_blend(asset, workspace, overlay_root)
                mode = "STATIC"
            if pathlib.Path(prepared).resolve() != blend.resolve():
                shutil.move(str(prepared), str(blend))
            import_meta = {
                "texture_overlay": str(overlay_root),
                "texture_ready": bool(texture_report.get("ready", True)),
                "texture_authoring_materialization": texture_authoring_materialization,
                "texture_overlay_writable": True,
            }
            if mode in {"RIGID", "RIGID_EXPLICIT_SKELETON_LOD"}:
                model_info_logical = str(selected_cfg.get("inx") or "").replace("\\", "/")
                skeleton_logical = (str(explicit_skeleton_lod_preflight.get("skeleton_logical") or "")
                                    if mode == "RIGID_EXPLICIT_SKELETON_LOD" else
                                    str(selected_cfg.get("motion_smb") or asset.binding_skeleton_smb or "")).replace("\\", "/")
                model_info_path = pathlib.Path(self.ctx.resolver.resolve(model_info_logical)).resolve()
                skeleton_path = pathlib.Path(self.ctx.resolver.resolve(skeleton_logical)).resolve()
                context_basis = selection_basis
                if mode == "RIGID_EXPLICIT_SKELETON_LOD" and context_basis is None:
                    context_basis = {
                        "kind": "EXPLICIT_SKELETON_LOD",
                        "roundtrip_target": asset.primary_path,
                        "structural_gate": "PASS",
                    }
                effective_coverage = effective_lod_node_coverage(asset, selected_cfg, actual_lod)
                selected_context = build_selected_authoring_context(
                    model_info_logical=model_info_logical, model_info_path=model_info_path,
                    skeleton_logical=skeleton_logical, skeleton_path=skeleton_path,
                    lod=actual_lod, lod_groups=selected_cfg.get("lod_groups") or {},
                    selected_lod_nodes=list(effective_coverage.get("effective_selected_nodes") or []),
                    lod_selection_mode=str(effective_coverage.get("selection_mode") or "MODEL_GROUP_KEYS"),
                    selection_basis=context_basis,
                )
                import_meta["model_info_inx"] = model_info_logical
                import_meta["skeleton_smb"] = skeleton_logical
                import_meta["selected_context"] = selected_context
                import_meta["lod_node_coverage"] = effective_coverage
                import_meta["explicit_skeleton_lod_context"] = mode == "RIGID_EXPLICIT_SKELETON_LOD"
            elif mode in {"RIGID_STANDALONE", "MIXED"}:
                structural_basis = {
                    "kind": "EXPLICIT_SKELETON",
                    "roundtrip_target": asset.primary_path,
                    "structural_gate": "PASS",
                }
                selected_context = build_standalone_rigid_authoring_context(
                    asset_logical=asset.primary_path, source_path=pathlib.Path(source),
                    skeleton_logical=standalone_preflight["skeleton_logical"],
                    skeleton_path=pathlib.Path(standalone_preflight["skeleton"]),
                    selected_nodes=list(standalone_preflight["selected_nodes"]),
                    structural_gate_report=pathlib.Path(standalone_preflight["structural_report"]),
                    selection_basis=structural_basis,
                )
                import_meta["skeleton_smb"] = standalone_preflight["skeleton_logical"]
                import_meta["selected_context"] = selected_context
                import_meta["structural_gate"] = "PASS"
        else:
            raise RuntimeError(
                "generic Blender import is not certified for "
                f"family={asset.family} kind={asset.kind}; use a specialized workflow if available"
            )

        info = write_workspace_info(
            workspace, workflow="generic_import", logical=asset.primary_path,
            extra={
                "family": asset.family, "kind": asset.kind, "mode": mode,
                "lod": actual_lod, "source": str(source), "reused_existing": False,
                "build_supported": False, **import_meta,
            },
        )
        deps = []
        for cfg in asset.configs:
            rel = cfg.get("motion_inx") or cfg.get("inx")
            if rel:
                try: deps.append(self.ctx.resolver.resolve(rel))
                except Exception: pass
            rel = cfg.get("motion_smb")
            if rel:
                try: deps.append(self.ctx.resolver.resolve(rel))
                except Exception: pass
        if asset.binding_skeleton_smb:
            try: deps.append(self.ctx.resolver.resolve(asset.binding_skeleton_smb))
            except Exception: pass
        if model_info:
            try: deps.append(self.ctx.resolver.resolve(model_info))
            except Exception: pass
        if skeleton:
            try: deps.append(self.ctx.resolver.resolve(skeleton))
            except Exception: pass
        plan = authoring_plan(asset, pathlib.Path(source))
        manifest = write_workspace_manifest(
            workspace, asset, pathlib.Path(source), plan, deps, selected_context=selected_context
        )
        provenance = verify_workspace_manifest(manifest)
        animation_authoring = attach_rigid_actions_to_workspace()
        result = {
            "format": "PT_GENERIC_BLENDER_IMPORT_V1", "status": "READY",
            "asset": asset.primary_path, "family": asset.family, "kind": asset.kind,
            "mode": mode, "lod": actual_lod, "workspace": str(workspace),
            "blend": str(blend), "workspace_info": str(info),
            "authoring_manifest": str(manifest), "workspace_provenance": provenance,
            "selected_context": selected_context,
            "animation_authoring": animation_authoring,
            "split_workspace": True,
            "paint_blend": str(blend),
            "animation_blend": animation_authoring.get("preview_blend"),
            "split_migration": split_migration,
            "authoring_plan": plan, "reused_existing": False, "build_supported": False,
            "client_modified": False,
        }
        summary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    @staticmethod
    def _ask(label: str) -> str:
        while True:
            ans = input(f"{label} [y]es / [n]o / [s]kip: ").strip().lower()
            if ans in {"y", "yes"}: return "PASS"
            if ans in {"n", "no"}: return "FAIL"
            if ans in {"s", "skip", ""}: return "SKIP"

    @staticmethod
    def _overall(geometry: str, texture: str, has_textures: bool) -> str:
        relevant = [geometry] + ([texture] if has_textures else [])
        if "FAIL" in relevant:
            return "FAIL"
        if relevant and all(x == "PASS" for x in relevant):
            return "PASS"
        return "SKIP"

    def visual_geometry(self, asset: Asset, lod: str = "auto", non_interactive_result: str | None = None) -> dict:
        mode = asset.visual_mode
        if not mode:
            raise RuntimeError(f"visual geometry gate not wired for family/binding: {asset.family}/{asset.binding_mode}")
        work = self._asset_workdir(asset, "VISUAL_GEOMETRY")
        work.mkdir(parents=True, exist_ok=True)

        self.structural(asset)
        overlay_root, texture_report = self._texture_overlay(asset, work)
        if mode == "RIGID":
            src, pristine, actual_lod, _cfg = self._prepare_rigid_blend(asset, lod, work, overlay_root)
        else:
            src, pristine, actual_lod = self._prepare_static_blend(asset, work, overlay_root)

        witness = work / "visual_geometry_witness.blend"
        witness_report = work / "witness.json"
        cmd = self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/blender/witness_geometry.py"), "--",
            "--out", str(witness), "--report", str(witness_report),
        ]
        run_logged(cmd, work / "02_witness.log")

        if non_interactive_result is None:
            gui_cmd = self.ctx.settings.blender_command() + [str(witness)]
            gui_log = work / "03_blender_gui.log"
            proc = subprocess.run(gui_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            geometry_result = self._ask("Geometria/witness visualmente correto?")
            texture_result = self._ask("Texturas e materiais carregaram corretamente?") if asset.textures else "SKIP"
        else:
            geometry_result = non_interactive_result.upper()
            if geometry_result not in {"PASS", "FAIL", "SKIP"}:
                raise ValueError("non_interactive_result must be PASS/FAIL/SKIP")
            texture_result = geometry_result if asset.textures else "SKIP"

        source_sha = sha256_file(src)
        artifact_sha = sha256_file(witness)
        common_meta = {
            "witness": str(witness), "pristine_blend": str(pristine), "lod": actual_lod, "mode": mode,
            "texture_overlay_report": str(work / "texture_overlay_report.json"),
            "binding_mode": asset.binding_mode, "binding_source": asset.binding_source,
            "binding_root_models": asset.binding_root_models,
        }
        geom_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="VISUAL_GEOMETRY", layer="HUMAN_VISUAL", result=geometry_result,
            source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta,
        )
        tex_cert = None
        if asset.textures:
            tex_cert = self.ctx.certifications.add(
                asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="VISUAL_TEXTURE_MATERIAL", layer="HUMAN_VISUAL", result=texture_result,
                source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta,
            )
        overall = self._overall(geometry_result, texture_result, bool(asset.textures))
        overall_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="VISUAL_ASSET", layer="HUMAN_VISUAL", result=overall,
            source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta,
        )
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "mode": mode, "requested_lod": lod, "lod": actual_lod,
            "witness": str(witness), "source_sha256": source_sha, "artifact_sha256": artifact_sha,
            "geometry_visual": geometry_result, "texture_material_visual": texture_result,
            "visual_asset": overall, "texture_prepare": "PASS" if texture_report["ready"] else "FAIL",
            "texture_usage_semantics": texture_report.get("usage_semantics"),
            "texture_required_count": texture_report.get("required_texture_count"),
            "texture_historical_unused_count": texture_report.get("historical_unused_texture_count"),
            "texture_prepare_warning_count": texture_report.get("historical_unused_failures", 0),
            "certification_id": overall_cert["certification_id"], "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def stage072_preview(self, asset: Asset) -> dict:
        if asset.kind != "SMD_STAGE_072":
            raise RuntimeError(f"Stage0.72 preview requires SMD_STAGE_072, got {asset.kind}")
        work = self._asset_workdir(asset, "STAGE072_PREVIEW")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)
        parsed = parse_stage072(src)
        if parsed.get("full_parse") != "PASS":
            raise RuntimeError("Stage0.72 source did not pass physical parser")

        overlay_root, texture_report = prepare_stage072_texture_overlay(
            asset=asset, parsed=parsed, resolver=self.ctx.resolver, root=self.root, work=work
        )
        texture_policy = classify_stage072_texture_transport_failures(texture_report)
        missing_client = list(texture_policy.get("missing_client_references") or [])
        invalid_serialized = list(texture_policy.get("invalid_serialized_references") or [])
        incomplete_texture_refs = list(texture_policy.get("incomplete_references") or [])
        hard_texture_failures = list(texture_policy.get("hard_preparation_failures") or [])
        if hard_texture_failures:
            raise RuntimeError(
                "Stage0.72 texture preparation hard-failed for existing client files: "
                f"failures={len(hard_texture_failures)}"
            )

        blend = work / "stage072_preview.blend"
        import_report = work / "stage072_import.json"
        import_script = self.root / "pt_asset_tool/blender/import_stage072.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1",
            "--python", str(import_script), "--",
            "--smd", str(src), "--client-root", str(overlay_root),
            "--out", str(blend), "--report", str(import_report),
        ], work / "01_stage072_import.log")
        imported = json.loads(import_report.read_text(encoding="utf-8"))
        if imported.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 Blender importer failed: {imported}")
        # Missing images already proven absent from the client are allowed only
        # as source-faithful degraded preview. Any other Blender image load
        # error is a tool failure and remains fail-closed.
        unexpected_load_failures = []
        for row in imported.get("texture_load_failures") or []:
            bad = [x for x in (row.get("status") or []) if x not in {"LOADED", "NO_TEXTURE", "MISSING"}]
            if bad:
                unexpected_load_failures.append({"material": row.get("material"), "status": bad})
        if unexpected_load_failures:
            raise RuntimeError(
                "Stage0.72 Blender texture load failed for prepared client files: "
                f"{unexpected_load_failures[:5]}"
            )

        transport_report = work / "stage072_transport_check.json"
        check_script = self.root / "pt_asset_tool/blender/check_stage072_transport.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(blend), "--python-exit-code", "1",
            "--python", str(check_script), "--",
            "--smd", str(src), "--report", str(transport_report),
        ], work / "02_stage072_transport_check.log")
        checked = json.loads(transport_report.read_text(encoding="utf-8"))
        if checked.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 persisted transport check failed: {checked}")

        artifact_sha = sha256_file(blend)
        meta = {
            "source_parse": "PASS",
            "max_texlink_depth": parsed.get("max_texlink_depth"),
            "area_encoding": (parsed.get("area") or {}).get("encoding"),
            "custom_vertex_color_vertices": parsed.get("custom_vertex_color_vertices"),
            "lights": (parsed.get("counts") or {}).get("lights"),
            "inert_zero_texture_texlink_faces": parsed.get("inert_zero_texture_texlink_faces"),
            "import_report": str(import_report),
            "transport_report": str(transport_report),
            "preview_blend": str(blend),
            "texture_overlay_report": str(work / "texture_overlay_report.json"),
            "texture_reference_presence": "INCOMPLETE_REFERENCE_SET" if incomplete_texture_refs else "PASS",
            "client_missing_texture_references": [str(x.get("logical") or "") for x in missing_client],
            "serialized_invalid_texture_references": [str(x.get("logical") or "") for x in invalid_serialized],
            "runtime_texture_aliases": dict(texture_report.get("runtime_path_aliases") or {}),
            "material_preview_complete": not bool(incomplete_texture_refs),
            "dynamic_form_preview": imported.get("dynamic_form_preview"),
            "light_preview": imported.get("light_preview"),
            "runtime_nonrendered_material_ids": imported.get("runtime_nonrendered_material_ids") or [],
            "runtime_nonrendered_faces": int(imported.get("runtime_nonrendered_faces") or 0),
        }
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STAGE072_BLENDER_TRANSPORT", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=meta,
        )
        print(f"STAGE072_PREVIEW source={asset.primary_path}")
        print(
            f"GEOMETRY vertices={checked.get('vertices')} faces={checked.get('faces')} "
            f"loops={checked.get('loops')}"
        )
        print(
            "PERSISTED_TRANSPORT=PASS "
            f"position_max_error={float(checked.get('max_position_abs_error') or 0):.9g} "
            f"uv_max_error={float(checked.get('max_uv_abs_error') or 0):.9g} "
            f"color_max_error={float(checked.get('max_color_abs_error') or 0):.9g}"
        )
        print(
            f"TEXLINK max_depth={parsed.get('max_texlink_depth')} "
            f"uv_layers={imported.get('uv_layers')}"
        )
        print(
            f"LIGHTS metadata={checked.get('light_metadata_count')} "
            "preview=METADATA_ONLY_NOT_RUNTIME_LIGHTING"
        )
        print(
            f"PREVIEW_VISIBILITY runtime_nonrendered_faces={int(imported.get('runtime_nonrendered_faces') or 0)} "
            f"inert_zero_texlink_faces={int(parsed.get('inert_zero_texture_texlink_faces') or 0)} "
            "policy=KEEP_IN_MESH_HIDE_AS_RUNTIME_NONRENDERED"
        )
        print(
            f"TEXTURES presence={'INCOMPLETE_REFERENCE_SET' if incomplete_texture_refs else 'PASS'} "
            f"missing_client={len(missing_client)} "
            f"serialized_invalid={len(invalid_serialized)} "
            f"runtime_aliases={int(texture_report.get('runtime_path_alias_count') or 0)} "
            f"material_preview_complete={str(not bool(incomplete_texture_refs)).lower()}"
        )
        if missing_client:
            print(
                "CLIENT_MISSING_TEXTURES=" + ",".join(
                    str(x.get("logical") or "") for x in missing_client
                )
            )
        if invalid_serialized:
            print(
                "SERIALIZED_INVALID_TEXTURES=" + ",".join(
                    str(x.get("logical") or "") for x in invalid_serialized
                )
            )
        if texture_report.get("runtime_path_aliases"):
            print("RUNTIME_TEXTURE_ALIASES=" + json.dumps(texture_report.get("runtime_path_aliases"), ensure_ascii=False))
        print(
            f"MATERIAL_FRAME0 exact={imported.get('combiner_exact_frame0_material_count')} "
            f"approximate={imported.get('combiner_approximate_frame0_material_count')} "
            f"texture_load_failures={imported.get('texture_load_failure_count')}"
        )

        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "source_sha256": source_sha, "artifact_sha256": artifact_sha,
            "source_parse": "PASS", "stage072_blender_transport": "PASS",
            "vertices": checked.get("vertices"), "faces": checked.get("faces"), "loops": checked.get("loops"),
            "max_texlink_depth": parsed.get("max_texlink_depth"),
            "uv_layers": imported.get("uv_layers"),
            "position_max_abs_error": checked.get("max_position_abs_error"),
            "uv_max_abs_error": checked.get("max_uv_abs_error"),
            "color_max_abs_error": checked.get("max_color_abs_error"),
            "custom_vertex_color_vertices": parsed.get("custom_vertex_color_vertices"),
            "lights": checked.get("light_metadata_count"),
            "area_encoding": (parsed.get("area") or {}).get("encoding"),
            "opaque_trailing_bytes": (parsed.get("area") or {}).get("opaque_trailing_bytes"),
            "inert_zero_texture_texlink_faces": parsed.get("inert_zero_texture_texlink_faces"),
            "combiner_exact_frame0_material_count": imported.get("combiner_exact_frame0_material_count"),
            "combiner_approximate_frame0_material_count": imported.get("combiner_approximate_frame0_material_count"),
            "texture_prepare": "PARTIAL_REFERENCE_INCOMPLETE" if incomplete_texture_refs else "PASS",
            "texture_reference_presence": "INCOMPLETE_REFERENCE_SET" if incomplete_texture_refs else "PASS",
            "client_missing_texture_reference_count": len(missing_client),
            "client_missing_texture_references": [str(x.get("logical") or "") for x in missing_client],
            "serialized_invalid_texture_reference_count": len(invalid_serialized),
            "serialized_invalid_texture_references": [str(x.get("logical") or "") for x in invalid_serialized],
            "runtime_texture_alias_count": int(texture_report.get("runtime_path_alias_count") or 0),
            "runtime_texture_aliases": dict(texture_report.get("runtime_path_aliases") or {}),
            "material_preview_complete": not bool(incomplete_texture_refs),
            "texture_load_failure_count": imported.get("texture_load_failure_count"),
            "dynamic_form_preview": imported.get("dynamic_form_preview"),
            "light_preview": imported.get("light_preview"),
            "runtime_nonrendered_material_ids": imported.get("runtime_nonrendered_material_ids") or [],
            "runtime_nonrendered_faces": int(imported.get("runtime_nonrendered_faces") or 0),
            "preview_blend": str(blend),
            "certification_id": cert["certification_id"],
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def stage072_uv_roundtrip(self, asset: Asset, uv_delta: float = 0.03125) -> dict:
        if asset.kind != "SMD_STAGE_072":
            raise RuntimeError(f"Stage0.72 UV roundtrip requires SMD_STAGE_072, got {asset.kind}")
        if not (1e-5 <= abs(float(uv_delta)) <= 0.25):
            raise ValueError("uv_delta magnitude must be between 1e-5 and 0.25")
        work = self._asset_workdir(asset, "STAGE072_UV_ROUNDTRIP")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)
        parsed = parse_stage072(src, include_payload=True)
        if parsed.get("full_parse") != "PASS":
            raise RuntimeError("Stage0.72 source did not pass physical parser")
        renderable_faces = 0
        mats = {int(m["id"]): m for m in parsed.get("materials") or []}
        for f in (parsed.get("payload") or {}).get("faces") or []:
            chain = f.get("texlink_chain") or []
            m = mats.get(int(f.get("material") or 0))
            if chain and m is not None and int(m.get("TextureCounter") or 0) >= len(chain):
                renderable_faces += 1
        if renderable_faces < 1:
            raise RuntimeError("Stage0.72 UV roundtrip requires at least one renderable TexLink face")

        overlay_root, texture_report = prepare_stage072_texture_overlay(
            asset=asset, parsed=parsed, resolver=self.ctx.resolver, root=self.root, work=work
        )
        texture_policy = classify_stage072_texture_transport_failures(texture_report)
        hard_texture_failures = list(texture_policy.get("hard_preparation_failures") or [])
        if hard_texture_failures:
            raise RuntimeError(
                "Stage0.72 texture preparation hard-failed for existing client files: "
                f"failures={len(hard_texture_failures)}"
            )

        pristine = work / "stage072_pristine.blend"
        import_report = work / "stage072_pristine_import.json"
        import_script = self.root / "pt_asset_tool/blender/import_stage072.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(import_script), "--",
            "--smd", str(src), "--client-root", str(overlay_root),
            "--out", str(pristine), "--report", str(import_report),
        ], work / "01_pristine_import.log")
        imported = json.loads(import_report.read_text(encoding="utf-8"))
        if imported.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 pristine importer failed: {imported}")
        unexpected = []
        for row in imported.get("texture_load_failures") or []:
            bad = [x for x in (row.get("status") or []) if x not in {"LOADED", "NO_TEXTURE", "MISSING"}]
            if bad:
                unexpected.append({"material": row.get("material"), "status": bad})
        if unexpected:
            raise RuntimeError(f"Stage0.72 pristine Blender texture load failed: {unexpected[:5]}")

        pristine_check = work / "stage072_pristine_transport.json"
        check_script = self.root / "pt_asset_tool/blender/check_stage072_transport.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--smd", str(src), "--report", str(pristine_check),
        ], work / "02_pristine_transport.log")
        checked0 = json.loads(pristine_check.read_text(encoding="utf-8"))
        if checked0.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 pristine transport failed: {checked0}")

        edited = work / "stage072_uv_witness.blend"
        witness_report = work / "stage072_uv_witness.json"
        witness_script = self.root / "pt_asset_tool/blender/witness_stage072_uv.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1", "--python", str(witness_script), "--",
            "--smd", str(src), "--out", str(edited), "--report", str(witness_report),
            "--delta-u", str(float(uv_delta)),
        ], work / "03_uv_witness.log")
        witness = json.loads(witness_report.read_text(encoding="utf-8"))
        if witness.get("check") != "PASS" or not witness.get("uv_edits"):
            raise RuntimeError(f"Stage0.72 UV witness failed: {witness}")

        rebuilt = work / "rebuilt_stage072_uv_roundtrip.smd"
        writer_report = work / "stage072_uv_writer.json"
        writer_script = self.root / "pt_asset_tool/blender/write_stage072_uv.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(edited), "--python-exit-code", "1", "--python", str(writer_script), "--",
            "--smd", str(src), "--witness", str(witness_report),
            "--out", str(rebuilt), "--report", str(writer_report),
            "--expected-source-sha256", source_sha,
        ], work / "04_uv_writer.log")
        writer_meta = json.loads(writer_report.read_text(encoding="utf-8"))
        if writer_meta.get("check") != "PASS" or writer_meta.get("strict_blender_edit_set") != "PASS":
            raise RuntimeError(f"Stage0.72 strict UV writer failed: {writer_meta}")

        compare_report = work / "stage072_uv_roundtrip_compare.json"
        comparison = compare_stage072_uv_roundtrip(src, rebuilt, witness_report, report_path=compare_report)

        rebuilt_blend = work / "rebuilt_stage072_preview.blend"
        rebuilt_import_report = work / "rebuilt_stage072_import.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(import_script), "--",
            "--smd", str(rebuilt), "--client-root", str(overlay_root),
            "--out", str(rebuilt_blend), "--report", str(rebuilt_import_report),
        ], work / "05_rebuilt_import.log")
        rebuilt_imported = json.loads(rebuilt_import_report.read_text(encoding="utf-8"))
        if rebuilt_imported.get("check") != "PASS":
            raise RuntimeError(f"rebuilt Stage0.72 importer failed: {rebuilt_imported}")

        rebuilt_check = work / "rebuilt_stage072_transport.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--smd", str(rebuilt), "--report", str(rebuilt_check),
        ], work / "06_rebuilt_transport.log")
        checked1 = json.loads(rebuilt_check.read_text(encoding="utf-8"))
        if checked1.get("check") != "PASS":
            raise RuntimeError(f"rebuilt Stage0.72 transport failed: {checked1}")

        rebuilt_parsed = parse_stage072(rebuilt)
        if rebuilt_parsed.get("full_parse") != "PASS":
            raise RuntimeError("rebuilt Stage0.72 physical parser failed")
        edit = (witness.get("uv_edits") or [{}])[0]
        meta = {
            "witness": edit, "uv_delta": float(uv_delta),
            "writer_report": str(writer_report), "compare_report": str(compare_report),
            "rebuilt_smd": str(rebuilt), "rebuilt_blend": str(rebuilt_blend),
            "max_texlink_depth": parsed.get("max_texlink_depth"),
            "area_encoding": (parsed.get("area") or {}).get("encoding"),
            "opaque_trailing_bytes": (parsed.get("area") or {}).get("opaque_trailing_bytes"),
            "geometry_edit_policy": "CURRENT_EXACT_NORMAL_FAMILY_AVAILABLE_V066_LEGACY_DEFERRED",
            "stage_area_and_suffix_byte_identical": comparison.get("stage_area_and_suffix_byte_identical"),
            "htexture_nexttex_byte_identical": comparison.get("htexture_nexttex_byte_identical"),
            "non_witness_bytes_byte_identical": comparison.get("non_witness_bytes_byte_identical"),
        }
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STAGE072_UV_ROUNDTRIP", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, artifact_sha256=sha256_file(rebuilt), metadata=meta,
        )
        print(f"STAGE072_UV_ROUNDTRIP source={asset.primary_path}")
        print(
            "WITNESS "
            f"face={edit.get('face_index')} stage={edit.get('stage_index')} corner={edit.get('corner')} "
            f"component={edit.get('component')} before={edit.get('before')} after={edit.get('after')}"
        )
        print(
            "ROUNDTRIP=PASS "
            f"area={comparison.get('area_encoding')} depth={comparison.get('max_texlink_depth')} "
            f"StageArea_suffix_exact={comparison.get('stage_area_and_suffix_byte_identical')} "
            f"hTexture_NextTex_exact={comparison.get('htexture_nexttex_byte_identical')} "
            f"non_witness_bytes_exact={comparison.get('non_witness_bytes_byte_identical')}"
        )
        print(
            "REIMPORT_TRANSPORT=PASS "
            f"uv_max_error={float(checked1.get('max_uv_abs_error') or 0):.9g} "
            f"lights={checked1.get('light_metadata_count')}"
        )
        print("GEOMETRY_WRITE=AVAILABLE_CURRENT_EXACT_FAMILY_V066 legacy_maps=17_deferred")
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "source_sha256": source_sha, "rebuilt_sha256": sha256_file(rebuilt),
            "rebuilt_smd": str(rebuilt), "rebuilt_preview": str(rebuilt_blend),
            "intentional_edit": f"TEXLINK_STAGE{edit.get('stage_index')}_UV_U",
            "uv_delta": float(uv_delta), "witness_edit": edit,
            "source_parse": parsed.get("full_parse"), "rebuilt_parse": rebuilt_parsed.get("full_parse"),
            "max_texlink_depth": parsed.get("max_texlink_depth"),
            "area_encoding": comparison.get("area_encoding"),
            "opaque_trailing_bytes": comparison.get("opaque_trailing_bytes"),
            "stage_header_byte_identical": comparison.get("stage_header_byte_identical"),
            "materials_byte_identical": comparison.get("materials_byte_identical"),
            "geometry_byte_identical": comparison.get("geometry_byte_identical"),
            "faces_byte_identical": comparison.get("faces_byte_identical"),
            "lights_byte_identical": comparison.get("lights_byte_identical"),
            "stage_area_and_suffix_byte_identical": comparison.get("stage_area_and_suffix_byte_identical"),
            "opaque_trailing_byte_identical": comparison.get("opaque_trailing_byte_identical"),
            "htexture_nexttex_byte_identical": comparison.get("htexture_nexttex_byte_identical"),
            "non_witness_bytes_byte_identical": comparison.get("non_witness_bytes_byte_identical"),
            "diff_byte_count": comparison.get("diff_byte_count"),
            "rebuilt_transport_check": checked1.get("check"),
            "rebuilt_uv_max_abs_error": checked1.get("max_uv_abs_error"),
            "geometry_write": "AVAILABLE_CURRENT_EXACT_FAMILY_V066_LEGACY_DEFERRED",
            "stage072_uv_roundtrip": "PASS",
            "certification_id": cert["certification_id"], "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def stage072_geometry_roundtrip(self, asset: Asset, delta_world: float = 64.0) -> dict:
        if asset.kind != "SMD_STAGE_072":
            raise RuntimeError(f"Stage0.72 geometry roundtrip requires SMD_STAGE_072, got {asset.kind}")
        if not (1.0 <= abs(float(delta_world)) <= 256.0):
            raise ValueError("delta_world magnitude must be between 1 and 256")
        work = self._asset_workdir(asset, "STAGE072_GEOMETRY_ROUNDTRIP_PROVENANCE_V2")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)
        parsed = parse_stage072(src, include_payload=True)
        if parsed.get("full_parse") != "PASS":
            raise RuntimeError("Stage0.72 source did not pass physical parser")
        normal_audit = analyze_stage072_normals(src)
        if normal_audit.get("check") != "PASS" or normal_audit.get("classification") not in STAGE072_SUPPORTED_GEOMETRY_NORMAL_MODELS:
            raise RuntimeError(
                "Stage0.72 geometry roundtrip V2 refuses unproven normal provenance; "
                f"got {normal_audit.get('classification')}"
            )
        witness_plan = select_stage072_geometry_witness(src, delta_world=float(delta_world))
        plan_path = work / "geometry_witness_plan.json"
        plan_path.write_text(json.dumps(witness_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        overlay_root, texture_report = prepare_stage072_texture_overlay(
            asset=asset, parsed=parsed, resolver=self.ctx.resolver, root=self.root, work=work
        )
        texture_policy = classify_stage072_texture_transport_failures(texture_report)
        hard_texture_failures = list(texture_policy.get("hard_preparation_failures") or [])
        if hard_texture_failures:
            raise RuntimeError(
                "Stage0.72 texture preparation hard-failed for existing client files: "
                f"failures={len(hard_texture_failures)}"
            )

        pristine = work / "stage072_pristine.blend"
        import_report = work / "stage072_pristine_import.json"
        import_script = self.root / "pt_asset_tool/blender/import_stage072.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(import_script), "--",
            "--smd", str(src), "--client-root", str(overlay_root),
            "--out", str(pristine), "--report", str(import_report),
        ], work / "01_pristine_import.log")
        imported = json.loads(import_report.read_text(encoding="utf-8"))
        if imported.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 pristine importer failed: {imported}")

        pristine_check = work / "stage072_pristine_transport.json"
        check_script = self.root / "pt_asset_tool/blender/check_stage072_transport.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--smd", str(src), "--report", str(pristine_check),
        ], work / "02_pristine_transport.log")
        checked0 = json.loads(pristine_check.read_text(encoding="utf-8"))
        if checked0.get("check") != "PASS":
            raise RuntimeError(f"Stage0.72 pristine transport failed: {checked0}")

        edited = work / "stage072_geometry_witness.blend"
        witness_report = work / "stage072_geometry_witness.json"
        witness_script = self.root / "pt_asset_tool/blender/witness_stage072_geometry.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1", "--python", str(witness_script), "--",
            "--smd", str(src), "--out", str(edited), "--report", str(witness_report),
            "--vertex-index", str(int(witness_plan["vertex_index"])),
            "--delta-x-world", str(float(witness_plan["delta_world"])),
        ], work / "03_geometry_witness.log")
        witness = json.loads(witness_report.read_text(encoding="utf-8"))
        if witness.get("check") != "PASS" or len(witness.get("geometry_edits") or []) != 1:
            raise RuntimeError(f"Stage0.72 geometry witness failed: {witness}")
        edit = witness["geometry_edits"][0]
        if int(edit.get("vertex_index")) != int(witness_plan["vertex_index"]):
            raise RuntimeError("Stage0.72 geometry witness selected a different vertex than the proven plan")

        rebuilt = work / "rebuilt_stage072_geometry_roundtrip.smd"
        writer_report = work / "stage072_geometry_writer.json"
        writer_script = self.root / "pt_asset_tool/blender/write_stage072_geometry.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(edited), "--python-exit-code", "1", "--python", str(writer_script), "--",
            "--smd", str(src), "--witness", str(witness_report),
            "--out", str(rebuilt), "--report", str(writer_report),
            "--expected-source-sha256", source_sha,
        ], work / "04_geometry_writer.log")
        writer_meta = json.loads(writer_report.read_text(encoding="utf-8"))
        if writer_meta.get("check") != "PASS" or writer_meta.get("strict_blender_edit_set") != "PASS":
            raise RuntimeError(f"Stage0.72 strict geometry writer failed: {writer_meta}")

        compare_report = work / "stage072_geometry_roundtrip_compare.json"
        comparison = compare_stage072_geometry_roundtrip(src, rebuilt, witness_report, report_path=compare_report)

        rebuilt_blend = work / "rebuilt_stage072_geometry_preview.blend"
        rebuilt_import_report = work / "rebuilt_stage072_geometry_import.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(import_script), "--",
            "--smd", str(rebuilt), "--client-root", str(overlay_root),
            "--out", str(rebuilt_blend), "--report", str(rebuilt_import_report),
        ], work / "05_rebuilt_import.log")
        rebuilt_imported = json.loads(rebuilt_import_report.read_text(encoding="utf-8"))
        if rebuilt_imported.get("check") != "PASS":
            raise RuntimeError(f"rebuilt Stage0.72 geometry importer failed: {rebuilt_imported}")

        rebuilt_check = work / "rebuilt_stage072_geometry_transport.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(rebuilt_blend), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--smd", str(rebuilt), "--report", str(rebuilt_check),
        ], work / "06_rebuilt_transport.log")
        checked1 = json.loads(rebuilt_check.read_text(encoding="utf-8"))
        if checked1.get("check") != "PASS":
            raise RuntimeError(f"rebuilt Stage0.72 geometry transport failed: {checked1}")

        meta = {
            "witness": edit, "witness_plan": witness_plan, "delta_world": float(delta_world),
            "writer_report": str(writer_report), "compare_report": str(compare_report),
            "rebuilt_smd": str(rebuilt), "rebuilt_blend": str(rebuilt_blend),
            "source_normal_family": normal_audit.get("classification"),
            "changed_face_normal_model": STAGE072_CURRENT_NORMAL_MODEL,
            "stagearea_changed": comparison.get("stagearea_changed"),
            "source_area_encoding": comparison.get("source_area_encoding"),
            "vectnormal3_byte_identical": comparison.get("vectnormal3_byte_identical"),
            "untouched_face_normal4_byte_identical": comparison.get("untouched_face_normal4_byte_identical"),
            "changed_face_current_setnormal_exact": comparison.get("changed_face_current_setnormal_exact"),
            "opaque_trailing_byte_identical": comparison.get("opaque_trailing_byte_identical"),
            "texlinks_byte_identical": comparison.get("texlinks_byte_identical"),
            "lights_byte_identical": comparison.get("lights_byte_identical"),
        }
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STAGE072_GEOMETRY_ROUNDTRIP_PROVENANCE_V2", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, artifact_sha256=sha256_file(rebuilt), metadata=meta,
        )
        stagearea_out = comparison.get("stagearea_output") or {}
        print(f"STAGE072_GEOMETRY_ROUNDTRIP source={asset.primary_path}")
        print(
            "WITNESS "
            f"vertex={edit.get('vertex_index')} delta_world={edit.get('delta_world')} "
            f"incident_faces={edit.get('incident_face_count')}"
        )
        print(
            "ROUNDTRIP=PASS "
            f"source_normal_family={normal_audit.get('classification')} "
            f"changed_faces=CURRENT_SOURCE_SETNORMAL area={comparison.get('source_area_encoding')} "
            f"stagearea_changed={comparison.get('stagearea_changed')} "
            f"vectnormal3_exact={comparison.get('vectnormal3_byte_identical')} "
            f"untouched_normals_exact={comparison.get('untouched_face_normal4_byte_identical')} "
            f"texlinks_exact={comparison.get('texlinks_byte_identical')} lights_exact={comparison.get('lights_byte_identical')} "
            f"opaque_exact={comparison.get('opaque_trailing_byte_identical')}"
        )
        print(
            "STAGEAREA_REBUILD=PASS "
            f"active_cells={((stagearea_out.get('counts') or {}).get('active_area_cells'))} "
            f"wAreaSize={((stagearea_out.get('counts') or {}).get('wAreaSize_rebuilt'))} "
            f"max_span={stagearea_out.get('max_face_area_cell_span')}/4096"
        )
        print(
            "REIMPORT_TRANSPORT=PASS "
            f"position_max_error={float(checked1.get('max_position_abs_error') or 0):.9g} "
            f"uv_max_error={float(checked1.get('max_uv_abs_error') or 0):.9g} "
            f"lights={checked1.get('light_metadata_count')}"
        )
        if normal_audit.get("classification") == STAGE072_CURRENT_NORMAL_MODEL:
            print("NORMAL_PROVENANCE=CURRENT_EXACT_WHOLE_FILE")
        else:
            print("NORMAL_PROVENANCE=LEGACY_UNTOUCHED_BYTES_PLUS_CURRENT_SETNORMAL_CHANGED_FACES")
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "source_sha256": source_sha, "rebuilt_sha256": sha256_file(rebuilt),
            "rebuilt_smd": str(rebuilt), "rebuilt_preview": str(rebuilt_blend),
            "witness_edit": edit, "witness_plan": witness_plan,
            "source_normal_family": normal_audit.get("classification"),
            "changed_face_normal_model": STAGE072_CURRENT_NORMAL_MODEL,
            "source_area_encoding": comparison.get("source_area_encoding"),
            "stagearea_changed": comparison.get("stagearea_changed"),
            "stagearea_output_check": stagearea_out.get("check"),
            "vectnormal3_byte_identical": comparison.get("vectnormal3_byte_identical"),
            "untouched_face_normal4_byte_identical": comparison.get("untouched_face_normal4_byte_identical"),
            "changed_face_current_setnormal_exact": comparison.get("changed_face_current_setnormal_exact"),
            "opaque_trailing_byte_identical": comparison.get("opaque_trailing_byte_identical"),
            "texlinks_byte_identical": comparison.get("texlinks_byte_identical"),
            "lights_byte_identical": comparison.get("lights_byte_identical"),
            "rebuilt_transport_check": checked1.get("check"),
            "rebuilt_position_max_abs_error": checked1.get("max_position_abs_error"),
            "rebuilt_uv_max_abs_error": checked1.get("max_uv_abs_error"),
            "stage072_geometry_roundtrip": "PASS",
            "certification_id": cert["certification_id"], "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    # Compatibility alias retained for callers from V0.6.6.
    def stage072_geometry_roundtrip_current(self, asset: Asset, delta_world: float = 64.0) -> dict:
        return self.stage072_geometry_roundtrip(asset, delta_world=delta_world)

    def multilayer_texlink(self, asset: Asset, lod: str = "auto", non_interactive_result: str | None = None) -> dict:
        if asset.kind != "SMD_MODEL_062":
            raise RuntimeError(f"multilayer TexLink requires Model0.62, got {asset.kind}")
        work = self._asset_workdir(asset, "MULTILAYER_TEXLINK")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)
        parsed = parse_multilayer_semantics(src)
        compact = compact_semantics(parsed)
        source_report = work / "multilayer_source.json"
        source_report.write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if parsed.get("source_semantics") != "PASS":
            raise RuntimeError("multilayer TexLink source semantics failed")
        if int(parsed.get("max_layers") or 0) != 2:
            raise RuntimeError(f"multilayer TexLink visual validation applies only to a source with exactly 2 layers; got max_layers={parsed.get('max_layers')}. Use `asset texlinks <asset>` for generic TexLink inspection.")
        if int(parsed.get("multilayer_faces") or 0) < 1:
            raise RuntimeError("asset has no multilayer TexLink faces")
        mixed_depth = [
            m for m in (parsed.get("multilayer_materials") or [])
            if len(m.get("chain_depth_histogram") or {}) > 1
        ]
        if mixed_depth:
            raise RuntimeError(
                "multilayer preview V1 refuses material ids with mixed 1/2-stage face depth: "
                + ",".join(str(m.get("material_id")) for m in mixed_depth)
            )

        auto_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="MULTILAYER_TEXLINK_SOURCE_SEMANTICS", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, metadata={
                "report": str(source_report),
                "max_layers": parsed.get("max_layers"),
                "multilayer_faces": parsed.get("multilayer_faces"),
                "profile_counts": parsed.get("profile_counts"),
                "htexture_slot_mapping": parsed.get("htexture_slot_mapping"),
            },
        )

        overlay_root, texture_report = self._texture_overlay(asset, work)
        standalone_preflight = None
        if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            if asset.rigid_binding_ready:
                src2, pristine, actual_lod, _cfg = self._prepare_rigid_blend(asset, lod, work, overlay_root)
                mode = "RIGID"
            else:
                # Fail-closed fallback for physical MAP/EFFECT rigid assets whose
                # exact sibling SMB is present but no usable INX binding exists.
                # The filename is only a hypothesis: the structural gate below
                # must prove the skeleton before Blender imports or writes anything.
                sibling = str(pathlib.PurePosixPath(asset.primary_path).with_suffix(".smb"))
                if self.ctx.resolver.resolve(sibling, required=False) is None:
                    raise RuntimeError(
                        f"asset cannot use rigid Blender importer without unambiguous skeleton binding: binding={asset.binding_mode}; "
                        "no exact sibling SMB exists for structural standalone proof"
                    )
                standalone_preflight = self._preflight_standalone_rigid_import(asset, sibling)
                src2, pristine = self._prepare_standalone_rigid_blend(asset, work, overlay_root, standalone_preflight)
                actual_lod = "standalone"
                mode = "RIGID_STANDALONE"
        elif asset.family == "SMD_MODEL_062_STATIC":
            src2, pristine, actual_lod = self._prepare_static_blend(asset, work, overlay_root)
            mode = "STATIC"
        else:
            raise RuntimeError(f"multilayer Blender preview not wired for family {asset.family}")
        if pathlib.Path(src2).resolve() != pathlib.Path(src).resolve():
            raise RuntimeError("multilayer preview imported an unexpected source")

        preview = work / "multilayer_preview.blend"
        preview_report = work / "multilayer_preview.json"
        script = self.root / "pt_asset_tool/blender/apply_multilayer_texlink.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(script), "--",
            "--smd", str(src), "--client-root", str(overlay_root),
            "--out", str(preview), "--report", str(preview_report),
        ], work / "02_multilayer_preview.log")
        post = json.loads(preview_report.read_text(encoding="utf-8"))
        if (
            post.get("check") != "PASS"
            or post.get("htexture_slot_mapping") != "SMATERIAL_SM_TEXTURE_SLOT_EXACT"
            or post.get("uv_assignment_check") != "PASS"
            or int(post.get("uv_assignment_mismatch_count") or 0) != 0
            or int(post.get("uv_assignment_depth_mismatch_count") or 0) != 0
        ):
            raise RuntimeError(f"multilayer Blender postprocess failed semantics/UV transport: {post}")

        print(f"MULTILAYER_TEXLINK source={asset.primary_path} mode={mode} lod={actual_lod}")
        print(f"LAYERS=2 multilayer_faces={parsed['multilayer_faces']} uv_distinct_faces={parsed['uv_distinct_multilayer_faces']}")
        print(f"PROFILES={parsed['profile_counts']}")
        print("UV layers PT_TEXLINK_STAGE_0 / PT_TEXLINK_STAGE_1 foram preservados separadamente.")
        print(
            "UV_ASSIGNMENT=PASS "
            f"loops={post.get('uv_assignment_checked_loops')} "
            f"max_error={float(post.get('uv_assignment_max_abs_error') or 0.0):.9g}; "
            "a ordem face/canto foi verificada automaticamente contra o SMD."
        )
        profiles = parsed.get("profile_counts") or {}
        if "REFLEX_ADD" in profiles:
            print("REFLEX_ADD: o stage 1 usa coordenada Reflection no preview; sobreposição no UV Editor não é evidência de UV embaralhado.")
        if "SECOND_UV_LIGHTMAP_MODULATE" in profiles:
            print("LIGHTMAP: o stage 1 possui UV próprio; ilhas sobrepostas/visualmente densas no UV Editor podem ser normais.")
        if int(parsed.get("uv_distinct_multilayer_faces") or 0) == 0:
            print("UV_SERIALIZED: stage 0 e stage 1 não diferem nas faces multilayer deste asset.")
        print("Materiais com FS_SCROLL* são mostrados no frame-base; o movimento do UV dinâmico não é certificado neste gate.")

        if non_interactive_result is None:
            gui_log = work / "03_blender_gui.log"
            proc = subprocess.run(self.ctx.settings.blender_command() + [str(preview)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            layer_result = self._ask("No MODELO renderizado, o efeito da segunda camada (reflexo/lightmap/overlay) aparece nas superfícies corretas, sem artefatos visuais evidentes?")
            texture_result = self._ask("Texturas e materiais do preview multilayer carregaram corretamente?") if asset.textures else "SKIP"
        else:
            layer_result = non_interactive_result.upper()
            if layer_result not in {"PASS", "FAIL", "SKIP"}:
                raise ValueError("non_interactive_result must be PASS/FAIL/SKIP")
            texture_result = layer_result if asset.textures else "SKIP"

        overall = self._overall(layer_result, texture_result, bool(asset.textures))
        meta = {
            "source_report": str(source_report),
            "preview_report": str(preview_report),
            "preview_blend": str(preview),
            "automatic_certification_id": auto_cert["certification_id"],
            "mode": mode, "lod": actual_lod,
            "profile_counts": parsed.get("profile_counts"),
            "multilayer_faces": parsed.get("multilayer_faces"),
            "uv_distinct_multilayer_faces": parsed.get("uv_distinct_multilayer_faces"),
            "htexture_slot_mapping": parsed.get("htexture_slot_mapping"),
            "dynamic_form_preview": post.get("dynamic_form_preview"),
            "uv_assignment_check": post.get("uv_assignment_check"),
            "uv_assignment_checked_loops": post.get("uv_assignment_checked_loops"),
            "uv_assignment_mismatch_count": post.get("uv_assignment_mismatch_count"),
            "uv_assignment_depth_mismatch_count": post.get("uv_assignment_depth_mismatch_count"),
            "uv_assignment_max_abs_error": post.get("uv_assignment_max_abs_error"),
        }
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="VISUAL_MULTILAYER_TEXLINK", layer="HUMAN_VISUAL", result=overall,
            source_sha256=source_sha, artifact_sha256=sha256_file(preview), metadata=meta,
        )
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "mode": mode, "requested_lod": lod, "lod": actual_lod,
            "max_layers": parsed.get("max_layers"),
            "multilayer_faces": parsed.get("multilayer_faces"),
            "singlelayer_faces": parsed.get("singlelayer_faces"),
            "uv_distinct_multilayer_faces": parsed.get("uv_distinct_multilayer_faces"),
            "profile_counts": parsed.get("profile_counts"),
            "htexture_slot_mapping": parsed.get("htexture_slot_mapping"),
            "uv_layers": post.get("uv_layers"),
            "uv_assignment_check": post.get("uv_assignment_check"),
            "uv_assignment_checked_loops": post.get("uv_assignment_checked_loops"),
            "uv_assignment_mismatch_count": post.get("uv_assignment_mismatch_count"),
            "uv_assignment_depth_mismatch_count": post.get("uv_assignment_depth_mismatch_count"),
            "uv_assignment_max_abs_error": post.get("uv_assignment_max_abs_error"),
            "dynamic_form_preview": post.get("dynamic_form_preview"),
            "combiner_exact_material_count": post.get("combiner_exact_material_count"),
            "combiner_approximate_material_count": post.get("combiner_approximate_material_count"),
            "multilayer_visual": layer_result,
            "texture_material_visual": texture_result,
            "visual_multilayer_asset": overall,
            "texture_prepare": "PASS" if texture_report["ready"] else "FAIL",
            "preview_blend": str(preview),
            "source_sha256": source_sha, "artifact_sha256": sha256_file(preview),
            "certification_id": cert["certification_id"],
            "automatic_certification_id": auto_cert["certification_id"],
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def multilayer_texlink_roundtrip(self, asset: Asset, lod: str = "auto", uv_delta: float = 0.03125) -> dict:
        if asset.kind != "SMD_MODEL_062":
            raise RuntimeError(f"multilayer TexLink roundtrip requires Model0.62, got {asset.kind}")
        if not (1e-5 <= abs(float(uv_delta)) <= 0.25):
            raise ValueError("uv_delta magnitude must be between 1e-5 and 0.25")
        work = self._asset_workdir(asset, "MULTILAYER_TEXLINK_ROUNDTRIP")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)
        parsed = parse_multilayer_semantics(src)
        if parsed.get("source_semantics") != "PASS":
            raise RuntimeError("multilayer TexLink source semantics failed")
        if int(parsed.get("max_layers") or 0) != 2 or int(parsed.get("multilayer_faces") or 0) < 1:
            raise RuntimeError("TexLink roundtrip is a specialized writer gate for a source-proven two-stage asset. This asset is not eligible; use `asset texlinks <asset>` to inspect its ordinary material/TexLink structure.")

        overlay_root, texture_report = self._texture_overlay(asset, work)
        standalone_preflight = None
        if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            if asset.rigid_binding_ready:
                src2, pristine, actual_lod, _cfg = self._prepare_rigid_blend(asset, lod, work, overlay_root)
                mode = "RIGID"
            else:
                # Fail-closed fallback for physical MAP/EFFECT rigid assets whose
                # exact sibling SMB is present but no usable INX binding exists.
                # The filename is only a hypothesis: the structural gate below
                # must prove the skeleton before Blender imports or writes anything.
                sibling = str(pathlib.PurePosixPath(asset.primary_path).with_suffix(".smb"))
                if self.ctx.resolver.resolve(sibling, required=False) is None:
                    raise RuntimeError(
                        f"asset cannot use rigid Blender importer without unambiguous skeleton binding: binding={asset.binding_mode}; "
                        "no exact sibling SMB exists for structural standalone proof"
                    )
                standalone_preflight = self._preflight_standalone_rigid_import(asset, sibling)
                src2, pristine = self._prepare_standalone_rigid_blend(asset, work, overlay_root, standalone_preflight)
                actual_lod = "standalone"
                mode = "RIGID_STANDALONE"
        elif asset.family == "SMD_MODEL_062_STATIC":
            src2, pristine, actual_lod = self._prepare_static_blend(asset, work, overlay_root)
            mode = "STATIC"
        else:
            raise RuntimeError(f"TexLink roundtrip not wired for family {asset.family}")
        if pathlib.Path(src2).resolve() != pathlib.Path(src).resolve():
            raise RuntimeError("TexLink roundtrip imported an unexpected source")

        preview = work / "multilayer_pristine.blend"
        preview_report = work / "multilayer_pristine.json"
        apply_script = self.root / "pt_asset_tool/blender/apply_multilayer_texlink.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(apply_script), "--",
            "--smd", str(src), "--client-root", str(overlay_root),
            "--out", str(preview), "--report", str(preview_report),
        ], work / "02_multilayer_pristine.log")
        preview_meta = json.loads(preview_report.read_text(encoding="utf-8"))
        if preview_meta.get("check") != "PASS" or preview_meta.get("uv_assignment_check") != "PASS":
            raise RuntimeError(f"pristine multilayer preview did not pass: {preview_meta}")

        edited = work / "multilayer_uv_witness.blend"
        witness_report = work / "texlink_uv_witness.json"
        witness_script = self.root / "pt_asset_tool/blender/witness_multilayer_texlink.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(preview), "--python-exit-code", "1",
            "--python", str(witness_script), "--",
            "--smd", str(src), "--out", str(edited), "--report", str(witness_report),
            "--delta-u", str(float(uv_delta)),
        ], work / "03_texlink_witness.log")
        witness = json.loads(witness_report.read_text(encoding="utf-8"))
        if witness.get("check") != "PASS" or not witness.get("edits"):
            raise RuntimeError(f"TexLink UV witness did not pass: {witness}")

        rebuilt = work / "rebuilt_texlink_roundtrip.smd"
        writer_report = work / "texlink_writer.json"
        writer_script = self.root / "pt_asset_tool/blender/write_multilayer_texlink.py"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(edited), "--python-exit-code", "1",
            "--python", str(writer_script), "--",
            "--smd", str(src), "--witness", str(witness_report),
            "--out", str(rebuilt), "--report", str(writer_report),
            "--expected-source-sha256", source_sha,
        ], work / "04_texlink_writer.log")
        writer_meta = json.loads(writer_report.read_text(encoding="utf-8"))
        if writer_meta.get("check") != "PASS" or writer_meta.get("strict_blender_edit_set") != "PASS":
            raise RuntimeError(f"strict TexLink writer did not pass: {writer_meta}")

        compare_report = work / "texlink_roundtrip_compare.json"
        comparison = compare_texlink_roundtrip(src, rebuilt, witness_report, report_path=compare_report)

        # Reimport the rebuilt SMD with the same family/LOD path, then run the
        # automatic source->Blender UV transport gate again on the rebuilt bytes.
        rebuilt_import = work / "rebuilt_import.blend"
        if mode == "RIGID":
            actual_lod2, cfg = self._select_rigid_lod(asset, actual_lod)
            if actual_lod2 != actual_lod:
                raise RuntimeError("rebuilt rigid LOD selection drift")
            inx = self.ctx.resolver.resolve(cfg["inx"])
            smb = self.ctx.resolver.resolve(asset.binding_skeleton_smb)
            run_logged(self.ctx.settings.blender_command() + [
                "--background", "--python-exit-code", "1",
                "--python", str(self.root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"), "--",
                "--smd", str(rebuilt), "--skeleton", str(smb), "--model-info", str(inx),
                "--lod", actual_lod, "--client-root", str(overlay_root),
                "--out", str(rebuilt_import), "--no-pack",
            ], work / "05_rebuilt_import.log")
        elif mode == "RIGID_STANDALONE":
            if standalone_preflight is None:
                raise RuntimeError("standalone TexLink reimport lost structural skeleton context")
            run_logged(self.ctx.settings.blender_command() + [
                "--background", "--python-exit-code", "1",
                "--python", str(self.root / "pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"), "--",
                "--smd", str(rebuilt), "--skeleton", str(standalone_preflight["skeleton"]),
                "--client-root", str(overlay_root), "--out", str(rebuilt_import), "--no-pack",
            ], work / "05_rebuilt_import.log")
        else:
            run_logged(self.ctx.settings.blender_command() + [
                "--background", "--python-exit-code", "1",
                "--python", str(self.root / "pt_smd_blender_import_v4_generic.py"), "--",
                "--smd", str(rebuilt), "--client-root", str(overlay_root),
                "--out", str(rebuilt_import), "--no-pack",
            ], work / "05_rebuilt_import.log")

        rebuilt_preview = work / "rebuilt_multilayer_preview.blend"
        rebuilt_preview_report = work / "rebuilt_multilayer_preview.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(rebuilt_import), "--python-exit-code", "1",
            "--python", str(apply_script), "--",
            "--smd", str(rebuilt), "--client-root", str(overlay_root),
            "--out", str(rebuilt_preview), "--report", str(rebuilt_preview_report),
        ], work / "06_rebuilt_multilayer_preview.log")
        rebuilt_preview_meta = json.loads(rebuilt_preview_report.read_text(encoding="utf-8"))
        if (
            rebuilt_preview_meta.get("check") != "PASS"
            or rebuilt_preview_meta.get("uv_assignment_check") != "PASS"
            or int(rebuilt_preview_meta.get("uv_assignment_mismatch_count") or 0) != 0
            or int(rebuilt_preview_meta.get("uv_assignment_depth_mismatch_count") or 0) != 0
        ):
            raise RuntimeError(f"rebuilt multilayer reimport/UV gate failed: {rebuilt_preview_meta}")

        rebuilt_parsed = parse_multilayer_semantics(rebuilt)
        if rebuilt_parsed.get("source_semantics") != "PASS":
            raise RuntimeError("rebuilt source semantics failed after TexLink roundtrip")

        edit = (witness.get("edits") or [{}])[0]
        metadata = {
            "mode": mode, "lod": actual_lod,
            "source_report_semantics": parsed.get("source_semantics"),
            "witness_report": str(witness_report), "writer_report": str(writer_report),
            "compare_report": str(compare_report), "rebuilt_smd": str(rebuilt),
            "rebuilt_preview": str(rebuilt_preview), "rebuilt_preview_report": str(rebuilt_preview_report),
            "uv_delta": float(uv_delta), "witness_edit": edit,
            "texlink_structure_exact": comparison.get("texlink_structure_exact"),
            "htexture_nexttex_byte_identical": comparison.get("htexture_nexttex_byte_identical"),
            "non_witness_bytes_byte_identical": comparison.get("non_witness_bytes_byte_identical"),
            "rebuilt_uv_assignment_check": rebuilt_preview_meta.get("uv_assignment_check"),
            "texture_overlay_report": str(work / "texture_overlay_report.json"),
            "standalone_structural_skeleton": (
                str(standalone_preflight.get("skeleton_logical")) if standalone_preflight else None
            ),
            "standalone_structural_report": (
                str(standalone_preflight.get("structural_report")) if standalone_preflight else None
            ),
        }
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="MULTILAYER_TEXLINK_ROUNDTRIP", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, artifact_sha256=sha256_file(rebuilt), metadata=metadata,
        )
        print(f"MULTILAYER_TEXLINK_ROUNDTRIP source={asset.primary_path} mode={mode} lod={actual_lod}")
        print(
            "WITNESS "
            f"object={edit.get('object_name')} face={edit.get('face_index')} stage={edit.get('stage_index')} "
            f"corner={edit.get('corner')} component={edit.get('component')} "
            f"before={edit.get('before')} after={edit.get('after')}"
        )
        print(
            "ROUNDTRIP=PASS "
            f"structure_exact={comparison.get('texlink_structure_exact')} "
            f"hTexture_NextTex_byte_identical={comparison.get('htexture_nexttex_byte_identical')} "
            f"non_witness_bytes_byte_identical={comparison.get('non_witness_bytes_byte_identical')}"
        )
        print(
            "REIMPORT_UV=PASS "
            f"loops={rebuilt_preview_meta.get('uv_assignment_checked_loops')} "
            f"max_error={float(rebuilt_preview_meta.get('uv_assignment_max_abs_error') or 0.0):.9g}"
        )
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "mode": mode, "requested_lod": lod, "lod": actual_lod,
            "source_sha256": source_sha, "rebuilt_sha256": sha256_file(rebuilt),
            "rebuilt_smd": str(rebuilt), "rebuilt_preview": str(rebuilt_preview),
            "intentional_edit": "TEXLINK_STAGE1_UV_U", "uv_delta": float(uv_delta),
            "witness_edit": edit,
            "source_semantics": parsed.get("source_semantics"),
            "rebuilt_semantics": rebuilt_parsed.get("source_semantics"),
            "texlink_structure_exact": comparison.get("texlink_structure_exact"),
            "htexture_nexttex_byte_identical": comparison.get("htexture_nexttex_byte_identical"),
            "materials_exact": comparison.get("materials_exact"),
            "non_witness_bytes_byte_identical": comparison.get("non_witness_bytes_byte_identical"),
            "diff_byte_count": comparison.get("diff_byte_count"),
            "rebuilt_uv_assignment_check": rebuilt_preview_meta.get("uv_assignment_check"),
            "rebuilt_uv_assignment_mismatch_count": rebuilt_preview_meta.get("uv_assignment_mismatch_count"),
            "rebuilt_uv_assignment_depth_mismatch_count": rebuilt_preview_meta.get("uv_assignment_depth_mismatch_count"),
            "multilayer_texlink_roundtrip": "PASS",
            "texture_prepare": "PASS" if texture_report["ready"] else "FAIL",
            "certification_id": cert["certification_id"],
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def static_roundtrip(self, asset: Asset, witness_strength: float = 0.08, non_interactive_result: str | None = None) -> dict:
        if asset.family != "SMD_MODEL_062_STATIC":
            raise RuntimeError(f"static roundtrip requires SMD_MODEL_062_STATIC, got {asset.family}")
        if not (0.005 <= float(witness_strength) <= 0.25):
            raise ValueError("witness_strength must be between 0.005 and 0.25")
        work = self._asset_workdir(asset, "STATIC_ROUNDTRIP")
        work.mkdir(parents=True, exist_ok=True)

        structural = self.structural(asset)
        probe = structural.get("static_capability") or {}
        ready = list(probe.get("ready_objects") or [])
        blocked = list(probe.get("blocked_objects") or [])
        object_local_preservation = False
        if blocked:
            rows = list(probe.get("objects") or [])
            ol_rows = [r for r in rows if r.get("name") in blocked and r.get("blockers") and all(str(b).startswith("OBJECT_LOCAL_ANIMATION:") for b in r.get("blockers") or [])]
            if len(rows) == 1 and len(ol_rows) == 1 and not ready:
                target_object = str(ol_rows[0]["name"])
                object_local_preservation = True
            else:
                raise RuntimeError(f"static roundtrip V1 refuses blockers other than a single object-local-animation-only object: {blocked}")
        else:
            if len(ready) != 1:
                raise RuntimeError(f"static roundtrip V1 currently requires exactly one authoring-ready object; ready={ready}")
            target_object = ready[0]

        overlay_root, texture_report = self._texture_overlay(asset, work)
        src, pristine, actual_lod = self._prepare_static_blend(asset, work, overlay_root)
        source_sha = sha256_file(src)

        edited = work / "edited_authoring.blend"
        witness_report = work / "witness_edit.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/blender/witness_geometry.py"), "--",
            "--out", str(edited), "--report", str(witness_report),
            "--strength", str(float(witness_strength)),
        ], work / "02_edit_witness.log")

        witness = json.loads(witness_report.read_text(encoding="utf-8"))
        if str(witness.get("object") or "").lower() != target_object.lower():
            raise RuntimeError(f"witness edited unexpected object: expected={target_object} got={witness.get('object')}")

        # Certification writer: this gate intentionally edits vertex positions only.
        # Preserve every non-XYZ source byte exactly instead of routing the witness
        # through the broader free-mesh writer (whose normal/topology regeneration
        # belongs to a separate authoring capability).
        writer_script = self.root / "pt_asset_tool/blender/write_static_witness.py"
        if not writer_script.is_file():
            raise FileNotFoundError(f"static witness writer missing: {writer_script}")
        rebuilt = work / "rebuilt_roundtrip.smd"
        writer_report = work / "writer.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(edited), "--python-exit-code", "1",
            "--python", str(writer_script), "--",
            "--smd", str(src), "--object", target_object,
            "--witness", str(witness_report),
            "--out", str(rebuilt), "--report", str(writer_report),
            "--expected-source-sha256", source_sha,
        ], work / "03_static_writer.log")

        compare_report = work / "roundtrip_compare.json"
        comparison = compare_static_roundtrip(src, rebuilt, target_object, witness_report, compare_report)

        rebuilt_probe_path = work / "rebuilt_static_capability.json"
        run_logged([
            "python3", str(self.root / "pt_smd_static_capability_probe_v1.py"),
            "--smd", str(rebuilt), "--report", str(rebuilt_probe_path),
        ], work / "04_rebuilt_probe.log")
        rebuilt_probe = json.loads(rebuilt_probe_path.read_text(encoding="utf-8"))
        if rebuilt_probe.get("ready_objects") != ready or rebuilt_probe.get("blocked_objects") != blocked:
            raise RuntimeError(f"rebuilt capability drift: ready={rebuilt_probe.get('ready_objects')} blocked={rebuilt_probe.get('blocked_objects')}")
        if object_local_preservation:
            src_rows = probe.get("objects") or []
            out_rows = rebuilt_probe.get("objects") or []
            signature = lambda rows: [(r.get("name"), r.get("rot_keys"), r.get("pos_keys"), r.get("scale_keys"), tuple(r.get("blockers") or [])) for r in rows]
            if signature(src_rows) != signature(out_rows):
                raise RuntimeError(f"object-local capability metadata drift: source={signature(src_rows)} output={signature(out_rows)}")

        reimport = work / "rebuilt_reimport.blend"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", "--python-exit-code", "1",
            "--python", str(self.root / "pt_smd_blender_import_v4_generic.py"), "--",
            "--smd", str(rebuilt), "--client-root", str(overlay_root),
            "--out", str(reimport), "--no-pack",
        ], work / "05_reimport.log")

        automatic_meta = {
            "target_object": target_object, "pristine_blend": str(pristine), "edited_blend": str(edited),
            "rebuilt_smd": str(rebuilt), "rebuilt_reimport": str(reimport),
            "witness_report": str(witness_report), "writer_report": str(writer_report),
            "compare_report": str(compare_report), "rebuilt_probe": str(rebuilt_probe_path),
            "witness_strength": float(witness_strength),
            "changed_vertices": comparison.get("details", {}).get("actual_changed_vertices", []),
            "byte_identical": comparison.get("byte_identical"),
            "object_local_animation_preserved_byte_identical": comparison.get("details", {}).get("object_local_animation_preserved_byte_identical"),
            "texture_overlay_report": str(work / "texture_overlay_report.json"),
        }
        auto_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STATIC_ROUNDTRIP_STRUCTURAL", layer="AUTOMATIC", result="PASS",
            source_sha256=source_sha, artifact_sha256=sha256_file(rebuilt), metadata=automatic_meta,
        )

        print(f"STATIC_ROUNDTRIP source={asset.primary_path} object={target_object}")
        print(f"INTENTIONAL_EDIT vertices={automatic_meta['changed_vertices']} strength={float(witness_strength):.4f}")
        print("Blender abrirá o SMD reconstruído. A pequena deformação do witness deve continuar visível; qualquer outra corrupção é FAIL.")
        if non_interactive_result is None:
            gui_log = work / "06_blender_gui.log"
            proc = subprocess.run(self.ctx.settings.blender_command() + [str(reimport)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            geometry_result = self._ask("Rebuild preservou o objeto e somente o witness intencional está alterado?")
            texture_result = self._ask("Texturas e materiais do rebuild carregaram corretamente?") if asset.textures else "SKIP"
        else:
            geometry_result = non_interactive_result.upper()
            if geometry_result not in {"PASS","FAIL","SKIP"}:
                raise ValueError("non_interactive_result must be PASS/FAIL/SKIP")
            texture_result = geometry_result if asset.textures else "SKIP"

        overall = self._overall(geometry_result, texture_result, bool(asset.textures))
        human_meta = dict(automatic_meta)
        human_meta.update({"automatic_certification_id": auto_cert["certification_id"], "automatic_compare": "PASS", "rebuilt_capability": "PASS"})
        overall_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="STATIC_ROUNDTRIP", layer="HUMAN_VISUAL", result=overall,
            source_sha256=source_sha, artifact_sha256=sha256_file(rebuilt), metadata=human_meta,
        )
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "mode": "STATIC", "target_object": target_object,
            "source_sha256": source_sha, "rebuilt_sha256": sha256_file(rebuilt),
            "rebuilt_smd": str(rebuilt), "edited_blend": str(edited), "rebuilt_reimport": str(reimport),
            "intentional_edit": "GEOMETRY_VERTEX_RADIAL", "witness_strength": float(witness_strength),
            "changed_vertices": automatic_meta["changed_vertices"],
            "byte_identical": comparison.get("byte_identical"),
            "object_local_animation_preserved_byte_identical": comparison.get("details", {}).get("object_local_animation_preserved_byte_identical"),
            "face_uv_material_semantic_exact": comparison.get("details", {}).get("face_uv_material_semantic_exact"),
            "static_roundtrip_structural": "PASS", "rebuilt_capability": "PASS",
            "object_local_animation_preserved": "PASS" if object_local_preservation else "NOT_APPLICABLE",
            "geometry_visual": geometry_result, "texture_material_visual": texture_result,
            "static_roundtrip": overall, "texture_prepare": "PASS" if texture_report["ready"] else "FAIL",
            "texture_usage_semantics": texture_report.get("usage_semantics"),
            "texture_required_count": texture_report.get("required_texture_count"),
            "texture_historical_unused_count": texture_report.get("historical_unused_texture_count"),
            "texture_prepare_warning_count": texture_report.get("historical_unused_failures", 0),
            "certification_id": overall_cert["certification_id"], "automatic_certification_id": auto_cert["certification_id"],
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def object_local_animation(self, asset: Asset, fps: int = 30, non_interactive_result: str | None = None) -> dict:
        if asset.family != "SMD_MODEL_062_STATIC":
            raise RuntimeError(f"object-local animation requires SMD_MODEL_062_STATIC, got {asset.family}")
        if fps <= 0 or fps > 240:
            raise ValueError("fps must be 1..240")
        work = self._asset_workdir(asset, "OBJECT_LOCAL_ANIMATION")
        work.mkdir(parents=True, exist_ok=True)
        src = self.ctx.resolver.resolve(asset.primary_path)
        source_sha = sha256_file(src)

        parsed = parse_object_local_smd(src, strict_v1=True)
        source_report = compact_report(parsed)
        source_report_path = work / "object_local_source_report.json"
        source_report_path.write_text(json.dumps(source_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if parsed["animated_object_count"] < 1:
            raise RuntimeError("object-local source is HOLD/NONE: serialized transform arrays exist but no visible local transform changes")
        segmented = [o["name"] for o in parsed["objects"] if o.get("TmFrameCnt")]
        animated = [o for o in parsed["objects"] if o["motion_class"] == "ANIMATED"]
        channel_union = sorted({c for o in animated for c in o["channels_animated"]})
        max_rot_error = max((float(o.get("rotation_cumulative_max_error") or 0.0) for o in parsed["objects"]), default=0.0)
        legacy_affine = bool(parsed.get("legacy_affine_object_count"))
        zero_scale_spawn = [o for o in animated if o.get("zero_scale_reference_axes")]
        rotation_semantics = "RAW_NONUNIT_QUATERNION_MATRIX" if legacy_affine else "ACCUMULATED_TM_PREV_ROT"
        blender_semantics = "AFFINE_WORLD_DELTA_ABSOLUTE_SHAPE_KEYS" if legacy_affine else "DELTA_TRANSFORMS_OVER_STATIC_BIND"
        auto_cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="OBJECT_LOCAL_SOURCE_SEMANTICS", layer="AUTOMATIC", result="PASS", source_sha256=source_sha,
            metadata={"report": str(source_report_path), "object_count": parsed["object_count"],
                      "animated_objects": [o["name"] for o in animated], "channels_animated": channel_union,
                      "parent_edges": parsed.get("parent_edges", []),
                      "unresolved_parents": parsed.get("unresolved_parents", []),
                      "duplicate_node_name_groups": parsed.get("duplicate_node_name_groups", {}),
                      "parent_resolution_semantics": parsed.get("parent_resolution_semantics"),
                      "hierarchy_semantics": "LOCAL_QMAT_TIMES_PARENT_TMRESULT",
                      "blender_transform_semantics": blender_semantics,
                      "rotation_semantics": rotation_semantics,
                      "legacy_affine_object_count": parsed.get("legacy_affine_object_count",0),
                      "legacy_affine_objects": parsed.get("legacy_affine_objects",[]),
                      "zero_scale_spawn_objects": [o["name"] for o in zero_scale_spawn],
                      "scale_reference_semantics": "ZERO_SCALE_SPAWN_EXCEPTION_WHEN_REFERENCE_AXIS_IS_ZERO",
                      "source_rot_key_semantics": "INCREMENTAL_LOCAL_QUATERNION"},
        )

        overlay_root, texture_report = self._texture_overlay(asset, work)
        _src, pristine, _lod = self._prepare_static_blend(asset, work, overlay_root)
        preview = work / "object_local_preview.blend"
        bake_report_path = work / "object_local_bake_report.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/blender/bake_object_local.py"), "--",
            "--smd", str(src), "--out", str(preview), "--report", str(bake_report_path), "--fps", str(int(fps)),
        ], work / "02_object_local_bake.log")
        bake_report = json.loads(bake_report_path.read_text(encoding="utf-8"))
        if bake_report.get("status") != "PASS":
            raise RuntimeError(f"object-local Blender bake did not pass: {bake_report.get('status')}")

        if non_interactive_result is None:
            gui_log = work / "03_blender_gui.log"
            proc = subprocess.run(self.ctx.settings.blender_command() + [str(preview)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            if legacy_affine:
                animation_result = self._ask("Efeito object-local affine legado está visualmente correto (movimento/escala/shear), sem explosões ou saltos espúrios?")
            elif parsed["object_count"] > 1:
                animation_result = self._ask("Movimento multiobjeto/hierarquia está correto (pais, filhos e peças independentes), sem deformar as meshes?")
            else:
                animation_result = self._ask("Movimento object-local (rotação/posição/escala) está correto, sem deformar a mesh?")
            texture_result = self._ask("Texturas e materiais carregaram corretamente?") if asset.textures else "SKIP"
        else:
            animation_result = non_interactive_result.upper()
            if animation_result not in {"PASS", "FAIL", "SKIP"}:
                raise ValueError("non_interactive_result must be PASS/FAIL/SKIP")
            texture_result = animation_result if asset.textures else "SKIP"

        overall = self._overall(animation_result, texture_result, bool(asset.textures))
        artifact_sha = sha256_file(preview)
        cert = self.ctx.certifications.add(
            asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="VISUAL_OBJECT_LOCAL_ANIMATION", layer="HUMAN_VISUAL", result=overall,
            source_sha256=source_sha, artifact_sha256=artifact_sha,
            metadata={"automatic_certification_id": auto_cert["certification_id"], "source_report": str(source_report_path),
                      "bake_report": str(bake_report_path), "preview": str(preview), "preview_fps": int(fps),
                      "object_count": parsed["object_count"], "parent_edge_count": parsed.get("parent_edge_count", 0),
                      "unresolved_parent_count": parsed.get("unresolved_parent_count", 0),
                      "duplicate_node_name_group_count": parsed.get("duplicate_node_name_group_count", 0),
                      "parent_resolution_semantics": parsed.get("parent_resolution_semantics"),
                      "hierarchy_semantics": "LOCAL_QMAT_TIMES_PARENT_TMRESULT",
                      "blender_transform_semantics": blender_semantics,
                      "rotation_semantics": rotation_semantics,
                      "legacy_affine_object_count": parsed.get("legacy_affine_object_count",0),
                      "zero_scale_spawn_object_count": len(zero_scale_spawn),
                      "zero_scale_spawn_objects": [o["name"] for o in zero_scale_spawn],
                      "timing_status": "PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED"},
        )
        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family, "mode": "STATIC_OBJECT_LOCAL",
            "preview_version": int(bake_report.get("preview_version") or (4 if legacy_affine else 3)), "object_count": parsed["object_count"],
            "animated_object_count": parsed["animated_object_count"], "animated_objects": [o["name"] for o in animated],
            "root_objects": parsed.get("root_objects", []), "parent_edge_count": parsed.get("parent_edge_count", 0),
            "parent_edges": parsed.get("parent_edges", []),
            "unresolved_parent_count": parsed.get("unresolved_parent_count", 0),
            "unresolved_parents": parsed.get("unresolved_parents", []),
            "duplicate_node_name_group_count": parsed.get("duplicate_node_name_group_count", 0),
            "duplicate_node_name_groups": parsed.get("duplicate_node_name_groups", {}),
            "parent_resolution_semantics": parsed.get("parent_resolution_semantics"),
            "channels_animated": channel_union,
            "reference_engine_frame": bake_report.get("reference_engine_frame"), "max_engine_frame": bake_report.get("max_engine_frame"),
            "preview_frame_start": bake_report.get("preview_frame_start"), "preview_frame_end": bake_report.get("preview_frame_end"),
            "preview_fps": int(fps), "preview_reference": bake_report.get("preview_reference"),
            "hierarchy_semantics": "LOCAL_QMAT_TIMES_PARENT_TMRESULT",
            "blender_transform_semantics": blender_semantics,
            "animated_child_count": parsed.get("animated_child_count", 0),
            "legacy_affine_object_count": parsed.get("legacy_affine_object_count",0),
            "legacy_affine_objects": parsed.get("legacy_affine_objects",[]),
            "affine_affected_objects": bake_report.get("affine_affected_objects",[]),
            "zero_scale_spawn_object_count": len(zero_scale_spawn),
            "zero_scale_spawn_objects": [o["name"] for o in zero_scale_spawn],
            "scale_reference_semantics": "ZERO_SCALE_SPAWN_EXCEPTION_WHEN_REFERENCE_AXIS_IS_ZERO",
            "rotation_semantics": rotation_semantics, "source_rot_key_semantics": "INCREMENTAL_LOCAL_QUATERNION",
            "legacy_affine_interpolation": bake_report.get("legacy_affine_interpolation"),
            "interpolation": "LINEAR_SAMPLED_EVERY_SOURCE_TICK", "timing_status": "PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED",
            "rotation_cumulative_max_error": max_rot_error,
            "source_semantics": "PASS", "animation_visual": animation_result, "texture_material_visual": texture_result,
            "visual_object_local_asset": overall, "texture_prepare": "PASS" if texture_report["ready"] else "FAIL",
            "preview_blend": str(preview), "source_sha256": source_sha, "artifact_sha256": artifact_sha,
            "certification_id": cert["certification_id"], "automatic_certification_id": auto_cert["certification_id"],
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary

    def visual_animation(self, asset: Asset, lod: str = "auto", motion: str = "auto", load_actions: str = "all", fps: int = 30, non_interactive_result: str | None = None, head_asset: Asset | None = None, head_variant: dict | None = None) -> dict:
        if asset.visual_mode != "RIGID" or not asset.animation_binding_ready:
            raise RuntimeError(f"animation gate requires a resolved motion context; skeleton binding={asset.binding_mode}/{asset.binding_source} animation_binding_ready={asset.animation_binding_ready}")

        load_actions = str(load_actions or "all").strip().lower()
        if load_actions not in {"selected", "core", "all"}:
            raise ValueError("load_actions must be selected/core/all")

        # RC6.18 workspace policy:
        # - all: one persistent asset-level workspace, reused across Action changes;
        # - selected: isolated single-motion workspace for focused editing;
        # - core: isolated legacy subset workspace.
        motion_token = "".join(c if c.isalnum() else "_" for c in str(motion or "auto")).strip("_") or "auto"
        if load_actions == "all":
            test_name = "VISUAL_ANIMATION"
        elif load_actions == "selected":
            test_name = f"VISUAL_ANIMATION_SELECTED_{motion_token}"
        else:
            test_name = f"VISUAL_ANIMATION_CORE_{motion_token}"
        work = self._asset_workdir(asset, test_name)
        work.mkdir(parents=True, exist_ok=True)

        self.structural(asset)
        if head_asset is not None:
            if head_asset.visual_mode != "RIGID" or not head_asset.animation_binding_ready:
                raise RuntimeError(f"head part has no resolved animation context: {head_asset.primary_path}")
            if head_asset.binding_skeleton_smb.lower() != asset.binding_skeleton_smb.lower():
                raise RuntimeError(f"head/body skeleton SMB mismatch: body={asset.binding_skeleton_smb} head={head_asset.binding_skeleton_smb}")
            body_motion_inx={str(c.get("motion_inx") or "").lower() for c in asset.configs if c.get("motion_inx")}
            head_motion_inx={str(c.get("motion_inx") or "").lower() for c in head_asset.configs if c.get("motion_inx")}
            if len(body_motion_inx)!=1 or head_motion_inx != body_motion_inx:
                raise RuntimeError(f"head/body root motion INX mismatch: body={sorted(body_motion_inx)} head={sorted(head_motion_inx)}")
            self.structural(head_asset)

        # Resolve motion context before importing/rebuilding Blender so an existing
        # persistent ALL workspace can be reused without destroying paint/edits.
        cfg = next((x for x in asset.configs if x.get("motion_smb")), asset.configs[0])
        motion_inx = cfg.get("motion_inx") or (cfg.get("inx") if asset.binding_source not in {"STRUCTURAL_GATE_UNIQUE", "SKELETON_SIGNATURE_UNIQUE", "GATE_FIRST_SKELETON_UNIQUE", "PHYSIQUE_SUBSET_EQUIVALENT"} else "")
        if not motion_inx:
            raise RuntimeError("root skeleton is structurally bound, but root motion INX is not uniquely resolved")
        inx = self.ctx.resolver.resolve(motion_inx)
        smb = self.ctx.resolver.resolve(cfg["motion_smb"])
        payload = build_bake_payload(self.root, inx, smb, selector=motion, load_actions=load_actions, fps=fps)
        print(f"selected_action={payload['selected_action']} load_actions={load_actions} actions_loaded={len(payload['actions'])}")
        print("available_actions=" + ",".join(x["name"] for x in payload["actions"]))
        if len(payload["actions"]) > 1:
            print("note=All loaded Actions share one Blender workspace. Switch them in Dope Sheet/Action Editor; reopening via UI reuses the ALL workspace instead of rebuilding it.")
        print("note=Motion state matching is case-insensitive.")
        payload_path = work / "motion_bake_payload.json"
        write_payload(payload_path, payload)

        body_work=work / "body" if head_asset is not None else work
        body_work.mkdir(parents=True,exist_ok=True)

        source_path = pathlib.Path(self.ctx.resolver.resolve(asset.primary_path))
        source_sha = sha256_file(source_path)
        inx_sha = sha256_file(pathlib.Path(inx))
        smb_sha = sha256_file(pathlib.Path(smb))

        persistent_single_asset = (head_asset is None and load_actions == "all")
        animated = work / "animated_validation.blend"
        state_path = work / "animation_workspace_state.json"
        reused_workspace = False

        src = source_path
        pristine = work / "pristine_import.blend"
        actual_lod = lod
        texture_report = {"ready": True}
        head_src=None; head_lod=None; head_texture_report=None; head_animated=None; assembly_report=None

        if persistent_single_asset and animated.is_file() and state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                state = {}
            expected_actions = {x["name"] for x in payload["actions"]}
            saved_actions = set(state.get("actions_loaded") or [])
            reusable = (
                state.get("format") == "PT_ANIMATION_PERSISTENT_WORKSPACE_V2"
                and state.get("asset_id") == asset.asset_id
                and state.get("source_sha256") == source_sha
                and state.get("inx_sha256") == inx_sha
                and state.get("smb_sha256") == smb_sha
                and state.get("load_actions") == "all"
                and expected_actions.issubset(saved_actions)
            )
            if reusable:
                selector_script = self.root / "pt_asset_tool/blender/select_animation_action.py"
                run_logged(self.ctx.settings.blender_command() + [
                    "--background", str(animated), "--python-exit-code", "1",
                    "--python", str(selector_script), "--",
                    "--action", str(payload["selected_action"]),
                    "--out", str(animated),
                ], work / "02_select_existing_action.log")
                reused_workspace = True
                actual_lod = str(state.get("lod") or "auto")
                pristine = pathlib.Path(state.get("pristine_blend") or pristine)
                try:
                    texture_report = json.loads((body_work / "texture_overlay_report.json").read_text(encoding="utf-8"))
                except Exception:
                    texture_report = {"ready": True, "reused_workspace": True}
                print(f"animation_workspace=REUSED persistent=true blend={animated}")

        if not reused_workspace:
            overlay_root, texture_report = self._texture_overlay(asset, body_work)
            src, pristine, actual_lod, _body_cfg = self._prepare_rigid_blend(asset, lod, body_work, overlay_root)

            body_animated = work / ("body_animated.blend" if head_asset is not None else "animated_validation.blend")
            body_bake_report = work / ("body_animation_bake_report.json" if head_asset is not None else "animation_bake_report.json")
            cmd = self.ctx.settings.blender_command() + [
                "--background", str(pristine), "--python-exit-code", "1",
                "--python", str(self.root / "pt_asset_tool/blender/bake_actions.py"), "--",
                "--payload", str(payload_path), "--out", str(body_animated), "--report", str(body_bake_report),
            ]
            run_logged(cmd, work / ("02_body_animation_bake.log" if head_asset is not None else "02_animation_bake.log"))

            animated=body_animated
            if head_asset is not None:
                head_work=work / "head"; head_work.mkdir(parents=True,exist_ok=True)
                head_overlay, head_texture_report = self._texture_overlay(head_asset, head_work)
                try:
                    head_src, head_pristine, head_lod, _head_cfg = self._prepare_rigid_blend(head_asset, actual_lod, head_work, head_overlay)
                except RuntimeError:
                    head_src, head_pristine, head_lod, _head_cfg = self._prepare_rigid_blend(head_asset, "auto", head_work, head_overlay)
                head_animated=work / "head_animated.blend"
                head_bake_report=work / "head_animation_bake_report.json"
                run_logged(self.ctx.settings.blender_command() + [
                    "--background", str(head_pristine), "--python-exit-code", "1",
                    "--python", str(self.root / "pt_asset_tool/blender/bake_actions.py"), "--",
                    "--payload", str(payload_path), "--out", str(head_animated), "--report", str(head_bake_report),
                ], work / "03_head_animation_bake.log")
                animated=work / "animated_validation.blend"
                assembly_report=work / "player_assembly_report.json"
                run_logged(self.ctx.settings.blender_command() + [
                    "--background", str(body_animated), "--python-exit-code", "1",
                    "--python", str(self.root / "pt_asset_tool/blender/assemble_player_parts.py"), "--",
                    "--part", str(head_animated), "--out", str(animated), "--report", str(assembly_report),
                    "--prefix", "PT_HEAD__",
                ], work / "04_player_assembly.log")

            # Prepare an edit-safe visual workspace. Affine helpers are hidden,
            # Armature deformation remains visible in Edit Mode, images remain
            # file-backed in the pt_build overlay, and modifier-on-cage is disabled
            # to avoid unstable legacy-rig mode/Texture-Paint transitions.
            prepare_script = self.root / "pt_asset_tool/blender/prepare_animation_workspace.py"
            run_logged(self.ctx.settings.blender_command() + [
                "--background", str(animated), "--python-exit-code", "1",
                "--python", str(prepare_script), "--",
                "--out", str(animated),
                "--action", str(payload["selected_action"]),
            ], work / ("05_prepare_animation_workspace.log" if head_asset is not None else "03_prepare_animation_workspace.log"))

            if persistent_single_asset:
                state = {
                    "format": "PT_ANIMATION_PERSISTENT_WORKSPACE_V2",
                    "asset_id": asset.asset_id,
                    "asset": asset.primary_path,
                    "source_sha256": source_sha,
                    "inx": str(inx),
                    "inx_sha256": inx_sha,
                    "smb": str(smb),
                    "smb_sha256": smb_sha,
                    "lod": actual_lod,
                    "load_actions": "all",
                    "actions_loaded": [x["name"] for x in payload["actions"]],
                    "pristine_blend": str(pristine),
                    "animated_blend": str(animated),
                    "paint_persistence": "PT_BUILD_OVERLAY_FILE_SAVE_AFTER_LEAVING_TEXTURE_PAINT",
                    "modifier_show_on_cage": False,
                    "action_slot_autofix": True,
                    "client_modified": False,
                }
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"animation_workspace=CREATED persistent=true blend={animated}")

        # Verify every baked Action after save/reopen before opening the GUI.
        # This turns WALK/action corruption into an automatic fail-closed result
        # and separates it from an Edit-Mode/viewport presentation issue.
        action_pose_check = None
        if head_asset is None:
            action_pose_report = work / "animation_pose_persistence_check.json"
            run_logged(self.ctx.settings.blender_command() + [
                "--background", str(animated), "--python-exit-code", "1",
                "--python", str(self.root / "pt_asset_tool/blender/check_baked_animation_pose.py"), "--",
                "--payload", str(payload_path),
                "--report", str(action_pose_report),
            ], work / "animation_pose_persistence_check.log")
            action_pose_check = json.loads(action_pose_report.read_text(encoding="utf-8"))
            if action_pose_check.get("status") != "PASS":
                raise RuntimeError(
                    "saved Action pose persistence failed before visual review: "
                    f"{action_pose_check.get('errors')}"
                )
            print(
                "animation_pose_persistence=PASS "
                f"actions={action_pose_check.get('action_count')} "
                f"max_error={action_pose_check.get('max_abs_matrix_error')}"
            )

        if non_interactive_result is None:
            # Run the session guard inside the actual GUI process. It keeps a mesh
            # active (not the armature), hides PT_AFF helper bones, keeps the
            # modifier visible in Edit Mode without forcing on-cage, fixes Action
            # slots after Action Editor switches, and saves dirty paint only to
            # pt_build overlay files after leaving Texture Paint.
            gui_cmd = self.ctx.settings.blender_command() + [str(animated)]
            print("animation_gui_live_guard=false")
            gui_log = work / ("06_blender_gui.log" if head_asset is not None else "04_blender_gui.log")
            proc = subprocess.run(gui_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            if head_asset is not None:
                assembly_visual=self._ask("Corpo e cabeça estão montados/alinhados corretamente durante a animação?")
                if assembly_visual == "FAIL":
                    rig_result="FAIL"; anim_result="SKIP"
                    print("mesh_deformation_visual=FAIL animation_visual=SKIP (blocked_by_player_assembly_fail)")
                else:
                    rig_result = self._ask("A malha/deformação visual do conjunto corpo+cabeça está correta? (ignore a forma gráfica dos bones/helper bones)")
                    if rig_result == "FAIL":
                        print("animation_visual=SKIP (blocked_by_mesh_deformation_fail)")
                        anim_result = "SKIP"
                    else:
                        anim_result = self._ask("A animação ativa do conjunto está visualmente correta?")
                has_textures=bool(asset.textures or head_asset.textures)
                texture_result = self._ask("Texturas e materiais do corpo+cabeça carregaram corretamente?") if has_textures else "SKIP"
            else:
                assembly_visual="SKIP"
                rig_result = self._ask("A malha/deformação visual durante a animação está correta? (ignore a forma gráfica dos bones/helper bones)")
                if rig_result == "FAIL":
                    print("animation_visual=SKIP (blocked_by_mesh_deformation_fail)")
                    anim_result = "SKIP"
                else:
                    anim_result = self._ask("A animação ativa está visualmente correta?")
                texture_result = self._ask("Texturas e materiais carregaram corretamente?") if asset.textures else "SKIP"
        else:
            v = non_interactive_result.upper()
            if v not in {"PASS","FAIL","SKIP"}: raise ValueError("non_interactive_result must be PASS/FAIL/SKIP")
            assembly_visual = v if head_asset is not None else "SKIP"
            rig_result = anim_result = v
            texture_result = v if (asset.textures or (head_asset and head_asset.textures)) else "SKIP"

        source_sha = sha256_file(src)
        head_source_sha=sha256_file(head_src) if head_src is not None else None
        artifact_sha = sha256_file(animated)
        selected = payload["selected_action"]
        selected_spec = next((x for x in payload["actions"] if x["name"] == selected), {})
        assembly_mode="BODY_PLUS_INDEPENDENT_HEAD" if head_asset is not None else "SINGLE_ASSET"
        common_meta = {
            "animated_blend": str(animated), "pristine_blend": str(pristine), "lod": actual_lod,
            "selected_action": selected, "selected_motion_index": payload["selected_motion_index"],
            "actions_loaded": [x["name"] for x in payload["actions"]], "load_actions": load_actions,
            "animation_workspace_reused": reused_workspace,
            "animation_workspace_persistent": persistent_single_asset,
            "paint_persistence": "PT_BUILD_OVERLAY_FILE_SAVE_AFTER_LEAVING_TEXTURE_PAINT" if persistent_single_asset else "SESSION_BLEND",
            "action_pose_persistence_check": (action_pose_check or {}).get("status") if head_asset is None else None,
            "action_pose_persistence_max_error": (action_pose_check or {}).get("max_abs_matrix_error") if head_asset is None else None,
            "fps": fps, "timing_status": "PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED",
            "quaternion_null_semantics": payload.get("quaternion_null_semantics", "UNKNOWN"),
            "source_pose_reference": selected_spec.get("source_pose_reference", "GLOBAL_BIND"),
            "pose_guard": selected_spec.get("pose_guard", "NONE"),
            "pose_guard_bones": selected_spec.get("pose_guard_bones", []),
            "quaternion_sign_continuity": True, "interpolation": "LINEAR",
            "texture_overlay_report": str(body_work / "texture_overlay_report.json"),
            "binding_mode": asset.binding_mode, "binding_source": asset.binding_source,
            "binding_root_models": asset.binding_root_models,
            "assembly_mode":assembly_mode,
            "assembly_visual":assembly_visual,
            "head_asset_id":head_asset.asset_id if head_asset else None,
            "head_asset":head_asset.primary_path if head_asset else None,
            "head_lod":head_lod,
            "head_appearance_key":(head_variant or {}).get("appearance_key") if head_asset else None,
            "head_tier":(head_variant or {}).get("tier_name") if head_asset else None,
            "head_tier_code":(head_variant or {}).get("tier_code") if head_asset else None,
            "head_tier_index":(head_variant or {}).get("tier_index") if head_asset else None,
            "head_tier_kind":(head_variant or {}).get("tier_kind") if head_asset else None,
            "head_descriptor_kind":(head_variant or {}).get("descriptor_kind") if head_asset else None,
            "head_source_sha256":head_source_sha,
            "head_animated_blend":str(head_animated) if head_animated else None,
            "head_texture_overlay_report":str((work / "head" / "texture_overlay_report.json")) if head_asset else None,
            "assembly_report":str(assembly_report) if assembly_report else None,
        }
        for test, result in (("VISUAL_RIG", rig_result), (f"VISUAL_ANIMATION_{selected}", anim_result)):
            self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test=test, layer="HUMAN_VISUAL", result=result, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta)
        if asset.textures or (head_asset and head_asset.textures):
            self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="VISUAL_TEXTURE_MATERIAL", layer="HUMAN_VISUAL", result=texture_result, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta)
        relevant=[rig_result,anim_result]+([texture_result] if (asset.textures or (head_asset and head_asset.textures)) else [])
        if head_asset is not None:
            relevant.append(assembly_visual)
        overall="FAIL" if "FAIL" in relevant else ("PASS" if all(x=="PASS" for x in relevant) else "SKIP")
        if head_asset is not None:
            self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="VISUAL_PLAYER_ASSEMBLY", layer="HUMAN_VISUAL", result=assembly_visual, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta)
            self.ctx.certifications.add(asset_id=head_asset.asset_id, asset_path=head_asset.primary_path, family=head_asset.family,
                test="VISUAL_ANIMATION_ASSEMBLED_PART", layer="HUMAN_VISUAL", result=overall, source_sha256=head_source_sha, artifact_sha256=artifact_sha, metadata=common_meta)
        cert=self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
            test="VISUAL_ANIMATION_ASSET", layer="HUMAN_VISUAL", result=overall, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=common_meta)
        summary={
            "asset_id":asset.asset_id,"asset":asset.primary_path,"family":asset.family,"requested_lod":lod,"lod":actual_lod,
            "binding_mode":asset.binding_mode,"binding_source":asset.binding_source,"binding_root_models":asset.binding_root_models,
            "assembly_mode":assembly_mode,"assembly_visual":assembly_visual,
            "head_asset_id":head_asset.asset_id if head_asset else None,"head_asset":head_asset.primary_path if head_asset else None,"head_lod":head_lod,
            "head_appearance_key":(head_variant or {}).get("appearance_key") if head_asset else None,
            "head_tier":(head_variant or {}).get("tier_name") if head_asset else None,
            "head_tier_code":(head_variant or {}).get("tier_code") if head_asset else None,
            "head_tier_index":(head_variant or {}).get("tier_index") if head_asset else None,
            "head_tier_kind":(head_variant or {}).get("tier_kind") if head_asset else None,
            "selected_action":selected,"selected_motion_index":payload["selected_motion_index"],
            "actions_loaded":[x["name"] for x in payload["actions"]],"active_motion_count":payload["active_motion_count"],
            "load_actions":load_actions,
            "animation_workspace_reused":reused_workspace,
            "animation_workspace_persistent":persistent_single_asset,
            "action_pose_persistence_check":(action_pose_check or {}).get("status") if head_asset is None else None,
            "action_pose_persistence_max_error":(action_pose_check or {}).get("max_abs_matrix_error") if head_asset is None else None,
            "animated_blend":str(animated),"source_sha256":source_sha,"head_source_sha256":head_source_sha,"artifact_sha256":artifact_sha,
            "rig_visual":rig_result,"animation_visual":anim_result,"texture_material_visual":texture_result,"visual_animation_asset":overall,
            "preview_fps":fps,"timing_status":"PREVIEW_NOT_RUNTIME_SPEED_CERTIFIED",
            "quaternion_null_semantics":payload.get("quaternion_null_semantics","UNKNOWN"),
            "source_pose_reference":selected_spec.get("source_pose_reference","GLOBAL_BIND"),
            "pose_guard":selected_spec.get("pose_guard","NONE"),
            "pose_guard_bones":selected_spec.get("pose_guard_bones",[]),
            "quaternion_sign_continuity":True,"interpolation":"LINEAR",
            "certification_id":cert["certification_id"],"client_modified":False,
        }
        (work / "summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return summary

    def animation_diagnostic(self, asset: Asset, lod: str = "auto", motion: str = "ATTACK", load_actions: str = "selected", fps: int = 30, non_interactive: bool = False) -> dict:
        if asset.visual_mode != "RIGID" or not asset.animation_binding_ready:
            raise RuntimeError(f"animation diagnostic requires a resolved motion context; skeleton binding={asset.binding_mode}/{asset.binding_source} animation_binding_ready={asset.animation_binding_ready}")
        work = self._asset_workdir(asset, "ANIMATION_DIAGNOSTIC")
        work.mkdir(parents=True, exist_ok=True)

        self.structural(asset)
        overlay_root, texture_report = self._texture_overlay(asset, work)
        src, pristine, actual_lod, _cfg = self._prepare_rigid_blend(asset, lod, work, overlay_root)
        cfg = next((x for x in asset.configs if x.get("motion_smb")), asset.configs[0])
        motion_inx = cfg.get("motion_inx") or (cfg.get("inx") if asset.binding_source not in {"STRUCTURAL_GATE_UNIQUE", "SKELETON_SIGNATURE_UNIQUE", "GATE_FIRST_SKELETON_UNIQUE", "PHYSIQUE_SUBSET_EQUIVALENT"} else "")
        if not motion_inx:
            raise RuntimeError("root skeleton is structurally bound, but root motion INX is not uniquely resolved")
        inx = self.ctx.resolver.resolve(motion_inx)
        smb = self.ctx.resolver.resolve(cfg["motion_smb"])

        payload = build_bake_payload(self.root, inx, smb, selector=motion, load_actions=load_actions, fps=fps)
        print(f"selected_action={payload['selected_action']} load_actions={load_actions} actions_loaded={len(payload['actions'])}")
        print("available_actions=" + ",".join(x["name"] for x in payload["actions"]))
        if len(payload["actions"]) > 1:
            print("note=Blender shows only selected_action as active in the viewport; the other loaded Actions are available in the Dope Sheet/Action Editor.")
        payload_path = work / "motion_bake_payload.json"
        write_payload(payload_path, payload)

        animated = work / "animated_validation.blend"
        bake_report = work / "animation_bake_report.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(pristine), "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/blender/bake_actions.py"), "--",
            "--payload", str(payload_path), "--out", str(animated), "--report", str(bake_report),
        ], work / "02_animation_bake.log")

        diagnostic = work / "source_vs_armature_diagnostic.blend"
        diagnostic_report = work / "animation_bridge_diagnostic.json"
        run_logged(self.ctx.settings.blender_command() + [
            "--background", str(animated), "--python-exit-code", "1",
            "--python", str(self.root / "pt_asset_tool/blender/diagnose_animation_bridge.py"), "--",
            "--payload", str(payload_path), "--out", str(diagnostic), "--report", str(diagnostic_report),
        ], work / "03_animation_diagnostic.log")

        report = json.loads(diagnostic_report.read_text(encoding="utf-8"))
        direct_result = armature_match = "SKIP"
        if not non_interactive:
            gui_log = work / "04_blender_gui.log"
            proc = subprocess.run(self.ctx.settings.blender_command() + [
                str(diagnostic), "--python", str(self.root / "pt_asset_tool/blender/open_animation_diagnostic.py")
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            gui_log.write_text(proc.stdout or "", encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Blender GUI exited rc={proc.returncode}; log={gui_log}")
            direct_result = self._ask(f"SOURCE_DIRECT (esquerda, animado) executa {payload.get('selected_action', 'a motion selecionada')} de forma coerente?")
            armature_match = self._ask("BLENDER_ARMATURE (direita, animado) acompanha o SOURCE_DIRECT sem explodir?")

        source_sha = sha256_file(src)
        artifact_sha = sha256_file(diagnostic)
        selected_spec = next((x for x in payload["actions"] if x["name"] == payload["selected_action"]), {})
        meta = {
            "diagnostic_blend": str(diagnostic),
            "diagnostic_report": str(diagnostic_report),
            "selected_action": payload["selected_action"],
            "selected_motion_index": payload["selected_motion_index"],
            "lod": actual_lod,
            "worst_frame": report.get("worst_frame", {}),
            "source_pose_reference": selected_spec.get("source_pose_reference", "GLOBAL_BIND"),
            "pose_guard": selected_spec.get("pose_guard", "NONE"),
            "pose_guard_bones": selected_spec.get("pose_guard_bones", []),
            "comparison": "ANIMATED_SOURCE_DIRECT_vs_BLENDER_ARMATURE",
        }
        if not non_interactive:
            self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="DIAG_SOURCE_DIRECT", layer="HUMAN_VISUAL", result=direct_result, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=meta)
            self.ctx.certifications.add(asset_id=asset.asset_id, asset_path=asset.primary_path, family=asset.family,
                test="DIAG_ARMATURE_MATCH", layer="HUMAN_VISUAL", result=armature_match, source_sha256=source_sha, artifact_sha256=artifact_sha, metadata=meta)

        summary = {
            "asset_id": asset.asset_id, "asset": asset.primary_path, "family": asset.family,
            "requested_lod": lod, "lod": actual_lod,
            "selected_action": payload["selected_action"],
            "selected_motion_index": payload["selected_motion_index"],
            "frames_checked": report.get("frames_checked"),
            "worst_frame": report.get("worst_frame"),
            "top_bone_max_error": report.get("top_bone_max_error", [])[:10],
            "source_pose_reference": selected_spec.get("source_pose_reference", "GLOBAL_BIND"),
            "pose_guard": selected_spec.get("pose_guard", "NONE"),
            "pose_guard_bones": selected_spec.get("pose_guard_bones", []),
            "source_direct_visual": direct_result,
            "armature_match_visual": armature_match,
            "diagnostic_blend": str(diagnostic),
            "diagnostic_report": str(diagnostic_report),
            "source_sha256": source_sha, "artifact_sha256": artifact_sha,
            "client_modified": False,
        }
        (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        return summary

