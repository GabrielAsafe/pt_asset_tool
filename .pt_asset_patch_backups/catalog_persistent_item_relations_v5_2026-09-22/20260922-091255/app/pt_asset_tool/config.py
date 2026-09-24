from __future__ import annotations
import os, pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    project_root: pathlib.Path
    client_root: pathlib.Path
    inventory: pathlib.Path
    pairing: pathlib.Path
    certifications_dir: pathlib.Path
    work_dir: pathlib.Path
    server_root: pathlib.Path | None = None

    @classmethod
    def discover(cls, project_root: str | pathlib.Path | None = None, client_root: str | pathlib.Path | None = None, server_root: str | pathlib.Path | None = None):
        if project_root is None:
            env = os.environ.get("PT_PROJECT_ROOT")
            if env:
                root = pathlib.Path(env).expanduser().resolve()
            else:
                here = pathlib.Path(__file__).resolve()
                root = here.parent.parent
        else:
            root = pathlib.Path(project_root).expanduser().resolve()

        if client_root is None:
            env = os.environ.get("PT_CLIENT_ROOT")
            if env:
                client = pathlib.Path(env).expanduser().resolve()
            else:
                try:
                    from .app_config import discover_client_root
                    client = discover_client_root(root)
                except Exception:
                    # No machine-specific historical path is baked into a fresh install.
                    # Commands that require a client will report this missing location.
                    client = root / "__client_not_configured__"
        else:
            client = pathlib.Path(client_root).expanduser().resolve()

        if server_root is None:
            env = os.environ.get("PT_SERVER_ROOT")
            if env:
                server = pathlib.Path(env).expanduser().resolve()
            else:
                try:
                    from .app_config import discover_server_root
                    server = discover_server_root(root)
                except Exception:
                    server = None
        else:
            server = pathlib.Path(server_root).expanduser().resolve()

        runtime_state = root / "pt_build" / "state"
        registry_state = runtime_state / "asset_registry"
        inventory = registry_state / "asset_inventory.json"
        pairing = registry_state / "inx_physical_pairing.csv"

        # A fresh installation carries no client-derived inventory. Build it on
        # first use from the configured client and keep it outside the package.
        if client.is_dir():
            from .registry_bootstrap import ensure_runtime_registry
            ensure_runtime_registry(client, inventory, pairing)

        return cls(
            project_root=root,
            client_root=client,
            inventory=inventory,
            pairing=pairing,
            certifications_dir=runtime_state / "certifications",
            work_dir=root / "pt_build/pt_asset_tool",
            server_root=server,
        )

    def blender_command(self) -> list[str]:
        # Keep every Blender-backed feature on the same launcher resolution
        # path as the dependency diagnostic.  This avoids the previous split
        # brain where `pt_asset.py dependencies` could report native Blender
        # READY while particle preview still hard-coded the Flatpak launcher.
        from .dependencies import resolve_blender_command
        command, _ready, _detail = resolve_blender_command(self.project_root)
        return command
