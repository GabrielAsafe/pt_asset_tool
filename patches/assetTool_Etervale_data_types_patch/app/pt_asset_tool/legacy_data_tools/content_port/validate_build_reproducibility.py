#!/usr/bin/env python3
import argparse, hashlib, subprocess, sys, tempfile
from pathlib import Path

def digest_tree(root: Path):
    out = {}
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def main():
    ap=argparse.ArgumentParser(description='Prove canonical build byte reproducibility across two clean outputs')
    ap.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    args=ap.parse_args(); root=args.repo_root.resolve()
    build=root/'tools/content_port/build_from_canonical.py'; c=root/'Content/canonical'
    common=[sys.executable,str(build),'--canonical-text',str(c/'text'),'--canonical-spawns',str(c/'stage_spawns'),'--canonical-maps',str(c/'maps'),'--canonical-start-points',str(c/'stage_start_points'),'--canonical-fixed-npcs',str(c/'fixed_npcs'),'--canonical-item-profiles',str(c/'item_profiles')]
    with tempfile.TemporaryDirectory(prefix='summit-canonical-repro-') as td:
        a=Path(td)/'a'; b=Path(td)/'b'
        subprocess.run(common+['--out-root',str(a)],cwd=root,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(common+['--out-root',str(b)],cwd=root,check=True,stdout=subprocess.DEVNULL)
        da,db=digest_tree(a),digest_tree(b)
        if da != db:
            keys=sorted(set(da)|set(db));
            for k in keys:
                if da.get(k)!=db.get(k): print(f'FAIL: reproducibility mismatch: {k}',file=sys.stderr)
            raise SystemExit(1)
        packs=[k for k in da if k.startswith('packs/') and not k.endswith('.report.json')]
        print(f'canonical build reproducibility: PASS ({len(da)} files, {len(packs)} runtime packs)')
if __name__=='__main__': main()
