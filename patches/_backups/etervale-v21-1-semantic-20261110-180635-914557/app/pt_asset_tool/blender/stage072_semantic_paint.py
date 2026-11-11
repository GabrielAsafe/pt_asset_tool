"""V21 Blender 5.x Stage072 semantic paint pilot — manual semantic brush.

Launched on a DISPOSABLE .blend, using the V19 proxy. Writes only a separate,
source-SHA locked JSON. It never writes original SMD, meshes or game assets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.kdtree import KDTree

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from pt_asset_tool.stage072_semantic_core import (  # noqa E402
    FORMAT, VERSION, CATEGORIES, COLORS, source_to_view,
    suggest_material, source_anchor_from_view_vertices, replace_overlapping_faces,
    check_document, atomic_write_json,
)
from pt_asset_tool.blender import open_stage072_preview as view_module  # noqa E402

OPTIONS = None
DOCUMENT = None
INDICES = {}
IS_LOADING = False
MARKER_COLLECTION = 'PT_STAGE072_SEMANTIC_MARKERS_V21'
CATEGORY_ITEMS = [
    ('ARVORE','Árvore','Folhas, tronco ou conjunto de copa'),
    ('ARBUSTO','Arbusto','Vegetação baixa, relva e arbustos'),
    ('FOGO','Fogo','Chamas, tochas e braseiros'),
    ('PEDRA','Pedra','Pedras, rochas e blocos'),
    ('SOLO','Solo','Superfícies do terreno'),
    ('PAREDE','Parede','Superfície arquitetónica visível'),
    ('EDIFICIO','Edifício','Construção ou parte dela'),
    ('AGUA','Água','Superfície de água'),
    ('OUTRO','Outro','Outro elemento'),
    ('POSSIVEL_COLISAO','Possível colisão','Suspeita: não é prova de colisão'),
    ('APAGAR','Apagar','Apaga rótulos das faces tocadas'),
]


def _proxies():
    return [o for o in bpy.data.objects
            if o.type == 'MESH' and o.get('pt_stage072_view_proxy')
            and o.get('pt_stage072_view_only') and o.name.startswith('PT_STAGE072_VIEW_STAGE')]


def _opts():
    if OPTIONS is None or DOCUMENT is None:
        raise RuntimeError('SEMANTIC_SESSION_NOT_INITIALIZED')
    return OPTIONS


def _get_region(region_id):
    for r in DOCUMENT['regions']:
        if r['id'] == region_id:
            return r
    return None


def _save():
    opts = _opts()
    DOCUMENT['saved_utc'] = datetime.now(timezone.utc).isoformat()
    check_document(DOCUMENT, asset=opts.asset, source_sha256=opts.source_sha256,
                   vertex_count=DOCUMENT['source_vertex_count'], face_count=DOCUMENT['source_face_count'])
    atomic_write_json(opts.output, DOCUMENT)


def _marker_collection():
    col = bpy.data.collections.get(MARKER_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(MARKER_COLLECTION)
        bpy.context.scene.collection.children.link(col)
    return col


def _view_anchor(region):
    a = region['anchor']['game_anchor']
    off = region.get('offset_game', [0., 0., 0.])
    center = bpy.context.scene.get('pt_stage072_source_bounds_center')
    scale = float(bpy.context.scene.get('pt_stage072_view_scale', 0.))
    return source_to_view(tuple(float(a[i])+float(off[i]) for i in range(3)), center, scale)


def _render_markers():
    col = _marker_collection()
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for index, region in enumerate(DOCUMENT.get('regions', []), 1):
        cat = region['category']
        obj = bpy.data.objects.new(f'PT_CLASS_{cat}_{index:03d}_{region["id"]}', None)
        col.objects.link(obj)
        obj.empty_display_type = 'SPHERE'
        obj.empty_display_size = 0.6
        obj.location = _view_anchor(region)
        r, g, b = COLORS.get(cat, COLORS['OUTRO'])
        obj.color = (r, g, b, 1)
        obj.show_in_front = True
        obj.hide_render = True
        obj['semantic_region_id'] = region['id']
        obj['semantic_category'] = cat


def _on_edit(self, context):
    if IS_LOADING or DOCUMENT is None:
        return
    region = _get_region(self.region_id)
    if region is None:
        return
    region['category'] = self.category
    region['note'] = self.note[:1000]
    region['replacement_asset'] = self.replacement_asset[:1024]
    region['asset_scale'] = float(self.asset_scale)
    region['yaw_degrees'] = float(self.yaw_degrees)
    region['offset_game'] = [float(v) for v in self.offset_game]
    _save()
    _render_markers()


class PT_SemanticRegion(bpy.types.PropertyGroup):
    region_id: StringProperty()
    category: EnumProperty(items=CATEGORY_ITEMS[:-1], update=_on_edit)
    face_count: IntProperty(default=0)
    note: StringProperty(name='Nota', default='', update=_on_edit)
    replacement_asset: StringProperty(name='Asset 3D futuro', default='', update=_on_edit,
                                      description='Caminho anotado; não importa nem publica assets nesta versão')
    offset_game: FloatVectorProperty(name='Ajuste XYZ (jogo)', size=3, subtype='TRANSLATION',
                                     default=(0., 0., 0.), update=_on_edit)
    yaw_degrees: FloatProperty(name='Rotação Y (graus)', default=0.0, min=-360.0, max=360.0, update=_on_edit)
    asset_scale: FloatProperty(name='Escala proposta', default=1.0, min=0.01, max=100., update=_on_edit)


def _refresh_ui(scene):
    global IS_LOADING
    IS_LOADING = True
    try:
        scene.pt_semantic_regions.clear()
        for region in DOCUMENT.get('regions', []):
            item = scene.pt_semantic_regions.add()
            item.name = f"{region['category']} · {len(region['faces'])} faces"
            item.region_id = region['id']
            item.category = region['category']
            item.face_count = len(region['faces'])
            item.note = region.get('note', '')
            item.replacement_asset = region.get('replacement_asset', '')
            item.offset_game = region.get('offset_game', [0., 0., 0.])
            item.yaw_degrees = region.get('yaw_degrees', 0.)
            item.asset_scale = region.get('asset_scale', 1.)
        if len(scene.pt_semantic_regions) > 0:
            scene.pt_semantic_active = min(scene.pt_semantic_active, len(scene.pt_semantic_regions)-1)
        else:
            scene.pt_semantic_active = 0
    finally:
        IS_LOADING = False
    _render_markers()


class _Spatial:
    def __init__(self, obj):
        me = obj.data
        self.obj_name = obj.name
        self.me = me
        kd = KDTree(len(me.polygons))
        for p in me.polygons:
            kd.insert(p.center, p.index)
        kd.balance()
        self.kd = kd
        self.neighbors = None

    def _make_neighbors(self):
        edge_faces = defaultdict(list)
        for p in self.me.polygons:
            for key in p.edge_keys:
                edge_faces[tuple(sorted(key))].append(p.index)
        neighbors = defaultdict(set)
        for faces in edge_faces.values():
            for idx in faces:
                neighbors[idx].update(f for f in faces if f != idx)
        self.neighbors = neighbors

    def select_faces(self, hit_idx, hit_pos, mode, radius, limit=10000):
        mat = self.me.polygons[hit_idx].material_index
        if mode == 'FACE':
            return [hit_idx]
        if mode == 'RAIO':
            faces = [idx for (_co, idx, dist) in self.kd.find_range(hit_pos, radius)
                     if self.me.polygons[idx].material_index == mat]
            faces.append(hit_idx)
            selected = sorted(set(faces))
            if len(selected) > limit:
                raise ValueError(f'RAIO_MUITO_GRANDE:{len(selected)}_FACES')
            return selected
        if mode == 'ILHA':
            if self.neighbors is None:
                self._make_neighbors()
            seen = {hit_idx}
            stack = [hit_idx]
            while stack:
                idx = stack.pop()
                for n in self.neighbors.get(idx, ()):
                    if n not in seen and self.me.polygons[n].material_index == mat:
                        seen.add(n)
                        stack.append(n)
                        if len(seen) > limit:
                            raise ValueError('ILHA_MUITO_GRANDE:usa_RAIO_ou_FACE')
            return sorted(seen)
        raise ValueError(f'MODO_NAO_SUPORTADO:{mode}')


def _spatial(obj):
    s = INDICES.get(obj.name)
    if s is None or s.me != obj.data:
        s = _Spatial(obj)
        INDICES[obj.name] = s
    return s


def _get_view_ray(context, event):
    # The operator is invoked from the N-panel (UI region). Resolve the
    # separate WINDOW region explicitly; event.mouse_region_* otherwise refers
    # to the panel, breaking picking even though the 3D view is visible.
    area = context.area
    if area is None or area.type != 'VIEW_3D':
        return None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return None
    mx, my = event.mouse_x - region.x, event.mouse_y - region.y
    if mx < 0 or my < 0 or mx >= region.width or my >= region.height:
        return None
    coord = (mx, my)
    r3d = area.spaces.active.region_3d
    origin = view3d_utils.region_2d_to_origin_3d(region, r3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, r3d, coord)
    return origin, direction


def _hit_proxy(context, event):
    ray = _get_view_ray(context, event)
    if ray is None:
        return None
    origin, direction = ray
    best = None
    for obj in _proxies():
        inv = obj.matrix_world.inverted_safe()
        local_origin = inv @ origin
        local_direction = (inv.to_3x3() @ direction).normalized()
        hit, loc, normal, poly_idx = obj.ray_cast(local_origin, local_direction)
        if not hit or poly_idx < 0:
            continue
        world_loc = obj.matrix_world @ loc
        dist = (world_loc-origin).length
        if best is None or dist < best[0]:
            best = (dist, obj, poly_idx, loc)
    return best


def _anchor_for(obj, face_indices):
    me = obj.data
    vert_ids = set()
    for i in face_indices:
        vert_ids.update(me.polygons[i].vertices)
    coords = [obj.matrix_world @ me.vertices[i].co for i in vert_ids]
    scene = bpy.context.scene
    center = tuple(scene['pt_stage072_source_bounds_center'])
    scale = float(scene['pt_stage072_view_scale'])
    return source_anchor_from_view_vertices(coords, center, scale)


def _commit_stroke(obj_name, face_ids, category):
    if not face_ids:
        return
    obj = bpy.data.objects[obj_name]
    material_names = []
    for idx in face_ids:
        slot = obj.data.polygons[idx].material_index
        mat = obj.material_slots[slot].material if slot < len(obj.material_slots) else None
        if mat:
            material_names.append(mat.name)
    anchor = _anchor_for(obj, face_ids)
    new_regions = replace_overlapping_faces(
        DOCUMENT['regions'], obj_name=obj_name, chosen_faces=sorted(face_ids),
        category=category, region_id=uuid4().hex[:12], anchor=anchor,
        material_names=material_names)
    DOCUMENT['regions'] = new_regions
    _save()
    _refresh_ui(bpy.context.scene)
    print(f'PT_SEMANTIC_BRUSH=PASS category={category} faces={len(face_ids)} '
          f'regions={len(new_regions)} output={OPTIONS.output}', flush=True)


class PT_OT_SemanticBrush(bpy.types.Operator):
    bl_idname = 'pt_semantic.brush'
    bl_label = 'Ativar pincel semântico'
    bl_description = 'Clique/arraste nas faces; Esc ou botão direito termina o pincel'

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and bool(_proxies())

    def invoke(self, context, event):
        self.strokes = defaultdict(set)
        self.pressed = False
        self.last_mouse = None
        self.last_index = None
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, 'Pincel ativo: clique/arraste, Esc termina; registo automático em JSON')
        return {'RUNNING_MODAL'}

    def _sample(self, context, event):
        hit = _hit_proxy(context, event)
        if hit is None:
            return
        _dist, obj, idx, loc = hit
        if self.last_index == (obj.name, idx):
            return
        self.last_index = (obj.name, idx)
        scene = context.scene
        try:
            ids = _spatial(obj).select_faces(idx, loc, scene.pt_semantic_pick_mode,
                                             scene.pt_semantic_brush_radius)
            total = len(ids) + len(self.strokes[obj.name])
            if total > 15000:
                raise ValueError('PINCEL_MAX_15000_FACES_POR_TRAÇO')
            self.strokes[obj.name].update(ids)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))

    def _commit(self, context):
        cat = context.scene.pt_semantic_category
        for obj_name, faces in self.strokes.items():
            _commit_stroke(obj_name, faces, cat)
        self.strokes.clear()
        self.last_index = None

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._commit(context)
            self.report({'INFO'}, 'Pincel desativado; classificações gravadas')
            return {'FINISHED'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                # UI clicks on the sidebar are outside the VIEW_3D WINDOW region.
                if _get_view_ray(context, event) is None:
                    return {'PASS_THROUGH'}
                self.pressed = True
                self.strokes.clear()
                self.last_index = None
                self._sample(context, event)
                self.last_mouse = (event.mouse_x, event.mouse_y)
                return {'RUNNING_MODAL'}
            if event.value == 'RELEASE' and self.pressed:
                self.pressed = False
                self._commit(context)
                return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self.pressed:
            curr = (event.mouse_x, event.mouse_y)
            if self.last_mouse is None or math.dist(curr, self.last_mouse) >= 9:
                self.last_mouse = curr
                self._sample(context, event)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


class PT_OT_DeleteRegion(bpy.types.Operator):
    bl_idname = 'pt_semantic.delete_region'
    bl_label = 'Apagar classificação selecionada'

    def execute(self, context):
        i = context.scene.pt_semantic_active
        entries = context.scene.pt_semantic_regions
        if i < 0 or i >= len(entries):
            return {'CANCELLED'}
        rid = entries[i].region_id
        DOCUMENT['regions'] = [r for r in DOCUMENT['regions'] if r['id'] != rid]
        _save()
        _refresh_ui(context.scene)
        return {'FINISHED'}


class PT_OT_AnalyzeMaterials(bpy.types.Operator):
    bl_idname = 'pt_semantic.analyze_materials'
    bl_label = 'Pré-analisar materiais'
    bl_description = 'Exporta sugestões por nome sem classificar automaticamente faces'

    def execute(self, context):
        candidates = []
        for obj in _proxies():
            counts = Counter(p.material_index for p in obj.data.polygons)
            for i, count in sorted(counts.items()):
                mat = obj.material_slots[i].material if i < len(obj.material_slots) else None
                name = mat.name if mat else f'UNASSIGNED_{i}'
                candidates.append({'proxy_object': obj.name, 'material_index': i,
                                   'material_name': name, 'face_count': count,
                                   **suggest_material(name)})
        doc = {'format': 'PT_ETERVALE_STAGE072_MATERIAL_SUGGESTIONS_V21',
               'asset': OPTIONS.asset, 'source_sha256': OPTIONS.source_sha256,
               'note': 'NAME_BASED_HINTS_NOT_AUTO_CLASSIFICATION_OR_COLLISION_PROOF',
               'candidates': candidates}
        dest = OPTIONS.output.with_suffix('.materials.json')
        atomic_write_json(dest, doc)
        self.report({'INFO'}, f'{len(candidates)} materiais analisados; ficheiro: {dest}')
        print(f'PT_SEMANTIC_MATERIAL_HINTS={dest} materials={len(candidates)}', flush=True)
        return {'FINISHED'}


class PT_OT_SaveSemantic(bpy.types.Operator):
    bl_idname = 'pt_semantic.save'
    bl_label = 'Guardar marcações'

    def execute(self, context):
        _save()
        self.report({'INFO'}, f'JSON guardado: {OPTIONS.output}')
        return {'FINISHED'}


class PT_PT_SemanticPanel(bpy.types.Panel):
    bl_label = 'Etervale · Classificação V21'
    bl_idname = 'PT_PT_ETERVALE_SEMANTIC_V21'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Etervale'

    def draw(self, context):
        lay = self.layout
        scene = context.scene
        lay.label(text='Pincel semântico · NÃO publica no jogo')
        lay.prop(scene, 'pt_semantic_category', text='Categoria')
        lay.prop(scene, 'pt_semantic_pick_mode', text='Seleção')
        if scene.pt_semantic_pick_mode == 'RAIO':
            lay.prop(scene, 'pt_semantic_brush_radius', text='Raio no proxy')
        lay.operator('pt_semantic.brush', text='Ativar pincel · Esc termina', icon='BRUSH_DATA')
        row = lay.row(align=True)
        row.operator('pt_semantic.analyze_materials', text='Sugestões materiais', icon='VIEWZOOM')
        row.operator('pt_semantic.save', text='Guardar', icon='FILE_TICK')
        lay.separator()
        lay.label(text=f'Marcações: {len(scene.pt_semantic_regions)}')
        lay.template_list('UI_UL_list', 'PT_SEMANTIC', scene, 'pt_semantic_regions',
                          scene, 'pt_semantic_active', rows=5)
        if scene.pt_semantic_regions and 0 <= scene.pt_semantic_active < len(scene.pt_semantic_regions):
            item = scene.pt_semantic_regions[scene.pt_semantic_active]
            box = lay.box()
            box.label(text=f'{item.face_count} faces · proposta')
            box.prop(item, 'category', text='Categoria da região')
            box.prop(item, 'note')
            box.prop(item, 'replacement_asset')
            box.prop(item, 'offset_game')
            box.prop(item, 'yaw_degrees')
            box.prop(item, 'asset_scale')
            box.operator('pt_semantic.delete_region', text='Apagar região', icon='TRASH')
        lay.separator()
        lay.label(text='Posição = limite inferior da seleção')
        lay.label(text='Ajustar âncora manualmente')
        lay.label(text='WALL não prova colisão')


CLASSES = (PT_SemanticRegion, PT_OT_SemanticBrush, PT_OT_DeleteRegion,
           PT_OT_AnalyzeMaterials, PT_OT_SaveSemantic, PT_PT_SemanticPanel)


def _initialize():
    global DOCUMENT
    try:
        if not bpy.context.scene.get('pt_stage072_view_scale'):
            view_module.configure_stage072_view()
        proxies = _proxies()
        if not proxies:
            raise RuntimeError('V19_STAGE072_VIEW_PROXY_MISSING')
        face_count = sum(len(p.data.polygons) for p in proxies)
        vertex_count = sum(len(p.data.vertices) for p in proxies)
    except RuntimeError as e:
        print(f'PT_SEMANTIC=FAIL reason={e}', flush=True)
        return None
    try:
        proxies = _proxies()
        face_count = sum(len(p.data.polygons) for p in proxies)
        vertex_count = sum(len(p.data.vertices) for p in proxies)
        if OPTIONS.output.exists():
            doc = json.loads(OPTIONS.output.read_text(encoding='utf-8'))
            check_document(doc, asset=OPTIONS.asset, source_sha256=OPTIONS.source_sha256,
                           vertex_count=vertex_count, face_count=face_count)
        else:
            doc = {'format': FORMAT, 'version': VERSION, 'asset': OPTIONS.asset,
                   'source_sha256': OPTIONS.source_sha256,
                   'source_face_count': face_count, 'source_vertex_count': vertex_count,
                   'source_mapping': 'V19_PROXY_TO_ORIGINAL_FACE_INDEX_SOURCE_SHA_LOCKED',
                   'coordinate_basis': 'GAME_Y_UP_LEFT_HANDED',
                   'not_game_runtime_certified': True, 'publish_enabled': False,
                   'regions': []}
        DOCUMENT = doc
        for cls in CLASSES:
            if not hasattr(bpy.types, cls.__name__):
                bpy.utils.register_class(cls)
        scene = bpy.context.scene
        if not hasattr(bpy.types.Scene, 'pt_semantic_category'):
            bpy.types.Scene.pt_semantic_category = EnumProperty(name='Categoria', items=CATEGORY_ITEMS, default='ARVORE')
            bpy.types.Scene.pt_semantic_pick_mode = EnumProperty(
                name='Modo de seleção', items=[('FACE','Face','Uma face'),
                                              ('ILHA','Ilha do material','Faces ligadas do mesmo material'),
                                              ('RAIO','Raio + material','Faces próximas com o mesmo material')], default='RAIO')
            bpy.types.Scene.pt_semantic_brush_radius = FloatProperty(
                name='Raio', min=.05, max=20., default=1.8, description='Unidades do proxy normalizado, não unidades do jogo')
            bpy.types.Scene.pt_semantic_regions = CollectionProperty(type=PT_SemanticRegion)
            bpy.types.Scene.pt_semantic_active = IntProperty(default=0, min=0)
        _refresh_ui(scene)
        _save()  # Initialize an empty, source-locked document for this map.
        print(f'PT_SEMANTIC=READY asset={OPTIONS.asset} faces={face_count} '
              f'regions={len(DOCUMENT["regions"])} output={OPTIONS.output} '
              'brush=N_PANEL_ETERVALE', flush=True)
    except Exception as exc:
        print(f'PT_SEMANTIC=FAIL reason={type(exc).__name__}:{exc}', flush=True)
        raise
    return None


def _arguments():
    args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', required=True)
    ap.add_argument('--source-sha256', required=True)
    ap.add_argument('--output', type=Path, required=True)
    opts = ap.parse_args(args)
    if not opts.output.parent.is_dir():
        raise ValueError('OUTPUT_PARENT_NOT_CREATED_BY_LAUNCHER')
    return opts


if __name__ == '__main__':
    OPTIONS = _arguments()
    bpy.app.timers.register(_initialize, first_interval=0.5)
