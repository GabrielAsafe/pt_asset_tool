"""V25 Blender UI: review foliage/stem links without altering any native Stage mesh.

V25 persists only decisions (separate JSON). Extracted meshes are disposable.
"""
import json
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty

from pt_asset_tool.stage072_semantic_core import atomic_write_json
from pt_asset_tool.stage072_tree_review_v25 import (
    approve_high_review, build_review, check_review, review_path,
    set_decision, virtual_groups,
)
from pt_asset_tool.blender import stage072_tree_group_v24 as v24
from pt_asset_tool.blender import stage072_tree_v23 as v23

PLAN = None
LOCK = False
PAIR_COLLECTION = 'PT_V25_PAR_COPA_TRONCO_SO_INSPECAO'
GROUP_COLLECTION = 'PT_V25_ARVORES_APROVADAS_SO_INSPECAO'
SOURCE_WAS_HIDDEN = None


def _hide_native_stage_sources():
    """Keep only the V19 floating-origin proxy visible in the V25 workbench.

    Stage072 preview .blend includes BOTH the untouched source mesh (game
    coordinates) and the normalised display proxy.  If the source is unhidden
    while reviewing a pair, Blender shows a second, distant map.  Resolve the
    source by the proxy's recorded provenance, never by a loose name prefix.
    Only session visibility/selection flags change, never mesh geometry.
    """
    source_names = {
        proxy.get('pt_stage072_source_object')
        for proxy in bpy.data.objects
        if proxy.type == 'MESH'
        and proxy.get('pt_stage072_view_proxy')
        and proxy.get('pt_stage072_view_only')
        and proxy.get('pt_stage072_source_object')
    }
    hidden = 0
    for name in sorted(source_names):
        source = bpy.data.objects.get(name)
        if (source is None or source.type != 'MESH'
                or not source.get('pt_stage072_source_sha256')
                or source.get('pt_stage072_view_proxy')):
            # Never hide an arbitrary user object simply because of its name.
            print(f'PT_V25_NATIVE_SOURCE=SKIP_UNVERIFIED name={name}', flush=True)
            continue
        if not source.hide_get():
            hidden += 1
        source.select_set(False)
        source.hide_set(True)
        source.hide_render = True
    return hidden


def _v24():
    if v24.PLAN is None:
        raise ValueError('V25_PRECISA_PLANO_V24')
    return v24.PLAN


def _path():
    return review_path(v24._plan_path())


def _save():
    check_review(PLAN, v24=_v24())
    atomic_write_json(_path(), PLAN)


def _selected(context):
    if PLAN is None:
        return None
    ix = context.scene.pt_v25_active
    return PLAN['matches'][ix] if 0 <= ix < len(PLAN['matches']) else None


def _refresh(context, preferred_id=None):
    global LOCK
    LOCK = True
    try:
        scene = context.scene
        old = scene.pt_v25_active
        scene.pt_v25_matches.clear()
        matches = PLAN['matches'] if PLAN else []
        for m in matches:
            it=scene.pt_v25_matches.add()
            it.match_id=m['id']
            mark = '*' if m['tier']=='HIGH_REVIEW' else '?'
            done = {'APPROVED':'OK','REJECTED':'X','NEEDS_REVIEW':'R','PENDING':'·'}[m['decision']]
            it.name=f"{mark}{done} {m['score']:02d} · copa {m['orphan_face_count']} faces → tronco {m['target_id'][:7]}"
        if preferred_id:
            scene.pt_v25_active=next((i for i,m in enumerate(matches) if m['id']==preferred_id),0)
        else:
            scene.pt_v25_active=min(old,max(0,len(matches)-1))
    finally:
        LOCK=False


def _restore_stage():
    global SOURCE_WAS_HIDDEN
    if SOURCE_WAS_HIDDEN is not None:
        try:
            original=v23._source()
            original.hide_set(SOURCE_WAS_HIDDEN)
        finally:
            SOURCE_WAS_HIDDEN=None


def _clear_pair():
    try:
        _restore_stage()
    finally:
        v23._remove_collection(PAIR_COLLECTION)
        # Restoring the *visual proxy* must never reveal the native source.
        _hide_native_stage_sources()


def _hide_older_inspection():
    for name in (v23.ISOLATE_COLLECTION, v24.COLLECTION, GROUP_COLLECTION):
        col=bpy.data.collections.get(name)
        if col:
            for ob in col.objects:
                ob.hide_set(True)
                ob.select_set(False)


def _focus_pair(context):
    m=_selected(context)
    if m is None:
        raise ValueError('V25_SELECIONAR_ASSOCIACAO')
    groups={g['id']:g for g in _v24()['groups']}
    orphan,stem=groups.get(m['orphan_id']),groups.get(m['target_id'])
    if orphan is None or stem is None:
        raise ValueError('V25_PAR_DESATUALIZADO')
    _clear_pair()
    _hide_older_inspection()
    original=v23._source()
    col=v23._collection(PAIR_COLLECTION)
    for group,kind in ((stem,'TRONCO'),(orphan,'COPA')):
        ob=v23._create_inspection_mesh(original,group['faces'],
                                        f'PT_V25_{kind}_{group["id"]}')
        if ob is None:
            raise ValueError('V25_PARCELAS_SEM_GEOMETRIA')
        col.objects.link(ob)
        ob['pt_v25_part']=kind
        ob['pt_v25_source_id']=group['id']
        ob.show_wire=True
        ob.show_all_edges=True
        ob.select_set(True)
        if kind=='TRONCO':
            context.view_layer.objects.active=ob
    # Isolation is temporary and reversible. Scene is V21 preview, not real SMD.
    global SOURCE_WAS_HIDDEN
    SOURCE_WAS_HIDDEN = original.hide_get()
    original.hide_set(True)
    _hide_native_stage_sources()
    return m


def _clear_inspection_copies():
    """Delete only generated inspection meshes, never source/proxy/JSON/GLB.

    V23/V24/V25 may each have a small set of disposable mesh objects in the
    Blender workbench; removing those collections frees memory.  This is an
    explicit action and does not publish or delete native Stage data.
    """
    _clear_pair()
    removed = 0
    for collection_name in (GROUP_COLLECTION, v24.COLLECTION, v23.ISOLATE_COLLECTION):
        col = bpy.data.collections.get(collection_name)
        if col is None:
            continue
        removed += len(col.objects)
        v23._remove_collection(collection_name)
    _hide_native_stage_sources()
    return removed


class PT_V25MatchRow(bpy.types.PropertyGroup):
    match_id: StringProperty()


class PT_OT_V25HideNative(bpy.types.Operator):
    bl_idname='pt_semantic.v25_hide_native_stage'
    bl_label='Ocultar Stage original duplicado'
    bl_description='Oculta somente o Stage em coordenadas do jogo; mantém o proxy e os JSON intactos'

    def execute(self, context):
        hidden = _hide_native_stage_sources()
        print(f'PT_V25_NATIVE_SOURCE=HIDDEN changed={hidden} source_mesh_unchanged=true',
              flush=True)
        self.report({'INFO'}, 'Stage original oculto; usa o proxy V19 para rever árvores')
        return {'FINISHED'}


class PT_OT_V25ClearInspection(bpy.types.Operator):
    bl_idname='pt_semantic.v25_clear_inspection'
    bl_label='Limpar malhas temporárias de inspeção'
    bl_description='Liberta objetos V23/V24/V25 criados para inspeção; mantém mapas, GLB, decisões JSON e Stage original intactos'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            removed = _clear_inspection_copies()
            print(f'PT_V25_CLEANUP=PASS objects_removed={removed} '
                  'source_mesh_unchanged=true json_preserved=true', flush=True)
            self.report({'INFO'}, f'{removed} objetos temporários removidos; decisões preservadas')
            return {'FINISHED'}
        except Exception as exc:
            print(f'PT_V25_CLEANUP=FAIL {type(exc).__name__}:{exc}', flush=True)
            self.report({'ERROR'}, f'V25: {exc}')
            return {'CANCELLED'}


class PT_OT_V25Build(bpy.types.Operator):
    bl_idname='pt_semantic.v25_analyze'
    bl_label='Analisar sugestões V24'
    bl_description='Usa V24 já guardada; nunca sobrescreve decisões V25 existentes'

    def execute(self, context):
        global PLAN
        try:
            if PLAN is not None:
                check_review(PLAN,v24=_v24())
                _refresh(context)
                self.report({'INFO'},'V25 existente reutilizada; decisões preservadas')
                print(f'PT_V25_BUILD=REUSED matches={len(PLAN["matches"])}',flush=True)
                return {'FINISHED'}
            if _path().exists():
                raise ValueError('V25_JSON_EXISTE_MAS_NAO_E_COMPATIVEL_NAO_SUBSTITUIR')
            PLAN=build_review(v24=_v24())
            _save()
            _refresh(context)
            high=sum(m['tier']=='HIGH_REVIEW' for m in PLAN['matches'])
            print(f'PT_V25_BUILD=PASS matches={len(PLAN["matches"])} high_review={high} '
                  f'path={_path()} original_unchanged=true',flush=True)
            self.report({'INFO'},f'V25: {len(PLAN["matches"])} sugestões, {high} prioritárias')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V25: {type(exc).__name__}: {exc}')
            print(f'PT_V25_BUILD=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V25Inspect(bpy.types.Operator):
    bl_idname='pt_semantic.v25_inspect_pair'
    bl_label='Inspecionar copa + tronco'
    bl_description='Isola duas cópias no Blender; o Stage original só fica oculto temporariamente'

    def execute(self, context):
        try:
            m=_focus_pair(context)
            print(f'PT_V25_INSPECT=PASS orphan={m["id"]} target={m["target_id"]} '
                  'source_unchanged=true',flush=True)
            self.report({'INFO'},'Par isolado; seleciona e usa Numpad . para aproximar')
            return {'FINISHED'}
        except Exception as exc:
            _clear_pair()
            self.report({'ERROR'},f'V25: {exc}')
            print(f'PT_V25_INSPECT=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_OT_V25Restore(bpy.types.Operator):
    bl_idname='pt_semantic.v25_restore_stage'
    bl_label='Restaurar mapa'
    bl_description='Repõe a visibilidade original do Stage e remove só as duas cópias temporárias'

    def execute(self,context):
        _clear_pair()
        return {'FINISHED'}


class PT_OT_V25Decide(bpy.types.Operator):
    bl_idname='pt_semantic.v25_decide'
    bl_label='Avaliar associação'
    decision: StringProperty(default='NEEDS_REVIEW')

    def execute(self, context):
        try:
            m=_selected(context)
            if m is None:
                raise ValueError('V25_SELECIONAR_ASSOCIACAO')
            set_decision(PLAN,v24=_v24(),orphan_id=m['id'],decision=self.decision)
            _save()
            _refresh(context,preferred_id=m['id'])
            print(f'PT_V25_DECISION=PASS orphan={m["id"]} decision={self.decision} '
                  f'path={_path()} original_unchanged=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V25: {exc}')
            return {'CANCELLED'}


class PT_OT_V25BatchHigh(bpy.types.Operator):
    bl_idname='pt_semantic.v25_batch_high_review'
    bl_label='Aprovar sugestões prioritárias'
    bl_description='Aprova explicitamente as sugestões HIGH_REVIEW pendentes; não publica no jogo'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self,event)

    def execute(self,context):
        try:
            if PLAN is None:
                raise ValueError('V25_ANALISAR_PRIMEIRO')
            count=approve_high_review(PLAN,v24=_v24())
            _save()
            _refresh(context)
            self.report({'INFO'},f'{count} associações aprovadas só para inspeção; não publica')
            print(f'PT_V25_BATCH=PASS approved_new={count} '
                  'not_game_runtime_certified=true',flush=True)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V25: {exc}')
            return {'CANCELLED'}


class PT_OT_V25CreateObjects(bpy.types.Operator):
    bl_idname='pt_semantic.v25_inspection_objects'
    bl_label='Criar grupos V25 no Outliner'
    bl_description='Cria malhas temporárias após as decisões V25, sem editar faces originais'

    def execute(self, context):
        try:
            if PLAN is None:
                raise ValueError('V25_ANALISAR_PRIMEIRO')
            groups=virtual_groups(PLAN,v24=_v24())
            _clear_pair()
            v23._remove_collection(GROUP_COLLECTION)
            _hide_older_inspection()
            col=v23._collection(GROUP_COLLECTION)
            original=v23._source()
            total=0
            for group in groups:
                ob=v23._create_inspection_mesh(original,group['faces'],
                                               'PT_V25_ARVORE_'+group['id'])
                if ob is None:
                    raise ValueError(f'V25_GROUP_EMPTY:{group["id"]}')
                col.objects.link(ob)
                ob['pt_v25_group_id']=group['id']
                ob['pt_v25_source_ids']=','.join(group['source_tree_ids'])
                total+=1
            # Default: do not render all duplicated meshes on top of original stage.
            for ob in col.objects:
                ob.hide_set(True)
            _hide_native_stage_sources()
            approved=sum(m['decision']=='APPROVED' for m in PLAN['matches'])
            print(f'PT_V25_SEPARATE=PASS objects={total} approved_links={approved} '
                  'face_coverage_preserved=true source_mesh_unchanged=true',flush=True)
            self.report({'INFO'},f'{total} objetos V25 criados e ocultos; seleciona no Outliner para mostrar')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},f'V25: {type(exc).__name__}: {exc}')
            print(f'PT_V25_SEPARATE=FAIL {type(exc).__name__}:{exc}',flush=True)
            return {'CANCELLED'}


class PT_PT_V25Panel(bpy.types.Panel):
    bl_label='V25 · Rever associações copa/tronco'
    bl_idname='PT_PT_ETERVALE_V25_TREES'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='Etervale'
    bl_parent_id='PT_PT_ETERVALE_SEMANTIC_V21'

    def draw(self, context):
        lay=self.layout
        lay.label(text='Só prévia Blender · sem publicar SMD')
        lay.operator('pt_semantic.v25_hide_native_stage',
                     text='Ocultar Stage original duplicado', icon='HIDE_ON')
        lay.operator('pt_semantic.v25_clear_inspection',
                     text='Limpar cópias temporárias', icon='TRASH')
        lay.operator('pt_semantic.v25_analyze',text='1. Analisar sugestões V24',icon='VIEWZOOM')
        if PLAN is None:
            lay.label(text='Primeiro agrupar/reabrir V24')
            return
        matches=PLAN['matches']
        high=sum(m['tier']=='HIGH_REVIEW' for m in matches)
        approved=sum(m['decision']=='APPROVED' for m in matches)
        lay.label(text=f'{len(matches)} associações · {high} prioritárias')
        lay.label(text=f'{approved} aprovadas para a cópia')
        scene=context.scene
        lay.template_list('UI_UL_list','PT_V25_LINKS',scene,'pt_v25_matches',scene,'pt_v25_active',rows=6)
        m=_selected(context)
        if m:
            b=lay.box()
            b.label(text=f'Pontuação heurística: {m["score"]}/100')
            b.label(text=f'{m["tier"]} · {m["decision"]}')
            b.label(text=f'Distância: {m["distance_view"]:.2f} no proxy')
            b.label(text=f'Faces soltas: {m["orphan_face_count"]}')
            for flag in m['flags'][:3]:
                b.label(text=flag[:38],icon='ERROR')
            b.operator('pt_semantic.v25_inspect_pair',text='2. Isolar par (copa + tronco)',icon='RESTRICT_VIEW_OFF')
            row=b.row(align=True)
            row.operator('pt_semantic.v25_decide',text='Aprovar ligação').decision='APPROVED'
            row.operator('pt_semantic.v25_decide',text='Rejeitar').decision='REJECTED'
            b.operator('pt_semantic.v25_decide',text='Deixar para revisão').decision='NEEDS_REVIEW'
        lay.operator('pt_semantic.v25_restore_stage',text='Restaurar mapa e remover par',icon='LOOP_BACK')
        lay.separator()
        lay.operator('pt_semantic.v25_batch_high_review',
                     text=f'Aprovar {high} prioritárias (confirmar)',icon='CHECKMARK')
        lay.operator('pt_semantic.v25_inspection_objects',
                     text='3. Criar grupos V25 no Outliner',icon='OUTLINER_COLLECTION')
        lay.label(text='Aprovação não certifica a árvore toda')
        lay.label(text='Tronco/terreno: base estimada, não colisão')


CLASSES=(PT_V25MatchRow,PT_OT_V25HideNative,PT_OT_V25ClearInspection,PT_OT_V25Build,
         PT_OT_V25Inspect,PT_OT_V25Restore,
         PT_OT_V25Decide,PT_OT_V25BatchHigh,PT_OT_V25CreateObjects,PT_PT_V25Panel)


def configure():
    global PLAN
    PLAN=None
    repaired = _hide_native_stage_sources()
    if repaired:
        print(f'PT_V25_NATIVE_SOURCE=HIDDEN_ON_START changed={repaired}', flush=True)
    path=_path()
    if path.is_file():
        raw=json.loads(path.read_text(encoding='utf-8'))
        try:
            check_review(raw,v24=_v24())
            PLAN=raw
        except (ValueError,KeyError,TypeError) as exc:
            print(f'PT_V25=STALE_PRESERVED path={path} error={exc}',flush=True)
    if not hasattr(bpy.types.Scene,'pt_v25_matches'):
        bpy.types.Scene.pt_v25_matches=CollectionProperty(type=PT_V25MatchRow)
        bpy.types.Scene.pt_v25_active=IntProperty(default=0,min=0)
    _refresh(bpy.context)
    print(f'PT_V25=READY matches={len(PLAN["matches"]) if PLAN else 0} '
          f'path={path} source_unchanged=true',flush=True)
