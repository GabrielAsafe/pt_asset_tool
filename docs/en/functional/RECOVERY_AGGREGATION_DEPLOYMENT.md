# Recovery, Aggregation, and Deployment

## Recovery evidence

Reference and donor roots are evidence sources. Recovery planning may identify candidates but does not silently copy them into client/server runtime roots.

## Aggregation

Aggregation outputs remain in `pt_build` and are reviewable artifacts. Aggregation is not publication.

## Deployment

Where a writer supports publication, the deployment transaction performs:

1. current-source/hash preflight;
2. target backup;
3. atomic or verified replacement;
4. post-write verification;
5. transaction journal;
6. restore/rollback path;
7. drift refusal when the current target no longer matches the transaction contract.
