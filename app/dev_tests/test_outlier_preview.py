from __future__ import annotations

import pathlib

import pytest

from pt_asset_tool.ui_image import PreviewDecodeError, preview_image_bytes

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT.parent / "fixture_client"

pytestmark = pytest.mark.skipif(not CLIENT.is_dir(), reason="external fixture_client is not packaged")


def test_archivotmp_uses_existing_preview_only_recovery():
    data, mime = preview_image_bytes(CLIENT / "Effect/Particle/ArchivoTmp.tga", ROOT)
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("rel", [
    "Field/Ricarten/ch_tree1.tga",
    "Effect/AssaEffect/MonsterFury/m_fury.tga",
])
def test_known_non_images_remain_fail_closed(rel):
    with pytest.raises(PreviewDecodeError):
        preview_image_bytes(CLIENT / rel, ROOT)
