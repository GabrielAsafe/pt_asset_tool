"""P0/01: stage authored writer candidates and probe with native Etervale readers.

No game asset mutation, no implicit publishing, no false runtime claims.
"""
from __future__ import annotations
import json
import pathlib
import uuid
from typing import Any
from . import etervale_integration as bridge


def _stage_payload() -> dict:
    return {'materials': [], 'vertices': [[0, 0, 0], [64, 0, 0], [0, 0, 64]],
            'faces': [{'vertices': [0, 2, 1], 'material': 0}], 'area_mode': 'NONE'}


def generate(mode: str, game_root: pathlib.Path, source: str | None,
             work_root: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """Use the actual writers; never just copy a source and call it a writer test."""
    from .runtime_paths import bundle_root
    work_root.mkdir(parents=True, exist_ok=True)
    if mode == 'model':
        if source:
            raise ValueError('MODEL_PROBE_USES_SYNTHETIC_FIXTURE_NO_SOURCE')
        from .model062_static_compiler import compile_static_model062
        from .static_roundtrip import _parse
        payload = {'mesh': {'materials': [{'textures': []}], 'objects': [{'name':'probe',
                   'vertices': [[0,0,0],[1,0,0],[0,1,0]],
                   'faces': [{'vertices':[0,1,2], 'material':0}]}]}}
        dest = work_root / 'model062-native.smd'
        raw, metadata = compile_static_model062(payload)
        dest.write_bytes(raw)
        parsed = _parse(raw)
        if parsed['n'] != 1 or parsed['mat_count'] != 1:
            raise ValueError('MODEL_WRITER_SELF_ROUNDTRIP_FAILED')
        return dest, {'writer': metadata.get('writer'), 'self_roundtrip': 'PASS',
                      'synthetic_geometry_only': True, 'texture_required': False}
    if mode == 'stage':
        if source:
            raise ValueError('STAGE_PROBE_USES_SYNTHETIC_FIXTURE_NO_SOURCE')
        from .stage072_compiler import compile_stage072
        from .stage072_corpus import parse_stage072
        dest = work_root / 'stage072-native.smd'
        raw, metadata = compile_stage072(_stage_payload())
        dest.write_bytes(raw)
        parsed = parse_stage072(dest)
        if parsed['full_parse'] != 'PASS' or parsed['counts']['faces'] != 1:
            raise ValueError('STAGE_WRITER_SELF_ROUNDTRIP_FAILED')
        return dest, {'writer': metadata.get('writer'), 'self_roundtrip': 'PASS',
                      'synthetic_geometry_only': True, 'texture_required': False}
    if not source:
        raise ValueError('SOURCE_ASSET_REQUIRED_FOR_INX_OR_SMB')
    suffix = { 'inx': '.inx', 'smb': '.smb' }[mode]
    selected = bridge._input_path(game_root, source, None, {suffix})
    dest = work_root / ('edited-' + selected.name)
    if mode == 'inx':
        from .inx_writer import patch_motion
        import pt_inx_motion_core_v2 as core
        parsed = core.parse_inx(selected)
        motions = list(parsed.get('motions') or [])
        if not motions:
            raise ValueError('INX_NO_EDITABLE_MOTIONS')
        motion = next((m for m in motions if int(m['repeat']) in (0, 1)), motions[0])
        updated = (int(motion['repeat']) ^ 1) if int(motion['repeat']) in (0, 1) else int(motion['repeat']) + 1
        evidence = patch_motion(selected, dest, motion=int(motion['index']), repeat=updated)
    else:
        from .smb_writer import patch_key, first_editable_key
        key = first_editable_key(bundle_root(), selected)
        if key is None:
            raise ValueError('SMB_NO_EXISTING_EDITABLE_TRACK')
        if key['track'] == 'scale':
            desired = {'x': int(key['values'][0]) + 1}
        else:
            desired = {'x': float(key['values'][0]) + 0.5}
        evidence = patch_key(bundle_root(), selected, dest, bone=key['bone'],
                             track=key['track'], key_index=key['key_index'], **desired)
    if evidence.get('status') != 'PASS' or not evidence.get('allowed_offsets_only', True):
        raise ValueError('WRITER_SEMANTIC_GATE_FAILED')
    return dest, evidence


def run(a: Any) -> int:
    root = bridge._game_root(a)
    if a.build and not a.execute:
        raise ValueError('BUILD_REQUIRES_EXECUTE')
    mode = a.mode
    run_dir = bridge._work_root() / 'writer_probes' / uuid.uuid4().hex
    candidate, writer_evidence = generate(mode, root, a.source, run_dir)
    hash_before = bridge._hash_file(candidate)
    project = bridge._csproj(root, 'inspect')
    report = {
        'format': 'PT_ASSET_ETERVALE_WRITER_CERT_V1', 'mode': mode,
        'input': a.source, 'candidate': str(candidate), 'candidate_sha256': hash_before,
        'writer_evidence': writer_evidence, 'writer_status': 'PASS',
        'reader_status': 'NOT_RUN', 'runtime_status': 'NOT_CERTIFIED',
        'game_assets_modified': False,
        'candidate_manifest_format': 'PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1',
    }
    manifest = run_dir / 'batch.json'
    manifest.write_text(json.dumps({'format': 'PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1',
                                   'candidates': [str(candidate)]}, indent=2) + '\n')
    report['batch_manifest'] = str(manifest)
    if a.execute:
        result = bridge._run_game_tool(root, project, [str(candidate)], build=a.build)
        report['reader_result'] = result
        report['candidate_unchanged'] = hash_before == bridge._hash_file(candidate)
        report['reader_status'] = ('READER_ACCEPTED' if result['exit_code'] == 0 and report['candidate_unchanged']
                                   else 'READER_REJECTED')
    report['status'] = ('READY_FOR_NATIVE_VALIDATION' if not a.execute else
                        'READER_ACCEPTED_NOT_RUNTIME_CERTIFIED' if report['reader_status'] == 'READER_ACCEPTED' else
                        'FAILED_NATIVE_READER')
    report['report_file'] = bridge._write_report('writer_probes', report)
    bridge._print(report)
    return 3 if report['status'] == 'FAILED_NATIVE_READER' else 0


def register(sp):
    x = sp.add_parser('writer-certify', help='produce a real writer candidate and optionally validate with C# AssetDump')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.add_argument('--mode', choices=('stage', 'model', 'inx', 'smb'), required=True)
    x.add_argument('--source', help='relative asset path for existing .inx/.smb; no source for synthetic stage')
    x.add_argument('--execute', action='store_true', help='run native C# reader against staged output')
    x.add_argument('--build', action='store_true', help='build AssetDump first (requires --execute)')
    x.set_defaults(func=run)
