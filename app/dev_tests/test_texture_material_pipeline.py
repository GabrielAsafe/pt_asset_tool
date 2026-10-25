"""Post-upscale workflow: engine gating, identity, review, maps and legacy codecs."""
import hashlib
import io
import json
from pathlib import Path
import pytest

Image=pytest.importorskip('PIL.Image')
from pt_asset_tool import texture_material_pipeline as m
from pt_asset_tool import texture_upscale as t
from pt_asset_tool.texture_material_maps import height_from_diffuse, normals_from_height, renormalize_normals
from pt_protected_tga_v1 import protect_header


def create(root, name, img=None):
    path=root/name
    path.parent.mkdir(parents=True,exist_ok=True)
    im=img or Image.new('RGBA',(13,9),(100,100,50,255))
    im.save(path)
    return path


def perform(root, output, **kwargs):
    args=dict(include=[],exact=[],all_=True,denoise='off',maps='off')
    args.update(kwargs)
    return m.prepare(root,output,**args)


def test_no_rescale_no_mutation_byte_identity_and_map_generation(tmp_path):
    root,out=tmp_path/'live',tmp_path/'stage'
    im=Image.new('RGBA',(20,12),(100,200,30,127)); im.putpixel((4,4),(200,20,10,0))
    src=create(root,'Image/Field/stone.png',im)
    sha=t.sha256_file(src)
    report=perform(root,out,maps='from-diffuse')
    r=report['records'][0]
    assert report['upscale_performed'] is False and report['scaling_factor']==1
    assert r['dimensions']==[20,12] and r['output_sha256']==sha
    assert t.sha256_file(src)==sha
    assert (out/r['output']).read_bytes()==src.read_bytes()
    assert {k for k in r['maps']}=={'height','normal_dx','normal_gl','parallax_demo'}
    assert Image.open(out/r['maps']['normal_dx']['path']).size==(20,12)
    assert (out/'review_001.html').is_file()
    assert m.audit(out/'manifest.json')['client_publish_authorized'] is False


def test_denoise_changes_rgb_but_alpha_identical(tmp_path):
    root,out=tmp_path/'source',tmp_path/'run'
    im=Image.new('RGBA',(15,15),(120,140,88,160));im.putpixel((5,5),(255,2,255,0))
    p=create(root,'Image/Field/wood.png',im)
    before=p.read_bytes()
    r=perform(root,out,denoise='medium')['records'][0]
    assert r['status']=='staged' and r['bytes_changed'] is True
    target=out/r['output']
    assert target.read_bytes()!=before and p.read_bytes()==before
    assert Image.open(target).getchannel('A').tobytes()==im.getchannel('A').tobytes()
    assert Image.open(target).size==im.size


def test_legacy_protected_tga_preserved_without_resize(tmp_path):
    root,out=tmp_path/'input',tmp_path/'output'
    src=create(root,'Image/Field/stone.tga',Image.new('RGBA',(17,12),(50,70,80,65)))
    original=src.read_bytes()
    src.write_bytes(protect_header(original[:18],'FULL18')+original[18:])
    r=perform(root,out,denoise='light')['records'][0]
    assert r['status']=='staged',r.get('reason')
    dest=out/r['output']
    assert dest.read_bytes()[:2]==b'G8'
    assert t.inspect_texture(dest)[0].protected
    assert t.inspect_texture(dest)[0].width==17
    assert t.sha256_file(src)==r['source_sha256']


def test_bmp_black_colorkey_preserved(tmp_path):
    root,out=tmp_path/'input',tmp_path/'output'
    im=Image.new('RGB',(16,16),(20,40,60)); im.putpixel((0,0),(0,0,0))
    im.putpixel((5,5),(255,255,255))
    p=create(root,'Image/Terrain/ground.bmp',im)
    before=p.read_bytes()
    r=perform(root,out,denoise='medium')['records'][0]
    assert r['status']=='staged',r.get('reason')
    result=Image.open(out/r['output']).convert('RGB')
    assert result.getpixel((0,0))==(0,0,0)
    assert sum(tuple(px)==(0,0,0) for px in list(result.get_flattened_data() if hasattr(result,'get_flattened_data') else result.getdata()))==1
    assert r['bmp_black_colorkey_preserved']
    assert p.read_bytes()==before


def test_normal_height_generator_and_wrap():
    h=Image.new('L',(10,10),127)
    n=normals_from_height(h)
    assert n.getpixel((1,1)) in ((128,128,255),(128,128,254))
    n2=normals_from_height(h,convention='opengl')
    assert n2.tobytes()==n.tobytes()
    im=Image.new('RGB',(10,10),(220,90,50))
    assert height_from_diffuse(im).size==(10,10)
    assert renormalize_normals(n).size==(10,10)
    with pytest.raises(ValueError): normals_from_height(h,strength=-1)


def test_source_role_risk_blocks_by_default(tmp_path):
    src,out=tmp_path/'in',tmp_path/'out'
    for name in ('game/Login/button.png','Image/Field/stone_n.png','Image/Field/stone_height.png'):
        create(src,name)
    result=perform(src,out)
    assert result['status_counts']=={'skipped_ui_atlas':1,'skipped_technical':2}
    assert list((out/'overlay').rglob('*'))==[] if (out/'overlay').exists() else True


def test_ai_requires_model_and_does_not_fallback_to_median(tmp_path):
    src,out=tmp_path/'in',tmp_path/'out'
    p=create(src,'Image/Field/stone.png'); before=p.read_bytes()
    d=perform(src,out,denoise='ai')
    assert d['records'][0]['status']=='failed'
    assert 'AI_MODEL_NOT_CONFIGURED' in d['records'][0]['reason']
    assert p.read_bytes()==before
    assert not (out/'overlay'/'Image/Field/stone.png').exists()


def test_external_model_pin_and_scale_one(tmp_path,monkeypatch):
    import subprocess
    model=tmp_path/'weights.pth';model.write_bytes(b'test_weights')
    cfg=tmp_path/'models.json'
    cfg.write_text(json.dumps({'material_overrides':{},'models':{
        'stone': {'engine':'external','model':'weights.pth','sha256':hashlib.sha256(b'test_weights').hexdigest(),
                  'argv':['fake_ai','--input','{input}','--output','{output}','--model','{model}']}}}))
    def fake_run(cmd,**kwargs):
        with Image.open(cmd[cmd.index('--input')+1]) as im:
            im.save(cmd[cmd.index('--output')+1])
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(m.subprocess,'run',fake_run)
    img=Image.new('RGBA',(12,8),(50,60,80,100));img.putpixel((2,2),(25,77,99,0))
    source=tmp_path/'in'
    create(source,'Image/Field/stone.png',img)
    d=perform(source,tmp_path/'out',denoise='ai',config_path=cfg)
    assert d['records'][0]['status']=='staged',d['records'][0].get('reason')
    assert d['records'][0]['ai']['scale']==1
    cfg_data=json.loads(cfg.read_text())
    cfg_data['models']['stone']['sha256']='0'*64
    cfg.write_text(json.dumps(cfg_data))
    d=perform(source,tmp_path/'out2',denoise='ai',config_path=cfg)
    assert d['records'][0]['status']=='failed'
    assert 'MODEL_SHA256_MISMATCH' in d['records'][0]['reason']


def test_external_ai_that_resizes_is_blocked(tmp_path,monkeypatch):
    import subprocess
    model=tmp_path/'weights.pth';model.write_bytes(b'bytes')
    config=tmp_path/'models.json'
    config.write_text(json.dumps({'models':{'default':{'engine':'external','model':'weights.pth',
        'sha256':hashlib.sha256(b'bytes').hexdigest(),'argv':['mock','{input}','{output}']}}}))
    def fake_run(cmd,**kwargs):
        with Image.open(cmd[1]) as im:
            im.resize((im.width*2,im.height*2)).save(cmd[2])
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(m.subprocess,'run',fake_run)
    root=tmp_path/'src'
    create(root,'Image/Field/stone.png')
    d=perform(root,tmp_path/'dst',denoise='ai',config_path=config)
    assert d['records'][0]['status']=='failed'
    assert 'CHANGED_DIMENSIONS' in d['records'][0]['reason']


def test_review_hash_verification_rejects_drift_and_runtime_release_blocked(tmp_path):
    root,out=tmp_path/'in',tmp_path/'out'
    create(root,'Image/Field/wood.png')
    d=perform(root,out)
    r=d['records'][0]
    reviews=tmp_path/'decisions.json'
    reviews.write_text(json.dumps({'format':'PT_MATERIAL_REVIEWS_V1','entries':[
        {'source':r['source'],'output_sha256':r['output_sha256'],'decision':'approve'}]}))
    audit=m.import_reviews(out/'manifest.json',reviews)
    assert audit['all_staged_reviewed'] is True
    assert audit['client_publish_authorized'] is False
    (out/r['output']).write_bytes(b'bad')
    assert 'CANDIDATE_HASH_DRIFT' in [x['reason'] for x in m.audit(out/'manifest.json')['issues']]
    with pytest.raises(ValueError,match='OUTPUT_DRIFT'):
        m.import_reviews(out/'manifest.json',reviews)


def test_no_source_nesting_and_read_only_mesh_audit(tmp_path):
    src=tmp_path/'source';src.mkdir()
    create(src,'Image/Field/stone.png')
    with pytest.raises(ValueError,match='DISJOINT'):
        perform(src,src/'output')
    with pytest.raises(ValueError,match='DISJOINT'):
        perform(src,tmp_path)
    mesh=tmp_path/'meshes';mesh.mkdir()
    (mesh/'model.smd').write_bytes(b'unproven')
    d=m.mesh_diagnostics(mesh)
    assert d['meshes'][0]['status']=='UNSUPPORTED_OR_INVALID_SMD'
    assert not d['runtime_parallax_certified']


def test_height_must_be_authored_for_strict_from_height(tmp_path):
    src=tmp_path/'src'; create(src,'Image/Field/stone.png')
    height=tmp_path/'height';height.mkdir()
    result=perform(src,tmp_path/'out',maps='from-height',height_root=height)
    assert result['records'][0]['status']=='failed'
    assert not (tmp_path/'out'/'overlay'/'Image/Field/stone.png').exists()
    create(height,'Image/Field/stone_height.png',Image.new('L',(13,9),128))
    result=perform(src,tmp_path/'out2',maps='from-height',height_root=height)
    assert result['records'][0]['status']=='staged'
    assert result['records'][0]['height_source']['basis']=='authored'
