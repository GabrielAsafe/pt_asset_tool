#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(*args: object) -> None:
    print('+', ' '.join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], check=True)




def relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()

def main() -> None:
    ap = argparse.ArgumentParser(description='Reproducible Summit textual-content migration build')
    ap.add_argument('--corpus', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--out-root', type=Path, required=True)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    out = args.out_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    shadow = out / 'content_shadow'
    canonical = out / 'canonical_text'
    stage_canonical = out / 'canonical_stage_spawns'
    map_shadow = out / 'map_shadow'
    map_semantic = out / 'map_semantic'
    canonical_build = out / 'canonical_build'
    py = sys.executable

    # One-time import / semanticization from proprietary text and hardcoded C++.
    run(py, here / 'import_corpus.py', '--corpus', args.corpus, '--source-root', args.source_root, '--out', shadow)
    run(py, here / 'validate_shadow.py', shadow)
    run(py, here / 'validate_relations.py', '--shadow', shadow, '--corpus', args.corpus, '--out', shadow / 'RELATIONS.json')
    run(py, here / 'canonicalize_text_content.py', '--shadow', shadow, '--corpus', args.corpus, '--out', canonical)
    run(py, here / 'validate_canonical_text.py', canonical)
    coverage = out / 'MIGRATION_COVERAGE.json'
    run(py, here / 'classify_migration_coverage.py', '--shadow', shadow, '--out', coverage)
    run(py, here / 'canonicalize_stage_spawns.py', '--shadow', shadow, '--canonical-text', canonical, '--out', stage_canonical)

    map_shadow.mkdir(parents=True, exist_ok=True)
    map_semantic.mkdir(parents=True, exist_ok=True)
    server = args.source_root / 'Shared/world/field/field_legacy_server.inl'
    client = args.source_root / 'Shared/world/field/field_legacy_client.inl'
    run(py, here / 'extract_legacy_maps.py', server, client, '--out-dir', map_shadow)
    run(py, here / 'compare_map_shadows.py', map_shadow / 'field_legacy_server.maps.json', map_shadow / 'field_legacy_client.maps.json', '--out', map_shadow / 'client_server_diff.json')
    for profile, source in (('client', client), ('server', server)):
        run(py, here / 'semanticize_maps.py', source, '--profile', profile, '--source-root', args.source_root, '--output', map_semantic / f'{profile}.maps.json')

    # From this point onward the build consumes canonical JSON only.
    run(
        py, here / 'build_from_canonical.py',
        '--canonical-text', canonical,
        '--canonical-spawns', stage_canonical,
        '--canonical-maps', map_semantic,
        '--out-root', canonical_build,
    )

    summary = {
        'schema': 'summit.text-pipeline-build/v2',
        'corpus': args.corpus.resolve().name,
        'source_root': '.',
        'shadow': relative_to(shadow, out),
        'canonical_text': relative_to(canonical, out),
        'canonical_stage_spawns': relative_to(stage_canonical, out),
        'canonical_maps': relative_to(map_semantic, out),
        'canonical_build': relative_to(canonical_build / 'BUILD.json', out),
        'migration_coverage': relative_to(coverage, out),
        'note': 'Runtime packs are rebuilt exclusively from canonical JSON after the import/semanticization boundary. Coverage validation fails the build if any imported textual document remains unclassified.',
    }
    (out / 'BUILD.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('BUILD=PASS')


if __name__ == '__main__':
    main()
