# PT Asset Tool R14 1.0.0 — Release Notes

<!-- PT_HISTORICAL_RELEASE_CONTEXT_2026-09-25 -->

> **Contexto histórico:** este documento preserva evidência/claims da Release 1.0 na data indicada. Para validar o checkout atual, use `docs/engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md` e não trate contagens/flags históricas como resultado de uma execução nova.

Date: 2026-09-14

## Release status

PT Asset Tool 1.0.0 is certified for the tool scope. The final physical `release-1-auto` evidence reports `automatic_gate_status=PASS` with no automatic blockers. The distribution remains safety-locked by default: installing 1.0.0 does **not** authorize writes to the game client or server.

## Certified scope

- Model0.62 physical/static/rigid parsing and writer/reimport regression gates.
- Material writer corpus: 3144 physical assets; status `PASS`.
- Stage0.72 physical/material/texture/normal gates.
- INX/SMB animation and motion semantic corpus.
- Proprietary BMP/TGA codec capability.
- General Asset Census, dependency/reachability evidence, closed-bundle recovery policy, donor lineage and hashes.
- Tier-5 asset/effect/audio diagnostics with PRELOAD separated from ACTIVATION.
- Mechanician canonical UI policy.
- Package/snapshot verification and fail-closed safety controls.

## Safety model

`production_authorized=false`, `client_write_authorized=false` and `server_write_authorized=false` are intentional defaults in the release package. Writer promotion and publish/restore are an explicit operational action, not something the 1.0 package enables silently.

## Content readiness is separate

The tool is certified even though the current Summit target content is not perfect. Model0.62 texture presence remains strict `FAIL` with 19 reference failures. Proprietary texture corpus capability is `PASS` while target-content status is `FAIL`. These remain visible diagnostics; they are not hidden or converted into codec PASS by pathname exceptions.

See `KNOWN_LIMITATIONS_1_0.md` and `RELEASE_1_CERTIFICATION.md`.
