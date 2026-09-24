#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

from pt_asset_tool.runtime_paths import bundle_root, prepare_runtime_layout, run_internal_path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = bundle_root()
    prepare_runtime_layout(root)

    if args and args[0] == "__internal-path":
        if len(args) < 2:
            print("pt_asset_internal_error=SCRIPT_PATH_REQUIRED", file=sys.stderr)
            return 2
        try:
            return run_internal_path(pathlib.Path(args[1]), args[2:])
        except Exception as exc:
            print(f"pt_asset_internal_error={type(exc).__name__}:{exc}", file=sys.stderr)
            return 2

    if not args or args[0] == "gui":
        from pt_asset_gui import main as gui_main
        return int(gui_main(args[1:] if args and args[0] == "gui" else []))

    if args[0] == "cli":
        args = args[1:]

    # pt_asset.py is the consolidated compatibility overlay and historically
    # reads arguments from sys.argv instead of accepting an argv parameter.
    # In the frozen one-file entrypoint we therefore project the requested
    # arguments into sys.argv for the duration of the call, then restore the
    # process state. This keeps source-mode behavior unchanged while making
    # `pt-asset-tool <command>` work without a system Python interpreter.
    from pt_asset import main as cli_main
    old_argv = sys.argv[:]
    try:
        sys.argv = [old_argv[0] if old_argv else str(sys.executable), *args]
        return int(cli_main())
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
