from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .authoring import authoring_plan
from .build_provenance import sha256_file, write_build_provenance
from .static_authoring_candidate import build_static_candidate_blender_command
from .static_roundtrip import _parse as parse_model062_bytes
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner
from .blender_workspace import asset_workspace_name

FORMAT='PT_STATIC_SEMANTIC_AUTOMATED_DEVTEST_V1'
BATCH_FORMAT='PT_STATIC_SEMANTIC_AUTOMATED_DEVTEST_BATCH_V1'


def _work_root(project_root: pathlib.Path, domain: str, asset_path: str) -> pathlib.Path:
    return pathlib.Path(project_root).resolve()/'pt_build'/'devtest'/'static_semantic_auto'/str(domain).lower()/asset_workspace_name(asset_path)


def validate_static_stress_output(source: pathlib.Path, output: pathlib.Path, target_objects: list[str]) -> dict[str,Any]:
    source=pathlib.Path(source).resolve(); output=pathlib.Path(output).resolve()
    s=parse_model062_bytes(source.read_bytes()); o=parse_model062_bytes(output.read_bytes())
    errors=[]
    if s['n']!=o['n']: errors.append('OBJECT_COUNT')
    if s['mat_count']!=o['mat_count']: errors.append('MATERIAL_COUNT')
    if s['mat_region']!=o['mat_region']: errors.append('MATERIAL_REGION_BYTES')
    if set(s['objects'])!=set(o['objects']): errors.append('OBJECT_NAMES')
    target_cf={x.casefold() for x in target_objects}; by_actual={x.casefold():x for x in set(s['objects']) & set(o['objects'])}
    missing=[x for x in target_objects if x.casefold() not in by_actual]
    if missing: errors.append('TARGET_MISSING')
    non_target=[]
    for name in set(s['objects']) & set(o['objects']):
        if name.casefold() in target_cf: continue
        if s['objects'][name]['block'] != o['objects'][name]['block']: non_target.append(name)
    if non_target: errors.append('NON_TARGET_BLOCK_CHANGED')
    targets={}; edit_observed={}; topology_changed={}
    for requested in target_objects:
        actual=by_actual.get(requested.casefold())
        if actual is None: continue
        a=s['objects'][actual]; b=o['objects'][actual]; terr=[]
        if a['phys'] or b['phys']: terr.append('PHYSIQUE_PRESENT')
        if any([a['nr'],a['np'],a['ns'],b['nr'],b['np'],b['ns']]): terr.append('OBJECT_LOCAL_ANIMATION_PRESENT')
        depths=[len(f.get('uv_layers') or []) for f in b['faces']]
        if not depths or min(depths)!=1 or max(depths)!=1: terr.append('OUTPUT_TEXLINK_NOT_SINGLE_LAYER')
        if b['nv']<3 or b['nf']<1: terr.append('OUTPUT_GEOMETRY_EMPTY')
        if terr: errors.extend([f'{actual}:{x}' for x in terr])
        same=a['block']==b['block']; edit_observed[actual]=not same
        topology_changed[actual]=[a['nv'],a['nf']] != [b['nv'],b['nf']]
        targets[actual]={'source_counts':[a['nv'],a['nf'],a['nt']],'output_counts':[b['nv'],b['nf'],b['nt']],'target_block_byte_identical':same,'topology_changed':topology_changed[actual],'texlink_layer_depths':sorted(set(depths)),'errors':terr}
    not_edited=[x for x,v in edit_observed.items() if not v]
    if not_edited: errors.append('STATIC_TARGET_EDIT_NOT_OBSERVED')
    return {'format':'PT_STATIC_SEMANTIC_AUTOMATED_VERIFY_V1','status':'PASS' if not errors else 'FAIL','source':str(source),'output':str(output),'objects':target_objects,'targets':targets,'edit_observed_by_object':edit_observed,'all_target_edits_observed':bool(edit_observed) and all(edit_observed.values()),'targets_without_observed_edit':not_edited,'topology_changed_by_object':topology_changed,'topology_change_observed':any(topology_changed.values()),'non_target_changed':non_target,'errors':errors,'candidate_only':True,'production_authorized':False,'client_write_authorized':False,'client_modified':False}


def choose_static_semantic_representatives(registry, resolver, domain: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Choose physically authorable static witnesses with deterministic backfill.

    Registry complexity alone is not enough: some shipped static containers parse
    correctly but have no object that the saved-Blender candidate writer can edit.
    Release planning must not spend its witness budget on those assets.  This
    selector reads sources only, asks the same ``authoring_plan`` used by the
    writer, and keeps scanning until the requested number of actually authorable
    witnesses is found.  Absence remains explicit: an empty result never paints a
    domain green.
    """
    from .release_1_coverage import content_domain

    rows=[]
    for asset in registry.assets:
        if asset.family != 'SMD_MODEL_062_STATIC' or content_domain(asset) != str(domain):
            continue
        rows.append({
            'asset_id':asset.asset_id,'asset':asset.primary_path,'domain':str(domain),
            'object_count':int(asset.object_count or 0),'material_count':int(asset.material_count or 0),
            'total_vertices':int(asset.total_vertices or 0),'total_faces':int(asset.total_faces or 0),
            'size':int(asset.size or 0),
        })
    if not rows or int(limit) <= 0:
        return []
    key=lambda r:(r['object_count'],r['material_count'],r['total_faces'],r['size'],r['asset'].casefold())
    ordered=sorted(rows,key=key)
    candidate_order=[]
    # Complexity extremes first, then quantiles, then every remaining row.
    for idx in (0, len(ordered)-1, len(ordered)//4, len(ordered)//2, (3*len(ordered))//4):
        if 0 <= idx < len(ordered): candidate_order.append(ordered[idx])
    candidate_order.extend(reversed(ordered))
    candidate_order.extend(ordered)
    out=[]; seen=set()
    for row in candidate_order:
        aid=str(row['asset_id'])
        if aid in seen: continue
        seen.add(aid)
        try:
            asset=registry.resolve(row['asset'])
            source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
            plan=authoring_plan(asset,source)
            eligible=list(((plan.get('channels') or {}).get('geometry') or {}).get('eligible_objects') or [])
            if not eligible:
                continue
            picked=dict(row)
            picked['eligible_object_count']=len(eligible)
            picked['eligible_objects']=eligible
            picked['physical_authoring_preflight']='PASS'
            out.append(picked)
            if len(out) >= int(limit): break
        except Exception:
            continue
    return out


def run_static_semantic_automated_devtest(settings,asset_registry,resolver,certifications,*,asset_path:str,domain:str,amplitude:float=0.08,require_topology:bool=True)->dict[str,Any]:
    asset=asset_registry.resolve(asset_path)
    if asset.family!='SMD_MODEL_062_STATIC': raise RuntimeError(f'static semantic devtest requires SMD_MODEL_062_STATIC, got {asset.family}')
    project_root=pathlib.Path(settings.project_root).resolve(); work=_work_root(project_root,domain,asset.primary_path)
    if work.exists(): shutil.rmtree(work)
    import_work,edit_work,build_work,reimport_work=[work/x for x in ('01_import','02_edit','03_candidate','04_reimport')]
    for p in (import_work,edit_work,build_work,reimport_work): p.mkdir(parents=True,exist_ok=True)
    runner=ValidationRunner(ValidationContext(settings,resolver,certifications)); runner.structural(asset)
    overlay,texture_report=runner._texture_overlay(asset,import_work)
    source,pristine,_lod=runner._prepare_static_blend(asset,import_work,overlay)
    plan=authoring_plan(asset,pathlib.Path(source)); eligible=list(((plan.get('channels') or {}).get('geometry') or {}).get('eligible_objects') or [])
    if not eligible: raise RuntimeError('static semantic devtest has no saved-Blender candidate eligible objects')
    edit_modes={name:('TOPOLOGY' if require_topology and i==0 else 'DEFORM') for i,name in enumerate(eligible)}
    edit_plan={'format':'PT_STATIC_SEMANTIC_AUTOMATED_EDIT_PLAN_V1','domain':domain,'asset':asset.primary_path,'objects':eligible,'edit_modes':edit_modes,'amplitude':float(amplitude),'source_sha256':sha256_file(source)}
    ep=edit_work/'edit_plan.json'; ep.write_text(json.dumps(edit_plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    edited_blend=edit_work/'automatically_edited.blend'; edit_report=edit_work/'edit_report.json'; script=project_root/'pt_asset_tool'/'blender'/'apply_static_semantic_devtest.py'
    run_logged(settings.blender_command()+['--background',str(pristine),'--python-exit-code','1','--python',str(script),'--','--plan',str(ep),'--out',str(edited_blend),'--report',str(edit_report)],edit_work/'01_automatic_edit.log')
    edit_data=json.loads(edit_report.read_text(encoding='utf-8'))
    if edit_data.get('status')!='PASS' or int(edit_data.get('target_count') or 0)!=len(eligible): raise RuntimeError(f'automatic static edit failed: {edit_data}')
    if require_topology and int(edit_data.get('topology_edit_count') or 0)<1: raise RuntimeError('automatic static devtest did not exercise topology change')

    output=build_work/pathlib.PurePosixPath(asset.primary_path).name; steps_dir=build_work/'steps'; steps_dir.mkdir(parents=True,exist_ok=True); current=pathlib.Path(source).resolve(); steps=[]
    for idx,name in enumerate(eligible,start=1):
        step_output=output if idx==len(eligible) else steps_dir/f'{idx:02d}_{name}.smd'; report=steps_dir/f'{idx:02d}_{name}.writer.json'; log=steps_dir/f'{idx:02d}_{name}.log'
        candidate={'status':'READY','blend':str(edited_blend),'source':str(current),'source_sha256':sha256_file(current),'object':name,'output':str(step_output)}
        run_logged(build_static_candidate_blender_command(settings,candidate,report=report),log)
        data=json.loads(report.read_text(encoding='utf-8'))
        steps.append({'index':idx,'object':name,'edit_mode':edit_modes[name],'input_sha256':sha256_file(current),'output_sha256':sha256_file(step_output),'source_counts':data.get('source_counts'),'output_counts':data.get('output_counts')})
        current=step_output.resolve()
    verification=validate_static_stress_output(source,output,eligible)
    if verification.get('status')!='PASS': raise RuntimeError(f'combined static candidate failed: {verification.get("errors")}')
    if require_topology and not verification.get('topology_change_observed'): raise RuntimeError('combined static output did not preserve a topology-changing edit')
    writer_summary=build_work/'writer_summary.json'; writer_summary.write_text(json.dumps({'tool':'PT_STATIC_SEMANTIC_AUTOMATED_DEVTEST_WRITER_V1','step_count':len(steps),'steps':steps,'output_sha256':sha256_file(output)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    provenance=write_build_provenance(output,asset=asset,source=source,build_mode='CANDIDATE_STATIC_SEMANTIC_AUTOMATED_DEVTEST',adapter='pt_blender_to_smd_static_v1.py',build_status='PASS',production_authorized=False,evidence={'automated_devtest':True,'semantic_domain':domain,'candidate_objects':eligible,'all_target_edits_observed':bool(verification.get('all_target_edits_observed')),'topology_change_observed':bool(verification.get('topology_change_observed')),'non_target_changed':list(verification.get('non_target_changed') or []),'verification_errors':list(verification.get('errors') or []),'writer_summary':str(writer_summary)})

    parsed=parse_model062_bytes(output.read_bytes()); expected={'format':'PT_STATIC_SEMANTIC_AUTOMATED_REIMPORT_EXPECTED_V1','objects':{}}
    for name in eligible:
        obj=parsed['objects'].get(name)
        if obj is None: raise RuntimeError(f'candidate missing static target before reimport: {name}')
        expected['objects'][name]={'vertices':int(obj['nv']),'faces':int(obj['nf'])}
    expected_path=reimport_work/'expected.json'; expected_path.write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    blend=reimport_work/'candidate_reimport.blend'; import_script=project_root/'pt_smd_blender_import_v4_generic.py'
    run_logged(settings.blender_command()+['--background','--python-exit-code','1','--python',str(import_script),'--','--smd',str(output),'--client-root',str(overlay),'--out',str(blend),'--no-pack'],reimport_work/'01_import.log')
    check_report=reimport_work/'check.json'; check_script=project_root/'pt_asset_tool'/'blender'/'check_static_semantic_devtest.py'
    run_logged(settings.blender_command()+['--background',str(blend),'--python-exit-code','1','--python',str(check_script),'--','--expected',str(expected_path),'--report',str(check_report)],reimport_work/'02_check.log')
    checked=json.loads(check_report.read_text(encoding='utf-8'))
    if checked.get('status')!='PASS': raise RuntimeError(f'static candidate reimport failed: {checked.get("errors")}')
    result={'format':FORMAT,'status':'PASS','domain':domain,'asset':asset.primary_path,'source_sha256':sha256_file(source),'texture_ready':bool(texture_report.get('ready',True)),'automatic_edit':{'status':edit_data.get('status'),'target_count':edit_data.get('target_count'),'topology_edit_count':edit_data.get('topology_edit_count'),'objects':eligible,'edit_modes':edit_modes,'report':str(edit_report)},'candidate':{'status':verification.get('status'),'artifact':str(output),'artifact_sha256':sha256_file(output),'provenance':str(provenance),'writer_step_count':len(steps),'all_target_edits_observed':bool(verification.get('all_target_edits_observed')),'topology_change_observed':bool(verification.get('topology_change_observed')),'non_target_changed':list(verification.get('non_target_changed') or []),'errors':list(verification.get('errors') or []),'writer_summary':str(writer_summary)},'reimport':{'status':'PASS','checked_object_count':checked.get('checked_object_count'),'blend':str(blend),'check_report':str(check_report)},'automatic_devtest_pass':True,'runtime_authorized':False,'production_authorized':False,'client_write_authorized':False,'client_modified':False,'workdir':str(work)}
    rp=work/'result.json'; result['report']=str(rp); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return result


def run_static_semantic_automated_devtest_batch(settings,asset_registry,resolver,certifications,rows:list[dict[str,Any]],*,amplitude:float=0.08,require_topology:bool=True)->dict[str,Any]:
    results=[]; failures=[]
    for row in rows:
        try: results.append(run_static_semantic_automated_devtest(settings,asset_registry,resolver,certifications,asset_path=row['asset'],domain=row['domain'],amplitude=amplitude,require_topology=require_topology))
        except Exception as exc: failures.append({'asset':row.get('asset'),'domain':row.get('domain'),'error':f'{type(exc).__name__}: {exc}'})
    result={'format':BATCH_FORMAT,'status':'PASS' if results and not failures else 'FAIL','requested':len(rows),'passed_assets':[x.get('asset') for x in results],'failed_assets':failures,'results':results,'automatic_only':True,'runtime_authorized':False,'production_authorized':False,'client_write_authorized':False,'client_modified':False}
    out=pathlib.Path(settings.project_root).resolve()/'pt_build'/'devtest'/'static_semantic_auto'/'batch_result.json'; out.parent.mkdir(parents=True,exist_ok=True); result['report']=str(out); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return result


CORPUS_FORMAT='PT_MODEL062_STATIC_PHYSICAL_CORPUS_AUDIT_V1'

def audit_model062_static_physical_corpus(registry,resolver,*,sample_limit:int=100)->dict[str,Any]:
    """Physically reparse every canonical static Model0.62 asset.

    The representative Blender gate proves topology-changing authoring.  This
    corpus gate separately proves that the fixed Model0.62 object/face/TexLink
    layout closes on every shipped STATIC member and agrees with canonical
    inventory counts.  Object-local keys are allowed here; Physique is not.
    """
    from collections import Counter
    from .release_1_coverage import CONTENT_DOMAINS, content_domain
    by_domain={d:Counter() for d in CONTENT_DOMAINS}; rows=[]; failures=[]
    for asset in registry.assets:
        if str(asset.family or '')!='SMD_MODEL_062_STATIC':
            continue
        domain=content_domain(asset)
        if domain not in by_domain:
            continue
        by_domain[domain]['ASSET_COUNT'] += 1
        try:
            source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
            parsed=parse_model062_bytes(source.read_bytes())
            objects=list((parsed.get('objects') or {}).values())
            object_count=len(objects)
            vertices=sum(int(o.get('nv') or 0) for o in objects)
            faces=sum(int(o.get('nf') or 0) for o in objects)
            texlinks=sum(int(o.get('nt') or 0) for o in objects)
            physique=[str(o.get('name') or '') for o in objects if bool(o.get('phys'))]
            errors=[]
            expected_object=int(getattr(asset,'object_count',0) or 0)
            expected_vertices=int(getattr(asset,'total_vertices',0) or 0)
            expected_faces=int(getattr(asset,'total_faces',0) or 0)
            expected_materials=int(getattr(asset,'material_count',0) or 0)
            expected_texlinks=int((getattr(asset,'source_record',{}) or {}).get('total_texlinks') or 0)
            if expected_object and object_count!=expected_object: errors.append('OBJECT_COUNT')
            if expected_vertices and vertices!=expected_vertices: errors.append('VERTEX_COUNT')
            if expected_faces and faces!=expected_faces: errors.append('FACE_COUNT')
            if int(parsed.get('mat_count') or 0)!=expected_materials: errors.append('MATERIAL_COUNT')
            if expected_texlinks and texlinks!=expected_texlinks: errors.append('TEXLINK_COUNT')
            if physique: errors.append('PHYSIQUE_PRESENT_IN_STATIC_FAMILY')
            if errors:
                raise RuntimeError(','.join(errors))
            animated=sum(1 for o in objects if any(int(o.get(k) or 0)>0 for k in ('nr','np','ns')))
            by_domain[domain]['OBJECT_COUNT'] += object_count
            by_domain[domain]['VERTEX_COUNT'] += vertices
            by_domain[domain]['FACE_COUNT'] += faces
            by_domain[domain]['TEXLINK_COUNT'] += texlinks
            by_domain[domain]['OBJECTS_WITH_LOCAL_KEYS'] += animated
            row={'asset_id':asset.asset_id,'asset':asset.primary_path,'domain':domain,'status':'PASS',
                 'object_count':object_count,'material_count':int(parsed.get('mat_count') or 0),
                 'vertices':vertices,'faces':faces,'texlinks':texlinks,'objects_with_local_keys':animated}
            rows.append(row)
        except Exception as exc:
            by_domain[domain]['FAIL_COUNT'] += 1
            row={'asset_id':asset.asset_id,'asset':asset.primary_path,'domain':domain,'status':'FAIL',
                 'error':f'{type(exc).__name__}: {exc}'}
            rows.append(row); failures.append(row)
    pass_domains=[]; domain_summary={}
    for d,c in by_domain.items():
        count=int(c.get('ASSET_COUNT') or 0); fail=int(c.get('FAIL_COUNT') or 0)
        status='PASS' if count and not fail else ('NOT_PRESENT' if not count else 'FAIL')
        domain_summary[d]={**dict(sorted(c.items())),'status':status}
        if status=='PASS': pass_domains.append(d)
    return {'format':CORPUS_FORMAT,'status':'PASS' if rows and not failures else ('EMPTY' if not rows else 'FAIL'),
            'asset_count':len(rows),'failure_count':len(failures),'pass_domains':sorted(pass_domains),
            'by_domain':domain_summary,'failure_sample':failures[:max(0,int(sample_limit))],'rows':rows,
            'policy':{'corpus_wide_physical_parse':True,'topology_candidate_is_separate_representative_gate':True,
                      'production_authorized':False,'client_write_authorized':False},
            'client_modified':False}
