from __future__ import annotations

from pt_asset_tool.entity_catalog import build_live_entities, query_entities


def rows():
    return [
        {'path':'char/npc/Ahin/Ahin.smd','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'MODEL','ext':'.smd','size':10,'previewable':False},
        {'path':'char/npc/Ahin/Ahin.inx','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'CONFIG','ext':'.inx','size':20,'previewable':False},
        {'path':'char/npc/Ahin/Ahin.smb','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'ANIMATION','ext':'.smb','size':30,'previewable':False},
        {'path':'char/npc/Ahin/Ahin-body.tga','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'TEXTURE','ext':'.tga','size':40,'previewable':True},
        {'path':'char/monster/Acero/Acero.smd','category':'MONSTER','folder':'Acero','folder_path':'char/monster/Acero','role':'MODEL','ext':'.smd','size':50,'previewable':False},
        {'path':'char/monster/Acero/Acero.tga','category':'MONSTER','folder':'Acero','folder_path':'char/monster/Acero','role':'TEXTURE','ext':'.tga','size':60,'previewable':True},
    ]


def test_live_entities_group_files_and_preview():
    seed={'entity_count':2,'entities':[
        {'entity_key':'NPC|char/npc/ahin','file_count':7,'representative_preview':'char/npc/Ahin/Ahin.tga'},
        {'entity_key':'MONSTER|char/monster/acero','file_count':4,'representative_preview':'char/monster/Acero/Acero.tga'},
    ]}
    items=build_live_entities(rows(),seed)
    by={x['display_name']:x for x in items}
    assert by['Ahin']['asset_count']==4
    assert by['Ahin']['role_counts']=={'ANIMATION':1,'CONFIG':1,'MODEL':1,'TEXTURE':1}
    assert by['Ahin']['representative_preview'].endswith('Ahin-body.tga')
    assert by['Ahin']['known_canonical_entity'] is True
    assert by['Ahin']['runtime_status']=='UNPROVEN'
    assert by['Acero']['writer_status']=='UNAUTHORIZED'


def test_entity_query_filters_group():
    r=query_entities(rows(), {'entity_count':0,'entities':[]}, group='NPC')
    assert r['status']=='PASS'
    assert len(r['items'])==1
    assert r['items'][0]['display_name']=='Ahin'
