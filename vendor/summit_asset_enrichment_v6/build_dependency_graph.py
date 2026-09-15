#!/usr/bin/env python3
"""Build a cross client/server asset dependency graph for Summit.

The graph is intentionally evidence-oriented: it records literal references found in
files/source catalogs and marks whether the referenced target exists. It does not invent
semantic aliases.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from asset_common import CaseIndex, extract_binary_refs, extract_item_codes, extract_text_refs, load_csv, norm_key, norm_rel, read_legacy_text, write_csv

HERE = Path(__file__).resolve().parent
AUDIT = HERE / 'audit_data'

SPM_ACTOR_ALIASES = {
    '*ACTOR': 'ACTOR', '*출연자': 'ACTOR',
    '*BOSS_ACTOR': 'BOSS_ACTOR', '*출연자두목': 'BOSS_ACTOR',
}
SPM_WORD_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')


def parse_spm_actor_rows(text: str) -> List[Tuple[str, str]]:
    """Mirror DecodeOpenMonster actor tokens, including CP949 aliases.

    Actor names may be quoted and contain spaces. BOSS_ACTOR carries master and
    slave names, both of which are runtime dependencies.
    """
    out: List[Tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        token = parts[0].upper()
        kind = SPM_ACTOR_ALIASES.get(token) or SPM_ACTOR_ALIASES.get(parts[0])
        if not kind:
            continue
        rest = parts[1] if len(parts) > 1 else ''
        words = []
        for m in SPM_WORD_RE.finditer(rest):
            words.append(next((x for x in m.groups() if x is not None), ''))
        wanted = 2 if kind == 'BOSS_ACTOR' else 1
        out.extend((kind, x) for x in words[:wanted] if x)
    return out
MODEL_HINT_RE = re.compile(r'(?i)(char[\\/][^"\r\n]+?\.(?:ini|inf|inx|smd|smb|ase))')
ZHOON_RE = re.compile(r'(?i)((?:name[\\/])?[^\s"\']+\.zhoon)')


def node_id(side: str, rel: str) -> str:
    return f'{side}:{norm_rel(rel)}'


class Graph:
    def __init__(self):
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []
        self._edge_seen = set()

    def add_node(self, nid: str, **attrs):
        cur = self.nodes.setdefault(nid, {'id': nid})
        for k, v in attrs.items():
            if v not in ('', None):
                cur[k] = v

    def add_edge(self, src: str, dst: str, relation: str, evidence: str = '', exists: Optional[bool] = None, note: str = ''):
        key = (src, dst, relation, evidence)
        if key in self._edge_seen:
            return
        self._edge_seen.add(key)
        self.edges.append({'src': src, 'dst': dst, 'relation': relation, 'evidence': evidence, 'target_exists': '' if exists is None else str(bool(exists)), 'note': note})


def resolve_ref(ref: str, client_idx: CaseIndex, server_idx: CaseIndex) -> Tuple[str, bool]:
    ref = norm_rel(ref)
    low = ref.casefold()
    if low.startswith('gameserver/'):
        return node_id('server', ref), server_idx.find(ref) is not None
    if low.startswith(('char/','field/','image/','effect/','wav/','weapons/','cselect/','startimage/','res/','game/')):
        return node_id('client', ref), client_idx.find(ref) is not None
    # Server files frequently use name/foo.zhoon relative to their own folder.
    if low.endswith('.zhoon'):
        candidates = [f'GameServer/Monster/{ref}', f'GameServer/NPC/{ref}', f'GameServer/OpenItem/{ref}']
        for c in candidates:
            if server_idx.find(c):
                return node_id('server', c), True
        return node_id('server-ref', ref), False
    return node_id('ref', ref), False


def scan_server_text(graph: Graph, root: Path, idx: CaseIndex, client_idx: CaseIndex):
    roots = [root / 'GameServer' / 'Monster', root / 'GameServer' / 'NPC', root / 'GameServer' / 'OpenItem', root / 'GameServer' / 'Field']
    for base in roots:
        if not base.exists():
            continue
        for p in base.rglob('*'):
            if not p.is_file() or p.suffix.casefold() not in {'.inf','.npc','.txt','.spm','.ini','.zhoon'}:
                continue
            rel = p.relative_to(root).as_posix()
            src = node_id('server', rel)
            graph.add_node(src, side='server', path=rel, ext=p.suffix.casefold(), size=p.stat().st_size)
            try:
                text, enc = read_legacy_text(p)
            except OSError:
                continue
            graph.nodes[src]['analysis_encoding'] = enc
            for ref in extract_text_refs(p):
                dst, exists = resolve_ref(ref, client_idx, idx)
                graph.add_node(dst, path=ref)
                graph.add_edge(src, dst, 'literal_file_reference', evidence=rel, exists=exists)
            if p.suffix.casefold() == '.spm':
                for kind, actor in parse_spm_actor_rows(text):
                    dst = f'actor:{actor}'
                    graph.add_node(dst, side='semantic', name=actor, kind='spawn_actor')
                    graph.add_edge(src, dst, kind.lower(), evidence=rel)
            if '/openitem/' in ('/' + rel.casefold()):
                codes = extract_item_codes(p)
                for code in codes[:8]:
                    dst = f'item:{code}'
                    graph.add_node(dst, side='semantic', code=code, kind='item_code')
                    graph.add_edge(src, dst, 'defines_or_mentions_item_code', evidence=rel)
            if p.suffix.casefold() in {'.inf','.npc'}:
                for m in MODEL_HINT_RE.finditer(text):
                    ref = norm_rel(m.group(1))
                    dst = node_id('client', ref)
                    graph.add_node(dst, side='client', path=ref)
                    graph.add_edge(src, dst, 'server_character_model', evidence=rel, exists=client_idx.find(ref) is not None)
                for z in ZHOON_RE.findall(text):
                    dst, exists = resolve_ref(z, client_idx, idx)
                    graph.add_node(dst, path=z)
                    graph.add_edge(src, dst, 'name_resource', evidence=rel, exists=exists)


def scan_spc(graph: Graph, root: Path, server_idx: CaseIndex, client_idx: CaseIndex):
    base = root / 'GameServer' / 'Field'
    if not base.exists():
        return
    for p in base.rglob('*.spc'):
        rel = p.relative_to(root).as_posix()
        src = node_id('server', rel)
        graph.add_node(src, side='server', path=rel, ext='.spc', size=p.stat().st_size)
        for ref in extract_binary_refs(p):
            dst, exists = resolve_ref(ref, client_idx, server_idx)
            graph.add_node(dst, path=ref)
            graph.add_edge(src, dst, 'fixed_character_binary_reference', evidence=rel, exists=exists)


def scan_client(graph: Graph, root: Path, idx: CaseIndex, server_idx: CaseIndex):
    relevant = {'.ini','.inf','.inx','.smd','.smb','.ase','.part','.lua','.msg','.sin','.fnt','.fx'}
    for p in root.rglob('*') if root.exists() else []:
        if not p.is_file() or p.suffix.casefold() not in relevant:
            continue
        rel = p.relative_to(root).as_posix()
        src = node_id('client', rel)
        graph.add_node(src, side='client', path=rel, ext=p.suffix.casefold(), size=p.stat().st_size)
        try:
            refs = extract_text_refs(p) if p.suffix.casefold() in {'.ini','.inf','.ase','.part','.lua','.msg','.sin','.fnt','.fx'} else extract_binary_refs(p)
        except OSError:
            continue
        for ref in refs:
            dst, exists = resolve_ref(ref, idx, server_idx)
            if dst.startswith('ref:'):
                # Client-relative references often omit a top-level prefix. Try same directory.
                same = norm_rel(str(Path(rel).parent / ref))
                if idx.find(same):
                    dst, exists = node_id('client', same), True
            graph.add_node(dst, path=ref)
            graph.add_edge(src, dst, 'client_asset_reference', evidence=rel, exists=exists)


def add_item_catalog(graph: Graph, client_idx: CaseIndex):
    for r in load_csv(AUDIT / 'recovered_item_catalog.csv'):
        code = (r.get('last_category') or '').upper()
        if not code:
            continue
        item = f'item:{code}'
        graph.add_node(item, side='semantic', code=code, kind='item_catalog_record', numeric_code=r.get('numeric_code',''))
        folder = r.get('item_file_path','')
        icon_pattern = norm_rel(f'image/Sinimage/Items/{folder}/it{code}')
        icon_matches = []
        for ext in ('.bmp','.tga','.dds','.png'):
            p = client_idx.find(icon_pattern + ext)
            if p:
                icon_matches.append(client_idx.rel(p))
        icon_node = node_id('client-expected', icon_pattern + '.<texture>')
        graph.add_node(icon_node, side='client', path=icon_pattern + '.<texture>', kind='expected_item_icon')
        graph.add_edge(item, icon_node, 'catalog_icon', evidence='item_catalog_recovered.inc', exists=bool(icon_matches), note=';'.join(icon_matches))

        drop = (r.get('drop_item') or '').strip()
        if drop:
            drop_base = norm_rel(f'image/Sinimage/Items/DropItem/it{drop}')
            models = []
            for ext in ('.smd','.ase','.inx','.smb'):
                p = client_idx.find(drop_base + ext)
                if p:
                    models.append(client_idx.rel(p))
            drop_node = node_id('client-expected', drop_base + '.<model>')
            graph.add_node(drop_node, side='client', path=drop_base + '.<model>', kind='expected_drop_model')
            graph.add_edge(item, drop_node, 'catalog_drop_model', evidence='item_catalog_recovered.inc', exists=bool(models), note=';'.join(models))


def add_audit_edges(graph: Graph):
    for r in load_csv(AUDIT / 'classificacao_final_35_modelos_monstros.csv'):
        model = node_id('client', r['model_ref'])
        inf = node_id('server', r['preferred_inf'])
        graph.add_node(model, side='client', path=r['model_ref'], kind='monster_model')
        graph.add_node(inf, side='server', path=r['preferred_inf'], kind='monster_definition', audit_status=r['status'])
        graph.add_edge(inf, model, 'audit_monster_model', evidence='classificacao_final_35_modelos_monstros.csv')
        for code in (r.get('preferred_missing_items') or '').split():
            dst = f'item:{code.upper()}'
            graph.add_node(dst, side='semantic', code=code.upper(), kind='item_code')
            graph.add_edge(inf, dst, 'monster_drop_dependency', evidence='classificacao_final_35_modelos_monstros.csv')
    for r in load_csv(AUDIT / 'classificacao_final_npcs.csv'):
        if r['classification'] not in {'D_STRONG_SERVER_ONLY_NPC','C_NEW_NPC_ROLE_USING_EXISTING_MONSTER_MODEL'}:
            continue
        model = node_id('client', r['model_ref'])
        graph.add_node(model, side='client', path=r['model_ref'], kind='npc_model')
        for p in re.split(r'\s*[|;]\s*', r.get('donor_npc_paths','')):
            if p.strip():
                src = node_id('server', p.strip())
                graph.add_node(src, side='server', path=p.strip(), kind='npc_definition', audit_status=r['classification'])
                graph.add_edge(src, model, 'audit_npc_model', evidence='classificacao_final_npcs.csv')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default=str(HERE / 'summit_paths.json'))
    ap.add_argument('--out-dir', default='dependency_graph')
    ap.add_argument('--skip-client-scan', action='store_true', help='faster: use only server/audit/catalog evidence')
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    client = Path(cfg['target_client']).expanduser()
    server = Path(cfg['target_server']).expanduser()
    ci, si = CaseIndex(client), CaseIndex(server)
    g = Graph()
    scan_server_text(g, server, si, ci)
    scan_spc(g, server, si, ci)
    if not args.skip_client_scan:
        scan_client(g, client, ci, si)
    add_item_catalog(g, ci)
    add_audit_edges(g)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    node_fields = sorted({k for n in g.nodes.values() for k in n.keys()})
    edge_fields = ['src','dst','relation','evidence','target_exists','note']
    write_csv(out / 'nodes.csv', list(g.nodes.values()), node_fields)
    write_csv(out / 'edges.csv', g.edges, edge_fields)
    (out / 'graph.json').write_text(json.dumps({'nodes': list(g.nodes.values()), 'edges': g.edges}, indent=2, ensure_ascii=False), encoding='utf-8')
    missing = [e for e in g.edges if e.get('target_exists') == 'False']
    summary = {
        'nodes': len(g.nodes), 'edges': len(g.edges), 'missing_reference_edges': len(missing),
        'client_root': str(client), 'server_root': str(server),
        'outputs': {'nodes': str(out/'nodes.csv'), 'edges': str(out/'edges.csv'), 'json': str(out/'graph.json')}
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
