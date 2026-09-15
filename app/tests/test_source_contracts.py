from __future__ import annotations

from pathlib import Path
import json

from pt_asset_tool.source_catalog import SourceTree
from pt_asset_tool.source_evidence import parse_reference_skill_catalog, scan_source_evidence
from pt_asset_tool.skill_contract_census import audit_player_class_contracts


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_reference_skill_and_sound_parser(tmp_path: Path):
    ref = tmp_path / 'ref'
    _write(ref / 'shared' / 'skill.h', r'''
#define SKILL_SOUND_V_THRONE 0x4803 // VenomThorn
//Assassin Skills - Tier 1
{ "x", SKILLID_Stinger, "TA10 Stingger" },
//Tier 2
{ "x", SKILLID_VenomThorn, "TA20 V_Throne", "As2_VENOM.tga" },
//Shaman Skills - Tier 1
{ "x", SKILLID_DarkBolt, "MS10 Darkbolt" },
//Tier 2
{ "x", SKILLID_AdventMigal, "MS30 A_Migal", "Sh2_A_MIGAL.tga" },
wav\Effects\Skill\Tempskron\VenomThorn 01.wav 0x4803
''')
    _write(ref / 'game' / 'game' / 'CAssassinSkillHandler.cpp', r'''
void CAssassinSkillHandler::LoadParticle(){ PARTICLE->Load("Effect\\Particle\\Script\\Alas_Cast.part"); }
void f(){
case AssassinSkill::VenomThorn:
  SKILLMANAGERHANDLER->SkillPlaySound(SKILL_SOUND_V_THRONE, point3D);
}
''')
    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    rows = parse_reference_skill_catalog(tree)
    assert [x['skill_id'] for x in rows] == [
        'SKILLID_Stinger', 'SKILLID_VenomThorn', 'SKILLID_DarkBolt', 'SKILLID_AdventMigal'
    ]
    ev = scan_source_evidence(tree)
    venom = [x for x in ev['skill_cases'] if x['skill_name'] == 'VenomThorn'][0]
    assert venom['sounds'][0]['path'] == 'wav/Effects/Skill/Tempskron/VenomThorn 01.wav'
    assert ev['class_parts']['Assassin'][0]['value'] == 'Effect/Particle/Script/Alas_Cast.part'


def test_player_class_contract_audit_is_read_only_and_classifies_donor(tmp_path: Path):
    project = tmp_path / 'project'
    project.mkdir()
    current = tmp_path / 'current_source'
    ref = tmp_path / 'reference_source'
    client = tmp_path / 'client'
    donor = tmp_path / 'donor'

    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h',
           '{ "Assassine", "Assassine", JOB_CODE_ASSASSINE, 9, X },\n'
           '{ "Shaman", "Shaman", JOB_CODE_SHAMAN, 10, X },\n')

    _write(ref / 'shared' / 'skill.h', r'''
#define SKILL_SOUND_V_THRONE 0x4803
//Assassin Skills - Tier 1
{ "x", SKILLID_Stinger, "TA10 Stingger" },
//Tier 2
{ "x", SKILLID_VenomThorn, "TA20 V_Throne", "As2_VENOM.tga" },
//Shaman Skills - Tier 1
{ "x", SKILLID_DarkBolt, "MS10 Darkbolt" },
//Tier 2
{ "x", SKILLID_AdventMigal, "MS30 A_Migal", "Sh2_A_MIGAL.tga" },
wav\Effects\Skill\Tempskron\VenomThorn 01.wav 0x4803
''')
    _write(ref / 'game' / 'game' / 'CAssassinSkillHandler.cpp', r'''
void CAssassinSkillHandler::LoadParticle(){ PARTICLE->Load("Effect\\Particle\\Script\\VenomThorn.part"); }
void f(){ case AssassinSkill::VenomThorn: SKILLMANAGERHANDLER->SkillPlaySound(SKILL_SOUND_V_THRONE, p); }
''')

    # Target has one required button and the audio; donor completes the other UI
    # button plus the explicit TGA and particle closure.
    _write(client / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger.bmp', 'button')
    _write(client / 'wav' / 'Effects' / 'Skill' / 'Tempskron' / 'VenomThorn 01.wav', 'wav')
    _write(donor / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger_.bmp', 'hover')
    _write(donor / 'As2_VENOM.tga', 'tga')
    _write(donor / 'Effect' / 'Particle' / 'Script' / 'VenomThorn.part', 'Texture "venom.dds"\n')
    _write(donor / 'Effect' / 'Particle' / 'Script' / 'venom.dds', 'dds')

    result = audit_player_class_contracts(
        project,
        client,
        source_root=current,
        reference_source_root=ref,
        donor_clients=[f'OFFICIAL={donor}'],
        classes=('Assassin',),
    )
    assert result['status'] == 'PASS'
    assert result['hashes_calculated'] == 0
    assert result['classes'][0]['runtime_source']['status'] == 'RUNTIME_DISABLED_BY_MAX_JOBNUM'
    assert result['asset_status_counts']['PRESENT_TARGET'] >= 2
    assert result['asset_status_counts']['RECOVERABLE_REFERENCE'] >= 2
    assert Path(result['graph']).is_file()
    assert Path(result['report']).is_file()


def test_source_scanner_ignores_archives_and_reads_mixed_case_spellings(tmp_path: Path):
    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'game' / 'CAssassinSkillHandler.cpp', r'''
void f(){
  switch(x){
    case SKILLID_Stinger: UNITDATA->Animate(ANIMATIONTYPE_Skill); break;
    case ESkillID::SKILLID_ShadowBlink: return SHADOWBLINKHANDLER->OnCastAnimationStart(x);
    case AssassinSkill::Wisp: SKILLMANAGERHANDLER->AssaParticle_AttackSkillEffect("Wisp1", x); break;
  }
}
''')
    _write(current / 'old_src_antes_do_porte' / 'game' / 'CAssassinSkillHandler.cpp', r'''
void old(){ case AssassinSkill::VenomThorn: break; }
''')
    tree = SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current)
    ev = scan_source_evidence(tree)
    names = {x['skill_name'] for x in ev['skill_cases'] if x['class'] == 'Assassin'}
    assert names == {'Stinger', 'ShadowBlink', 'Wisp'}
    shadow = [x for x in ev['skill_cases'] if x['skill_name'] == 'ShadowBlink'][0]
    assert shadow['delegates'] == ['SHADOWBLINKHANDLER']
    stinger = [x for x in ev['skill_cases'] if x['skill_name'] == 'Stinger'][0]
    assert stinger['animations'] == ['ANIMATIONTYPE_Skill']
    wisp = [x for x in ev['skill_cases'] if x['skill_name'] == 'Wisp'][0]
    assert wisp['effect_tokens'] == ['Wisp1']


def test_player_class_report_does_not_equate_buttons_with_class_completeness(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h',
           '{ "Assassine", "Assassine", JOB_CODE_ASSASSINE, 9, X },\n')
    _write(ref / 'shared' / 'skill.h', r'''
//Assassin Skills - Tier 1
{ "x", SKILLID_Stinger, "TA10 Stingger" },
''')
    _write(client / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger.bmp', 'x')
    _write(client / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger_.bmp', 'x')
    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Assassin',),
    )
    cls = result['classes'][0]
    assert cls['proven_required_assets_complete'] is True
    assert cls['overall_status'] == 'RUNTIME_BLOCKED_MAX_JOBNUM'
    assert cls['source_contract']['reference_state'] == 'REFERENCE_RUNTIME_SOURCE_NOT_DETECTED'


def _write_plain_inx(path: Path, *, state: int = 0x150):
    import struct
    size = 95268
    motion_size = 172
    off = 0x18C
    motion_count_off = off + 512 * motion_size
    data = bytearray(size)
    struct.pack_into('<I', data, off + 0, state)
    struct.pack_into('<I', data, off + 8, 10)
    struct.pack_into('<I', data, off + 16, 20)
    struct.pack_into('<I', data, off + 0xA0, 0)
    data[off + 0xA4] = 0
    struct.pack_into('<i', data, off + 0xA8, 0)
    struct.pack_into('<I', data, motion_count_off, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_reference_class_config_parser_and_motion_state_contract(tmp_path: Path):
    from pt_asset_tool.contract_graph import ContractGraph
    from pt_asset_tool.player_class_motion_contract import parse_reference_class_configs, audit_class_motion_contract
    from pt_asset_tool.skill_contract_census import PhysicalSource

    ref = tmp_path / 'ref'
    client = tmp_path / 'client'
    project = tmp_path / 'project'; project.mkdir()
    _write(ref / 'shared' / 'character.h', r'''
{ ITEMID_X, CHARACTERCLASS_Assassin, "char\\tmABCD\\e001.ini" },
{ ITEMID_Y, CHARACTERCLASS_Shaman, "char\\tmABCD\\me001.ini" },
''')
    _write(ref / 'game' / 'game' / 'itemhandlerstruct.h', r'''
static HeadModelStruct saAssassinHeadModel[]
{
  { ITEMID_HairPotionA, 0, "char\\tmABCD\\tfh-e01.inf" },
};
static HeadModelStruct saShamanHeadModel[]
{
  { ITEMID_HairPotionA, 0, "char\\tmABCD\\mmh-e01.inf" },
};
''')
    _write_plain_inx(client / 'char' / 'tmABCD' / 'e001.inx')

    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    rows = parse_reference_class_configs(tree)
    assert {(x['class'], x['kind'], x['logical_inx']) for x in rows} == {
        ('Assassin', 'BODY_BASE_CONFIG', 'char/tmABCD/e001.inx'),
        ('Assassin', 'HEAD_CONFIG', 'char/tmABCD/tfh-e01.inx'),
        ('Shaman', 'BODY_BASE_CONFIG', 'char/tmABCD/me001.inx'),
        ('Shaman', 'HEAD_CONFIG', 'char/tmABCD/mmh-e01.inx'),
    }

    target = PhysicalSource('SUMMIT_CLIENT', client)
    _ = target.resolver.index
    graph = ContractGraph()
    graph.ensure_node('PLAYER_CLASS:Assassin', 'PLAYER_CLASS', 'Assassin')
    graph.ensure_node('SKILL:Assassin:SKILLID_Stinger', 'SKILL', 'Stinger')
    report = audit_class_motion_contract(
        project, tree, 'Assassin', target, [], graph,
        skill_contracts=[{
            'skill_id': 'SKILLID_Stinger', 'skill_name': 'Stinger',
            'animation_tokens': ['ANIMATIONTYPE_Skill'],
        }],
    )
    assert report['dominant_motion_root'] == 'char/tmABCD/e001.inx'
    assert report['dominant_skill_motion_record_count'] == 1
    assert report['status'] == 'MOTION_SMB_NOT_PAIRED'
    assert report['specific_skill_motion_record_certified'] is False
    assert 'Stinger' in report['skills_requesting_animationtype_skill']


def _write_link_inx(path: Path, logical_target: str):
    import struct
    from pt_asset_tool.motion_core import inx_speed_sum

    size = 95268
    motion_size = 172
    off = 0x18C
    motion_count_off = off + 512 * motion_size
    data = bytearray(size)
    code = inx_speed_sum(logical_target)
    c0 = code & 0xff
    c1 = (code >> 8) & 0xff
    c2 = (code >> 16) & 0xff
    c3 = (code >> 24) & 0xff
    # Inverse of _inx_reconstruct_codes for link_code; unused file-code bytes
    # stay zero because this fixture tests only the verified LinkFile contract.
    file_type_kw = c3 | (c0 << 16)
    link_kw = c2 | (c1 << 16)
    struct.pack_into('<I', data, motion_count_off, 0)
    struct.pack_into('<I', data, motion_count_off + 4, file_type_kw)
    struct.pack_into('<I', data, motion_count_off + 8, link_kw)
    serialized = logical_target[:-1] if logical_target.casefold().endswith('.inx') else logical_target
    raw = serialized.encode('latin1')[:63]
    data[motion_count_off + 12:motion_count_off + 12 + len(raw)] = raw
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_motion_contract_follows_only_verified_inx_link(tmp_path: Path):
    from pt_asset_tool.contract_graph import ContractGraph
    from pt_asset_tool.player_class_motion_contract import audit_class_motion_contract
    from pt_asset_tool.skill_contract_census import PhysicalSource

    project = tmp_path / 'project'; (project / 'data' / 'asset_registry').mkdir(parents=True)
    ref = tmp_path / 'ref'; client = tmp_path / 'client'
    _write(ref / 'shared' / 'character.h', r'''
{ ITEMID_X, CHARACTERCLASS_Assassin, "char\\tmABCD\\e001.ini" },
''')
    target_logical = r'char\tmABCD\M6Bip.inx'
    _write_link_inx(client / 'char' / 'tmABCD' / 'e001.inx', target_logical)
    _write_plain_inx(client / 'char' / 'tmABCD' / 'M6Bip.inx')

    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    target = PhysicalSource('SUMMIT_CLIENT', client)
    graph = ContractGraph(); graph.ensure_node('PLAYER_CLASS:Assassin', 'PLAYER_CLASS', 'Assassin')
    report = audit_class_motion_contract(project, tree, 'Assassin', target, [], graph)
    assert report['dominant_motion_root'].casefold() == 'char/tmabcd/m6bip.inx'
    assert report['link_status_counts']['VERIFIED'] == 1
    assert report['dominant_skill_motion_record_count'] == 1
    assert report['status'] == 'MOTION_SMB_NOT_PAIRED'


def test_skill_motion_registry_is_bounded_and_ignores_commented_current_rows(tmp_path: Path):
    from pt_asset_tool.source_evidence import parse_skill_motion_registry

    ref = tmp_path / 'ref'
    current = tmp_path / 'current'
    _write(ref / 'shared' / 'skill.h', r'''
enum ESkillPlayID {
  SKILLPLAYID_Undefined = 0x00,
  SKILLPLAYID_T11 = 0x1A,
  SKILLPLAYID_T12 = 0x1B,
};
''')
    _write(ref / 'game' / 'game' / 'SkillManager.h', r'''
static SkillData saSkillData[4] = {
  { "xxxxxxxxxxxxx", SKILLPLAYID_Undefined },
  //Assassin
  { "Stingger", SKILLPLAYID_T11 },
  { "RunningHit", SKILLPLAYID_T12 },
  { 0, 0 },
};
static SkillSoundData saSoundData[2]
{
  { "wav\\Effects\\Skill\\Assassin\\Stingger.wav", 0x4800 },
  { "wav\\Effects\\Skill\\Assassin\\RunningHit.wav", 0x4801 },
};
''')
    _write(current / 'SrcGame' / 'src' / 'core' / 'data' / 'legacy_loader' / 'SkillDataCode.inl', r'''
SKILL_DATA_CODE SkillDataCode[] = {
  { "xxxxxxxxxxxxx", 0 },
  { "ExistingOne", SKILL_PLAY_T11 },
  ////ASSASSIN
  //{ "Stingger", SKILL_PLAY_STINGGER },
  //{ "RunningHit", SKILL_PLAY_RUNNING_HIT },
  { "", 0 }
};
''')
    _write(current / 'SrcGame' / 'src' / 'systems' / 'gameplay' / 'character' / 'core' / 'character.h',
           '#define SKILL_PLAY_T11 0x11\n')

    rr = parse_skill_motion_registry(SourceTree('REF', 'REFERENCE', ref))
    cr = parse_skill_motion_registry(SourceTree('CUR', 'CURRENT', current))
    assert rr['entry_count'] == 3
    assert [(x['index'], x['name']) for x in rr['entries']] == [
        (0, 'xxxxxxxxxxxxx'), (1, 'Stingger'), (2, 'RunningHit')
    ]
    assert rr['class_counts'] == {'Assassin': 2}
    # Most importantly, the following WAV table must not become SkillData rows.
    assert not any(x['name'].casefold().endswith('.wav') for x in rr['entries'])
    assert cr['entry_count'] == 2
    assert [x['name'] for x in cr['entries']] == ['xxxxxxxxxxxxx', 'ExistingOne']


def test_inx_skill_code_list_exactly_binds_reference_skill_motion(tmp_path: Path):
    import struct
    from pt_asset_tool.contract_graph import ContractGraph
    from pt_asset_tool.player_class_motion_contract import audit_class_motion_contract
    from pt_asset_tool.skill_contract_census import PhysicalSource

    project = tmp_path / 'project'; project.mkdir()
    ref = tmp_path / 'ref'; client = tmp_path / 'client'
    _write(ref / 'shared' / 'character.h', r'''
{ ITEMID_X, CHARACTERCLASS_Assassin, "char\\tmABCD\\e001.ini" },
''')

    # One modern MotionInfo record in SKILL state. SkillCodeList[0] is byte 1,
    # so it must resolve to registry index 1 and no other skill.
    size = 95268; motion_size = 172; off = 0x18C
    motion_count_off = off + 512 * motion_size
    data = bytearray(size)
    struct.pack_into('<I', data, off + 0, 0x150)
    struct.pack_into('<I', data, off + 8, 10)
    struct.pack_into('<I', data, off + 16, 20)
    data[off + 0x94] = 1
    data[off + 0x95] = 0
    struct.pack_into('<I', data, motion_count_off, 1)
    p = client / 'char' / 'tmABCD' / 'e001.inx'
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)

    ref_registry = {
        'status': 'PASS', 'source_file': 'game/game/SkillManager.h',
        'registry_kind': 'EU_SKILLMANAGER_SASKILLDATA', 'entry_count': 2,
        'selector_witnesses': [],
        'entries': [
            {'index': 0, 'name': 'xxxxxxxxxxxxx', 'play_token': 'SKILLPLAYID_Undefined', 'play_id': 0, 'class': '', 'class_ordinal': 0},
            {'index': 1, 'name': 'Stingger', 'play_token': 'SKILLPLAYID_T11', 'play_id': 0x1A, 'class': 'Assassin', 'class_ordinal': 1},
        ],
    }
    cur_registry = {
        'status': 'PASS', 'source_file': 'SkillDataCode.inl',
        'registry_kind': 'LEGACY_SKILLDATACODE', 'entry_count': 2,
        'selector_witnesses': [],
        'entries': [
            {'index': 0, 'name': 'xxxxxxxxxxxxx', 'play_token': '0', 'play_id': 0, 'class': '', 'class_ordinal': 0},
            {'index': 1, 'name': 'OtherSkill', 'play_token': 'SKILL_PLAY_OTHER', 'play_id': 7, 'class': '', 'class_ordinal': 0},
        ],
    }

    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    target = PhysicalSource('SUMMIT_CLIENT', client)
    graph = ContractGraph(); graph.ensure_node('PLAYER_CLASS:Assassin', 'PLAYER_CLASS', 'Assassin')
    graph.ensure_node('SKILL:Assassin:SKILLID_Stinger', 'SKILL', 'Stinger')
    report = audit_class_motion_contract(
        project, tree, 'Assassin', target, [], graph,
        skill_contracts=[{
            'skill_id': 'SKILLID_Stinger', 'skill_name': 'Stinger',
            'tier': 1, 'tier_slot': 1, 'class_ordinal': 1,
            'animation_tokens': ['ANIMATIONTYPE_Skill'],
        }],
        reference_motion_registry=ref_registry,
        current_motion_registry=cur_registry,
    )
    assert report['specific_skill_motion_record_certified'] is True
    assert report['exact_skill_motion_binding_count'] == 1
    binding = report['skill_motion_bindings'][0]
    assert binding['binding_status'] == 'REFERENCE_SKILLCODELIST_EXACT'
    assert binding['matching_motion_indices'] == [0]
    assert binding['matching_motion_records'][0]['skill_code_list'] == [1]
    assert binding['current_runtime_registry_status'] == 'INDEX_POINTS_TO_DIFFERENT_SKILL'
    assert report['runtime_motion_selectability_status'] == 'CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES'


def test_all_class_catalog_uses_runtime_skill_folder_aliases(tmp_path: Path):
    ref = tmp_path / 'ref'
    _write(ref / 'shared' / 'skill.h', r'''
//Mechanician Skills - Tier 1
{ "x", SKILLID_ExtremeShield, "TM10 Ex_shield" },
//Fighter Skills - Tier 1
{ "x", SKILLID_MeleeMastery, "TF10 Melee" },
''')
    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    rows = parse_reference_skill_catalog(tree, ('Mechanician', 'Fighter'))
    by_class = {x['class']: x for x in rows}
    assert '/skill/Mecha/Button/' in by_class['Mechanician']['button_normal']
    assert '/skill/Fighter/Button/' in by_class['Fighter']['button_normal']


def test_reference_class_config_parser_supports_original_eight_classes(tmp_path: Path):
    from pt_asset_tool.player_class_motion_contract import parse_reference_class_configs
    ref = tmp_path / 'ref'
    _write(ref / 'shared' / 'character.h', r'''
{ ITEMID_None, CHARACTERCLASS_Fighter, "char\\tmABCD\\B001.ini" },
{ ITEMID_None, CHARACTERCLASS_Mechanician, "char\\tmABCD\\A001.ini" },
{ ITEMID_None, CHARACTERCLASS_Priestess, "char\\tmABCD\\mC001.ini" },
''')
    _write(ref / 'game' / 'game' / 'itemhandlerstruct.h', r'''
static HeadModelStruct saFighterHeadModel[] { { ITEMID_X, 0, "char\\tmABCD\\tfh-b01.inf" }, };
static HeadModelStruct saMechanicianHeadModel[] { { ITEMID_X, 0, "char\\tmABCD\\tfh-a01.inf" }, };
static HeadModelStruct saPriestessHeadModel[] { { ITEMID_X, 0, "char\\tmABCD\\mfh-c01.inf" }, };
''')
    tree = SourceTree('EU_REFERENCE_SOURCE', 'REFERENCE_RUNTIME_SOURCE', ref)
    rows = parse_reference_class_configs(tree, ('Fighter','Mechanician','Priestess'))
    got = {(x['class'], x['logical_inx']) for x in rows}
    assert ('Fighter', 'char/tmABCD/B001.inx') in got
    assert ('Mechanician', 'char/tmABCD/A001.inx') in got
    assert ('Priestess', 'char/tmABCD/mC001.inx') in got


def test_player_class_aggregator_dedupes_identical_donors_and_materializes_overlay(tmp_path: Path):
    from pt_asset_tool.aggregation import build_player_class_aggregation
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    d1 = tmp_path / 'official'; d2 = tmp_path / 'pteu'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h',
           '{ "Assassine", "Assassine", JOB_CODE_ASSASSINE, 9, X },\n')
    _write(ref / 'shared' / 'skill.h', r'''
//Assassin Skills - Tier 1
{ "x", SKILLID_Stinger, "TA10 Stingger" },
''')
    for root in (d1, d2):
        _write(root / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger.bmp', 'same-normal')
        _write(root / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger_.bmp', 'same-hover')
    result = build_player_class_aggregation(
        project, client,
        source_root=current, reference_source_root=ref,
        donor_clients=[f'OFFICIAL={d1}', f'PT_EU={d2}'],
        classes=('Assassin',), materialize=True,
    )
    assert result['status'] == 'PASS'
    assert result['unresolved_count'] == 0
    assert result['action_counts']['RECOVER_DEDUPED'] == 2
    assert result['materialized_recovery_count'] == 2
    overlay = Path(result['overlay_root'])
    assert (overlay / 'image/Sinimage/skill/Assassin/Button/TA10 Stingger.bmp').read_text() == 'same-normal'
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['client_modified'] is False
    assert manifest['server_modified'] is False
    assert manifest['ready_to_apply'] is True


def test_player_class_aggregator_blocks_variant_donor_conflict(tmp_path: Path):
    from pt_asset_tool.aggregation import build_player_class_aggregation
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    d1 = tmp_path / 'official'; d2 = tmp_path / 'pteu'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(ref / 'shared' / 'skill.h', r'''
//Assassin Skills - Tier 1
{ "x", SKILLID_Stinger, "TA10 Stingger" },
''')
    _write(d1 / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger.bmp', 'official-variant')
    _write(d2 / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger.bmp', 'pteu-variant')
    # Hover is identical so the fixture proves that only divergent candidates
    # remain blocked while safe assets can still stage.
    for root in (d1, d2):
        _write(root / 'image' / 'Sinimage' / 'skill' / 'Assassin' / 'Button' / 'TA10 Stingger_.bmp', 'same-hover')
    result = build_player_class_aggregation(
        project, client,
        source_root=current, reference_source_root=ref,
        donor_clients=[f'OFFICIAL={d1}', f'PT_EU={d2}'],
        classes=('Assassin',), materialize=True,
    )
    assert result['status'] == 'PASS'
    assert result['aggregate_state'] == 'REVIEW_REQUIRED'
    assert result['action_counts']['CONFLICT'] == 1
    assert result['action_counts']['RECOVER_DEDUPED'] == 1
    assert result['unresolved_count'] == 1
    overlay = Path(result['overlay_root'])
    assert not (overlay / 'image/Sinimage/skill/Assassin/Button/TA10 Stingger.bmp').exists()
    assert (overlay / 'image/Sinimage/skill/Assassin/Button/TA10 Stingger_.bmp').is_file()


def test_current_effect_token_resolves_particle_registry_basename(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'; donor = tmp_path / 'donor'
    client.mkdir(); donor.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 1, X },\n')
    _write(current / 'SrcGame' / 'game' / 'CFighterSkillHandler.cpp', r'''
void f(){ case FighterSkill::MeleeMastery: SKILLMANAGERHANDLER->AssaParticle_AttackSkillEffect("Stingger", x); }
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 1
{ "x", SKILLID_MeleeMastery, "FT10 MeleeMastery" },
''')
    part = donor / 'Effect' / 'Particle' / 'Script' / 'Stingger.part'
    part.parent.mkdir(parents=True); part.write_text('Texture "spark.bmp"\n', encoding='utf-8')
    (donor / 'Effect' / 'Particle' / 'spark.bmp').write_bytes(b'bmp')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], classes=('Fighter',),
    )
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    edges = [e for e in graph['edges'] if e['relation'] == 'RESOLVES_PARTICLE_SCRIPT']
    assert edges
    assert any(e['source'] == 'EFFECT_TOKEN:stingger' for e in edges)
    part_nodes = [n for n in graph['nodes'] if n['node_type'] == 'ASSET' and (n.get('attributes') or {}).get('asset_role') == 'EFFECT_PARTICLE_SCRIPT']
    assert any((n.get('attributes') or {}).get('resolution', {}).get('status') == 'RECOVERABLE_REFERENCE' for n in part_nodes)


def test_unscoped_t5_switch_case_is_catalog_attributed_and_runtime_effect_proven(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'; donor = tmp_path / 'donor'
    client.mkdir(); donor.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 1, X },\n')
    _write(current / 'SrcGame' / 'src' / 'SkillEffect.cpp', r'''
void RunSkill(int id) {
    switch (id) {
    case SKILLID_SeismicImpact:
        AssaParticle_AttackSkillEffect("T5SeismicImpact", unit);
        break;
    }
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 5
{ "x", SKILLID_SeismicImpact, "TF103 Seismic_Impact" },
''')
    part = donor / 'Effect' / 'Particle' / 'Script' / 'T5SeismicImpact.part'
    part.parent.mkdir(parents=True)
    part.write_text('Texture "spark.bmp"\r\n', encoding='ascii', newline='')
    (donor / 'Effect' / 'Particle' / 'spark.bmp').write_bytes(b'bmp')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], classes=('Fighter',),
    )
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    edges = graph['edges']
    assert any(
        e['source'] == 'SKILL:Fighter:SKILLID_SeismicImpact'
        and e['relation'] == 'USES_EFFECT_TOKEN'
        and e['target'] == 'EFFECT_TOKEN:t5seismicimpact'
        and e['status'] == 'CURRENT_RUNTIME_TOKEN'
        for e in edges
    )
    nodes = {n['node_id']: n for n in graph['nodes']}
    part_node = nodes['ASSET:t5seismicimpact.part']
    assert part_node['attributes']['resolution']['status'] == 'RECOVERABLE_REFERENCE'
    fighter = result['classes'][0]
    skill = next(x for x in fighter['skill_contracts'] if x['skill_id'] == 'SKILLID_SeismicImpact')
    assert skill['current_case_count'] == 1
    assert skill['current_effect_tokens'] == ['T5SeismicImpact']


def test_unscoped_commented_t5_case_does_not_become_runtime_evidence(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 1, X },\n')
    _write(current / 'SrcGame' / 'src' / 'SkillEffect.cpp', r'''
void RunSkill(int id) {
    switch (id) {
    // case SKILLID_SeismicImpact:
    //     AssaParticle_AttackSkillEffect("T5SeismicImpact", unit);
    }
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 5
{ "x", SKILLID_SeismicImpact, "TF103 Seismic_Impact" },
''')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Fighter',),
    )
    fighter = result['classes'][0]
    skill = next(x for x in fighter['skill_contracts'] if x['skill_id'] == 'SKILLID_SeismicImpact')
    assert skill['current_case_count'] == 0
    assert skill['current_effect_tokens'] == []


def test_legacy_runtime_function_alias_binds_t5_effect_without_skillid_switch(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'src' / 'legacy' / 'SkillEffect.cpp', r'''
void CSeismicImpactHandler::OnCast()
{
    StartParticle("T5SeismicImpact");
}
void CRisingSlashHandler::Start()
{
    LoadScript("Effect\\Particle\\Script\\RisingSlash1.part");
}
// void CCreedHandler::Start(){ StartParticle("CreedStart"); }
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[
            {'class': 'Fighter', 'skill_name': 'SeismicImpact'},
            {'class': 'Assassin', 'skill_name': 'RisingSlash'},
            {'class': 'Shaman', 'skill_name': 'Creed'},
        ],
    )
    seismic = [x for x in ev['skill_cases'] if x['skill_name'] == 'SeismicImpact']
    assert len(seismic) == 1
    assert seismic[0]['scope_basis'] == 'RUNTIME_FUNCTION_SKILL_ALIAS'
    assert seismic[0]['effect_tokens'] == ['T5SeismicImpact']
    # FIX14 contract: LoadScript is PRELOAD evidence, not runtime activation.
    rising = [x for x in ev['skill_cases'] if x['skill_name'] == 'RisingSlash']
    assert rising == []
    rising_probe = next(x for x in ev['runtime_asset_call_probes'] if x.get('function') == 'CRisingSlashHandler::Start')
    assert rising_probe['particle_literals'] == []
    assert rising_probe['particle_preload_literals'] == ['Effect/Particle/Script/RisingSlash1.part']
    assert not [x for x in ev['skill_cases'] if x['skill_name'] == 'Creed']
    assert any(x['skill_name'] == 'SeismicImpact' and x['has_runtime_effect_evidence'] for x in ev['skill_alias_probes'])


def test_reference_handler_alias_can_bind_current_legacy_handler_typo(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'src' / 'legacy' / 'SesmicImpact.cpp', r'''
void CSesmicImpactHandler::OnCast()
{
    StartParticle("T5SeismicImpact");
}
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Fighter', 'skill_name': 'SeismicImpact'}],
        skill_handler_aliases={'SESMICIMPACTHANDLER': ('Fighter', 'SeismicImpact')},
    )
    rows = [x for x in ev['skill_cases'] if x['skill_name'] == 'SeismicImpact']
    assert len(rows) == 1
    assert rows[0]['scope_basis'] == 'REFERENCE_HANDLER_ALIAS_CURRENT_BODY'
    assert rows[0]['effect_tokens'] == ['T5SeismicImpact']


def test_legacy_runtime_function_alias_binds_t5_audio_without_skillid_switch(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'src' / 'legacy' / 'SeismicImpact.cpp', '''
#define SKILL_SOUND_SEISMIC_IMPACT 0x4401
{ "wav/Effects/Skill/Tempskron/Seismic Impact.wav", SKILL_SOUND_SEISMIC_IMPACT }
void CSeismicImpactHandler::OnCast()
{
    SKILLMANAGERHANDLER->SkillPlaySound(SKILL_SOUND_SEISMIC_IMPACT, point3D);
}
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Fighter', 'skill_name': 'SeismicImpact'}],
    )
    rows = [x for x in ev['skill_cases'] if x['skill_name'] == 'SeismicImpact']
    assert len(rows) == 1
    assert rows[0]['sounds'][0]['symbol'] == 'SKILL_SOUND_SEISMIC_IMPACT'
    assert rows[0]['sounds'][0]['path'] == 'wav/Effects/Skill/Tempskron/Seismic Impact.wav'
    probes = [x for x in ev['skill_alias_probes'] if x['skill_name'] == 'SeismicImpact']
    assert probes and probes[0]['has_runtime_audio_evidence'] is True


def test_current_t5_sound_symbol_can_use_reference_path_only_when_numeric_code_matches(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'; donor = tmp_path / 'donor'
    client.mkdir(); donor.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 1, X },\n')
    _write(current / 'SrcGame' / 'src' / 'legacy' / 'SeismicImpact.cpp', '''
#define SKILL_SOUND_SEISMIC_IMPACT 0x4401
void CSeismicImpactHandler::OnCast()
{
    SKILLMANAGERHANDLER->SkillPlaySound(SKILL_SOUND_SEISMIC_IMPACT, point3D);
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 5
{ "x", SKILLID_SeismicImpact, "TF103 Seismic_Impact" },
''')
    _write(ref / 'game' / 'sound' / 'SkillSound.cpp', '''
#define SKILL_SOUND_SEISMIC_IMPACT 0x4401
{ "wav/Effects/Skill/Tempskron/Seismic Impact.wav", SKILL_SOUND_SEISMIC_IMPACT }
''')
    wav = donor / 'wav' / 'Effects' / 'Skill' / 'Tempskron' / 'Seismic Impact.wav'
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b'RIFFxxxxWAVE')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], classes=('Fighter',),
    )
    audio_rows = [x for x in result['assets'] if x.get('skill_id') == 'SKILLID_SeismicImpact' and x.get('role') == 'SKILL_AUDIO']
    assert len(audio_rows) == 1
    row = audio_rows[0]
    assert row['logical_path'] == 'wav/Effects/Skill/Tempskron/Seismic Impact.wav'
    assert row['status'] == 'RECOVERABLE_REFERENCE'
    assert 'REFERENCE_SOUND_CODE_MATCH' in row['evidence']


def test_current_t5_sound_symbol_does_not_use_reference_path_when_numeric_code_differs(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 1, X },\n')
    _write(current / 'SrcGame' / 'src' / 'legacy' / 'SeismicImpact.cpp', '''
#define SKILL_SOUND_SEISMIC_IMPACT 0x4402
void CSeismicImpactHandler::OnCast()
{
    SKILLMANAGERHANDLER->SkillPlaySound(SKILL_SOUND_SEISMIC_IMPACT, point3D);
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 5
{ "x", SKILLID_SeismicImpact, "TF103 Seismic_Impact" },
''')
    _write(ref / 'game' / 'sound' / 'SkillSound.cpp', '''
#define SKILL_SOUND_SEISMIC_IMPACT 0x4401
{ "wav/Effects/Skill/Tempskron/Seismic Impact.wav", SKILL_SOUND_SEISMIC_IMPACT }
''')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Fighter',),
    )
    audio_rows = [x for x in result['assets'] if x.get('skill_id') == 'SKILLID_SeismicImpact' and x.get('role') == 'SKILL_AUDIO']
    assert audio_rows == []
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    assert any(
        e.get('source') == 'SKILL:Fighter:SKILLID_SeismicImpact'
        and e.get('relation') == 'PLAYS_SOUND'
        and e.get('status') == 'CURRENT_RUNTIME_SYMBOL_UNRESOLVED'
        for e in graph['edges']
    )


def test_legacy_oracle_server_skill_alias_is_review_only_not_runtime_probe(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'Shared' / 'legacy_oracle' / 'server' / 'systems' / 'combat' / 'skills' / 'legacy' / 'Tempskron.cpp.inl', r'''
void F_Seismic_Impact()
{
    StartParticle("T5SeismicImpact");
}
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Fighter', 'skill_name': 'SeismicImpact'}],
    )
    assert ev['skill_alias_probes'] == []
    assert ev['runtime_asset_call_probes'] == []
    assert not [x for x in ev['skill_cases'] if x['skill_name'] == 'SeismicImpact']


def test_current_client_unscoped_token_bridges_unique_reference_t5_effect(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'; donor = tmp_path / 'donor'
    client.mkdir(); donor.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 8\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Mechanician", "Mechanician", JOB_CODE_MECHANICIAN, 1, X },\n')
    _write(current / 'SrcGame' / 'game' / 'GenericFX.cpp', r'''
void SpawnGenericCombatFX()
{
    StartParticle("MC5RuptureHit");
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Mechanician Skills - Tier 5
{ "x", SKILLID_Rupture, "TM100 Rupture" },
''')
    _write(ref / 'game' / 'game' / 'CMechanicianSkillHandler.cpp', r'''
void f(){ case SKILLID_Rupture: StartParticle("MC5RuptureHit"); break; }
''')
    part = donor / 'Effect' / 'Particle' / 'Script' / 'MC5RuptureHit.part'
    part.parent.mkdir(parents=True)
    part.write_text('Texture "spark.bmp"\r\n', encoding='ascii', newline='')
    (donor / 'Effect' / 'Particle' / 'spark.bmp').write_bytes(b'bmp')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], classes=('Mechanician',),
    )
    mech = result['classes'][0]
    skill = next(x for x in mech['skill_contracts'] if x['skill_id'] == 'SKILLID_Rupture')
    assert skill['current_case_count'] == 1
    assert skill['current_effect_tokens'] == ['MC5RuptureHit']
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    node = next(x for x in graph['nodes'] if x['node_id'] == 'SKILL:Mechanician:SKILLID_Rupture')
    ev = node['attributes']['current_runtime_case_evidence']
    assert ev and ev[0]['scope_basis'] == 'CURRENT_CLIENT_REFERENCE_UNIQUE_EFFECT_TOKEN'
    assert graph['metadata']['current_client_asset_call_probe_count'] == 1
    assert graph['metadata']['current_t5_asset_bridge_case_count'] == 1


def test_current_client_unscoped_part_name_bridges_unique_t5_skill_alias(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'; donor = tmp_path / 'donor'
    client.mkdir(); donor.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 10\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Assassin", "Assassin", JOB_CODE_ASSASSIN, 9, X },\n')
    _write(current / 'SrcGame' / 'game' / 'GenericFX.cpp', r'''
void LoadExtraSkillFX()
{
    LoadScript("Effect\\Particle\\Script\\RisingSlash1.part");
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Assassin Skills - Tier 5
{ "x", SKILLID_RisingSlash, "TS83 R_Slash" },
''')
    part = donor / 'Effect' / 'Particle' / 'Script' / 'RisingSlash1.part'
    part.parent.mkdir(parents=True)
    part.write_text('Texture "spark.bmp"\r\n', encoding='ascii', newline='')
    (donor / 'Effect' / 'Particle' / 'spark.bmp').write_bytes(b'bmp')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], classes=('Assassin',),
    )
    assassin = result['classes'][0]
    skill = next(x for x in assassin['skill_contracts'] if x['skill_id'] == 'SKILLID_RisingSlash')
    assert skill['current_case_count'] == 0
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    hints = [x for x in graph['metadata']['current_t5_particle_preload_hints'] if x['skill_name'] == 'RisingSlash']
    assert len(hints) == 1
    assert hints[0]['scope_basis'] == 'CURRENT_CLIENT_PRELOAD_ASSET_NAME_SKILL_ALIAS'
    assert hints[0]['resolution']['status'] == 'RECOVERABLE_REFERENCE'
    assert hints[0]['authorization'] == 'DIAGNOSTIC_ONLY_PRELOAD_IS_NOT_ACTIVATION'
    assert not any(
        e['source'] == 'SKILL:Assassin:SKILLID_RisingSlash'
        and e['target'].casefold().endswith('risingslash1.part')
        for e in graph['edges']
    )


def test_current_client_part_name_uses_unique_reference_handler_spelling_alias(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 10\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Fighter", "Fighter", JOB_CODE_FIGHTER, 2, X },\n')
    _write(current / 'SrcGame' / 'game' / 'GenericFX.cpp', r'''
void InitEffect()
{
    LoadScript("game/scripts/particles/R5SesmicImpact.part");
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Fighter Skills - Tier 5
{ "x", SKILLID_SeismicImpact, "TF103 Sesmic_Impact" },
''')
    _write(ref / 'game' / 'game' / 'CFighterSkillHandler.cpp', r'''
void f(){ case SKILLID_SeismicImpact: SESMICIMPACTHANDLER->Cast(); break; }
''')
    (client / 'game' / 'scripts' / 'particles').mkdir(parents=True)
    (client / 'game' / 'scripts' / 'particles' / 'R5SesmicImpact.part').write_text('x', encoding='ascii')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Fighter',),
    )
    fighter = result['classes'][0]
    skill = next(x for x in fighter['skill_contracts'] if x['skill_id'] == 'SKILLID_SeismicImpact')
    assert skill['current_case_count'] == 0
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    hints = [x for x in graph['metadata']['current_t5_particle_preload_hints'] if x['skill_name'] == 'SeismicImpact']
    assert len(hints) == 1
    assert hints[0]['scope_basis'] == 'CURRENT_CLIENT_PRELOAD_ASSET_NAME_SKILL_ALIAS'
    assert hints[0]['resolution']['status'] == 'PRESENT_TARGET'
    assert hints[0]['authorization'] == 'DIAGNOSTIC_ONLY_PRELOAD_IS_NOT_ACTIVATION'
    assert not any(
        e['source'] == 'SKILL:Fighter:SKILLID_SeismicImpact'
        and e['target'].casefold().endswith('r5sesmicimpact.part')
        for e in graph['edges']
    )


def test_generic_client_sound_api_with_current_sound_symbol_bridges_t5_by_asset_name(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 10\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Assassin", "Assassin", JOB_CODE_ASSASSIN, 9, X },\n')
    _write(current / 'SrcGame' / 'sound' / 'SkillSound.cpp', r'''
#define SKILL_SOUND_RISING_SLASH 0x4401
{ "wav/Effects/Skill/Assassin/RisingSlash 01.wav", SKILL_SOUND_RISING_SLASH }
void PlayT5Audio()
{
    SoundHandler->Play(SKILL_SOUND_RISING_SLASH);
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Assassin Skills - Tier 5
{ "x", SKILLID_RisingSlash, "TS83 R_Slash" },
''')
    wav = client / 'wav' / 'Effects' / 'Skill' / 'Assassin' / 'RisingSlash 01.wav'
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b'RIFFtest')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Assassin',),
    )
    assassin = result['classes'][0]
    skill = next(x for x in assassin['skill_contracts'] if x['skill_id'] == 'SKILLID_RisingSlash')
    assert skill['current_case_count'] == 1
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    assert graph['metadata']['current_client_audio_call_probe_count'] >= 1
    assert graph['metadata']['current_client_unresolved_audio_call_probe_count'] == 0
    assert any(
        e['source'] == 'SKILL:Assassin:SKILLID_RisingSlash'
        and e['relation'] == 'REQUIRES_ASSET'
        and e['status'] == 'PRESENT_TARGET'
        and (next(x for x in graph['nodes'] if x['node_id'] == e['target'])['attributes'].get('asset_role') == 'SKILL_AUDIO')
        for e in graph['edges']
    )


def test_generic_client_sound_api_unresolved_argument_is_diagnostic_only(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'game' / 'Audio.cpp', r'''
void PlayT5Audio()
{
    SoundHandler->Play(mysterySkillSoundId);
}
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Assassin', 'skill_name': 'RisingSlash'}],
    )
    assert ev['runtime_asset_call_probes'] == []
    assert len(ev['runtime_audio_call_probes']) == 1
    assert ev['runtime_audio_call_probes'][0]['resolved_identity'] is False
    assert ev['runtime_audio_call_probes'][0]['callee'] == 'SoundHandler->Play'


def test_generic_client_effect_api_token_bridges_unique_reference_t5_effect(tmp_path: Path):
    project = tmp_path / 'project'; project.mkdir()
    current = tmp_path / 'current'; ref = tmp_path / 'ref'; client = tmp_path / 'client'
    client.mkdir()
    _write(current / 'Shared' / 'smPacket.h', '#define MAX_JOBNUM 10\n#define MAX_JOB_CAPACITY 10\n')
    _write(current / 'SrcGame' / 'English' / 'e_JobCode.h', '{ "Shaman", "Shaman", JOB_CODE_SHAMAN, 10, X },\n')
    _write(current / 'SrcGame' / 'game' / 'GenericFX.cpp', r'''
void CastLegacyFX()
{
    EffectManager->Start("CreedStart");
}
''')
    _write(ref / 'shared' / 'skill.h', r'''
//Shaman Skills - Tier 5
{ "x", SKILLID_Creed, "MS80 Creed" },
''')
    _write(ref / 'game' / 'game' / 'CCreedHandler.cpp', r'''
void f(){ case SKILLID_Creed: StartParticle("CreedStart"); break; }
''')
    part = client / 'Effect' / 'Particle' / 'Script' / 'CreedStart.part'
    part.parent.mkdir(parents=True)
    part.write_text('x', encoding='ascii')

    result = audit_player_class_contracts(
        project, client, source_root=current, reference_source_root=ref,
        donor_clients=[], classes=('Shaman',),
    )
    shaman = result['classes'][0]
    skill = next(x for x in shaman['skill_contracts'] if x['skill_id'] == 'SKILLID_Creed')
    assert skill['current_case_count'] == 1
    assert 'CreedStart' in skill['current_effect_tokens']
    graph = json.loads(Path(result['graph']).read_text(encoding='utf-8'))
    assert graph['metadata']['current_client_effect_call_probe_count'] >= 1
    assert graph['metadata']['current_client_unresolved_effect_call_probe_count'] == 0


def test_control_statements_are_not_recorded_as_runtime_function_probes(tmp_path: Path):
    from pt_asset_tool.source_evidence import scan_source_evidence

    current = tmp_path / 'current'
    _write(current / 'SrcGame' / 'game' / 'Audio.cpp', r'''
#define SKILL_SOUND_TEST 0x4401
{ "wav/Effects/Test.wav", SKILL_SOUND_TEST }
void RealFunction()
{
    if (true)
        SkillPlaySound(SKILL_SOUND_TEST, 0, 0, 0);
}
''')
    ev = scan_source_evidence(
        SourceTree('CURRENT_SOURCE', 'TARGET_RUNTIME_SOURCE', current),
        skill_catalog=[{'class': 'Fighter', 'skill_name': 'SeismicImpact'}],
    )
    functions = {str(x.get('function') or '').casefold() for x in ev['runtime_asset_call_probes']}
    assert 'realfunction' in functions
    assert 'if' not in functions
    assert 'switch' not in functions
