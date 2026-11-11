"""Read-only census of Asset Tool modules and Etervale root-routing contracts.

Static inspection is an inventory, not a claim that every legacy user workflow
runs on a MonoGame checkout. Results are never used as publication approval.
"""
from __future__ import annotations

import ast
import argparse
import re
import csv
import hashlib
import io
import json
import pathlib
from collections import Counter
from typing import Any

from . import etervale_integration as bridge
from . import app_config
from .runtime_paths import bundle_root

FORMAT='PT_ASSET_ETERVALE_MIGRATION_LEGACY_AUDIT_V1'
LEGACY_DIRS={'legacy_data_tools','legacy_apps','legacy_runtime'}
HISTORICAL_ACTIVE={
    'summit_canonical','summit_asset_migration_audit','canonical_authoring',
    'legacy_authoring','asset_compiler','asset_bundle_deploy','legacy_management_audit',
    'legacy_management_contracts','donor_recovery_explorer','general_asset_recovery',
    'workspace_bundle_deploy','asset_quarantine','asset_retention',
}
ROOT_ROUTING={'config','app_config','cli','data_type_tools','runtime_paths'}
MUTATION_CALLS={
    'write_bytes','write_text','unlink','rmtree','replace','copy','copy2',
    'move','rename','mkdir','makedirs','remove','Popen','run','check_call',
}
LEGACY_MARKERS=('summit tale client full','summit tale server','summit.sqlite',
                'legacy_parent_layout','sibling_summit_layout','/servidor/',
                'summit_content')


def _classification(rel:pathlib.Path)->str:
    if LEGACY_DIRS.intersection(rel.parts):return 'HISTORICAL_ISOLATED_NOT_NATIVE'
    if rel.stem in HISTORICAL_ACTIVE:return 'ACTIVE_LEGACY_WORKFLOW_REVIEW_REQUIRED'
    if rel.stem in ROOT_ROUTING:return 'SHARED_ROOT_ROUTING'
    if rel.stem.startswith('etervale_'):return 'ETERVALE_NATIVE_BRIDGE_SCOPE'
    return 'SHARED_OR_GENERIC_NOT_END_TO_END_CERTIFIED'


def _module_row(path:pathlib.Path,root:pathlib.Path)->dict:
    raw=path.read_bytes()
    rel=path.relative_to(root)
    row={'path':rel.as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),
         'bytes':len(raw),'classification':_classification(rel),
         'syntax':'PASS','legacy_literal_lines':[],'mutation_call_names':[],
         'compatibility':'NOT_INFERRED_FROM_STATIC_SCAN'}
    try:
        tree=ast.parse(raw.decode('utf-8-sig'),filename=str(path))
    except (UnicodeError,SyntaxError,ValueError) as exc:
        row['syntax']='ERROR_'+type(exc).__name__
        return row
    flags=set();mutation=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            low=node.value.casefold()
            if any(marker in low for marker in LEGACY_MARKERS):flags.add(node.lineno)
        if isinstance(node,ast.Call):
            fn=node.func
            name=fn.attr if isinstance(fn,ast.Attribute) else fn.id if isinstance(fn,ast.Name) else ''
            if name in MUTATION_CALLS:mutation.add(name)
    row['legacy_literal_lines']=sorted(flags)[:120]
    row['mutation_call_names']=sorted(mutation)
    return row


def _root_routing(project_root:pathlib.Path, game_root:pathlib.Path|None)->dict:
    result={'configured_root':None,'provided_root':str(game_root) if game_root else None,
            'client_root':None,'server_root':None,'client_source':None,'server_source':None,
            'status':'NOT_CHECKED_NO_GAME_ROOT','diagnostics':[]}
    try:
        configured=app_config.configured_etervale_root(project_root)
        result['configured_root']=str(configured) if configured else None
        if configured is None:
            result['status']='ETERVALE_ROOT_NOT_CONFIGURED'
            return result
        valid=app_config.validate_etervale_root(configured)
        client,source1=app_config.resolve_client_root(project_root)
        server,source2=app_config.resolve_server_root(project_root)
        result.update(client_root=str(client),server_root=str(server),
                      client_source=source1,server_source=source2)
        good=(client==valid/'assets' and server==valid/'assets'/'GameServer' and
              source1=='ETERVALE_UNIFIED_ASSETS' and source2=='ETERVALE_UNIFIED_GAMESERVER')
        if game_root is not None and valid.resolve()!=game_root.resolve():
            result['diagnostics'].append('CONFIGURED_ROOT_DIFFERS_FROM_EXPLICIT_REPO_ROOT')
            good=False
        result['status']='PASS_UNIFIED_ASSET_ROOT_ROUTING' if good else 'REVIEW_ROOT_ROUTING_MISMATCH'
    except (ValueError,OSError,FileNotFoundError) as exc:
        result['status']='REVIEW_ROOT_ROUTING_ERROR'
        result['diagnostics'].append(type(exc).__name__+':'+str(exc))
    return result


def audit(code_root:pathlib.Path, project_root:pathlib.Path,game_root:pathlib.Path|None=None)->dict:
    code_root=code_root.resolve(strict=True)
    targets=sorted(p for p in code_root.rglob('*.py') if p.is_file() and not p.is_symlink()
                   and '__pycache__' not in p.parts and 'pt_build' not in p.parts)
    rows=[_module_row(p,code_root) for p in targets]
    counts=dict(sorted(Counter(x['classification'] for x in rows).items()))
    syntax_failures=[r['path'] for r in rows if r['syntax']!='PASS']
    old_literals=[r['path'] for r in rows if r['legacy_literal_lines']]
    legacy_active=[r['path'] for r in rows if r['classification']=='ACTIVE_LEGACY_WORKFLOW_REVIEW_REQUIRED']
    routing=_root_routing(project_root,game_root)
    return {'format':FORMAT,'status':'AUDIT_COMPLETED_WITH_EXPLICIT_LEGACY_BOUNDARIES'
            if not syntax_failures else 'AUDIT_COMPLETED_WITH_SYNTAX_ERRORS',
            'scope':'SOURCE_STATIC_CENSUS_AND_UNIFIED_ROOT_ROUTING',
            'scanned_python_files':len(rows),'classification_counts':counts,
            'syntax_errors':syntax_failures,'legacy_literal_module_count':len(old_literals),
            'legacy_literal_modules':old_literals,'active_legacy_review_required':legacy_active,
            'root_routing':routing,'modules':rows,
            'legacy_runtime_pack_policy':'DO_NOT_PUBLISH_SUMMIT_PACKS_AS_ETERVALE_NATIVE',
            'unknown_modules_are_runtime_certified':False,
            'all_ui_commands_tested':False,
            'content_json_integration':'FUTURE_SEPARATE_PROJECT_NOT_IMPLEMENTED',
            'game_assets_modified':False,
            'limitations':[
                'AST census detects literals and operations, not behavior of each UI command',
                'Active legacy publisher modules remain subject to a later UI/operation audit',
                'New Etervale runtime assets must pass native reader/WorldImport proofs',
                'No gameplay rendering, database mutation or full-module execution was performed',
            ]}


def _csv_bytes(rows:list[dict])->bytes:
    stream=io.StringIO()
    writer=csv.DictWriter(stream,fieldnames=['path','classification','syntax','bytes',
                                              'legacy_literal_lines','mutation_call_names','sha256'])
    writer.writeheader()
    for row in rows:
        writer.writerow({k:json.dumps(row[k],ensure_ascii=False) if isinstance(row[k],list) else row[k]
                         for k in writer.fieldnames})
    return stream.getvalue().encode('utf-8-sig')


def _surface_inventory(code_root:pathlib.Path)->dict:
    # Parser construction is introspection only; no subcommand is executed.
    from . import cli
    parser=cli.build_parser()
    names=[]
    def walk(p:argparse.ArgumentParser,prefix:str=''):
        for action in p._actions:
            if isinstance(action,argparse._SubParsersAction):
                for name,sub in action.choices.items():
                    label=(prefix+' '+name).strip()
                    names.append(label)
                    walk(sub,label)
    walk(parser)
    routes=set()
    app_ui=code_root/'ui_app.py'
    if app_ui.is_file():
        routes.update(re.findall(r'/api/[a-zA-Z0-9/_-]+',app_ui.read_text(encoding='utf-8',errors='replace')))
    static=code_root/'ui_static'
    if static.is_dir():
        for f in static.rglob('*'):
            if f.is_file() and f.suffix.lower() in {'.html','.js'}:
                routes.update(re.findall(r'/api/[a-zA-Z0-9/_-]+',f.read_text(encoding='utf-8',errors='replace')))
    return {'cli_command_paths':sorted(set(names)), 'cli_command_count':len(set(names)),
            'ui_api_route_literals':sorted(routes),'ui_api_route_literal_count':len(routes),
            'coverage':'REGISTERED_COMMANDS_AND_TEXTUAL_ENDPOINTS_ONLY_NOT_EXECUTION'}


def run(a:Any)->int:
    game=bridge._game_root(a)
    project=bundle_root()
    report=audit(project/'pt_asset_tool',project,game)
    # Store complete per-module manifest separately; only a compact summary to CLI.
    rows=report.pop('modules')
    surfaces=_surface_inventory(project/'pt_asset_tool')
    report['surface_inventory']={'cli_command_count':surfaces['cli_command_count'],
                                'ui_api_route_literal_count':surfaces['ui_api_route_literal_count'],
                                'coverage':surfaces['coverage']}
    outdir=bridge._work_root()/'migration_audit'
    outdir.mkdir(parents=True,exist_ok=True)
    import uuid
    tag=uuid.uuid4().hex
    manifest_file=outdir/(tag+'.modules.json')
    csv_file=outdir/(tag+'.modules.csv')
    manifest_file.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    csv_file.write_bytes(_csv_bytes(rows))
    surfaces_file=outdir/(tag+'.surfaces.json')
    surfaces_file.write_text(json.dumps(surfaces,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    report['surfaces_file']=str(surfaces_file)
    report['manifest_file']=str(manifest_file)
    report['csv_file']=str(csv_file)
    report['report_file']=bridge._write_report('migration_audit',report)
    bridge._print(report)
    return 0 if not report['syntax_errors'] and report['root_routing']['status']=='PASS_UNIFIED_ASSET_ROOT_ROUTING' else 3


def register(sp:Any)->None:
    p=sp.add_parser('legacy-migration-audit',help='scan Python modules and verify unified root routing without executing legacy workflows')
    p.add_argument('--repo-root',type=pathlib.Path,help='optional Etervale game repository root; must match configured root')
    p.set_defaults(func=run)
