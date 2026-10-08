from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "docs"


def _text(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def test_validation_runbook_is_canonical_and_complete():
    text = _text("engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md")
    required = [
        "PYTHONDONTWRITEBYTECODE=1",
        "::test_realesrgan_discovers_bundled_binary",
        '"$PY" -m pytest -q dev_tests tests',
        "node --check pt_asset_tool/ui_static/app.js",
        "READY_TO_DEPLOY.py",
        "requirements-dev.txt",
        "compileall",
        "app/pt_build/texture_upscale/",
    ]
    for token in required:
        assert token in text, token


def test_operational_docs_reference_canonical_runbook():
    assert "en/engineering/VALIDATION_RUNBOOK.md" in _text("README.md")
    refs = [
        "engenharia/MANUAL_DESENVOLVEDOR.md",
        "comece_aqui/INSTALLATION_QUICKSTART_1_0.md",
        "comece_aqui/CLI_REFERENCE_1_0.md",
        "cobertura_funcional/TROUBLESHOOTING_1_0.md",
        "cobertura_funcional/SECURITY_SAFETY_1_0.md",
        "engenharia/SNAPSHOT_MANIFEST_POLICY.md",
    ]
    for rel in refs:
        assert "VALIDACAO_TESTES_DESENVOLVIMENTO.md" in _text(rel), rel


def test_no_literal_escaped_newlines_in_current_operational_docs():
    refs = [
        "comece_aqui/CLI_REFERENCE_1_0.md",
        "cobertura_funcional/FORMATS_WRITERS_1_0.md",
        "cobertura_funcional/TROUBLESHOOTING_1_0.md",
    ]
    for rel in refs:
        assert r"\\n##" not in _text(rel), rel


def test_texture_upscale_uses_canonical_runtime_root():
    refs = [
        "comece_aqui/CLI_REFERENCE_1_0.md",
        "tematicos/TEXTURE_UPSCALE_PIPELINE.md",
    ]
    for rel in refs:
        text = _text(rel)
        assert "app/pt_build/texture_upscale/" in text, rel
        assert "`enhancement/runs" not in text, rel
        assert "enhancement/transactions/" not in text, rel
        assert "enhancement/batches/" not in text, rel


def test_release_documents_are_explicitly_historical():
    for rel in [
        "release/RELEASE_1_READINESS.md",
        "release/RELEASE_1_CERTIFICATION.md",
        "release/FINAL_CERTIFICATION_EVIDENCE.md",
        "release/RELEASE_NOTES_1_0.md",
    ]:
        text = _text(rel)
        assert "PT_HISTORICAL_RELEASE_CONTEXT_2026-09-25" in text, rel
        assert "VALIDACAO_TESTES_DESENVOLVIMENTO.md" in text, rel


def test_source_api_reference_generation_is_not_ast_unparse_version_dependent(monkeypatch):
    import ast
    import importlib.util
    import sys

    module_path = DOCS / "validation" / "source_api_reference.py"
    name = "source_api_reference_version_gate"
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)

    def fail_unparse(*_args, **_kwargs):
        raise AssertionError("source API reference must not depend on ast.unparse")

    monkeypatch.setattr(ast, "unparse", fail_unparse)
    rendered = module.render_reference(ROOT.parent)
    assert rendered.startswith("# Source API Reference\n")
    assert "Source SHA-256" in rendered
