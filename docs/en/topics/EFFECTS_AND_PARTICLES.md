# Effects and Particles

## Effect runtime coverage

The tool scans known legacy effect-loader patterns in source and resolves their referenced physical effect definitions/assets when unambiguous. These resolved paths can become strong runtime roots for retention analysis.

Ambiguous basenames remain review evidence rather than automatic roots.

## Root-unreachable components

Graph-linked client subgraphs that are not reached by strong roots are grouped into `URC-xxxxx` components for review.

## Particle editor

The first-party `.part` editor supports parsing, staged value edits, draft verification, semantic preview planning, and Blender preview when configured. Source client `.part` files are not silently overwritten.
