from __future__ import annotations

from pathlib import Path
import csv
import json
import struct

from pt_asset_tool.aggregation import build_player_class_aggregation
from pt_asset_tool.skill_contract_census import audit_player_class_contracts


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _write_plain_inx(path: Path, *, state: int = 0x150, marker: bytes = b''):
    size = 95268
    motion_size = 172
    off = 0x18C
    motion_count_off = off + 512 * motion_size
    data = bytearray(size)
    struct.pack_into('<I', data, off + 0, state)
    struct.pack_into('<I', data, off + 8, 10)
    struct.pack_into('<I', data, off + 16, 20)
    struct.pack_into('<I', data, motion_count_off, 1)
    if marker:
        data[-len(marker):] = marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_enabled_legacy_job_is_not_reported_as_missing_implementation(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h',
           '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 2, X },\n')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 1
{ "x", SKILLID_MeleeMastery, "TF10 Melee" },
''')
    _write(ref / 'game' / 'game' / 'CFighterSkillHandler.cpp', r'''
void f(){ case FighterSkill::MeleeMastery: break; }
''')
    _write(client / 'image' / 'Sinimage' / 'skill' / 'Fighter' / 'Button' / 'TF10 Melee.bmp', 'x')
    _write(client / 'image' / 'Sinimage' / 'skill' / 'Fighter' / 'Button' / 'TF10 Melee_.bmp', 'x')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Fighter',),
    )
    cls = result['classes'][0]
    assert cls['runtime_source']['status'] == 'RUNTIME_JOB_ENABLED'
    assert cls['source_contract']['migration_state'] == 'RUNTIME_CLASS_ENABLED_HANDLER_DISCOVERY_INCOMPLETE'
    assert cls['overall_status'] != 'RUNTIME_CLASS_IMPLEMENTATION_MISSING'


def test_aggregation_optional_variants_do_not_block_core_and_are_archived(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    official = tmp_path / 'official'; pteu = tmp_path / 'pteu'

    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h',
           '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 2, X },\n')
    _write(ref / 'shared' / 'character.h', r'''
{ ITEMID_X, CHARACTERCLASS_Fighter, "char\\tmABCD\\b001.ini" },
''')
    _write(ref / 'game' / 'game' / 'itemhandlerstruct.h', r'''
static HeadModelStruct saFighterHeadModel[]
{
  { ITEMID_HairPotionA, 0, "char\\tmABCD\\fh-e01.inf" },
  { ITEMID_HairPotionB, 0, "char\\tmABCD\\fh-e02.inf" },
};
''')
    # Core body config exists in Summit. Both donors have different versions of
    # one optional head; the other optional head exists nowhere.
    _write_plain_inx(client / 'char' / 'tmABCD' / 'b001.inx')
    _write_plain_inx(official / 'char' / 'tmABCD' / 'fh-e01.inx', marker=b'OFFICIAL')
    _write_plain_inx(pteu / 'char' / 'tmABCD' / 'fh-e01.inx', marker=b'PT_EU')

    result = build_player_class_aggregation(
        project, client,
        source_root=current,
        reference_source_root=ref,
        donor_clients=[f'OFFICIAL={official}', f'PT_EU={pteu}'],
        classes=('Fighter',),
        materialize=True,
    )
    assert result['status'] == 'PASS'
    assert result['core_unresolved_count'] == 0
    assert result['action_counts']['RECOVER_PREFERRED_VARIANT'] == 1
    assert result['action_counts']['OPTIONAL_MISSING'] == 1
    assert result['ready_to_apply'] is True

    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    preferred = [x for x in manifest['rows'] if x['action'] == 'RECOVER_PREFERRED_VARIANT'][0]
    assert preferred['source_label'] == 'OFFICIAL'
    assert preferred['variant_count'] == 2
    assert len(preferred['variant_archive']) == 2
    assert all(Path(x['archived_path']).is_file() for x in preferred['variant_archive'])
    assert Path(preferred['staged_path']).read_bytes().endswith(b'OFFICIAL')

    optional_rows = list(csv.DictReader(open(result['optional_gaps'], encoding='utf-8'), delimiter='\t'))
    assert [x['logical_path'] for x in optional_rows] == ['char/tmABCD/fh-e02.inx']
