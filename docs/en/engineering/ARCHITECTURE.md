# Architecture

## Core principles

PT Asset Tool is evidence-driven and fail-closed.

- Client and Server are independent physical roots.
- Asset relationships may cross roots through typed contracts.
- Persistence, logs, security state, and operational databases are not promoted into the asset graph merely because they live under a server tree.
- Generated work stays under `app/pt_build` until an explicit transactional publication step.
- Legacy executables are reverse-engineering evidence, not runtime dependencies of the modern tool.

## Major layers

1. **Inventory / Catalog** — physical client files, metadata, previews, facets.
2. **Entity graph** — grouped Character/Item/Monster/NPC/Effect/Map relationships.
3. **Contract graph** — typed dependency evidence and source/runtime relationships.
4. **Client / Server enrichment** — aggregate diagnostics, census, recovery, reachability.
5. **Legacy Management** — source-backed authoring and local persistence ports.
6. **Semantic authoring catalog** — display-name → `canonical_id` / runtime identity / physical target mapping.
7. **Retention / quarantine** — root reachability, component review, reversible staging outside the runtime client.
8. **Transactional deployment** — preflight, backup, hash verification, atomic replacement, restore.

## Root reachability

Strong roots are the only runtime roots for retention traversal. A generic ContractGraph edge is positive linkage evidence but is not sufficient runtime protection by itself. Entity/catalog fail-closed rules are stronger where required, especially for Monster/NPC bundles.

## Authoring identity

`canonical_id` is the primary semantic authoring identity. Runtime codes remain format identities where required. This prevents collisions where multiple authored definitions share a runtime code.
