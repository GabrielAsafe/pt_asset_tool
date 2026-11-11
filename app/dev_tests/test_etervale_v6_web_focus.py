"""V6 audit gates: field identity, entity facets, favorite persistence and UI wiring."""
from pathlib import Path
from pt_asset_tool.entity_catalog import build_live_entities, query_built_entities, _physical_entity_descriptor
from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore
from pt_asset_tool.ui_app import _preview_etag

ROOT=Path(__file__).resolve().parents[1] / 'pt_asset_tool' / 'ui_static'


def row(path, category='MAP', role='WORLD'):
    file=Path(path)
    return {'path':path,'category':category,'role':role,'ext':file.suffix.lower(),
            'folder':file.parent.name,'folder_path':file.parent.as_posix(),
            'size':20,'previewable':False,'favorite':False}


def test_field_file_variants_share_single_identity():
    records=[row('Field/AncientW/village-2.smd'),row('GameServer/Field/AncientW.ASE.spm'),
             row('GameServer/Field/ancientW.ASE.spc'),row('GameServer/Field/ancientW.ASE.spp')]
    fields=[x for x in build_live_entities(records) if x['semantic_group']=='MAP_FIELD']
    assert len(fields)==1
    field=fields[0]
    assert field['display_name'].casefold()=='ancientw'
    assert field['asset_count']==4
    assert field['extension_counts']=={'.smd':1,'.spc':1,'.spm':1,'.spp':1}
    assert field['folder_root'].casefold()=='field/ancientw'
    assert field['identity_evidence']=='CLIENT_SERVER_FIELD_ID_AND_NATIVE_FIELD_SUFFIX'
    assert query_built_entities(fields,ext='spm')['matched_entity_count']==1
    assert query_built_entities(fields,source='linked')['matched_entity_count']==1
    assert query_built_entities(fields,source='client')['matched_entity_count']==1
    assert query_built_entities(fields,source='server')['matched_entity_count']==1


def test_unrelated_files_not_merged_by_loose_stem():
    a=_physical_entity_descriptor('Image/AncientW.spm','MAP')
    b=_physical_entity_descriptor('GameServer/Field/AncientW.ASE.spm','MAP')
    assert a != b
    assert b['entity_key']=='MAP_FIELD|field:ancientw'
    assert _physical_entity_descriptor('GameServer/Field/Unrelated.txt','MAP')['entity_key'] != b['entity_key']


def test_entities_filter_before_limit_and_reject_invalid_source():
    items=build_live_entities([row('Field/Ricarten/a.smd'),row('GameServer/Field/AncientW.ASE.spm')])
    r=query_built_entities(items,ext='spm',limit=1)
    assert r['matched_entity_count']==1
    assert '.spm' in r['extension_facets']
    try:query_built_entities(items,source='bogus')
    except ValueError as e:assert 'ENTITY_SOURCE_FILTER_INVALID' in str(e)
    else:assert False


def test_favorites_are_persisted_and_filterable(tmp_path):
    root=tmp_path/'assets';(root/'Field'/'Ricarten').mkdir(parents=True)
    file=root/'Field'/'Ricarten'/'village-2.smd';file.write_bytes(b'SMD Model data Ver 0.72')
    state=UIStateStore(tmp_path/'ui_state.json')
    index=CatalogIndex(root,state)
    index.rebuild()
    assert index.query(favorites=True)['total']==0
    a=index.apply_state_update('Field/Ricarten/village-2.smd',{'favorite':True})
    assert a['favorite'] is True
    assert index.query(favorites=True)['total']==1
    new_state=UIStateStore(tmp_path/'ui_state.json')
    new_index=CatalogIndex(root,new_state)
    new_index.rebuild()
    assert new_index.query(favorites=True)['total']==1


def test_preview_etag_tracks_external_change(tmp_path):
    f=tmp_path/'asset.tga';f.write_bytes(b'first')
    one=_preview_etag(f)
    f.write_bytes(b'changed-size')
    assert one != _preview_etag(f)


def test_frontend_workspace_cache_and_particle_scopes_are_wired():
    page=(ROOT/'index.html').read_text()
    js=(ROOT/'app.js').read_text()
    css=(ROOT/'app.css').read_text()
    assert 'data-nav-group="workspaces"' in page
    assert 'data-workspace-tab="client"' in page
    assert 'data-workspace-tab="compare"' in page
    assert 'data-support-tab="validation"' not in page
    assert 'id="etervaleEvidenceSummary"' in page
    assert 'id="entityExtension"' in page
    assert 'id="entitySource"' in page
    assert 'quick-filters' not in page
    assert 'data-fav-path' in js
    assert "bindCatalogStars($('#assetRows'))" in js
    assert 'entityRenderedKey===cacheKey' in js
    assert 'setParticleMotionPlaying' in js
    assert 'NOT certified playback' in page
    assert 'minmax(0,1fr)' in css
