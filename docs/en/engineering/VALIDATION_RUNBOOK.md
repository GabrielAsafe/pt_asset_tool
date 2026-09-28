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

```bash
python3 docs/validation/validate_documentation.py
```

## Release hygiene

Before snapshot generation remove only reproducible caches such as `__pycache__`, `.pytest_cache`, `.pyc`, and `.pyo`. Do not delete `app/pt_build` or user enhancement/quarantine data as part of development hygiene.

## Snapshot and package verification

Regenerate the static snapshot with the project snapshot tool, then run:

```bash
./VERIFY_PACKAGE.sh
```

## Ready-to-deploy gate

When preparing a release commit, use the project `READY_TO_DEPLOY.py` workflow. It is responsible for reproducible-cache cleanup, tests, snapshot regeneration, package verification, staged diff checks, and commit preparation.
