# RC6.15 Asset Contracts Integration

Source: PT Asset Tool 0.17.1 Documentation Handoff FULL.

Integrated selectively into the certified RC6.14 line.

## Imported
- source evidence/catalog/census
- contract graph
- player-class skill/motion contracts
- player-class aggregation
- client/server/summit superset aggregation
- CLI and GUI configuration/endpoints

## Explicitly not overwritten from 0.17.1
- registry / rigid binding implementation
- rigid authoring implementation
- release gate implementation
- Mixed Physique scope policy
- TGA494 policy

The active product version remains 0.13.0 / NOT Release 1.0 until final promotion.
All aggregation is staging-only under app/pt_build; real client/server are read-only.
