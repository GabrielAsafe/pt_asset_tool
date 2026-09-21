"""Fedora-friendly Python replacements for the historical Management utilities.

The package is deliberately split by capability rather than by EXE.  The reverse
manifest keeps provenance back to the original binaries while the public modules
expose first-party, testable Python operations.
"""

from .reverse_manifest import reverse_status

__all__ = ["reverse_status"]
