from __future__ import annotations
import hashlib
import json
import pathlib
import sqlite3
from unittest.mock import patch
import pytest
from pt_asset_tool import etervale_native_pipeline as n


def env(tmp_path):
    game=tmp_path/'game'
    server=game/'assets'/'GameServer'
    for d in ('OpenItem','Monster','NPC','Field'):
        (server/d).mkdir(parents=True,exist_ok=True)
    src=server/'Monster'/'A.inf'
    src.write_bytes('*이름 "Monster A"\r\n*레벨 10\r\n*레벨 11\r\n// note\r\n*E_NAME Alpha\r\n'.encode('cp949'))
    (server/'OpenItem'/'AX101.txt').write_bytes('*코드 AX101\r\n*Name Test\r\n'.encode('cp949'))
    return game,src


def spec(path, ops=None, *, target='Monster/A.inf', source=None):
    return {'format':n.FORMAT,'files':[{'path':target,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      **({'template':source} if source else {}),'operations':ops or []}]}


def test_snapshot_noop_preserves_bytes(tmp_path):
    game,src=env(tmp_path)
    report=n.build_overlay(spec(src),game,tmp_path/'out')
    assert pathlib.Path(report['files'][0]['output']).read_bytes()==src.read_bytes()
    assert report['status']=='OVERLAY_READY_REQUIRES_NATIVE_IMPORT'
    assert not report['identity_review_required']
    assert src.read_bytes().decode('cp949').count('*레벨')==2


def test_set_occurrence_preserves_other_lines(tmp_path):
    game,src=env(tmp_path)
    report=n.build_overlay(spec(src,[{'op':'set','key':'*레벨','values':[47],'occurrence':1}]),game,tmp_path/'out')
    raw=pathlib.Path(report['files'][0]['output']).read_bytes()
    assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n',b'')
    text=raw.decode('cp949')
    assert '*레벨 10\r\n*레벨 47' in text and '// note' in text
    assert '*E_NAME Alpha' in text
    assert '*레벨 11' not in text
    assert src.read_bytes().decode('cp949').count('*레벨 11')==1


def test_new_entity_requires_review_and_source_unchanged(tmp_path):
    game,src=env(tmp_path)
    report=n.build_overlay(spec(src,[{'op':'set','key':'*이름','values':['Monstro Novo']}],
                                target='Monster/New.inf',source='Monster/A.inf'),game,tmp_path/'out')
    assert report['identity_review_required']
    assert report['files'][0]['new_entity']
    assert (game/'assets'/'GameServer'/'Monster'/'New.inf').exists() is False
    assert b'Monstro' in pathlib.Path(report['files'][0]['output']).read_bytes()


def test_hash_anchors_reject_changed_source(tmp_path):
    game,src=env(tmp_path)
    recipe=spec(src)
    src.write_bytes(src.read_bytes()+b'//changed\r\n')
    with pytest.raises(ValueError,match='CHANGED'):
        n.build_overlay(recipe,game,tmp_path/'out')


def test_ambiguous_duplicate_key_requires_occurrence(tmp_path):
    game,src=env(tmp_path)
    with pytest.raises(ValueError,match='EXACT_MATCH'):
        n.build_overlay(spec(src,[{'op':'set','key':'*레벨','values':[20]}]),game,tmp_path/'out')


def test_bad_content_is_rejected_before_any_output(tmp_path):
    game,src=env(tmp_path)
    attacks=[('Monster/../A.inf',[]),('Monster\\A.inf',[]),
             ('Monster/A.inf',[{'op':'append','key':'*Name','values':['bad\nline']}]),
             ('Monster/A.inf',[{'op':'append','key':'*연결파일','values':['../evil']}]),
             ('Monster/A.inf',[{'op':'append','key':'*Name','values':['🙂']}])]
    for path,ops in attacks:
        with pytest.raises((ValueError,UnicodeEncodeError)):
            n.build_overlay(spec(src,ops,target=path),game,tmp_path/'out')
    assert not (tmp_path/'out'/'native_pipeline').exists()


def test_manifest_private_path_and_hash_check(tmp_path):
    game,src=env(tmp_path)
    root=tmp_path/'out'
    report=n.build_overlay(spec(src),game,root)
    obj,fp=n._load_manifest(pathlib.Path(report['manifest']),root)
    assert len(obj['files'])==1
    pathlib.Path(report['files'][0]['output']).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='HASH'):
        n._load_manifest(fp,root)


def test_verify_plan_does_not_copy_source_or_make_database(tmp_path):
    game,src=env(tmp_path)
    root=tmp_path/'out'
    report=n.build_overlay(spec(src),game,root)
    plan=n.verify_overlay(pathlib.Path(report['manifest']),game,root)
    assert plan['status']=='PLAN_ONLY'
    assert not list(root.rglob('*.sqlite'))


def fake_db(path, source, *, extra_unresolved=False):
    with sqlite3.connect(path) as db:
        for name in ('items','monsters','npcs','fields'):
            db.execute(f'CREATE TABLE {name} (id INTEGER)')
        db.execute('CREATE TABLE world_import_unresolved_refs (kind TEXT, owner_key TEXT, raw_reference TEXT)')
        db.execute('CREATE TABLE world_source_files (source_path TEXT, sha256 TEXT)')
        db.execute('CREATE TABLE world_entity_variants (source_path TEXT, kind TEXT, is_catalog_entry INTEGER)')
        for path in source.rglob('*'):
            if not path.is_file(): continue
            rel=path.relative_to(source).as_posix()
            db.execute('INSERT INTO world_source_files VALUES (?,?)',(rel,hashlib.sha256(path.read_bytes()).hexdigest()))
            if path.suffix=='.inf':
                db.execute('INSERT INTO world_entity_variants VALUES (?,?,?)',(rel,'monster',1))
        # Simulate the semantic parser reading *레벨 into the native catalog.
        import re
        mon=(source/'Monster'/'A.inf').read_bytes().decode('cp949')
        levels=re.findall(r'\*레벨\s+(\d+)',mon)
        db.execute('INSERT INTO monsters VALUES (?)',(int(levels[0]),))
        db.execute('INSERT INTO world_import_unresolved_refs VALUES (?,?,?)',('monster_drop','Prior','OLD_CODE'))
        if extra_unresolved:
            db.execute('INSERT INTO world_import_unresolved_refs VALUES (?,?,?)',('monster_drop','New','BROKEN_CODE'))


def test_semantic_diff_detects_new_errors_not_preexisting_ones(tmp_path,monkeypatch):
    game,src=env(tmp_path)
    project=game/'tools'/'PristonTale.WorldImport'/'PristonTale.WorldImport.csproj'
    project.parent.mkdir(parents=True); project.touch()
    for extra,expected in [(False,'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED'),(True,'FAILED_NATIVE_SEMANTICS')]:
        work=tmp_path/('out1' if extra else 'out0')
        report=n.build_overlay(spec(src,[{'op':'set','key':'*레벨','values':[22],'occurrence':0}]),game,work)
        def execute(repo,proj,source,db,empty,*,build):
            fake_db(db,source,extra_unresolved=extra and source.name=='candidate')
            return {'exit_code':0,'steps':[]}
        monkeypatch.setattr(n.shutil,'which',lambda name:'/fake/dotnet')
        monkeypatch.setattr(n,'_execute_import',execute)
        result=n.verify_overlay(pathlib.Path(report['manifest']),game,work,execute=True)
        assert result['status']==expected
        assert not result['game_assets_modified']
        assert len(result['new_unresolved'])==int(extra)
        assert src.read_bytes().decode('cp949').count('*레벨 10')==1


def test_cli_registration_available():
    import argparse
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd')
    n.register(sub)
    for name in ('native-content-snapshot','native-content-build','native-content-verify'):
        assert name in sub.choices
