# Summit Canonical Source V2.12 — Extended Domains

V2.12 keeps `Content/canonical/**` as the only authoring authority and extends the PT Asset Tool to the Summit domains added after V2.11.

## New canonical domains

The Canonical Source panel and `pt_asset canonical domains` now expose:

- Coin/Time shop catalog (`COIN_SHOP_CATALOG`)
- NPC shop overrides (`NPC_SHOP_OVERRIDES`)
- Model configs (`MODEL_CONFIG`)
- Equipment sets (`EQUIPMENT_SETS`)
- Head cosmetics (`HEAD_COSMETICS`)
- World story campaigns (`WORLD_STORY`)
- World phases (`WORLD_PHASES`)
- Covenant altar placement (`COVENANT_ALTARS`)
- Experience balance (`EXPERIENCE_BALANCE`)

Typed staging uses the existing two-phase canonical publish transaction. Fixed documents retain an immutable schema identifier. Model configs may be resolved by canonical id or explicit path.

## Coin shop pack

When `canonical/commerce/coin_shop.json` exists, staged builds compile and inspect `coin_shop.scsp`. The pack participates in BUILD hash gating and canonical pack freshness. Mutable wallets remain server database state; the catalog and prices are canonical static content.

## Map model after the content-driven map fix

Field 53 is no longer a special read-only field. It may be an ordinary static map. The legacy/custom dynamic field follows the compiled catalog policy `append_after_static`, so a catalog with N static maps uses N as the dynamic field code. The PT Asset Tool no longer blocks editing a static field with code 53.

## Safety

The browser is read-only. Writes still require canonical staging, validation, compilation and explicit publish confirmation. Domains whose runtime milestone is not active can be authored and validated without implying that the game runtime consumes them yet.
