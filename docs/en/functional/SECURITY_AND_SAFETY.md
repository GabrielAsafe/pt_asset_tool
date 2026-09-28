# Security and Safety

## Fail-closed rules

- Read-only is the default.
- Build/staging actions require an explicit temporary arm.
- Client/server publication requires separate authorization.
- Hash drift blocks unsafe reuse of plans/transactions.
- Missing or ambiguous evidence remains REVIEW/BLOCKED.
- Quarantine review scores never imply delete permission.
- Monster/NPC catalog/bundle protection remains conservative.

## No shell interpolation

User-facing actions use fixed command/operation allowlists. Paths and payloads are passed as data rather than arbitrary shell fragments.

## Backups and restore

Any promoted destructive/publishing operation must produce a backup or quarantine transaction sufficient for restore. Restore checks collisions/drift and does not silently overwrite unknown changes.
