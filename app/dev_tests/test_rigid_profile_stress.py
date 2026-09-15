import json
from pathlib import Path
from types import SimpleNamespace

import pt_asset_tool.rigid_authoring_stress as stress
import pt_asset_tool.rigid_authoring_evidence as evidence


def _context():
    return {
        "format": "PT_ASSET_SELECTED_AUTHORING_CONTEXT_V1",
        "model_info_inx": {"logical": "char/x/a.inx", "path": "/client/char/x/a.inx", "size": 1, "sha256": "a"*64},
        "skeleton_smb": {"logical": "char/x/a.smb", "path": "/client/char/x/a.smb", "size": 1, "sha256": "b"*64},
        "lod": "default",
        "lod_groups": {"high": ["H1","H2"], "default": ["M1","M2"], "low": ["L1","L2"]},
        "lod_groups_signature": "c"*64,
        "selected_lod_nodes": ["M1","M2"],
        "selection_basis": {"kind":"CANONICAL_PROFILE","profile_id":"p","profile_version":3,"roundtrip_target":"char/x/model.smd"},
    }


def _plan(names=("H1","H2","M1","M2","L1","L2")):
    return {"source_analysis":{"objects":[
        {"name":n,"physique":True,"has_object_local_animation":False,"faces":3,"vertices":4,"texlink_min_layers":1,"texlink_max_layers":1}
        for n in names
    ]}}


def test_stress_scope_is_all_profile_lods_not_just_selected_lod():
    scope=stress.inspect_rigid_profile_stress_scope(_plan(),_context())
    assert scope["canonical_profile_context"] is True
    assert scope["scope_complete"] is True
    assert scope["all_lods_present"] is True
    assert scope["eligible_objects"] == ["H1","H2","M1","M2","L1","L2"]
    assert scope["object_lods"]["H1"] == "high"
    assert scope["object_lods"]["M2"] == "default"
    assert scope["object_lods"]["L1"] == "low"


def test_stress_scope_fails_closed_if_any_profile_mesh_missing():
    scope=stress.inspect_rigid_profile_stress_scope(_plan(("H1","H2","M1","M2","L1")),_context())
    assert scope["scope_complete"] is False
    assert scope["missing_or_ineligible_objects"] == ["L2"]


def test_stress_context_key_is_deterministic_and_object_set_sensitive():
    a=stress.stress_context_key("char/x/model.smd",_context(),["H1","M1","L1"])
    b=stress.stress_context_key("char/x/model.smd",_context(),["L1","H1","M1"])
    c=stress.stress_context_key("char/x/model.smd",_context(),["H1","M1","L2"])
    assert a == b
    assert a.startswith("RIGIDSTRESS-")
    assert a != c


def test_verify_stress_artifact_requires_every_target_edit(tmp_path, monkeypatch):
    project=tmp_path/'app'; project.mkdir()
    artifact=project/'pt_build'/'candidate_stress'/'model.smd'; artifact.parent.mkdir(parents=True); artifact.write_bytes(b'out')
    source=tmp_path/'client'/'model.smd'; source.parent.mkdir(); source.write_bytes(b'src')
    prov=artifact.with_suffix('.smd.build.json')
    data={
        'build_mode':'CANDIDATE_RIGID_STRESS','build_status':'PASS','production_authorized':False,
        'selected_context':_context(),
        'evidence':{
            'stress_profile':True,'candidate_objects':['H1','H2','M1','M2','L1','L2'],
            'stress_object_lods':{'H1':'high','H2':'high','M1':'default','M2':'default','L1':'low','L2':'low'},
            'verification_status':'PASS','all_target_edits_observed':True,'targets_without_observed_edit':[],
            'edit_observed_by_object':{x:True for x in ['H1','H2','M1','M2','L1','L2']},
            'verification_errors':[],'non_target_changed':[],'unknown_physique_bones_by_object':{},
        }
    }
    prov.write_text(json.dumps(data))
    asset=SimpleNamespace(asset_id='AST-1',primary_path='char/x/model.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE')
    class Resolver:
        def resolve(self,*a,**k): return source
    monkeypatch.setattr(evidence,'verify_build_provenance',lambda *a,**k:{'status':'PASS','errors':[]})
    monkeypatch.setattr(evidence,'verify_selected_context_for_asset',lambda *a,**k:{'status':'PASS','errors':[]})
    monkeypatch.setattr(evidence,'authoring_plan',lambda *a,**k:_plan())
    ok=evidence.verify_rigid_candidate_artifact(project,Resolver(),asset,artifact)
    assert ok['status']=='PASS'
    assert ok['stress_profile'] is True
    assert len(ok['candidate_objects']) == 6
    assert ok['ready_for_human_review'] is True

    data['evidence']['all_target_edits_observed']=False
    data['evidence']['targets_without_observed_edit']=['L2']
    prov.write_text(json.dumps(data))
    bad=evidence.verify_rigid_candidate_artifact(project,Resolver(),asset,artifact)
    assert bad['status']=='FAIL'
    assert 'STRESS_ALL_TARGET_EDITS_NOT_OBSERVED' in bad['errors']


def test_cli_stress_review_records_all_profile_objects_with_one_human_decision(tmp_path, monkeypatch, capsys):
    import pt_asset_tool.cli as cli
    source=tmp_path/'source.smd'; source.write_bytes(b'src')
    artifact=tmp_path/'app'/'pt_build'/'candidate_stress'/'out.smd'; artifact.parent.mkdir(parents=True); artifact.write_bytes(b'out')
    asset=SimpleNamespace(asset_id='AST-1',primary_path='char/x/model.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE')
    class Reg:
        def resolve(self,target): return asset
    class Resolver:
        def resolve(self,*a,**k): return source
    class Cert:
        def __init__(self): self.rows=[]
        def add(self,**kwargs): self.rows.append(kwargs); return {'certification_id':f'C{len(self.rows)}',**kwargs}
    cert=Cert(); settings=SimpleNamespace(project_root=tmp_path/'app')
    monkeypatch.setattr(cli,'make_context',lambda a:(settings,Reg(),cert,Resolver()))
    ctx=_context(); objs=['H1','H2','M1','M2','L1','L2']
    verified={
        'status':'PASS','stress_profile':True,'context_key':'RIGIDSTRESS-X','artifact':str(artifact),'artifact_sha256':'d'*64,
        'provenance':str(artifact)+'.build.json','candidate_objects':objs,
        'stress_object_lods':{'H1':'high','H2':'high','M1':'default','M2':'default','L1':'low','L2':'low'},
        'selected_context':ctx,
        'evidence':{'edit_observed_by_object':{x:True for x in objs},'unknown_physique_bones_by_object':{},'non_target_changed':[],'verification_errors':[]},
    }
    monkeypatch.setattr(cli,'verify_rigid_candidate_review_workspace',lambda *a,**k:{
        'status':'PASS','artifact_verification':verified,'review_manifest':'review.json','review':{'review_blend':'review.blend','review_blend_sha256':'e'*64}
    })
    args=SimpleNamespace(target=asset.primary_path,artifact=str(artifact),result='PASS',notes='full stress looks correct')
    assert cli.cmd_cert_rigid_candidate_review(args)==0
    assert len(cert.rows)==12
    assert sum(1 for x in cert.rows if x['layer']==evidence.AUTOMATIC_LAYER)==6
    assert sum(1 for x in cert.rows if x['layer']==evidence.HUMAN_LAYER)==6
    out=json.loads(capsys.readouterr().out)
    assert out['format']=='PT_RIGID_PROFILE_STRESS_CANDIDATE_REVIEW_V1'
    assert out['reviewed_context_count']==6
    assert out['context_pass'] is True
    assert out['production_authorized'] is False


def test_build_parser_exposes_stress_profile_flag():
    import pt_asset_tool.cli as cli
    parser=cli.build_parser()
    args=parser.parse_args(['build','char/x/model.smd','--candidate','--stress-profile'])
    assert args.candidate is True
    assert args.stress_profile is True

def test_cli_stress_build_orchestrates_all_targets_once(tmp_path, monkeypatch, capsys):
    import pt_asset_tool.cli as cli
    project=tmp_path/'app'; project.mkdir()
    source=tmp_path/'source.smd'; source.write_bytes(b'source')
    skeleton=tmp_path/'skeleton.smb'; skeleton.write_bytes(b'skeleton')
    blend=project/'pt_build'/'blender_edits'/'imported.blend'; blend.parent.mkdir(parents=True); blend.write_bytes(b'blend')
    output=project/'pt_build'/'candidate_stress'/'model.smd'
    asset=SimpleNamespace(asset_id='AST-1',primary_path='char/x/model.smd',kind='SMD_MODEL_062',family='SMD_MODEL_062_RIGID_PHYSIQUE')
    class Reg:
        def resolve(self,target): return asset
    settings=SimpleNamespace(project_root=project)
    monkeypatch.setattr(cli,'make_context',lambda a:(settings,Reg(),object(),object()))
    monkeypatch.setattr(cli,'build_plan',lambda a:{'authorized':False})
    monkeypatch.setattr(cli,'authoring_plan',lambda *a,**k:{})
    ctx=_context(); objects=['H1','H2','M1','M2','L1','L2']
    plan={
        'format':stress.FORMAT,'status':'READY','source':str(source),'source_sha256':cli.sha256_file(source),
        'skeleton':str(skeleton),'selected_context':ctx,'blend':str(blend),'objects':objects,
        'object_lods':{'H1':'high','H2':'high','M1':'default','M2':'default','L1':'low','L2':'low'},
        'output':str(output),'blockers':[],
    }
    monkeypatch.setattr(cli,'plan_rigid_profile_stress_candidate',lambda *a,**k:dict(plan))
    monkeypatch.setattr(cli,'build_rigid_candidate_blender_command',lambda settings,candidate,report:['fake',str(report),str(candidate['output'])])
    def fake_run(cmd, log):
        report=Path(cmd[1]); out=Path(cmd[2]); report.parent.mkdir(parents=True,exist_ok=True); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes((Path(plan['source']).read_bytes() if Path(plan['source']).is_file() else b'') + out.name.encode())
        report.write_text(json.dumps({'tool':'writer','source_counts':{'vertices':3},'output_counts':{'vertices':3},'unrelated_object_blocks_byte_identical':5,'max_vertex_fit_error':0.0,'output_sha256':cli.sha256_file(out)}))
        Path(log).parent.mkdir(parents=True,exist_ok=True); Path(log).write_text('ok')
    monkeypatch.setattr(cli,'run_logged',fake_run)
    monkeypatch.setattr(cli,'validate_rigid_profile_stress_output',lambda *a,**k:{
        'format':stress.VERIFY_FORMAT,'status':'PASS','edit_observed_by_object':{x:True for x in objects},
        'all_target_edits_observed':True,'targets_without_observed_edit':[],'unknown_physique_bones_by_object':{},
        'targets':{},'non_target_changed':[],'errors':[],'candidate_only':True,'production_authorized':False,'client_write_authorized':False,'client_modified':False,
    })
    monkeypatch.setattr(cli,'write_build_provenance',lambda output,**kwargs: output.with_suffix(output.suffix+'.build.json'))
    args=SimpleNamespace(target=asset.primary_path,plan=False,candidate=True,stress_profile=True,object=None,require_edit=False,output=None)
    assert cli.cmd_build_asset(args)==0
    shown=json.loads(capsys.readouterr().out)
    assert shown['status']=='PASS'
    assert shown['candidate_kind']=='RIGID_STRESS'
    assert shown['writer_report']['step_count']==6
    assert [x['object'] for x in shown['writer_report']['steps']]==objects
    assert shown['verification']['all_target_edits_observed'] is True
    assert shown['production_authorized'] is False
