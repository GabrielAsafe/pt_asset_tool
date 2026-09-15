from pt_asset_tool.mixed_synthetic_devtest import run_mixed_physique_synthetic_devtest


def test_mixed_synthetic_gate_exercises_rigid_static_combined_container(tmp_path):
    r=run_mixed_physique_synthetic_devtest(tmp_path)
    assert r['status']=='PASS'
    assert r['analysis']['mode']=='MIXED'
    assert r['verification']['all_target_edits_observed'] is True
    assert r['verification']['non_target_changed']==[]
    assert r['real_corpus_certified'] is False
    assert r['production_authorized'] is False
