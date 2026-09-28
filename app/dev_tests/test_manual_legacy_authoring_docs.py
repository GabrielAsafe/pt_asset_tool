from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def test_user_manual_documents_legacy_authoring_end_to_end():
    text = (PROJECT / "docs" / "comece_aqui" / "MANUAL_UTILIZADOR.md").read_text(encoding="utf-8")
    for marker in (
        "World Closure Explorer",
        "Legacy Authoring / Reescrita Python",
        "ITEM MONSTER NPC SPM SPP SPC",
        "APPLY ASSET BUNDLE",
        "RESTORE ASSET BUNDLE",
        "RUNTIME_CATALOG_MISSING",
        "Nenhum executável legacy é requerido",
    ):
        assert marker in text


def test_gui_help_surfaces_explorer_to_authoring_workflow():
    html = (ROOT / "pt_asset_tool" / "ui_static" / "index.html").read_text(encoding="utf-8")
    assert 'data-manual-legacy-authoring="2026-09-21"' in html
    assert 'data-manual-legacy-runbook="2026-09-21"' in html
    assert "ARM BUILD WRITES" in html
    assert "ARM ASSET DEPLOY" in html
    assert "docs/en/topics/LEGACY_MANAGEMENT_AUTHORING.md" in html


def test_supporting_manuals_no_longer_claim_server_is_unconditionally_read_only():
    security = (PROJECT / "docs" / "cobertura_funcional" / "SECURITY_SAFETY_1_0.md").read_text(encoding="utf-8")
    server = (PROJECT / "docs" / "cobertura_funcional" / "SERVER_ENRICHMENT_1_0.md").read_text(encoding="utf-8")
    assert "capability-scoped" in security
    assert "read-only por padrão" in server
    assert "Legacy Authoring" in security and "Legacy Authoring" in server
