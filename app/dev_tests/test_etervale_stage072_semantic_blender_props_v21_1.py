"""V21.1 regression: Blender 5.2 deferred class registration must see real bpy props.

No Blender binary is required; the test compiles the extracted PropertyGroup
with mock property factories and simulates the RNA registration contract.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
SCRIPT = APP / 'pt_asset_tool/blender/stage072_semantic_paint.py'
PROPERTY_NAMES = {
    'region_id', 'category', 'face_count', 'note', 'replacement_asset',
    'offset_game', 'yaw_degrees', 'asset_scale',
}


def _source_tree():
    return ast.parse(SCRIPT.read_text(encoding='utf8'), filename=str(SCRIPT))


def test_blender_properties_not_postponed_as_strings():
    tree = _source_tree()
    assert not any(
        isinstance(n, ast.ImportFrom) and n.module == '__future__'
        and any(a.name == 'annotations' for a in n.names)
        for n in tree.body
    ), 'Blender 5.2 cannot resolve stringified bpy.props in delayed registration'
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PT_SemanticRegion')
    annotated = {n.target.id: n for n in cls.body if isinstance(n, ast.AnnAssign)}
    assert set(annotated) == PROPERTY_NAMES
    assert all(isinstance(n.annotation, ast.Call) for n in annotated.values())
    assert all(isinstance(n.annotation.func, ast.Name) and n.annotation.func.id.endswith('Property')
               for n in annotated.values())


def test_propertygroup_annotations_are_real_objects_for_registration():
    tree = _source_tree()
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PT_SemanticRegion')
    # Mock Blender bpy.props as distinct non-string objects to verify that
    # each property's factory actually executes at class definition time.
    class Deferred:
        def __init__(self, kind, kwargs):
            self.kind = kind
            self.kwargs = kwargs

    def factory(kind):
        return lambda **kwargs: Deferred(kind, kwargs)

    ns = {
        '__name__': 'test_blender_registration_v21_1',
        'bpy': SimpleNamespace(types=SimpleNamespace(PropertyGroup=object)),
        'CATEGORY_ITEMS': [('ARVORE', 'Árvore', 'Árvore'), ('APAGAR', 'Apagar', 'Apagar')],
        '_on_edit': lambda self, context: None,
        **{name: factory(name) for name in
           ('StringProperty', 'EnumProperty', 'IntProperty', 'FloatProperty',
            'FloatVectorProperty')},
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(SCRIPT), 'exec'), ns)
    annotations = ns['PT_SemanticRegion'].__annotations__
    assert set(annotations) == PROPERTY_NAMES
    assert all(isinstance(value, Deferred) for value in annotations.values())
    assert annotations['note'].kwargs['update'] is ns['_on_edit']
    assert annotations['category'].kind == 'EnumProperty'
    assert annotations['offset_game'].kwargs['size'] == 3


def test_no_changes_to_semantic_source_contract():
    source = SCRIPT.read_text(encoding='utf8')
    assert 'bpy.app.timers.register(_initialize, first_interval=0.5)' in source
    assert 'atomic_write_json(opts.output, DOCUMENT)' in source
    assert 'view_module.configure_stage072_view()' in source
    assert 'bpy.ops.wm.save_as_mainfile' not in source
    assert 'src.data.transform(' not in source
