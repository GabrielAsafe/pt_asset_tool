import json
from pathlib import Path
from types import SimpleNamespace

import pt_asset_tool.rigid_authoring_evidence as mod


def _context():
    return {
        "format": "PT_ASSET_SELECTED_AUTHORING_CONTEXT_V1",
        "model_info_inx": {"logical": "char/x/a.inx", "path": "/client/char/x/a.inx", "size": 1, "sha256": "a" * 64},
        "skeleton_smb": {"logical": "char/x/a.smb", "path": "/client/char/x/a.smb", "size": 2, "sha256": "b" * 64},
        "lod": "default",
        "lod_groups": {"high": ["Hi"], "default": ["Body"], "low": ["Lo"]},
        "lod_groups_signature": "c" * 64,
        "selected_lod_nodes": ["Body"],
        "selection_basis": {"kind": "CANONICAL_PROFILE", "profile_id": "p", "profile_version": 3, "roundtrip_target": "char/x/model.smd"},
    }


def test_candidate_provenance_evidence_captures_controlled_edit_contract():
    ev = mod.build_candidate_provenance_evidence(
        "RIGID",
        {"object": "Body", "selected_context": _context()},
        {"tool": "writer", "output_sha256": "d" * 64, "source_counts": {"vertices": 3}, "output_counts": {"vertices": 3}, "unrelated_object_blocks_byte_identical": 4, "max_vertex_fit_error": 0.0},
        {"format": "VERIFY", "status": "PASS", "edit_observed": True, "errors": [], "non_target_changed": [], "unknown_physique_bones": [], "target": {"target_block_byte_identical": False}},
        require_edit=True,
    )
    assert ev["candidate_object"] == "Body"
    assert ev["selected_lod"] == "default"
    assert ev["profile_id"] == "p"
    assert ev["edit_observed"] is True
    assert ev["edit_required"] is True
    assert ev["non_target_changed"] == []
    assert ev["unknown_physique_bones"] == []
    assert ev["unrelated_object_blocks_byte_identical"] == 4


def test_rigid_context_key_changes_with_lod_or_object():
    a = mod.rigid_candidate_context_key("char/x/model.smd", _context(), "Body")
    bctx = _context(); bctx["lod"] = "high"; bctx["selected_lod_nodes"] = ["Hi"]
    b = mod.rigid_candidate_context_key("char/x/model.smd", bctx, "Body")
    c = mod.rigid_candidate_context_key("char/x/model.smd", _context(), "Other")
    assert a.startswith("RIGIDCTX-")
    assert len({a, b, c}) == 3


def test_verify_rigid_candidate_requires_observed_edit_and_clean_scope(tmp_path, monkeypatch):
    project = tmp_path / "app"; project.mkdir()
    build = project / "pt_build" / "candidate"; build.mkdir(parents=True)
    artifact = build / "model.smd"; artifact.write_bytes(b"candidate")
    source = tmp_path / "client" / "model.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    prov = artifact.with_suffix(".smd.build.json")
    data = {
        "format": "PT_ASSET_BUILD_PROVENANCE_V1",
        "asset_id": "AST-1", "asset": "char/x/model.smd", "family": "SMD_MODEL_062_RIGID_PHYSIQUE", "kind": "SMD_MODEL_062",
        "source": {"path": str(source), "sha256": mod.sha256_file(source), "size": source.stat().st_size},
        "artifact": {"path": str(artifact), "sha256": mod.sha256_file(artifact), "size": artifact.stat().st_size},
        "build_mode": "CANDIDATE_RIGID", "adapter": "writer", "build_status": "PASS", "production_authorized": False, "client_write_authorized": False,
        "selected_context": _context(),
        "evidence": {"candidate_object": "Body", "verification_status": "PASS", "edit_observed": True, "verification_errors": [], "non_target_changed": [], "unknown_physique_bones": []},
        "client_modified": False,
    }
    prov.write_text(json.dumps(data))
    asset = SimpleNamespace(asset_id="AST-1", primary_path="char/x/model.smd", family="SMD_MODEL_062_RIGID_PHYSIQUE")
    class Resolver:
        def resolve(self, logical, required=True): return source
    monkeypatch.setattr(mod, "verify_build_provenance", lambda *a, **k: {"status":"PASS", "errors":[], "selected_context": _context()})
    monkeypatch.setattr(mod, "verify_selected_context_for_asset", lambda *a, **k: {"status":"PASS", "errors":[]})
    monkeypatch.setattr(mod, "authoring_plan", lambda *a, **k: {"source_analysis": {"objects": [{"name":"Body","physique":True,"has_object_local_animation":False,"faces":1,"vertices":3,"texlink_min_layers":1,"texlink_max_layers":1}]}})
    ok = mod.verify_rigid_candidate_artifact(project, Resolver(), asset, artifact)
    assert ok["status"] == "PASS"
    assert ok["ready_for_human_review"] is True

    data["evidence"]["edit_observed"] = False
    prov.write_text(json.dumps(data))
    bad = mod.verify_rigid_candidate_artifact(project, Resolver(), asset, artifact)
    assert bad["status"] == "FAIL"
    assert "CONTROLLED_EDIT_NOT_OBSERVED" in bad["errors"]


def test_certification_plan_requires_automatic_and_human_pass(tmp_path, monkeypatch):
    profile = SimpleNamespace(
        profile_id="p", profile_version=1, roundtrip_target="char/x/model.smd",
        lod_groups={"high":["H"], "default":["M"], "low":["L"]},
    )
    class Profiles:
        def list(self): return [profile]
        def get(self, profile_id): assert profile_id == "p"; return profile
    asset = SimpleNamespace(asset_id="AST-1", primary_path="char/x/model.smd")
    class Assets:
        def resolve(self, path): return asset
    source = tmp_path / "model.smd"; source.write_bytes(b"x")
    class Resolver:
        def resolve(self, path, required=True): return source
    monkeypatch.setattr(mod, "authoring_plan", lambda *a, **k: {"source_analysis":{"objects":[
        {"name":"H","physique":True,"has_object_local_animation":False,"faces":1,"vertices":3,"texlink_min_layers":1,"texlink_max_layers":1},
        {"name":"M","physique":True,"has_object_local_animation":False,"faces":1,"vertices":3,"texlink_min_layers":1,"texlink_max_layers":1},
        {"name":"L","physique":True,"has_object_local_animation":False,"faces":1,"vertices":3,"texlink_min_layers":1,"texlink_max_layers":1},
    ]}})
    meta={"rigid_candidate_context_key":"K","profile_id":"p","lod":"default","object":"M","asset":"char/x/model.smd","artifact_sha256":"a"*64}
    class Certs:
        def records(self): return [
            {"test":mod.AUTOMATIC_TEST,"layer":mod.AUTOMATIC_LAYER,"result":"PASS","metadata":meta},
            {"test":mod.AUTOMATIC_TEST,"layer":mod.HUMAN_LAYER,"result":"PASS","metadata":meta},
        ]
    result=mod.build_rigid_authoring_certification_plan(Profiles(), Assets(), Resolver(), Certs(), profile_id="p")
    assert result["row_count"] == 3
    assert result["controlled_edit_pass_count"] == 1
    assert result["human_review_pass_count"] == 1
    assert result["context_pass_count"] == 1
    row=[r for r in result["rows"] if r["lod"]=="default"][0]
    assert row["context_pass"] is True
    assert row["review_matches_candidate_artifact"] is True
    assert row["production_authorized"] is False

    class CertsMismatch:
        def records(self): return [
            {"test":mod.AUTOMATIC_TEST,"layer":mod.AUTOMATIC_LAYER,"result":"PASS","artifact_sha256":"a"*64,"metadata":meta},
            {"test":mod.AUTOMATIC_TEST,"layer":mod.HUMAN_LAYER,"result":"PASS","artifact_sha256":"b"*64,"metadata":meta},
        ]
    mismatch=mod.build_rigid_authoring_certification_plan(Profiles(), Assets(), Resolver(), CertsMismatch(), profile_id="p")
    mrow=[r for r in mismatch["rows"] if r["lod"]=="default"][0]
    assert mrow["review_matches_candidate_artifact"] is False
    assert mrow["context_pass"] is False


def test_cli_rigid_candidate_review_records_automatic_and_human_layers(tmp_path, monkeypatch, capsys):
    import pt_asset_tool.cli as cli
    source = tmp_path / "source.smd"; source.write_bytes(b"src")
    artifact = tmp_path / "app" / "pt_build" / "out.smd"; artifact.parent.mkdir(parents=True); artifact.write_bytes(b"out")
    asset = SimpleNamespace(asset_id="AST-1", primary_path="char/x/model.smd", family="SMD_MODEL_062_RIGID_PHYSIQUE")
    class Reg:
        def resolve(self, target): return asset
    class Resolver:
        def resolve(self, logical, required=True): return source
    class Cert:
        def __init__(self): self.rows=[]
        def add(self, **kwargs): self.rows.append(kwargs); return {"certification_id": f"CERT-{len(self.rows)}", **kwargs}
    cert=Cert()
    settings=SimpleNamespace(project_root=tmp_path / "app")
    monkeypatch.setattr(cli, "make_context", lambda a: (settings, Reg(), cert, Resolver()))
    verified = {
        "status":"PASS", "errors":[], "artifact":str(artifact), "artifact_sha256":"d"*64, "provenance":str(artifact)+".build.json",
        "candidate_object":"Body", "context_key":"RIGIDCTX-K",
        "selected_context": {"lod":"default", "selection_basis":{"profile_id":"p","profile_version":1}, "model_info_inx":{"logical":"a.inx"}, "skeleton_smb":{"logical":"a.smb"}, "lod_groups_signature":"e"*64},
        "evidence":{"edit_observed":True,"non_target_changed":[],"unknown_physique_bones":[],"verification_errors":[]},
        "provenance_verification": {"status":"PASS"},
    }
    monkeypatch.setattr(cli, "verify_rigid_candidate_review_workspace", lambda *a, **k: {
        "status":"PASS", "errors":[], "artifact_verification":verified, "review_manifest":"review.json",
        "review":{"review_blend":"review.blend","review_blend_sha256":"f"*64},
    })
    args=SimpleNamespace(target="char/x/model.smd", artifact=str(artifact), result="PASS", notes="looks correct")
    assert cli.cmd_cert_rigid_candidate_review(args) == 0
    assert len(cert.rows) == 2
    assert cert.rows[0]["layer"] == mod.AUTOMATIC_LAYER
    assert cert.rows[1]["layer"] == mod.HUMAN_LAYER
    assert cert.rows[0]["result"] == "PASS"
    assert cert.rows[1]["result"] == "PASS"
    out=json.loads(capsys.readouterr().out)
    assert out["context_pass"] is True
    assert out["production_authorized"] is False


def test_candidate_review_workspace_is_bound_to_artifact_hash_and_context(tmp_path, monkeypatch):
    project=tmp_path/'app'; project.mkdir()
    artifact=project/'pt_build'/'candidate'/'model.smd'; artifact.parent.mkdir(parents=True); artifact.write_bytes(b'candidate')
    inx=tmp_path/'client'/'a.inx'; inx.parent.mkdir(); inx.write_bytes(b'i')
    smb=tmp_path/'client'/'a.smb'; smb.write_bytes(b's')
    context=_context(); context['model_info_inx']['path']=str(inx); context['model_info_inx']['size']=1; context['model_info_inx']['sha256']=mod.sha256_file(inx)
    context['skeleton_smb']['path']=str(smb); context['skeleton_smb']['size']=1; context['skeleton_smb']['sha256']=mod.sha256_file(smb)
    verified={
        'status':'PASS','errors':[],'artifact':str(artifact),'artifact_sha256':mod.sha256_file(artifact),
        'candidate_object':'Body','context_key':'RIGIDCTX-TEST','selected_context':context,
    }
    monkeypatch.setattr(mod,'verify_rigid_candidate_artifact',lambda *a,**k: dict(verified))
    overlay=tmp_path/'overlay'; overlay.mkdir()
    monkeypatch.setattr(mod,'prepare_texture_overlay',lambda **k:(overlay,{'ready':True}))
    def fake_run(cmd, log):
        out=Path(cmd[cmd.index('--out')+1]); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(b'blend')
    monkeypatch.setattr(mod,'run_logged',fake_run)
    settings=SimpleNamespace(project_root=project, blender_command=lambda:['blender'])
    asset=SimpleNamespace(asset_id='AST-1',primary_path='char/x/model.smd')
    result=mod.prepare_rigid_candidate_review_workspace(settings, object(), asset, artifact)
    assert result['status']=='READY_FOR_HUMAN_VISUAL_REVIEW'
    assert Path(result['review_blend']).is_file()
    assert result['artifact_sha256']==mod.sha256_file(artifact)
    checked=mod.verify_rigid_candidate_review_workspace(settings, object(), asset, artifact)
    assert checked['status']=='PASS'
    artifact.write_bytes(b'drift')
    verified['artifact_sha256']=mod.sha256_file(artifact)
    checked2=mod.verify_rigid_candidate_review_workspace(settings, object(), asset, artifact)
    assert checked2['status']=='FAIL'
    assert 'CANDIDATE_REVIEW_ARTIFACT_DRIFT' in checked2['errors']


def test_certification_plan_surfaces_external_report_without_counting_it_as_verified(tmp_path, monkeypatch):
    profile_dir=tmp_path/'data'/'character_profiles'; profile_dir.mkdir(parents=True)
    evdir=tmp_path/'data'/'development_evidence'; evdir.mkdir()
    (evdir/'rigid_saved_blender_external_witnesses_v1.json').write_text(json.dumps({
        'witnesses':[{'status':'PASS_REPORTED','asset':'char/x/model.smd','profile_id':'p','lod':'default','object':'M','artifact_sha256':'a'*64}]
    }))
    profile=SimpleNamespace(profile_id='p',profile_version=1,roundtrip_target='char/x/model.smd',lod_groups={'high':['H'],'default':['M'],'low':['L']})
    class Profiles:
        directory=profile_dir
        def list(self): return [profile]
        def get(self,p): return profile
    asset=SimpleNamespace(asset_id='AST-1',primary_path='char/x/model.smd')
    class Assets:
        def resolve(self,p): return asset
    source=tmp_path/'model.smd'; source.write_bytes(b'x')
    class Resolver:
        def resolve(self,p,required=True): return source
    class Certs:
        def records(self): return []
    monkeypatch.setattr(mod,'authoring_plan',lambda *a,**k:{'source_analysis':{'objects':[
        {'name':n,'physique':True,'has_object_local_animation':False,'faces':1,'vertices':3,'texlink_min_layers':1,'texlink_max_layers':1} for n in ('H','M','L')
    ]}})
    result=mod.build_rigid_authoring_certification_plan(Profiles(),Assets(),Resolver(),Certs(),profile_id='p')
    assert result['external_real_blender_reported_count']==1
    row=[r for r in result['rows'] if r['lod']=='default'][0]
    assert row['external_real_blender_reported'] is True
    assert row['controlled_edit_proven'] is False
    assert row['context_pass'] is False
