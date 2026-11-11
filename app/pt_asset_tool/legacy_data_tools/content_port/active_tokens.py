from __future__ import annotations
import re
from pathlib import Path
from source_tokens import cpp_string_bytes, load_source_token_maps

# Extract literal tokens compared directly against the legacy `decode` buffer.
CMP_RE=re.compile(r'lstrcmpi?\s*\(\s*decode\s*,\s*("(?:\\.|[^"\\])*")\s*\)')

def active_tokens_from_file(path:Path)->set[bytes]:
    if not path.exists(): return set()
    text=path.read_text(encoding='utf-8',errors='replace')
    out=set()
    for lit in CMP_RE.findall(text):
        try: out.add(cpp_string_bytes(lit))
        except Exception: pass
    return out

def load_active_token_sets(source_root:Path)->dict[str,set[bytes]]:
    files={
      'character': source_root/'Shared/formats/character_config/LegacyCharacterConfigExact_server.inl',
      'item': source_root/'Shared/formats/item_config/LegacyItemDefinitionExact_server.inl',
      'spawn': source_root/'Shared/formats/stage_spawn/LegacyStageSpawnExact_server.inl',
    }
    out={k:active_tokens_from_file(v) for k,v in files.items()}
    # Once a family is bridged behind a content-source abstraction, the exact wrapper
    # intentionally no longer contains the old token comparisons. The source-derived
    # token map then becomes the auditable contract for that family. Spawn is the first
    # migrated slice and its map contains exactly the CP949 + ASCII aliases accepted by
    # LegacyStageSpawnContentSource.
    maps=load_source_token_maps(source_root)
    if len(out['spawn']) < 5:
        out['spawn']=set(maps['spawn'])
    return out
