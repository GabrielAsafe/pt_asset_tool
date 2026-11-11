"""P1/03: evidence-backed inventory of missing field primary textures.

Uses native AssetDump --matbounds; does not infer exhaustive asset dependency
closure from filename matches or textual grep. Secondary UV dependencies still need
coverage; report explicitly retains this scope limitation.
"""
from __future__ import annotations
import csv
import io
import json
import pathlib
import re
import subprocess
from typing import Any
from . import etervale_integration as bridge

# The per-material bounds table (C# AssetDump) includes a face count.
MAT_ROW = re.compile(r'^\s*(\d+)\s+\S+\s+(\d+)\s+\([^)]*\)\s+\([^)]*\)\s+(\S+\.\w+)\s*$', re.I)
IMAGE_SUFFIXES = {'.bmp', '.tga', '.jpg', '.jpeg', '.png', '.dds'}

def parse_matbounds(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        m = MAT_ROW.match(line)
        if m and pathlib.PureWindowsPath(m.group(3)).suffix.casefold() in IMAGE_SUFFIXES:
            rows.append({'material': int(m.group(1)), 'faces': int(m.group(2)),
                         'texture': m.group(3)})
    return rows


def resolve_local_texture(stage: pathlib.Path, texture: str) -> dict:
    token = texture.replace('\\', '/').strip()
    raw = pathlib.PurePosixPath(token)
    if raw.is_absolute() or '..' in raw.parts or not raw.parts:
        return {'state': 'UNSAFE_REFERENCE', 'texture': texture}
    base = stage.parent
    # Casefold segment-by-segment; follow only within the map directory.
    segment_choices = [raw] if len(raw.parts) == 1 else [raw]
    for candidate in segment_choices:
        cur = base
        for part in candidate.parts:
            if not cur.is_dir():
                break
            matches = [p for p in cur.iterdir() if p.name.casefold() == part.casefold()]
            if len(matches) != 1:
                break
            cur = matches[0]
        else:
            if cur.is_file() and cur.resolve().is_relative_to(base.resolve()):
                return {'state': 'PRESENT_LOCAL', 'path': str(cur)}
    # Alternate image formats cannot be called identical textures. List as candidates.
    alternatives = sorted(p.name for p in base.iterdir()
                          if p.is_file() and p.stem.casefold() == raw.stem.casefold()
                          and p.suffix.casefold() in IMAGE_SUFFIXES)
    return {'state': 'MISSING_LOCAL', 'alternatives': alternatives}


def classify_rows(stage: pathlib.Path, rows: list[dict]) -> list[dict]:
    classified = []
    for row in rows:
        if row['faces'] <= 0:
            classified.append({**row, 'state': 'UNUSED_MATERIAL_REFERENCE'})
        else:
            classified.append({**row, **resolve_local_texture(stage, row['texture'])})
    return classified


def _csv(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=('stage', 'material', 'faces', 'texture', 'state', 'path', 'alternatives'))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row[k],ensure_ascii=False) if isinstance(row.get(k),list) else row.get(k, '')
                             for k in writer.fieldnames})


def run(a: Any) -> int:
    root = bridge._game_root(a)
    if a.build and not a.execute:
        raise ValueError('BUILD_REQUIRES_EXECUTE')
    if not 1 <= len(a.asset) <= 100:
        raise ValueError('REQUIRE_1_TO_100_EXPLICIT_STAGES')
    stage_files = [bridge._input_path(root, name, None, {'.smd'}) for name in a.asset]
    items = []
    output_rows = []
    native_failures = 0
    for idx, stage in enumerate(stage_files):
        item = {'file': str(stage), 'sha256': bridge._hash_file(stage),
                'native_reader': 'NOT_RUN', 'rows': [], 'missing_used_count': None}
        if a.execute:
            project = bridge._csproj(root, 'inspect')
            if a.build and idx == 0:
                built = subprocess.run(['dotnet', 'build', str(project), '-c', 'Release', '-m:1'],
                                       cwd=root, env=bridge.external_process_env(),
                                       text=True, capture_output=True, timeout=180, check=False)
                if built.returncode:
                    raise RuntimeError('ASSETDUMP_BUILD_FAILED:' + built.stderr[-500:])
            # --matbounds can exceed the bridge's 12k stdout tail on large maps.
            # Keep the full bounded process output for precise per-material counts.
            proc = subprocess.run(['dotnet','run','--project',str(project),'-c','Release',
                                   '--no-build','--',str(stage),'--matbounds'],
                                  cwd=root, env=bridge.external_process_env(),
                                  text=True, capture_output=True, timeout=180, check=False)
            item['native_exit_code'] = proc.returncode
            item['native_reader'] = 'PASS' if proc.returncode == 0 else 'FAIL'
            if proc.returncode:
                native_failures += 1
                item['stderr_tail'] = proc.stderr[-1000:]
            else:
                if len(proc.stdout) > 16 * 1024 * 1024:
                    raise ValueError('ASSETDUMP_OUTPUT_EXCEEDS_SAFE_LIMIT')
                item['rows'] = classify_rows(stage, parse_matbounds(proc.stdout))
                item['missing_used_count'] = sum(r['state'] == 'MISSING_LOCAL' for r in item['rows'])
                output_rows.extend({'stage': str(stage), **row} for row in item['rows'])
            item['source_unchanged'] = bridge._hash_file(stage) == item['sha256']
        items.append(item)
    missing = sum(r['state'] == 'MISSING_LOCAL' for r in output_rows)
    report = {'format': 'PT_ASSET_ETERVALE_ASSET_GAPS_V1',
              'scope': 'PRIMARY_TEXTURE_PER_MATERIAL_WITH_NONZERO_FACE_COUNT_ONLY',
              'limitations': ['secondary textures, opacity references and runtime-only dependencies not fully scanned',
                              'missing local does not prove absent in all donor sources'],
              'game_root': str(root), 'assets_checked': len(items), 'assets': items,
              'missing_used_texture_count': missing, 'native_failures': native_failures,
              'game_assets_modified': False,
              'status': 'PLANNED' if not a.execute else 'NATIVE_FAILED' if native_failures else 'MISSING_DEPENDENCIES' if missing else 'NO_MISSING_PRIMARY_TEXTURES_IN_CHECKED_SCOPE'}
    report_path = pathlib.Path(bridge._write_report('asset_gaps', report))
    csv_path = report_path.with_suffix('.csv')
    _csv(csv_path, output_rows)
    report['csv_file'] = str(csv_path)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    bridge._print(report)
    return 3 if native_failures or (a.strict and missing) else 0


def register(sp):
    x = sp.add_parser('asset-gaps', help='audit used stage material primary textures using native matbounds')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.add_argument('--asset', action='append', required=True, help='relative stage SMD; repeat to audit multiple')
    x.add_argument('--execute', action='store_true')
    x.add_argument('--build', action='store_true')
    x.add_argument('--strict', action='store_true', help='nonzero exit when used textures missing')
    x.set_defaults(func=run)
