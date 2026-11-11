"""P1/04: quality evidence ledger for SMD, SMB, INX and .part candidates.

Never confuses reader acceptance or structural GLB inspection with in-game
rendering, animation, collision, audio, or particle fidelity.
"""
from __future__ import annotations
import json
import pathlib
from typing import Any
from . import etervale_integration as bridge


def classify_native(suffix: str, output: str) -> dict:
    result = {'geometry': 'NOT_TESTED', 'materials': 'NOT_TESTED',
              'textures': 'NOT_TESTED', 'animation': 'NOT_TESTED',
              'collision': 'NOT_TESTED', 'effects': 'NOT_TESTED',
              'runtime_visual': 'NOT_CERTIFIED'}
    if suffix == '.smd':
        result['geometry'] = 'CSHARP_READER_ACCEPTED'
        result['materials'] = 'CSHARP_READER_INSPECTED' if '-- MATERIAL AGGREGATES --' in output else 'NOT_TESTED'
        if 'collision faces :' in output:
            result['collision'] = 'COLLISION_FACE_COUNT_READ_NOT_PHYSICS_TESTED'
    elif suffix == '.smb':
        result['animation'] = 'SMB_SERIALIZED_READER_ACCEPTED_NOT_PLAYBACK_TESTED'
    elif suffix == '.inx':
        result['animation'] = 'INX_MOTION_TABLE_ACCEPTED_NOT_PLAYBACK_TESTED'
    return result


def run(a: Any) -> int:
    root = bridge._game_root(a)
    if a.build and not a.execute:
        raise ValueError('BUILD_REQUIRES_EXECUTE')
    path = bridge._input_path(root, a.asset, a.candidate, {'.smd', '.smb', '.inx', '.part'})
    suffix = path.suffix.lower()
    report = {'format': 'PT_ASSET_ETERVALE_QUALITY_GATES_V1', 'file': str(path),
              'sha256': bridge._hash_file(path), 'kind': suffix,
              'game_assets_modified': False, 'proof_level': 'OFFLINE_AND_CSHARP_READER_ONLY',
              'quality': classify_native(suffix, ''), 'status': 'PLANNED'}
    if a.execute:
        if suffix == '.part':
            # Read-only basic viability, intentionally no claim of VFX runtime parser certification.
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError('PART_TOO_LARGE_FOR_SAFE_READ')
            sample = path.read_bytes()
            report['effects'] = {'bytes': len(sample), 'zero_bytes': sample.count(b'\0'),
                                  'not_empty': bool(sample), 'native_part_reader': 'NOT_AVAILABLE_IN_ASSETDUMP'}
            report['status'] = 'STATIC_PART_INSPECTION_ONLY' if sample else 'FAILED_EMPTY_PART'
        else:
            native = bridge._run_game_tool(root, bridge._csproj(root, 'inspect'),
                                           [str(path), '--full'], build=a.build)
            report['reader_exit_code'] = native['exit_code']
            text = '\n'.join(step['stdout_tail'] for step in native['steps'])
            report['quality'] = classify_native(suffix, text) if native['exit_code'] == 0 else report['quality']
            report['status'] = 'READER_ACCEPTED_NOT_RUNTIME_CERTIFIED' if native['exit_code'] == 0 else 'READER_FAILED'
        report['source_unchanged'] = bridge._hash_file(path) == report['sha256']
        if not report['source_unchanged']:
            report['status'] = 'SOURCE_CHANGED'
    if a.texture_report:
        evidence_path = pathlib.Path(a.texture_report).resolve(strict=True)
        if not bridge._which_candidate_root(evidence_path):
            raise ValueError('TEXTURE_EVIDENCE_MUST_BE_UNDER_PT_BUILD')
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        count = evidence.get('missing_or_invalid_texture_count')
        report['texture_evidence'] = {'report': str(evidence_path), 'fallbacks': count,
                                      'coverage': evidence.get('texture_diagnostic_status'),
                                      'status': evidence.get('status')}
        report['quality']['textures'] = ('MISSING_TEXTURES' if isinstance(count,int) and count else
                                          'EXPORT_COVERAGE_NO_FALLBACKS' if count == 0 else 'COVERAGE_UNKNOWN')
    report['report_file'] = bridge._write_report('quality', report)
    bridge._print(report)
    return 3 if report['status'] in ('SOURCE_CHANGED', 'READER_FAILED', 'FAILED_EMPTY_PART') or (
        a.strict and (report['quality']['textures'] in ('MISSING_TEXTURES','COVERAGE_UNKNOWN') or
                      suffix == '.part' or report['status'] == 'PLANNED')) else 0


def register(sp):
    x = sp.add_parser('quality-check', help='record per-domain offline/native evidence; never claim runtime certification')
    x.add_argument('--repo-root', type=pathlib.Path)
    y=x.add_mutually_exclusive_group(required=True)
    y.add_argument('--asset', help='relative to Etervale assets')
    y.add_argument('--candidate', help='absolute under Asset Tool pt_build')
    x.add_argument('--texture-report', type=pathlib.Path, help='GLB export JSON evidence under pt_build')
    x.add_argument('--execute', action='store_true')
    x.add_argument('--build', action='store_true')
    x.add_argument('--strict', action='store_true')
    x.set_defaults(func=run)
