from pathlib import Path
from dev_tests._runtime_context import runtime_registry

from pt_asset_tool.release_1_coverage import (
    CAPABILITIES,
    CONTENT_DOMAINS,
    build_release_1_automated_gate_plan,
    build_release_1_coverage,
    content_domain_from_values,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry():
    return runtime_registry()


def test_release_1_coverage_crosses_content_domains_and_capabilities():
    report=build_release_1_coverage(_registry(), external_evidence={'rigid_automated_pass_domains':['PLAYER']})
    assert report['status']=='PARTIAL'
    assert report['content_domains']==list(CONTENT_DOMAINS)
    assert report['required_capabilities']==list(CAPABILITIES)
    assert report['matrix']['NPC']['MODEL062_RIGID']['asset_count'] >= 90
    assert report['matrix']['MONSTER']['MODEL062_RIGID']['asset_count'] >= 390
    assert report['matrix']['WEAPON_ITEM']['MODEL062_STATIC']['asset_count'] > 100
    assert report['matrix']['MAP']['STAGE072']['asset_count'] > 50
    assert report['matrix']['PLAYER']['MODEL062_MIXED']['state']=='OUT_OF_SCOPE_NOT_CERTIFIED'
    mixed_global=next(x for x in report['global_gates'] if x['capability']=='MODEL062_MIXED')
    assert mixed_global['state']=='OUT_OF_SCOPE_NOT_CERTIFIED'
    assert mixed_global['release_1_blocking'] is False
    assert report['policy']['automatic_tests_preferred'] is True
    assert report['policy']['production_authorized'] is False
    assert report['blocking_gate_count'] == len(report['blocking_gates'])
    assert not any(x['domain']=='GLOBAL' and x['capability']=='MODEL062_MIXED' for x in report['blocking_gates'])


def test_release_1_plan_selects_real_npc_monster_and_static_semantic_representatives():
    plan=build_release_1_automated_gate_plan(_registry(), rigid_per_domain=4, static_per_domain=3)
    assert plan['status']=='PASS'
    assert plan['rigid_representatives']['NPC']
    assert plan['rigid_representatives']['MONSTER']
    for domain in ('NPC','MONSTER'):
        for row in plan['rigid_representatives'][domain]:
            assert row['domain']==domain
            assert row['model_info_inx']
            assert row['skeleton_smb']
            assert row['valid_lods']
    for domain in ('WEAPON_ITEM','EFFECT','MAP'):
        assert len(plan['static_representatives'][domain]) == 3
    assert plan['automatic_only'] is True
    assert plan['production_authorized'] is False
    assert not any('Mixed-Physique' in x for x in plan['external_requirements'])


def test_release_1_content_domain_uses_structural_character_roots_then_semantic_category():
    assert content_domain_from_values('char/monster/Bear/Maplebear.smd', 'MAP_STAGE') == 'MONSTER'
    assert content_domain_from_values('char/npc/Bcn02/Bcn02.smd', 'EFFECT') == 'NPC'
    assert content_domain_from_values('Effect/AssaEffect/Skill3Mesh/dancesword.smd', 'WEAPON_ITEM') == 'WEAPON_ITEM'
    assert content_domain_from_values('Effect/ObjAnimationData/MonsterWeb/Web.smd', 'MOB_MONSTER') == 'MONSTER'
    assert content_domain_from_values('Effect/SomeFx/foo.smd', 'EFFECT') == 'EFFECT'


def test_release_1_registry_matrix_counts_object_local_only_where_structurally_present():
    report=build_release_1_coverage(_registry())
    counts={d: report['matrix'][d]['OBJECT_LOCAL_ANIMATION']['asset_count'] for d in CONTENT_DOMAINS}
    assert sum(counts.values()) > 400
    assert counts['MAP'] > 300
    assert counts['MONSTER'] > 0
    assert report['matrix']['NPC']['OBJECT_LOCAL_ANIMATION']['asset_count'] == 0


def test_release_1_proprietary_texture_inventory_is_domain_attributed():
    report=build_release_1_coverage(_registry())
    for domain in CONTENT_DOMAINS:
        cell=report['matrix'][domain]['BMP_TGA_PROPRIETARY']
        assert cell['asset_count'] > 0, domain
        assert cell['state']=='DOMAIN_CODEC_AUTOMATION_PENDING'


def test_release_1_existing_animation_uses_physical_smb_census_when_available():
    evidence={
        'animated_smb_physical_by_domain': {'EFFECT': 3},
        'animation_pose_pass_domains': ['EFFECT'],
    }
    report=build_release_1_coverage(_registry(), external_evidence=evidence)
    cell=report['matrix']['EFFECT']['EXISTING_ANIMATION']
    assert cell['asset_count']==3
    assert cell['state']=='AUTOMATED_POSE_SPACE_PASS'
    assert cell['evidence']['presence_basis']=='PHYSICAL_SMB_CENSUS'


def test_release_1_map_material_requires_stage_material_gate_when_stage_is_present():
    report=build_release_1_coverage(_registry(), external_evidence={'model062_material_pass_domains':['MAP']})
    cell=report['matrix']['MAP']['MATERIALS']
    assert cell['state']=='MATERIAL_CANDIDATE_PIPELINE_PRESENT_EXECUTION_PENDING'
    assert cell['evidence']['stage072_material_gate_pass'] is False
    report2=build_release_1_coverage(_registry(), external_evidence={
        'model062_material_pass_domains':['MAP'], 'stage072_material_pass_domains':['MAP'],
    })
    assert report2['matrix']['MAP']['MATERIALS']['state']=='AUTOMATED_MATERIAL_EDIT_PASS_ALL_PRESENT_FAMILIES'


def test_release_1_lod_cell_pass_requires_every_config_to_have_a_safe_model_key():
    report=build_release_1_coverage(_registry(), external_evidence={
        'lod_corpus_pass_domains':['NPC'],
        'lod_content_inconsistent_by_domain':{'NPC':0},
        'lod_fixed16_model_key_by_domain':{'NPC':2},
    })
    cell=report['matrix']['NPC']['LOD']
    assert cell['state']=='CORPUS_MODEL_KEY_AUTHORABLE'
    assert cell['evidence']['fixed16_model_key_configs']==2


def test_release_1_lod_true_nonprefix_outlier_blocks_only_when_asset_has_no_authorable_config():
    report=build_release_1_coverage(_registry(), external_evidence={
        'lod_corpus_pass_domains':[],
        'lod_content_inconsistent_by_domain':{'NPC':1},
        'lod_assets_without_authorable_config_by_domain':{'NPC':1},
    })
    cell=report['matrix']['NPC']['LOD']
    assert cell['state']=='CORPUS_HAS_ASSETS_WITHOUT_AUTHORABLE_LOD_CONFIG'
    assert cell['evidence']['diagnosed_non_authorable_configs_fail_closed']==1
    assert cell['evidence']['assets_without_authorable_lod_config']==1
    assert any(b['domain']=='NPC' and b['capability']=='LOD' for b in report['blocking_gates'])


def test_release_1_lod_diagnosed_bad_config_does_not_block_asset_with_safe_alternative():
    report=build_release_1_coverage(_registry(), external_evidence={
        'lod_corpus_pass_domains':['NPC'],
        'lod_content_inconsistent_by_domain':{'NPC':1},
        'lod_assets_without_authorable_config_by_domain':{'NPC':0},
        'lod_assets_with_diagnosed_fail_closed_outliers_by_domain':{'NPC':1},
    })
    cell=report['matrix']['NPC']['LOD']
    assert cell['state']=='CORPUS_AUTHORABLE_WITH_DIAGNOSED_FAIL_CLOSED_CONFIG_OUTLIERS'
    assert cell['evidence']['diagnosed_non_authorable_configs_fail_closed']==1
    assert cell['evidence']['assets_with_diagnosed_fail_closed_config_outliers']==1
    assert not any(b['domain']=='NPC' and b['capability']=='LOD' for b in report['blocking_gates'])


def test_release_1_lod_single_tier_full_container_is_authorable_not_alias_blocker():
    report=build_release_1_coverage(_registry(), external_evidence={
        'lod_corpus_pass_domains':['MONSTER'],
        'lod_content_inconsistent_by_domain':{'MONSTER':0},
        'lod_single_tier_full_container_by_domain':{'MONSTER':7},
    })
    cell=report['matrix']['MONSTER']['LOD']
    assert cell['state']=='CORPUS_MODEL_KEY_AUTHORABLE'
    assert cell['evidence']['single_tier_full_container_configs']==7
    assert not any(b['domain']=='MONSTER' and b['capability']=='LOD' for b in report['blocking_gates'])
