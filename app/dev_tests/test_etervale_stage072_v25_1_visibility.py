"""V25.1 regression: V19 native Stage must never reappear beside the proxy.

No Blender executable required: isolate the small visibility function by AST
and test it with strict Blender-object doubles; static checks cover all V25 UI
entry points. Actual Blender 5.2 execution remains a separate smoke test.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / 'pt_asset_tool/blender/stage072_tree_review_v25.py'


class FakeObject(dict):
    def __init__(self, name, *, src=False, proxy=False, view_only=False, source_name=None, hidden=False):
        super().__init__()
        self.name = name
        self.type = 'MESH'
        self.hidden = hidden
        self.selected = True
        self.hide_render = False
        self.actions = []
        if src:
            self['pt_stage072_source_sha256'] = 'f' * 64
        if proxy:
            self['pt_stage072_view_proxy'] = True
        if view_only:
            self['pt_stage072_view_only'] = True
        if source_name:
            self['pt_stage072_source_object'] = source_name

    def hide_get(self):
        return self.hidden

    def hide_set(self, state):
        self.hidden = state
        self.actions.append(('hide', state))

    def select_set(self, state):
        self.selected = state
        self.actions.append(('select', state))


class FakeObjects(list):
    def get(self, name):
        return next((ob for ob in self if ob.name == name), None)


def visibility_function(objects):
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_hide_native_stage_sources')
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {'bpy': SimpleNamespace(data=SimpleNamespace(objects=FakeObjects(objects)))}
    exec(compile(module, str(SCRIPT), 'exec'), scope)
    return scope['_hide_native_stage_sources']


def test_native_stage_hidden_without_hiding_proxy_or_arbitrary_objects():
    native = FakeObject('PT_STAGE072_STAGE', src=True)
    proxy = FakeObject('PT_STAGE072_VIEW_STAGE', proxy=True, view_only=True,
                       source_name=native.name)
    unrelated = FakeObject('PT_STAGE072_STAGE_BACKUP', src=True)
    fn = visibility_function([native, proxy, unrelated])
    assert fn() == 1
    assert native.hidden and native.hide_render and not native.selected
    assert proxy.hidden is False
    assert unrelated.hidden is False
    assert fn() == 0  # idempotent, not another import or source edit


def test_unverified_object_cannot_be_hidden_even_with_matching_name():
    impostor = FakeObject('PT_STAGE072_STAGE')  # no source provenance
    proxy = FakeObject('PT_STAGE072_VIEW_STAGE', proxy=True, view_only=True,
                       source_name=impostor.name)
    fn = visibility_function([impostor, proxy])
    assert fn() == 0
    assert not impostor.hidden
    assert not impostor.hide_render


def test_does_not_hide_other_stage_if_proxy_missing_or_unrelated():
    native = FakeObject('PT_STAGE072_STAGE', src=True)
    proxy_wrong = FakeObject('UNRELATED_VIEW', proxy=True, view_only=False,
                             source_name=native.name)
    fn = visibility_function([native, proxy_wrong])
    assert fn() == 0
    assert not native.hidden


def test_hides_only_the_native_source_named_in_each_valid_proxy():
    native1 = FakeObject('PT_STAGE072_STAGE', src=True)
    native2 = FakeObject('PT_STAGE072_STAGE_02', src=True, hidden=True)
    proxy1 = FakeObject('PT_STAGE072_VIEW_STAGE', proxy=True, view_only=True,
                        source_name=native1.name)
    proxy2 = FakeObject('PT_STAGE072_VIEW_STAGE_02', proxy=True, view_only=True,
                        source_name=native2.name)
    assert visibility_function([native1, native2, proxy1, proxy2])() == 1
    assert native1.hidden and native2.hidden
    assert not proxy1.hidden and not proxy2.hidden


def test_calls_always_enforce_native_visibility_and_expose_ui_repair():
    script = SCRIPT.read_text(encoding='utf-8')
    tree = ast.parse(script)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for fn in ('_clear_pair', '_focus_pair', 'configure'):
        segment = ast.get_source_segment(script, functions[fn])
        assert '_hide_native_stage_sources()' in segment, fn
    create = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                  and n.name == 'PT_OT_V25CreateObjects')
    assert '_hide_native_stage_sources()' in ast.get_source_segment(script, create)
    assert 'pt_semantic.v25_hide_native_stage' in script
    assert 'PT_OT_V25HideNative' in script
    assert 'from __future__ import annotations' not in script  # bpy.props in Blender 5.2
    compile(script, str(SCRIPT), 'exec')


def test_uploaded_v25_review_decisions_not_changed_if_fixture_available():
    fixture = Path('/mnt/data/6cd0d6e8c7586543.v25_review.json')
    if not fixture.exists():
        return
    doc = json.loads(fixture.read_text())
    assert len(doc['matches']) == 41
    assert sum(m['decision'] == 'PENDING' for m in doc['matches']) == 41
    assert doc['publish_enabled'] is False


def test_cleanup_deletes_only_named_inspection_collections():
    script = SCRIPT.read_text(encoding='utf-8')
    tree = ast.parse(script)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    fn = funcs['_clear_inspection_copies']
    source = ast.get_source_segment(script, fn)
    assert 'v23._remove_collection(collection_name)' in source
    assert 'GROUP_COLLECTION, v24.COLLECTION, v23.ISOLATE_COLLECTION' in source
    assert '_hide_native_stage_sources()' in source
    assert 'bpy.data.objects.remove' not in source
    assert '.write_' not in source and 'atomic_write_json' not in source
    assert 'PT_OT_V25ClearInspection' in script
    assert 'pt_semantic.v25_clear_inspection' in script


def test_cleanup_mock_removes_only_copies_and_keeps_state():
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == '_clear_inspection_copies')
    partial = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(partial)
    names = ['TEMP_V25', 'TEMP_V24', 'TEMP_V23']
    objects = {names[0]: ['a', 'b'], names[1]: ['c'], names[2]: ['d']}
    removed_names = []
    native_calls = []
    scope = {
        '_clear_pair': lambda: None,
        '_hide_native_stage_sources': lambda: native_calls.append('hide'),
        'GROUP_COLLECTION': names[0],
        'v24': SimpleNamespace(COLLECTION=names[1]),
        'v23': SimpleNamespace(ISOLATE_COLLECTION=names[2],
                               _remove_collection=lambda name: removed_names.append(name)),
        'bpy': SimpleNamespace(data=SimpleNamespace(collections=SimpleNamespace(
            get=lambda name: SimpleNamespace(objects=objects[name]) if name in objects else None))),
    }
    exec(compile(partial, str(SCRIPT), 'exec'), scope)
    assert scope['_clear_inspection_copies']() == 4
    assert removed_names == names
    assert native_calls == ['hide']
