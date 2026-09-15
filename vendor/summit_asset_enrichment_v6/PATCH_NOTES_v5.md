# PATCH NOTES v5

## What v4 proved
- 461 samples were collected.
- 47 INX files were classified: 36 MODERN_172, 11 LEGACY_120.
- 25 server character definitions were audited; 21 have the essential runtime visual chain INX -> SMD/SMB present in the v4 corpus.
- This is enough to stop random corpus growth and move to an authoring scaffold/validator.

## Fixes
1. `analyze_reverse_samples.py` now resolves `*link-file` / `.zhoon` relative to the directory of the `.NPC/.INF`, matching `GetDirectoryFromFile()` in `smCharDecode`. v4 falsely marked many present localization files as missing.
2. `collect_reverse_samples.py` now samples `.jpg`, `.jpeg`, and `.png` too. v4 already detected a real `houndD_opa.jpg` reference but did not include those extensions in the representative pool.
3. Added `character_bundle_tool.py`.

## Character bundle tool
The tool deliberately does **not** synthesize or rename INX/SMD/SMB binaries. Those stay on the already-certified PT Asset Tool path.

It can:
- clone a known-good `.NPC` or `.INF` server definition and patch the internal character name, model logical path, level, and linked `.zhoon` file;
- create Brazilian localization using `*J_NAME` / `*J_CHAT`;
- emit an SPM spawn fragment for monsters;
- emit an SPC placement request for NPCs (SPC write remains review/clone-based);
- validate the expected MODERN_172 INX, SMD/SMB dependencies, and embedded texture references on both Summit client and server roots.

## Important distinction
Missing authoring sources such as `.ASE`, `.INI`, and `.IN` are not automatically runtime defects. Current Summit runtime performs extension substitution (`.INI/.IN -> .INX`, INX `.ASE -> .SMD/.SMB`). Missing runtime `.INX/.SMD/.SMB` or referenced textures remains an actual gap.
