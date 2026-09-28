# Asset Retention and Cooked DDS Evidence

## Retention model

Retention classifies physical client files using strong roots, directed dependency reachability, ContractGraph evidence, manifests/source evidence, entity catalog/bundle guards, and cooker integrity metadata.

A ContractGraph edge alone is not runtime-root proof.

## Root reachability

Traversal starts only from strong client roots. Output records can include root reachability, distance, sampled root sources, edge details, and component information.

Generic graph-linked assets with no strong-root path remain review-only rather than automatically protected or deleted.

## Monster/NPC protection

Monster/NPC bundles remain fail-closed. Catalog membership or bundle linkage can preserve protection even when strong-root runtime reachability is not proven.

## Cooked DDS evidence

Cooker manifests/failure metadata are imported as integrity/build evidence. Cooker failure does not override retention reachability or authorize deletion.

Documented invalid files can influence quarantine review only when all independent retention gates also allow it.
