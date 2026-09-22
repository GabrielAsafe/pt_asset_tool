#!/usr/bin/env python3
from __future__ import annotations
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args(argv):
    p=argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--size', type=int, default=320)
    return p.parse_args(argv)


def visible_meshes():
    return [o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render]


def bounds_world(objects):
    pts=[]
    for obj in objects:
        for c in obj.bound_box:
            pts.append(obj.matrix_world @ Vector(c))
    if not pts:
        raise RuntimeError('NO_VISIBLE_MESH_BOUNDS')
    mn=Vector((min(p.x for p in pts),min(p.y for p in pts),min(p.z for p in pts)))
    mx=Vector((max(p.x for p in pts),max(p.y for p in pts),max(p.z for p in pts)))
    return mn,mx


def look_at(obj, target):
    direction=target-obj.location
    obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()


def main(argv):
    a=args(argv)
    objects=visible_meshes()
    mn,mx=bounds_world(objects)
    center=(mn+mx)*0.5
    dims=mx-mn
    radius=max(float(dims.x),float(dims.y),float(dims.z),0.5)*0.5

    # Remove prior preview-only camera/lights if a cached blend is rerendered.
    for obj in list(bpy.context.scene.objects):
        if obj.name.startswith('PT_CATALOG_PREVIEW_'):
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data=bpy.data.cameras.new('PT_CATALOG_PREVIEW_CAMERA')
    cam=bpy.data.objects.new('PT_CATALOG_PREVIEW_CAMERA',cam_data)
    bpy.context.scene.collection.objects.link(cam)
    distance=max(radius*3.2,2.0)
    cam.location=center+Vector((distance*0.78,-distance*0.78,distance*0.52))
    cam_data.lens=52
    cam_data.clip_start=max(0.01,radius/100.0)
    cam_data.clip_end=max(1000.0,distance*20.0)
    look_at(cam,center)
    bpy.context.scene.camera=cam

    def light(name, loc, energy, size):
        data=bpy.data.lights.new(name,'AREA'); data.energy=energy; data.shape='DISK'; data.size=size
        obj=bpy.data.objects.new(name,data); bpy.context.scene.collection.objects.link(obj); obj.location=loc; look_at(obj,center); return obj
    light('PT_CATALOG_PREVIEW_KEY', center+Vector((distance*0.7,-distance*0.55,distance*0.9)), 900, max(radius*1.5,2.0))
    light('PT_CATALOG_PREVIEW_FILL', center+Vector((-distance*0.65,-distance*0.15,distance*0.45)), 500, max(radius*1.2,1.5))
    light('PT_CATALOG_PREVIEW_RIM', center+Vector((0,distance*0.75,distance*0.7)), 650, max(radius,1.5))

    scene=bpy.context.scene
    try: scene.render.engine='BLENDER_EEVEE_NEXT'
    except Exception:
        try: scene.render.engine='BLENDER_EEVEE'
        except Exception: pass
    scene.render.resolution_x=max(128,min(768,a.size)); scene.render.resolution_y=scene.render.resolution_x; scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'; scene.render.film_transparent=False
    scene.world.color=(0.055,0.065,0.085)
    out=Path(a.out).expanduser().resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    scene.render.filepath=str(out)
    bpy.ops.render.render(write_still=True)
    print(f'PT_CATALOG_SMD_RENDER=PASS out={out} objects={len(objects)} size={scene.render.resolution_x}')

if __name__=='__main__':
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    main(argv)
