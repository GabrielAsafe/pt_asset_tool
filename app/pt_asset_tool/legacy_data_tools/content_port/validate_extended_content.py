#!/usr/bin/env python3
from pathlib import Path
import argparse,json,sys
import jsonschema
PAIRS=[('model_configs/models','model_config.schema.json'),('gameplay_balance','experience_balance.schema.json'),('equipment_sets','equipment_sets.schema.json'),('world_phases','world_phases.schema.json'),('world_story','world_story_campaigns.schema.json'),('head_cosmetics','head_cosmetics.schema.json')]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('canonical',type=Path);ap.add_argument('--schemas',type=Path,default=Path(__file__).parent/'schemas');a=ap.parse_args(); errors=[]; count=0
 for rel,schema_name in PAIRS:
  base=a.canonical/rel
  if not base.exists():continue
  schema=json.loads((a.schemas/schema_name).read_text(encoding='utf-8'))
  files=[base] if base.is_file() else list(base.glob('*.json'))
  for p in files:
   if p.name in ('index.json','report.json'):continue
   count+=1
   try: jsonschema.Draft202012Validator(schema).validate(json.loads(p.read_text(encoding='utf-8')))
   except Exception as exc: errors.append(f'{p}: {exc}')
 print(json.dumps({'validated':count,'errors':len(errors)},ensure_ascii=False))
 for e in errors: print(e,file=sys.stderr)
 raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
