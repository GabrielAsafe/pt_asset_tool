from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_vendor_module():
    root = Path(__file__).resolve().parents[2]
    vendor = root / 'vendor' / 'summit_asset_enrichment_v9'
    sys.path.insert(0, str(vendor))
    try:
        spec = importlib.util.spec_from_file_location('summit_vendor_graph_v9_test', vendor / 'build_dependency_graph.py')
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_vendor_spm_parser_matches_runtime_cp949_aliases_and_boss_pair():
    mod = _load_vendor_module()
    text = '*출연자 "Ice Hopy" 50\n*출연자두목 "Boss One" "Slave Two" 2 12\n*ACTOR Hopy 50\n'
    assert mod.parse_spm_actor_rows(text) == [
        ('ACTOR', 'Ice Hopy'),
        ('BOSS_ACTOR', 'Boss One'),
        ('BOSS_ACTOR', 'Slave Two'),
        ('ACTOR', 'Hopy'),
    ]
