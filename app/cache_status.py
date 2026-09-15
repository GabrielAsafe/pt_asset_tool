#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "pt_build" / "incremental_cache_v1" / "entries"
if not ROOT.exists():
    print("INCREMENTAL_CACHE entries=0")
    raise SystemExit(0)
items = []
for p in sorted(ROOT.glob("*.json")):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    items.append(d)
print(f"INCREMENTAL_CACHE entries={len(items)}")
for d in items:
    print(f"{d.get('gate')} status={d.get('status')} source={d.get('source')} created={d.get('created_at')}")
