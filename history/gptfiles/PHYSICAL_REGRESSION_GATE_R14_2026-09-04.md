# R14 physical regression gate — 2026-09-04

The environment gate has passed on the physical client. The next automatic gate is:

```bash
cd app
python3 pt_asset.py --client-root "/path/to/client" validate physical-regression-auto
```

This gate is intentionally smaller than `release-1-auto`. It re-runs the exact physical regressions exposed by the first complete client run and adds one current representative per content domain where applicable. It covers Model0.62 material writer + full material corpus, rigid regression assets, static source-authorable witnesses + full static corpus, standalone rigid backfill, bound and standalone animation pose-space, SMB animation census and MONSTER/EFFECT SMB writer samples, the MAP rigid TexLink standalone structural path, and representative proprietary texture codec edit/rebuild.

It writes only under `app/pt_build` and never authorizes production or client writes. The report is `app/pt_build/devtest/physical_regression_auto/result.json`. A PASS means the corrected physical surfaces are ready to return to the full `validate release-1-auto --resume`; it is not by itself a Release 1.0 claim.

Local regression before packaging: 186/186 non-fixture dev tests PASS. Certified rare-writer SHA-256 values are unchanged.
