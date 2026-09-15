from __future__ import annotations

import pathlib

from pt_asset_tool.entity_catalog import load_entity_seed


def test_packaged_entity_seed_matches_canonical_fixture_shape():
    project = pathlib.Path(__file__).resolve().parents[1]
    seed = load_entity_seed(project)
    assert seed['status'] == 'PASS'
    assert seed['entity_count'] == 351
    assert seed['monster_count'] == 267
    assert seed['npc_count'] == 84
    assert all(x['runtime_status'] == 'UNPROVEN' for x in seed['entities'])
    assert all(x['writer_status'] == 'UNAUTHORIZED' for x in seed['entities'])
    names = {(x['semantic_group'], x['display_name']) for x in seed['entities']}
    assert ('NPC', 'Ahin') in names
    assert ('MONSTER', 'Acero') in names
    assert ('MONSTER', 'Monbagon') in names
