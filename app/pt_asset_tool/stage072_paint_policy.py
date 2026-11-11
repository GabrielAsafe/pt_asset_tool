"""Conservative policy for known missing, unpaintable Stage0.72 textures.

This module does not replace missing texture data. It only allows the private
Blender paint workspace to open with affected faces hidden, while retaining
an explicit incomplete validation state. All other paint failures remain fatal.
"""
from __future__ import annotations

# Verified absent from the provided Etervale corpus; this exception is *not*
# a substitute for a successful dependency audit.
KNOWN_UNRECOVERABLE_TEXTURES = frozenset({'field/ricarten/tem_wall04.bmp'})


def canonical_reference(reference):
    return str(reference or '').replace('\\', '/').lstrip('/').casefold()


def partition_target_failures(failures):
    """Return (blocking_errors, documented_unpaintable_errors), unchanged refs."""
    blockers = []
    known_missing = []
    for row in failures:
        is_known = (str(row.get('reason')) == 'target_image_none'
                    and str(row.get('stage')) == '0'
                    and canonical_reference(row.get('logical')) in KNOWN_UNRECOVERABLE_TEXTURES)
        if is_known:
            known_missing.append(dict(row, resolution='KNOWN_MISSING_UNPAINTABLE_NO_SUBSTITUTE'))
        else:
            blockers.append(row)
    return blockers, known_missing
