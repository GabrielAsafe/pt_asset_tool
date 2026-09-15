#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, random, sys
from pathlib import Path

PLAN_FORMAT="PT_EFFECT_PART_BLENDER_PREVIEW_PLAN_V3"
RESULT_FORMAT="PT_EFFECT_PART_BLENDER_PREVIEW_RESULT_V3"


def _args():
    argv=sys.argv
    argv=argv[argv.index("--")+1:] if "--" in argv else []
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",required=True); ap.add_argument("--out",required=True); ap.add_argument("--report",required=True)
    ap.add_argument("--render-dir",required=True); ap.add_argument("--render-frames",default="1,30,60,90"); ap.add_argument("--render-size",type=int,default=512)
    ap.add_argument("--max-events",type=int,default=64); ap.add_argument("--max-particles-per-event",type=int,default=32); ap.add_argument("--max-total-particles",type=int,default=256)
    ap.add_argument("--frames",type=int,default=120); ap.add_argument("--display-scale",type=float,default=0.02)
    return ap.parse_args(argv)


def mid(spec, default=0.0):
    if not spec: return default
    if spec.get("kind") == "FIXED": return float(spec["value"])
    if spec.get("kind") == "RANGE": return (float(spec["a"])+float(spec["b"]))/2.0
    return default


def sample(spec, rng, default=0.0):
    if not spec: return default
    if spec.get("kind") == "FIXED": return float(spec["value"])
    if spec.get("kind") == "RANGE": return rng.uniform(float(spec["low"]),float(spec["high"]))
    return default


def xyz_sample(spec,rng):
    if not spec or spec.get("kind") != "XYZ3": return (0.0,0.0,0.0)
    return tuple(sample(c,rng) for c in spec["components"])


def rgba(spec,default=(1,1,1,1)):
    if not spec or spec.get("kind") != "RGBA": return default
    return tuple(float(x) for x in spec["rgba01"])


def make_plane_mesh(bpy,name):
    mesh=bpy.data.meshes.new(name+"Mesh")
    mesh.from_pydata([(-.5,-.5,0),(.5,-.5,0),(.5,.5,0),(-.5,.5,0)],[],[(0,1,2,3)])
    mesh.update(); return mesh


def make_material(bpy,name,event,warnings):
    mat=bpy.data.materials.new(name); mat.use_nodes=True
    try: mat.surface_render_method='DITHERED'
    except Exception: pass
    nodes=mat.node_tree.nodes; links=mat.node_tree.links; nodes.clear()
    out=nodes.new("ShaderNodeOutputMaterial")
    emission=nodes.new("ShaderNodeEmission")
    transparent=nodes.new("ShaderNodeBsdfTransparent")
    mix=nodes.new("ShaderNodeMixShader")
    color=rgba((event.get("initial") or {}).get("color"))
    emission.inputs["Color"].default_value=color
    emission.inputs["Strength"].default_value=2.0 if "LAMP" in str((event.get("sourceblendmode") or {}).get("value","")).upper() else 1.0
    alpha=color[3]; mix.inputs[0].default_value=max(0.0,min(1.0,alpha))
    links.new(transparent.outputs[0],mix.inputs[1]); links.new(emission.outputs[0],mix.inputs[2]); links.new(mix.outputs[0],out.inputs[0])
    tex=(event.get("texture") or {}).get("reference") or {}; path=tex.get("resolved_path")
    if path and Path(path).is_file():
        try:
            img=bpy.data.images.load(path,check_existing=True); node=nodes.new("ShaderNodeTexImage"); node.image=img
            links.new(node.outputs["Color"],emission.inputs["Color"])
            if "Alpha" in node.outputs: links.new(node.outputs["Alpha"],mix.inputs[0])
        except Exception as exc:
            warnings.append({"code":"BLENDER_DIRECT_TEXTURE_LOAD_FAILED","path":path,"error":str(exc)})
            mat["pt_texture_load_warning"]=str(exc)
    elif tex.get("legacy_path"):
        warnings.append({"code":"TEXTURE_REFERENCE_UNRESOLVED","legacy_path":tex.get("legacy_path")})
    mat["pt_sourceblendmode"]=str((event.get("sourceblendmode") or {}).get("value",""))
    return mat


def orient_camera(cam,target):
    import mathutils
    direction=mathutils.Vector(target)-cam.location
    cam.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()


def _bounds_add(bounds,p):
    if bounds[0] is None:
        bounds[0]=[float(p[0]),float(p[1]),float(p[2])]; bounds[1]=list(bounds[0]); return
    for i in range(3):
        bounds[0][i]=min(bounds[0][i],float(p[i])); bounds[1][i]=max(bounds[1][i],float(p[i]))


def _frame_camera(cam,bounds):
    if bounds[0] is None:
        center=(0.0,0.0,0.0); radius=4.0
    else:
        center=tuple((bounds[0][i]+bounds[1][i])/2.0 for i in range(3))
        span=math.sqrt(sum((bounds[1][i]-bounds[0][i])**2 for i in range(3)))
        radius=max(2.5,span*0.85)
    cam.location=(center[0]+radius*1.7,center[1]-radius*1.7,center[2]+radius*1.1)
    cam.data.lens=50; cam.data.clip_start=.01; cam.data.clip_end=max(1000.0,radius*30)
    orient_camera(cam,center)
    return {"center":[round(x,6) for x in center],"radius":round(radius,6),"camera_location":[round(float(x),6) for x in cam.location]}


def build(plan,a):
    import bpy
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene; scene.frame_start=1; scene.frame_end=max(2,a.frames); scene.render.fps=30
    root=bpy.data.objects.new("PT_EFFECT_PREVIEW_ROOT",None); scene.collection.objects.link(root)
    root["pt_asset"]=plan["asset"]; root["pt_preview_certification"]=plan["preview_certification"]; root["pt_plan_sha256"]=plan.get("plan_content_sha256","")
    camdata=bpy.data.cameras.new("PT_Preview_Camera"); cam=bpy.data.objects.new("PT_Preview_Camera",camdata); scene.collection.objects.link(cam); scene.camera=cam
    lightdata=bpy.data.lights.new("PT_Key","AREA"); lightdata.energy=700; lightdata.shape='DISK'; lightdata.size=8; light=bpy.data.objects.new("PT_Key",lightdata); scene.collection.objects.link(light); light.location=(4,-4,8)
    try:
        scene.world.color=(0.015,0.015,0.02)
    except Exception: pass
    rng=random.Random(int(plan.get("source_payload_sha256","5054")[:8],16) if plan.get("source_payload_sha256") else 0x5054)
    syspos=xyz_sample(plan.get("position"),rng); syspos=tuple(v*a.display_scale for v in syspos)
    created=0; skipped=[]; warnings=[]; bounds=[None,None]; _bounds_add(bounds,syspos)
    events=plan.get("events",[])
    for ei,event in enumerate(events):
        if ei >= max(0,a.max_events): skipped.append({"event_index":ei,"reason":"MAX_EVENTS"}); continue
        if created >= max(1,a.max_total_particles): skipped.append({"event_index":ei,"reason":"MAX_TOTAL_PARTICLES"}); continue
        coll=bpy.data.collections.new(f"Event_{ei:03d}"); scene.collection.children.link(coll)
        emitter=bpy.data.objects.new(f"Event_{ei:03d}_Emitter",None); coll.objects.link(emitter); emitter.parent=root; emitter.location=syspos; emitter.empty_display_type='SPHERE'; emitter.empty_display_size=.3
        emitter["pt_header"]=str(event.get("header_value","")); emitter["pt_sourceblendmode"]=str((event.get("sourceblendmode") or {}).get("value","")); emitter["pt_loops_source"]=str((event.get("loops") or {}).get("raw",""))
        requested=max(1,int(round(abs(mid(event.get("numparticles"),1)))))
        remaining=max(0,a.max_total_particles-created); n=min(requested,max(1,a.max_particles_per_event),remaining)
        if n <= 0: skipped.append({"event_index":ei,"reason":"MAX_TOTAL_PARTICLES"}); continue
        if n < requested: warnings.append({"code":"PARTICLE_COUNT_CAPPED","event_index":ei,"requested":requested,"created":n})
        mesh=make_plane_mesh(bpy,f"PT_Event_{ei:03d}"); mat=make_material(bpy,f"PT_Event_{ei:03d}_Mat",event,warnings); mesh.materials.append(mat)
        init=event.get("initial") or {}; fade=event.get("fade") or {}; vel=init.get("velocity"); grav=event.get("gravity"); radius=event.get("emitradius")
        start_size=max(.02,abs(mid(init.get("size"),10))*a.display_scale); end_size=max(.001,abs(mid(fade.get("size"),mid(init.get("size"),10)))*a.display_scale)
        life=max(2,min(a.frames-1,int(abs(mid(event.get("lifetime"),2))*30)))
        at_seconds=max(0.0,mid(event.get("at"),0.0)) if (event.get("at") or {}).get("kind") in {"FIXED","RANGE"} else 0.0
        delay_seconds=max(0.0,abs(mid(event.get("delay"),0.0))); base_spawn=1+int((at_seconds+delay_seconds)*30)
        rate=abs(mid(event.get("emitrate"),0.0)); spacing=(30.0/rate) if rate > 0 else (min(30.0,max(1.0,life/2.0))/max(1,n))
        for pi in range(n):
            spawn=min(a.frames,max(1,int(round(base_spawn+pi*spacing)))); end=min(a.frames,spawn+life)
            if end <= spawn: skipped.append({"event_index":ei,"particle_index":pi,"reason":"TIMELINE_OUTSIDE_PREVIEW"}); continue
            obj=bpy.data.objects.new(f"E{ei:03d}_P{pi:03d}",mesh); coll.objects.link(obj); obj.parent=emitter
            rv=xyz_sample(radius,rng); v=xyz_sample(vel,rng); g=xyz_sample(grav,rng)
            p0=tuple(x*a.display_scale for x in rv); dt=(end-spawn)/30.0; p1=tuple((rv[j]+v[j]*dt+0.5*g[j]*dt*dt)*a.display_scale for j in range(3))
            world0=tuple(syspos[j]+p0[j] for j in range(3)); world1=tuple(syspos[j]+p1[j] for j in range(3)); _bounds_add(bounds,world0); _bounds_add(bounds,world1)
            obj.location=p0; obj.scale=(start_size,start_size,start_size); obj.hide_viewport=True; obj.hide_render=True
            obj.keyframe_insert("hide_viewport",frame=max(1,spawn-1)); obj.keyframe_insert("hide_render",frame=max(1,spawn-1))
            obj.hide_viewport=False; obj.hide_render=False; obj.keyframe_insert("hide_viewport",frame=spawn); obj.keyframe_insert("hide_render",frame=spawn); obj.keyframe_insert("location",frame=spawn); obj.keyframe_insert("scale",frame=spawn)
            obj.location=p1; obj.scale=(end_size,end_size,end_size); obj.keyframe_insert("location",frame=end); obj.keyframe_insert("scale",frame=end)
            obj.hide_viewport=True; obj.hide_render=True; obj.keyframe_insert("hide_viewport",frame=min(a.frames,end+1)); obj.keyframe_insert("hide_render",frame=min(a.frames,end+1))
            con=obj.constraints.new(type='TRACK_TO'); con.target=cam; con.track_axis='TRACK_Z'; con.up_axis='UP_Y'; created += 1
    framing=_frame_camera(cam,bounds); scene["pt_effect_preview_approximate"]=True; scene["pt_source_asset"]=plan["asset"]
    return {"created_sprite_objects":created,"event_count":len(events),"skipped":skipped,"warnings":warnings,"bounds":{"min":bounds[0],"max":bounds[1]},"framing":framing,"limits":{"max_events":a.max_events,"max_particles_per_event":a.max_particles_per_event,"max_total_particles":a.max_total_particles,"frames":a.frames}}


def render_previews(bpy,scene,a):
    render_dir=Path(a.render_dir).resolve(); render_dir.mkdir(parents=True,exist_ok=True)
    size=max(64,min(2048,int(a.render_size))); scene.render.resolution_x=size; scene.render.resolution_y=size; scene.render.resolution_percentage=100
    frames=[]
    for token in str(a.render_frames).split(','):
        try: f=max(1,min(a.frames,int(token.strip())))
        except Exception: continue
        if f not in frames: frames.append(f)
    if not frames: frames=[min(a.frames,30)]
    files=[]; errors=[]
    for frame in frames:
        scene.frame_set(frame); out=render_dir/f"frame_{frame:04d}.png"; scene.render.filepath=str(out)
        try:
            bpy.ops.render.render(write_still=True)
            if out.is_file(): files.append(str(out))
            else: errors.append({"frame":frame,"error":"RENDER_FILE_MISSING"})
        except Exception as exc:
            errors.append({"frame":frame,"error":str(exc)})
    return files,errors


def main():
    a=_args(); plan=json.loads(Path(a.plan).read_text(encoding='utf-8'))
    if plan.get("format") != PLAN_FORMAT: raise RuntimeError("unexpected preview plan format")
    result=build(plan,a)
    import bpy
    out=Path(a.out).resolve(); report=Path(a.report).resolve(); out.parent.mkdir(parents=True,exist_ok=True); report.parent.mkdir(parents=True,exist_ok=True)
    render_files,render_errors=render_previews(bpy,bpy.context.scene,a)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    payload={"format":RESULT_FORMAT,"status":"PASS","asset":plan["asset"],"source_payload_sha256":plan.get("source_payload_sha256"),"plan_content_sha256":plan.get("plan_content_sha256"),"preview_certification":"BLENDER_PREVIEW_APPROXIMATE","blend":str(out),"render_files":render_files,"render_errors":render_errors,**result,"production_authorized":False,"client_write_authorized":False,"server_write_authorized":False}
    report.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding='utf-8'); print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__ == '__main__': main()
