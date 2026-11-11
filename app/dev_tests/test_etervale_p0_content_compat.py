from pathlib import Path
from pt_asset_tool.etervale_content_compat import inventory_content, DOMAINS
from pt_asset_tool.data_type_tools import FORMAT_SPECS

def test_all_legacy_packs_explicitly_unmapped():
    assert {x.upper() for x in FORMAT_SPECS} == set(DOMAINS)
    assert all(len(v)==4 for v in DOMAINS.values())

def test_content_inventory_is_read_only(tmp_path):
    (tmp_path/'canonical').mkdir()
    (tmp_path/'canonical'/'item.json').write_text('{}')
    out=inventory_content(tmp_path)
    assert out['total_files']==1 and out['extensions']=={'.json':1}
    assert not (tmp_path/'compiled').exists()

def test_content_limit_fails_closed(tmp_path):
    import pytest
    for i in range(3): (tmp_path/f'{i}.json').write_text('{}')
    with pytest.raises(ValueError,match='LIMIT'):
        inventory_content(tmp_path,limit=2)


def test_native_content_draft_without_reader_changes(tmp_path):
    from pt_asset_tool.etervale_content_compat import compile_native_draft
    result=compile_native_draft({'format':'PT_ASSET_ETERVALE_NATIVE_AUTHORING_V1',
     'files':[{'path':'Monster/Example.inf','directives':[
      {'key':'*이름','values':['Exemplo']},{'key':'*모양파일','values':['char/monster/example.smd']},
      {'key':'*레벨','values':[12]}]}]},tmp_path)
    from pathlib import Path
    output=Path(result['outputs'][0]['path'])
    assert output.read_bytes().decode('cp949').startswith('*이름 Exemplo\r\n')
    assert 'NOT_IMPORT_CERTIFIED' in result['status']

def test_native_draft_prevents_links_and_path_escapes(tmp_path):
    from pt_asset_tool.etervale_content_compat import compile_native_draft
    import pytest
    spec={'format':'PT_ASSET_ETERVALE_NATIVE_AUTHORING_V1',
      'files':[{'path':'../evil.inf','directives':[{'key':'*Name','values':['x']}]}]}
    with pytest.raises(ValueError,match='PATH'):
       compile_native_draft(spec,tmp_path)
    spec['files'][0]['path']='Monster/demo.inf'
    spec['files'][0]['directives'][0]['key']='*연결파일'
    with pytest.raises(ValueError,match='LINKED_FILE'):
       compile_native_draft(spec,tmp_path)
