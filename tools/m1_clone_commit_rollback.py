#!/usr/bin/env python3
"""M1 isolated rehearsal using PT Asset Tool's existing bundle pipeline.

No writes to game_root or game_root/assets. --run writes only under
<tool_root>/app/pt_build/etervale/m1_clone_rehearsals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time
import uuid

STAGE_REL = pathlib.Path('Field/forest/fore-1.smd')
EXPECTED_STAGE_SHA = 'df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62'


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def execute(tool_root: pathlib.Path, game_root: pathlib.Path, *, run: bool = False,
            stage_override: pathlib.Path | None = None,
            expected_sha: str = EXPECTED_STAGE_SHA) -> dict:
    tool_root = tool_root.expanduser().resolve(strict=True)
    game_root = game_root.expanduser().resolve(strict=True)
    assets_root = game_root / 'assets'
    stage = (stage_override or (assets_root / STAGE_REL)).expanduser().resolve(strict=True)
    # An override is intentionally only for fixture testing, and still read-only.
    if not assets_root.is_dir():
        raise ValueError('CLIENT_ASSETS_ROOT_NOT_FOUND')
    if stage_override is None and not stage.is_relative_to(assets_root.resolve()):
        raise ValueError('STAGE_ESCAPES_ASSETS_ROOT')
    if not (tool_root / 'app' / 'pt_asset_tool' / 'asset_bundle_deploy.py').is_file():
        raise ValueError('ASSET_TOOL_DEPLOY_MODULE_NOT_FOUND')
    original_hash = sha256_file(stage)
    if original_hash != expected_sha:
        raise ValueError(f'SOURCE_STAGE_SHA_MISMATCH:{original_hash}:{expected_sha}')
    with stage.open('rb') as f:
        if f.read(23) != b'SMD Stage data Ver 0.72':
            raise ValueError('NOT_STAGE072')

    sys.path.insert(0, str(tool_root / 'app'))
    from pt_asset_tool.asset_compiler import BUNDLE_RECIPE_FORMAT, plan_asset_bundle, compile_asset_bundle
    from pt_asset_tool.asset_bundle_deploy import (
        APPLY_CONFIRM, RESTORE_CONFIRM, publish_asset_bundle, restore_asset_bundle,
    )

    recipe = {
        'format': BUNDLE_RECIPE_FORMAT,
        'id': 'm1_rehearsal_forest_stage',
        'bundle_type': 'FIELD',
        'payload': {'stage_asset': {
            'output': STAGE_REL.as_posix(),
            'source_path': str(stage),
            'expected_sha256': expected_sha,
            'target_policy': 'REPLACE_EXISTING',
        }},
    }
    result = {
        'format': 'ETERVALE_M1_CLONE_REHEARSAL_V1',
        'mode': 'CLONE_TRANSACTION' if run else 'READ_ONLY_PLAN',
        'game_assets_written': False,
        'source_stage': str(stage),
        'source_sha256_before': original_hash,
        'source_sha256_expected': expected_sha,
    }
    # Plan on the real assets root only: validates graph closure and target hash.
    plan = plan_asset_bundle(recipe, client_root=assets_root, server_root=None)
    result['plan_status'] = plan.get('status')
    result['plan_errors'] = plan.get('errors', [])
    visual = plan.get('visual_dependency') or {}
    result['visual_dependency_status'] = visual.get('status')
    result['missing_dependencies'] = visual.get('missing', [])
    if plan.get('status') != 'READY':
        result['status'] = 'BLOCKED_NO_WRITES'
        return result
    if not run:
        result['status'] = 'READY_FOR_ISOLATED_TEST'
        return result

    work_base = tool_root / 'app' / 'pt_build' / 'etervale' / 'm1_clone_rehearsals'
    work = work_base / f'm1_{time.strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:8]}'
    client_clone = work / 'client_clone'
    target = client_clone / STAGE_REL
    target.parent.mkdir(parents=True)
    shutil.copy2(stage, target)
    result['rehearsal_dir'] = str(work)
    result['clone_target'] = str(target)
    result['clone_sha256_before'] = sha256_file(target)
    # Compile against the *read-only* actual asset tree so dependencies can be checked.
    # Actual publishing occurs ONLY to client_clone, never the game asset tree.
    build = compile_asset_bundle(work, recipe, client_root=assets_root, server_root=None)
    result['build_manifest'] = str(build['manifest'])
    if sha256_file(target) != original_hash or sha256_file(stage) != original_hash:
        raise RuntimeError('SOURCE_OR_CLONE_DRIFT_BEFORE_PUBLISH')
    tx = publish_asset_bundle(work, client_clone, None, build['manifest'], confirm=APPLY_CONFIRM)
    result['publish_state'] = tx.get('state')
    result['published_sha256'] = sha256_file(target)
    result['backup_sha256'] = tx['files'][0].get('backup_sha256')
    if result['publish_state'] != 'APPLIED_VERIFIED' or result['published_sha256'] != expected_sha:
        raise RuntimeError('PUBLISH_VERIFICATION_FAILED')
    restored = restore_asset_bundle(work, client_clone, None, build['manifest'], confirm=RESTORE_CONFIRM)
    result['restore_state'] = restored.get('state')
    result['clone_sha256_after'] = sha256_file(target)
    result['source_sha256_after'] = sha256_file(stage)
    if result['restore_state'] != 'RESTORED_VERIFIED' or result['clone_sha256_after'] != original_hash:
        raise RuntimeError('RESTORE_VERIFICATION_FAILED')
    if result['source_sha256_after'] != original_hash:
        raise RuntimeError('GAME_SOURCE_CHANGED_ABORT')
    result['status'] = 'CLONE_COMMIT_ROLLBACK_PASS'
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tool-root', type=pathlib.Path, default=pathlib.Path.cwd())
    ap.add_argument('--game-root', type=pathlib.Path, required=True)
    ap.add_argument('--run', action='store_true', help='perform isolated clone transaction and restore')
    ns = ap.parse_args(argv)
    try:
        result = execute(ns.tool_root, ns.game_root, run=ns.run)
    except Exception as exc:
        result = {'format': 'ETERVALE_M1_CLONE_REHEARSAL_V1', 'status': 'FAILED',
                  'error': f'{type(exc).__name__}:{exc}', 'game_assets_written': False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] != 'BLOCKED_NO_WRITES' else 2


if __name__ == '__main__':
    raise SystemExit(main())
