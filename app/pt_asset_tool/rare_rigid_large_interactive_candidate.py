from __future__ import annotations
import argparse, contextlib, hashlib, json, pathlib, shutil, sys
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .utils import run_logged
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from . import rare_rigid_edit as redit
from . import rare_rigid_multivertex as mv
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, PROBE_MAX, _safe_rows, _beam_candidate_sets
from .rare_rigid_large_live_writer_candidate import _candidate_live_write
from .rare_rigid_multibone_bridge import TARGET

FORMAT='PT_RARE_RIGID_LARGE_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V2'
PREP_FORMAT='PT_RARE_RIGID_LARGE_INTERACTIVE_CANDIDATE_WORKSPACE_V2'
RELEASE_VERSION='0.8.19'
PRIOR='pt_build/rare_rigid_large_live_writer_candidate_workflow_v0817.json'
TARGET_COUNT=5
WORK_REL=pathlib.Path('pt_build/rare_rigid_large_manual_candidate_v0819/at_dragon.smd')
FAILED_V0818=pathlib.Path('pt_build/rare_rigid_large_manual_candidate_v0818/at_dragon.smd/manual_write_result.json')

def _sha256(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def _json(p:pathlib.Path)->dict[str,Any]: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
def _writer_hashes(root:pathlib.Path)->dict[str,str]: return {rel:_sha256(root/rel) for rel in EXPECTED_WRITER_HASHES}
def _cert_sha(c:CertificationRegistry)->str|None: return _sha256(c.path) if c.path.is_file() else None

def _prior(root:pathlib.Path)->dict[str,Any]:
    p=root/PRIOR
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0817_REPORT_MISSING:{p}')
    r=_json(p)
    checks=[r.get('format')=='PT_RARE_RIGID_LARGE_LIVE_WRITER_CANDIDATE_AUDIT_V1',r.get('status')=='PASS',
            int(r.get('candidate_live_writer_max_vertices',-1))==8,int(r.get('production_live_writer_max_vertices',-1))==4,
            r.get('process_local_widening_only') is True,r.get('process_local_limits_restored') is True,
            r.get('production_writer_five_vertex_blocked') is True,r.get('candidate_nine_vertex_blocked') is True,
            r.get('candidate_bounds_negative_blocked') is True,r.get('real_certification_registry_modified') is False,
            r.get('writer_modules_modified') is False,r.get('client_modified') is False,
            r.get('large_transaction_live_write_authorized') is False,r.get('manual_artist_proof_required_before_authorization') is True]
    if not all(checks): raise RuntimeError('PRIOR_V0817_GATE_NOT_STRICT_PASS')
    return r

@contextlib.contextmanager
def _widen():
    a,b=int(redit.MAX_TRANSACTION_VERTICES),int(mv.MAX_TRANSACTION_VERTICES)
    if (a,b)!=(4,4): raise RuntimeError(f'PRODUCTION_LIMIT_NOT_4:{a},{b}')
    redit.MAX_TRANSACTION_VERTICES=PROBE_MAX; mv.MAX_TRANSACTION_VERTICES=PROBE_MAX
    try: yield
    finally: redit.MAX_TRANSACTION_VERTICES=a; mv.MAX_TRANSACTION_VERTICES=b

def _plan_uniform(prepared:pathlib.Path,skeleton:pathlib.Path)->dict[str,Any]:
    safe,_=_safe_rows(prepared,skeleton); attempts=0
    # First prefer physically discovered per-vertex witnesses that already share the same one-step Blender transform.
    for oi,rows in sorted(safe.items()):
        groups:{} = {}
        for r in rows: groups.setdefault((str(r.get('axis')),int(r.get('delta_world_fixed',0))),[]).append(r)
        for (axis,delta),grp in sorted(groups.items(), key=lambda x:(abs(x[0][1]),x[0][0],x[0][1])):
            if len(grp)<TARGET_COUNT or delta==0: continue
            by={int(r['vertex_index']):r for r in grp}
            for combo in _beam_candidate_sets(grp,TARGET_COUNT)[:128]:
                attempts+=1
                changes=[{'object_index':oi,'vertex_index':vi,'after_world_fixed':list(by[vi]['requested_after_world_fixed'])} for vi in combo]
                try:
                    with _widen(): plan=mv.plan_requested_at_dragon_transaction(prepared,skeleton,changes=changes)
                except Exception: continue
                plan['uniform_axis']=axis; plan['uniform_delta_world_fixed']=delta; plan['uniform_delta_world']=float(delta)/256.0; plan['uniform_search_attempts']=attempts
                return plan
    # Conservative fallback: keep a connected five-vertex set, then test small uniform fixed-point translations.
    axis_i={'x':0,'y':1,'z':2}; deltas=(64,-64,32,-32,16,-16,8,-8,4,-4,2,-2,1,-1)
    for oi,rows in sorted(safe.items()):
        by={int(r['vertex_index']):r for r in rows}
        for combo in _beam_candidate_sets(rows,TARGET_COUNT)[:48]:
            for axis in ('x','y','z'):
                for delta in deltas:
                    attempts+=1; changes=[]
                    for vi in combo:
                        before=[int(x) for x in by[vi]['before_world_fixed']]; after=list(before); after[axis_i[axis]]+=delta
                        changes.append({'object_index':oi,'vertex_index':vi,'after_world_fixed':after})
                    try:
                        with _widen(): plan=mv.plan_requested_at_dragon_transaction(prepared,skeleton,changes=changes)
                    except Exception: continue
                    plan['uniform_axis']=axis; plan['uniform_delta_world_fixed']=delta; plan['uniform_delta_world']=float(delta)/256.0; plan['uniform_search_attempts']=attempts
                    return plan
    raise RuntimeError(f'NO_SAFE_UNIFORM_MANUAL_{TARGET_COUNT}_VERTEX_TRANSACTION')



def _failed_v0818(root:pathlib.Path)->dict[str,Any]:
    p=root/FAILED_V0818
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0818_FAIL_REPORT_MISSING:{p}')
    r=_json(p)
    err=str(r.get('error') or '')
    checks=[
        r.get('format')=='PT_RARE_RIGID_LARGE_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
        r.get('status')=='FAIL',
        'REOPEN_SELECTION_MISMATCH:' in err,
        '[0, 1, 2, 3, 4' in err,
        '!=[91, 94, 125, 157, 158]' in err,
        r.get('production_authorized') is False,
        int(r.get('candidate_max_vertices',-1))==8,
        int(r.get('production_writer_max_vertices',-1))==4,
    ]
    if not all(checks): raise RuntimeError('PRIOR_V0818_FAILURE_NOT_EXPECTED_SELECTION_FLUSH_BUG')
    return r

def _baseline_name(path:pathlib.Path,oi:int)->str|None:
    d=_json(path); tiers=[[],[],[],[]]; idxkeys={'object_index','smd_object_index','pt_object_index','source_object_index'}; pri={'blender_object_name':0,'blender_object':0,'mesh_object_name':0,'object_name':1,'mesh_object':1,'head_name':2,'name':3}
    def walk(x):
        if isinstance(x,dict):
            matched=any((str(k).lower() in idxkeys and str(v).lstrip('-').isdigit() and int(v)==oi) for k,v in x.items())
            if matched:
                for k,v in x.items():
                    q=pri.get(str(k).lower())
                    if q is not None and isinstance(v,str) and v.strip(): tiers[q].append(v.strip())
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(d)
    for t in tiers:
        if t: return list(dict.fromkeys(t))[0]
    return None

def _selection(settings:Settings,root:pathlib.Path,blend:pathlib.Path,baseline:pathlib.Path,plan:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    helper=root/'pt_asset_tool/blender/ensure_rare_rigid_large_candidate_selection.py'; verify=root/'pt_asset_tool/blender/verify_rare_rigid_transaction_selection.py'
    oi=int(plan['object_index']); vis=[int(x) for x in plan['changed_vertex_indices']]; vs=','.join(map(str,vis)); name=_baseline_name(baseline,oi)
    prep=work/'selection_prepare.json'; reopen=work/'selection_reopen.json'
    cmd=settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(helper),'--','--blend',str(blend),'--object-index',str(oi),'--vertices',vs,'--report',str(prep)]
    if name: cmd += ['--object-name',name]
    run_logged(cmd,work/'01_prepare_selection.log')
    pr=_json(prep); actual=pr.get('object_name') or name
    cmd=settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(verify),'--','--object-index',str(oi),'--vertices',vs,'--report',str(reopen)]
    if actual: cmd += ['--object-name',str(actual)]
    run_logged(cmd,work/'02_verify_selection.log'); vr=_json(reopen)
    if pr.get('status')!='PASS' or vr.get('status')!='PASS' or vr.get('selected_vertex_indices')!=vis or vr.get('mode_on_reopen')!='EDIT_MESH': raise RuntimeError('LARGE_CANDIDATE_SELECTION_PERSISTENCE_FAIL')
    return {'prepare':pr,'reopen':vr}

def _expected_map(plan:dict[str,Any])->dict[tuple[int,int],list[int]]:
    oi=int(plan['object_index']); return {(oi,int(r['vertex_index'])):[int(x) for x in r['requested_after_world_fixed']] for r in plan['changed_vertices']}

def _preflight(settings:Settings,root:pathlib.Path,blend:pathlib.Path,baseline:pathlib.Path,plan:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    report=work/'manual_preflight_extract.json'; script=root/'pt_asset_tool/blender/extract_rare_rigid_edit.py'
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(script),'--','--baseline',str(baseline),'--report',str(report),'--max-changed',str(PROBE_MAX)],work/'04_manual_preflight.log')
    r=_json(report); expected=_expected_map(plan); changed={(int(x['object_index']),int(x['vertex_index'])):[int(v) for v in x['after_world_fixed']] for x in r.get('changed_vertices') or []}
    if r.get('check')!='PASS' or len(changed)!=TARGET_COUNT or changed!=expected: raise RuntimeError(f'MANUAL_EDIT_NOT_EXACT_PREPARED_TRANSACTION:actual={changed}:expected={expected}')
    return r

def run(root:pathlib.Path,logical:str)->dict[str,Any]:
    root=pathlib.Path(root).resolve()
    if logical!=TARGET: raise RuntimeError(f'ONLY_AT_DRAGON_SUPPORTED:{logical}')
    prior=_prior(root); failed_v0818=_failed_v0818(root); writers_before=_writer_hashes(root)
    if writers_before!=EXPECTED_WRITER_HASHES: raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH')
    settings=Settings.discover(root,None); resolver=ClientResolver(settings.client_root); reg=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    real=CertificationRegistry(settings.certifications_dir); real_count_before=len(real.records()); real_sha_before=_cert_sha(real)
    source=pathlib.Path(resolver.resolve(TARGET,required=True)); source_sha_before=_sha256(source)
    if source_sha_before!=prior.get('client_source_sha256_after'): raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0817')
    work=root/WORK_REL
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    iso=CertificationRegistry(work/'isolated_certifications')
    manifest=prepare_at_dragon_edit_workspace(reg,resolver,iso,settings,project_root=root,open_gui=False,reset=True,workspace_root=work,workspace_origin='USER_V0818_LARGE_INTERACTIVE_CANDIDATE')
    if len(iso.records())!=1 or iso.records()[0].get('test')!='RARE_RIGID_BLENDER_PREVIEW': raise RuntimeError('ISOLATED_PREVIEW_CERT_UNEXPECTED')
    prepared=pathlib.Path(manifest['prepared_source']); skeleton=pathlib.Path(manifest['skeleton']); baseline=pathlib.Path(manifest['baseline_blender_report']); blend=pathlib.Path(manifest['edit_blend'])
    plan=_plan_uniform(prepared,skeleton)
    sel=_selection(settings,root,blend,baseline,plan,work/'selection')
    instruction={'format':PREP_FORMAT,'status':'READY','release_version':RELEASE_VERSION,'logical':TARGET,'candidate_only':True,'production_authorized':False,'prior_v0818_failure_understood':True,'prior_v0818_failure_kind':'BMesh face/edge selection flush repopulated all vertices on reopen','object_index':int(plan['object_index']),'changed_vertex_indices':[int(x) for x in plan['changed_vertex_indices']],'uniform_axis':str(plan['uniform_axis']),'uniform_delta_world_fixed':int(plan['uniform_delta_world_fixed']),'uniform_delta_world':float(plan['uniform_delta_world']),'shared_face_pairs':int(plan.get('changed_vertex_pairs_sharing_face',0)),'affected_bone_count':int(plan.get('affected_bone_count',0)),'edit_blend':str(blend),'baseline':str(baseline),'visible_selection_persisted':sel['reopen'].get('visible_selection_persisted') is True,'manual_steps':['Press G','Press '+str(plan['uniform_axis']).upper(),'Type '+format(float(plan['uniform_delta_world']),'.9g'),'Press Enter','Ctrl+S','Close Blender'],'real_certification_count_before':real_count_before,'real_certification_registry_sha256_before':real_sha_before,'client_source_sha256_before':source_sha_before,'writer_hashes_before':writers_before,'expected_changes':[{'object_index':int(plan['object_index']),'vertex_index':int(r['vertex_index']),'before_world_fixed':[int(x) for x in r['before_world_fixed']],'after_world_fixed':[int(x) for x in r['requested_after_world_fixed']]} for r in plan['changed_vertices']]}
    mp=work/'manual_candidate_manifest.json'; mp.write_text(json.dumps(instruction,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(instruction,ensure_ascii=False,indent=2),flush=True)
    print('rare_rigid_large_manual_candidate=READY vertices='+','.join(map(str,instruction['changed_vertex_indices']))+f" axis={str(plan['uniform_axis']).upper()} delta={instruction['uniform_delta_world']:.9g} blend={blend}",flush=True)
    # Interactive session. UI helper only displays instructions and rechecks persisted selection.
    ui=root/'pt_asset_tool/blender/open_rare_rigid_large_candidate.py'
    proc=run_logged(settings.blender_command()+[str(blend),'--python',str(ui),'--','--manifest',str(mp)],work/'03_interactive_blender.log')
    pre=_preflight(settings,root,blend,baseline,plan,work)
    out=work/'output/at_dragon_large_candidate_manual.smd'; out.parent.mkdir(parents=True,exist_ok=True); out.unlink(missing_ok=True)
    cert_before=len(iso.records())
    result=_candidate_live_write(reg=reg,resolver=resolver,cert=iso,settings=settings,project_root=root,workspace=work,edit_blend=blend,output=out)
    cert_after=len(iso.records()); last=iso.records()[-1] if iso.records() else {}
    if cert_after!=cert_before+1 or last.get('test')!='RARE_RIGID_ARTIST_GUARDED_LARGE_TRANSACTION_WRITE_CANDIDATE': raise RuntimeError('MANUAL_CANDIDATE_CERTIFICATION_NOT_ISOLATED_EXPECTED')
    if result.get('status')!='PASS' or int(result.get('artist_changed_vertices',-1))!=TARGET_COUNT or list(result.get('changed_vertex_indices') or [])!=instruction['changed_vertex_indices']: raise RuntimeError('MANUAL_CANDIDATE_WRITER_RESULT_UNEXPECTED')
    writers_after=_writer_hashes(root); source_sha_after=_sha256(source); real_count_after=len(real.records()); real_sha_after=_cert_sha(real)
    real_unchanged=(real_count_before==real_count_after and real_sha_before==real_sha_after); writer_unchanged=(writers_before==writers_after==EXPECTED_WRITER_HASHES); client_unchanged=(source_sha_before==source_sha_after)
    if not (real_unchanged and writer_unchanged and client_unchanged): raise RuntimeError('PRODUCTION_STATE_CHANGED_BY_MANUAL_CANDIDATE')
    report={'format':FORMAT,'status':'PASS','release_version':RELEASE_VERSION,'logical':TARGET,'manual_artist_proof':True,'prior_v0818_failure_understood':True,'artist_changed_vertices':int(result['artist_changed_vertices']),'object_index':result.get('object_index'),'changed_vertex_indices':result.get('changed_vertex_indices'),'manual_uniform_axis':instruction['uniform_axis'],'manual_uniform_delta_world':instruction['uniform_delta_world'],'all_non_authorized_bytes_byte_identical':result.get('all_non_authorized_bytes_byte_identical'),'bounds_header_byte_identical':result.get('bounds_header_byte_identical'),'transport_position_error':result.get('transport_position_error'),'transport_uv_error':result.get('transport_uv_error'),'physique_mismatch_count':result.get('physique_mismatch_count'),'transaction_atomic':result.get('transaction_atomic'),'atomic_output_replace':result.get('atomic_output_replace'),'joint_final_geometry_guard':result.get('joint_final_geometry_guard'),'candidate_certification_id':last.get('certification_id'),'candidate_certification_test':last.get('test'),'candidate_certification_isolated':True,'real_certification_count_before':real_count_before,'real_certification_count_after':real_count_after,'real_certification_registry_sha256_before':real_sha_before,'real_certification_registry_sha256_after':real_sha_after,'real_certification_registry_modified':not real_unchanged,'writer_modules_modified':not writer_unchanged,'client_source_sha256_before':source_sha_before,'client_source_sha256_after':source_sha_after,'client_modified':not client_unchanged,'output_smd':str(out),'output_sha256':_sha256(out),'candidate_max_vertices':8,'production_writer_max_vertices':4,'production_authorized':False,'ready_for_promotion_gate':True,'policy':{'scope':'one real manual five-vertex at_dragon artist transaction using the isolated V0.8.17 candidate writer path','manual_edit':'the artist moves the five preselected vertices with one physically prevalidated uniform Blender G/axis/value transform and saves the .blend','preflight':'actual saved fixed-point positions must exactly equal the prepared transaction before candidate writer execution','certification':'candidate PASS is written only to the isolated workspace registry; real append-only registry must remain count/hash identical','authorization':'this manual PASS is promotion evidence, not production authorization by itself','next_on_pass':'build V0.8.20 production-promotion gate that changes only the explicit 4->8 transaction cap after re-running regression/negative/manual evidence checks','deferred':'cross-object transactions, extent changes, topology and >8 vertices remain fail-closed'}}
    rp=work/'manual_write_result.json'; rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_large_manual_candidate=PASS changed_vertices=5 candidate_max=8 production_max=4 real_cert_unchanged=true client_modified=false ready_for_promotion_gate=true')
    return report

def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--logical',required=True); ns=ap.parse_args(argv)
    try: run(pathlib.Path(ns.root),ns.logical); return 0
    except Exception as exc:
        root=pathlib.Path(ns.root).resolve(); work=root/WORK_REL; work.mkdir(parents=True,exist_ok=True); out=work/'manual_write_result.json'
        report={'format':FORMAT,'status':'FAIL','release_version':RELEASE_VERSION,'logical':ns.logical,'error':f'{type(exc).__name__}:{exc}','production_authorized':False,'candidate_max_vertices':8,'production_writer_max_vertices':4}
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_large_manual_candidate=FAIL'); return 2
if __name__=='__main__': raise SystemExit(main())
