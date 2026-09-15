from pathlib import Path


def test_final_gui_surfaces_exist():
    root=Path(__file__).resolve().parents[1]
    html=(root/'payload/pt_asset_tool/ui_static/index.html').read_text()
    js=(root/'payload/pt_asset_tool/ui_static/app.js').read_text()
    for surface in ['Catálogo','Comparar','Tarefas','Relatórios','Configurações','Console ao vivo','NPCs']:
        assert surface in html
    assert 'Anotação do catálogo' in js
    assert '/api/safety/arm' in js
    assert '/api/action' in js
    assert '/api/tree-compare' in js
    assert '/api/monster-npc-census' in js


def test_launcher_version():
    import subprocess
    root=Path(__file__).resolve().parents[1]
    r=subprocess.run(['python3',str(root/'payload/pt_asset_gui.py'),'--version'],text=True,stdout=subprocess.PIPE,check=True)
    assert r.stdout.strip()=='0.12.0'


def test_compare_filters_are_exposed():
    root=Path(__file__).resolve().parents[1]
    html=(root/'payload/pt_asset_tool/ui_static/index.html').read_text()
    js=(root/'payload/pt_asset_tool/ui_static/app.js').read_text()
    for token in ['compareExt','compareCategory','comparePath','compareDiffOnly']:
        assert token in html and token in js


def test_compare_result_viewer_is_exposed():
    root=Path(__file__).resolve().parents[1]
    html=(root/'payload/pt_asset_tool/ui_static/index.html').read_text()
    js=(root/'payload/pt_asset_tool/ui_static/app.js').read_text()
    assert 'compareResult' in html and 'compareStatus' in html
    assert '/api/report?name=' in js and 'renderCompareReport' in js


def test_gui_missing_client_error_is_user_friendly(tmp_path):
    import subprocess, sys
    root=Path(__file__).resolve().parents[1]
    project=tmp_path/'isolated_design_work'; project.mkdir()
    # pt_asset_gui.py checks project root, so provide a minimal backend marker.
    (project/'pt_asset.py').write_text('# marker\n')
    # Run the packaged GUI script but point it at an isolated project with no discoverable client.
    cp=subprocess.run([sys.executable,str(root/'payload/pt_asset_gui.py'),'--project-root',str(project),'--no-browser'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=10,check=False,env={'PATH':'/usr/bin:/bin'})
    assert cp.returncode==2
    assert 'client root não encontrado' in cp.stdout
    assert 'config set-client-root' in cp.stdout
    assert 'Traceback' not in cp.stdout
