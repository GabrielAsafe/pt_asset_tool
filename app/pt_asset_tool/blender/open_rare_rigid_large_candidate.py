from __future__ import annotations
import argparse, json, pathlib, sys
import bpy, bmesh

def parse(argv):
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); return p.parse_args(argv)

def configure(mp):
    m=json.loads(pathlib.Path(mp).read_text(encoding='utf-8'))
    oi=int(m['object_index']); vertices=[int(x) for x in m['changed_vertex_indices']]
    axis=str(m['uniform_axis']).upper(); delta=float(m['uniform_delta_world'])
    active=bpy.context.view_layer.objects.active
    if active is None or active.type!='MESH': raise RuntimeError('NO_ACTIVE_MESH_FOR_MANUAL_CANDIDATE')
    if active.mode!='EDIT': raise RuntimeError(f'MANUAL_CANDIDATE_MODE_NOT_EDIT:{active.mode}')
    if int(active.get('pt_source_object_index',-1))!=oi: raise RuntimeError('MANUAL_CANDIDATE_OBJECT_MISMATCH')
    bm=bmesh.from_edit_mesh(active.data); selected=sorted(v.index for v in bm.verts if v.select)
    if selected!=vertices: raise RuntimeError(f'MANUAL_CANDIDATE_SELECTION_MISMATCH:{selected}!={vertices}')
    ts=bpy.context.scene.tool_settings
    ts.mesh_select_mode=(True,False,False)
    try: ts.use_proportional_edit='DISABLED'
    except Exception: pass
    if hasattr(ts,'use_mesh_automerge'): ts.use_mesh_automerge=False
    if hasattr(ts,'use_mesh_automerge_and_split'): ts.use_mesh_automerge_and_split=False
    active.lock_location=(True,True,True); active.lock_rotation=(True,True,True); active.lock_scale=(True,True,True)
    instruction=f"Move exactly these {len(vertices)} selected vertices together: G  {axis}  {delta:g}  Enter, then Ctrl+S and close Blender. Do not change selection, UV, weights, topology or object transforms."
    bpy.context.scene['pt_v0819_manual_candidate_instruction']=instruction
    try: bpy.context.workspace.status_text_set(instruction)
    except Exception: pass
    def draw(self, context):
        self.layout.label(text='PT Asset Tool V0.8.19 candidate test')
        self.layout.label(text=f'{len(vertices)} vertices selected on object {oi}')
        self.layout.label(text=f'Press: G  {axis}  {delta:g}  Enter')
        self.layout.label(text='Then Ctrl+S and close Blender.')
        self.layout.label(text='Do not alter selection, UV, weights, topology, or object transforms.')
    try: bpy.context.window_manager.popup_menu(draw,title='V0.8.19 Manual Candidate',icon='INFO')
    except Exception: pass
    print('PT_V0819_MANUAL_UI=READY vertices='+','.join(map(str,vertices))+f' axis={axis} delta={delta:g}')
    return None

def main(argv):
    a=parse(argv); mp=str(pathlib.Path(a.manifest).resolve()); bpy.app.timers.register(lambda:configure(mp),first_interval=0.7)
if __name__=='__main__':
    av=sys.argv; av=av[av.index('--')+1:] if '--' in av else []; main(av)
