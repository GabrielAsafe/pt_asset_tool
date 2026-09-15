from __future__ import annotations
from types import SimpleNamespace
from pathlib import Path
import pt_asset_tool.motion_core as mc


def test_standalone_smb_payload_uses_existing_tmframe_containers(monkeypatch,tmp_path):
    smb_path=tmp_path/'x.smb'; smb_path.write_bytes(b'x')
    smb={
        'header_frames':[{'slot':0,'start':0,'end':480,'pos_num':0,'pos_cnt':2}],
        'bones':[{'name':'Bone','parent_name':'','tm':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],'rot':[1,2],'pos':[1],'scale':[]}],
        'tm_sort':[0],
    }
    class Ev:
        def parse_smb(self,p): return smb
        def evaluate_pose(self,s,frame,end):
            m=[1,0,0,0,0,1,0,0,0,0,1,0,frame/160.0,0,0,1]
            return [m],None,None,{}
    monkeypatch.setattr(mc,'load_smb_evaluator',lambda root:Ev())
    payload=mc.build_standalone_smb_bake_payload(tmp_path,smb_path,max_actions=2,max_frames_per_action=20)
    assert payload['source_mode']=='STANDALONE_SMB_TMFRAME'
    assert payload['inx']==''
    assert len(payload['actions'])==1
    assert payload['actions'][0]['frame_count']==3
    assert payload['actions'][0]['frames'][-1]['matrices'][0][12]==2.0
    assert payload['track_key_counts']=={'rot':2,'pos':1,'scale':0}
    assert payload['client_modified'] is False


def test_smb_animation_census_is_corpus_wide_and_domain_attributed(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import pt_asset_tool.standalone_animation_devtest as sad
    p1=tmp_path/'char'/'tmABCD'/'m5.smb'; p1.parent.mkdir(parents=True); p1.write_bytes(b'x')
    p2=tmp_path/'Effect'/'Fx'/'fx.smb'; p2.parent.mkdir(parents=True); p2.write_bytes(b'x')
    records=[
        {'extension':'.smb','relative_path':'char/tmABCD/m5.smb','category_hint':'CHARACTER'},
        {'extension':'.smb','relative_path':'Effect/Fx/fx.smb','category_hint':'EFFECT'},
    ]
    class Resolver:
        def resolve(self,logical,required=True): return tmp_path/Path(logical)
    class Ev:
        def parse_smb(self,p):
            if p.name=='m5.smb':
                return {'header_frames':[{'slot':0,'start':0,'end':320}], 'bones':[{'rot':[1], 'pos':[], 'scale':[]}]}
            return {'header_frames':[{'slot':0,'start':0,'end':0}], 'bones':[{'rot':[], 'pos':[], 'scale':[]}]}
    monkeypatch.setattr(sad,'load_smb_evaluator',lambda root:Ev())
    report=sad.audit_smb_animation_corpus(SimpleNamespace(records=records),Resolver())
    assert report['status']=='PASS'
    assert report['smb_file_count']==2
    assert report['parse_pass_count']==2
    assert report['animated_smb_file_count']==1
    assert report['by_domain']['PLAYER']['animated_smb_file_count']==1
    assert report['by_domain']['EFFECT']['animated_smb_file_count']==0
    assert report['animated_rows'][0]['path']=='char/tmABCD/m5.smb'


def test_smb_animation_census_fails_closed_on_unparseable_physical_file(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import pt_asset_tool.standalone_animation_devtest as sad
    p=tmp_path/'Effect'/'Fx'/'bad.smb'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    records=[{'extension':'.smb','relative_path':'Effect/Fx/bad.smb','category_hint':'EFFECT'}]
    class Resolver:
        def resolve(self,logical,required=True): return tmp_path/Path(logical)
    class Ev:
        def parse_smb(self,p): raise ValueError('bad smb')
    monkeypatch.setattr(sad,'load_smb_evaluator',lambda root:Ev())
    report=sad.audit_smb_animation_corpus(SimpleNamespace(records=records),Resolver())
    assert report['status']=='FAIL'
    assert report['failure_count']==1
    assert report['client_modified'] is False
