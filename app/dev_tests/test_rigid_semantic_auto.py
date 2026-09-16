from pathlib import Path
from dev_tests._runtime_context import runtime_registry

from pt_asset_tool.release_1_coverage import build_release_1_automated_gate_plan
from pt_asset_tool.rigid_semantic_devtest import _cfg_for, _valid_lods

ROOT=Path(__file__).resolve().parents[1]


def test_rigid_semantic_planned_contexts_resolve_to_exact_config_and_valid_lods():
    reg=runtime_registry()
    plan=build_release_1_automated_gate_plan(reg,rigid_per_domain=3,static_per_domain=1)
    for domain in ('NPC','MONSTER'):
        for row in plan['rigid_representatives'][domain]:
            asset=reg.resolve(row['asset'])
            cfg=_cfg_for(asset,row['model_info_inx'])
            assert str(cfg['motion_smb']).replace('\\','/') == row['skeleton_smb']
            assert _valid_lods(asset,cfg) == row['valid_lods']
