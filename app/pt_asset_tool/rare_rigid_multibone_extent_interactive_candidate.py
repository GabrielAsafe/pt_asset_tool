from __future__ import annotations
import argparse, hashlib, json, pathlib, shutil
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_cross_object_production import POLICY_REL as CROSS_POLICY_REL, load_and_validate_cross_policy
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_multibone_extent_live_writer_candidate import (
    CANDIDATE_TEST,
    write_at_dragon_multibone_outward_extent_candidate_workspace,
)
from .rare_rigid_multibone_extent_probe import discover_witnesses, _evaluate, _world_positions
from .rare_rigid_multibone_extent_saved_blender_candidate import _extract_saved_change, _production_extent_negative
from .rare_rigid_normal_bridge import _build_source_normal_state
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_rigid_geometry import _parse_skeleton_tms
from .utils import sha256_file, run_logged

RELEASE_VERSION='0.8.35'
FORMAT='PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1'
PREP_FORMAT='PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_INTERACTIVE_CANDIDATE_WORKSPACE_V1'
PRIOR_REL=pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_live_writer_candidate_workflow_v0833.json')
PRIOR_FAILED_REL=pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_manual_candidate_v0834/at_dragon.smd/manual_write_result.json')
EXPECTED_PRIOR_V0834_ERROR='RuntimeError:V0834_MANUAL_PREFLIGHT_POSITION_MISMATCH:[1358, 370, 0]!=[1347, 370, 0]'
WORK_REL=pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_manual_candidate_v0835/at_dragon.smd')
MANUAL_KIND='maxX'
FRIENDLY_DELTAS_FIXED=(64,128,256,512,1024)

def _sha256(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def _json(path:pathlib.Path)->dict[str,Any]: return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def _writer_hashes(root:pathlib.Path)->dict[str,str]: return {rel:_sha256(root/rel) for rel in EXPECTED_WRITER_HASHES}
def _cert_sha(c:CertificationRegistry)->str: return _sha256(c.path) if c.path.is_file() else hashlib.sha256(b'').hexdigest()

def _strict_prior_v0833(root:pathlib.Path)->dict[str,Any]:
    p=root/PRIOR_REL
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0833_REPORT_MISSING:{p}')
    d=_json(p); rows=list(d.get('rows') or []); by={str(r.get('target_bound_kind')):r for r in rows if r.get('status')=='PASS'}
    checks=[
        d.get('format')=='PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_AUDIT_V1', d.get('status')=='PASS', d.get('release_version')=='0.8.33', d.get('logical')==TARGET,
        d.get('prior_v0832_strict_pass') is True, int(d.get('prior_v0832_witness_count',-1))==5, int(d.get('candidate_witness_count',-1))==5,
        d.get('exact_candidate_writer_function_exercised')=='write_at_dragon_multibone_outward_extent_candidate_workspace', d.get('all_candidate_rows_pass') is True,
        set(by)=={'maxX','maxZ','maxY','dBound','Bound'}, d.get('all_live_writer_outputs_match_v0832') is True,
        int(d.get('isolated_candidate_certification_count',-1))==5, d.get('candidate_certification_test')==CANDIDATE_TEST,
        d.get('production_extent_still_blocked') is True, d.get('production_extent_output_created') is False,
        d.get('multi_vertex_extent_blocked') is True, d.get('multi_vertex_extent_output_created') is False,
        d.get('cross_object_extent_blocked') is True, d.get('cross_object_extent_output_created') is False,
        d.get('inward_no_extent_blocked') is True, d.get('inward_no_extent_output_created') is False,
        d.get('real_certification_registry_modified') is False, d.get('single_object_production_policy_modified') is False, d.get('cross_object_production_policy_modified') is False,
        d.get('writer_modules_modified') is False, d.get('client_modified') is False,
        d.get('multibone_outward_extent_live_write_authorized') is False, d.get('extent_contraction_write_authorized') is False,
        d.get('multi_vertex_extent_write_authorized') is False, d.get('cross_object_extent_write_authorized') is False, d.get('topology_write_authorized') is False,
        d.get('writer_hashes')==EXPECTED_WRITER_HASHES,
    ]
    if not all(checks): raise RuntimeError('PRIOR_V0833_REPORT_NOT_STRICT_PASS')
    for kind,row in by.items():
        if row.get('candidate_only') is not True or row.get('production_authorized') is not False or row.get('candidate_certification_test')!=CANDIDATE_TEST or row.get('matches_v0832_output_sha256') is not True or not row.get('output_sha256'):
            raise RuntimeError(f'PRIOR_V0833_ROW_NOT_STRICT_PASS:{kind}')
    d['_rows_by_kind']=by; return d

def _strict_prior_v0834_failure(root:pathlib.Path)->dict[str,Any]:
    p=root/PRIOR_FAILED_REL
    if not p.is_file(): raise RuntimeError(f'PRIOR_V0834_FAILURE_REPORT_MISSING:{p}')
    d=_json(p)
    checks=[
        d.get('format')=='PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
        d.get('status')=='FAIL', d.get('release_version')=='0.8.34', d.get('logical')==TARGET,
        d.get('error')==EXPECTED_PRIOR_V0834_ERROR,
        d.get('multibone_outward_extent_live_write_authorized') is False,
    ]
    if not all(checks): raise RuntimeError('PRIOR_V0834_FAILURE_NOT_EXACT_EXPECTED_DELTA_MISMATCH')
    return d

def _manual_plan(prepared:pathlib.Path,skeleton:pathlib.Path,prior:dict[str,Any])->dict[str,Any]:
    discovery=discover_witnesses(prepared,skeleton); found=discovery.get('found') or {}
    if MANUAL_KIND not in found: raise RuntimeError('V0835_MAXX_MANUAL_WITNESS_NOT_DISCOVERED')
    base=dict(found[MANUAL_KIND]); prior_row=prior['_rows_by_kind'][MANUAL_KIND]
    oi=int(base['object_index']); vi=int(base['vertex_index'])
    if oi!=int(prior_row['object_index']) or vi!=int(prior_row['vertex_index']):
        raise RuntimeError('V0835_MANUAL_WITNESS_IDENTITY_DIVERGED_FROM_V0833')
    if list(base.get('changed_bound_fields') or [])!=['maxX']:
        raise RuntimeError(f'V0835_MANUAL_WITNESS_FIELD_SHAPE_UNEXPECTED:{base.get("changed_bound_fields")}')
    before=tuple(int(x) for x in base['before_world_fixed']); base_after=tuple(int(x) for x in base['requested_after_world_fixed'])
    if base_after[0]==before[0] or base_after[1:]!=before[1:]:
        raise RuntimeError(f'V0835_MANUAL_WITNESS_NOT_X_ONLY:{base_after}:{before}')
    direction=1 if base_after[0]>before[0] else -1
    model=_parse_with_offsets(prepared); obj=model['objects'][oi]; bone_tms=_parse_skeleton_tms(skeleton)
    world=_world_positions(obj,bone_tms)
    if tuple(world[vi])!=before: raise RuntimeError('V0835_MANUAL_WITNESS_WORLD_BASELINE_DIVERGED')
    state=_build_source_normal_state(world,obj['faces'])
    for mag in FRIENDLY_DELTAS_FIXED:
        requested=(before[0]+direction*int(mag),before[1],before[2])
        plan=_evaluate(obj,bone_tms,world,state,vi,requested,MANUAL_KIND)
        if plan is None or plan.get('guard_status')!='PASS':
            continue
        if int(plan['object_index'])!=oi or int(plan['vertex_index'])!=vi or list(plan.get('changed_bound_fields') or [])!=['maxX']:
            continue
        plan=dict(plan)
        plan['manual_axis']='x'; plan['manual_delta_world_fixed']=direction*int(mag); plan['manual_delta_world']=float(direction*int(mag))/256.0
        plan['manual_friendly_delta_prevalidated']=True
        plan['base_discovered_requested_after_world_fixed']=list(base_after)
        return plan
    raise RuntimeError('V0835_NO_HUMAN_FRIENDLY_MAXX_DELTA_PASSES_PHYSICAL_GUARDS')

def _selection(settings:Settings,root:pathlib.Path,blend:pathlib.Path,plan:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    work.mkdir(parents=True,exist_ok=True); helper=root/'pt_asset_tool/blender/ensure_rare_rigid_multibone_extent_manual_selection.py'
    prep=work/'selection_prepare.json'; reopen=work/'selection_reopen.json'; oi=int(plan['object_index']); vi=int(plan['vertex_index'])
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(helper),'--','--object-index',str(oi),'--vertex-index',str(vi),'--report',str(prep)],work/'01_prepare_selection.log')
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(helper),'--','--object-index',str(oi),'--vertex-index',str(vi),'--verify-only','--report',str(reopen)],work/'02_verify_selection.log')
    a=_json(prep); b=_json(reopen)
    if a.get('status')!='PASS' or b.get('status')!='PASS' or b.get('selected_vertex_indices')!=[vi] or b.get('saved_mode')!='EDIT_MESH' or b.get('visible_selection_persisted') is not True:
        raise RuntimeError('V0835_MANUAL_SELECTION_PERSISTENCE_FAILED')
    return {'prepare':a,'reopen':b}

def _preflight(settings:Settings,root:pathlib.Path,blend:pathlib.Path,baseline:pathlib.Path,plan:dict[str,Any],work:pathlib.Path)->dict[str,Any]:
    extraction=_extract_saved_change(settings=settings,root=root,blend=blend,baseline=baseline,report=work/'manual_preflight_extract.json',log=work/'04_manual_preflight_extract.log')
    rows=list(extraction.get('changed_vertices') or [])
    if len(rows)!=1: raise RuntimeError(f'V0835_MANUAL_PREFLIGHT_CHANGED_VERTEX_COUNT:{len(rows)}')
    r=rows[0]; oi=int(plan['object_index']); vi=int(plan['vertex_index']); expected=[int(x) for x in plan['requested_after_world_fixed']]
    if int(r['object_index'])!=oi or int(r['vertex_index'])!=vi: raise RuntimeError('V0835_MANUAL_PREFLIGHT_IDENTITY_MISMATCH')
    if [int(x) for x in r['after_world_fixed']]!=expected: raise RuntimeError(f'V0835_MANUAL_PREFLIGHT_POSITION_MISMATCH:{r.get("after_world_fixed")}!={expected}')
    if extraction.get('non_position_semantic_state_pass') is not True or float(extraction.get('max_uv_state_delta',1))!=0.0 or float(extraction.get('max_physique_weight_delta',1))!=0.0:
        raise RuntimeError('V0835_MANUAL_PREFLIGHT_SEMANTIC_STATE_FAILED')
    return extraction

def run(root:pathlib.Path,logical:str)->dict[str,Any]:
    root=pathlib.Path(root).resolve()
    if logical!=TARGET: raise RuntimeError(f'V0835_LOGICAL_SCOPE:{logical}')
    prior=_strict_prior_v0833(root); prior_fail=_strict_prior_v0834_failure(root); single=load_and_validate_policy(root); cross=load_and_validate_cross_policy(root)
    single_path=root/SINGLE_POLICY_REL; cross_path=root/CROSS_POLICY_REL; single_sha_before=_sha256(single_path); cross_sha_before=_sha256(cross_path)
    if int(single.get('production_max_vertices',-1))!=8: raise RuntimeError('V0835_SINGLE_OBJECT_POLICY_SCOPE_UNEXPECTED')
    if cross.get('cross_object_production_authorized') is not True: raise RuntimeError('V0835_CROSS_OBJECT_POLICY_NOT_AUTHORIZED')
    writers_before=_writer_hashes(root)
    if writers_before!=EXPECTED_WRITER_HASHES: raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0835')
    settings=Settings.discover(root,None); resolver=ClientResolver(settings.client_root); reg=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    real=CertificationRegistry(settings.certifications_dir); real_count_before=len(real.records()); real_sha_before=_cert_sha(real)
    source=pathlib.Path(resolver.resolve(TARGET,required=True)); source_sha_before=_sha256(source)
    expected_source=str(prior.get('client_source_sha256_before') or prior.get('client_source_sha256_after') or '')
    if expected_source and source_sha_before!=expected_source: raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0833_EVIDENCE')
    if source_sha_before!=str(single.get('client_source_sha256')) or source_sha_before!=str(cross.get('client_source_sha256')): raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_PRODUCTION_POLICIES')
    work=root/WORK_REL
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    iso=CertificationRegistry(work/'isolated_certifications'); workspace=work/'isolated_artist_workspace'
    manifest=prepare_at_dragon_edit_workspace(reg,resolver,iso,settings,project_root=root,open_gui=False,reset=True,workspace_root=workspace,workspace_origin='USER_V0835_INTERACTIVE_MULTIBONE_OUTWARD_EXTENT_DELTA_FIX_CANDIDATE')
    if len(iso.records())!=1 or iso.records()[0].get('test')!='RARE_RIGID_BLENDER_PREVIEW': raise RuntimeError('V0835_ISOLATED_PREVIEW_CERT_UNEXPECTED')
    prepared=pathlib.Path(manifest['prepared_source']); skeleton=pathlib.Path(manifest['skeleton']); blend=pathlib.Path(manifest['edit_blend']); baseline=pathlib.Path(manifest['baseline_blender_report'])
    plan=_manual_plan(prepared,skeleton,prior); sel=_selection(settings,root,blend,plan,work/'selection')
    instruction={'format':PREP_FORMAT,'status':'READY','release_version':RELEASE_VERSION,'logical':TARGET,'candidate_only':True,'production_extent_authorized':False,'target_bound_kind':MANUAL_KIND,'object_index':int(plan['object_index']),'vertex_index':int(plan['vertex_index']),'affected_bone_count':int(plan['affected_bone_count']),'affected_bones':list(plan['affected_bones']),'changed_bound_fields':list(plan['changed_bound_fields']),'manual_axis':plan['manual_axis'],'manual_delta_world_fixed':int(plan['manual_delta_world_fixed']),'manual_delta_world':float(plan['manual_delta_world']),'before_world_fixed':[int(x) for x in plan['before_world_fixed']],'expected_after_world_fixed':[int(x) for x in plan['requested_after_world_fixed']],'edit_blend':str(blend),'baseline':str(baseline),'visible_selection_persisted':sel['reopen'].get('visible_selection_persisted') is True,'popup_used':False,'prior_v0834_failure_understood':True,'prior_v0834_failure_error':prior_fail.get('error'),'manual_friendly_delta_prevalidated':plan.get('manual_friendly_delta_prevalidated') is True,'base_discovered_requested_after_world_fixed':list(plan.get('base_discovered_requested_after_world_fixed') or []),'manual_steps':['Press G','Press X','Type '+format(float(plan['manual_delta_world']),'.9g'),'Press Enter','Ctrl+S','Close Blender']}
    mp=work/'manual_multibone_extent_manifest.json'; mp.write_text(json.dumps(instruction,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(instruction,ensure_ascii=False,indent=2),flush=True)
    print(f"rare_rigid_multibone_extent_manual_candidate=READY object={instruction['object_index']} vertex={instruction['vertex_index']} kind=maxX axis=X delta={instruction['manual_delta_world']:.9g} blend={blend}",flush=True)
    ui=root/'pt_asset_tool/blender/open_rare_rigid_multibone_extent_manual_candidate.py'
    run_logged(settings.blender_command()+[str(blend),'--python',str(ui),'--','--manifest',str(mp)],work/'03_interactive_blender.log')
    _preflight(settings,root,blend,baseline,plan,work)
    out=work/'output/at_dragon_multibone_extent_candidate_manual.smd'; out.parent.mkdir(parents=True,exist_ok=True); out.unlink(missing_ok=True)
    cert_before=len(iso.records())
    result=write_at_dragon_multibone_outward_extent_candidate_workspace(reg,resolver,iso,settings,project_root=root,workspace_root=workspace,output=out)
    cert_after=len(iso.records()); last=iso.records()[-1] if iso.records() else {}; prior_row=prior['_rows_by_kind'][MANUAL_KIND]
    if cert_after!=cert_before+1 or last.get('test')!=CANDIDATE_TEST: raise RuntimeError('V0835_MANUAL_CANDIDATE_CERTIFICATION_NOT_ISOLATED_EXPECTED')
    if result.get('status')!='PASS' or int(result.get('artist_changed_vertices',-1))!=1 or int(result.get('object_index',-1))!=int(plan['object_index']) or int(result.get('vertex_index',-1))!=int(plan['vertex_index']) or result.get('target_bound_kind')!=MANUAL_KIND:
        raise RuntimeError('V0835_MANUAL_WRITER_RESULT_UNEXPECTED')
    if list(result.get('changed_bound_fields') or [])!=list(plan.get('changed_bound_fields') or []): raise RuntimeError('V0835_MANUAL_WRITER_BOUND_FIELD_SHAPE_DIVERGED')
    if {k:int(v) for k,v in (result.get('stored_bounds_after') or {}).items()}!={k:int(v) for k,v in (plan.get('stored_bounds_after') or {}).items()}: raise RuntimeError('V0835_MANUAL_WRITER_BOUNDS_DIVERGED_FROM_PREFLIGHT_PLAN')
    if set(result.get('affected_bones') or [])!=set(plan.get('affected_bones') or []): raise RuntimeError('V0835_MANUAL_WRITER_AFFECTED_BONES_DIVERGED')
    prod_out=work/'production_extent_control_should_not_exist.smd'; prod_before=len(iso.records())
    prod_blocked,prod_error=_production_extent_negative(reg=reg,resolver=resolver,certifications=iso,settings=settings,root=root,workspace=workspace,edit_blend=blend,output=prod_out)
    if not prod_blocked or prod_out.exists() or len(iso.records())!=prod_before: raise RuntimeError(f'V0835_PRODUCTION_EXTENT_CONTROL_FAILED:{prod_error}')
    writers_after=_writer_hashes(root); source_sha_after=_sha256(source); real_count_after=len(real.records()); real_sha_after=_cert_sha(real); single_sha_after=_sha256(single_path); cross_sha_after=_sha256(cross_path)
    if writers_after!=writers_before or writers_after!=EXPECTED_WRITER_HASHES: raise RuntimeError('V0835_CERTIFIED_WRITERS_MODIFIED')
    if source_sha_after!=source_sha_before: raise RuntimeError('V0835_CLIENT_SOURCE_MODIFIED')
    if real_count_after!=real_count_before or real_sha_after!=real_sha_before: raise RuntimeError('V0835_REAL_CERTIFICATION_REGISTRY_MODIFIED')
    if single_sha_after!=single_sha_before or cross_sha_after!=cross_sha_before: raise RuntimeError('V0835_PRODUCTION_POLICY_MODIFIED')
    report={'format':FORMAT,'status':'PASS','release_version':RELEASE_VERSION,'logical':TARGET,'manual_artist_proof':True,'prior_v0834_failure_understood':True,'prior_v0834_failure_error':prior_fail.get('error'),'manual_friendly_delta_prevalidated':plan.get('manual_friendly_delta_prevalidated') is True,'target_bound_kind':MANUAL_KIND,'object_index':int(result['object_index']),'vertex_index':int(result['vertex_index']),'artist_changed_vertices':1,'manual_axis':'x','manual_delta_world_fixed':int(plan['manual_delta_world_fixed']),'manual_delta_world':float(plan['manual_delta_world']),'visible_selection_persisted':True,'popup_used':False,'changed_bound_fields':list(result['changed_bound_fields']),'affected_bone_count':int(result['affected_bone_count']),'affected_bones':list(result['affected_bones']),'all_non_authorized_bytes_byte_identical':result['all_non_authorized_bytes_byte_identical'],'bound_window_non_field_bytes_byte_identical':result['bound_window_non_field_bytes_byte_identical'],'transport_position_error':result['transport_position_error'],'transport_uv_error':result['transport_uv_error'],'witness_check':result['witness_check'],'transaction_atomic':result['transaction_atomic'],'atomic_output_replace':result['atomic_output_replace'],'manual_output_matches_prevalidated_friendly_delta_plan':True,'v0833_maxX_reference_output_sha256':prior_row.get('output_sha256'),'manual_output_differs_from_v0833_reference':_sha256(out)!=prior_row.get('output_sha256'),'candidate_certification_id':last.get('certification_id'),'candidate_certification_test':last.get('test'),'candidate_certification_isolated':True,'production_extent_still_blocked':True,'production_extent_error':prod_error,'production_extent_output_created':False,'real_certification_count_before':real_count_before,'real_certification_count_after':real_count_after,'real_certification_registry_sha256_before':real_sha_before,'real_certification_registry_sha256_after':real_sha_after,'real_certification_registry_modified':False,'single_object_production_policy_modified':False,'cross_object_production_policy_modified':False,'writer_modules_modified':False,'client_source_sha256_before':source_sha_before,'client_source_sha256_after':source_sha_after,'client_modified':False,'output_smd':str(out),'output_sha256':_sha256(out),'multibone_outward_extent_live_write_authorized':False,'extent_contraction_write_authorized':False,'multi_vertex_extent_write_authorized':False,'cross_object_extent_write_authorized':False,'topology_write_authorized':False,'ready_for_multibone_outward_extent_promotion_gate':True,'policy':{'scope':'one real manual at_dragon multi-bone outward extent transaction; one mesh object and exactly one changed vertex; maxX witness only','manual_edit':'one selected vertex is persisted in EDIT_MESH and the artist performs one human-friendly G/X/value outward transform chosen only after the physical planner proves it safe','preflight':'V0.8.35 first requires the exact V0.8.34 +64-vs-+53 mismatch failure, then physically prevalidates a human-friendly maxX delta; the saved fixed-point position must exactly equal that new target before candidate writer execution','binary_equivalence':'because the manual target is intentionally changed from the minimal V0.8.33 witness, byte identity to V0.8.33 is not required; instead the live candidate result must exactly match the independently prevalidated object/vertex, bound-field shape, resulting bounds and affected-bone set','certification':'manual PASS is candidate-labelled only in an isolated registry; real registry and both production policies stay byte-identical','production_control':'the exact existing production writer must continue rejecting the same saved extent blend','authorization':'this manual PASS is promotion evidence only; production extent remains unauthorized','next_on_pass':'build V0.8.36 multi-bone outward extent production-promotion gate for the exact one-vertex field shapes after full regression/negative/manual evidence checks','deferred':'contraction, topology, multi-vertex extent and cross-object extent remain fail-closed'}}
    rp=work/'manual_write_result.json'; rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_multibone_extent_manual_candidate=PASS changed_vertices=1 target=maxX extent_authorized=false ready_for_promotion_gate=true')
    return report

def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description='V0.8.35 interactive/manual one-vertex multi-bone outward extent candidate'); ap.add_argument('--root',required=True); ap.add_argument('--logical',required=True); ns=ap.parse_args(argv)
    try: run(pathlib.Path(ns.root),ns.logical); return 0
    except Exception as exc:
        root=pathlib.Path(ns.root).resolve(); work=root/WORK_REL; work.mkdir(parents=True,exist_ok=True); out=work/'manual_write_result.json'
        report={'format':FORMAT,'status':'FAIL','release_version':RELEASE_VERSION,'logical':ns.logical,'error':f'{type(exc).__name__}:{exc}','multibone_outward_extent_live_write_authorized':False}
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); print('rare_rigid_multibone_extent_manual_candidate=FAIL'); return 2
if __name__=='__main__': raise SystemExit(main())
