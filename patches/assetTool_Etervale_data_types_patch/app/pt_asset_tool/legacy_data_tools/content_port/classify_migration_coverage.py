#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path
from canonicalize_text_content import is_selected, MUTABLE_OR_MIXED_CONFIGS, norm


def classify(doc: dict) -> tuple[str, str]:
    selected, reason = is_selected(doc)
    if selected:
        return 'MIGRATED_CANONICAL_JSON', reason
    kind = doc.get('kind','')
    path = norm(doc.get('source',{}).get('path',''))
    low = path.casefold()
    if kind == 'stage_spawn':
        return 'MIGRATED_STAGE_SPAWN_JSON', 'compiled_to_sspb'
    if low in MUTABLE_OR_MIXED_CONFIGS:
        return 'KEEP_OPERATIONAL_TEXT', MUTABLE_OR_MIXED_CONFIGS[low]
    if kind == 'model_config_text':
        return 'KEEP_ASSET_METADATA', 'model_pipeline_out_of_scope'
    if kind == 'lua_script':
        return 'KEEP_SCRIPT_ASSET', 'effect_script_out_of_scope'
    if kind in {'npc_auxiliary','open_item_auxiliary','monster_auxiliary'}:
        return 'IGNORE_FILESYSTEM_METADATA', 'desktop_ini_or_auxiliary'
    if kind == 'ini_config':
        if low in {'cliente/game.ini','cliente/settings.ini'} or '/savedata/' in low:
            return 'KEEP_OPERATIONAL_TEXT', 'mutable_user_or_runtime_state'
        if low.startswith('servidor/') and any(x in low for x in ('configrestarter.ini','banned.ini','/management/','/toplevel/','/configs/welcome.ini')):
            return 'KEEP_OPERATIONAL_TEXT', 'deployment_or_admin_config'
        if '/effect/' in low or '/char/' in low or '/field/' in low or '/image/' in low or '/cselect/' in low:
            return 'KEEP_ASSET_METADATA', 'render_model_effect_metadata'
        return 'KEEP_OPERATIONAL_TEXT', 'non_content_ini'
    if kind == 'generic_text':
        if '/savedata/' in low:
            return 'KEEP_PERSISTENCE_STATE', 'runtime_state_out_of_scope'
        if any(x in low for x in ('ptprotector','_pt_protector','pritator.config')):
            return 'KEEP_OPERATIONAL_TEXT', 'security_or_admin_config'
        if any(x in low for x in ('trace.txt','runtime_info.txt','xphex','cssandurr')):
            return 'KEEP_DIAGNOSTIC_ARTIFACT', 'debug_or_diagnostic_output'
        if low.endswith('.zif'):
            return 'KEEP_OPAQUE_ASSET', 'asset_file_misclassified_as_text'
        if '/effect/' in low or '/field/' in low or '/game/maps/' in low:
            return 'KEEP_ASSET_METADATA', 'render_or_field_asset_metadata'
        if low.endswith(('map.txt','_update.inf','assaloadingfile.txt','cooked/manifest.json')):
            return 'KEEP_BUILD_ARTIFACT', 'build_or_distribution_artifact'
        return 'REVIEW_NON_CONTENT_TEXT', 'no_active_gameplay_consumer_identified'
    return 'REVIEW_UNCLASSIFIED', kind or 'unknown'


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--shadow',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    root=a.shadow.resolve(); idx=json.loads((root/'index.json').read_text(encoding='utf-8'))['documents']
    rows=[]; counts=Counter(); reasons=Counter(); examples=defaultdict(list)
    for e in idx:
        d=json.loads((root/e['json_path']).read_text(encoding='utf-8'))
        status,reason=classify(d); path=d['source']['path']; kind=d['kind']
        counts[status]+=1; reasons[(status,reason)]+=1
        if len(examples[status])<20: examples[status].append(path)
        rows.append({'path':path,'kind':kind,'status':status,'reason':reason})
    unresolved=[r for r in rows if r['status'].startswith('REVIEW_')]
    report={
        'schema':'summit.text-migration-coverage/v1','source_documents':len(rows),
        'status_counts':dict(sorted(counts.items())),
        'reason_counts':[{'status':s,'reason':r,'count':n} for (s,r),n in sorted(reasons.items())],
        'unresolved_count':len(unresolved),'unresolved':unresolved,
        'examples':dict(examples),'documents':rows,
    }
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'documents':len(rows),'status_counts':dict(counts),'unresolved_count':len(unresolved)},ensure_ascii=False))
    if unresolved: raise SystemExit(2)
if __name__=='__main__': main()
