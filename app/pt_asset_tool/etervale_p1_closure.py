"""Evidence-driven P1 closure ledger. No inference of visual/runtime fidelity."""
from __future__ import annotations
import json
import pathlib
from typing import Any
from . import etervale_integration as bridge
from .etervale_p1_full import FORMAT as AUDIT_FORMAT

FORMAT='PT_ASSET_ETERVALE_P1_CLOSURE_V4'


def _latest(work:pathlib.Path)->tuple[pathlib.Path|None,dict|None]:
    folder=work/'p1_full'
    if not folder.is_dir():return None,None
    for path in sorted((p for p in folder.glob('*.json') if p.is_file() and not p.is_symlink()),
                       key=lambda p:p.stat().st_mtime_ns,reverse=True):
        if path.stat().st_size > 16*1024*1024:continue
        try:obj=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if obj.get('format')==AUDIT_FORMAT and isinstance(obj.get('assets'),list):
            return path,obj
    return None,None


def inspect(work:pathlib.Path, game_root:pathlib.Path|None=None)->dict:
    p,data=_latest(work)
    gates={k:{'status':'NO_EVIDENCE','details':[]} for k in ('P1_03_DEPENDENCIES','P1_04_QUALITY',
                                                             'P1_05_FIELDS','P1_06_UI')}
    if data is None:
        status='P1_EVIDENCE_INCOMPLETE'
    else:
        source_changed=data.get('game_assets_modified') is not False
        if game_root is not None:
            from .etervale_p1_full import NATIVE_EXTS
            game_root=game_root.resolve(strict=True)
            if str(game_root)!=data.get('game_root'):
                source_changed=True
            else:
                for row in data.get('assets',[]):
                    try:
                        original=bridge._input_path(game_root,row['path'],None,NATIVE_EXTS)
                        if bridge._hash_file(original)!=row.get('sha256'):source_changed=True
                    except (OSError,KeyError,ValueError):source_changed=True
                for row in data.get('effects',[]):
                    try:
                        original=bridge._input_path(game_root,row['path'],None,{'.part'})
                        if bridge._hash_file(original)!=row.get('sha256'):source_changed=True
                    except (OSError,KeyError,ValueError):source_changed=True
                for row in data.get('fields',[]):
                    try:
                        original=bridge._input_path(game_root,'GameServer/'+row['path'],None,
                                                    {'.spm','.spp','.spc'})
                        if bridge._hash_file(original)!=row.get('sha256'):source_changed=True
                    except (OSError,KeyError,ValueError):source_changed=True
        native_assets=data.get('assets') or []
        effect_files=data.get('effects') or []
        effect_ok=bool(effect_files) and all(e.get('status')=='STATIC_PART_NONEMPTY_NOT_RENDER_CERTIFIED' for e in effect_files)
        sample_kinds={r.get('kind') for r in native_assets}
        readers=[a for a in native_assets if a.get('native_reader',{}).get('status')=='READER_ACCEPTED']
        textures=[r for r in native_assets if str(r.get('path','')).lower().endswith(('.tga','.bmp'))]
        stage_model= {'STAGE_072','MODEL_062'}.issubset(sample_kinds)
        animated=all(any(str(a.get('path','')).lower().endswith('.'+ext) for a in native_assets)
                     for ext in ('smb','inx'))
        image_decode=bool(textures) and all(t.get('native_reader',{}).get('image_pixels_decoded') is True
                                            for t in textures)
        native_ok=len(readers)==len(native_assets) and bool(readers)
        dependency_proven=bool(data.get('texture_references')) and not data.get('missing_unacknowledged') and not data.get('acknowledged_unresolved')
        if dependency_proven and not source_changed:
            gates['P1_03_DEPENDENCIES']={'status':'PASS_SCOPED','details':['All used material slots in explicit sample resolved locally']}
        else:
            gates['P1_03_DEPENDENCIES']={'status':'REVIEW_REQUIRED','details':[
                'unacknowledged='+str(len(data.get('missing_unacknowledged',[]))),
                'acknowledged_unresolved='+str(len(data.get('acknowledged_unresolved',[])))]}
        quality_ok=stage_model and animated and native_ok and image_decode and effect_ok and not source_changed
        gates['P1_04_QUALITY']={'status':'PASS_NATIVE_READERS_NOT_VISUAL' if quality_ok else 'INCOMPLETE',
                                 'details':['STAGE_AND_MODEL='+str(stage_model),'SMB_AND_INX='+str(animated),
                                            'ALL_READERS='+str(native_ok),'PIXEL_DECODING='+str(image_decode),
                                            'PART_EFFECT_STATIC_ONLY='+str(effect_ok)]}
        suffixes={pathlib.PurePosixPath(r['path']).suffix.lower() for r in data.get('fields',[])}
        structural=suffixes>={'.spm','.spp','.spc'} and not data.get('field_structural_failures')
        imp=data.get('field_native_import') or {}
        import_ok=imp.get('status')=='NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE' and imp.get('field_rows_in_catalog',0)>0
        gates['P1_05_FIELDS']={'status':'PASS_DISPOSABLE_WORLDIMPORT' if structural and import_ok and not source_changed else 'INCOMPLETE',
                               'details':['STRUCTURAL='+str(structural),'NATIVE_IMPORT='+str(import_ok)]}
        # UI is a real, separately tested read-only consumer, not a runtime preview.
        from .etervale_ui_readiness import board
        ui=board(work.parent)
        ids={item['id'] for item in ui['items']}
        ui_ok='p1_closure' in ids and all(x in ids for x in ('dependencies','quality','fields'))
        gates['P1_06_UI']={'status':'PASS_READ_ONLY_UI' if ui_ok else 'INCOMPLETE',
                            'details':['Read-only evidence board; no asset publishing']}
        status=('P1_AUTOMATED_GATES_PASSED_RUNTIME_REVIEW_PENDING'
                if all(v['status'].startswith('PASS') for v in gates.values()) else 'P1_EVIDENCE_INCOMPLETE')
    return {'format':FORMAT,'status':status,'source_report':str(p) if p else None,
            'gates':gates,'runtime_visual':'NOT_CERTIFIED',
            'renderer_PBR_upgrade':'SEPARATE_PROJECT_NOT_COVERED',
            'physical_collision_and_particle_playback':'MANUAL_RUNTIME_REVIEW_PENDING',
            'game_assets_modified':False}


def run(a:Any)->int:
    work=bridge._work_root()
    result=inspect(work,bridge._game_root(a))
    result['report_file']=bridge._write_report('p1_closure',result)
    bridge._print(result)
    return 0 if result['status']=='P1_AUTOMATED_GATES_PASSED_RUNTIME_REVIEW_PENDING' else 3


def register(sp:Any)->None:
    x=sp.add_parser('p1-closure-audit',help='classify P1 proof gates and pending game runtime review')
    x.add_argument('--repo-root',type=pathlib.Path)
    x.set_defaults(func=run)
