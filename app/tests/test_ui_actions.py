from __future__ import annotations

from pathlib import Path
import pytest

from pt_asset_tool.ui_actions import build_command


def project(tmp_path: Path) -> Path:
    p=tmp_path/'project'; p.mkdir(); (p/'pt_asset.py').write_text('print("ok")')
    return p


def test_commands_are_argv_not_shell(tmp_path: Path):
    p=project(tmp_path)
    cmd=build_command(p,'inspect','char/tmABCD/at_dragon.smd',{})
    assert cmd[:2]==['python3',str(p/'pt_asset.py')]
    assert cmd[-2:]==['--physical'] or '--physical' in cmd
    assert ';' not in ''.join(cmd)


def test_write_command_and_path_guard(tmp_path: Path):
    p=project(tmp_path)
    assert build_command(p,'write_rare','char/tmABCD/at_dragon.smd',{})[-3:]==['write','rare-model','char/tmABCD/at_dragon.smd']
    with pytest.raises(ValueError):
        build_command(p,'write_rare','../escape.smd',{})


def test_motion_is_sanitized(tmp_path: Path):
    p=project(tmp_path)
    cmd=build_command(p,'validate_animation','char/a.smd',{'motion':'stand'})
    assert cmd[-2:]==['--motion','STAND']
    with pytest.raises(ValueError):
        build_command(p,'validate_animation','char/a.smd',{'motion':'STAND; rm -rf /'})


def test_stage_and_roundtrip_commands(tmp_path: Path):
    p=project(tmp_path)
    assert build_command(p,'validate_stage072_preview','field/a.smd',{})[-3:]==['validate','stage072-preview','field/a.smd']
    assert build_command(p,'validate_roundtrip','char/a.smd',{})[-3:]==['validate','roundtrip','char/a.smd']
