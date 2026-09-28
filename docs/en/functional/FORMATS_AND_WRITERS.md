# Formats and Writers

PT Asset Tool distinguishes parsing/inspection support from promoted write authority.

## Client-side formats

The package contains inspection/validation support for the established model, stage, INX/INI, SMB, texture, effect, and particle families used by the project. A parser or preview does not automatically imply a writer is certified.

## Server-side authoring

Promoted Legacy Management writers cover the supported text/binary contracts used by:

- OpenItem item definitions;
- Monster definitions;
- NPC definitions;
- SPM spawn/actor metadata;
- SPP start-point metadata;
- SPC fixed-NPC metadata.

Each writer uses explicit specs, staging, manifests, verification, and transactional publication where publication is supported.

## Stage geometry

SPM/SPP/SPC metadata editing does not create or rewrite the client Stage0.72 geometry. Stage geometry remains a separate client pipeline.
