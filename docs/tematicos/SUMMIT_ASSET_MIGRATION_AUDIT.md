# Summit canonical asset migration audit

This integration makes `SourceCode/Content/canonical/**/*.json` a first-class evidence source for PT Asset Tool retention audits and adds a migration-gap report for asset/UI hardcodes that still live in C/C++.

## Safety model

The audit is read-only. It does not move, quarantine, delete, recook, or publish client assets.

Canonical JSON is treated conservatively:

- explicit client runtime fields (`runtime_paths`, `model_file`, texture/image/effect/audio/asset fields) become strong retention roots;
- report/provenance/server paths remain review evidence;
- source-only asset literals remain protected and are queued for migration, never classified as disposable merely because they are not canonical yet;
- quarantine authority remains in the existing retention/quarantine gates.

## Audits

From `app/`:

```bash
python3 pt_asset.py audit summit-canonical-assets \
  --source-root "/home/gabriel/Área de Trabalho/summit/SourceCode"
```

This writes:

```text
pt_build/summit_asset_migration/canonical_asset_relations.json
pt_build/summit_asset_migration/canonical_asset_relations.tsv
```

Then run the migration-gap audit:

```bash
python3 pt_asset.py audit summit-asset-migration \
  --source-root "/home/gabriel/Área de Trabalho/summit/SourceCode"
```

It writes:

```text
pt_build/summit_asset_migration/result.json
pt_build/summit_asset_migration/source_asset_literals.tsv
pt_build/summit_asset_migration/migration_queue.tsv
pt_build/summit_asset_migration/ui_text_candidates.tsv
pt_build/summit_asset_migration/runtime_cook_plan.tsv
pt_build/summit_asset_migration/runtime_cook_plan.json
```

Finally rerun the normal retention/quarantine planning. `asset-retention` now imports canonical client roots automatically:

```bash
python3 pt_asset.py audit asset-retention \
  --source-root "/home/gabriel/Área de Trabalho/summit/SourceCode"

python3 pt_asset.py audit quarantine-plan
```

## Migration queue

Priority is intentionally operational:

- `P0` — runtime/canonical asset missing physically, especially effect-loader roots. Release blocker until explained or restored.
- `P1` — source-only runtime asset that exists. Migrate the relation to canonical JSON before removing the hardcode.
- `P2` — canonical review-only or lower-confidence source-only relation. Inspect and migrate when ownership is proven.
- `P4` — already covered by canonical authority; kept in the full literal report for traceability.

Important states:

- `CANONICAL_COVERED`
- `CANONICAL_REVIEW_ONLY`
- `SOURCE_ONLY_PRESENT`
- `SOURCE_ONLY_MISSING`
- `CANONICAL_RUNTIME_ASSET_MISSING`

## UI migration

`ui_text_candidates.tsv` is deliberately review-only. It scans UI-oriented source files for human-readable string literals so UI text/config can be moved to canonical JSON/localization incrementally. It never edits source automatically.

UI asset paths are also present in `migration_queue.tsv` with scope `UI`.

## Cook/distribution plan

`runtime_cook_plan` does not change the runtime yet. It defines the required distribution closure:

- BMP/TGA/PNG/JPG/JPEG => `DDS_COOK_REQUIRED`, `DDS_COOK_OK`, or explicit cooker review;
- existing DDS => `COPY_AS_IS_NATIVE_DDS`;
- INI/PART/SMD/SMB/ASE/INX/WAV/etc. => `COPY_AS_IS_TO_COOKED_RUNTIME`.

This is the input for the next packaging step: a deterministic cooked runtime tree containing every required effect/model/audio/config dependency, while the source tree remains authoring authority.

Do not remove original assets until the runtime/package path is proven in an acceptance build. The current audit only creates evidence and a plan.
