import struct

import pytest

from pt_asset_tool.asset_contract_registry import source_registry
from pt_asset_tool.model_cache_compiler import (
    CHRMOTION_EXT,
    M_END,
    M_KW1,
    M_KW2,
    M_START,
    OFF_DEFAULT_GROUP,
    OFF_LINK_FILE,
    OFF_MODEL_FILE,
    _motion_base,
    compile_model_cache,
    get_speed_sum,
    inspect_model_cache,
)


def _compile(config: str, logical: str = "char/monster/demo/demo.ini"):
    return compile_model_cache(
        logical,
        config.encode("cp949"),
        item_catalog=source_registry("item_catalog"),
        skill_catalog=source_registry("model_motion_skills"),
    )


def test_link_keyword_checksum_preserves_serialized_link_path():
    data, meta = _compile("*모양파일 demo.smd\r\n*파일연결 linked/sub.ini\r\n")
    inspected = inspect_model_cache(data, logical_cache="char/monster/demo/demo.inx")

    # CopyModelPath preserves the source spelling.  ModelKeyWordEncode then
    # changes only the extension before hashing szLinkFile; it does not apply
    # the MinGW physical-path canonicalizer used for the outer cache path.
    serialized_link = "char/monster/demo/linked/sub.ini"
    expected_link_cache = "char/monster/demo/linked/sub.inx"
    assert inspected["link_file"] == serialized_link
    assert meta["checksum_link_path"] == expected_link_cache
    assert meta["link_checksum_path_policy"] == "SOURCE_PRESERVE"
    assert inspected["encoded_link_code"] == get_speed_sum(expected_link_cache)
    assert inspected["encoded_link_code"] != get_speed_sum(expected_link_cache.replace("/", "\\"))
    assert inspected["link_code_match"] is True
    assert inspected["valid"] is True


def test_inspector_rejects_source_invalid_model_group_count():
    data, _ = _compile("*모양파일 demo.smd\r\n")
    tampered = bytearray(data)
    struct.pack_into("<i", tampered, OFF_DEFAULT_GROUP, 5)
    inspected = inspect_model_cache(bytes(tampered), logical_cache="char/monster/demo/demo.inx")
    assert inspected["valid"] is False
    assert inspected["group_counts"]["default"] == 5
    assert "MODEL_GROUP_COUNT_INVALID:default:5" in inspected["structural_errors"]


def test_inspector_rejects_unterminated_runtime_string():
    data, _ = _compile("*모양파일 demo.smd\r\n")
    tampered = bytearray(data)
    tampered[OFF_MODEL_FILE:OFF_MODEL_FILE + 64] = b"A" * 64
    inspected = inspect_model_cache(bytes(tampered), logical_cache="char/monster/demo/demo.inx")
    assert inspected["valid"] is False
    assert "MODEL_CACHE_STRING_UNTERMINATED:model_file" in inspected["structural_errors"]


def test_motion_keyword_inspection_uses_global_source_encoding_gate():
    # A talk motion beyond CHRMOTION_EXT disables MotionKeyWordEncode globally
    # in WriteModelCache, so regular motions remain plain even beyond index 10.
    config = (
        "*동작모음 motion-a.ase\r\n"
        "*서있기동작 10 20 100 0\r\n"
        "*아표정 30 40 100 0\r\n"
    )
    data, _ = _compile(config)
    inspected = inspect_model_cache(data, logical_cache="char/monster/demo/demo.inx")
    assert inspected["talk_motion_count"] == CHRMOTION_EXT + 1
    assert inspected["motion_keywords_encoded"] is False
    motion = inspected["motions"][CHRMOTION_EXT]
    assert motion["encoding"] == "PLAIN"
    assert (motion["start"], motion["end"]) == (10, 20)
    assert inspected["valid"] is True


def test_keyword_encoded_record_detects_frame_side_tamper_even_if_keyword_word_is_zeroed():
    config = "*서있기동작 10 20 100 0\r\n"
    data, _ = _compile(config)
    tampered = bytearray(data)
    base = _motion_base(CHRMOTION_EXT)
    # Source decoder checks (keyword || frame) for each half.  Zeroing only the
    # keyword word must not make the inspector reinterpret the record as plain.
    struct.pack_into("<I", tampered, base + M_KW1, 0)
    assert struct.unpack_from("<I", tampered, base + M_START)[0] != 0
    inspected = inspect_model_cache(bytes(tampered), logical_cache="char/monster/demo/demo.inx")
    assert inspected["motion_keywords_encoded"] is True
    assert CHRMOTION_EXT in inspected["keyword_failures"]
    assert inspected["valid"] is False
