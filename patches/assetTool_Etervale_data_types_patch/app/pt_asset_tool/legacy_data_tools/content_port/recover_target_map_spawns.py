#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from active_tokens import load_active_token_sets
from import_corpus import parse_directive_document, parse_spawn_semantics
from source_tokens import load_source_token_maps

TARGETS = {
    46: 'slab.ase.spm',
    47: 'ancientw.ase.spm',
    48: 'seaa.ase.spm',
    49: 'stemple.ase.spm',
    50: 'ruin-arenasf.ase.spm',
    51: 'lost3.ase.spm',
    52: 'dark_boss.ase.spm',
}

@dataclass
class Candidate:
    label: str
    data: bytes
    actors: int
    bosses: int

    @property
    def score(self):
        return (self.actors + self.bosses, self.actors, self.bosses, len(self.data))


def parse_counts(data: bytes, source_root: Path) -> tuple[int, int]:
    maps = load_source_token_maps(source_root)
    active = load_active_token_sets(source_root)
    parsed = parse_directive_document(data, maps['spawn'], active['spawn'])
    sem = parse_spawn_semantics(parsed)
    return len(sem.get('actors') or []), len(sem.get('bosses') or [])


def add_candidate(out: dict[str, list[Candidate]], basename: str, label: str, data: bytes, source_root: Path):
    if basename.casefold() not in out or not data:
        return
    try:
        actors, bosses = parse_counts(data, source_root)
    except Exception as exc:
        print(f'CANDIDATE_REJECT file={basename} source={label} reason=parse_error:{exc}')
        return
    c = Candidate(label, data, actors, bosses)
    out[basename.casefold()].append(c)
    print(f'CANDIDATE file={basename} source={label} bytes={len(data)} actors={actors} bosses={bosses}')


def scan(repo: Path, source_root: Path) -> dict[str, list[Candidate]]:
    found = {name.casefold(): [] for name in TARGETS.values()}
    wanted = set(found)

    # Prefer live deployment and local Summit backups; these preserve the user's
    # actual server data better than fabricating spawn composition from monster names.
    roots = [repo / 'Servidor', repo / 'cliente']
    roots.extend(sorted((p for p in repo.glob('.summit_*') if p.is_dir()), key=lambda p: p.name))
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if path.is_file() and path.name.casefold() in wanted:
                add_candidate(found, path.name, str(path), path.read_bytes(), source_root)

    # Migration backups are the expected source after --prune-legacy.
    zip_roots = [repo / 'SourceCode' / 'Content' / 'migration_backups']
    for zr in zip_roots:
        if not zr.is_dir():
            continue
        for zpath in sorted(zr.glob('*.zip')):
            try:
                with zipfile.ZipFile(zpath) as zf:
                    for info in zf.infolist():
                        name = Path(info.filename).name.casefold()
                        if name not in wanted:
                            continue
                        add_candidate(found, Path(info.filename).name, f'{zpath}!{info.filename}', zf.read(info), source_root)
            except zipfile.BadZipFile:
                print(f'ZIP_REJECT file={zpath} reason=bad_zip')
    return found


def run(*args: object) -> None:
    print('+', ' '.join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description='Recover non-empty canonical spawn data for Summit fields 46-52 from live/pruned legacy SPM backups.')
    ap.add_argument('--repo-root', type=Path, default=HERE.parents[2])
    args = ap.parse_args()
    repo = args.repo_root.expanduser().resolve()
    source = repo / 'SourceCode'
    canonical = source / 'Content/canonical/stage_spawns'
    if not source.is_dir() or not canonical.is_dir():
        raise SystemExit('repo/source canonical roots not found')

    candidates = scan(repo, source)
    chosen: dict[int, Candidate] = {}
    for field, basename in TARGETS.items():
        rows = candidates[basename.casefold()]
        viable = [c for c in rows if c.actors + c.bosses > 0]
        if not viable:
            print(f'FIELD={field} FILE={basename} STATUS=BLOCKED_NO_NONEMPTY_LEGACY_SPM')
            continue
        best = max(viable, key=lambda c: c.score)
        chosen[field] = best
        print(f'FIELD={field} FILE={basename} STATUS=RECOVER source={best.label} actors={best.actors} bosses={best.bosses}')

    if not chosen:
        print('TARGET_MAP_SPAWN_RECOVERY=BLOCKED_NO_SOURCE')
        return 0

    with tempfile.TemporaryDirectory(prefix='summit-spawn-recovery-') as td:
        td = Path(td)
        corpus = td / 'corpus'
        field_root = corpus / 'Servidor/GameServer/Field'
        field_root.mkdir(parents=True)
        for field, best in chosen.items():
            basename = TARGETS[field]
            (field_root / basename).write_bytes(best.data)

        shadow = td / 'shadow'
        recovered = td / 'canonical'
        run(sys.executable, HERE / 'import_corpus.py', '--corpus', corpus, '--source-root', source, '--out', shadow)
        run(sys.executable, HERE / 'canonicalize_stage_spawns.py', '--shadow', shadow, '--canonical-text', source / 'Content/canonical/text', '--out', recovered)

        existing_index_path = canonical / 'index.json'
        existing = json.loads(existing_index_path.read_text(encoding='utf-8'))
        by_path = {str(e['logical_path']).casefold(): e for e in existing.get('documents', [])}
        rindex = json.loads((recovered / 'index.json').read_text(encoding='utf-8'))
        accepted = 0
        for entry in rindex.get('documents', []):
            doc_path = recovered / entry['json_path']
            doc = json.loads(doc_path.read_text(encoding='utf-8'))
            count = len(doc.get('actors') or []) + len(doc.get('bosses') or [])
            if count <= 0:
                print(f'RECOVERED_REJECT logical={entry["logical_path"]} reason=empty_after_canonicalize')
                continue
            dest = canonical / entry['json_path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc_path, dest)
            by_path[str(entry['logical_path']).casefold()] = entry
            accepted += 1
            print(f'RECOVERED_ACCEPT logical={entry["logical_path"]} actors={len(doc.get("actors") or [])} bosses={len(doc.get("bosses") or [])}')
        existing['documents'] = sorted(by_path.values(), key=lambda e: str(e['logical_path']).casefold())
        existing_index_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    if accepted:
        # Rebuild field/text/definition packs from the canonical source and deploy
        # them to standalone client/server roots. This updates BUILD/CANONICAL_SOURCE too.
        run(sys.executable, HERE / 'consolidate_canonical_content.py', '--repo-root', repo)

    missing = [field for field in TARGETS if field not in chosen]
    if missing:
        print('TARGET_MAP_SPAWN_RECOVERY=PARTIAL')
        print('BLOCKED_FIELDS=' + ','.join(map(str, missing)))
    else:
        print('TARGET_MAP_SPAWN_RECOVERY=PASS')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
