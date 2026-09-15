# Manual R10 confirmation — 2026-09-02

Environment reported by the user: real Summit Tale client + Blender installation, snapshot R10.

Observed results:

- `python3 pt_asset.py status` => `status: PASS`.
- app-level client discovery resolved `/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente` with source `LEGACY_HOME_DESKTOP_LAYOUT`.
- `python3 pt_asset.py smoke` => `status: PASS`; all listed smoke contracts were true and `client_modified=false`.
- `import char/npc/Bcn02/Bcn02.smd --model-info char/npc/Bcn02/Bcn02f.inx --lod default --reset --no-open`
  failed host-side with:
  `MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES ... missing=['hart']`.
- No Blender-side failure was needed for the invalid Bcn02f/default context in this rerun.

Interpretation:

- R10 client-root discovery fix is externally confirmed in the reported environment.
- R10 missing-LOD-node preflight is externally confirmed for Bcn02f/default.
- This evidence does not promote any writer, runtime acceptance, production authorization, or client-write capability.
