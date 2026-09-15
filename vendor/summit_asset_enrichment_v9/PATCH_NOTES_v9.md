# Patch notes v9 — Fix 136

V9 closes two issues exposed by the real v8 run:

1. **Fighter TF26 WarCry donor alias**
   - `shared/skill.h` requests `TF26 WarCry(.bmp/_ .bmp)`.
   - Both principal donor trees expose the same Fighter TF26 slot as `TF26 Roar(.bmp/_ .bmp)`.
   - V9 treats only this exact slot/name as a structural alias. Fuzzy suggestions remain non-actionable.

2. **Shared runtime dependency collisions**
   - Different selected `.part` bundles may reference one runtime texture path but donor lineages may contain different bytes.
   - V8 could stage the first one and report `CONFLICT_STAGE` on the second.
   - V9 groups `STAGE_SAFE` rows by runtime destination before staging.
   - If a unique target-baseline hash exists, that hash wins globally for the shared runtime path.
   - If there is no unique baseline winner, the group is downgraded to `REVIEW`; staging order never decides silently.
   - New output: `fix136_runtime_collisions.csv`.

For the supplied v8 manifests this specifically addresses the divergent `Effect/Particle/flare.tga` references from `HolyValor.part` (old baseline) and `Ac5FierceWind.part` (PT_EU).
