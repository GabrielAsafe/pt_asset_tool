"""Regression tests for P0 four-domain auto selection against C# WorldImport rules."""
from pathlib import Path

import pytest

from pt_asset_tool import etervale_p0_content_probe as content
from pt_asset_tool import etervale_native_pipeline as native


def _root(tmp_path):
    game = tmp_path/'game'
    for d in native.TYPES:
        (game/'assets'/'GameServer'/d).mkdir(parents=True)
    return game, game/'assets'/'GameServer'


def _write(folder: Path, name: str, text: str):
    p=folder/name
    p.write_bytes(text.encode('cp949'))
    return p


def test_item_auto_avoids_unselected_duplicate_variant(tmp_path):
    game,server=_root(tmp_path)
    _write(server/'OpenItem','2_WA108.txt', '*코드 WA108\n*레벨 41\n')
    _write(server/'OpenItem','WA108.txt', '*코드 WA108\n*레벨 40\n')
    _write(server/'Monster','Mon.inf','*레벨 5\n')
    _write(server/'NPC','npc.npc','*NAME "Abaranbo"\n')
    _write(server/'Field','Test.spm','*DELAY 5 23\n')
    chosen=content.choose_auto(game)
    assert chosen == ['OpenItem/WA108.txt','Monster/Mon.inf','NPC/npc.npc','Field/Test.spm']
    assert content._probe_op(server/'OpenItem'/'WA108.txt','OpenItem')['values'][0] == 41


def test_item_winner_when_no_exact_basename_uses_ordinal_first(tmp_path):
    game,server=_root(tmp_path)
    _write(server/'OpenItem','2_WA108.txt', '*코드 WA108\n*레벨 41\n')
    _write(server/'OpenItem','1_WA108.txt', '*코드 WA108\n*레벨 40\n')
    chosen=content._item_catalog_candidates(server/'OpenItem')
    assert [p.name for p in chosen] == ['1_WA108.txt']


def test_npc_name_only_uses_persisted_scalar_not_localized_label(tmp_path):
    game,server=_root(tmp_path)
    original=_write(server/'NPC','adventure-artes.NPC','*NAME Abaranbo\n')
    op=content._probe_op(original,'NPC')
    assert op == {'op':'append','key':'*모델크기','values':[1.25]}
    # The append is actually written, and the original is unchanged.
    spec={'format':native.FORMAT,'files':[{'path':'NPC/adventure-artes.NPC',
          'sha256':native._hash(original.read_bytes()),'operations':[op]}]}
    overlay=native.build_overlay(spec,game,tmp_path/'work')
    candidate=Path(overlay['files'][0]['output']).read_bytes().decode('cp949')
    assert '*모델크기 1.25' in candidate
    assert original.read_bytes().decode('cp949') == '*NAME Abaranbo\n'


def test_npc_cannot_append_after_importer_link_cutoff(tmp_path):
    game,server=_root(tmp_path)
    linked=_write(server/'NPC','a.npc','*NAME Abaranbo\n*연결파일 b.npc\n')
    with pytest.raises(ValueError,match='REQUIRES_TYPED_FIELD_BEFORE_LINK'):
        content._probe_op(linked,'NPC')
    typed=_write(server/'NPC','b.npc','*레벨 5\n*연결파일 c.npc\n')
    assert content._probe_op(typed,'NPC')['values']==[6]


def test_npc_auto_skips_linked_ignored_appends(tmp_path):
    game,server=_root(tmp_path)
    _write(server/'OpenItem','WA108.txt','*코드 WA108\n*레벨 40\n')
    _write(server/'Monster','Mon.inf','*레벨 5\n')
    _write(server/'NPC','a.npc','*NAME Abaranbo\n*연결파일 b.npc\n')
    _write(server/'NPC','b.npc','*NAME B\n')
    _write(server/'Field','Test.spm','*DELAY 5 23\n')
    selected=content.choose_auto(game)
    assert selected[2]=='NPC/b.npc'


def test_item_does_not_select_directives_after_link(tmp_path):
    game,server=_root(tmp_path)
    source=_write(server/'OpenItem','AA101.txt',
                  '*코드 AA101\n*연결파일 other.txt\n*레벨 45\n')
    with pytest.raises(ValueError,match='P0_NO_SAFE_SCALAR'):
        content._probe_op(source,'OpenItem')
