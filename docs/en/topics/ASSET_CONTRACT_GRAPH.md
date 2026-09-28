# Asset Contract Graph

The ContractGraph stores typed positive relationships discovered from client assets, server definitions, source evidence, manifests, and promoted contracts.

## Important distinction

Graph linkage is not the same as strong-root runtime reachability.

A component may have many internal edges and still have no trusted runtime root. Retention therefore computes directed reachability from strong roots independently of generic graph linkage.

## Uses

- dependency inspection;
- World Closure;
- enrichment/recovery evidence;
- retention reachability;
- root-unreachable component grouping;
- semantic authoring relationship validation.
