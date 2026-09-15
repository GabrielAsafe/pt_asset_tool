from __future__ import annotations
import argparse, hashlib, json, pathlib, shutil, subprocess
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .utils import run_logged
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from .rare_rigid_large_production import POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, _safe_rows, _beam_candidate_sets
from .rare_rigid_multibone_bridge import TARGET, WITNESS_DELTAS_FIXED
from .rare_rigid_cross_object_live_writer_candidate import (
    CANDIDATE_TEST, _cert_sha, _writer_hashes,
    write_at_dragon_cross_object_candidate_workspace,
    _exact_production_core_still_blocks,
)
from .rare_rigid_cross_object_saved_blender_candidate import _extract_candidate
from . import rare_rigid_multivertex as mv

RELEASE_VERSION='0.8.28'
FORMAT='PT_RARE_RIGID_CROSS_OBJECT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1'
PREP_FORMAT='PT_RARE_RIGID_CROSS_OBJECT_INTERACTIVE_CANDIDATE_WORKSPACE_V1'
PRIOR_REPORT=pathlib.Path('pt_build/rare_rigid_cross_object_live_writer_candidate_workflow_v0826.json')
PRIOR_FAILED_MANUAL_REPORT=pathlib.Path('pt_build/rare_rigid_cross_object_manual_candidate_v0827/at_dragon.smd/manual_write_result.json')
WORK_REL=pathlib.Path('pt_build/rare_rigid_cross_object_manual_candidate_v0828/at_dragon.smd')
TARGET_OBJECT_COUNT=2
VERTICES_PER_OBJECT=2
MAX_TOTAL=8


def _sha256(p:pathlib.Path)->str:
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def _json(p:pathlib.Path)->dict[str,Any]: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))

def _prior(root:pathlib.Path)->dict[str,Any]:
    p=root/PRIOR_REPORT
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0826_REPORT_MISSING:{p}')
    r=_json(p)
    checks=[
        r.get('format')=='PT_RARE_RIGID_CROSS_OBJECT_LIVE_WRITER_CANDIDATE_AUDIT_V1',
        r.get('status')=='PASS', r.get('release_version')=='0.8.26',
        r.get('prior_v0825_gate_pass') is True,
        list(r.get('candidate_object_counts') or [])==[2,3],
        list(r.get('candidate_total_changed_vertices') or [])==[4,6],
        int(r.get('candidate_max_total_changed_vertices',-1))==8,
        int(r.get('candidate_vertices_per_object',-1))==2,
        r.get('production_exact_core_writer_cross_object_blocked') is True,
        r.get('negative_bounds_blocked') is True,
        r.get('nine_vertex_blocked') is True,
        r.get('real_certification_registry_modified') is False,
        r.get('production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
        r.get('process_local_limits_restored_to_4') is True,
        int(r.get('production_single_object_max_vertices',-1))==8,
        r.get('cross_object_live_write_authorized') is False,
        r.get('manual_artist_proof_required_before_cross_object_authorization') is True,
    ]
    if not all(checks): raise RuntimeError('PRIOR_V0826_GATE_NOT_STRICT_PASS')
    return r

def _prior_v0827_failure(root:pathlib.Path)->dict[str,Any]:
    p=root/PRIOR_FAILED_MANUAL_REPORT
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0827_MANUAL_FAILURE_REPORT_MISSING:{p}')
    r=_json(p)
    err=str(r.get('error',''))
    checks=[
        r.get('format')=='PT_RARE_RIGID_CROSS_OBJECT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
        r.get('status')=='FAIL', r.get('release_version')=='0.8.27',
        'ensure_rare_rigid_cross_object_manual_selection.py' in err,
        'IndexError: BMElemSeq[index]: outdated internal index table' in err,
        'ensure_lookup_table() first' in err,
        int(r.get('production_single_object_max_vertices',-1))==8,
        r.get('cross_object_live_write_authorized') is False,
    ]
    if not all(checks): raise RuntimeError('PRIOR_V0827_MANUAL_FAILURE_NOT_EXPECTED_BMESH_LOOKUP_TABLE_CASE')
    return r

def _prior_two_object_shape(prior:dict[str,Any])->tuple[list[int],dict[int,list[int]]]:
    rows=[x for x in prior.get('rows') or [] if int(x.get('object_count',-1))==2 and x.get('status')=='PASS']
    if len(rows)!=1: raise RuntimeError('PRIOR_V0826_TWO_OBJECT_ROW_NOT_UNIQUE')
    row=rows[0]; objs=[int(x) for x in row.get('object_indices') or []]
    per={int(k):[int(v) for v in vals] for k,vals in (row.get('per_object_changed_vertex_indices') or {}).items()}
    if len(objs)!=2 or sorted(per)!=sorted(objs) or any(len(per[o])!=2 for o in objs):
        raise RuntimeError(f'PRIOR_V0826_TWO_OBJECT_SHAPE_INVALID:{objs}:{per}')
    return objs,per

def _plan_uniform_pair(prepared:pathlib.Path,skeleton:pathlib.Path,oi:int,by_vi:dict[int,dict[str,Any]],pair:tuple[int,int],axis:int,delta:int):
    changes=[]
    for vi in pair:
        row=by_vi.get(int(vi))
        if row is None: return None
        before=[int(x) for x in row['before_world_fixed']]; after=list(before); after[axis]+=int(delta)
        changes.append({'object_index':oi,'vertex_index':int(vi),'before_world_fixed':before,'after_world_fixed':after})
    try: return mv.plan_requested_at_dragon_transaction(prepared,skeleton,changes=changes)
    except Exception: return None

def _row_motion_key(row:dict[str,Any])->tuple[int,int]|None:
    before=[int(x) for x in row.get('before_world_fixed') or []]; after=[int(x) for x in row.get('requested_after_world_fixed') or []]
    if len(before)!=3 or len(after)!=3: return None
    d=[after[i]-before[i] for i in range(3)]; nz=[i for i,x in enumerate(d) if x]
    if len(nz)!=1: return None
    return nz[0],int(d[nz[0]])

def discover_manual_uniform_transaction(prepared:pathlib.Path,skeleton:pathlib.Path,prior:dict[str,Any])->dict[str,Any]:
    objects,prior_pairs=_prior_two_object_shape(prior)
    safe,_=_safe_rows(prepared,skeleton)
    axis_names={0:'x',1:'y',2:'z'}; attempts=0
    # Fast path: the single-vertex census already contains physically safe motions.
    # Find a common motion key with >=2 candidate vertices on each proven object,
    # then joint-plan the pair on each object.
    grouped={}
    for oi in objects:
        groups={}
        for row in safe.get(oi) or []:
            key=_row_motion_key(row)
            if key is not None: groups.setdefault(key,[]).append(row)
        grouped[oi]=groups
    common=sorted(set(grouped[objects[0]]) & set(grouped[objects[1]]), key=lambda k:(abs(k[1]),0 if k[0]==0 else 1 if k[0]==2 else 2,k[1]))
    for axis,delta in common:
        plans=[]; ok=True
        for oi in objects:
            rows=grouped[oi][(axis,delta)]; by_vi={int(r['vertex_index']):r for r in rows}
            pairs=[]; pp=tuple(sorted(prior_pairs[oi]))
            if all(v in by_vi for v in pp): pairs.append(pp)
            for pair in _beam_candidate_sets(rows,2,beam_limit=96):
                pair=tuple(int(x) for x in pair)
                if pair not in pairs: pairs.append(pair)
            chosen=None
            for pair in pairs:
                attempts+=1; chosen=_plan_uniform_pair(prepared,skeleton,oi,by_vi,pair,axis,delta)
                if chosen is not None: break
            if chosen is None: ok=False; break
            plans.append(chosen)
        if ok and len(plans)==2:
            return {'object_count':2,'object_indices':objects,'total_changed_vertices':4,'per_object_plans':plans,'transaction_atomic':True,'guard_status':'PASS','uniform_axis':axis_names[axis],'uniform_axis_index':axis,'uniform_delta_world_fixed':delta,'uniform_delta_world':delta/256.0,'search_attempts':attempts,'search_mode':'shared_single_vertex_witness_motion','prior_v0826_object_pair_preserved':True}
    # Conservative fallback: test the small certified witness amplitudes uniformly.
    axis_order=[(0,'x'),(2,'z'),(1,'y')]; deltas=[int(x) for x in WITNESS_DELTAS_FIXED]
    for axis,axis_name in axis_order:
        for delta in deltas:
            plans=[]; ok=True
            for oi in objects:
                rows=safe.get(oi) or []; by_vi={int(r['vertex_index']):r for r in rows}; pairs=[]
                pp=tuple(sorted(prior_pairs[oi])); pairs.append(pp)
                for pair in _beam_candidate_sets(rows,2,beam_limit=96):
                    pair=tuple(int(x) for x in pair)
                    if pair not in pairs: pairs.append(pair)
                chosen=None
                for pair in pairs:
                    attempts+=1; chosen=_plan_uniform_pair(prepared,skeleton,oi,by_vi,pair,axis,delta)
                    if chosen is not None: break
                if chosen is None: ok=False; break
                plans.append(chosen)
            if ok and len(plans)==2:
                return {'object_count':2,'object_indices':objects,'total_changed_vertices':4,'per_object_plans':plans,'transaction_atomic':True,'guard_status':'PASS','uniform_axis':axis_name,'uniform_axis_index':axis,'uniform_delta_world_fixed':delta,'uniform_delta_world':delta/256.0,'search_attempts':attempts,'search_mode':'uniform_fallback','prior_v0826_object_pair_preserved':True}
    raise RuntimeError(f'NO_COMMON_UNIFORM_TWO_OBJECT_MANUAL_TRANSACTION:attempts={attempts}')

def _selection(settings:Settings,root:pathlib.Path,blend:pathlib.Path,tx:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    work.mkdir(parents=True,exist_ok=True); plan=work/'selection_plan.json'; plan.write_text(json.dumps(tx,indent=2)+'\n',encoding='utf-8')
    helper=root/'pt_asset_tool/blender/ensure_rare_rigid_cross_object_manual_selection.py'
    prep=work/'selection_prepare.json'
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(helper),'--','--plan',str(plan),'--report',str(prep)],work/'01_prepare_selection.log')
    verify=work/'selection_reopen_verify.json'
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(helper),'--','--plan',str(plan),'--report',str(verify),'--verify-only'],work/'02_verify_selection.log')
    a=_json(prep); b=_json(verify)
    if a.get('status')!='PASS' or b.get('status')!='PASS' or b.get('visible_selection_persisted') is not True: raise RuntimeError('CROSS_OBJECT_MANUAL_SELECTION_NOT_PERSISTED')
    return {'prepare':a,'reopen':b,'plan_path':str(plan)}

def _expected_map(tx:dict[str,Any])->dict[tuple[int,int],list[int]]:
    out={}
    for p in tx['per_object_plans']:
        oi=int(p['object_index'])
        for r in p['changed_vertices']:
            if int(r['vertex_index']) not in {int(x) for x in p['changed_vertex_indices']}: continue
            out[(oi,int(r['vertex_index']))]=[int(x) for x in r['requested_after_world_fixed']]
    return out

def _preflight(settings:Settings,root:pathlib.Path,blend:pathlib.Path,baseline:pathlib.Path,tx:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    rp=work/'04_manual_preflight_extract.json'
    r,_=_extract_candidate(root=root,settings=settings,blend=blend,baseline=baseline,report_path=rp,work=work/'preflight',expect_success=True)
    assert r is not None
    actual={(int(x['object_index']),int(x['vertex_index'])):[int(v) for v in x['after_world_fixed']] for x in r.get('changed_vertices') or []}
    expected=_expected_map(tx)
    if actual!=expected: raise RuntimeError(f'MANUAL_CROSS_OBJECT_EDIT_NOT_EXACT_PREPARED_TRANSACTION:actual={actual}:expected={expected}')
    if r.get('writer_input_mode_before')!='EDIT_MESH' or r.get('writer_input_mode_after')!='OBJECT': raise RuntimeError('MANUAL_CROSS_OBJECT_PREFLIGHT_MODE_INVALID')
    if r.get('non_position_semantic_state_pass') is not True or float(r.get('max_uv_state_delta',1))!=0 or float(r.get('max_physique_weight_delta',1))!=0: raise RuntimeError('MANUAL_CROSS_OBJECT_PREFLIGHT_SEMANTIC_FAIL')
    return r

def run(root:pathlib.Path,logical:str)->dict[str,Any]:
    root=pathlib.Path(root).resolve()
    if logical!=TARGET: raise RuntimeError(f'ONLY_AT_DRAGON_SUPPORTED:{logical}')
    prior=_prior(root); prior_failed=_prior_v0827_failure(root); policy=load_and_validate_policy(root); policy_path=root/POLICY_REL; policy_sha_before=_sha256(policy_path)
    if int(policy.get('production_max_vertices',-1))!=8 or policy.get('single_object_only') is not True: raise RuntimeError('V0821_PRODUCTION_POLICY_SCOPE_UNEXPECTED')
    writers_before=_writer_hashes(root)
    if writers_before!=EXPECTED_WRITER_HASHES: raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0828')
    settings=Settings.discover(root,None); resolver=ClientResolver(settings.client_root); reg=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    real=CertificationRegistry(settings.certifications_dir); real_count_before=len(real.records()); real_sha_before=_cert_sha(real)
    source=pathlib.Path(resolver.resolve(TARGET,required=True)); source_sha_before=_sha256(source)
    if source_sha_before!=policy.get('client_source_sha256'): raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0821_POLICY')
    work=root/WORK_REL
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    iso=CertificationRegistry(work/'isolated_certifications')
    workspace=work/'isolated_artist_workspace'
    manifest=prepare_at_dragon_edit_workspace(reg,resolver,iso,settings,project_root=root,open_gui=False,reset=True,workspace_root=workspace,workspace_origin='USER_V0828_INTERACTIVE_CROSS_OBJECT_CANDIDATE_LOOKUP_FIX')
    if len(iso.records())!=1 or iso.records()[0].get('test')!='RARE_RIGID_BLENDER_PREVIEW': raise RuntimeError('ISOLATED_PREVIEW_CERT_UNEXPECTED')
    prepared=pathlib.Path(manifest['prepared_source']); skeleton=pathlib.Path(manifest['skeleton']); blend=pathlib.Path(manifest['edit_blend']); baseline=pathlib.Path(manifest['baseline_blender_report'])
    tx=discover_manual_uniform_transaction(prepared,skeleton,prior)
    sel=_selection(settings,root,blend,tx,work/'selection')
    selected={str(p['object_index']):[int(x) for x in p['changed_vertex_indices']] for p in tx['per_object_plans']}
    instruction={'format':PREP_FORMAT,'status':'READY','release_version':RELEASE_VERSION,'logical':TARGET,'candidate_only':True,'production_cross_object_authorized':False,'prior_v0827_failure_understood':True,'prior_v0827_failure_kind':'Blender 5.2 BMesh vertex lookup table required ensure_lookup_table() before indexed access','object_count':2,'object_indices':tx['object_indices'],'total_changed_vertices':4,'vertices_per_object':2,'selected_vertices_by_object':selected,'uniform_axis':tx['uniform_axis'],'uniform_delta_world_fixed':tx['uniform_delta_world_fixed'],'uniform_delta_world':tx['uniform_delta_world'],'edit_blend':str(blend),'baseline':str(baseline),'visible_selection_persisted':sel['reopen'].get('visible_selection_persisted') is True,'popup_used':False,'manual_steps':['Press G','Press '+str(tx['uniform_axis']).upper(),'Type '+format(float(tx['uniform_delta_world']),'.9g'),'Press Enter','Ctrl+S','Close Blender'],'expected_changes':[{'object_index':oi,'vertex_index':vi,'after_world_fixed':after} for (oi,vi),after in sorted(_expected_map(tx).items())]}
    mp=work/'manual_cross_object_manifest.json'; mp.write_text(json.dumps(instruction,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(instruction,ensure_ascii=False,indent=2),flush=True)
    print('rare_rigid_cross_object_manual_candidate=READY objects='+','.join(map(str,instruction['object_indices']))+' vertices='+json.dumps(selected,separators=(',',':'))+f" axis={str(tx['uniform_axis']).upper()} delta={instruction['uniform_delta_world']:.9g} blend={blend}",flush=True)
    ui=root/'pt_asset_tool/blender/open_rare_rigid_cross_object_manual_candidate.py'
    run_logged(settings.blender_command()+[str(blend),'--python',str(ui),'--','--manifest',str(mp)],work/'03_interactive_blender.log')
    _preflight(settings,root,blend,baseline,tx,work)
    out=work/'output/at_dragon_cross_object_candidate_manual.smd'; out.parent.mkdir(parents=True,exist_ok=True); out.unlink(missing_ok=True)
    cert_before=len(iso.records())
    result=write_at_dragon_cross_object_candidate_workspace(reg,resolver,iso,settings,project_root=root,workspace_root=workspace,output=out)
    cert_after=len(iso.records()); last=iso.records()[-1] if iso.records() else {}
    if cert_after!=cert_before+1 or last.get('test')!=CANDIDATE_TEST: raise RuntimeError('MANUAL_CROSS_OBJECT_CANDIDATE_CERTIFICATION_NOT_ISOLATED_EXPECTED')
    if result.get('status')!='PASS' or int(result.get('object_count',-1))!=2 or int(result.get('artist_changed_vertices',-1))!=4 or result.get('per_object_changed_vertex_indices')!=selected: raise RuntimeError('MANUAL_CROSS_OBJECT_WRITER_RESULT_UNEXPECTED')
    prod_cert_before=len(iso.records()); prod_blocked,prod_error=_exact_production_core_still_blocks(root=root,reg=reg,resolver=resolver,certifications=iso,settings=settings,workspace=workspace)
    if not prod_blocked or len(iso.records())!=prod_cert_before: raise RuntimeError(f'PRODUCTION_CORE_MANUAL_CROSS_OBJECT_NOT_BLOCKED:{prod_error}')
    prod_out=workspace/'production_control_should_not_exist.smd'
    if prod_out.exists(): raise RuntimeError('PRODUCTION_CORE_MANUAL_CROSS_OBJECT_OUTPUT_CREATED')
    writers_after=_writer_hashes(root); source_sha_after=_sha256(source); real_count_after=len(real.records()); real_sha_after=_cert_sha(real); policy_sha_after=_sha256(policy_path)
    real_unchanged=real_count_before==real_count_after and real_sha_before==real_sha_after
    writer_unchanged=writers_before==writers_after==EXPECTED_WRITER_HASHES; client_unchanged=source_sha_before==source_sha_after; policy_unchanged=policy_sha_before==policy_sha_after
    if not all([real_unchanged,writer_unchanged,client_unchanged,policy_unchanged]): raise RuntimeError('PRODUCTION_STATE_CHANGED_BY_MANUAL_CROSS_OBJECT_CANDIDATE')
    report={'format':FORMAT,'status':'PASS','release_version':RELEASE_VERSION,'logical':TARGET,'manual_artist_proof':True,'prior_v0827_failure_understood':True,'prior_v0827_failure_kind':'Blender 5.2 BMesh vertex lookup table required ensure_lookup_table() before indexed access','object_count':2,'object_indices':result['object_indices'],'artist_changed_vertices':4,'per_object_changed_vertex_indices':result['per_object_changed_vertex_indices'],'manual_uniform_axis':instruction['uniform_axis'],'manual_uniform_delta_world':instruction['uniform_delta_world'],'visible_selection_persisted':True,'popup_used':False,'all_non_authorized_bytes_byte_identical':result['all_non_authorized_bytes_byte_identical'],'all_affected_object_bounds_byte_identical':result['all_affected_object_bounds_byte_identical'],'transport_position_error':result['transport_position_error'],'transport_uv_error':result['transport_uv_error'],'physique_mismatch_count':result['physique_mismatch_count'],'all_object_transaction_witness_pass':result['all_object_transaction_witness_pass'],'transaction_atomic':result['transaction_atomic'],'atomic_output_replace':result['atomic_output_replace'],'candidate_certification_id':last.get('certification_id'),'candidate_certification_test':last.get('test'),'candidate_certification_isolated':True,'production_exact_core_writer_cross_object_blocked':True,'production_exact_core_writer_error':prod_error,'real_certification_count_before':real_count_before,'real_certification_count_after':real_count_after,'real_certification_registry_sha256_before':real_sha_before,'real_certification_registry_sha256_after':real_sha_after,'real_certification_registry_modified':False,'production_policy_sha256_before':policy_sha_before,'production_policy_sha256_after':policy_sha_after,'production_policy_modified':False,'writer_modules_modified':False,'client_source_sha256_before':source_sha_before,'client_source_sha256_after':source_sha_after,'client_modified':False,'output_smd':str(out),'output_sha256':_sha256(out),'production_single_object_max_vertices':8,'cross_object_live_write_authorized':False,'ready_for_cross_object_promotion_gate':True,'policy':{'scope':'one real manual two-object at_dragon artist transaction; exactly two vertices per object; four total; interior only','manual_edit':'two mesh objects are persisted together in EDIT_MESH with exactly two vertices selected on each; artist performs one common G/axis/value transform','preflight':'saved multi-object fixed-point positions must exactly equal the prevalidated uniform transaction before candidate writer execution','certification':'manual PASS is candidate-labelled only in isolated registry; real registry and V0.8.21 production policy stay byte-identical','production_control':'the exact production core path remains required to reject the same manual multi-object saved blend','authorization':'this manual PASS is promotion evidence only; cross-object production remains unauthorized','next_on_pass':'build V0.8.29 cross-object production-promotion gate for the exact proven shapes after full regression/negative/manual evidence checks','deferred':'extent/bounds changes, topology, more than 3 objects, other vertices-per-object shapes and >8 total changed vertices remain fail-closed'}}
    rp=work/'manual_write_result.json'; rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_cross_object_manual_candidate=PASS objects=2 changed_vertices=4 production_single_object_max=8 cross_object_authorized=false ready_for_promotion_gate=true')
    return report

def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description='V0.8.28 interactive cross-object candidate BMesh lookup fix'); ap.add_argument('--root',required=True); ap.add_argument('--logical',required=True); ns=ap.parse_args(argv)
    try: run(pathlib.Path(ns.root),ns.logical); return 0
    except Exception as exc:
        root=pathlib.Path(ns.root).resolve(); work=root/WORK_REL; work.mkdir(parents=True,exist_ok=True); out=work/'manual_write_result.json'
        report={'format':FORMAT,'status':'FAIL','release_version':RELEASE_VERSION,'logical':ns.logical,'error':f'{type(exc).__name__}:{exc}','production_single_object_max_vertices':8,'cross_object_live_write_authorized':False}
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_cross_object_manual_candidate=FAIL'); return 2
if __name__=='__main__': raise SystemExit(main())
