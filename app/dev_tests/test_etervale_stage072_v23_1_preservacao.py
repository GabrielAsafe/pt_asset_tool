"""V23.1: protect V22/V23 proposals from empty overwrite and restore the 103 trees."""
from __future__ import annotations
import ast
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
RECOVERY=ROOT.parent/'patches/etervale_v23_1_fore1_v22_recovery.json'

spec=importlib.util.spec_from_file_location('restore_v23_1',ROOT/'pt_stage072_restore_v23_1.py')
restore=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=restore
spec.loader.exec_module(restore)


def simulated_root(tmp):
    root=tmp/'pt_asset_tool'
    (root/'app').mkdir(parents=True)
    (root/'app/pt_asset.py').write_text('# test placeholder')
    return root


def target(root):
    return root/'app/pt_build/etervale/stage072_semantic_v21/maps'/restore.OUT_NAME


def test_uploaded_evidence_is_source_locked():
    doc=json.loads(RECOVERY.read_text())
    assert restore.validate(doc,expected_candidates=103)==103
    assert len({f for c in doc['candidates'] for f in c['faces']})==3859
    assert all(c['status']=='PENDING' for c in doc['candidates'])


def test_dry_run_and_restore_zero_with_backup(tmp_path):
    root=simulated_root(tmp_path)
    dest=target(root);dest.parent.mkdir(parents=True)
    doc=json.loads(RECOVERY.read_text());doc['candidates']=[]
    dest.write_text(json.dumps(doc))
    assert restore.restore(root,RECOVERY,dry_run=True)==103
    assert len(json.loads(dest.read_text())['candidates'])==0
    assert restore.restore(root,RECOVERY)==103
    assert len(json.loads(dest.read_text())['candidates'])==103
    backups=list((dest.parent/'_recovery_backups').rglob('*.json'))
    assert len(backups)==1
    assert json.loads(backups[0].read_text())['candidates']==[]


def test_preserve_existing_nonempty_does_not_overwrite(tmp_path):
    root=simulated_root(tmp_path)
    dest=target(root);dest.parent.mkdir(parents=True)
    doc=json.loads(RECOVERY.read_text());doc['candidates'][0]['status']='APPROVED'
    dest.write_text(json.dumps(doc));old=dest.read_bytes()
    assert restore.restore(root,RECOVERY)==0
    assert dest.read_bytes()==old


def test_reject_wrong_source_and_status():
    doc=json.loads(RECOVERY.read_text())
    doc['source_sha256']='f'*64
    try:
        restore.validate(doc)
        assert False
    except ValueError as e:
        assert 'SOURCE' in str(e)
    doc=json.loads(RECOVERY.read_text())
    doc['candidates'][0]['accepted_for_runtime']=True
    try:
        restore.validate(doc)
        assert False
    except ValueError as e:
        assert 'BAD_CANDIDATE' in str(e)


def test_blender_handlers_block_empty_overwrites_without_dropping_reviews():
    addon=(ROOT/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    trees=(ROOT/'pt_asset_tool/blender/stage072_tree_v23.py').read_text()
    assert 'V22_EMPTY_RESULT_PRESERVED_EXISTING_PROPOSALS' in addon
    assert 'V22_NO_CANDIDATES_NO_SAVE_REQUIRES_SEEDS_OR_RESTORED_JSON' in addon
    assert 'V23_EMPTY_RESULT_PRESERVED_EXISTING_TREES' in trees
    assert 'V23_NO_TREES_NO_SAVE_RESTORE_V22_PROPOSALS' in trees
    assert 'PREVIA_APROVADAS_REQUER_APROVAR_ARVORES_NA_LISTA' in trees
    ast.parse(addon);ast.parse(trees)


def test_preservation_guards_before_save_calls():
    addon=(ROOT/'pt_asset_tool/blender/stage072_semantic_paint.py').read_text()
    trees=(ROOT/'pt_asset_tool/blender/stage072_tree_v23.py').read_text()
    detect=addon.split('class PT_OT_V22Detect')[1].split('class PT_OT_V22Decide')[0]
    build=trees.split('class PT_OT_V23Build')[1].split('class PT_OT_V23Separate')[0]
    assert detect.index('if not new[\'candidates\']') < detect.index('PROPOSALS = new')
    assert build.index('if not new[\'trees\']') < build.index('PLAN = new')
