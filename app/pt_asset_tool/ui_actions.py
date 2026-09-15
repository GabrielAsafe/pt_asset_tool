from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    group: str
    description: str
    mutates_build: bool = False
    long_running: bool = False
    interactive: bool = False


ACTION_SPECS: dict[str, ActionSpec] = {
    "inspect": ActionSpec("inspect", "Inspecionar", "Analisar", "Inspeção física/semântica do asset."),
    "authoring_plan": ActionSpec("authoring_plan", "Plano de edição", "Analisar", "Mostra quais canais do asset podem ser editados hoje, quais writers existem e quais gates ainda bloqueiam build/publish."),
    "validate_structural": ActionSpec("validate_structural", "Estrutural", "Validar", "Executa o validator estrutural."),
    "bindings": ActionSpec("bindings", "Bindings", "Analisar", "Descobre candidatos de skeleton/Physique.", long_running=True),
    "motions": ActionSpec("motions", "Animações", "Analisar", "Lista motions associados ao asset."),
    "heads": ActionSpec("heads", "Cabeças compatíveis", "Analisar", "Lista partes de cabeça/rosto verificadas para o mesmo root de animação."),
    "texlinks": ActionSpec("texlinks", "TexLinks", "Analisar", "Inspeciona relações TexLink/material."),
    "object_local": ActionSpec("object_local", "Object Local", "Analisar", "Inspeciona semântica de transform object-local."),
    "validate_visual": ActionSpec("validate_visual", "Validar visual", "Validar", "Abre o asset no Blender para avaliação humana de geometria/texturas; responda pela aba Tarefas.", long_running=True, interactive=True),
    "validate_roundtrip": ActionSpec("validate_roundtrip", "Roundtrip Model", "Validar", "Reconstrói uma cópia estática com witness controlado e pede avaliação humana pela aba Tarefas.", long_running=True, interactive=True),
    "validate_object_local": ActionSpec("validate_object_local", "Roundtrip Object Local", "Validar", "Valida animação/transforms object-local em Blender; respostas humanas são enviadas pela aba Tarefas.", long_running=True, interactive=True),
    "validate_texlink_roundtrip": ActionSpec("validate_texlink_roundtrip", "Roundtrip TexLink", "Validar", "Valida roundtrip TexLink/UV.", long_running=True),
    "validate_stage072_preview": ActionSpec("validate_stage072_preview", "Stage Preview", "Validar", "Valida transporte/preview Stage0.72.", long_running=True),
    "validate_stage072_uv_roundtrip": ActionSpec("validate_stage072_uv_roundtrip", "Stage UV Roundtrip", "Validar", "Valida roundtrip UV Stage0.72.", long_running=True),
    "validate_stage072_geometry_roundtrip": ActionSpec("validate_stage072_geometry_roundtrip", "Stage Geometria", "Validar", "Valida roundtrip de geometria Stage0.72.", long_running=True),
    "validate_animation": ActionSpec("validate_animation", "Animação", "Validar", "Avaliação visual sem guard/timer. Para editar ou pintar, use Importar para Blender.", long_running=True, interactive=True),
    "diagnose_animation": ActionSpec("diagnose_animation", "Diagnosticar animação", "Analisar", "Compara o movimento source e o armature Blender; respostas humanas são enviadas pela aba Tarefas.", long_running=True, interactive=True),
    "import_blender": ActionSpec("import_blender", "Importar para Blender", "Editar", "Cria workspaces separados: Paint/Edit estável e Animation Preview; ambos compartilham texturas pt_build.", mutates_build=True, long_running=True),
    "view_rare": ActionSpec("view_rare", "Abrir no Blender", "Abrir", "Abre preview rare Model0.62 no Blender.", long_running=True),
    "view_stage072": ActionSpec("view_stage072", "Abrir Stage0.72", "Abrir", "Abre preview Stage0.72 no Blender.", long_running=True),
    "paint_stage072": ActionSpec("paint_stage072", "Texture Paint", "Editar", "Abre workspace de texture paint Stage0.72.", mutates_build=True, long_running=True),
    "edit_rare": ActionSpec("edit_rare", "Editar no Blender", "Editar", "Cria/abre workspace guardado de rare-model.", mutates_build=True, long_running=True),
    "write_rare": ActionSpec("write_rare", "Gerar SMD", "Build", "Executa o writer guardado; output permanece em pt_build.", mutates_build=True, long_running=True),
    "doctor": ActionSpec("doctor", "Doctor", "Sistema", "Executa pt_asset doctor."),
}

MOTION_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,48}$")


def public_action_specs() -> list[dict[str, Any]]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "group": s.group,
            "description": s.description,
            "mutates_build": s.mutates_build,
            "long_running": s.long_running,
            "interactive": s.interactive,
        }
        for s in ACTION_SPECS.values()
    ]


def build_command(project_root: pathlib.Path, action: str, rel: str | None, options: dict[str, Any] | None = None) -> list[str]:
    if action not in ACTION_SPECS:
        raise ValueError("ACTION_NOT_ALLOWED")
    options = options or {}
    exe = project_root / "pt_asset.py"
    if not exe.is_file():
        raise FileNotFoundError(f"PT_ASSET_NOT_FOUND:{exe}")
    base = ["python3", str(exe)]
    if action == "doctor":
        return base + ["doctor"]
    if not rel:
        raise ValueError("ASSET_PATH_REQUIRED")
    rel = rel.replace("\\", "/").strip("/")
    if "\x00" in rel or rel.startswith("../") or "/../" in ("/" + rel + "/"):
        raise ValueError("INVALID_ASSET_PATH")
    if action == "inspect":
        return base + ["asset", "inspect", rel, "--physical"]
    if action == "authoring_plan":
        return base + ["asset", "authoring", rel]
    if action == "validate_structural":
        return base + ["validate", "structural", rel]
    if action == "bindings":
        return base + ["bindings", "--discover", rel]
    if action == "motions":
        return base + ["asset", "motions", rel]
    if action == "heads":
        return base + ["asset", "heads", rel, "--limit", "100"]
    if action == "texlinks":
        return base + ["asset", "texlinks", rel]
    if action == "object_local":
        return base + ["asset", "object-local", rel]
    if action == "validate_roundtrip":
        return base + ["validate", "roundtrip", rel]
    if action == "validate_object_local":
        return base + ["validate", "object-local", rel]
    if action == "validate_texlink_roundtrip":
        return base + ["validate", "texlink-roundtrip", rel]
    if action == "validate_stage072_preview":
        return base + ["validate", "stage072-preview", rel]
    if action == "validate_stage072_uv_roundtrip":
        return base + ["validate", "stage072-roundtrip", rel]
    if action == "validate_stage072_geometry_roundtrip":
        return base + ["validate", "stage072-geometry-roundtrip", rel]
    if action == "validate_visual":
        return base + ["validate", "visual", rel]
    if action in {"validate_animation", "diagnose_animation"}:
        motion = str(options.get("motion") or "STAND").strip().upper()
        if not MOTION_RE.match(motion):
            raise ValueError("INVALID_MOTION")
        prefix = ["validate", "animation"] if action == "validate_animation" else ["diagnose", "animation"]
        cmd = base + prefix + [rel, "--motion", motion]
        if "load_actions" in options:
            load_actions = str(options.get("load_actions") or "").strip().lower()
            if load_actions not in {"selected", "core", "all"}:
                raise ValueError("INVALID_LOAD_ACTIONS")
            cmd += ["--load-actions", load_actions]
        if action == "validate_animation" and ("head" in options or "head_tier" in options):
            head = str(options.get("head") or "auto").strip()
            head_tier = str(options.get("head_tier") or "auto").strip()
            if "\x00" in head or head.startswith("../") or "/../" in ("/" + head.replace("\\", "/") + "/"):
                raise ValueError("INVALID_HEAD")
            if not re.match(r"^[A-Za-z0-9_./\\ -]{1,240}$", head):
                raise ValueError("INVALID_HEAD")
            if not re.match(r"^[A-Za-z0-9_-]{1,32}$", head_tier):
                raise ValueError("INVALID_HEAD_TIER")
            cmd += ["--head", head, "--head-tier", head_tier]
        return cmd
    if action == "import_blender":
        cmd = base + ["import", rel]
        lod = str(options.get("lod") or "auto").strip().lower()
        if lod not in {"auto", "high", "default", "low"}:
            raise ValueError("INVALID_LOD")
        if lod != "auto":
            cmd += ["--lod", lod]
        model_info = str(options.get("model_info") or "").replace("\\", "/").strip("/")
        if model_info:
            if "\x00" in model_info or model_info.startswith("../") or "/../" in ("/" + model_info + "/"):
                raise ValueError("INVALID_MODEL_INFO")
            if not re.match(r"^[A-Za-z0-9_./ -]{1,240}\.inx$", model_info, re.IGNORECASE):
                raise ValueError("INVALID_MODEL_INFO")
            cmd += ["--model-info", model_info]
        load_actions = str(options.get("load_actions") or "all").strip().lower()
        if load_actions not in {"all", "selected", "none"}:
            raise ValueError("INVALID_IMPORT_LOAD_ACTIONS")
        cmd += ["--load-actions", load_actions]
        motion = str(options.get("motion") or "STAND").strip()
        if not MOTION_RE.match(motion):
            raise ValueError("INVALID_MOTION")
        cmd += ["--motion", motion]
        open_mode = str(options.get("open_mode") or "paint").strip().lower()
        if open_mode not in {"paint", "animation"}:
            raise ValueError("INVALID_IMPORT_OPEN_MODE")
        cmd += ["--open-mode", open_mode]
        if options.get("reset"):
            cmd.append("--reset")
        return cmd
    if action == "view_rare":
        return base + ["view", "rare-model", rel]
    if action == "view_stage072":
        return base + ["view", "stage072", rel]
    if action == "paint_stage072":
        stage = str(options.get("stage") if options.get("stage") is not None else "0")
        if stage not in {str(i) for i in range(8)}:
            raise ValueError("INVALID_STAGE")
        return base + ["paint", "stage072", rel, "--stage", stage]
    if action == "edit_rare":
        cmd = base + ["edit", "rare-model", rel]
        if options.get("reset"):
            cmd.append("--reset")
        return cmd
    if action == "write_rare":
        return base + ["write", "rare-model", rel]
    raise AssertionError(action)
