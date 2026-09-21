#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"

# Runtime/user artifacts are intentionally *preserved*.  They are ignored by
# Git and excluded from the static snapshot; deleting them is not required to
# create a clean source commit.  In particular, texture enhancement runs may be
# tens of gigabytes and are user data, not disposable cache.
PRESERVED_RUNTIME_REASONS = {
    "app/pt_build": "runtime/user workspace: may contain enhancement outputs, transaction backups, staging evidence and reports; it is excluded from Git/snapshots but must never be recursively deleted by release hygiene",
    "enhancement": "legacy enhancement workspace: may contain irreplaceable user-generated upscales from older versions; preserve it and migrate explicitly instead of deleting it",
}


def preserved_runtime_roots() -> list[tuple[Path, str]]:
    # Compute from the current ROOT/APP at call time so copied test trees and
    # patch-validation roots inherit the same safety boundary.
    return [
        (APP / "pt_build", PRESERVED_RUNTIME_REASONS["app/pt_build"]),
        (ROOT / "enhancement", PRESERVED_RUNTIME_REASONS["enhancement"]),
    ]


CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache"}
CACHE_SUFFIXES = {".pyc", ".pyo"}


def say(kind: str, path: Path, reason: str) -> None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    print(f"{kind} {rel}", flush=True)
    print(f"  reason={reason}", flush=True)


def generated_paths() -> list[tuple[Path, str]]:
    found: dict[Path, str] = {}
    preserved_roots = [path.resolve() for path, _ in preserved_runtime_roots()]
    for p in ROOT.rglob("*"):
        if ".git" in p.parts:
            continue
        rp = p.resolve()
        if any(rp == root or root in rp.parents for root in preserved_roots):
            # Runtime/user trees are opaque to release hygiene. Even cache-like
            # names inside them belong to the user's run state and are untouched.
            continue
        if p.is_dir() and p.name in CACHE_DIR_NAMES:
            found[p.resolve()] = (
                "ephemeral tool cache: recreated automatically and may encode local test history, interpreter paths or timestamps; it is not source or release evidence"
            )
        elif p.is_file() and p.suffix.lower() in CACHE_SUFFIXES:
            found[p.resolve()] = (
                "Python bytecode cache: interpreter/version-specific and fully reproducible from source; packaging it can make a clean clone look machine-dependent"
            )
    # If a whole parent will be deleted, do not print/delete every child separately.
    result: list[tuple[Path, str]] = []
    for path, reason in sorted(found.items(), key=lambda x: (len(x[0].parts), str(x[0]))):
        if any(parent == path or parent in path.parents for parent, _ in result):
            continue
        result.append((path, reason))
    return result


def report_preserved_runtime() -> int:
    count = 0
    for path, reason in preserved_runtime_roots():
        if path.exists():
            say("PRESERVED", path, reason)
            count += 1
    return count


def clean_generated(*, dry_run: bool = False) -> int:
    rows = generated_paths()
    if not rows:
        print("CLEAN=PASS no ephemeral cache artifacts found")
        return 0
    for path, reason in rows:
        say("WOULD_REMOVE" if dry_run else "REMOVED", path, reason)
        if dry_run:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return len(rows)


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(x) for x in cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, check=check)


def require_git_repo() -> None:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if cp.returncode != 0:
        raise SystemExit("READY_TO_DEPLOY=FAIL reason=not_a_git_repository\nInstall Git if needed on Fedora (`sudo dnf install git`) and run this from the project repository.")
    top = Path(cp.stdout.strip()).resolve()
    if top != ROOT.resolve():
        raise SystemExit(f"READY_TO_DEPLOY=FAIL reason=repository_root_mismatch expected={ROOT} actual={top}")


def dependency_gate(*, need_pytest: bool) -> None:
    sys.path.insert(0, str(APP))
    from pt_asset_tool.dependencies import dependency_report, format_dependency_report
    report = dependency_report(APP)
    by_id = {row["id"]: row for row in report["dependencies"]}
    required = ["python", "git"] + (["pytest"] if need_pytest else [])
    bad = [by_id[x] for x in required if by_id.get(x, {}).get("status") != "READY"]
    if bad:
        print(format_dependency_report(report))
        raise SystemExit("READY_TO_DEPLOY=FAIL reason=missing_release_dependency ids=" + ",".join(x["id"] for x in bad))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run regression, remove only reproducible caches, preserve runtime/user artifacts, regenerate the static snapshot, verify source hygiene and commit the clean tree."
    )
    ap.add_argument("--check", action="store_true", help="read-only preflight: show what would be removed and dependency/Git status; do not test, clean, snapshot, stage or commit")
    ap.add_argument("--skip-tests", action="store_true", help="skip pytest only; useful after a just-completed full regression")
    ap.add_argument("--no-commit", action="store_true", help="clean + verify + stage, but do not create the Git commit")
    ap.add_argument("--message", default="chore: ready to deploy", help="Git commit message")
    ns = ap.parse_args(argv)

    dependency_gate(need_pytest=not ns.skip_tests and not ns.check)
    require_git_repo()

    if ns.check:
        report_preserved_runtime()
        clean_generated(dry_run=True)
        print("READY_TO_DEPLOY_CHECK=PASS runtime_user_data_preserved=true")
        return 0

    if not ns.skip_tests:
        # Run before cleanup so test-produced evidence cannot leak into the release.
        run([sys.executable, "-m", "pytest", "-q", "dev_tests", "tests"], cwd=APP)

    report_preserved_runtime()
    clean_generated(dry_run=False)

    # Snapshot immutable package content. Runtime/user data may remain on disk:
    # update_snapshot_manifest.py excludes pt_build, and Git ignore policy keeps
    # those local artifacts out of commits without destroying them.
    run([sys.executable, "update_snapshot_manifest.py", "--current-root", str(ROOT)], cwd=APP)
    run(["bash", "VERIFY_PACKAGE.sh"], cwd=ROOT)

    # Stage only after verification. `git diff --cached --check` catches conflict
    # markers/whitespace problems before the commit is created.
    run(["git", "add", "-A"])
    run(["git", "diff", "--cached", "--check"])
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        print("READY_TO_DEPLOY=PASS nothing_to_commit=true working_tree_verified=true")
        return 0
    if staged.returncode not in {0, 1}:
        raise SystemExit("READY_TO_DEPLOY=FAIL reason=git_diff_failed")

    if ns.no_commit:
        print("READY_TO_DEPLOY=PASS staged=true committed=false")
        return 0

    run(["git", "commit", "-m", ns.message])
    cp = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, stdout=subprocess.PIPE, check=True)
    if cp.stdout.strip():
        print(cp.stdout, end="")
        raise SystemExit("READY_TO_DEPLOY=FAIL reason=working_tree_not_clean_after_commit")
    print("READY_TO_DEPLOY_COMMIT=PASS working_tree=clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
