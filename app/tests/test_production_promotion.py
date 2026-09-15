from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

PKG = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = PKG / "payload"
sys.path.insert(0, str(PAYLOAD))

from pt_asset_tool import rare_rigid_edit as redit
from pt_asset_tool import rare_rigid_multivertex as mv
from pt_asset_tool.rare_rigid_large_production import (
    _ProductionCertificationProxy,
    load_and_validate_policy,
    production_widening,
    POLICY_FORMAT,
    POLICY_REL,
    MANUAL_REL,
)
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from pt_asset_tool.rare_rigid_multivertex import plan_requested_at_dragon_transaction
from pt_asset_tool.rare_rigid_large_production_promotion import _cross_object_changes_from_discovery


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256(path.read_bytes())
    return h.hexdigest()


class FakeRegistry:
    def __init__(self):
        self.directory = pathlib.Path("/fake")
        self.path = self.directory / "assets.jsonl"
        self.rows = []
    def records(self):
        return list(self.rows)
    def add(self, **kwargs):
        row = dict(kwargs)
        row["certification_id"] = "CERT-TEST"
        self.rows.append(row)
        return row


class PromotionTests(unittest.TestCase):
    def test_widening_restores(self):
        self.assertEqual(redit.MAX_TRANSACTION_VERTICES, 4)
        self.assertEqual(mv.MAX_TRANSACTION_VERTICES, 4)
        with production_widening():
            self.assertEqual(redit.MAX_TRANSACTION_VERTICES, 8)
            self.assertEqual(mv.MAX_TRANSACTION_VERTICES, 8)
        self.assertEqual(redit.MAX_TRANSACTION_VERTICES, 4)
        self.assertEqual(mv.MAX_TRANSACTION_VERTICES, 4)

    def test_widening_restores_on_exception(self):
        with self.assertRaises(RuntimeError):
            with production_widening():
                raise RuntimeError("boom")
        self.assertEqual(redit.MAX_TRANSACTION_VERTICES, 4)
        self.assertEqual(mv.MAX_TRANSACTION_VERTICES, 4)

    def test_proxy_relabels_only_large_transaction(self):
        fake = FakeRegistry()
        proxy = _ProductionCertificationProxy(fake)
        row = proxy.add(
            test="RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE",
            metadata={"artist_changed_vertices": 5, "write_scope": "old"},
            notes="",
        )
        self.assertEqual(row["test"], "RARE_RIGID_ARTIST_GUARDED_LARGE_TRANSACTION_WRITE")
        self.assertTrue(row["metadata"]["production_authorized"])
        row2 = proxy.add(
            test="RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE",
            metadata={"artist_changed_vertices": 4, "write_scope": "old"},
            notes="",
        )
        self.assertEqual(row2["test"], "RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE")

    def test_policy_validation_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            for rel in EXPECTED_WRITER_HASHES:
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PAYLOAD / rel, dst)
            manual = root / MANUAL_REL
            manual.parent.mkdir(parents=True, exist_ok=True)
            manual.write_text('{"status":"PASS"}\n', encoding="utf-8")
            policy = {
                "format": POLICY_FORMAT,
                "status": "PASS",
                "production_authorized": True,
                "production_max_vertices": 8,
                "logical": "char/tmABCD/at_dragon.smd",
                "writer_hashes": EXPECTED_WRITER_HASHES,
                "cross_object_blocked": True,
                "nine_vertex_blocked": True,
                "bounds_negative_blocked": True,
                "manual_artist_proof": True,
                "manual_report_sha256": sha(manual),
            }
            pp = root / POLICY_REL
            pp.parent.mkdir(parents=True, exist_ok=True)
            pp.write_text(json.dumps(policy), encoding="utf-8")
            got = load_and_validate_policy(root)
            self.assertTrue(got["production_authorized"])
            manual.write_text('{"status":"FAIL"}\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_and_validate_policy(root)

    def test_cross_object_schema_uses_parent_object_index(self):
        discovery = {
            "complete": True,
            "representatives": {
                "vertices_5": {
                    "object_index": 0,
                    "changed_vertices": [{"vertex_index": 91, "requested_after_world_fixed": [1, 2, 3]}],
                },
                "vertices_6": {
                    "object_index": 8,
                    "changed_vertices": [{"vertex_index": 35, "requested_after_world_fixed": [4, 5, 6]}],
                },
                "vertices_7": {"object_index": 8, "changed_vertices": [{"vertex_index": 38, "requested_after_world_fixed": [7, 8, 9]}]},
                "vertices_8": {"object_index": 0, "changed_vertices": [{"vertex_index": 4, "requested_after_world_fixed": [10, 11, 12]}]},
            },
        }
        changes = _cross_object_changes_from_discovery(discovery)
        self.assertEqual(changes, [
            {"object_index": 0, "vertex_index": 91, "after_world_fixed": [1, 2, 3]},
            {"object_index": 8, "vertex_index": 35, "after_world_fixed": [4, 5, 6]},
        ])

        with self.assertRaisesRegex(ValueError, "MULTI_OBJECT_TRANSACTION_DEFERRED"):
            plan_requested_at_dragon_transaction(pathlib.Path("unused.smd"), pathlib.Path("unused.smb"), changes=changes)

    def test_payload_writers_still_match_v089(self):
        for rel, expected in EXPECTED_WRITER_HASHES.items():
            self.assertEqual(sha(PAYLOAD / rel), expected, rel)


if __name__ == "__main__":
    unittest.main()
