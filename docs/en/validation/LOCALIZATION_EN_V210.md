# English Localization Validation — V2.10

## Scope

V2.10 localizes the first-party PT Asset Tool web UI and makes the English documentation tree under `docs/en/` the default operator/developer documentation surface.

The localization boundary intentionally excludes data that participates in game/runtime identity:

- semantic catalog `display_name` values sourced from the game localization;
- `canonical_id`, runtime item codes, file paths, hashes, evidence tokens, and raw source excerpts;
- historical Portuguese documentation retained outside `docs/en/` for provenance and compatibility.

## Automated gates

```bash
python3 docs/validation/validate_english_localization.py
python3 -m pytest -q app/dev_tests/test_english_localization.py
node --check app/pt_asset_tool/ui_static/app.js
```

The localization gate verifies:

1. HTML declares `lang="en"`.
2. Known Portuguese application-chrome phrases are absent from the first-party static UI and selected UI backend surfaces.
3. Required English operator/developer documents exist.
4. `docs/README.md` points to `docs/en/` as the default documentation tree.
5. Source-locale semantic game names remain unchanged contract data.

## Safety

V2.10 does not expand write, quarantine, or delete authority. Existing workspace/build arms, transactional client/server publication, hash preflight, backup, drift checks, quarantine restore, and fail-closed retention rules are unchanged.
