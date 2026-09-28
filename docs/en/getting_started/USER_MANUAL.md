# User Manual

PT Asset Tool combines client asset inspection, server-aware enrichment, semantic authoring, validation, reversible quarantine, and transactional publication.

## 1. Safety model

The application is read-only by default. There are three distinct levels of authority:

1. **Read / inspect** — catalog, entity graph, reports, census, diagnostics.
2. **Workspace/build writes** — staging and generated outputs under `app/pt_build`; these require the workspace/build arm.
3. **Client/server publication** — separate explicit authorization, hash preflight, backup, atomic replacement, post-write verification, and restore/rollback support.

A report state such as `REVIEW`, `ORPHAN_CANDIDATE`, `Q1_PRIORITY_A_REVIEW`, or a high review score is not delete authority.

## 2. Catalog

Use **Catalog** to locate a physical client asset. Filter by category, entity, character, folder, role, extension, preview status, and favorites.

For a selected asset the detail panel can show:

- physical path and size;
- registry family/kind/binding;
- related assets;
- item visual bundle;
- SMD preview status;
- applicable contract candidates;
- supported actions and safety requirements;
- roundtrip/enhancement state.

## 3. Game Entities

Use **Game Entities** to inspect grouped Character, Item, Monster, NPC, Effect, and Map/Field relationships. Entity grouping is evidence, not writer authority. A physical relationship does not automatically prove runtime reachability.

## 4. Client / Enrichment

Use this workflow for aggregate client diagnostics:

- inventory/reindex handoff;
- client-side enrichment analysis;
- General Census projection for client assets;
- retention/reachability review;
- global texture enhancement batch;
- activity and result tracking.

For an individual asset, hand off to **Catalog**. For physical relationships, hand off to **Game Entities**.

## 5. Server / Enrichment

Use this workflow to configure and inspect the Summit server side:

- server root;
- Summit source root;
- reference source root;
- donor roots;
- environment diagnostics;
- server inventory;
- General Census and recovery evidence;
- contract registry and dependency graph;
- retention projection.

This workflow is analysis-oriented. Content editing belongs to **Legacy Management**.

## 6. Legacy Management

Legacy Management replaces dependence on historical executables with source-backed Python contracts and writers.

### Item

- Look up the runtime code first.
- Use the semantic catalog to choose the intended `canonical_id`.
- Create/edit an OpenItem definition only when the runtime code is already source-verified.
- New `sITEM` runtime-code registration remains outside the promoted writer.

### Monster

- Create/edit Monster INF definitions.
- Manage stats, EXP, money/drop directives, dialogs, and linked visual metadata where supported.
- Related items are selected through the semantic item catalog.
- Bulk EXP and Gold workflows are preview/stage-first.

### NPC

- Create/edit NPC definitions and supported shop/dialog fields.
- Related shop items are selected through the semantic item catalog.
- Fixed placement belongs to SPC.

### Map / Field

The semantic map catalog resolves a human-facing map name to its field/stage identity and SPM/SPP/SPC targets.

- **SPM** — actors/spawns/boss/directives.
- **SPP** — canonical start-point records.
- **SPC** — canonical fixed-NPC records.

This does not create Stage0.72 client geometry.

### Character / Account

Inspect is read-only. Supported Level/XP, primary-stat, rename, migration, and restore operations produce a reviewable persisted plan before any write.

### Items / Postbox

Postbox distribution, duplicate detection, slot inspection, and proven slot removal are plan-first. Arbitrary edits to security/checksum identifiers are not exposed.

### Local Admin

SoD, BPRank, account protection, Hotuk configuration, and server-supervisor workflows use detected local SQLite/config contracts. They do not assume SQL Server/ODBC.

### World Closure

World Closure cross-references Field/SPM → Monster/NPC → item code → OpenItem → runtime item identity → client visual assets. A `REVIEW` row explains what is missing and can explicitly hand off to the correct authoring task.

## 7. Semantic Authoring Catalog

The V2.9+ catalog maps game display names to stable authoring identities.

Primary identity:

```text
canonical_id
```

Additional fields may include:

```text
display_name
internal_name
runtime code
asset path
model file
map/stage/spawn target
confidence
```

Do not collapse two definitions only because they share a runtime code. The semantic catalog intentionally distinguishes variants by `canonical_id`.

Game display names remain in their source locale. UI labels and documentation are English.

## 8. Asset retention and quarantine

Retention separates graph linkage from strong-root reachability. An edge alone is not runtime proof.

- `PROTECTED_*` — positive protection evidence.
- `REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE` — graph-linked but not reached by a trusted root.
- `ORPHAN_CANDIDATE` — no known linkage/root evidence; still not delete authority.

Quarantine is reversible and auditable:

- Q0 handles a very narrow class of documented-invalid, zero-linkage orphans.
- Q1 review ranks root-unreachable components.
- Manual Q1 component quarantine requires an exact component, strict eligibility gates, physical hashes, and explicit confirmation.
- There is no automatic delete path.

## 9. Particles

The `.part` editor is first-party and integrated into the main UI. Draft edits remain staged. Semantic preview planning does not require Blender; visual rendering uses the configured Blender runtime when requested.

## 10. Tree comparison

Compare two asset trees by relative path/size and optionally SHA-256. Comparison is read-only and exports reports under `pt_build`.

## 11. Reports and jobs

Workflows with dedicated pages keep their activity/result history on those pages. General Jobs contains operations without a dedicated surface. Reports reads existing artifacts and does not silently rerun expensive analyses.

## 12. Interpreting states

- `PASS` — the executed gate passed.
- `REVIEW` — useful evidence exists, but a human/contract decision is still required.
- `BLOCKED` — a required contract/dependency/safety condition is not satisfied.
- `NOT_RUN` — the gate has not been executed.
- `RUNTIME_REVIEW_PENDING` — automated checks passed but in-game behavior still needs validation.

Never reinterpret a diagnostic status as deletion or publication authority.
