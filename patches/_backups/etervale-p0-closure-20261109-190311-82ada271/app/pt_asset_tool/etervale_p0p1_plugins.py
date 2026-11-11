"""Optional independent Etervale P0/P1 patch commands. Installed modules only."""
from __future__ import annotations
from importlib import import_module
from importlib.util import find_spec

EXTENSIONS = (
    "etervale_writer_cert",
    "etervale_content_compat",
    "etervale_native_pipeline",
    "etervale_asset_gaps",
    "etervale_quality_gates",
    "etervale_field_contracts",
    "etervale_ui_readiness",
)

def register_extensions(subparsers):
    for suffix in EXTENSIONS:
        module_name = f"{__package__}.{suffix}"
        if find_spec(module_name) is not None:
            import_module(module_name).register(subparsers)
