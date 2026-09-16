from pathlib import Path
from dev_tests._runtime_context import runtime_registry
from pt_asset_tool.rigid_model_info import audit_rigid_lod_context_corpus

ROOT=Path(__file__).resolve().parents[1]

def test_rigid_lod_corpus_audits_single_and_multi_configs_and_classifies_known_outliers():
    reg=runtime_registry()
    report=audit_rigid_lod_context_corpus(reg,sample_limit=20)
    assert report['status']=='PASS'
    assert report['config_count'] > 2000
    assert report['lod_config_count'] > 1900
    assert report['importable_config_count'] > 0
    assert report['content_inconsistent_config_count'] == 2
    assert report['legacy_single_tier_alias_config_count'] == 0
    assert report['single_tier_full_container_config_count'] == 10
    assert report['importable_config_count'] + report['content_inconsistent_config_count'] + report['legacy_single_tier_alias_config_count'] + report['no_lod_group_config_count'] == report['config_count']
    assert report['fixed_width_model_key_config_count'] > 0
    rows=[r for r in report['rows'] if r['state']=='MISSING_SMD_NODES_FAIL_CLOSED']
    assert any(r['asset']=='char/npc/Bcn02/Bcn02.smd' and r['inx'].endswith('Bcn02f.inx') and 'hart' in r['missing_nodes'] for r in rows)
    assert any(r['asset']=='char/tmABCD/tmbC03.smd' and r['inx'].endswith('C004.inx') for r in rows)
    legacy=[r for r in report['rows'] if r['state']=='AUTHORABLE_SINGLE_TIER_FULL_CONTAINER']
    assert any(r['asset']=='char/monster/GoblinShaman/GoblinShaman.smd' for r in legacy)
    assert any(r['asset']=='char/monster/Firechick/Firechick.smd' for r in legacy)
    goblin=next(r for r in legacy if r['asset']=='char/monster/GoblinShaman/GoblinShaman.smd')
    cov=next(iter(goblin['lod_node_coverage'].values()))
    assert cov['selection_mode']=='SINGLE_TIER_FULL_CONTAINER'
    assert cov['full_container_preserves_unmapped_labels'] is True
    assert report['policy']['missing_nodes_are_never_synthesized_or_guessed'] is True
    assert report['policy']['inx_full_16byte_slot_uses_serialized_16byte_model_key'] is True
