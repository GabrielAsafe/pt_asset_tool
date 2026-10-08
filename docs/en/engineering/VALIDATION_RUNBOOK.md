# Validation Runbook

Use a clean worktree for release gates.

## Python syntax

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q pt_asset_tool
```

## Test suite

Use the environment Python selected by the project. The canonical test invocation includes:

```bash
PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q dev_tests tests
```

Focused suites may be run before the full regression, but they do not replace the release regression.

## JavaScript syntax

```bash
node --check app/pt_asset_tool/ui_static/app.js
```

## Documentation validation

The exhaustive runtime Python symbol reference is generated from the AST and must match the source. Regenerate it after intentional runtime Python changes, then validate:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 docs/validation/generate_source_api_reference.py
PYTHONDONTWRITEBYTECODE=1 python3 docs/validation/generate_source_api_reference.py --check
PYTHONDONTWRITEBYTECODE=1 python3 docs/validation/validate_documentation.py
```

## Release hygiene

Before snapshot generation remove only reproducible caches such as `__pycache__`, `.pytest_cache`, `.pyc`, and `.pyo`. Do not delete `app/pt_build` or user enhancement/quarantine data as part of development hygiene. A reproducible cleanup from the repository root is:

```bash
find app docs vendor -type d -name __pycache__ -prune -exec rm -rf {} +
find app docs vendor -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf .pytest_cache app/.pytest_cache
```

## Snapshot and package verification

Generate the source API reference first, clean reproducible caches, then regenerate the static snapshot. The snapshot must be the final derived file before package verification:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 docs/validation/generate_source_api_reference.py
PYTHONDONTWRITEBYTECODE=1 python3 docs/validation/generate_source_api_reference.py --check
PYTHONDONTWRITEBYTECODE=1 python3 app/update_snapshot_manifest.py --current-root .
PYTHONDONTWRITEBYTECODE=1 ./VERIFY_PACKAGE.sh
```

## Ready-to-deploy gate

When preparing a release commit, use the project `READY_TO_DEPLOY.py` workflow. It is responsible for reproducible-cache cleanup, tests, snapshot regeneration, package verification, staged diff checks, and commit preparation.
