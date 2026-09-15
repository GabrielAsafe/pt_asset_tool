#!/usr/bin/env python3
"""Audit-driven, missing-only Summit asset migration.

Default behavior is PLAN ONLY. `apply` copies only rows whose status is AUTO and whose
preconditions still match. Existing files are never overwritten unless --overwrite is
explicitly passed, and even then BLOCKED/REVIEW rows are not applied.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from asset_common import CaseIndex, Validation, load_csv, norm_key, norm_rel, safe_copy, sha256_file, validate_candidate, write_csv

HERE = Path(__file__).resolve().parent
AUDIT = HERE / 'audit_data'

DEFAULT_PROFILES = ['client-confirmed', 'source-armors', 'server-monsters', 'server-npcs', 'server-fields']
ALL_PROFILES = DEFAULT_PROFILES + ['server-openitems-review', 'historical-missing-only']


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding='utf-8'))
    for key in ('target_client', 'target_server'):
        if key not in cfg:
            raise SystemExit(f'config missing required key: {key}')
    cfg.setdefault('donors', [])
    return cfg


def split_paths(value: str) -> List[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r'\s*[|;]\s*', value) if x.strip()]


class Planner:
    def __init__(self, cfg: dict, args):
        self.cfg = cfg
        self.args = args
        self.target_client = Path(os.path.expanduser(cfg['target_client']))
        self.target_server = Path(os.path.expanduser(cfg['target_server']))
        self.target_indexes = {
            'client': CaseIndex(self.target_client),
            'server': CaseIndex(self.target_server),
        }
        self.donors = []
        for d in sorted(cfg.get('donors', []), key=lambda x: int(x.get('priority', 100))):
            root = Path(os.path.expanduser(d['root']))
            self.donors.append({**d, 'root_path': root, 'index': CaseIndex(root)})
        self.rows: List[dict] = []
        self._seen = {}

    def donors_for(self, side: str, preferred: str = '') -> List[dict]:
        items = [d for d in self.donors if d.get('side') == side and d['root_path'].exists()]
        if preferred:
            p = preferred.casefold()
            items.sort(key=lambda d: (0 if p in d.get('label', '').casefold() else 1, int(d.get('priority', 100))))
        return items

    def _target_root(self, side: str) -> Path:
        return self.target_client if side == 'client' else self.target_server

    def _target_lookup(self, side: str, rel: str) -> Optional[Path]:
        return self.target_indexes[side].find(rel)

    def locate_source(self, side: str, rels: Sequence[str], preferred: str = '', basename_fallback: bool = False) -> Tuple[Optional[dict], Optional[Path], Optional[str]]:
        for donor in self.donors_for(side, preferred):
            idx: CaseIndex = donor['index']
            for rel in rels:
                p = idx.find(rel)
                if p:
                    return donor, p, idx.rel(p)
            # Donor roots may be configured at a base directory above the actual
            # client/server tree.  Accept a unique recursive suffix match before
            # falling back to basename-only resolution.
            for rel in rels:
                matches = idx.find_suffix(rel)
                if len(matches) == 1:
                    p = matches[0]
                    return donor, p, idx.rel(p)
            if basename_fallback:
                for rel in rels:
                    matches = idx.find_basename(Path(rel).name)
                    if len(matches) == 1:
                        p = matches[0]
                        return donor, p, idx.rel(p)
        return None, None, None

    def add(self, *, profile: str, side: str, target_rel: str, source_rels: Sequence[str], preferred: str = '', reason: str = '', policy: str = 'AUTO', basename_fallback: bool = False):
        target_rel = norm_rel(target_rel)
        if not target_rel:
            return
        target_existing = self._target_lookup(side, target_rel)
        target_path = target_existing or (self._target_root(side) / target_rel)
        donor, source, source_rel = self.locate_source(side, [norm_rel(x) for x in source_rels if x], preferred, basename_fallback)

        row = {
            'profile': profile,
            'side': side,
            'target_rel': target_rel,
            'source_label': donor.get('label', '') if donor else '',
            'source_rel': source_rel or '',
            'source_path': str(source) if source else '',
            'target_path': str(target_path),
            'source_sha256': '',
            'target_sha256': '',
            'status': '',
            'format': '',
            'reason': reason,
            'validation': '',
        }

        if not source:
            row['status'] = 'BLOCKED'
            row['validation'] = 'no authorized donor contains the requested file/path'
            self._merge_row(row)
            return

        row['source_sha256'] = sha256_file(source)
        if target_existing:
            row['target_sha256'] = sha256_file(target_existing)
            if row['source_sha256'] == row['target_sha256']:
                row['status'] = 'PRESENT_IDENTICAL'
                row['validation'] = 'target already contains identical content'
            else:
                row['status'] = 'PRESENT_DIFFERENT_PRESERVE'
                row['validation'] = 'target already exists with different content; missing-only policy preserves it'
            self._merge_row(row)
            return

        v = validate_candidate(source, target_path, source_label=row['source_label'], allow_dds=self.args.allow_dds, allow_stage072=self.args.allow_stage072_from_previous_summit)
        row['format'] = v.format_name
        rank = {'AUTO': 0, 'REVIEW': 1, 'BLOCKED': 2}
        effective = v.status
        if rank.get(policy, 1) > rank.get(effective, 1):
            effective = policy
        row['status'] = effective
        row['validation'] = v.reason
        self._merge_row(row)

    def _merge_row(self, row: dict):
        key = (row['side'], norm_key(row['target_rel']))
        status_rank = {'AUTO': 0, 'REVIEW': 1, 'BLOCKED': 2, 'PRESENT_IDENTICAL': 3, 'PRESENT_DIFFERENT_PRESERVE': 4}
        prev_i = self._seen.get(key)
        if prev_i is None:
            self._seen[key] = len(self.rows)
            self.rows.append(row)
            return
        prev = self.rows[prev_i]
        # Prefer an actionable exact source over a blocked/missing duplicate.
        if status_rank.get(row['status'], 9) < status_rank.get(prev['status'], 9):
            self.rows[prev_i] = row
        elif row['profile'] not in prev['profile'].split('+'):
            prev['profile'] += '+' + row['profile']
            if row['reason'] and row['reason'] not in prev['reason']:
                prev['reason'] += ' | ' + row['reason']

    def add_package(self, *, profile: str, side: str, model_ref: str, preferred: str = '', reason: str = '', policy: str = 'AUTO'):
        model_ref = norm_rel(model_ref)
        donor, model_path, source_rel = self.locate_source(side, [model_ref], preferred, basename_fallback=True)
        if not donor or not model_path or not source_rel:
            self.add(profile=profile, side=side, target_rel=model_ref, source_rels=[model_ref], preferred=preferred, reason=reason, policy='BLOCKED', basename_fallback=True)
            return
        src_parent = model_path.parent
        idx: CaseIndex = donor['index']
        rel_parent = Path(source_rel).parent.as_posix()
        # Package = exact parent subtree. Copy is missing-only and each file is validated.
        for p in src_parent.rglob('*'):
            if not p.is_file():
                continue
            sub = p.relative_to(src_parent).as_posix()
            target_rel = norm_rel(f'{rel_parent}/{sub}')
            self.add(profile=profile, side=side, target_rel=target_rel, source_rels=[idx.rel(p)], preferred=donor['label'], reason=reason, policy=policy)

    def profile_client_confirmed(self):
        rows = load_csv(AUDIT / 'classificacao_final_cliente_atual.csv')
        for r in rows:
            cls = r.get('class', '')
            if cls == 'A_CONFIRMED_SERVER_TO_CURRENT_CLIENT_PACKAGE_GAP':
                self.add_package(profile='client-confirmed', side='client', model_ref=r['reference'], reason=f"{r['id']}: {r['note']}")
            elif cls == 'A_CONFIRMED_SERVER_TO_CURRENT_CLIENT_FIELD_GAP':
                field_id = r['id']
                # Stage is explicitly review unless trusted previous-Summit lineage is accepted.
                candidates = []
                for donor in self.donors_for('client'):
                    for p in donor['index'].find_stem(field_id, ['.smd']):
                        if '/field/' in ('/' + donor['index'].rel(p).casefold()):
                            candidates.append((donor, p))
                if not candidates:
                    self.add(profile='client-confirmed', side='client', target_rel=f'Field/{field_id}.smd', source_rels=[f'Field/{field_id}.smd'], reason=r['note'], policy='BLOCKED', basename_fallback=True)
                else:
                    donor, p = candidates[0]
                    parent_rel = Path(donor['index'].rel(p)).parent.as_posix()
                    self.add_package(profile='client-confirmed', side='client', model_ref=donor['index'].rel(p), preferred=donor['label'], reason=r['note'], policy='REVIEW')

    def profile_source_armors(self):
        live = {r['source_entry'].casefold(): r for r in load_csv(AUDIT / 'source_armor_032_034_current_client.csv')}
        rows = load_csv(AUDIT / 'tmabcd_armaduras_source_confirmed.csv')
        for r in rows:
            state = live.get(r['source_table_entry'].casefold(), {})
            # Re-check target live; audit state is only a hint.
            for field in ('inx_logical_path', 'smd_logical_path'):
                rel = r[field]
                self.add(profile='source-armors', side='client', target_rel=rel, source_rels=[rel], preferred='exmachina', reason=f"source table {r['job']} {r['source_table_entry']} references this armor resource")
            tex_pat = r['texture_logical_path']
            tex_stem = Path(tex_pat.replace('<texture>', 'x')).stem
            # Search extension variants in donors; prefer non-DDS when available, otherwise review DDS.
            found = []
            for donor in self.donors_for('client', 'exmachina'):
                for p in donor['index'].find_stem(tex_stem):
                    if p.suffix.casefold() in {'.bmp', '.tga', '.dds', '.png'}:
                        found.append((0 if p.suffix.casefold() != '.dds' else 1, donor, p))
            if found:
                found.sort(key=lambda x: x[0])
                _, donor, p = found[0]
                rel = donor['index'].rel(p)
                self.add(profile='source-armors', side='client', target_rel=rel, source_rels=[rel], preferred=donor['label'], reason=f"texture companion for {r['source_table_entry']}")
            else:
                self.add(profile='source-armors', side='client', target_rel=tex_pat, source_rels=[], preferred='exmachina', reason=f"texture companion for {r['source_table_entry']}", policy='BLOCKED')

    def profile_server_monsters(self):
        for r in load_csv(AUDIT / 'classificacao_final_35_modelos_monstros.csv'):
            st = r['status']
            policy = 'AUTO' if st in {'A_SELF_CONTAINED', 'A_HAS_SELF_CONTAINED_VARIANT'} else 'REVIEW'
            if st == 'C_BLOCKED_ORPHAN':
                policy = 'BLOCKED'
            inf = norm_rel(r.get('preferred_inf', ''))
            preferred = r.get('preferred_source', '')
            if inf:
                self.add(profile='server-monsters', side='server', target_rel=inf, source_rels=[inf], preferred=preferred, reason=f"{st}; model={r['model_ref']}; missing_items={r.get('preferred_missing_items','')}", policy=policy, basename_fallback=True)
            z = norm_rel(r.get('preferred_zhoon', ''))
            if z and z.lower() != 'nan':
                target = z if z.casefold().startswith('gameserver/') else f'GameServer/Monster/{z}'
                srcs = [target, f'GameServer/monster/{z}', f'GameServer/Monster/{z}']
                self.add(profile='server-monsters', side='server', target_rel=target, source_rels=srcs, preferred=preferred, reason=f'name resource for {Path(inf).name if inf else r["model_ref"]}', policy=policy, basename_fallback=True)

    def profile_server_npcs(self):
        for r in load_csv(AUDIT / 'classificacao_final_npcs.csv'):
            if r['classification'] != 'D_STRONG_SERVER_ONLY_NPC':
                continue
            preferred = 'exmachina' if 'exmachina' in r.get('donor_systems', '').casefold() else ''
            for p in split_paths(r.get('donor_npc_paths', '')):
                p = norm_rel(p)
                self.add(profile='server-npcs', side='server', target_rel=p, source_rels=[p], preferred=preferred, reason=f"strong server-only NPC; model={r['model_ref']}; client_files={r.get('summit_client_files','')}", policy='AUTO', basename_fallback=True)
            zstat = r.get('zhoon_status', '') or ''
            m = re.search(r'\[([^\]]+\.zhoon)\]', zstat, re.I)
            if m and 'MISSING_FROM_SUMMIT' in zstat:
                z = norm_rel(m.group(1))
                self.add(profile='server-npcs', side='server', target_rel=z, source_rels=[z, z.replace('gameserver/npc/', 'GameServer/NPC/')], preferred=preferred, reason=f"name resource for NPC model={r['model_ref']}", policy='AUTO', basename_fallback=True)

    def profile_server_fields(self):
        for r in load_csv(AUDIT / 'classificacao_lacunas_fields.csv'):
            grade = r['audit_grade']
            if grade == 'HIGH_CONFIDENCE_COMPONENT_GAP':
                # The gap itself is high-confidence, but dcave.ase.spc was also
                # flagged by the audit as a direct binary conflict between donors.
                # Keep it REVIEW until one lineage is chosen/runtime-approved.
                policy = 'REVIEW'
            elif grade.startswith('HIGH_RELEVANCE'):
                policy = 'REVIEW'  # becomes safe after related NPC package is runtime-approved
            elif grade.startswith('LOW_'):
                policy = 'BLOCKED'
            else:
                policy = 'REVIEW'
            field_id = r['field_id']
            for ext in r['components_missing_from_summit'].split():
                ext = ext.strip()
                if not ext:
                    continue
                fname = f'{field_id}.ase{ext}'
                target = f'GameServer/Field/{fname}'
                srcs = [target, f'GameServer/Field/{field_id}{ext}', f'GameServer/Field/{fname}']
                preferred = 'exmachina' if r.get('exmachina_' + ext.lstrip('.'), '').casefold() == 'true' else 'priston'
                self.add(profile='server-fields', side='server', target_rel=target, source_rels=srcs, preferred=preferred, reason=f"{grade}: {r['notes']}", policy=policy, basename_fallback=True)

    def profile_server_openitems_review(self):
        for r in load_csv(AUDIT / 'classificacao_206_openitems_ausentes.csv'):
            if r['audit_class'] != 'A_AUDITED_EARLY_BATCH':
                continue
            preferred = 'priston' if r['pristontale_paths'] else 'exmachina'
            src_paths = split_paths(r.get('pristontale_paths', '')) + split_paths(r.get('exmachina_paths', ''))
            target = f"GameServer/OpenItem/{r['code'].upper()}.txt"
            self.add(profile='server-openitems-review', side='server', target_rel=target, source_rels=src_paths, preferred=preferred, reason=f"audited identical-donor OpenItem {r['code'].upper()} ({r['names']}); still REVIEW because adding a server item also needs client/catalog/runtime intent", policy='REVIEW', basename_fallback=True)
            for z in split_paths(r.get('donor_zhoons', '')):
                self.add(profile='server-openitems-review', side='server', target_rel=z, source_rels=[z], preferred=preferred, reason=f"name resource for {r['code'].upper()}", policy='REVIEW', basename_fallback=True)

    def profile_historical_missing_only(self):
        trusted_labels = {'previous_client', 'ptbr_antigo', 'ptbr_novo'}
        allowed_roots = {'char', 'cselect', 'effect', 'field', 'image', 'rain', 'sky', 'startimage', 'wav', 'weapons', 'res', 'game'}
        for donor in self.donors_for('client'):
            if donor.get('label', '').casefold() not in trusted_labels:
                continue
            idx: CaseIndex = donor['index']
            for relk, p in idx.files.items():
                rel = idx.rel(p)
                parts = Path(rel).parts
                if not parts or parts[0].casefold() not in allowed_roots:
                    continue
                if p.suffix.casefold() not in {'.inx','.smd','.smb','.ase','.bmp','.tga','.dds','.png','.jpg','.jpeg','.pkg','.wav','.ini','.inf','.txt','.cht','.rgx','.rxg'}:
                    continue
                self.add(profile='historical-missing-only', side='client', target_rel=rel, source_rels=[rel], preferred=donor['label'], reason='trusted historical client missing-only residual reconciliation')

    def build(self, profiles: Sequence[str]) -> List[dict]:
        for p in profiles:
            fn = getattr(self, 'profile_' + p.replace('-', '_'))
            fn()
        self.rows.sort(key=lambda r: (r['status'], r['side'], r['target_rel'].casefold()))
        return self.rows



def resolve_case_preserving_target(root: Path, rel: str) -> Path:
    """Resolve existing parent components case-insensitively without inventing duplicate dirs.

    Summit assets are Windows-era and manifests use normalized logical paths. On Linux,
    `char/tmabcd` and `char/tmABCD` are different directories. This resolver reuses the
    casing already present in the target tree and only creates genuinely missing parts.
    """
    root = root.expanduser()
    parts = Path(norm_rel(rel)).parts
    cur = root
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        if cur.is_dir():
            match = None
            try:
                for child in cur.iterdir():
                    if child.name.casefold() == part.casefold():
                        if is_last or child.is_dir():
                            match = child
                            break
            except OSError:
                match = None
            if match is not None:
                cur = match
                continue
        cur = cur / part
    return cur


def _configured_target_root(cfg: dict, side: str) -> Path:
    if side == 'client':
        return Path(os.path.expanduser(cfg['target_client']))
    if side == 'server':
        return Path(os.path.expanduser(cfg['target_server']))
    raise ValueError(f'unknown side in manifest: {side!r}')


def _error_summary(log_rows: List[dict]) -> dict:
    errs = [r for r in log_rows if r.get('apply_result') == 'ERROR']
    by_side = Counter(r.get('side','') for r in errs)
    by_profile = Counter(r.get('profile','') for r in errs)
    by_detail = Counter(r.get('apply_detail','') for r in errs)
    return {
        'errors_by_side': dict(by_side),
        'errors_by_profile': dict(by_profile),
        'errors_by_detail': dict(by_detail.most_common(12)),
        'first_errors': [
            {
                'side': r.get('side',''),
                'profile': r.get('profile',''),
                'target_rel': r.get('target_rel',''),
                'source_path': r.get('source_path',''),
                'detail': r.get('apply_detail',''),
            } for r in errs[:12]
        ],
    }


def diagnose_apply_log(path: Path) -> int:
    rows = load_csv(path)
    results = Counter(r.get('apply_result','') for r in rows)
    out = {'log': str(path.resolve()), 'results': dict(results)}
    out.update(_error_summary(rows))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if results.get('ERROR', 0) else 0

def summarize(rows: List[dict]) -> dict:
    out = {'total': len(rows), 'by_status': {}, 'by_profile': {}, 'by_side': {}}
    for r in rows:
        out['by_status'][r['status']] = out['by_status'].get(r['status'], 0) + 1
        out['by_side'][r['side']] = out['by_side'].get(r['side'], 0) + 1
        for p in r['profile'].split('+'):
            out['by_profile'][p] = out['by_profile'].get(p, 0) + 1
    return out


def apply_manifest(path: Path, cfg: dict, args) -> int:
    rows = load_csv(path)
    copied = 0
    skipped = 0
    errors = 0
    log_rows = []
    for r in rows:
        if r.get('status') != 'AUTO':
            skipped += 1
            continue
        source = Path(r['source_path'])
        result = 'SKIP'
        detail = ''
        try:
            side = r.get('side','')
            target_root = _configured_target_root(cfg, side)
            target = resolve_case_preserving_target(target_root, r.get('target_rel',''))

            # Never trust a stale/edited absolute target_path from the CSV. Rebuild it
            # from the configured Summit root + logical target_rel and preserve casing.
            root_resolved = target_root.resolve(strict=False)
            target_resolved = target.resolve(strict=False)
            try:
                target_resolved.relative_to(root_resolved)
            except ValueError:
                raise RuntimeError(f'target escapes configured {side} root: {target}')

            if not source.is_file():
                raise FileNotFoundError(f'source disappeared: {source}')
            current_src_hash = sha256_file(source)
            if current_src_hash != r.get('source_sha256'):
                raise RuntimeError('source hash changed since plan; regenerate manifest')
            if target.exists() and not args.overwrite:
                result = 'PRESERVE_EXISTING'
                detail = 'target appeared after plan or was copied by a previous apply'
                skipped += 1
            else:
                v = validate_candidate(source, target, source_label=r.get('source_label',''), allow_dds=args.allow_dds, allow_stage072=args.allow_stage072_from_previous_summit)
                if v.status != 'AUTO':
                    raise RuntimeError(f'candidate no longer AUTO: {v.status}: {v.reason}')
                safe_copy(source, target, overwrite=args.overwrite)
                if sha256_file(target) != current_src_hash:
                    raise RuntimeError('post-copy SHA256 mismatch')
                result = 'COPIED'
                detail = f'copied to {target}'
                copied += 1
        except Exception as e:
            result = 'ERROR'
            detail = f'{type(e).__name__}: {e}'
            errors += 1
        log_rows.append({**r, 'apply_result': result, 'apply_detail': detail})
    log_path = path.with_name(path.stem + '.apply.csv')
    fields = list(rows[0].keys()) + ['apply_result', 'apply_detail'] if rows else ['apply_result','apply_detail']
    write_csv(log_path, log_rows, fields)
    summary = {'copied': copied, 'skipped': skipped, 'errors': errors, 'apply_log': str(log_path)}
    if errors:
        summary.update(_error_summary(log_rows))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default=str(HERE / 'summit_paths.json'), help='JSON config with target and donor roots')
    ap.add_argument('--allow-dds', action='store_true', help='allow DDS even when target subtree has no DDS peer')
    ap.add_argument('--allow-stage072-from-previous-summit', action='store_true', help='allow Stage 0.72 only from donor label previous_client/summit_previous')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('plan', help='produce a migration manifest; never writes target trees')
    p.add_argument('--profiles', nargs='+', choices=ALL_PROFILES, default=DEFAULT_PROFILES)
    p.add_argument('--out', default='migration_plan.csv')

    a = sub.add_parser('apply', help='apply only AUTO rows from an existing manifest')
    a.add_argument('manifest')
    a.add_argument('--overwrite', action='store_true', help='not recommended; missing-only is the default')

    d = sub.add_parser('diagnose', help='summarize an existing *.apply.csv, grouped by error cause/profile/side')
    d.add_argument('apply_log')

    args = ap.parse_args()
    cfg = load_config(Path(args.config))
    if args.cmd == 'diagnose':
        return diagnose_apply_log(Path(args.apply_log))
    if args.cmd == 'apply':
        return apply_manifest(Path(args.manifest), cfg, args)

    planner = Planner(cfg, args)
    rows = planner.build(args.profiles)
    fields = ['profile','side','target_rel','source_label','source_rel','source_path','target_path','source_sha256','target_sha256','status','format','reason','validation']
    out = Path(args.out)
    write_csv(out, rows, fields)
    summary = summarize(rows)
    summary['manifest'] = str(out.resolve())
    summary['note'] = 'Only AUTO rows are eligible for apply. REVIEW/BLOCKED/PRESENT rows are never copied.'
    out.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
