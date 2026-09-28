# Developer Manual

## Development rules

- Preserve fail-closed behavior.
- Do not silently upgrade review evidence into write/delete authority.
- Keep runtime/generated data out of the static package snapshot.
- Add tests for every new writer, safety gate, or mapping rule.
- Use exact typed/semantic identities instead of filename heuristics when a verified contract exists.
- Never make source/reference/donor presence an automatic runtime root unless the contract explicitly proves that semantics.

## UI

The first-party UI lives under:

```text
app/pt_asset_tool/ui_static/
```

User-facing API endpoints are implemented primarily in `ui_app.py` and supporting UI services. V2.10 uses English as the application language. Game display names from the semantic catalog remain source data and are not translated.

## Legacy Management

The promoted Legacy Management implementation is Python-first. Historical executable metadata remains evidence/provenance only.

Authoring writers operate on explicit specs and produce staged manifests. Publication consumes only a current staged manifest and performs safety checks again.

## Semantic authoring catalog

Packaged contract:

```text
app/pt_asset_tool/contracts/priston_asset_name_map_v1.json
```

Key rules:

- `canonical_id` is unique authoring identity.
- Display name is presentation/search data.
- Runtime code may be non-unique across semantic variants.
- Map relationships resolve to field/stage/spawn targets.
- Related Item/Mob/NPC references are persisted as semantic provenance.
- Ambiguity is surfaced instead of silently resolved.

## Retention and quarantine

Retention output is versioned. Quarantine commands must reject stale/incompatible plans. Physical moves verify hashes and preserve relative paths in a transaction journal. Restore rejects unsafe collisions/drift.

## Package integrity

Static package integrity is controlled by `SNAPSHOT_SHA256SUMS.txt` and `VERIFY_PACKAGE.sh`. Remove only reproducible caches before regenerating the snapshot; preserve user/runtime data.
