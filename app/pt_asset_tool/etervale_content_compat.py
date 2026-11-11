"""P0/02: Summit legacy content compatibility inventory; never change C# readers.

Etervale's authoritative content path is GameServer -> WorldImport -> persistence,
not Summit binary packs. This patch emits a human-reviewed adaptation plan.
"""
from __future__ import annotations
import json
import pathlib
from typing import Any
from . import etervale_integration as bridge
from .data_type_tools import FORMAT_SPECS

DOMAINS = {
    'SCFG': ('OpenItem/Monster/NPC', 'WorldImport', 'GameServer text definitions', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SMAP': ('Field', 'Shared/PristonTale.Simulation/World', 'WorldCatalog + stage paths', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SRES': ('NPC', 'Translations/pt-BR.json', 'world importer localization', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SFLD': ('Field', 'Parsers/SpmParser.cs', 'SPM/SPP/SPC + world field catalog', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SGCF': ('Shared', 'WorldCatalog', 'gameplay config and simulation contracts', 'NO_DIRECT_BINARY_LOADER'),
    'SGRF': ('Shared', 'Simulation', 'gameplay reference contracts', 'NO_DIRECT_BINARY_LOADER'),
    'SCSP': ('NPC', 'Importer.Npcs.cs', 'NPC shop source definitions', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SSKM': ('Shared', 'Simulation', 'skin reform/data contract', 'NO_DIRECT_BINARY_LOADER'),
    'SSPB': ('Field', 'Parsers/SppReader.cs', 'spawn point records', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SLOC': ('Translations', 'Translations/pt-BR.json', 'localization source records', 'MANUAL_SCHEMA_MAPPING_REQUIRED'),
    'SCTB': ('GameServer', 'WorldImport', 'text-authoring source records', 'NO_DIRECT_BINARY_LOADER'),
}


def inventory_content(root: pathlib.Path, *, limit: int = 20000) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('CONTENT_ROOT_MUST_BE_DIRECTORY')
    counts: dict[str, int] = {}
    sample: dict[str, list[str]] = {}
    total = 0
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        total += 1
        if total > limit:
            raise ValueError('CONTENT_INVENTORY_LIMIT_EXCEEDED')
        suffix = path.suffix.lower() or '(no extension)'
        counts[suffix] = counts.get(suffix, 0) + 1
        rows = sample.setdefault(suffix, [])
        if len(rows) < 3:
            rows.append(path.relative_to(root).as_posix())
    return {'root': str(root), 'total_files': total, 'extensions': counts, 'samples': sample}


def run(a: Any) -> int:
    root = bridge._game_root(a)
    game_server = root/'assets'/'GameServer'
    imported = root/'tools'/'PristonTale.WorldImport'
    rows = []
    for key, spec in sorted(FORMAT_SPECS.items()):
        kind = key.upper()
        target, owner, description, gap = DOMAINS[kind]
        rows.append({'legacy_pack': kind, 'extension': spec.extension,
                     'etervale_authoring_area': target, 'owner_contract': owner,
                     'target_description': description, 'compatibility': 'NO_DIRECT_READER',
                     'adaptation': gap, 'allow_direct_publish': False})
    evidence = {'world_import_project': (imported/'PristonTale.WorldImport.csproj').is_file(),
                'item_parser': (imported/'Parsers'/'ItemTxtParser.cs').is_file(),
                'monster_parser': (imported/'Parsers'/'MonsterInfParser.cs').is_file(),
                'npc_parser': (imported/'Parsers'/'NpcParser.cs').is_file(),
                'field_spm_parser': (imported/'Parsers'/'SpmParser.cs').is_file(),
                'field_spp_reader': (imported/'Parsers'/'SppReader.cs').is_file(),
                'field_spc_reader': (imported/'Parsers'/'SpcReader.cs').is_file(),
                'game_server_root': game_server.is_dir()}
    report = {'format': 'PT_ASSET_ETERVALE_CONTENT_COMPAT_V1', 'game_root': str(root),
              'status': 'ADAPTATION_REQUIRED_NO_READER_CHANGE', 'legacy_formats': rows,
              'etervale_contract_evidence': evidence, 'game_assets_modified': False,
              'reader_changes': 'FORBIDDEN_IN_THIS_PATCH',
              'database_import': 'NOT_RUN:WorldImport import mutates catalog database',
              'runtime_compatible_packs': [],
              'proof_level': 'CONTRACT_DISCOVERY_ONLY_NOT_DATA_CONVERSION'}
    if a.content_root:
        report['legacy_content_inventory'] = inventory_content(pathlib.Path(a.content_root))
    report['report_file'] = bridge._write_report('content_compat', report)
    bridge._print(report)
    return 0 if all(evidence.values()) else 3



# JSON authoring for the CURRENT native Etervale source format (not Summit packs).
# Produces editable text drafts in pt_build, never in assets/GameServer.
ALLOWED_NATIVE_TARGETS = {'OpenItem': '.txt', 'Monster': '.inf', 'NPC': '.npc', 'Field': '.spm'}

def _literal(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('DIRECTIVE_VALUE_MUST_BE_STRING_OR_NUMBER')
    result = str(value)
    if any(ch in result for ch in ('\r', '\n', '\x00', '"')):
        raise ValueError('DIRECTIVE_VALUE_UNSAFE_CHARACTER')
    if any(c.isspace() for c in result):
        return '"' + result + '"'
    return result


def compile_native_draft(spec: dict, work_root: pathlib.Path) -> dict:
    import re
    import uuid
    if spec.get('format') != 'PT_ASSET_ETERVALE_NATIVE_AUTHORING_V1':
        raise ValueError('NATIVE_AUTHORING_FORMAT_REQUIRED')
    files = spec.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 50:
        raise ValueError('NATIVE_AUTHORING_1_TO_50_FILES_REQUIRED')
    plans=[]
    paths=set()
    for item in files:
        if not isinstance(item,dict): raise ValueError('NATIVE_AUTHORING_FILE_OBJECT_REQUIRED')
        rel=pathlib.PurePosixPath(str(item.get('path','')).replace('\\','/'))
        if (rel.is_absolute() or len(rel.parts)!=2 or '..' in rel.parts or
            rel.parts[0] not in ALLOWED_NATIVE_TARGETS or
            rel.suffix.lower()!=ALLOWED_NATIVE_TARGETS[rel.parts[0]] or
            not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',rel.name)):
            raise ValueError('UNSUPPORTED_ETERVALE_NATIVE_AUTHORING_PATH')
        if rel.as_posix().casefold() in paths:
            raise ValueError('DUPLICATE_NATIVE_DRAFT_PATH')
        paths.add(rel.as_posix().casefold())
        directives=item.get('directives')
        if not isinstance(directives,list) or not 1 <= len(directives) <= 500:
            raise ValueError('NATIVE_AUTHORING_DIRECTIVES_REQUIRED')
        lines=[]
        for d in directives:
            if not isinstance(d,dict):raise ValueError('DIRECTIVE_OBJECT_REQUIRED')
            key=str(d.get('key',''))
            if (not key.startswith('*') or len(key)>80 or
                any(ch.isspace() or ch in ('\x00','"') for ch in key) or
                key.casefold() in ('*연결파일','**연결파일')):
                raise ValueError('DIRECTIVE_KEY_UNSAFE_OR_LINKED_FILE_FORBIDDEN')
            values=d.get('values',[])
            if not isinstance(values,list) or len(values)>32:
                raise ValueError('DIRECTIVE_VALUES_LIST_REQUIRED')
            lines.append(' '.join([key,*(_literal(value) for value in values)]))
        raw=('\r\n'.join(lines)+'\r\n').encode('cp949')
        plans.append((rel,raw))
    destination=work_root/'native_content' / uuid.uuid4().hex
    destination.mkdir(parents=True,exist_ok=False)
    outputs=[]
    for rel,raw in plans:
        out=destination.joinpath(*rel.parts)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(raw)
        outputs.append({'path':str(out),'relative_path':rel.as_posix(),
                        'sha256':bridge._hash_file(out),'bytes':len(raw)})
    report={'format':'PT_ASSET_ETERVALE_NATIVE_DRAFT_V1',
            'status':'DRAFT_WRITTEN_NOT_IMPORT_CERTIFIED',
            'outputs':outputs,'game_assets_modified':False,
            'world_import_execution':'NOT_RUN',
            'limitations':['syntax and encoding only; identities, relationships and gameplay require native importer verification',
                           'not a Summit pack converter']}
    manifest=destination/'manifest.json'
    manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report['manifest']=str(manifest)
    return report


def native_draft(a: Any) -> int:
    root=bridge._game_root(a)
    spec=json.loads(pathlib.Path(a.spec).expanduser().resolve(strict=True).read_text(encoding='utf-8'))
    if not isinstance(spec,dict):raise ValueError('NATIVE_AUTHORING_JSON_OBJECT_REQUIRED')
    report=compile_native_draft(spec,bridge._work_root())
    report['game_root']=str(root)
    bridge._print(report)
    return 0

def register(sp):
    x = sp.add_parser('content-compat', help='map Summit packs to Etervale authoring contracts without reader changes')
    x.add_argument('--repo-root', type=pathlib.Path)
    x.add_argument('--content-root', type=pathlib.Path, help='optional legacy Content directory to inventory read-only')
    x.set_defaults(func=run)
    x=sp.add_parser('content-draft', help='compile typed JSON to native Etervale GameServer TEXT drafts in pt_build')
    x.add_argument('--repo-root',type=pathlib.Path)
    x.add_argument('--spec',required=True,type=pathlib.Path)
    x.set_defaults(func=native_draft)
