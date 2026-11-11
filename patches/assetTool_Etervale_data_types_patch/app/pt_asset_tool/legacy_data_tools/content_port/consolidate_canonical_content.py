#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

IMPORT_FAMILIES = ("maps", "stage_spawns", "stage_start_points", "fixed_npcs", "text")
REQUIRED_INTERNAL = (
    "maps/client.maps.json",
    "maps/server.maps.json",
    "stage_spawns/index.json",
    "stage_start_points/index.json",
    "fixed_npcs/index.json",
    "text/index.json",
    "item_profiles/client.items.json",
    "item_profiles/server.items.json",
    "item_profiles/skin_reforms.json",
)
FOREVER_FALL = (
    "forever-fall-01.ase.spm.json",
    "forever-fall-02.ase.spm.json",
    "forever-fall-03.ase.spm.json",
    "forever-fall-04.ase.spm.json",
)


def run(*args: object) -> None:
    print("+", " ".join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], check=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_digest(root: Path) -> tuple[str, int, int]:
    h = hashlib.sha256()
    files = 0
    total = 0
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix().casefold()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        digest = sha256_file(path).encode("ascii")
        size = path.stat().st_size
        h.update(rel + b"\0" + str(size).encode("ascii") + b"\0" + digest + b"\n")
        files += 1
        total += size
    return h.hexdigest(), files, total


def fail(message: str) -> None:
    print(f"ERROR={message}")
    print("RESULT=FAIL")
    raise SystemExit(1)


def validate_required(canonical: Path) -> None:
    missing = [rel for rel in REQUIRED_INTERNAL if not (canonical / rel).is_file()]
    npc_root = canonical / "text/resources/Servidor/GameServer/NPC"
    openitem_root = canonical / "text/resources/Servidor/GameServer/OpenItem"
    if not npc_root.is_dir():
        missing.append("text/resources/Servidor/GameServer/NPC/")
    if not openitem_root.is_dir():
        missing.append("text/resources/Servidor/GameServer/OpenItem/")
    if missing:
        fail("canonical source is incomplete: " + ", ".join(missing))


def validate_forever_fall(canonical: Path) -> dict[str, dict[str, int]]:
    field = canonical / "stage_spawns/spawns/GameServer/Field"
    result: dict[str, dict[str, int]] = {}
    for name in FOREVER_FALL:
        path = field / name
        if not path.is_file():
            fail(f"missing canonical Forever Fall document: {path}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        actors = doc.get("actors") or []
        unresolved = [x for x in actors if not x.get("monster_id")]
        weight = sum(int(x.get("weight", 0)) for x in actors)
        if not actors:
            fail(f"Forever Fall canonical document still has no actors: {name}")
        if unresolved:
            fail(f"Forever Fall canonical document has unresolved actors: {name}")
        if weight != 100:
            fail(f"Forever Fall actor weight must total 100: {name}={weight}")
        result[name] = {"actors": len(actors), "bosses": len(doc.get("bosses") or []), "weight_sum": weight}
    return result


def import_external(import_root: Path, internal: Path) -> dict[str, dict[str, object]]:
    if not import_root.is_dir():
        fail(f"import canonical root does not exist: {import_root}")
    imported: dict[str, dict[str, object]] = {}
    internal.mkdir(parents=True, exist_ok=True)
    for family in IMPORT_FAMILIES:
        src = import_root / family
        dst = internal / family
        if not src.is_dir():
            fail(f"import canonical family is missing: {src}")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        digest, files, total = tree_digest(dst)
        imported[family] = {"files": files, "bytes": total, "sha256": digest}
        print(f"CANONICAL_IMPORT family={family} files={files} bytes={total} sha256={digest}")
    return imported


def main() -> int:
    here = Path(__file__).resolve()
    ap = argparse.ArgumentParser(
        description="Consolidate Summit canonical content into SourceCode, rebuild packs, deploy standalone client/server content, and validate the result."
    )
    ap.add_argument("--repo-root", type=Path, default=here.parents[3])
    ap.add_argument(
        "--import-root",
        type=Path,
        default=None,
        help="Optional one-time external canonical root. maps/, stage_spawns/, stage_start_points/, fixed_npcs/ and text/ are copied into SourceCode/Content/canonical before building. Runtime never uses this path.",
    )
    ap.add_argument("--no-deploy", action="store_true", help="Build and validate SourceCode packs without copying them to cliente/ and Servidor/.")
    args = ap.parse_args()

    repo = args.repo_root.expanduser().resolve()
    source = repo / "SourceCode"
    tools = source / "tools/content_port"
    content = source / "Content"
    canonical = content / "canonical"

    if not source.is_dir():
        fail(f"SourceCode directory not found: {source}")

    print(f"REPO_ROOT={repo}")
    print(f"SOURCE_CODE={source}")
    print(f"CANONICAL_ROOT={canonical}")

    imported: dict[str, dict[str, object]] = {}
    if args.import_root is not None:
        imported = import_external(args.import_root.expanduser().resolve(), canonical)

    validate_required(canonical)
    forever = validate_forever_fall(canonical)

    for name, row in forever.items():
        print(f"FOREVER_FALL_CANONICAL file={name} actors={row['actors']} bosses={row['bosses']} weight_sum={row['weight_sum']}")

    run(
        sys.executable,
        tools / "build_from_canonical.py",
        "--canonical-text", canonical / "text",
        "--canonical-spawns", canonical / "stage_spawns",
        "--canonical-maps", canonical / "maps",
        "--canonical-start-points", canonical / "stage_start_points",
        "--canonical-fixed-npcs", canonical / "fixed_npcs",
        "--canonical-item-profiles", canonical / "item_profiles",
        "--out-root", content,
    )

    # SUMMIT_ITEM_VISUAL_REGISTRY_PIPELINE_V1: geracao do mapa C++ a partir do Content.
    run(sys.executable, tools / "compile_item_visual_registry.py", "--repo-root", repo)
    run(sys.executable, tools / "validate_compiled_item_materialization.py", "--source-root", source)
    run(sys.executable, tools / "validate_internal_runtime_contract.py", "--source-root", source)

    if not args.no_deploy:
        run(sys.executable, tools / "deploy_runtime_content.py", "--repo-root", repo)
        run(sys.executable, tools / "validate_runtime_pack_resolution.py", "--repo-root", repo)

    family_manifest = {}
    for family in sorted(path.name for path in canonical.iterdir() if path.is_dir()):
        digest, files, total = tree_digest(canonical / family)
        family_manifest[family] = {"files": files, "bytes": total, "sha256": digest}

    manifest = {
        "schema": "summit.canonical-source/v1",
        "source_of_truth": "SourceCode/Content/canonical",
        "runtime_dependency_on_external_canonical": False,
        "imported_this_run": bool(args.import_root is not None),
        "imported_families": imported,
        "families": family_manifest,
        "forever_fall": forever,
    }
    manifest_path = content / "CANONICAL_SOURCE.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CANONICAL_MANIFEST={manifest_path}")
    print("CANONICAL_SOURCE_OF_TRUTH=SourceCode/Content/canonical")
    print("EXTERNAL_RUNTIME_DEPENDENCY=NO")
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
