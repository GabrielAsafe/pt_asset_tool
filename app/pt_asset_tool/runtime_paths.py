from __future__ import annotations

import os
import pathlib
import runpy
import shutil
import sys
from typing import Iterable

APP_ID = "pt-asset-tool"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def external_process_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment suitable for *system* executables.

    PyInstaller prepends its one-file extraction directory to
    ``LD_LIBRARY_PATH`` so bundled extension modules find their private
    libraries.  External applications such as Blender, Wine, xdg-open and
    Real-ESRGAN must instead resolve the host libraries they were built
    against.  Keep the frozen application's own environment untouched and
    sanitize only the child environment.
    """
    env = dict(os.environ if base is None else base)
    if not is_frozen():
        return env
    if os.name == "posix":
        key = "LIBPATH" if sys.platform.startswith("aix") else "LD_LIBRARY_PATH"
        original = env.get(key + "_ORIG")
        if original is not None:
            env[key] = original
        else:
            env.pop(key, None)
    return env


def external_process_command(command: Iterable[str]) -> list[str]:
    """Wrap a Linux system command so it also stays safe in old call sites.

    Most new call sites should prefer ``env=external_process_env()``.  Blender
    command vectors, however, are passed through several legacy modules, so a
    small ``env`` launcher wrapper lets the central resolver sanitize them once
    without touching every Blender workflow.
    """
    cmd = [str(x) for x in command]
    if not cmd or not is_frozen() or os.name != "posix" or sys.platform == "darwin":
        return cmd
    env_bin = shutil.which("env") or "/usr/bin/env"
    key = "LIBPATH" if sys.platform.startswith("aix") else "LD_LIBRARY_PATH"
    original = os.environ.get(key + "_ORIG")
    if original is None:
        return [env_bin, "-u", key, *cmd]
    return [env_bin, f"{key}={original}", *cmd]


def bundle_root() -> pathlib.Path:
    """Read-only application root.

    In source mode this is the app/ directory. In PyInstaller it is the
    extraction/bundle directory exposed through module __file__.
    """
    return pathlib.Path(__file__).resolve().parents[1]


def executable_path() -> pathlib.Path:
    return pathlib.Path(sys.executable if is_frozen() else bundle_root() / "pt_asset.py").resolve()


def executable_dir() -> pathlib.Path:
    return pathlib.Path(sys.executable).resolve().parent if is_frozen() else bundle_root()


def _xdg(env_name: str, fallback: pathlib.Path) -> pathlib.Path:
    raw = os.environ.get(env_name)
    return pathlib.Path(raw).expanduser().resolve() if raw else fallback.expanduser().resolve()


def app_home() -> pathlib.Path | None:
    raw = os.environ.get("PT_ASSET_HOME")
    return pathlib.Path(raw).expanduser().resolve() if raw else None


def state_root() -> pathlib.Path:
    raw = os.environ.get("PT_ASSET_STATE_ROOT")
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    home = app_home()
    if home:
        return home / "state"
    if not is_frozen():
        return bundle_root()
    return _xdg("XDG_DATA_HOME", pathlib.Path.home() / ".local" / "share") / APP_ID


def config_root() -> pathlib.Path:
    raw = os.environ.get("PT_ASSET_CONFIG_ROOT")
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    home = app_home()
    if home:
        return home / "config"
    if not is_frozen():
        return bundle_root() / "pt_build" / "state"
    return _xdg("XDG_CONFIG_HOME", pathlib.Path.home() / ".config") / APP_ID


def cache_root() -> pathlib.Path:
    raw = os.environ.get("PT_ASSET_CACHE_ROOT")
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    home = app_home()
    if home:
        return home / "cache"
    if not is_frozen():
        return bundle_root() / "pt_build" / "cache"
    return _xdg("XDG_CACHE_HOME", pathlib.Path.home() / ".cache") / APP_ID


def persistent_pt_build() -> pathlib.Path:
    if not is_frozen():
        return bundle_root() / "pt_build"
    return state_root() / "pt_build"


def prepare_runtime_layout(project_root: pathlib.Path | None = None) -> dict[str, str | bool]:
    """Prepare writable runtime state without depending on cwd.

    Existing code consistently writes to <project_root>/pt_build. For frozen
    one-file builds the project root is read-only/temporary application data,
    so we project pt_build to a stable XDG/override location with a symlink.
    Source mode is intentionally unchanged.
    """
    root = pathlib.Path(project_root or bundle_root()).resolve()
    config_root().mkdir(parents=True, exist_ok=True)
    cache_root().mkdir(parents=True, exist_ok=True)
    target = persistent_pt_build().resolve()
    target.mkdir(parents=True, exist_ok=True)
    link = root / "pt_build"
    if is_frozen():
        if link.is_symlink():
            try:
                if link.resolve() != target:
                    link.unlink()
            except OSError:
                link.unlink(missing_ok=True)
        if link.exists() and not link.is_symlink():
            raise RuntimeError(f"FROZEN_PT_BUILD_COLLISION:{link}")
        if not link.exists():
            link.symlink_to(target, target_is_directory=True)
    return {
        "frozen": is_frozen(),
        "bundle_root": str(root),
        "state_root": str(state_root()),
        "config_root": str(config_root()),
        "cache_root": str(cache_root()),
        "pt_build": str(target),
        "executable": str(executable_path()),
    }



def repository_resource_root(project_root: pathlib.Path | None = None) -> pathlib.Path:
    root = pathlib.Path(project_root or bundle_root()).resolve()
    return root if is_frozen() else root.parent.resolve()

def app_command(project_root: pathlib.Path | None = None, *args: str) -> list[str]:
    if is_frozen():
        return [str(pathlib.Path(sys.executable).resolve()), *map(str, args)]
    root = pathlib.Path(project_root or bundle_root()).resolve()
    return ["python3", str(root / "pt_asset.py"), *map(str, args)]


def python_script_command(script: pathlib.Path | str, *args: str) -> list[str]:
    script_path = pathlib.Path(script).expanduser().resolve()
    if is_frozen():
        return [str(pathlib.Path(sys.executable).resolve()), "__internal-path", str(script_path), *map(str, args)]
    return ["python3", str(script_path), *map(str, args)]


def invocation_label() -> str:
    return pathlib.Path(sys.executable).name if is_frozen() else "python3 pt_asset.py"


def run_internal_path(script: pathlib.Path | str, argv: Iterable[str]) -> int:
    script_path = pathlib.Path(script).expanduser().resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"INTERNAL_SCRIPT_NOT_FOUND:{script_path}")
    old_argv = sys.argv[:]
    old_path = sys.path[:]
    try:
        sys.argv = [str(script_path), *map(str, argv)]
        script_dir = str(script_path.parent)
        if not sys.path or sys.path[0] != script_dir:
            sys.path.insert(0, script_dir)
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            return int(code) if isinstance(code, int) else (0 if code is None else 1)
        return 0
    finally:
        sys.argv = old_argv
        sys.path[:] = old_path
