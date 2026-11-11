"""V7 proof boundaries: optional Summit UI, local NCNN discovery, particle paging."""
from pathlib import Path
from html.parser import HTMLParser
import os
import pytest

from pt_asset_tool.dependencies import resolve_realesrgan
from pt_asset_tool.texture_upscale import discover_ncnn_model_dir, ncnn_model_inventory

ROOT = Path(__file__).resolve().parents[1] / 'pt_asset_tool'


def test_ai_enhcance_layout_detects_existing_binary_and_ncnn_pairs(tmp_path):
    repo = tmp_path / 'repo'
    app = repo / 'app'
    app.mkdir(parents=True)
    base = repo / 'AI_enhcance' / 'realesrgan'
    models = base / 'models'
    models.mkdir(parents=True)
    binary = base / 'realesrgan-ncnn-vulkan'
    binary.write_text('#!/bin/sh\nexit 0\n', encoding='utf8')
    binary.chmod(0o755)
    (models / 'realesrgan-x4plus.param').write_text('param')
    (models / 'realesrgan-x4plus.bin').write_bytes(b'model')
    (models / 'incomplete.param').write_text('param')
    resolved, reason = resolve_realesrgan(app)
    assert resolved == str(binary.resolve())
    assert 'bundled' in reason
    assert discover_ncnn_model_dir('realesrgan-x4plus', app) == models
    assert discover_ncnn_model_dir('incomplete', app) is None
    assert discover_ncnn_model_dir('../escape', app) is None
    assert [m['name'] for m in ncnn_model_inventory(app)] == ['realesrgan-x4plus']


def test_non_executable_ai_binary_is_not_presented_as_ready(tmp_path,monkeypatch):
    repo=tmp_path/'repo';app=repo/'app';app.mkdir(parents=True)
    exe=repo/'AI_enhcance'/'realesrgan'/'realesrgan-ncnn-vulkan'
    exe.parent.mkdir(parents=True);exe.write_bytes(b'no executable permission');exe.chmod(0o644)
    monkeypatch.setattr('pt_asset_tool.dependencies._which', lambda name:None)
    resolved, reason=resolve_realesrgan(app)
    assert resolved is None
    assert 'PATH' in reason


class _SimpleHtmlTree(HTMLParser):
    """Find elements, attributes and ancestors using Python's standard library."""
    void_tags = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs),
                'ancestors': tuple(n['attrs'].get('id') for n in self.stack)}
        self.elements.append(node)
        if tag not in self.void_tags:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def with_attr(self, attr, value):
        matches = [node for node in self.elements if node['attrs'].get(attr) == value]
        assert len(matches) == 1, (attr, value, len(matches))
        return matches[0]


def test_ui_native_navigation_hides_summit_requirements():
    html=(ROOT/'ui_static/index.html').read_text(encoding='utf8')
    css=(ROOT/'ui_static/app.css').read_text(encoding='utf8')
    js=(ROOT/'ui_static/app.js').read_text(encoding='utf8')
    page=_SimpleHtmlTree()
    page.feed(html)
    ids = [node['attrs']['id'] for node in page.elements if 'id' in node['attrs']]
    assert len(ids) == len(set(ids))
    assert 'hidden' in page.with_attr('data-server-workflow','census')['attrs']
    assert 'hidden' in page.with_attr('data-client-workflow','census')['attrs']
    for elem in ['playerContractsBtn','clientPlayerContractsBtn','sourceContractsBtn']:
        assert 'hidden' in page.with_attr('id',elem)['attrs']
    source_root=page.with_attr('id','sourceRootInput')
    assert 'legacySourceDonorsDetails' in source_root['ancestors']
    assert 'canonicalLegacyDetails' in page.with_attr('id','canonicalV211Panel')['ancestors']
    for action in ['canonicalV211PublishSource','canonicalV211PublishPacks','canonicalV211DeployRuntime']:
        assert 'disabled' in page.with_attr('id',action)['attrs']
    assert page.with_attr('id','legacyAuthoringStageBtn')
    assert page.with_attr('id','clientEnhancementIncludeUi')
    assert page.with_attr('id','clientEnhancementBackend')
    assert 'data-support-tab="validation"' in html
    assert '[hidden]{display:none !important}' in css
    assert "const allowed=new Set(['config','diagnostics','validation','evidence','activity']);" in js
    assert '/api/enhancement/backend-status' in js


def test_particles_are_paged_not_rendered_whole_and_responsive():
    html=(ROOT/'ui_static/index.html').read_text()
    js=(ROOT/'ui_static/app.js').read_text()
    css=(ROOT/'ui_static/app.css').read_text()
    backend=(ROOT/'ui_app.py').read_text()
    for elem in ['particlePagePrev','particlePageNext','particlePageInfo']:
        assert f'id="{elem}"' in html
    assert 'class="particle-layout"' in html
    assert 'max-width:880px' in css
    assert "offset:String(page*100),limit:'100'" in js
    assert 'S.particleRequestSeq' in js
    assert 'S.particleInspectSeq' in js
    assert 'rows[offset:offset+limit]' in backend
    assert 'allFields.slice(0,150)' in js


def test_global_ai_no_longer_forces_ui_atlases_or_realesrgan():
    js=(ROOT/'ui_static/app.js').read_text()
    app=(ROOT/'ui_app.py').read_text()
    dependencies=(ROOT/'dependencies.py').read_text()
    assert "backend=$('#clientEnhancementBackend')?.value||'auto'" in js
    assert "includeUi=Boolean($('#clientEnhancementIncludeUi')?.checked)" in js
    assert '*(["--include-ui"] if body.get("include_ui") is True else [])' in app
    assert "discover_ncnn_model_dir(model_name, self.ctx.project_root)" in app
    assert "AI_enhcance" in dependencies
    assert 'pytorch_pth_directly_compatible' in app
