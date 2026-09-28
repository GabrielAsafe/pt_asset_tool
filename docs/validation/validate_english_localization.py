#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

STATIC_FILES = [
    APP / "pt_asset_tool/ui_static/index.html",
    APP / "pt_asset_tool/ui_static/app.js",
]
BACKEND_SURFACES = [
    APP / "pt_asset_tool/ui_actions.py",
    APP / "pt_asset_tool/ui_catalog.py",
    APP / "pt_asset_tool/server_ui.py",
    APP / "pt_asset_tool/ui_app.py",
    APP / "pt_asset_tool/legacy_management_web.py",
]
REQUIRED_ENGLISH_DOCS = [
    ROOT / "docs/en/README.md",
    ROOT / "docs/en/getting_started/INSTALLATION_QUICKSTART.md",
    ROOT / "docs/en/getting_started/USER_MANUAL.md",
    ROOT / "docs/en/getting_started/GUI_MANUAL.md",
    ROOT / "docs/en/getting_started/CLI_REFERENCE.md",
    ROOT / "docs/en/engineering/ARCHITECTURE.md",
    ROOT / "docs/en/topics/SEMANTIC_AUTHORING_CATALOG.md",
    ROOT / "docs/en/topics/ASSET_QUARANTINE_WORKFLOW.md",
]

# These are application chrome / operator phrases, not game data. Game display
# names are deliberately excluded because the semantic authoring catalog keeps
# source-locale names as matching data.
FORBIDDEN_STATIC = [
    "Catálogo",
    "Tarefas",
    "Configuração",
    "Comparação concluída",
    "Nenhum candidato",
    "Por que está em REVIEW?",
    "Armar por 15 min",
    "Construir / auditar",
    "Carregando characters",
    "Detectando base local",
]
FORBIDDEN_BACKEND = [
    "Arme explicitamente",
    "Instale Pillow",
    "Mostra quais canais",
    "Executa o validator",
    "Descobre candidatos",
    "Inspeciona relações",
    "Restaura os bytes",
    "A definição aponta",
]


def fail(message: str) -> None:
    raise SystemExit(f"EN_LOCALIZATION=FAIL {message}")


def main() -> int:
    html = STATIC_FILES[0].read_text(encoding="utf-8")
    if '<html lang="en">' not in html:
        fail("html_lang_not_en")

    static = "\n".join(path.read_text(encoding="utf-8") for path in STATIC_FILES)
    for token in FORBIDDEN_STATIC:
        if token in static:
            fail(f"portuguese_static_token={token!r}")

    backend = "\n".join(path.read_text(encoding="utf-8") for path in BACKEND_SURFACES)
    for token in FORBIDDEN_BACKEND:
        if token in backend:
            fail(f"portuguese_backend_token={token!r}")

    for path in REQUIRED_ENGLISH_DOCS:
        if not path.is_file():
            fail(f"missing_english_doc={path.relative_to(ROOT)}")

    docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    if "docs/en" not in docs_index or "English" not in docs_index:
        fail("docs_index_not_english_first")

    catalog_path = APP / "pt_asset_tool/contracts/priston_asset_name_map_v1.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if data.get("metadata", {}).get("counts", {}).get("unique_1x1") != 2607:
        fail("semantic_catalog_count_changed")
    item = next((x for x in data.get("master_1x1", []) if x.get("canonical_id") == "item.or101"), None)
    if not item or item.get("display_name") != "Anel Comum" or item.get("internal_name") != "OR101":
        fail("semantic_game_display_name_was_translated_or_changed")

    print("EN_LOCALIZATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
