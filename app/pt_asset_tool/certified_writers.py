from __future__ import annotations

"""Single source of truth for certified writer integrity hashes.

The hashes below identify the writer sources shipped by this package revision.
They are intentionally kept outside generated state so runtime/config cleanup can
never silently redefine what constitutes a certified writer.
"""

CERTIFIED_WRITERS = {
    "pt_asset_tool/rare_rigid_edit.py": "3ff2769bbc9762c04fb992fbad52ba7d60ae6a53f19c22d4f1d68e274697eec3",
    "pt_asset_tool/rare_rigid_multivertex.py": "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991",
    "pt_asset_tool/rare_rigid_multibone_bridge.py": "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0",
    "pt_asset_tool/rare_rigid_normal_bridge.py": "2c0f75931e54a72cd87be2bc6694370f849c24c3f2b4b44afbdbc288dcaf622c",
}
