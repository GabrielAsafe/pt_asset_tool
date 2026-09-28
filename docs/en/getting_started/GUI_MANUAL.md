# GUI Manual

## Navigation

The main navigation is organized by authority:

- **Catalog** — physical assets and per-asset capabilities.
- **Game Entities** — grouped relationships.
- **Client / Enrichment** — aggregate client diagnostics and global texture workflow.
- **Server / Enrichment** — server configuration, census, contracts, recovery evidence.
- **Legacy Management** — content authoring and local persistence administration.
- **Particles** — first-party `.part` editing and preview.
- **Compare** — read-only tree comparison.
- **General Jobs** — jobs without a dedicated workflow surface.
- **Reports** — existing artifacts under `pt_build`.
- **Help / Guides** — English operational guidance.
- **Settings** — resolved roots, dependencies, and integration status.

## Safety controls

The sidebar shows the current workspace/build arm state. Arming workspace/build only enables staged/generated writes. It does not authorize client/server publication.

Publication workflows use their own explicit confirmation and transaction gates.

## Catalog workflow

1. Filter or search the asset.
2. Select the row/card.
3. Review physical metadata, registry/binding, relationships, and evidence.
4. Choose only capabilities shown for that asset.
5. For build actions, arm workspace/build.
6. For publication, use the dedicated publish/restore workflow and review transaction output.

## Legacy authoring workflow

1. Choose Item, Monster, NPC, or Map/Field.
2. Choose Create/Edit.
3. Select a semantic catalog target when available.
4. Inspect or populate the source-backed spec.
5. Stage to `pt_build`.
6. Review the manifest.
7. Publish only with explicit deployment authorization.
8. Validate in-game.
9. Restore if runtime behavior is not acceptable.

## Semantic catalog behavior

Selectors show game display name plus stable identity information. The selected `canonical_id` is persisted as authoring provenance. Runtime code alone is not treated as unique when the catalog has multiple variants.

Ambiguous game display names are not silently resolved.

## Quarantine workflow

The UI/reporting surfaces quarantine evidence, but quarantine eligibility remains fail-closed. Q1 ranking is a review priority, not permission. Restore remains available for quarantined transactions.
