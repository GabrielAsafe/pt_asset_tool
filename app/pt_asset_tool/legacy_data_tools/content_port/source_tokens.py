from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CONST_RE = re.compile(r'static\s+const\s+char\s+(\w+)\s*\[\s*\]\s*=\s*("(?:\\.|[^"\\])*")\s*;')


def snake(name: str) -> str:
    s=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',name)
    s=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1_\2',s)
    return s.replace('__','_').lower()


def cpp_string_bytes(literal: str) -> bytes:
    # ast turns \xNN into Unicode chars U+00NN; latin-1 maps them back to bytes.
    value=ast.literal_eval(literal)
    return value.encode('latin-1')


@dataclass(frozen=True)
class TokenSpec:
    family: str
    symbol: str
    canonical: str
    raw: bytes


def extract_constants(path: Path, family: str) -> list[TokenSpec]:
    text=path.read_text(encoding='utf-8',errors='replace')
    out=[]
    for symbol,literal in CONST_RE.findall(text):
        try: raw=cpp_string_bytes(literal)
        except Exception: continue
        if not raw.startswith(b'*'): continue
        out.append(TokenSpec(family,symbol,snake(symbol),raw))
    return out


def load_source_token_maps(source_root: Path) -> dict[str,dict[bytes,str]]:
    paths={
      'character': source_root/'Shared/formats/character_config/CharacterConfigTokens.h',
      'item': source_root/'Shared/formats/item_config/ItemDefinitionReader.inl',
      'spawn': source_root/'Shared/formats/stage_spawn/StageMonsterConfigReader.h',
    }
    maps={k:{} for k in paths}
    for family,path in paths.items():
        for spec in extract_constants(path,family):
            maps[family].setdefault(spec.raw,spec.canonical)

    # English aliases explicitly accepted by the current loaders.
    maps['spawn'].update({
      b'*ACTOR':'actor', b'*BOSS_ACTOR':'boss_actor',
      b'*MAX_ACTOR_POS':'max_actor_position', b'*DELAY':'delay', b'*MAX_ACTOR':'max_actor',
    })
    maps['character'].update({
      b'*J_NAME':'name', b'*J_CHAT':'dialog',
      b'*ClanCustom':'clan_custom', b'*NPCinfo':'npc_info', b'*Rank':'rank',
      b'*BattlePass':'battle_pass', b'*SkinChange':'skin_change', b'*Shop':'shop',
      b'*TShop':'time_shop', b'*Ranking':'ranking', b'*Name':'english_name', b'*NAME':'english_name',
    })
    maps['item'].update({b'*J_NAME':'name', b'*Name':'english_name'})
    return maps
