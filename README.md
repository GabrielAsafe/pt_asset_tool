# PT Asset Tool R14 1.0.0

PT Asset Tool is an evidence-driven Priston Tale asset and legacy-content engineering toolkit. It combines client inventory/inspection, server-aware enrichment, source-backed Legacy Management authoring, semantic name mapping, reversible quarantine, texture workflows, and transactional publication.

## Language

The first-party UI and default operational documentation are English as of V2.10.

Game display names stored in the semantic authoring catalog remain in their source game locale. Internal IDs, runtime codes, paths, hashes, and raw evidence are never translated.

English documentation starts at:

```text
docs/en/README.md
```

## Verify the package

```bash
./VERIFY_PACKAGE.sh
```

## CLI

```bash
cd app
python3 pt_asset.py --help
```

## UI

```bash
cd app
python3 pt_asset_gui.py
```

The UI is read-only by default. Workspace/build staging requires a temporary arm. Client/server publication uses separate explicit transactional authorization, hash preflight, backup, post-write verification, and restore/rollback.

## Dependencies

```bash
cd app
python3 pt_asset.py dependencies
```

## Runtime data

Generated/user runtime data belongs under `app/pt_build` and related local workspaces. Runtime data is excluded from the static package snapshot and must not be removed as part of normal release hygiene.

## Asset retention and quarantine

Retention distinguishes generic graph linkage from strong-root reachability. `ORPHAN_CANDIDATE` and Q1 review scores are not delete authority.

Quarantine remains reversible:

- Q0 — narrow documented-invalid zero-linkage orphans;
- Q1 — root-unreachable components ranked for review;
- manual Q1 component quarantine — exact component, strict eligibility, physical hashes, explicit confirmation, transactional restore.

There is no automatic delete authority.

## Semantic authoring catalog

Legacy Management packages a semantic catalog mapping game display names to stable internal identities for Item, Monster, NPC, and Map/Field authoring.

`canonical_id` is the primary authoring selection identity. Runtime codes remain format/runtime identities where required and may be shared by distinct semantic variants.

The map catalog resolves map identity to field/stage and SPM/SPP/SPC targets; related Item/Mob/NPC selectors preserve semantic provenance in authoring specs.
