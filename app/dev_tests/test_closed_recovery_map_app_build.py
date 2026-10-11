from __future__ import annotations

import json

import pt_asset_tool.donor_recovery_explorer as dre


def test_closed_recovery_map_reads_app_pt_build_state(tmp_path):
    path = tmp_path / "app" / "pt_build" / "general_asset_census" / "recovery_bundles.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "status": "CLOSED",
                        "side": "CLIENT",
                        "root_path": "char/npcXms/ChTree_Longbo.inx",
                        "donor_label": "DONOR4",
                    },
                    {
                        "status": "OPEN",
                        "side": "CLIENT",
                        "root_path": "char/ignored.inx",
                        "donor_label": "DONOR4",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = dre._closed_recovery_map(tmp_path)
    key = ("CLIENT", "char/npcxms/chtree_longbo.inx", "DONOR4")
    assert key in rows
    assert len(rows) == 1


def test_closed_recovery_map_keeps_legacy_pt_build_fallback(tmp_path):
    path = tmp_path / "pt_build" / "general_asset_census" / "recovery_bundles.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "status": "CLOSED",
                        "side": "CLIENT",
                        "root_path": "char/legacy.inx",
                        "selected_source": "DONOR1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = dre._closed_recovery_map(tmp_path)
    assert ("CLIENT", "char/legacy.inx", "DONOR1") in rows
