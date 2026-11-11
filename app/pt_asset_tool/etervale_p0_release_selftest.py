"""Auditable release/rollback exercise against a disposable mock asset tree.

This proves approval, hash anchoring, atomic apply and rollback mechanics, not
content eligibility, C# reader acceptance, production publishing, or runtime.
"""
from __future__ import annotations

import pathlib
import tempfile
from typing import Any

from . import etervale_integration as bridge
from . import etervale_p0_release as release

FORMAT = 'PT_ASSET_ETERVALE_P0_RELEASE_SELFTEST_V1'
PASS = 'PASS_ISOLATED_RELEASE_ROLLBACK_NOT_PRODUCTION'


def exercise(lab_parent: pathlib.Path) -> dict:
    lab_parent.mkdir(parents=True, exist_ok=True)
    checks: dict[str,bool] = {}
    with tempfile.TemporaryDirectory(prefix='p0-release-sandbox-', dir=lab_parent) as directory:
        lab=pathlib.Path(directory)
        game=lab/'game'
        asset=game/'assets'/'GameServer'/'Field'/'Proof.spm'
        asset.parent.mkdir(parents=True)
        original=b'*DELAY 5 23\r\n'
        edited=b'*DELAY 3 2\r\n'
        asset.write_bytes(original)
        work=lab/'work'
        work.mkdir()
        candidate=work/'candidate.spm'
        candidate.write_bytes(edited)
        proof=work/'selftest-proof.json'
        proof.write_text('{"test_only":true}', encoding='utf-8')
        entry=release._entry(game,work,'GameServer/Field/Proof.spm',
                             release.digest(original),candidate,release.digest(edited))
        # Intentionally exercising the release mechanics via the internal plan
        # builder, NOT pretending this is a semantically validated WorldImport plan.
        plan=release._save_plan(game,work,'ISOLATED_MECHANICS_SELFTEST',[entry],proof)
        try:
            release.apply(game,work,pathlib.Path(plan['plan']),'invalid-approval')
        except ValueError as exc:
            checks['incorrect_approval_rejected']='APPROVAL' in str(exc)
        else:
            checks['incorrect_approval_rejected']=False
        checks['original_unchanged_after_denial']=asset.read_bytes()==original
        pub=release.apply(game,work,pathlib.Path(plan['plan']),plan['approval_sha256'])
        checks['publish_hash_matches_candidate']=(pub['status']=='PUBLISHED_NOT_RUNTIME_CERTIFIED' and
                                                   release.hashfile(asset)==release.digest(edited))
        rb=release.rollback(game,work,pathlib.Path(pub['journal']),plan['approval_sha256'])
        checks['rollback_restores_original']=(rb['status']=='ROLLED_BACK' and asset.read_bytes()==original)
        try:
            release.rollback(game,work,pathlib.Path(pub['journal']),plan['approval_sha256'])
        except ValueError as exc:
            checks['double_rollback_rejected']='ALREADY_COMPLETED' in str(exc)
        else:
            checks['double_rollback_rejected']=False
        # A separate plan must refuse unexpected edits between planning and apply.
        next_plan=release._save_plan(game,work,'ISOLATED_MECHANICS_SELFTEST',[entry],proof)
        asset.write_bytes(original+b'// external change\r\n')
        try:
            release.apply(game,work,pathlib.Path(next_plan['plan']),next_plan['approval_sha256'])
        except ValueError as exc:
            checks['source_drift_rejected']='CHANGED_SINCE_PLAN' in str(exc)
        else:
            checks['source_drift_rejected']=False
    passed=all(checks.values()) and len(checks)==6
    return {'format':FORMAT, 'status':PASS if passed else 'FAILED_ISOLATED_RELEASE_SELFTEST',
            'proof_level':'ISOLATED_SHA_APPLY_ROLLBACK_MECHANICS_ONLY',
            'checks':checks,'check_count':len(checks),
            'production_assets_modified':False,'game_assets_modified':False,
            'runtime_certification':'NOT_CERTIFIED',
            'limitations':['Plan made by isolated test fixture; does not certify native/binary content eligibility',
                           'No live Etervale game files, runtime, or production database were accessed'],
            'selftest_only':True}


def run(args:Any)->int:
    root=bridge._work_root()
    report=exercise(root/'p0_release_labs')
    report['report_file']=bridge._write_report('p0_release_selftest',report)
    bridge._print(report)
    return 0 if report['status']==PASS else 3


def register(sp:Any)->None:
    p=sp.add_parser('p0-release-selftest',help='isolated release SHA approval + rollback mechanical test (no game changes)')
    p.set_defaults(func=run)
