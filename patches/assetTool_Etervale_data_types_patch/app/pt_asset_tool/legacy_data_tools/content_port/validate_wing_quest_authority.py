#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

WINGS = {f'QW10{i}' for i in range(1, 7)}
QUEST_ONLY = {'QW103', 'QW106'}

def compact(text: str) -> str:
    return re.sub(r'\s+', '', text)

def main() -> int:
    ap = argparse.ArgumentParser(description='Validate that wings are quest-owned and absent from premium CoinShops')
    ap.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    a = ap.parse_args()
    root = a.repo_root.resolve()
    errors: list[str] = []

    catalog_path = root / 'Content/canonical/commerce/coin_shop.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    configured = {str(x).upper() for x in catalog.get('policy', {}).get('quest_only_item_codes', [])}
    if configured != QUEST_ONLY:
        errors.append(f'coin shop quest_only_item_codes must be {sorted(QUEST_ONLY)}, got {sorted(configured)}')

    offered = []
    for shop, rows in catalog.get('shops', {}).items():
        for row in rows:
            code = str(row.get('code', '')).upper()
            if code in WINGS:
                offered.append((shop, code))
    if offered:
        errors.append(f'wing rewards still offered by premium shop: {offered}')

    quest_table = compact((root / 'Shared/inventory/legacy/SinWingItemLegacyShared.inl').read_text(encoding='utf-8', errors='ignore'))
    expected_steps = [
        ('QW101', '(sinGP1|sin01),(sinGP1|sin02)', '(sinQW1|sin01)'),
        ('QW102', '(sinQW1|sin01),(sinGP1|sin02),(sinGP1|sin03)', '(sinQW1|sin02)'),
        ('QW103', '(sinQW1|sin02),(sinGP1|sin03),(sinGP1|sin04)', '(sinQW1|sin03)'),
        ('QW104', '(sinQW1|sin03),(sinGP1|sin05),(sinGP1|sin06)', '(sinQW1|sin04)'),
        ('QW105', '(sinQW1|sin04),(sinGP1|sin06),(sinGP1|sin07)', '(sinQW1|sin05)'),
        ('QW106', '(sinQW1|sin05),(sinGP1|sin07),(sinGP1|sin08)', '(sinQW1|sin06)'),
    ]
    for code, needs, reward in expected_steps:
        if needs.replace(' ', '') not in quest_table or reward.replace(' ', '') not in quest_table:
            errors.append(f'{code}: legacy wing quest recipe/reward is missing')

    for rel in (
        'SrcGame/src/systems/inventory/legacy/sinInvenTory.cpp',
        'SrcServer/src/systems/inventory/legacy/sinInvenTory.cpp',
    ):
        text = compact((root / rel).read_text(encoding='utf-8', errors='ignore'))
        for i in range(1, 7):
            if f'case(sinQW1|sin0{i}):' not in text:
                errors.append(f'{rel}: missing wing inventory state QW10{i}')
        if 'sWingQuest[Index].NeedItemCode' not in text or 'sWingQuest[Index].Money' not in text:
            errors.append(f'{rel}: wing NPC flow does not use the progression requirements/cost table')

    grant_text = compact((root / 'SrcGame/src/core/client/legacy_sin_runtime/sinSubMain.cpp').read_text(encoding='utf-8', errors='ignore'))
    if 'sWingQuest[pWingItem->Index].ChangeItemCode' not in grant_text:
        errors.append('sinSubMain.cpp: server-side wing crafting does not grant the ChangeItemCode from the quest table')

    for rel in (
        'SrcServer/src/systems/commerce/coin_shop/CoinShop.cpp',
        'SrcServer/src/systems/commerce/coin_shop/CoinShop_T.cpp',
    ):
        text = (root / rel).read_text(encoding='utf-8', errors='ignore')
        if 'QuestOnlyWingCode' not in text or 'QW103' not in text or 'QW106' not in text:
            errors.append(f'{rel}: DB fallback does not filter quest-only wing rewards')

    print(f'premium_wings_in_shop={len(offered)}')
    print('quest_chain=QW101 -> QW102 -> QW103 -> QW104 -> QW105 -> QW106')
    if errors:
        for e in errors:
            print('FAIL', e)
        return 1
    print('PASS no QW101-QW106 wing reward is sold in canonical premium shops')
    print('PASS QW103/QW106 are filtered from legacy DB fallback')
    print('PASS legacy Portal Inventor quest chain still produces QW101 through QW106')
    return 0

if __name__ == '__main__':
    sys.exit(main())
