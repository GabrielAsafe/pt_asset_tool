# v3 reverse-corpus patch

- Adds `.ini` and `.in` to reverse sampling.
- Adds reference-following collection and implicit same-stem INX collection for resolved model INI files.
- Fixes legacy text analysis priority: CP949 is tried before CP1252.
- INX is classified as `LEGACY_120` (67,084) or `MODERN_172` (95,268), matching historical/current source struct math.
- SPP reports current 200-record vs legacy 50-record layouts and active coordinates.
- SPC parses 504-byte records and exposes active NPC name/model/server-definition/position fields.
- SPM recognizes historical Korean tokens and modern English aliases.
- Adds `analyze_reverse_samples.py` and the findings generated from the first 155-sample corpus.
