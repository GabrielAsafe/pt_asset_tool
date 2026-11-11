from __future__ import annotations

from pathlib import Path

import pytest

from pt_asset_tool.etervale_texture_selection import (
    catalogue_texture_paths, family_for_path, list_selection, validate_selected_paths,
)


def _fixture(tmp_path):
    paths = [
        'image/ui/button01.png',
        'image/ui/button02.png',
        'image/ui/button03.png',
        'image/ui/button04.png',
        'image/ui/button05.png',
        'Field/Ricarten/tem_wall03.BMP',
        'char/npc/TN-008/face.tga',
        'Effect/glow.tga',
        'sound.wav',
    ]
    root = tmp_path/'assets'
    for path in paths:
        file = root/path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'dummy')
    assets = [{'path': p} for p in paths]
    return root, assets


def test_selector_first_four_ui_files_and_counts(tmp_path):
    root, assets = _fixture(tmp_path)
    page = list_selection(assets, family='ui')
    assert page['total'] == 5
    assert page['counts']['all'] == 8  # excludes .wav
    assert page['counts']['ui'] == 5
    assert [x['path'] for x in page['rows'][:4]] == [f'image/ui/button0{i}.png' for i in range(1,5)]
    selected = [x['path'] for x in page['rows'][:4]]
    assert validate_selected_paths(assets, root, selected, family='ui', include_ui=True) == selected
    assert family_for_path('Field/Ricarten/tem_wall03.BMP') == 'world'
    assert family_for_path('char/npc/TN-008/face.tga') == 'characters'


def test_pagination_and_search(tmp_path):
    _, assets = _fixture(tmp_path)
    assert list_selection(assets, family='ui', offset=2, limit=2)['rows'][0]['path'] == 'image/ui/button03.png'
    assert list_selection(assets, family='ui', search='button05')['total'] == 1
    assert list_selection(assets, family='other')['total'] == 0
    with pytest.raises(ValueError, match='TEXTURE_PAGE_INVALID'):
        list_selection(assets, limit=200)
    with pytest.raises(ValueError, match='TEXTURE_FAMILY_INVALID'):
        list_selection(assets, family='unknown')


def test_reject_empty_oversized_and_ui_without_consent(tmp_path):
    root, assets = _fixture(tmp_path)
    with pytest.raises(ValueError, match='SIZE_INVALID'):
        validate_selected_paths(assets, root, [], family='ui', include_ui=True)
    with pytest.raises(ValueError, match='SIZE_INVALID'):
        validate_selected_paths(assets, root, ['x']*101, family='all', include_ui=True)
    with pytest.raises(ValueError, match='EXPLICIT_CONSENT'):
        validate_selected_paths(assets, root, ['image/ui/button01.png'], family='ui', include_ui=False)
    with pytest.raises(ValueError, match='FAMILY_MISMATCH'):
        validate_selected_paths(assets, root, ['Field/Ricarten/tem_wall03.BMP'], family='ui', include_ui=True)


def test_reject_path_traversal_unknown_duplicate_and_symlink_escape(tmp_path):
    root, assets = _fixture(tmp_path)
    for paths in [['../outside.png'], ['/etc/passwd'], ['image\\ui\\button01.png'], ['not/catalog.png'], ['image/ui/button01.png']*2]:
        with pytest.raises(ValueError):
            validate_selected_paths(assets, root, paths, family='all', include_ui=True)
    outside = tmp_path/'outside.png';outside.write_bytes(b'no')
    sub = root/'image/ui/link.png';sub.symlink_to(outside)
    assets.append({'path':'image/ui/link.png'})
    with pytest.raises(ValueError, match='OUTSIDE_CLIENT'):
        validate_selected_paths(assets, root, ['image/ui/link.png'], family='all', include_ui=True)


def test_cli_is_explicit_and_ui_has_four_select_button():
    root = Path(__file__).resolve().parents[1]/'pt_asset_tool'
    py = (root/'ui_app.py').read_text()
    js = (root/'ui_static'/'app.js').read_text()
    html = (root/'ui_static'/'index.html').read_text()
    assert 'texture_validate_selected_paths(' in py
    assert '"--include-exact", item' in py
    assert '"texture-upscale", "run", "--all"' not in py
    assert 'id="clientEnhancementFirst4"' in html
    assert 'bindEnhancementSelection();' in js
    assert 'paths:selected' in js
