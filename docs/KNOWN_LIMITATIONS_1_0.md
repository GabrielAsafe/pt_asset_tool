# PT Asset Tool R14 1.0.0 — Known Limitations

These are limitations of the current target/content or intentionally excluded product scope. They do not represent hidden automatic tool blockers.

## Expected texture-path gaps

The FIX23 diagnostic recorded 15 unique expected paths. The final Model0.62 audit still reports strict status `FAIL` and failure_count `19`.

- `char/tmABCD/LLhead.tga`
- `char/tmABCD/TfhD02b.bmp`
- `char/tmABCD/hair06_yun.tga`
- `Effect/Sky/losttemple/day/space.bmp`
- `Effect/Sky/Sky08/day/02dayhill.TGA`
- `image/Sinimage/AssaEffect/TwistJavelin/fire01_01.bmp`
- `field/forest/07-g9 copy.bmp`
- `char/monster/d_kn/MMHA02.BMP`
- `char/monster/Kakoa/Kakoa_BB copy.tga`
- `char/monster/Monhobgoblin/hobgoblin-w01.bmp`
- `Char/Monster/Monrebion/Mon-Rebion-1.bmp`
- `char/monster/RibbonHopy/Packjjangpy.tga`
- `char/npc/TN-017/______--a.jpg`
- `StartImage/Opening/npc/mm.bmp`
- `Effect/AssaEffect/Skill3Mesh/itws213.TGA`

Four casefold-exact PT_EU donor candidates were diagnostic-only; no automatic write was authorized. Basename hints are not recovery authority.

## Invalid target TGA payloads

- `Field/Ricarten/ch_tree1.tga`: HTML/IIS 404 document stored under a `.tga` path.
- `Effect/AssaEffect/MonsterFury/m_fury.tga`: zero-filled payload.

The codec corpus classifies these structurally as target-content invalid. Codec failure count remains `0`.

## Out of scope

- Mixed Physique physical certification: `NOT_CERTIFIED / OUT_OF_SCOPE`; preserved fail-closed for post-1.0 work.
- Legacy game/runtime Tier 1–4 behavior is not a PT Asset Tool 1.0 release gate.
- Assassin/Shaman remain outside the eight-active-class 1.0 line.

## Production writes

The release package is safety-locked. Production writer promotion and publish/restore require an explicit operational action and are not enabled by the version bump.
