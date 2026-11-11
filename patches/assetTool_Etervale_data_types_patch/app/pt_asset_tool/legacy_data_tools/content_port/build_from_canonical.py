#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def run(*args: object) -> None:
    print('+', ' '.join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], check=True)




def portable_input_path(path: Path, cwd: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return resolved.name


def portable_output_path(path: Path, out_root: Path) -> str:
    return path.resolve().relative_to(out_root.resolve()).as_posix()

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Compile all Summit runtime content packs using canonical JSON only'
    )
    ap.add_argument('--canonical-text', type=Path, required=True)
    ap.add_argument('--canonical-spawns', type=Path, required=True)
    ap.add_argument('--canonical-maps', type=Path, required=True)
    ap.add_argument('--canonical-start-points', type=Path, required=True)
    ap.add_argument('--canonical-fixed-npcs', type=Path, required=True)
    ap.add_argument('--canonical-item-profiles', type=Path, required=True)
    ap.add_argument('--out-root', type=Path, required=True)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    py = sys.executable
    text = args.canonical_text.resolve()
    spawns = args.canonical_spawns.resolve()
    maps = args.canonical_maps.resolve()
    start_points = args.canonical_start_points.resolve()
    fixed_npcs = args.canonical_fixed_npcs.resolve()
    item_profiles = args.canonical_item_profiles.resolve()
    gameplay_reference = (text.parent / 'gameplay_reference').resolve()
    commerce = (text.parent / 'commerce').resolve()
    out = args.out_root.resolve()
    invocation_root = Path.cwd().resolve()
    packs = out / 'packs'
    packs.mkdir(parents=True, exist_ok=True)

    run(py, here / 'materialize_localization_catalog.py', text)
    run(py, here / 'validate_canonical_text.py', text)
    run(py, here / 'validate_canonical_schemas.py', '--canonical-text', text, '--canonical-spawns', spawns, '--canonical-maps', maps, '--canonical-start-points', start_points, '--canonical-fixed-npcs', fixed_npcs)
    run(py, here / 'validate_single_entry_map_policy.py', '--canonical-maps', maps)
    run(py, here / 'validate_monster_runtime_limits.py', '--repo-root', here.parents[2])

    outputs = {
        'text_resources': packs / 'text_resources.sres',
        'definitions_client': packs / 'definitions_client.scfg',
        'definitions_server': packs / 'definitions_server.scfg',
        'gameplay_config': packs / 'gameplay_config.sgcf',
        'gameplay_reference': packs / 'gameplay_reference.sgrf',
        'coin_shop': packs / 'coin_shop.scsp',
        'skin_reforms': packs / 'skin_reforms.sskm',
        'field_runtime': packs / 'field_runtime.sfld',
        'maps_client': packs / 'maps_client.smap',
        'maps_server': packs / 'maps_server.smap',
    }

    run(py, here / 'compile_text_resources.py', text, outputs['text_resources'])
    run(py, here / 'inspect_text_resources.py', outputs['text_resources'])
    # Remove the obsolete second pack only once the merged SRES passes both inspectors.
    run(py, here / 'inspect_localization.py', outputs['text_resources'])
    legacy_sloc = packs / 'localization.sloc'
    if legacy_sloc.exists():
        if not legacy_sloc.is_file() or legacy_sloc.is_symlink():
            raise SystemExit('refusing to delete non-regular legacy localization pack')
        # Keep the old format outside Content for explicit rollback.
        old_backup = here.parents[2] / 'bugfixes' / '.summit_sres_merge' / 'source_localization.sloc'
        old_backup.parent.mkdir(parents=True, exist_ok=True)
        if old_backup.exists():
            if old_backup.is_symlink() or not old_backup.is_file() or sha256(old_backup) != sha256(legacy_sloc):
                raise SystemExit(f'legacy backup already exists with different bytes: {old_backup}')
        else:
            old_backup.write_bytes(legacy_sloc.read_bytes())
        legacy_sloc.unlink()
    legacy_report = packs / 'localization.sloc.report.json'
    if legacy_report.exists():
        if legacy_report.is_symlink() or not legacy_report.is_file():
            raise SystemExit('refusing to delete non-regular legacy report')
        report_backup = here.parents[2] / 'bugfixes' / '.summit_sres_merge' / 'source_localization.sloc.report.json'
        report_backup.parent.mkdir(parents=True, exist_ok=True)
        if report_backup.exists():
            if report_backup.is_symlink() or not report_backup.is_file() or sha256(report_backup) != sha256(legacy_report):
                raise SystemExit(f'conflicting localization report backup: {report_backup}')
        else:
            report_backup.write_bytes(legacy_report.read_bytes())
        legacy_report.unlink()
    npc_shop_overrides = commerce / 'npc_shop_overrides.json'
    if not npc_shop_overrides.is_file():
        raise SystemExit(f'missing canonical NPC shop overrides: {npc_shop_overrides}')
    run(py, here / 'validate_npc_shop_catalog.py', '--repo-root', here.parent.parent)
    for profile in ('client', 'server'):
        profile_catalog = item_profiles / f'{profile}.items.json'
        if not profile_catalog.is_file():
            raise SystemExit(f'missing canonical item profile: {profile_catalog}')
        output = outputs[f'definitions_{profile}']
        run(py, here / 'compile_definitions.py', text, output, '--item-profile', profile_catalog, '--npc-shop-overrides', npc_shop_overrides)
        run(py, here / 'inspect_definitions.py', output)
    run(py, here / 'validate_item_profile_pack.py', '--source-root', here.parent.parent, '--content-root', out, '--canonical-item-profiles', item_profiles, '--canonical-text', text, '--profile', 'both')
    run(py, here / 'compile_gameplay_config.py', text, outputs['gameplay_config'])
    run(py, here / 'inspect_gameplay_config.py', outputs['gameplay_config'])
    coin_shop_catalog = commerce / 'coin_shop.json'
    if not coin_shop_catalog.is_file():
        raise SystemExit(f'missing canonical coin shop catalog: {coin_shop_catalog}')
    run(py, here / 'validate_coin_shop_catalog.py', '--repo-root', here.parent.parent)
    run(py, here / 'compile_coin_shop.py', coin_shop_catalog, outputs['coin_shop'])
    run(py, here / 'inspect_coin_shop.py', outputs['coin_shop'])
    run(py, here / 'compile_skin_reforms.py', item_profiles / 'skin_reforms.json', outputs['skin_reforms'])
    if not gameplay_reference.is_dir():
        raise SystemExit(f'missing canonical gameplay reference root: {gameplay_reference}')
    run(py, here / 'compile_gameplay_reference.py', gameplay_reference, outputs['gameplay_reference'])
    run(py, here / 'inspect_gameplay_reference.py', outputs['gameplay_reference'])
    run(py, here / 'compile_field_runtime.py', '--canonical-spawns', spawns, '--canonical-start-points', start_points, '--canonical-fixed-npcs', fixed_npcs, '--canonical-text', text, outputs['field_runtime'])
    run(py, here / 'inspect_field_runtime.py', outputs['field_runtime'])
    for stale_name in ('stage_spawns.sspb', 'stage_spawns.sspb.report.json'):
        stale = packs / stale_name
        if stale.exists():
            stale.unlink()

    for profile in ('client', 'server'):
        catalog = maps / f'{profile}.maps.json'
        if not catalog.is_file():
            raise SystemExit(f'missing canonical map catalog: {catalog}')
        output = outputs[f'maps_{profile}']
        run(py, here / 'compile_maps.py', catalog, output)
        run(py, here / 'inspect_maps.py', output)

    manifest = {
        'schema': 'summit.canonical-content-build/v1',
        'inputs': {
            'canonical_text': portable_input_path(text, invocation_root),
            'canonical_spawns': portable_input_path(spawns, invocation_root),
            'canonical_maps': portable_input_path(maps, invocation_root),
            'canonical_start_points': portable_input_path(start_points, invocation_root),
            'canonical_fixed_npcs': portable_input_path(fixed_npcs, invocation_root),
            'canonical_item_profiles': portable_input_path(item_profiles, invocation_root),
            'canonical_gameplay_reference': portable_input_path(gameplay_reference, invocation_root),
            'canonical_commerce': portable_input_path(commerce, invocation_root),
        },
        'packs': {
            name: {
                'path': portable_output_path(path, out),
                'bytes': path.stat().st_size,
                'sha256': sha256(path),
            }
            for name, path in outputs.items()
        },
    }
    (out / 'BUILD.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    print('CANONICAL_BUILD=PASS')


if __name__ == '__main__':
    main()
