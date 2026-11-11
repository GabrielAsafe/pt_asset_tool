from pt_asset_tool.etervale_quality_gates import classify_native

def test_stage_quality_does_not_claim_runtime():
    row=classify_native('.smd','-- MATERIAL AGGREGATES --\n collision faces : 319')
    assert row['materials']=='CSHARP_READER_INSPECTED'
    assert 'NOT_PHYSICS_TESTED' in row['collision']
    assert row['runtime_visual']=='NOT_CERTIFIED'

def test_inx_motion_not_playback():
    row=classify_native('.inx','some output')
    assert 'NOT_PLAYBACK_TESTED' in row['animation']

def test_part_cannot_be_native_certified():
    row=classify_native('.part','')
    assert row['effects']=='NOT_TESTED'
