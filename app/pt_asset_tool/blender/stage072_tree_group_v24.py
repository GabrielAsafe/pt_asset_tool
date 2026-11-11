"""V24 Blender inspection of tree groups; only writes private, source-locked JSON.

V23 and its 103 proposal objects remain unchanged; V24 creates a separate
inspection collection from original face IDs, maintaining every UV/material.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty

from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.stage072_tree_groups_v24 import (
    accept_manual_attachment, build_v24_groups, check_v24_groups, group_plan_path,
)
from pt_asset_tool.blender import stage072_tree_v23 as v23

CONFIG = {}
PLAN = None
LOCK = False
COLLECTION = 'PT_V24_ARVORES_AGRUPADAS_INSPECAO'
PREVIEW = 'PT_V24_ARVORE_GLB_PREVIEW'


def _source():
    return v23._source()


def _v23():
    p = CONFIG['v23_provider']()
    if p is None or not p.get('trees'):
        raise ValueError('V24_RECONSTRUIR_V23_PRIMEIRO')
    return p


def _plan_path():
    return group_plan_path(v23._plan_path())


def _save():
    check_v24_groups(PLAN, v23=_v23())
    atomic_write_json(_plan_path(), PLAN)


def _selected(context):
    i = context.scene.pt_v24_active
    if PLAN is None or i < 0 or i >= len(PLAN['groups']):
        return None
    return PLAN['groups'][i]


def _select_group(context):
    c = bpy.data.collections.get(COLLECTION)
    if c is None:
        return
    group = _selected(context)
    gid = group['id'] if group else None
    current = None
    for obj in c.objects:
        is_active = obj.get('pt_v24_group_id') == gid
        obj.hide_set(not is_active)
        obj.select_set(is_active)
        if is_active:
            current = obj
    if current:
        context.view_layer.objects.active = current
    # Keep the older V23 copies out of the way, but never delete them.
    old = bpy.data.collections.get(v23.ISOLATE_COLLECTION)
    if old is not None:
        for obj in old.objects:
            obj.hide_set(True)
            obj.select_set(False)


def _active_update(self, context):
    if not LOCK:
        _select_group(context)


class PT_V24GroupRow(bpy.types.PropertyGroup):
    group_id: StringProperty()


def _refresh(context, focus_id=None):
    global LOCK
    LOCK=True
    try:
        scene=context.scene
        previous=scene.pt_v24_active
        scene.pt_v24_groups.clear()
        groups=PLAN['groups'] if PLAN else []
        for g in groups:
            item=scene.pt_v24_groups.add()
            item.group_id=g['id']
            kind='Tronco' if g['trunk_faces'] else 'Folhas'
            item.name=(f"{kind} · {len(g['source_tree_ids'])} orig. · "
                       f"{len(g['foliage_faces'])}+{len(g['trunk_faces'])} faces")
        if focus_id:
            idx=next((i for i,g in enumerate(groups) if g['id']==focus_id),0)
        else:
            idx=min(previous,max(0,len(groups)-1))
        scene.pt_v24_active=idx
    finally:
        LOCK=False
    _select_group(context)


class PT_OT_V24Build(bpy.types.Operator):
    bl_idname='pt_semantic.v24_group'
    bl_label='Agrupar folhas com troncos'
    bl_description='Cria um plano separado sem alterar propostas V22/V23; não apaga os fragmentos ambíguos'

    def execute(self, context):
        global PLAN
        try:
            old = PLAN
            if old is not None and old.get('groups'):
                # Deliberately do not overwrite manual associations or approvals.
                self.report({'INFO'},'V24 já tem grupos; usa os existentes para revisão')
                print(f'PT_V24_GROUP=REUSED groups={len(old["groups"])} path={_plan_path()}',flush=True)
                _refresh(context)
                return {'FINISHED'}
            v = _v23()
            result=build_v24_groups(v23=v, faces=v23._tree_faces())
            PLAN=result
            _save()
            _refresh(context)
            c=result['counts']
            print(f'PT_V24_GROUP=PASS sources={c["source_proposals"]} groups={c["groups"]} '
                  f'with_trunk={c["with_trunk"]} foliage_only={c["foliage_only"]} '
                  f'auto_attached={c["auto_attached"]} review_suggestions={c["review_suggestions"]} '
                  f'path={_plan_path()} source_unchanged=true',flush=True)
            self.report({'INFO'},f'V24: {c["groups"]} grupos; {c["auto_attached"]} associações seguras')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V24: {type(exc).__name__}: {exc}')
            print(f'PT_V24_GROUP=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V24Separate(bpy.types.Operator):
    bl_idname='pt_semantic.v24_create_group_objects'
    bl_label='Criar grupos no Outliner'
    bl_description='Cria cópias temporárias texturizadas das faces de cada grupo, sem alterar a malha Stage'

    def execute(self,context):
        try:
            if PLAN is None:
                raise ValueError('V24_AGRUPAR_PRIMEIRO')
            v23._remove_collection(COLLECTION)
            col=v23._collection(COLLECTION)
            original=_source()
            n=0
            for g in PLAN['groups']:
                ob=v23._create_inspection_mesh(original,g['faces'],'PT_V24_ARVORE_'+g['id'])
                if ob is None:
                    continue
                col.objects.link(ob)
                ob['pt_v24_group_id']=g['id']
                ob['pt_v24_source_ids']=','.join(g['source_tree_ids'])
                n+=1
            _select_group(context)
            self.report({'INFO'},f'V24: {n} grupos no Outliner')
            print(f'PT_V24_SEPARATE=PASS objects={n} stage_source_unchanged=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V24: {exc}')
            print(f'PT_V24_SEPARATE=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V24AcceptLink(bpy.types.Operator):
    bl_idname='pt_semantic.v24_attach_suggested'
    bl_label='Associar à árvore sugerida'
    bl_description='Ação manual explícita para ligar uma copa solta ao tronco sugerido'

    def execute(self,context):
        try:
            g=_selected(context)
            if g is None:
                raise ValueError('V24_SELECIONAR_GRUPO')
            target=accept_manual_attachment(PLAN,orphan_id=g['id'],v23=_v23())
            _save()
            _refresh(context,focus_id=target)
            # An existing inspection collection shows OLD faces. Remove it
            # rather than falsely displaying a stale grouping.
            v23._remove_collection(COLLECTION)
            self.report({'INFO'},'Associação guardada; recria os objetos V24 no Outliner')
            print(f'PT_V24_ATTACH=PASS target={target} source_unchanged=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V24: {exc}')
            print(f'PT_V24_ATTACH=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V24Decide(bpy.types.Operator):
    bl_idname='pt_semantic.v24_review'
    bl_label='Avaliar grupo'
    decision: StringProperty(default='NEEDS_REVIEW')

    def execute(self,context):
        g=_selected(context)
        if g is None or self.decision not in {'PENDING','APPROVED','REJECTED','NEEDS_REVIEW'}:
            return {'CANCELLED'}
        g['review_status']=self.decision
        _save()
        _refresh(context,focus_id=g['id'])
        return {'FINISHED'}


class PT_OT_V24Preview(bpy.types.Operator):
    bl_idname='pt_semantic.v24_preview_glb'
    bl_label='Prévia GLB deste grupo'
    bl_description='Modelo GLB temporário colocado na base proposta; não esconde nem modifica o Stage'

    def execute(self,context):
        try:
            g=_selected(context)
            if g is None or g['review_status']=='REJECTED':
                raise ValueError('V24_SELECIONAR_GRUPO_NAO_REJEITADO')
            path=Path(bpy.path.abspath(context.scene.pt_v23_glb)).expanduser().resolve()
            v23._remove_collection(PREVIEW)
            # Do not leave behind a previous V23 mask or GLB library.
            v23._clear_preview()
            lib,ht=v23._import_glb_library(path)
            col=v23._collection(PREVIEW)
            o=bpy.data.objects.new('PT_V24_NOVA_ARVORE_'+g['id'],None)
            col.objects.link(o)
            o.instance_type='COLLECTION'
            o.instance_collection=lib
            o.location=g['anchor_view']
            factor=max(.5,float(g['height_view']))/ht*context.scene.pt_v23_size_factor
            o.scale=(factor,)*3
            o['pt_v24_preview_only']=True
            print(f'PT_V24_PREVIEW=PASS group={g["id"]} game_assets_modified=false',flush=True)
            self.report({'INFO'},'GLB visível na base proposta; geometria antiga intacta')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V24: {exc}')
            print(f'PT_V24_PREVIEW=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V24ClearPreview(bpy.types.Operator):
    bl_idname='pt_semantic.v24_clear_glb'
    bl_label='Remover GLB de teste'
    def execute(self,context):
        v23._remove_collection(PREVIEW)
        v23._remove_collection(v23.LIB_COLLECTION)
        return {'FINISHED'}


class PT_PT_V24Panel(bpy.types.Panel):
    bl_label='V24 · Juntar folhas por tronco'
    bl_idname='PT_PT_ETERVALE_V24_GROUPS'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='Etervale'
    bl_parent_id='PT_PT_ETERVALE_SEMANTIC_V21'

    def draw(self,context):
        lay=self.layout
        lay.label(text='Troncos como âncoras; folhas soltas em revisão')
        lay.operator('pt_semantic.v24_group',text='1. Agrupar propostas V23',icon='OUTLINER_OB_MESH')
        if PLAN is None:
            lay.label(text='Reconstruir V23 antes de agrupar')
            return
        c=PLAN['counts']
        lay.label(text=f"{c['source_proposals']} originais → {c['groups']} grupos")
        lay.label(text=f"Troncos: {c['with_trunk']} · folhas soltas: {c['foliage_only']}")
        lay.label(text=f"Auto: {c['auto_attached']} · sugest.: {c['review_suggestions']}")
        lay.operator('pt_semantic.v24_create_group_objects',text='2. Criar grupos no Outliner',icon='OUTLINER_COLLECTION')
        scene=context.scene
        lay.template_list('UI_UL_list','PT_V24_LIST',scene,'pt_v24_groups',scene,'pt_v24_active',rows=6)
        g=_selected(context)
        if g is not None:
            b=lay.box()
            b.label(text=f"{len(g['foliage_faces'])} folhas / {len(g['trunk_faces'])} tronco")
            b.label(text=f"Fontes V23: {len(g['source_tree_ids'])}")
            b.label(text=f"{g['completion'][:30]}")
            b.label(text=f"Estado: {g['review_status']}")
            if not g['trunk_faces'] and g['suggested_trunk_id']:
                b.label(text=f"Tronco próximo: {g['suggested_trunk_id'][:8]}")
                b.label(text=f"Distância proxy: {g['suggestion_distance']:.2f}")
                b.operator('pt_semantic.v24_attach_suggested',text='Associar à árvore sugerida')
            row=b.row(align=True)
            row.operator('pt_semantic.v24_review',text='Aprovar').decision='APPROVED'
            row.operator('pt_semantic.v24_review',text='Rever').decision='NEEDS_REVIEW'
            b.operator('pt_semantic.v24_review',text='Rejeitar').decision='REJECTED'
        lay.separator()
        lay.label(text='Opcional: usa o campo GLB da V23')
        lay.prop(scene,'pt_v23_glb',text='Modelo GLB')
        lay.operator('pt_semantic.v24_preview_glb',text='Prévia GLB grupo selecionado',icon='MESH_DATA')
        lay.operator('pt_semantic.v24_clear_glb',text='Retirar GLB de teste',icon='LOOP_BACK')
        lay.label(text='Nunca modifica o Stage nem exporta para o jogo')


CLASSES=(PT_V24GroupRow,PT_OT_V24Build,PT_OT_V24Separate,PT_OT_V24AcceptLink,
         PT_OT_V24Decide,PT_OT_V24Preview,PT_OT_V24ClearPreview,PT_PT_V24Panel)


def configure():
    global CONFIG, PLAN
    CONFIG={'v23_provider':lambda:v23.PLAN}
    PLAN=None
    path=_plan_path()
    if path.is_file():
        doc=json.loads(path.read_text(encoding='utf-8'))
        check_v24_groups(doc,v23=_v23())
        PLAN=doc
    if not hasattr(bpy.types.Scene,'pt_v24_groups'):
        bpy.types.Scene.pt_v24_groups=CollectionProperty(type=PT_V24GroupRow)
        bpy.types.Scene.pt_v24_active=IntProperty(default=0,min=0,update=_active_update)
    _refresh(bpy.context)
    print(f'PT_V24=READY groups={len(PLAN["groups"]) if PLAN else 0} '
          f'output={path} source_unchanged=true',flush=True)
