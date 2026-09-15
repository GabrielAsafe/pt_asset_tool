from __future__ import annotations
import os, pathlib, subprocess

ROOT=pathlib.Path(__file__).resolve().parents[1]


def test_desktop_entry_quotes_project_path_with_spaces(tmp_path: pathlib.Path):
    project=tmp_path/'Área de Trabalho'/'design_work'
    project.mkdir(parents=True)
    (project/'pt_asset_gui.py').write_text('#!/usr/bin/env python3\n')
    (project/'pt-asset-gui').write_text('#!/bin/sh\n')
    home=tmp_path/'home'; home.mkdir()
    env=os.environ.copy(); env['HOME']=str(home)
    cp=subprocess.run([str(ROOT/'payload/install_desktop_entry.sh'),str(project)],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)
    assert cp.returncode==0,cp.stdout
    desktop=home/'.local/share/applications/pt-asset-tool.desktop'
    text=desktop.read_text()
    assert f'Exec="{project.resolve()}/pt-asset-gui"' in text
    assert f'Path={project.resolve()}' in text
