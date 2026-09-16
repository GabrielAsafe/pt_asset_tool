# PT Asset Tool R14 — T1–T4 Regression + Class UI Alias Audit

> **Policy update — 2026-09-14:** the project intentionally migrated the active Mechanician skill-UI root to `image/Sinimage/skill/Mechanician`, and the current source follows that root. The historical `Mecha` findings below are retained as audit history only. `Mecha` is now ignored legacy and is not a runtime/write source.


Date: 2026-09-14  
Product line: PT Asset Tool R14 / 0.13.0  
Status after policy update: **PRE-1.0 BLOCKED — runtime regression remains; UI alias split closed by project migration**

## Scope

This audit was triggered after a real manual smoke reported that Pikeman Tier 1–4 skills no longer showed their expected animation/audio/effects. The audit also reviews the current client tree split between:

- `image/Sinimage/skill/Mecha`
- `image/Sinimage/skill/Mechanician`

The historical Summit source archive supplied for comparison is `Source Summit Tale.rar`.

No client/server files are written by this report or by the new PT Asset Tool alias audit.

## Executive result

There are four distinct defects/risks. They must not be conflated.

| ID | Finding | Classification | Release impact |
|---|---|---|---|
| RUNTIME-PK-T1T4-01 | Pikeman T1–T4 have a broad runtime regression despite source handlers and physical assets still being present | **CONFIRMED RUNTIME DEFECT; root cause not yet isolated** | **BLOCKER** |
| UI-ALIAS-MECHA-01 | Historical `Mecha`/`Mechanician` split | **CLOSED BY PROJECT POLICY** — current source/UI root is `Mechanician`; `Mecha` is ignored legacy | **NOT A CURRENT RELEASE BLOCKER** |
| T5-FIX15-01 | FIX15 placed Rupture audio outside the PT-EU MotionEvent timing model | **CONFIRMED PATCH DEFECT** | revert/hold until baseline is stable |
| DOC-READINESS-01 | Pre-1.0 docs still said “final manual smoke pending/ready” after a real smoke exposed a regression | **CONFIRMED DOCUMENTATION/RELEASE-GATE DEFECT** | **BLOCKER** |

## Current disposition of the UI-root finding

The original analysis below is retained as historical evidence. The active project policy now supersedes it:

- canonical runtime/UI root: `image/Sinimage/skill/Mechanician`;
- historical `image/Sinimage/skill/Mecha`: ignored legacy;
- no automatic copy, delete or conflict resolution uses `Mecha`;
- `wav/Effects/player/Mechanician` remains valid player audio and unrelated to the skill-UI root decision.

## 1. Pikeman Tier 1–4: what did and did not change

### 1.1 Historical source files

The original archive contains the legacy implementation at the historical flat paths:

- `SrcGame/src/SkillSub.cpp`
- `SrcGame/src/character.cpp`
- `SrcGame/src/effectsnd.cpp`
- `SrcGame/src/sinbaram/sinSkill.cpp`
- `SrcGame/src/sinbaram/sinSkillEffect.cpp`

Historical SHA-256 witnesses extracted from the supplied RAR:

- `SkillSub.cpp`: `09ce0d342d1b0a3497c03d7b56362f92b4fb7da0f7b376257d011dce5531ef2b`
- `character.cpp`: `1f54dd47cb9ac85332a178312cab2bed81480064f79bbc9091fb1ed49dd5a01b`
- `effectsnd.cpp`: `99cef70e82afed44a2b9f41f03f5b09972a8f2a2fa3e88e53edfbd295d4a2a91`

### 1.2 `SkillSub` preservation

The current pre-FIX15 implementation was collected from:

`Shared/gameplay/skills/SkillSub_legacy_client.inl`

with SHA-256:

`e021e2c8e48700dd16103187eb67d01877d785a607f7462518966e5b448595a1`

After normalizing whitespace/include relocation/path separators, the historical `SkillSub.cpp` is preserved in the current file **in order, with no delete/replace opcode in the comparison**. The differences are insertions, principally the Summit T5 bridge/probe code.

This means the old T1–T4 `SkillSub` behavior was not wholesale removed by the T5 integration.

### 1.3 `effectsnd` preservation before FIX15

The historical and current pre-FIX15 `SkillSoundWav[]` tables both contain **183 mappings**.

Comparison result:

- removed sound-code mappings: **0**
- added mappings: **0**
- changed code→path mappings: **0**

Therefore the T1–T4 sound catalog itself was intact before FIX15.

FIX15 appended three T5 entries (`0x4855`, `0x4856`, `0x4857`) after the legacy entries; it did not reorder the 183 historical entries. This does **not** explain a global disappearance of Pikeman T1–T4 animation/effect behavior.

### 1.4 Current character dispatcher landmarks

The current refactored runtime still exposes the same Pikeman legacy case landmarks in `Shared/gameplay/character/character_legacy_client.inl`. The observed source-line shift is consistently six lines versus the historical `character.cpp`, for example:

- `SKILL_PLAY_PIKEWIND`: historical 13940 → current 13934
- `SKILL_PLAY_GROUND_PIKE`: historical 14063 → current 14057
- `SKILL_PLAY_EXPANSION`: historical 14075 → current 14069
- `SKILL_PLAY_TORNADO`: historical 14090 → current 14084
- `SKILL_PLAY_VANISH`: historical 14136 → current 14130
- `SKILL_PLAY_CHAIN_LANCE`: historical 14150 → current 14144
- `SKILL_PLAY_ASSASSIN_EYE`: historical 15219 → current 15213
- `SKILL_PLAY_CHARGING_STRIKE`: historical 15226 → current 15220

The collected current source also still contains the legacy `SkillPlaySound`, `StartSkill`, particle and MotionEvent calls around these cases.

**Conclusion:** the broad Pikeman T1–T4 failure is not supported as an asset-deletion defect or a wholesale handler deletion. The next runtime investigation belongs at the routing boundary: whether the built executable reaches `PlaySkillAttack` / `smCHAR::PlayAttack`, whether `AttackSkil` is populated with the expected legacy code, and whether the expected refactored source is actually part of the binary being tested.

## 2. Pikeman assets are physically present

The current client tree contains the legacy sound/effect families expected by the historical source, including examples:

- `wav/Effects/Skill/Tempskron/Pike_Wind 01.wav`
- `wav/Effects/Skill/Tempskron/Ground Pike 01.wav`
- `wav/Effects/Skill/Tempskron/Tornado 01.wav`
- `wav/Effects/Skill/Tempskron/Expansion 01.wav`
- `wav/Effects/Skill/Tempskron/Expansion 02.wav`
- `wav/Effects/Skill/Tempskron/RoZ 01.wav` … `RoZ 04.wav`
- `wav/Effects/Skill/Tempskron/vanish 01.wav`
- `wav/Effects/Skill/Tempskron/vanish 02.wav`
- `wav/Effects/Skill/Tempskron/ChainLance 01.wav` … `03.wav`
- `wav/Effects/Skill/Tempskron/VenomSpear 01.wav` / `02.wav`
- `wav/Effects/Skill/Tempskron/AssassinEye 01.wav`
- `wav/Effects/Skill/Tempskron/ChargingStrike 03.wav`
- `wav/Effects/Skill/Tempskron/vague 01.wav`
- `Effect/Particle/Script/Skill3PikeVanish1.part`
- `Effect/Particle/Script/Skill3PikeManVenomSpear.part`
- `Effect/Particle/Script/Skill3PikeManVenomSpear1.part`
- `Effect/AnimationData/GroundPike.ini`
- `Effect/ObjAnimationData/PikeWind/bong.smd`

This does not prove every animation dependency is valid, but it rules out the simple explanation “the Pike T1–T4 assets are all missing”.

## 3. `Mecha` vs `Mechanician`: confirmed UI root split

### 3.1 Historical canonical paths

Historical Summit source:

- Skill UI base: `Image\\SinImage\\Skill\\Mecha\\`
- Character/player audio base: `wav\\Effects\\player\\Mechanician\\`

These are two different content domains. The word `Mechanician` is historically valid for player audio; it is **not** evidence that `image/Sinimage/skill/Mechanician` should be a second skill-UI root.

### 3.2 Current target tree

For skill UI only:

- `image/Sinimage/skill/Mecha`: **48 files**
- `image/Sinimage/skill/Mechanician`: **40 files**
- same relative names present in both: **32**
- only in canonical `Mecha`: **16**
- only in alias `Mechanician`: **8**

The split is highly structured:

- `Mecha` contains the historical UI, Tier 1–4 content and JobTitle assets;
- `Mechanician` duplicates 32 older files and contains the eight T5 button images exclusively (`TM100`, `TM103`, `TM106`, `TM110`, normal + hover).

This is a real asset-layout defect. The canonical skill UI root should remain **`Mecha`** unless source evidence proves a deliberate migration. The eight T5 icons should ultimately live under the same canonical root. Duplicate/conflicting alias cleanup must be separately certified; it is not authorized merely by this audit.

### 3.3 Existing PT Asset Tool evidence

The pre-1.0 staging overlay already targets the eight T5 files at:

`image/Sinimage/skill/Mecha/Button/...`

That is consistent with the historical source. The problem is that the target client tree still contains the split alias root, and the tool previously lacked a dedicated gate to flag it.

## 4. FIX15/FIX16 disposition

FIX15 is not accepted as a stable baseline.

Confirmed issue: PT-EU Rupture plays `0x4855` on MotionEvent 1 and `0x4856` on MotionEvent 3. FIX15 initially placed those calls in the T5 cast/damage path instead of the character MotionEvent dispatcher.

FIX16 was prepared to move the Rupture calls to MotionEvent timing, but **do not continue applying T5 source patches while the T1–T4 regression is unresolved**. First restore a clean pre-FIX15 source baseline and reproduce the legacy skill issue independently.

The backup produced by the executed FIX15 was:

`/home/gabriel/Área de Trabalho/summit/SourceCode/.pt_t5_av_patch_backups/20260914_083426`

At minimum, restore the two FIX15-modified files before the next baseline smoke if they have not subsequently been intentionally changed:

- `Shared/gameplay/skills/SkillSub_legacy_client.inl`
- `SrcGame/src/systems/audio/effects/legacy/effectsnd.cpp`

Do not apply FIX16 until this baseline test is complete.

## 5. Bugs to correct in PT Asset Tool

### UI-ALIAS-MECHA-01 — class UI alias audit

**Fixed in the current development working tree.**

New read-only audit:

`audit class-ui-aliases`

It treats:

- canonical: `image/Sinimage/skill/Mecha`
- alias under review: `image/Sinimage/skill/Mechanician`

It reports:

- canonical-only files;
- alias-only files;
- byte-identical duplicates;
- hash conflicts;
- canonical target recommendation for alias-only files.

It never copies, deletes, moves or renames target files.

The general asset census now includes the alias audit and packages it as:

`general_asset_census/class_ui_alias_audit.json`

The web UI summary now exposes class-UI alias state, split-group count, alias-only count and conflicts.

### DOC-READINESS-01 — stale release readiness

**Corrected in documentation in this working tree.**

0.13.0 is no longer described as ready for a final manual smoke. The current state is blocked by the newly observed runtime regression and the UI alias split.

### Missing product gate identified

The final 1.0 gate must now require:

1. class UI alias audit = `CANONICAL` (or an explicitly accepted documented exception);
2. no unresolved target duplicate/conflict in class UI roots;
3. legacy T1–T4 manual smoke pass after a clean source baseline build;
4. then T5 audiovisual work may resume.

## 6. Recommended next sequence

1. Freeze T5 source changes; do not apply FIX16.
2. Restore the pre-FIX15 backup so the next runtime smoke is clean.
3. Rebuild the client.
4. Test one Pikeman active skill from each legacy tier and record whether the animation begins at all. If all four fail, instrument/trace the routing boundary, not the asset filesystem.
5. Run PT Asset Tool `audit class-ui-aliases` on the live client and keep the result with the release evidence.
6. Correct/certify the `Mecha` UI consolidation separately; do not touch `wav/Effects/player/Mechanician`.
7. Resume final UI/assets documentation and release gates only after the legacy smoke is green.

## Safety status

- Client write authorized by new alias audit: **NO**
- Alias deletion/move authorized: **NO**
- Server write authorized: **NO**
- T1–T4 donor recopy justified by this analysis: **NO**
- Release 1.0 ready: **NO**
