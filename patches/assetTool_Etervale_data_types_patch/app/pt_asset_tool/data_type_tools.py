"""Isolated legacy data-format tools and read-only Etervale tool discovery.

The imported parsers/compilers remain unmodified. Their runtime packs are NOT
assumed to be supported by the current Etervale C# runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import runpy
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class FormatSpec:
    name: str
    extension: str
    description: str
    inspect_script: str | None
    compile_script: str | None
    input_description: str


FORMAT_SPECS = {
    s.name.lower(): s for s in (
        FormatSpec("SMAP", ".smap", "Map catalog (legacy client/server profiles)", "inspect_maps.py", "compile_maps.py", "summit.map-catalog/v1 JSON"),
        FormatSpec("SCFG", ".scfg", "Monster/NPC/item definitions", "inspect_definitions.py", "compile_definitions.py", "canonical/text directory"),
        FormatSpec("SRES", ".sres", "Text resources and embedded localization", "inspect_text_resources.py", "compile_text_resources.py", "canonical/text directory"),
        FormatSpec("SFLD", ".sfld", "Field runtime: spawns, start points, fixed NPCs", "inspect_field_runtime.py", "compile_field_runtime.py", "multiple canonical directories (manual compiler)"),
        FormatSpec("SGCF", ".sgcf", "Gameplay configuration", "inspect_gameplay_config.py", "compile_gameplay_config.py", "canonical/text directory"),
        FormatSpec("SGRF", ".sgrf", "Gameplay reference data", "inspect_gameplay_reference.py", "compile_gameplay_reference.py", "canonical/gameplay_reference directory"),
        FormatSpec("SCSP", ".scsp", "Coin/time shop catalog", "inspect_coin_shop.py", "compile_coin_shop.py", "canonical/commerce/coin_shop.json"),
        FormatSpec("SSKM", ".sskm", "Skin reform mappings", None, "compile_skin_reforms.py", "canonical/item_profiles/skin_reforms.json"),
        FormatSpec("SSPB", ".sspb", "Legacy compiled stage spawn records", "inspect_stage_spawns.py", None, "legacy shadow JSON"),
        FormatSpec("SLOC", ".sloc", "Legacy localization pack (now embedded in SRES)", "inspect_localization.py", None, "canonical localization JSON"),
        FormatSpec("SCTB", ".sctb", "Legacy generic text shadow pack", "inspect_binary.py", None, "legacy text shadow JSON"),
    )
}

ETERVALE_TOOLS = {
    "PristonTale.AssetDump": "SMD, SMB, INX and bitmap inspection; read-only for individual files",
    "PristonTale.GltfExport": "Model/animation conversion to glTF; output must be staged",
    "PristonTale.DataImport": "Legacy asset copying/unmasking; mutating, not automatically run",
    "PristonTale.VfxImport": "Effect import and VFX authoring; mutating, not automatically run",
    "PristonTale.WorldImport": "World/database import; mutating, not automatically run",
    "PristonTale.WorldJson": "World catalog export, Etervale runtime-dependent",
}


def _base() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "legacy_data_tools"


def _script_path(kind: str, filename: str) -> pathlib.Path:
    candidate = _base() / kind / filename
    if not candidate.is_file():
        raise FileNotFoundError(f"DATA_TOOL_NOT_PACKAGED:{candidate}")
    return candidate


def _run_embedded(script: pathlib.Path, argv: list[str]) -> int:
    """Execute a vetted standalone script with embedded Python, also in PyInstaller.

    Only used for a closed allowlist of individual read-only inspectors and
    candidate compilers. Never invoke the old deployment/orchestration scripts.
    """
    previous_argv = sys.argv
    previous_path = sys.path[:]
    try:
        sys.argv = [str(script), *argv]
        sys.path.insert(0, str(script.parent))
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            print(str(exc.code), file=sys.stderr)
            return 2
        return 0
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_path


def _workspace(a: argparse.Namespace) -> pathlib.Path:
    # The Asset Tool's local pt_build is used, never the game's assets directory.
    root = pathlib.Path(a.root).expanduser().resolve() if a.root else pathlib.Path.cwd().resolve()
    return root / "pt_build" / "data_types"


def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    return path == root or root in path.parents


def _output_path(a: argparse.Namespace, spec: FormatSpec) -> pathlib.Path:
    workspace = _workspace(a).resolve()
    output = (pathlib.Path(a.output).expanduser() if a.output else
              workspace / "compiled" / (a.source.stem + spec.extension))
    output = output.resolve()
    if not _inside(output, workspace):
        raise ValueError(f"OUTPUT_MUST_BE_UNDER_PT_BUILD_DATA_TYPES:{workspace}")
    if output.suffix.lower() != spec.extension:
        raise ValueError(f"OUTPUT_EXTENSION_MISMATCH:{spec.extension}")
    # Refuse symlink outputs, drift, and implicit overwrites.
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"OUTPUT_ALREADY_EXISTS:{output}")
    return output


def list_formats(a: argparse.Namespace) -> int:
    rows = [
        {
            "format": s.name,
            "extension": s.extension,
            "description": s.description,
            "input": s.input_description,
            "inspect": bool(s.inspect_script or s.name == "SSKM"),
            "compile": bool(s.compile_script),
            "authority": "legacy_summit_only_not_verified_in_etervale",
        }
        for s in FORMAT_SPECS.values()
    ]
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for s in rows:
            print(f"{s['format']:5} {s['extension']:6} inspect={s['inspect']} compile={s['compile']} | {s['description']}")
        print("Legacy Summit runtime packs; Etervale C# loader compatibility not established.")
    return 0


def inspect_pack(a: argparse.Namespace) -> int:
    src = a.file.expanduser().resolve(strict=True)
    if not src.is_file():
        raise ValueError("INPUT_MUST_BE_FILE")
    if src.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("INPUT_EXCEEDS_INSPECTION_LIMIT_512MB")
    name = a.format.lower()
    if name == "auto":
        with src.open("rb") as stream:
            magic = stream.read(4)
        name = magic.decode("ascii", "replace").lower()
    spec = FORMAT_SPECS.get(name)
    if not spec:
        raise ValueError(f"UNKNOWN_PACK_FORMAT:{name}")
    with src.open("rb") as stream:
        magic = stream.read(4)
    if magic != spec.name.encode("ascii"):
        raise ValueError(f"FORMAT_MAGIC_MISMATCH:{spec.name}:{magic!r}")
    if spec.name == "SMAP":
        # The imported SMAP inspector exposes checksum validity as a boolean
        # instead of exiting with an error. Do not turn a corrupt pack into PASS.
        from importlib.util import spec_from_file_location, module_from_spec
        script = _script_path("content_port", "inspect_maps.py")
        loader = spec_from_file_location("_pt_smap", script)
        assert loader and loader.loader
        module = module_from_spec(loader)
        loader.loader.exec_module(module)
        info = module.inspect(src)
        if not info.get('sha256_body_valid'):
            raise ValueError('SMAP_BODY_SHA256_MISMATCH')
        print(json.dumps(info, indent=2, sort_keys=True))
        return 0
    if spec.name == "SSKM":
        # Source importer owns the pack header and complete SHA validation.
        script = _script_path("content_port", "compile_skin_reforms.py")
        import importlib.util
        loader = importlib.util.spec_from_file_location("_pt_sskm", script)
        module = importlib.util.module_from_spec(loader)
        assert loader and loader.loader
        loader.loader.exec_module(module)
        rows = module.inspect_pack(src)
        print(json.dumps({"format": "SSKM", "status": "PASS", "mappings": len(rows),
                          "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}, indent=2))
        return 0
    if not spec.inspect_script:
        raise ValueError(f"INSPECTOR_UNAVAILABLE:{spec.name}")
    return _run_embedded(_script_path("content_port", spec.inspect_script), [str(src)])


def compile_pack(a: argparse.Namespace) -> int:
    spec = FORMAT_SPECS[a.format.lower()]
    if not spec.compile_script:
        raise ValueError(f"COMPILER_NOT_ADAPTED:{spec.name}")
    src = a.source.expanduser().resolve(strict=True)
    if not (src.is_file() or src.is_dir()):
        raise ValueError("INPUT_MUST_BE_FILE_OR_DIRECTORY")
    target = _output_path(a, spec)
    # Specific compilers may accept extra flags, but are never allowed arbitrary
    # unvetted arguments. This maintains an inspectable input/output contract.
    argv = [str(src), str(target)]
    if spec.name == "SFLD":
        raise ValueError("USE_COMPILE_FIELD_RUNTIME_WITH_FOUR_CANONICAL_INPUTS")
    if spec.name == "SCFG":
        if a.item_profile:
            argv += ["--item-profile", str(a.item_profile.expanduser().resolve(strict=True))]
        if a.npc_shop_overrides:
            argv += ["--npc-shop-overrides", str(a.npc_shop_overrides.expanduser().resolve(strict=True))]
    code = _run_embedded(_script_path("content_port", spec.compile_script), argv)
    if code:
        return code
    if not target.is_file() or target.read_bytes()[:4] != spec.name.encode("ascii"):
        raise ValueError("COMPILE_OUTPUT_MISSING_OR_WRONG_MAGIC")
    print(json.dumps({"status": "GENERATED_NOT_ETERVALE_CERTIFIED", "format": spec.name,
                      "output": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "input": str(src)}, ensure_ascii=False))
    return 0


def compile_field_runtime(a: argparse.Namespace) -> int:
    spec = FORMAT_SPECS['sfld']
    # Reuse the staging/overwrite protection from the ordinary compiler.
    a.source = a.spawns
    output = _output_path(a, spec)
    inputs = {
        'canonical-spawns': a.spawns,
        'canonical-start-points': a.start_points,
        'canonical-fixed-npcs': a.fixed_npcs,
        'canonical-text': a.text,
    }
    argv = []
    for name, source in inputs.items():
        path = source.expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError(f"CANONICAL_INPUT_MUST_BE_DIRECTORY:{name}:{path}")
        argv.extend([f'--{name}', str(path)])
    argv.append(str(output))
    result = _run_embedded(_script_path('content_port', spec.compile_script), argv)
    if result:
        return result
    if not output.is_file() or output.read_bytes()[:4] != b'SFLD':
        raise ValueError('FIELD_PACK_OUTPUT_MISSING_OR_WRONG_MAGIC')
    print(json.dumps({'status': 'GENERATED_NOT_ETERVALE_CERTIFIED', 'format': 'SFLD',
                      'output': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()},
                     ensure_ascii=False))
    return 0


def schema_catalog(a: argparse.Namespace) -> int:
    root = _base() / 'content_port' / 'schemas'
    rows = []
    for path in sorted(root.glob('*.schema.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        rows.append({'name': path.name.removesuffix('.schema.json'),
                     'schema': doc.get('$id'), 'title': doc.get('title', ''),
                     'file': str(path)})
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def validate_json_schema(a: argparse.Namespace) -> int:
    schema_path = _base() / 'content_port' / 'schemas' / f'{a.schema}.schema.json'
    if not schema_path.is_file() or '/' in a.schema or '\\' in a.schema or '..' in a.schema:
        raise ValueError('UNKNOWN_IMPORTED_SCHEMA')
    data_path = a.json_file.expanduser().resolve(strict=True)
    from importlib.util import spec_from_file_location, module_from_spec
    validator_path = _script_path('content_port', 'validate_canonical_schemas.py')
    spec = spec_from_file_location('_pt_asset_imported_schema_validator', validator_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = module.load(schema_path)
    value = module.load(data_path)
    module.validate(value, schema, str(data_path))
    print(json.dumps({'status': 'PASS', 'schema': a.schema, 'file': str(data_path)}, ensure_ascii=False))
    return 0


def inspect_ase(a: argparse.Namespace) -> int:
    aliases = {
        "summary": "inspect_native_ase_265.py",
        "geometry": "inspect_ase_geometry_uv_266.py",
        "face-material": "inspect_ase_face_material_269.py",
        "materialless": "inspect_ase_materialless_271.py",
        "bones": "inspect_ase_bone_hierarchy_273.py",
        "empty-material": "inspect_ase_empty_material_274.py",
    }
    script = _script_path("ase_inspect", aliases[a.mode])
    return _run_embedded(script, ["--client", str(a.asset_root.expanduser().resolve(strict=True)),
                                  "--source", a.relative_path])


def etervale_tools(a: argparse.Namespace) -> int:
    repo = a.repo_root.expanduser().resolve()
    rows = [
        {"tool": name, "project": f"tools/{name}/{name}.csproj",
         "exists": (repo / "tools" / name / f"{name}.csproj").is_file(),
         "purpose": description, "source": "Etervale C# repo (not copied)",
         "migration": "adapter_only_keep_project_references_in_etervale"}
        for name, description in ETERVALE_TOOLS.items()
    ]
    print(json.dumps({"repo_root": str(repo), "tools": rows}, ensure_ascii=False, indent=2))
    return 0


def etervale_inspect(a: argparse.Namespace) -> int:
    """Use the real Etervale C# readers, without relocating their project refs."""
    repo = a.repo_root.expanduser().resolve(strict=True)
    project = repo / 'tools' / 'PristonTale.AssetDump' / 'PristonTale.AssetDump.csproj'
    if not project.is_file():
        raise FileNotFoundError(f"ETERVALE_TOOL_NOT_FOUND:{project}")
    assets = (repo / 'assets').resolve(strict=True)
    asset = (assets / a.asset).resolve(strict=True)
    if not asset.is_file() or not _inside(asset, assets):
        raise ValueError("ASSET_MUST_BE_FILE_UNDER_ETERVALE_ASSETS")
    cmd = ['dotnet', 'run', '--project', str(project), '-c', 'Release', '--no-build', '--', str(asset)]
    if a.full:
        cmd += ['--full']
    report = {"tool": "PristonTale.AssetDump", "command": cmd, "cwd": str(repo),
              "execute": bool(a.execute), "mutates_assets": False}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not a.execute:
        return 0
    if not shutil.which('dotnet'):
        raise FileNotFoundError('DOTNET_NOT_INSTALLED')
    return subprocess.run(cmd, cwd=repo, check=False).returncode


def register_parser(subparsers) -> None:
    tools = subparsers.add_parser('data-types', help='inspect/compile legacy content formats and probe Etervale-native asset readers')
    sub = tools.add_subparsers(dest='data_type_cmd', required=True)
    x = sub.add_parser('list', help='list migrated data formats and capabilities')
    x.add_argument('--json', action='store_true')
    x.set_defaults(func=list_formats)
    x = sub.add_parser('inspect', help='read-only inspection of a Summit legacy binary pack')
    x.add_argument('file', type=pathlib.Path)
    x.add_argument('--format', choices=['auto', *FORMAT_SPECS], default='auto')
    x.set_defaults(func=inspect_pack)
    x = sub.add_parser('compile', help='compile canonical legacy data only into pt_build/data_types')
    x.add_argument('format', choices=[n for n, s in FORMAT_SPECS.items() if s.compile_script and n != 'sfld'])
    x.add_argument('source', type=pathlib.Path)
    x.add_argument('--output', type=pathlib.Path, help='must be under --root/pt_build/data_types')
    x.add_argument('--item-profile', type=pathlib.Path)
    x.add_argument('--npc-shop-overrides', type=pathlib.Path)
    x.set_defaults(func=compile_pack)
    x = sub.add_parser('compile-field', help='compile SFLD from four canonical JSON directories into pt_build')
    x.add_argument('--spawns', type=pathlib.Path, required=True)
    x.add_argument('--start-points', type=pathlib.Path, required=True)
    x.add_argument('--fixed-npcs', type=pathlib.Path, required=True)
    x.add_argument('--text', type=pathlib.Path, required=True)
    x.add_argument('--output', type=pathlib.Path)
    x.set_defaults(func=compile_field_runtime)
    x = sub.add_parser('schemas', help='show imported JSON schemas for legacy canonical authoring')
    x.set_defaults(func=schema_catalog)
    x = sub.add_parser('validate-json', help='validate a canonical JSON using its imported type schema')
    x.add_argument('--schema', required=True)
    x.add_argument('json_file', type=pathlib.Path)
    x.set_defaults(func=validate_json_schema)
    x = sub.add_parser('ase-inspect', help='read-only ASE inspection within a source asset directory')
    x.add_argument('--asset-root', type=pathlib.Path, required=True)
    x.add_argument('--relative-path', required=True)
    x.add_argument('--mode', choices=('summary', 'geometry', 'face-material', 'materialless', 'bones', 'empty-material'), default='summary')
    x.set_defaults(func=inspect_ase)
    x = sub.add_parser('etervale-tools', help='discover C# format tools in a unified Etervale source tree')
    x.add_argument('--repo-root', type=pathlib.Path, required=True)
    x.set_defaults(func=etervale_tools)
    x = sub.add_parser('etervale-inspect', help='plan or explicitly execute the Etervale AssetDump reader')
    x.add_argument('--repo-root', type=pathlib.Path, required=True)
    x.add_argument('--asset', required=True, help='asset path relative to Etervale assets/')
    x.add_argument('--full', action='store_true')
    x.add_argument('--execute', action='store_true', help='explicitly launch previously built native C# tool')
    x.set_defaults(func=etervale_inspect)
