from __future__ import annotations
import os, pathlib, shlex
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
                    # Retain the historical fallback so diagnostic commands still report
                    # the expected legacy location instead of crashing during Settings creation.
                    client = pathlib.Path.home() / "Área de Trabalho/summit/Summit Tale Client Full/cliente"
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

        data_registry = root / "data" / "asset_registry"
        legacy_inventory = root / "logs/asset_similarity_v1_1/asset_inventory.json"
        legacy_pairing = root / "logs/asset_family_refine_v2/inx_physical_pairing.csv"
        inventory = data_registry / "asset_inventory.json"
        pairing = data_registry / "inx_physical_pairing.csv"
        # New standalone releases keep operational indices under data/. Older
        # design_work installs remain readable without migration.
        if not inventory.is_file() and legacy_inventory.is_file():
            inventory = legacy_inventory
        if not pairing.is_file() and legacy_pairing.is_file():
            pairing = legacy_pairing

        return cls(
            project_root=root,
            client_root=client,
            inventory=inventory,
            pairing=pairing,
            certifications_dir=root / "certifications",
            work_dir=root / "pt_build/pt_asset_tool",
            server_root=server,
        )

    def blender_command(self) -> list[str]:
        raw = os.environ.get("PT_BLENDER_COMMAND")
        if raw:
            return shlex.split(raw)
        return ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
