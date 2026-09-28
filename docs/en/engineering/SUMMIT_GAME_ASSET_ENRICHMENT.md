# Summit Game Asset Enrichment

Asset Enrichment connects server definitions and client physical assets without collapsing them into one root.

## Monster

Typical evidence chain:

```text
Monster INF
→ ZHOON / logical model reference
→ INI/INX package identity
→ SMD/SMB
→ textures/materials
→ drops
→ SPM/spawn placement
```

## NPC

Typical evidence chain:

```text
NPC definition
→ visual/model package
→ dialogs/shops/quest or event references
→ SPC fixed placement when applicable
```

## Item

Typical evidence chain:

```text
OpenItem
→ runtime item code
→ semantic/catalog identity
→ inventory icon / drop model / equipped visual
→ monster drops / NPC shops / Postbox or gameplay references
```

## Field / Map

Typical evidence chain:

```text
map semantic identity
→ field/stage identity
→ SPM / SPP / SPC metadata
→ referenced Monsters/NPCs/items
```

Source/donor/reference roots provide recovery and contract evidence. They do not automatically become runtime roots or publish sources.
