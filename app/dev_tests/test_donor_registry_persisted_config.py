from __future__ import annotations

import json

from pt_asset_tool.app_config import (
    configured_contract_donor_clients,
    configured_contract_donor_servers,
)
from pt_asset_tool.donor_recovery_explorer import donor_pairs


def test_contract_donor_registry_reads_persisted_app_pt_build_state(tmp_path):
    state = tmp_path / "app" / "pt_build" / "state"
    state.mkdir(parents=True)
    (state / "pt_asset_app_config.json").write_text(
        json.dumps(
            {
                "format": "PT_ASSET_APP_CONFIG_V1",
                "contract_donor_clients": [
                    {"label": "DONOR1", "path": "/evidence/client1"},
                    {"label": "DONOR4", "path": "/evidence/old"},
                ],
                "contract_donor_servers": [
                    {"label": "DONOR1", "path": "/evidence/server1"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert configured_contract_donor_clients(tmp_path) == [
        "DONOR1=/evidence/client1",
        "DONOR4=/evidence/old",
    ]
    assert configured_contract_donor_servers(tmp_path) == [
        "DONOR1=/evidence/server1",
    ]

    rows = {row["label"]: row for row in donor_pairs(tmp_path)}
    assert set(rows) == {"DONOR1", "DONOR4"}
    assert rows["DONOR4"]["client"]["root"] == "/evidence/old"
    assert rows["DONOR4"]["server"] is None


def test_contract_donor_registry_preserves_explicit_empty_list(tmp_path):
    state = tmp_path / "app" / "pt_build" / "state"
    state.mkdir(parents=True)
    (state / "pt_asset_app_config.json").write_text(
        json.dumps(
            {
                "format": "PT_ASSET_APP_CONFIG_V1",
                "contract_donor_clients": [],
                "contract_donor_servers": [],
            }
        ),
        encoding="utf-8",
    )

    assert configured_contract_donor_clients(tmp_path) == []
    assert configured_contract_donor_servers(tmp_path) == []
    assert donor_pairs(tmp_path) == []
