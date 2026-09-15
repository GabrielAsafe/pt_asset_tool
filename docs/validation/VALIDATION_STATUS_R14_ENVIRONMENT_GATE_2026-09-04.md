# Validation status — R14 environment gate development — 2026-09-04

- `python3 -m compileall -q .`: PASS on the cumulative working tree.
- Non-`fixture_client` dev tests: 176/176 PASS in reproducible chunks (70 + 64 + 42).
- Focused environment/material/legacy/release tests: 40/40 PASS.
- Certified rare writer SHA-256 values unchanged:
  - `rare_rigid_edit.py`: `229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42`
  - `rare_rigid_multivertex.py`: `0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991`
  - `rare_rigid_multibone_bridge.py`: `010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0`
  - `rare_rigid_normal_bridge.py`: `67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96`

Additional cumulative fixes in this patch:
- Model0.62 material group `MaterialCount` read from the physical `+8` offset;
- conservative NUL-only terminal padding support for legacy serialized material strings;
- opaque final object-container suffix preserved byte-identically in the free-mesh writer;
- duplicate skeleton names collapse only when transform and parent are identical;
- Blender baked Actions use Fake User so inactive actions survive save/reopen;
- pose-space report diagnoses non-TRS source-basis mismatches separately from action persistence/evaluation failures.

No production/client-write authorization is added by this patch.
