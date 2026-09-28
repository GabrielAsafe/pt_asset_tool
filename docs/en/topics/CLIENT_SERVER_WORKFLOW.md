# Client / Server End-to-End Workflow

## Monster / NPC

```text
server definition
→ logical visual identity
→ INI/INX package
→ SMD/SMB/textures
→ spawn/placement
→ item/drop/shop relationships where applicable
```

## Field

```text
map/field identity
→ stage relationship
→ SPM actors/spawns
→ SPP start points
→ SPC fixed NPCs
```

## Item

```text
OpenItem
→ runtime code
→ semantic canonical_id
→ client inventory/drop/equipped visuals
→ drops/shops/Postbox/gameplay references
```

Use Client/Server Enrichment for evidence and Legacy Management for promoted authoring. Use Catalog/Entities for individual physical inspection.
