from __future__ import annotations

# Release 1.0 scope policy.
# Mixed-Physique tooling remains preserved for post-1.0 work, but physical
# certification/support is explicitly outside the 1.0 support claim.
MIXED_PHYSIQUE_RELEASE_1_SCOPE = "OUT_OF_SCOPE_NOT_CERTIFIED"
MIXED_PHYSIQUE_RELEASE_1_BLOCKING = False
MIXED_PHYSIQUE_POST_1_0_BACKLOG = True

# Game/runtime behavior outside the PT Asset Tool itself is explicitly out of scope
# for the 1.0 product gate. The tool may report runtime observations as external
# evidence, but they do not block the asset-tool release.
LEGACY_GAME_RUNTIME_RELEASE_1_SCOPE = "OUT_OF_SCOPE_EXTERNAL_GAME_RUNTIME"
LEGACY_GAME_RUNTIME_RELEASE_1_BLOCKING = False
LEGACY_GAME_RUNTIME_POST_1_0_TRACKING = True
