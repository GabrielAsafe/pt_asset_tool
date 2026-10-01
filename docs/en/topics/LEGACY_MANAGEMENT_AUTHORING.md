> **Canonical-mode change (V2.11):** legacy definition/SPM/SPP/SPC writers are inspect/import/compare-only when a valid Summit canonical source is configured. Persistent content authoring is staged against `Content/canonical/**` and rebuilt packs.

# Legacy Management Authoring

Legacy Management provides first-party Python workflows for server content and local persistence operations that historically depended on external management executables.

## Historical executables

Historical executables are static reverse-engineering evidence only. Supported modern operations do not require launching them.

## World Closure

World Closure is the discovery/review surface. It resolves chains among Fields/SPM, Monsters/NPCs, item codes, OpenItem definitions, runtime item identities, and client visual assets.

Selecting a row does not silently change task or open an editor. An explicit review action hands off to Item/Monster/NPC/Map authoring when a target is proven.

## Item authoring

Create/Edit uses OpenItem contracts. CREATE is limited to runtime item codes already proven in the source-verified runtime catalog. The semantic catalog selects variants by `canonical_id`.

## Monster authoring

Supported fields include the promoted Monster definition contract, drops/money/extra drops, dialogs, and linked-file metadata where implemented. Related items use the semantic catalog.

Bulk EXP/Gold workflows calculate a preview first, then stage reviewable bundles under `pt_build`.

## NPC authoring

NPC definitions support promoted fields, dialogs, and shops. Fixed placement uses SPC. Related item references preserve semantic provenance.

## Map / Field authoring

Map selection can use the semantic catalog to resolve human-facing map identity to SPM/SPP/SPC targets. SPM uses related mob selection; SPC uses related NPC selection.

SPM/SPP/SPC editing does not create the visual Stage geometry on the client.

## Stage / publish / restore

The common workflow is:

```text
select target
→ inspect/create
→ stage to pt_build
→ review manifest
→ arm deployment
→ publish with preflight/backup/verify
→ validate in-game
→ restore if needed
```

The current staged manifest is required for publish. External drift blocks unsafe restore/publish.
