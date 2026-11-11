from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass, asdict
from typing import Iterable, Iterator, Any


SOURCE_EXTENSIONS = {
    '.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inl', '.inc', '.rc'
}

# Contract evidence must describe the active runtime tree.  Generated build
# trees, dependency SDKs and archived pre-port sources are useful historical
# material, but treating them as active source produces false-positive runtime
# evidence (for example duplicate job rows from old_src_antes_do_porte).
SOURCE_IGNORED_DIR_NAMES = {
    '.git', '.svn', '__pycache__', 'ccache',
    'dependency', 'dependencies', 'deps',
    'old_src_antes_do_porte', 'history', 'vendor',
    # FIX21_CURRENT_SOURCE_SCAN_HYGIENE: patch backups are not active runtime source.
    '.pt_t5_av_patch_backups', '.pt_asset_backups', '.pt_asset_tool_backups',
    'pt_asset_tool', 'dev_tests',
}
SOURCE_IGNORED_DIR_PREFIXES = ('build_', 'build-', 'dist_', 'dist-', '.pt_')


def _source_dir_is_ignored(name: str) -> bool:
    key = str(name).casefold()
    return key in SOURCE_IGNORED_DIR_NAMES or key.startswith(SOURCE_IGNORED_DIR_PREFIXES)


@dataclass(frozen=True)
class SourceTree:
    source_id: str
    role: str
    root: pathlib.Path

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['root'] = str(self.root)
        d['exists'] = self.root.is_dir()
        return d


def _safe_resolve(value: str | pathlib.Path | None) -> pathlib.Path | None:
    if value is None:
        return None
    p = pathlib.Path(value).expanduser()
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def configured_source_roots(
    project_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None = None,
    reference_source_root: str | pathlib.Path | None = None,
) -> list[SourceTree]:
    """Resolve current/reference source trees without scanning the filesystem.

    Resolution priority is explicit argument, environment, then the optional
    project config keys ``source_root`` / ``reference_source_root``.  No source
    tree is required for ordinary pt_asset operations; source-backed contract
    audits fail closed when a requested tree is missing.
    """
    project_root = pathlib.Path(project_root).resolve()
    cfg: dict[str, Any] = {}
    try:
        from .app_config import load_config
        cfg = load_config(project_root)
    except Exception:
        cfg = {}

    # The old Summit C/C++ scanner must not silently treat a persisted legacy
    # source tree as the C# Etervale authority. In unified mode an explicit
    # argument/environment override is still permitted for deliberate legacy
    # investigations, but persisted legacy roots are ignored here.
    from .app_config import configured_etervale_root
    in_unified_mode = configured_etervale_root(project_root) is not None
    configured_current = cfg.get('source_root') if not in_unified_mode else None
    configured_reference = cfg.get('reference_source_root') if not in_unified_mode else None
    current = _safe_resolve(
        source_root
        or os.environ.get('PT_SOURCE_ROOT')
        or (configured_current if isinstance(configured_current, str) else None)
    )
    reference = _safe_resolve(
        reference_source_root
        or os.environ.get('PT_REFERENCE_SOURCE_ROOT')
        or (configured_reference if isinstance(configured_reference, str) else None)
    )

    out: list[SourceTree] = []
    if current is not None:
        out.append(SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current))
    if reference is not None:
        out.append(SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', reference))
    return out


def require_source_trees(
    project_root: pathlib.Path,
    *,
    source_root: str | pathlib.Path | None = None,
    reference_source_root: str | pathlib.Path | None = None,
    require_current: bool = True,
    require_reference: bool = True,
) -> tuple[SourceTree | None, SourceTree | None]:
    trees = configured_source_roots(
        project_root,
        source_root=source_root,
        reference_source_root=reference_source_root,
    )
    by_id = {x.source_id: x for x in trees}
    current = by_id.get('CURRENT_SOURCE')
    reference = by_id.get('EU_REFERENCE_SOURCE')

    if require_current and (current is None or not current.root.is_dir()):
        raise FileNotFoundError(
            'CURRENT_SOURCE_ROOT_NOT_FOUND; pass --source-root, set PT_SOURCE_ROOT, '
            'or configure source_root in pt_build/state/pt_asset_app_config.json'
        )
    if require_reference and (reference is None or not reference.root.is_dir()):
        raise FileNotFoundError(
            'REFERENCE_SOURCE_ROOT_NOT_FOUND; pass --reference-source-root, '
            'set PT_REFERENCE_SOURCE_ROOT, or configure reference_source_root '
            'in pt_build/state/pt_asset_app_config.json'
        )
    return current, reference


def iter_source_files(root: pathlib.Path) -> Iterator[pathlib.Path]:
    root = pathlib.Path(root).resolve()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not _source_dir_is_ignored(d)]
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            p = pathlib.Path(base) / name
            if p.suffix.casefold() in SOURCE_EXTENSIONS:
                yield p


def read_source_text(path: pathlib.Path) -> tuple[str, str]:
    data = pathlib.Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'cp1252'):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode('latin1'), 'latin1'


def source_rel(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return pathlib.Path(path).resolve().relative_to(pathlib.Path(root).resolve()).as_posix()
    except Exception:
        return pathlib.Path(path).as_posix()


def source_tree_summary(tree: SourceTree) -> dict[str, Any]:
    counts: dict[str, int] = {}
    total = 0
    if tree.root.is_dir():
        for p in iter_source_files(tree.root):
            total += 1
            ext = p.suffix.casefold() or '[no_ext]'
            counts[ext] = counts.get(ext, 0) + 1
    return {
        **tree.to_dict(),
        'source_file_count': total,
        'extension_counts': dict(sorted(counts.items())),
    }
