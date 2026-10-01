> **V2.11 canonical authority:** when `Content/CANONICAL_SOURCE.json` is configured, persistent Item/Monster/NPC/Field/Map authoring uses canonical JSON and rebuilt packs. Legacy content writers are import/diagnostic only.

# Feature Matrix

| Area | Read/Inspect | Stage/Build | Publish | Restore | Notes |
|---|---:|---:|---:|---:|---|
| Catalog / Entities | Yes | — | — | — | Read-only discovery/evidence |
| SMD/visual preview | Yes | Cache/build | — | — | Blender optional per capability |
| Texture enhancement | Yes | Yes | Explicit | Yes | Hash/backups/drift gates |
| General Census | Yes | Reports only | — | — | No automatic import |
| Asset retention | Yes | Reports only | — | — | No delete authority |
| Q0 quarantine | Yes | Plan | Explicit move | Yes | Narrow documented-invalid class |
| Q1 ranking | Yes | Plan | No batch move | — | Review priority only |
| Q1 manual component | Yes | Plan + hashes | Exact explicit component | Yes | Strict eligibility gate |
| Item authoring | Yes | Yes | Explicit | Yes | Existing verified runtime code |
| Monster authoring | Yes | Yes | Explicit | Yes | Source-backed writer |
| NPC authoring | Yes | Yes | Explicit | Yes | Source-backed writer |
| SPM/SPP/SPC authoring | Yes | Yes | Explicit | Yes | Server metadata, not Stage geometry |
| Character/account ops | Yes | Plan | Explicit apply | Backup/restore per operation | Local persistence contract |
| Postbox/inventory ops | Yes | Plan | Explicit apply | Backup/restore per operation | No arbitrary security-field edits |
| Particle `.part` | Yes | Draft | Controlled by workflow | Draft/source safety | First-party editor |
