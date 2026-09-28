from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def test_primary_web_ui_is_english():
    html = (ROOT / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    for marker in (
        "Asset Catalog",
        "Client / Enrichment",
        "Server / Enrichment",
        "Legacy Authoring — Python tasks",
        "World Closure Explorer",
        "General Jobs",
        "Reports",
        "Settings",
    ):
        assert marker in html
    for forbidden in (
        "Catálogo",
        "Tarefas",
        "Configuração",
        "Nenhum candidato",
        "Por que está em REVIEW?",
        "Comparação concluída",
    ):
        assert forbidden not in html + js


def test_english_documentation_is_authoritative_and_linked():
    docs = PROJECT / "docs/en"
    required = (
        "README.md",
        "getting_started/USER_MANUAL.md",
        "getting_started/GUI_MANUAL.md",
        "getting_started/CLI_REFERENCE.md",
        "engineering/ARCHITECTURE.md",
        "topics/SEMANTIC_AUTHORING_CATALOG.md",
        "topics/ASSET_QUARANTINE_WORKFLOW.md",
    )
    for rel in required:
        assert (docs / rel).is_file(), rel
    root_readme = (PROJECT / "docs/README.md").read_text(encoding="utf-8")
    assert "docs/en" in root_readme
    assert "English" in root_readme


def test_semantic_catalog_game_names_are_not_translated():
    catalog = ROOT / "pt_asset_tool/contracts/priston_asset_name_map_v1.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    assert data["metadata"]["counts"]["unique_1x1"] == 2607
    # Game-facing localized names are contract data, not UI chrome.
    row = next(x for x in data["master_1x1"] if x.get("canonical_id") == "item.or101")
    assert row["display_name"] == "Anel Comum"
    assert row["internal_name"] == "OR101"
