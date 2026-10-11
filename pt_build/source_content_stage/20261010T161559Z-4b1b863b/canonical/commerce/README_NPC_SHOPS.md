# NPC shops — canonical authoring

NPC definitions remain preserved under `Content/canonical/text/resources/Servidor/GameServer/NPC/`.
Do not edit their legacy payload just to change a shop inventory. Runtime shop adjustments live in
`Content/canonical/commerce/npc_shop_overrides.json`.

## Associate an existing item with a vendor

The item must already exist in both executable item profiles:

```bash
python3 tools/content_port/manage_npc_shop.py \
  --repo-root . \
  --npc npc.toolsric \
  --channel sell_etc \
  --add TW105
```

Use `sell_weapon`, `sell_defence`, or `sell_etc` according to the NPC's existing shop channel.
The command refuses an item that is missing from either client or server profile.

Preview without writing:

```bash
python3 tools/content_port/manage_npc_shop.py --repo-root . --npc npc.toolsric --channel sell_etc --add TW105 --dry-run
```

Remove/suppress a legacy shop entry without deleting it from the canonical NPC resource:

```bash
python3 tools/content_port/manage_npc_shop.py \
  --repo-root . \
  --npc npc.toolsric \
  --channel sell_etc \
  --remove TW106
```

## Diagnose shop items that do not load

```bash
python3 tools/content_port/validate_npc_shop_catalog.py --repo-root .
```

The validator resolves the effective inventory after overrides and requires every sold code to exist
in both `client.items.json` and `server.items.json`.

`build_from_canonical.py` runs this validator before compiling definition packs and applies the same
override file to both client and server packs.
