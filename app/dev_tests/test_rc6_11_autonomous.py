from __future__ import annotations
import json

import pathlib
from types import SimpleNamespace

import pt_asset_tool.rigid_context_census as census
import pt_asset_tool.standalone_rigid_devtest as standalone
import pt_asset_tool.writer_corpus_audit as writer
import pt_asset_tool.static_semantic_devtest as staticdev


def _asset(path, *, skeleton='', records=None, family='SMD_MODEL_062_RIGID_PHYSIQUE', category='EFFECT'):
    rec = records or {
        'total_texlinks': 4,
        'objects': [
            {'node_name': 'mesh_a', 'nVertex': 3, 'nFace': 2, 'nTexLink': 2},
            {'node_name': 'mesh_b', 'nVertex': 3, 'nFace': 2, 'nTexLink': 2},
        ],
    }
    return SimpleNamespace(
        asset_id='AST-'+path, primary_path=path, family=family, category=category,
        binding_mode='ROOT_SKELETON_BOUND' if skeleton else 'NONE',
        binding_source='TEST' if skeleton else 'NONE', binding_skeleton_smb=skeleton,
        configs=[], source_record=rec, object_count=2, total_vertices=6,
        total_faces=4, material_count=1,
    )


class Registry:
    def __init__(self, assets, records):
        self.assets = assets
        self.records = records


def test_structural_check_external_parent_support_is_rigid_only(monkeypatch, tmp_path):
    smd = tmp_path/'a.smd'; smb = tmp_path/'a.smb'; smd.write_bytes(b'x'); smb.write_bytes(b'y')
    fake = SimpleNamespace(
        parse_smd=lambda _p: {'bind_bone_names': {'Bone'}, 'objects': []},
        parse_smb=lambda _p: {
            'bone_names': {'Bone'}, 'bones': [{'name': 'Bone'}],
            'parent_errors': [{'name': 'Bone', 'parent': 'ExternalRoot'}],
        },
    )
    import sys
    monkeypatch.setitem(sys.modules, 'pt_character_structural_gate_v2', fake)
    strict = census._structural_check(smd, smb)
    support = census._structural_check(smd, smb, allow_external_parents=True)
    assert strict['status'] == 'FAIL'
    assert support['status'] == 'PASS'
    assert support['external_parent_support'] is True
    assert support['animation_pose_certified'] is False


def test_structural_twin_outvotes_wrong_unique_directory_candidate():
    target = _asset('Effect/New/target.smd')
    twin = _asset('Effect/Old/twin.smd')
    smb_records = [
        {'extension': '.smb', 'relative_path': 'Effect/New/wrong.smb'},
        {'extension': '.smb', 'relative_path': 'Effect/Old/twin.smb'},
    ]
    reg = Registry([target, twin], smb_records)
    direct = standalone.sibling_smb_candidates(reg, target)
    assert direct['candidate_basis'] == 'UNIQUE_DIRECTORY_SMB'
    assert direct['candidate_smb'].endswith('wrong.smb')
    probe = standalone.explicit_skeleton_candidate(reg, target)
    assert probe['candidate_basis'] == 'STRUCTURAL_TWIN_SKELETON'
    assert probe['candidate_smb'].casefold() == 'effect/old/twin.smb'
    assert probe['binding_proven'] is False
    assert probe['requires_structural_gate'] is True


def test_structural_twin_conflict_fails_closed():
    target = _asset('Effect/New/target.smd')
    t1 = _asset('Effect/A/a.smd')
    t2 = _asset('Effect/B/b.smd')
    records = [
        {'extension': '.smb', 'relative_path': 'Effect/A/a.smb'},
        {'extension': '.smb', 'relative_path': 'Effect/B/b.smb'},
    ]
    reg = Registry([target, t1, t2], records)
    probe = standalone.structural_twin_skeleton_candidate(reg, target)
    assert probe['candidate_available'] is False
    assert probe['candidate_basis'] == 'STRUCTURAL_TWIN_CONFLICT'


def test_motion_inx_external_parent_support_skips_before_strict_pose(monkeypatch, tmp_path):
    monkeypatch.setattr(writer, 'parse_smb_structural', lambda *_a, **_k: {
        'hierarchy_closed': False, 'missing_parent_names': ['ExternalRoot']
    })
    monkeypatch.setattr(writer, 'load_motion_system', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('strict evaluator must not run')))
    r = writer._semantic_inx_edit(tmp_path, tmp_path/'a.inx', tmp_path/'a.smb', tmp_path/'out.inx')
    assert r == {'status': 'SKIP', 'reason': 'EXTERNAL_PARENT_SUPPORT_SMB', 'missing_parent_names': ['ExternalRoot']}


def test_static_corpus_uses_physical_object_list(monkeypatch, tmp_path):
    source = tmp_path/'x.smd'; source.write_bytes(b'x')
    # objects dict deliberately loses one duplicate; object_list preserves both.
    obj1={'name':'dup','nv':3,'nf':2,'nt':2,'phys':False,'nr':0,'np':0,'ns':0}
    obj2={'name':'dup','nv':3,'nf':2,'nt':2,'phys':False,'nr':0,'np':0,'ns':0}
    monkeypatch.setattr(staticdev, 'parse_model062_bytes', lambda _b: {
        'objects': {'dup': obj2}, 'object_list': [obj1,obj2], 'mat_count': 1
    })
    asset=SimpleNamespace(
        asset_id='AST-X', primary_path='Effect/x.smd', family='SMD_MODEL_062_STATIC',
        category='EFFECT', object_count=2, total_vertices=6, total_faces=4,
        material_count=1, source_record={'total_texlinks':4},
    )
    reg=SimpleNamespace(assets=[asset])
    resolver=SimpleNamespace(resolve=lambda *_a, **_k: source)
    r=staticdev.audit_model062_static_physical_corpus(reg,resolver)
    assert r['status']=='PASS'
    assert r['failure_count']==0
    assert r['rows'][0]['object_count']==2


def test_blender_importer_preserves_external_parent_metadata_source_contract():
    text=pathlib.Path('pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py').read_text(encoding='utf-8')
    assert 'parent and parent in edit_bones' in text
    assert 'pt_external_parent_count' in text
    assert 'pt_animation_pose_certified' in text
    assert 'external_parents.append' in text


def test_material_declared_strings_allow_only_nul_padding(tmp_path):
    import importlib.util
    path=pathlib.Path('pt_pikeman_smd_material_audit_v1.py')
    spec=importlib.util.spec_from_file_location('material_audit_rc611',path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    strings,pad=mod.decode_expected_cstrings(b'tex.tga\0\0\0\0\0',2)
    assert strings==['tex.tga','']
    assert pad==3
    import pytest
    with pytest.raises(ValueError):
        mod.decode_expected_cstrings(b'tex.tga\0\0X',2)
    # Strict API remains strict by default.
    with pytest.raises(ValueError):
        mod.decode_expected_cstrings(b'tex.tga\0legacy-namea.tg',2)
    # The physical legacy exception is opt-in and only the final declared
    # NameA may be StrLen-bounded without a NUL.
    strings,pad=mod.decode_expected_cstrings(
        b'tex.tga\0legacy-namea.tg',2,allow_final_length_delimited=True
    )
    assert strings==['tex.tga','legacy-namea.tg']
    assert pad==0
    with pytest.raises(ValueError):
        mod.decode_expected_cstrings(
            b'unterminated-first-field',2,allow_final_length_delimited=True
        )


def test_conflicting_duplicate_skeleton_support_remains_rigid_only_contract():
    importer=pathlib.Path('pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py').read_text(encoding='utf-8')
    writer=pathlib.Path('pt_blender_to_smd_free_mesh_v3.py').read_text(encoding='utf-8')
    assert 'duplicate_conflict_direct_physique_refs' in importer
    assert 'pt_duplicate_skeleton_conflict_count' in importer
    assert 'external_parents or duplicate_conflicts' in importer
    assert 'allow_conflicting_duplicates=True' in writer
    assert 'source_direct_conflicts' in writer
    assert 'rigid first-match support is unsafe' in writer


# --- RC6.11 consolidation regressions ---

def test_structural_twin_index_is_cached_once():
    target = _asset('Effect/New/target.smd')
    twin = _asset('Effect/Old/twin.smd')
    reg = Registry([target, twin], [{'extension': '.smb', 'relative_path': 'Effect/Old/twin.smb'}])
    first = standalone._structural_twin_index(reg)
    # Mutating the backing records after the first build must not trigger a second scan.
    reg.records.append({'extension': '.smb', 'relative_path': 'Effect/Old/other.smb'})
    second = standalone._structural_twin_index(reg)
    assert second is first


def test_name_shape_consensus_requires_unanimity_and_direct_peer():
    target = _asset('char/tmABCD/StylishUniform.smd', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    direct = _asset('char/tmABCD/CtmbB03.smd', skeleton='char/tmabcd/m1.smb', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    series = _asset('char/tmABCD/CtmbB01.smd', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    # Give the series peer at least three resolved same-prefix siblings so its own
    # RC6.10 proof rule is satisfied before it contributes to name-shape evidence.
    sibs = [
        _asset(f'char/tmABCD/CtmbB0{i}.smd', skeleton='char/tmabcd/m1.smb', records={'name_shape': 'other', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
        for i in (2,4,5)
    ]
    reg = Registry([target, direct, series, *sibs], [])
    r = standalone.name_shape_consensus_candidate(reg, target)
    assert r['candidate_available'] is True
    assert r['candidate_smb'] == 'char/tmabcd/m1.smb'
    assert r['name_shape_peer_count'] == 2
    assert r['name_shape_direct_resolved_count'] == 1
    assert r['requires_structural_gate'] is True

    conflict = _asset('char/tmABCD/CtmbB99.smd', skeleton='char/tmabcd/m4.smb', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    reg2 = Registry([target, direct, conflict], [])
    r2 = standalone.name_shape_consensus_candidate(reg2, target)
    assert r2['candidate_available'] is False
    assert r2['candidate_basis'] == 'NAME_SHAPE_CONFLICT'


def test_name_shape_consensus_does_not_guess_with_one_peer():
    target = _asset('char/tmABCD/StylishUniform.smd', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    direct = _asset('char/tmABCD/CtmbB03.smd', skeleton='char/tmabcd/m1.smb', records={'name_shape': 'fig_pa_#body', 'total_texlinks': 4, 'objects': []}, category='PLAYER')
    r = standalone.name_shape_consensus_candidate(Registry([target, direct], []), target)
    assert r['candidate_available'] is False
    assert r['candidate_basis'] == 'NAME_SHAPE_INSUFFICIENT'


def test_structural_gate_smb_physique_tail_is_counted(tmp_path):
    import importlib.util, struct
    path = pathlib.Path('pt_character_structural_gate_v2.py')
    spec = importlib.util.spec_from_file_location('gate_rc611', path)
    gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
    # One minimal SMB block.  Physique pointer is only a presence flag in the
    # serialized legacy structure; the tail is exactly nVertex*32 bytes.
    nv = 6
    block_len = gate.SO + nv * gate.SV + nv * 32
    total = gate.SH + gate.SI + block_len
    raw = bytearray(total)
    raw[:len(gate.HEADER)] = gate.HEADER
    struct.pack_into('<i', raw, 24, 1)
    info = gate.SH
    name = b'Bip01'
    raw[info:info+len(name)] = name
    struct.pack_into('<i', raw, info+32, block_len)
    struct.pack_into('<i', raw, info+36, gate.SH + gate.SI)
    start = gate.SH + gate.SI
    raw[start+gate.O_NAME:start+gate.O_NAME+len(name)] = name
    struct.pack_into('<I', raw, start+gate.O_PHYS, 1)
    struct.pack_into('<i', raw, start+gate.O_NV, nv)
    f = tmp_path/'p.smb'; f.write_bytes(raw)
    d = gate.parse_smb(f)
    assert d['bones'][0]['has_physique'] is True
    assert d['trailing_bytes'] == 0


def test_fit_local_prepared_is_exactly_legacy_equivalent():
    import importlib.util, math, random, sys, types
    path = pathlib.Path('pt_blender_to_smd_free_mesh_v3.py')
    # Import the pure math helpers outside Blender with minimal module stubs.
    sys.modules.setdefault('bpy', types.ModuleType('bpy'))
    sys.modules.setdefault('bmesh', types.ModuleType('bmesh'))
    mu=types.ModuleType('mathutils'); mu.Matrix=type('Matrix',(),{}); mu.Vector=type('Vector',(),{})
    sys.modules.setdefault('mathutils', mu)
    spec = importlib.util.spec_from_file_location('free_mesh_rc611', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

    def legacy_inv_row3(vec, tm):
        a,b,c=mod.m(tm,1,1)/256.0,mod.m(tm,1,2)/256.0,mod.m(tm,1,3)/256.0
        d,e,f=mod.m(tm,2,1)/256.0,mod.m(tm,2,2)/256.0,mod.m(tm,2,3)/256.0
        g,h,i=mod.m(tm,3,1)/256.0,mod.m(tm,3,2)/256.0,mod.m(tm,3,3)/256.0
        det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
        if abs(det)<1e-12: raise ValueError('singular')
        inv=((e*i-f*h, c*h-b*i, b*f-c*e),
             (f*g-d*i, a*i-c*g, c*d-a*f),
             (d*h-e*g, b*g-a*h, a*e-b*d))
        inv=tuple(tuple(x/det for x in row) for row in inv)
        x,y,z=vec
        return (x*inv[0][0]+y*inv[1][0]+z*inv[2][0],
                x*inv[0][1]+y*inv[1][1]+z*inv[2][1],
                x*inv[0][2]+y*inv[1][2]+z*inv[2][2])

    def legacy(world, tm, radius=4):
        t=(mod.m(tm,4,1)/256.0,mod.m(tm,4,2)/256.0,mod.m(tm,4,3)/256.0)
        q=legacy_inv_row3((world[0]-t[0],world[1]-t[1],world[2]-t[2]),tm)
        center=tuple(int(round(x*256.0)) for x in q)
        best=None
        for dx in range(-radius,radius+1):
            for dy in range(-radius,radius+1):
                for dz in range(-radius,radius+1):
                    cand=(center[0]+dx,center[1]+dy,center[2]+dz)
                    represented=tuple(x/256.0 for x in mod.world_fixed(cand,tm))
                    err2=sum((represented[k]-world[k])**2 for k in range(3))
                    score=(err2,cand)
                    if best is None or score<best[0]: best=(score,cand,represented)
        return best[1],best[2],math.sqrt(best[0][0])

    rnd=random.Random(611)
    checked=0
    for _ in range(500):
        # Row-major fixed-point affine matrix with an invertible near-orthogonal 3x3.
        while True:
            lin=[[rnd.randint(-400,400) for _ in range(3)] for _ in range(3)]
            # Bias diagonal to avoid accidental singularity.
            for i in range(3): lin[i][i] += 256 if lin[i][i] >= 0 else -256
            # pt writer matrices are flat 4x4 row-major and m() is 1-indexed.
            tm=[0]*16
            for r in range(3):
                for c in range(3): tm[r*4+c]=lin[r][c]
            tm[3]=tm[7]=tm[11]=0
            tm[12]=rnd.randint(-10000,10000); tm[13]=rnd.randint(-10000,10000); tm[14]=rnd.randint(-10000,10000); tm[15]=256
            try:
                mod.prepare_fit_local(tm); break
            except ValueError: pass
        world=(rnd.uniform(-100,100),rnd.uniform(-100,100),rnd.uniform(-100,100))
        a=legacy(world,tm); b=mod.fit_local_prepared(world,mod.prepare_fit_local(tm))
        assert a == b
        assert mod.fit_local(world,tm) == b
        checked += 1
    assert checked == 500


def test_motion_all_mode_prepares_context_once_and_audits_each_motion_once(monkeypatch, tmp_path):
    import pt_asset_tool.animation_source_regression as regmod
    motions=[{
        'index':i,'active_container':True,'state_name':('WALK' if i==1 else 'ATTACK' if i==2 else f'S{i}'),
        'repeat':0,'motion_frame':1,'global_start':0,'global_end':1,'engine_start':0,'engine_end':160,
    } for i in range(20)]
    prepare_calls=[]
    fake_inx=SimpleNamespace(validate_with_smb=lambda *_a,**_k:{'check':'PASS'})
    prepared={'parsed':{'layout':{'name':'x'},'motion_count':20},'inxcore':fake_inx,'motions':motions,'active':motions}
    def prepare(*_a,**_k):
        prepare_calls.append(1)
        return prepared
    analyze_calls=[]
    def analyze(_prepared,motion):
        analyze_calls.append(int(motion['index']))
        return {
            'index':int(motion['index']),'frames':1,
            'first_frame_rigidity_score':0.0,'last_frame_rigidity_score':0.0,
            'worst_rigidity':{'score':0.0},
        }
    monkeypatch.setattr(regmod,'prepare_motion_source_audit',prepare)
    monkeypatch.setattr(regmod,'analyze_prepared_motion',analyze)
    r=regmod.audit_animation_source_regression(tmp_path,tmp_path/'x.inx',tmp_path/'x.smb',mode='all')
    assert r['status']=='PASS'
    assert r['audited_motion_count']==20
    assert len(prepare_calls)==1
    assert analyze_calls==list(range(20))


def test_motion_source_wrapper_prepares_once_and_preserves_reference_selection(monkeypatch, tmp_path):
    import pt_asset_tool.motion_core as core
    motions=[
        {'index':0,'active_container':True,'state_name':'STAND','repeat':0,'motion_frame':1,'global_start':0,'global_end':1,'engine_start':0,'engine_end':160},
        {'index':1,'active_container':True,'state_name':'WALK','repeat':0,'motion_frame':1,'global_start':0,'global_end':1,'engine_start':0,'engine_end':160},
        {'index':2,'active_container':True,'state_name':'ATTACK','repeat':0,'motion_frame':1,'global_start':0,'global_end':1,'engine_start':0,'engine_end':160},
    ]
    calls=[]
    prepared={'motions':motions,'active':motions,'names':['Bip01']}
    monkeypatch.setattr(core,'prepare_motion_source_audit',lambda *_a,**_k: prepared)
    def analyze(_prepared,m):
        calls.append(int(m['index']))
        return {'index':int(m['index']),'state':m['state_name'],'repeat':0,'motion_frame':1,'global_start':0,'global_end':1,'engine_start':0,'engine_end':160,'frames':1,'first_frame_rigidity_score':0.0,'last_frame_rigidity_score':0.0,'worst_rigidity':{'score':0.0},'top_bones':[]}
    monkeypatch.setattr(core,'analyze_prepared_motion',analyze)
    monkeypatch.setattr(core,'select_motion',lambda ms,sel: next(m for m in ms if int(m['index'])==int(sel)))
    r=core.audit_motion_source(tmp_path,tmp_path/'x.inx',tmp_path/'x.smb',selector='0')
    assert [m['index'] for m in r['motions']]==[0,1,2]
    assert calls==[0,1,2]

def test_bake_actions_uses_represented_parent_without_tolerance_relaxation():
    text=pathlib.Path('pt_asset_tool/blender/bake_actions.py').read_text(encoding='utf-8')
    assert 'parent_target = represented_pose[parent_pb.name]' in text
    assert "represented_pose[name]=residual['represented_pose']" in text
    assert '_represented_pose_from_trs_basis' in text
    assert 'if err>2e-4' in text
    import re
    cur=re.search(r'AFFINE_SECOND_TRS_THRESHOLD\s*=\s*([^\n]+)',text).group(1).strip()
    # Portable regression contract: RC6.11 changed pose-space handling, not the
    # affine split acceptance threshold. Do not depend on an external RC6.10 tree.
    assert cur == '2e-5'


def test_motion_semantic_failure_is_skip_only_when_source_baseline_also_fails(monkeypatch, tmp_path):
    import pt_asset_tool.writer_corpus_audit as w
    calls=[]
    def audit(_root, inx, smb, mode='all'):
        calls.append((pathlib.Path(inx).name, pathlib.Path(smb).name))
        # First call in the helper is the untouched baseline; make it fail.
        raise RuntimeError('legacy source baseline broken')
    monkeypatch.setattr(w, 'audit_animation_source_regression', audit)
    r=w._semantic_failure_or_baseline_skip(
        project_root=tmp_path, inx=tmp_path/'a.inx', smb=tmp_path/'a.smb',
        edited_error=RuntimeError('edited probe failed'), baseline_cache={}
    )
    assert r['status']=='SKIP'
    assert r['reason']=='SOURCE_BASELINE_UNEVALUABLE'
    assert 'legacy source baseline broken' in r['baseline_error']


def test_motion_semantic_failure_remains_failure_when_source_baseline_passes(monkeypatch, tmp_path):
    import pt_asset_tool.writer_corpus_audit as w
    monkeypatch.setattr(w, 'audit_animation_source_regression', lambda *_a, **_k: {'status':'PASS'})
    import pytest
    with pytest.raises(RuntimeError, match='edited probe failed'):
        w._semantic_failure_or_baseline_skip(
            project_root=tmp_path, inx=tmp_path/'a.inx', smb=tmp_path/'a.smb',
            edited_error=RuntimeError('edited probe failed'), baseline_cache={}
        )


def test_motion_source_baseline_cache_reuses_one_result(monkeypatch, tmp_path):
    import pt_asset_tool.writer_corpus_audit as w
    count={'n':0}
    def audit(*_a, **_k):
        count['n'] += 1
        return {'status':'PASS'}
    monkeypatch.setattr(w, 'audit_animation_source_regression', audit)
    cache={}
    for _ in range(2):
        r=w._source_baseline_semantic(tmp_path,tmp_path/'a.inx',tmp_path/'a.smb',cache)
        assert r['status']=='PASS'
    assert count['n']==1


def test_structural_twin_texture_alias_is_exact_and_unanimous():
    from pt_asset_tool.registry import AssetRegistry
    reg=object.__new__(AssetRegistry)
    common={
        'kind':'SMD_MODEL_062','compatibility_family':'SMD_MODEL_062_STATIC',
        'object_count':1,'total_vertices':50,'total_faces':66,'total_texlinks':66,'material_count':1,
        'objects':[{'node_name':'box-02','nVertex':50,'nFace':66,'nTexLink':66}],
    }
    reg.records=[
        {**common,'relative_path':'Effect/New/Object/a.smd','texture_refs':['Effect/New/Object/t.bmp']},
        {**common,'relative_path':'Effect/Old/b_a.smd','texture_refs':['Effect/Old/t.bmp']},
        {'kind':'BMP_STANDARD','relative_path':'Effect/Old/t.bmp'},
    ]
    out=reg._structural_twin_texture_alias_index()
    row=out['effect/new/object/a.smd']['Effect/New/Object/t.bmp']
    assert row['alias']=='Effect/Old/t.bmp'
    assert row['basis']=='EXACT_STRUCTURAL_TWIN_TEXTURE'


def test_structural_twin_texture_alias_conflict_fails_closed():
    from pt_asset_tool.registry import AssetRegistry
    reg=object.__new__(AssetRegistry)
    common={
        'kind':'SMD_MODEL_062','compatibility_family':'SMD_MODEL_062_STATIC',
        'object_count':1,'total_vertices':50,'total_faces':66,'total_texlinks':66,'material_count':1,
        'objects':[{'node_name':'box-02','nVertex':50,'nFace':66,'nTexLink':66}],
    }
    reg.records=[
        {**common,'relative_path':'Effect/New/a.smd','texture_refs':['Effect/New/t.bmp']},
        {**common,'relative_path':'Effect/Old/b_a.smd','texture_refs':['Effect/Old/t.bmp']},
        {**common,'relative_path':'Effect/Other/b_a.smd','texture_refs':['Effect/Other/t.bmp']},
        {'kind':'BMP_STANDARD','relative_path':'Effect/Old/t.bmp'},
        {'kind':'BMP_STANDARD','relative_path':'Effect/Other/t.bmp'},
    ]
    out=reg._structural_twin_texture_alias_index()
    assert 'effect/new/a.smd' not in out


def test_exact_sibling_stem_texture_alias_requires_model_texture_stem_match():
    from pt_asset_tool.registry import AssetRegistry
    reg=object.__new__(AssetRegistry)
    reg.records=[
        {'kind':'SMD_MODEL_062','compatibility_family':'SMD_MODEL_062_STATIC',
         'relative_path':'Effect/sky/x/night/nighthill.smd','texture_refs':['Legacy/sky/nighthill.tga'],
         'object_count':1,'total_vertices':1,'total_faces':1,'total_texlinks':1,'material_count':1,
         'objects':[{'node_name':'n','nVertex':1,'nFace':1,'nTexLink':1}]},
        {'kind':'TGA_STANDARD','relative_path':'Effect/sky/x/night/nighthill.tga'},
    ]
    reg.by_rel={str(r['relative_path']).casefold():r for r in reg.records}
    out=reg._structural_twin_texture_alias_index()
    row=out['effect/sky/x/night/nighthill.smd']['Legacy/sky/nighthill.tga']
    assert row['alias']=='Effect/sky/x/night/nighthill.tga'
    assert row['basis']=='EXACT_SIBLING_STEM_TEXTURE'


def test_npc_object_token_texture_alias_requires_matching_object_token():
    from pt_asset_tool.registry import AssetRegistry
    reg=object.__new__(AssetRegistry)
    common={'kind':'SMD_MODEL_062','compatibility_family':'SMD_MODEL_062_RIGID_PHYSIQUE',
            'object_count':1,'total_vertices':1,'total_faces':1,'total_texlinks':1,'material_count':1,
            'objects':[{'node_name':'MN-012-body','nVertex':1,'nFace':1,'nTexLink':1}]}
    reg.records=[
        {**common,'relative_path':'char/npc/MN-011/MN-011.smd','category_hint':'NPC',
         'object_names':['MN-012-body'],'texture_refs':['char/npc/MN-011/MN-012-h.BMP']},
        {'kind':'BMP_STANDARD','relative_path':'char/npc/MN-012/MN-012-h.BMP'},
    ]
    reg.by_rel={str(r['relative_path']).casefold():r for r in reg.records}
    out=reg._structural_twin_texture_alias_index()
    row=out['char/npc/mn-011/mn-011.smd']['char/npc/MN-011/MN-012-h.BMP']
    assert row['alias']=='char/npc/MN-012/MN-012-h.BMP'
    assert row['basis']=='NPC_OBJECT_TOKEN_SIBLING_TEXTURE'


def test_current_inventory_texture_alias_surface_is_exactly_nine():
    from pt_asset_tool.registry import AssetRegistry, low_path
    from dev_tests._runtime_context import runtime_registry
    data={'records': runtime_registry().records}
    reg=object.__new__(AssetRegistry)
    reg.records=data['records']
    reg.by_rel={low_path(r.get('relative_path')):r for r in reg.records}
    out=reg._structural_twin_texture_alias_index()
    flat=[(asset,logical,info['alias'],info['basis']) for asset,aliases in out.items() for logical,info in aliases.items()]
    assert len(flat)==9
    assert {x[3] for x in flat} == {
        'EXACT_STRUCTURAL_TWIN_TEXTURE','EXACT_SIBLING_STEM_TEXTURE','NPC_OBJECT_TOKEN_SIBLING_TEXTURE'
    }


def test_standalone_representative_planner_accepts_strategy_without_sibling_list(monkeypatch):
    """Planner fields are strategy-specific; numbered-series probes need no sibling_smbs list."""
    target = _asset('char/tmABCD/CtmbB07.smd', category='PLAYER')
    reg = Registry([target], [])
    monkeypatch.setattr(standalone, 'standalone_rigid_context_eligible', lambda _asset: True)
    monkeypatch.setattr(standalone, 'explicit_skeleton_candidate', lambda _registry, _asset: {
        'candidate_available': True,
        'candidate_smb': 'char/tmabcd/m1.smb',
        'candidate_basis': 'SERIES_SIBLING_CONSENSUS',
        'binding_proven': False,
        'requires_structural_gate': True,
    })
    rows = standalone.choose_standalone_rigid_representatives(reg, 'PLAYER', limit=3)
    assert len(rows) == 1
    assert rows[0]['candidate_basis'] == 'SERIES_SIBLING_CONSENSUS'
    assert rows[0]['sibling_smb_count'] == 0
