#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys

from pt_asset_tool.runtime_paths import bundle_root, invocation_label, prepare_runtime_layout


def _project_root() -> pathlib.Path:
    return bundle_root()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pt-asset-tool gui",
        description="PT Asset Tool local graphical catalog/editor shell",
    )
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--project-root", default=str(_project_root()), help=argparse.SUPPRESS)
    parser.add_argument("--client-root", default=None)
    parser.add_argument("--server-root", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = choose an available local port")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--allow-remote", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.version:
        print("1.0.0")
        return 0

    project_root = pathlib.Path(args.project_root).expanduser().resolve()
    prepare_runtime_layout(project_root)
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from pt_asset_tool.ui_app import run_ui

    try:
        return run_ui(
            project_root=project_root,
            client_root=pathlib.Path(args.client_root).expanduser().resolve() if args.client_root else None,
            server_root=pathlib.Path(args.server_root).expanduser().resolve() if args.server_root else None,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            allow_remote=args.allow_remote,
        )
    except (FileNotFoundError, PermissionError) as exc:
        print("PT Asset Tool: client root não encontrado.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("Configure uma vez com:", file=sys.stderr)
        print(f'  {invocation_label()} config set-client-root "/caminho/do/cliente"', file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"PT Asset Tool UI: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
