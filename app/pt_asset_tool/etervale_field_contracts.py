"""P1/05: read-only SPM/SPP/SPC audits based on existing Asset Tool codecs and C# layouts.

WorldImport import modifies a database and is deliberately not invoked.
"""
from __future__ import annotations
import pathlib
import struct
from typing import Any
from . import etervale_integration as bridge
from .server_field_editor import _inspect_spm, _inspect_spp, _inspect_spc, SPP_FILE_SIZE, SPC_FILE_SIZE


def inspect_bytes(ext: str, raw: bytes) -> dict:
    if ext == '.spm':
        detail = _inspect_spm(raw)
        return {'kind': 'SPM', 'status': 'PASS', 'directives': detail['directives'],
                'spawn_actor_references': detail['actors'], 'encoding': detail['encoding'],
                'limitations': ['C# importer semantic parsing not executed']}
    if ext == '.spp':
        detail = _inspect_spp(raw)
        return {'kind': 'SPP', 'status': detail['status'], 'bytes': len(raw),
                'expected_bytes': SPP_FILE_SIZE, 'active_count': detail.get('active_count'),
                'csharp_layout': '200 × 12-byte records (state,x,z)'}
    if ext == '.spc':
        detail = _inspect_spc(raw)
        # C# SpcReader uses +4 as the live flag and +104..164 as NPC path.
        # The old editor uses +4 as an op code. Both are nonzero in shipped rows,
        # but it is unsafe to assume the semantics are identical in all files.
        active_csharp = sum(struct.unpack_from('<i', raw, i*504 + 4)[0] != 0
                            for i in range(min(len(raw)//504, 100)))
        return {'kind': 'SPC', 'status': detail['status'], 'bytes': len(raw),
                'expected_bytes': SPC_FILE_SIZE,
                'active_csharp_rows': active_csharp,
                'active_asset_tool_rows': detail.get('runtime_active_count'),
                'csharp_layout': '100 × 504-byte records; NPC path at +104; XYZ at +476',
                'limitations': ['C# WorldImport parser not executed',
                                'opcode semantics and NPC definition resolution require live import verification']}
    raise ValueError('FIELD_EXTENSION_NOT_SUPPORTED')


def run(a: Any) -> int:
    root = bridge._game_root(a)
    if not 1 <= len(a.asset) <= 300:
        raise ValueError('REQUIRE_1_TO_300_FIELD_PATHS')
    game_server = (root/'assets'/'GameServer').resolve(strict=True)
    rows=[]
    for rel in a.asset:
        req=pathlib.PurePosixPath(rel.replace('\\', '/'))
        if req.is_absolute() or '..' in req.parts or req.suffix.lower() not in ('.spm','.spp','.spc'):
            raise ValueError('FIELD_PATH_MUST_BE_RELATIVE_SPM_SPP_SPC')
        # Exact or unambiguous case-insensitive segment lookup, no symlink escape.
        current = game_server
        for segment in req.parts:
            matches = [p for p in current.iterdir() if p.name.casefold() == segment.casefold()]
            if len(matches) != 1:
                raise FileNotFoundError(f'FIELD_NOT_FOUND_OR_AMBIGUOUS:{rel}')
            current = matches[0]
        path = current.resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(game_server):
            raise ValueError('FIELD_PATH_ESCAPE')
        raw=path.read_bytes()
        row=inspect_bytes(req.suffix.lower(), raw)
        row.update({'source': str(path), 'relative_path': req.as_posix(),
                    'sha256': bridge._hash_file(path)})
        rows.append(row)
    bad=[r for r in rows if r['status']!='PASS']
    report={'format':'PT_ASSET_ETERVALE_FIELD_CONTRACTS_V1', 'game_root':str(root),
            'status':'REVIEW_REQUIRED' if bad else 'PASS_STRUCTURAL_ONLY',
            'count':len(rows), 'blocked_count':len(bad), 'files':rows,
            'runtime_verification':'NOT_RUN:WorldImport import mutates a database',
            'game_assets_modified':False}
    report['report_file']=bridge._write_report('fields',report)
    bridge._print(report)
    return 3 if bad else 0


def register(sp):
    x=sp.add_parser('field-check', help='inspect SPM/SPP/SPC contracts read-only; no world DB import')
    x.add_argument('--repo-root',type=pathlib.Path)
    x.add_argument('--asset',action='append',required=True,help='relative to assets/GameServer; repeat')
    x.set_defaults(func=run)
