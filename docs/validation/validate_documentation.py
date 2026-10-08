#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
CURRENT = [p for p in DOCS.rglob("*.md") if "docs/validation/" not in p.as_posix()]
errors: list[str] = []

for path in CURRENT:
    text = path.read_text(encoding="utf-8", errors="replace")
    if r"\\n##" in text:
        errors.append(f"literal escaped newline before heading: {path.relative_to(ROOT)}")


# The exhaustive maintained first-party Python symbol reference is generated from the source AST.
# This turns documentation drift into a validation failure instead of relying on
# a hand-maintained list of selected public symbols.
try:
    from source_api_reference import REFERENCE as SOURCE_API_REFERENCE, render_reference
    expected_reference = render_reference(ROOT)
    if not SOURCE_API_REFERENCE.is_file():
        errors.append(f"missing source API reference: {SOURCE_API_REFERENCE.relative_to(ROOT)}")
    elif SOURCE_API_REFERENCE.read_text(encoding="utf-8") != expected_reference:
        errors.append(f"stale source API reference: {SOURCE_API_REFERENCE.relative_to(ROOT)}")
except Exception as exc:
    errors.append(f"source API reference validation failed: {type(exc).__name__}:{exc}")

for rel in ["comece_aqui/CLI_REFERENCE_1_0.md", "tematicos/TEXTURE_UPSCALE_PIPELINE.md"]:
    path = DOCS / rel
    if not path.is_file():
        errors.append(f"missing operational doc: docs/{rel}")
        continue
    text = path.read_text(encoding="utf-8")
    for legacy in ("`enhancement/runs", "enhancement/transactions/", "enhancement/batches/"):
        if legacy in text:
            errors.append(f"legacy texture runtime path {legacy!r}: docs/{rel}")

runbook = DOCS / "engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md"
if not runbook.is_file():
    errors.append("missing canonical validation runbook")
else:
    text = runbook.read_text(encoding="utf-8")
    for token in ("PYTHONDONTWRITEBYTECODE=1", '"$PY" -m pytest -q dev_tests tests', "READY_TO_DEPLOY.py"):
        if token not in text:
            errors.append(f"runbook missing token: {token}")

print(f"DOC_AUDIT files={len(CURRENT)} errors={len(errors)}")
for e in errors:
    print(f"ERROR {e}")
raise SystemExit(1 if errors else 0)
