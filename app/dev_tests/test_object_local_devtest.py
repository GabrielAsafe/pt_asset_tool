from pt_asset_tool.object_local_devtest import _candidate_edits


def test_object_local_auto_selects_rot_pos_scale_existing_keys_once_each():
    parsed={'objects':[{
        'index':0,'name':'A','TmFrameCnt':0,
        'rot_keys':[{'q_incremental_xyzw':[0.0,0.0,0.0,1.0]}],
        'pos_keys':[{'xyz':[1.0,2.0,3.0]}],
        'scale_keys':[{'xyz':[1.0,1.0,1.0]}],
    }]}
    rows=_candidate_edits(parsed)
    assert [x['channel'] for x in rows]==['ROT','POS','SCALE']
    assert len(rows[0]['values'])==4
    assert rows[1]['values'][0]==1.125
    assert rows[2]['values'][0]==1.0+1.0/256.0


def test_object_local_auto_includes_segmented_existing_keys():
    parsed={'objects':[{
        'index':0,'name':'Seg','TmFrameCnt':2,
        'rot_keys':[],
        'pos_keys':[{'xyz':[0.0,0.0,0.0]}],
        'scale_keys':[],
    }]}
    rows=_candidate_edits(parsed)
    assert len(rows)==1
    assert rows[0]['channel']=='POS'
