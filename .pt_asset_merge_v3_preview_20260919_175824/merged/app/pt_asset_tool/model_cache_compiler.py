from __future__ import annotations

import hashlib
import pathlib
import re
import struct
from typing import Any

# Source-derived Win32 ABI from SrcGame/SrcServer smType.h.
FORMAT = "PT_MODEL_CACHE_INX_COMPILER_V2"
CHECKSUM_PATH_POLICY_WIN32 = "WIN32_CANONICAL"
CHECKSUM_PATH_POLICY_PRESERVE = "SOURCE_PRESERVE"
CACHE_SIZE = 95268
CHRMOTION_EXT = 10
MOTION_INFO_MAX = 512
MOTION_INFO_SIZE = 172
MOTION_INFO_OFFSET = 0x18C  # 396
NPC_MOTION_INFO_MAX = 30
TALK_MOTION_INFO_MAX = 30
TALK_MOTION_FILE_MAX = 2
MOTION_TOOL_MAX = 104
MOTION_SKILL_MAX = 8

# smMODELINFO offsets, verified against the source ABI and existing parser layout.
OFF_MODEL_FILE = 0
OFF_MOTION_FILE = 64
OFF_SUB_MODEL_FILE = 128
OFF_HIGH_GROUP = 192
OFF_DEFAULT_GROUP = 260
OFF_LOW_GROUP = 328
MODEL_GROUP_SIZE = 68
OFF_MOTION_COUNT = MOTION_INFO_OFFSET + MOTION_INFO_MAX * MOTION_INFO_SIZE
OFF_FILE_KEYWORD = OFF_MOTION_COUNT + 4
OFF_LINK_KEYWORD = OFF_FILE_KEYWORD + 4
OFF_LINK_FILE = OFF_LINK_KEYWORD + 4
OFF_TALK_LINK_FILE = OFF_LINK_FILE + 64
OFF_TALK_MOTION_FILE = OFF_TALK_LINK_FILE + 64
OFF_TALK_MOTION_INFO = OFF_TALK_MOTION_FILE + 64
OFF_TALK_MOTION_COUNT = OFF_TALK_MOTION_INFO + TALK_MOTION_INFO_MAX * MOTION_INFO_SIZE
OFF_NPC_MOTION_RATE = OFF_TALK_MOTION_COUNT + 4
OFF_NPC_MOTION_RATE_CNT = OFF_NPC_MOTION_RATE + NPC_MOTION_INFO_MAX * 4
OFF_TALK_MOTION_RATE = OFF_NPC_MOTION_RATE_CNT + 100 * 4
OFF_TALK_MOTION_RATE_CNT = OFF_TALK_MOTION_RATE + TALK_MOTION_INFO_MAX * 4
assert OFF_TALK_MOTION_RATE_CNT + TALK_MOTION_FILE_MAX * 100 * 4 == CACHE_SIZE

# smMOTIONINFO offsets.
M_STATE = 0
M_KW1 = 4
M_START = 8
M_KW2 = 12
M_END = 16
M_EVENTS = 20
M_ITEM_COUNT = 36
M_ITEM_LIST = 40
M_JOB_MASK = 144
M_SKILL_LIST = 148
M_MAP_POSITION = 156
M_REPEAT = 160
M_KEY_CODE = 164
M_MOTION_FRAME = 168

STATE = {
    "STAND": 0x040,
    "WALK": 0x050,
    "RUN": 0x060,
    "FALLDOWN": 0x080,
    "ATTACK": 0x100,
    "DAMAGE": 0x110,
    "DEAD": 0x120,
    "SOMETIME": 0x130,
    "EAT": 0x140,
    "SKILL": 0x150,
    "FALLSTAND": 0x170,
    "FALLDAMAGE": 0x180,
    "RESTART": 0x200,
    "WARP": 0x210,
    "YAHOO": 0x220,
}
TALK_STATE = {
    "아표정": 0x400,
    "이표정": 0x410,
    "오표정": 0x420,
    "눈깜빡표정": 0x430,
    "무표정(작동안함)": 0,
    "웃는표정": 0x440,
    "화난표정": 0x450,
    "슬픈표정": 0x460,
    "놀란표정": 0x470,
    "고유표정": 0x480,
    "특별표정": 0x490,
}
REGULAR_WORDS = [
    ("뛰는", "RUN"),
    ("공격", "ATTACK"),
    ("죽기", "DEAD"),
    ("죽는", "DEAD"),
    ("타격", "DAMAGE"),
    ("데미지", "DAMAGE"),
    ("막기", "DAMAGE"),
    ("가끔", "SOMETIME"),
    ("떨어", "FALLDOWN"),
    ("작은착지", "FALLSTAND"),
    ("큰착지", "FALLDAMAGE"),
    ("*서있기", "STAND"),
    ("*정지", "STAND"),
    ("*걷는", "WALK"),
    ("다시시작", "RESTART"),
    ("먹기", "EAT"),
    ("기술", "SKILL"),
    ("울기", "WARP"),
    ("워프", "WARP"),
    ("만세", "YAHOO"),
]

JOB_MASKS = {
    "fighter": 0x0001,
    "mechanician": 0x0002,
    "archer": 0x0004,
    "pikeman": 0x0008,
    "atalanta": 0x0010,
    "knight": 0x0020,
    "magician": 0x0040,
    "priest": 0x0080,
    # The legacy array contains repeated PureBody rows. Lookup stops at first.
    "purebody": 0x0040,
}

KNOWN_COMMANDS = {
    "*동작파일": "motion_file",
    "*동작모음": "motion_source",
    "*모양파일": "model_file",
    "*모양이름": "model_name",
    "*파일연결": "link_file",
    "*보조동작파일": "sub_motion_file",
    "*정밀모양": "lod_high",
    "*보통모양": "lod_default",
    "*저질모양": "lod_low",
    "*XX걷는동작": "ignored",
    "*XX서있기동작": "ignored",
    "*EQUIPPED_WEAPON": "equipped_weapon",
    "*APPLICABLE_JOB": "applicable_job",
    "*LOCATION": "location",
    "*APPLICABLE_SKILL": "applicable_skill",
    "*표정파일연결": "talk_link_file",
    "*표정파일": "talk_motion_file",
    "*표정모음": "talk_motion_source",
}


def _u32(value: int) -> int:
    return int(value) & 0xFFFFFFFF


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokenize(line: str) -> list[str]:
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in re.finditer(r'"([^"]*)"|(\S+)', line)]


def _put_cstr(buf: bytearray, offset: int, capacity: int, text: str, *, encoding: str = "cp949") -> None:
    raw = str(text or "").encode(encoding)
    if len(raw) >= capacity:
        raise ValueError(f"MODEL_CACHE_STRING_EXCEEDS_{capacity-1}_BYTES:{text}")
    buf[offset:offset + capacity] = b"\0" * capacity
    buf[offset:offset + len(raw)] = raw


def _logical_join(config_logical: str, value: str) -> str:
    value = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not value:
        return ""
    parent = pathlib.PurePosixPath(config_logical.replace("\\", "/")).parent
    out = (parent / pathlib.PurePosixPath(value)).as_posix()
    parts = pathlib.PurePosixPath(out).parts
    if any(x in {"", ".", ".."} for x in parts):
        raise ValueError(f"MODEL_CACHE_REFERENCE_INVALID:{value}")
    return out


def _replace_ext(path: str, ext: str) -> str:
    p = pathlib.PurePosixPath(path.replace("\\", "/"))
    return p.with_suffix("." + ext.lstrip(".")).as_posix()


def canonicalize_runtime_path(text: str, policy: str = CHECKSUM_PATH_POLICY_WIN32) -> str:
    """Return the path spelling used for INX keyword checksums.

    The legacy MSVC code hashes ChangeFileExt() verbatim.  The MinGW client
    explicitly canonicalizes both '/' and '\\' to a single '\\' and collapses
    repeated separators before calling GetSpeedSum.  Asset-tool recipes use
    portable '/' paths, so WIN32_CANONICAL is the publish-safe default while
    SOURCE_PRESERVE remains available for forensic parity with a source path.
    """
    value = str(text or "")
    mode = str(policy or CHECKSUM_PATH_POLICY_WIN32).upper()
    if mode == CHECKSUM_PATH_POLICY_PRESERVE:
        return value
    if mode != CHECKSUM_PATH_POLICY_WIN32:
        raise ValueError(f"MODEL_CACHE_CHECKSUM_PATH_POLICY_UNKNOWN:{policy}")
    out: list[str] = []
    last_sep = False
    for ch in value:
        if ch in "/\\":
            if last_sep:
                continue
            out.append("\\")
            last_sep = True
        else:
            out.append(ch)
            last_sep = False
    return "".join(out)


def _cstr(buf: bytes, offset: int, capacity: int, *, encoding: str = "cp949") -> str:
    return bytes(buf[offset:offset + capacity]).split(b"\0", 1)[0].decode(encoding, "strict")


def _decode_model_keywords(file_kw: int, link_kw: int, has_link: bool) -> tuple[int, int | None]:
    """Inverse of ModelKeyWordEncode, matching ModelKeyWordDecode."""
    if has_link:
        file_code = _u32(
            (link_kw & 0xFF000000)
            | ((file_kw & 0xFF000000) >> 8)
            | (link_kw & 0x0000FF00)
            | ((file_kw & 0x0000FF00) >> 8)
        )
        link_code = _u32(
            ((file_kw & 0x000000FF) << 24)
            | ((link_kw & 0x000000FF) << 16)
            | ((link_kw & 0x00FF0000) >> 8)
            | ((file_kw & 0x00FF0000) >> 16)
        )
        return file_code, link_code
    file_code = _u32(
        ((file_kw & 0xFF000000) >> 16)
        | ((file_kw & 0x00FF0000) << 8)
        | ((file_kw & 0x0000FF00) >> 8)
        | ((file_kw & 0x000000FF) << 16)
    )
    return file_code, None


def _decode_motion_start(raw_kw: int, raw_frame: int, code: int) -> tuple[int, bool, int]:
    if not (raw_kw or raw_frame):
        return 0, True, 0
    keyword = _u32(
        (raw_kw & 0xFF000000)
        | ((raw_kw & 0x0000FF00) << 8)
        | (raw_frame & 0x0000FF00)
        | ((raw_frame & 0xFF000000) >> 24)
    )
    frame = _u32(
        ((raw_frame & 0x000000FF) << 24)
        | (raw_frame & 0x00FF0000)
        | ((raw_kw & 0x00FF0000) >> 8)
        | (raw_kw & 0x000000FF)
    )
    return frame, keyword == _u32(code), keyword


def _decode_motion_end(raw_kw: int, raw_frame: int, code: int) -> tuple[int, bool, int]:
    if not (raw_kw or raw_frame):
        return 0, True, 0
    keyword = _u32(
        ((raw_frame & 0x0000FF00) << 16)
        | ((raw_frame & 0xFF000000) >> 8)
        | (raw_kw & 0x0000FF00)
        | ((raw_kw & 0xFF000000) >> 24)
    )
    frame = _u32(
        ((raw_kw & 0x00FF0000) << 8)
        | ((raw_kw & 0x000000FF) << 16)
        | ((raw_frame & 0x00FF0000) >> 8)
        | (raw_frame & 0x000000FF)
    )
    return frame, keyword == _u32(code), keyword


def inspect_model_cache(
    data: bytes,
    *,
    logical_cache: str | None = None,
    checksum_path_policy: str = CHECKSUM_PATH_POLICY_WIN32,
) -> dict[str, Any]:
    """Decode and validate the source-native 95,268-byte smMODELINFO cache."""
    if len(data) != CACHE_SIZE:
        raise ValueError(f"MODEL_CACHE_SIZE_INVALID:{len(data)}:{CACHE_SIZE}")
    motion_count = struct.unpack_from("<I", data, OFF_MOTION_COUNT)[0]
    talk_count = struct.unpack_from("<I", data, OFF_TALK_MOTION_COUNT)[0]
    if not CHRMOTION_EXT <= motion_count <= MOTION_INFO_MAX:
        raise ValueError(f"MODEL_CACHE_MOTION_COUNT_INVALID:{motion_count}")
    if not CHRMOTION_EXT <= talk_count <= TALK_MOTION_INFO_MAX:
        raise ValueError(f"MODEL_CACHE_TALK_COUNT_INVALID:{talk_count}")

    structural_errors: list[str] = []
    group_counts: dict[str, int] = {}
    for name, offset in (("high", OFF_HIGH_GROUP), ("default", OFF_DEFAULT_GROUP), ("low", OFF_LOW_GROUP)):
        count = struct.unpack_from("<i", data, offset)[0]
        group_counts[name] = count
        if not 0 <= count <= 4:
            structural_errors.append(f"MODEL_GROUP_COUNT_INVALID:{name}:{count}")

    for name, offset in (
        ("model_file", OFF_MODEL_FILE),
        ("motion_file", OFF_MOTION_FILE),
        ("sub_model_file", OFF_SUB_MODEL_FILE),
        ("link_file", OFF_LINK_FILE),
        ("talk_link_file", OFF_TALK_LINK_FILE),
        ("talk_motion_file", OFF_TALK_MOTION_FILE),
    ):
        if b"\0" not in data[offset:offset + 64]:
            structural_errors.append(f"MODEL_CACHE_STRING_UNTERMINATED:{name}")

    link_file = _cstr(data, OFF_LINK_FILE, 64)
    file_kw = struct.unpack_from("<I", data, OFF_FILE_KEYWORD)[0]
    link_kw = struct.unpack_from("<I", data, OFF_LINK_KEYWORD)[0]
    encoded_file_code, encoded_link_code = _decode_model_keywords(file_kw, link_kw, bool(link_file))
    expected_file_code = None
    expected_link_code = None
    path_code_match = None
    link_code_match = None
    canonical_cache = None
    canonical_link = None
    if logical_cache:
        canonical_cache = canonicalize_runtime_path(logical_cache, checksum_path_policy)
        expected_file_code = get_speed_sum(canonical_cache)
        path_code_match = encoded_file_code == expected_file_code
    if link_file:
        # ModelKeyWordDecode() hashes ChangeFileExt(szLinkFile) verbatim.  The
        # MinGW canonicalization patch applies only to the physical cache path
        # passed to the outer decoder, not to szLinkFile stored in smMODELINFO.
        link_cache = _replace_ext(link_file, "inx")
        canonical_link = canonicalize_runtime_path(link_cache, CHECKSUM_PATH_POLICY_PRESERVE)
        expected_link_code = get_speed_sum(canonical_link)
        link_code_match = encoded_link_code == expected_link_code

    motions: list[dict[str, Any]] = []
    keyword_failures: list[int] = []
    motion_keywords_encoded = motion_count > CHRMOTION_EXT and talk_count <= CHRMOTION_EXT
    for idx in range(motion_count):
        base = _motion_base(idx)
        raw_kw1 = struct.unpack_from("<I", data, base + M_KW1)[0]
        raw_start = struct.unpack_from("<I", data, base + M_START)[0]
        raw_kw2 = struct.unpack_from("<I", data, base + M_KW2)[0]
        raw_end = struct.unpack_from("<I", data, base + M_END)[0]
        if idx >= CHRMOTION_EXT and motion_keywords_encoded:
            start, start_ok, start_kw = _decode_motion_start(raw_kw1, raw_start, encoded_file_code)
            end, end_ok, end_kw = _decode_motion_end(raw_kw2, raw_end, encoded_file_code)
            encoding = "KEYWORD_ENCODED"
            if not (start_ok and end_ok):
                keyword_failures.append(idx)
        else:
            start, end = raw_start, raw_end
            start_ok = end_ok = True
            start_kw = end_kw = 0
            encoding = "PLAIN"
        motions.append({
            "index": idx,
            "state": struct.unpack_from("<I", data, base + M_STATE)[0],
            "start": start,
            "end": end,
            "start_ok": start_ok,
            "end_ok": end_ok,
            "start_keyword": start_kw,
            "end_keyword": end_kw,
            "repeat": struct.unpack_from("<I", data, base + M_REPEAT)[0],
            "key_code": data[base + M_KEY_CODE],
            "motion_frame": struct.unpack_from("<i", data, base + M_MOTION_FRAME)[0],
            "encoding": encoding,
        })
    valid = (
        not structural_errors
        and not keyword_failures
        and path_code_match is not False
        and link_code_match is not False
    )
    return {
        "format": FORMAT,
        "cache_size": len(data),
        "model_file": _cstr(data, OFF_MODEL_FILE, 64),
        "motion_file": _cstr(data, OFF_MOTION_FILE, 64),
        "sub_model_file": _cstr(data, OFF_SUB_MODEL_FILE, 64),
        "link_file": link_file,
        "talk_link_file": _cstr(data, OFF_TALK_LINK_FILE, 64),
        "talk_motion_file": _cstr(data, OFF_TALK_MOTION_FILE, 64),
        "motion_count": motion_count,
        "talk_motion_count": talk_count,
        "encoded_file_code": encoded_file_code,
        "encoded_link_code": encoded_link_code,
        "expected_file_code": expected_file_code,
        "expected_link_code": expected_link_code,
        "checksum_path_policy": checksum_path_policy,
        "link_checksum_path_policy": CHECKSUM_PATH_POLICY_PRESERVE,
        "canonical_cache_path": canonical_cache,
        "canonical_link_cache_path": canonical_link,
        "path_code_match": path_code_match,
        "link_code_match": link_code_match,
        "group_counts": group_counts,
        "structural_errors": structural_errors,
        "motion_keywords_encoded": motion_keywords_encoded,
        "keyword_failures": keyword_failures,
        "motions": motions,
        "valid": valid,
    }


def get_speed_sum(text: str) -> int:
    """Source-equivalent GetSpeedSum over the runtime path bytes.

    Game content paths are expected to fit CP949; ASCII paths are the common case.
    """
    raw = str(text).encode("cp949")
    sum2 = 0
    dwsum = 0
    cnt = 0
    for ch in raw:
        value = ch - 0x20 if 97 <= ch <= 122 else ch
        sum2 = _u32(sum2 + value * (cnt + 1))
        dwsum = _u32(dwsum + value * (cnt * cnt))
        cnt += 1
    return _u32((dwsum << 24) | (cnt << 16) | sum2)


def _encode_model_keywords(file_code: int, link_code: int | None) -> tuple[int, int]:
    if link_code is not None:
        file_kw = (
            ((file_code & 0x00FF0000) << 8)
            | ((link_code & 0x000000FF) << 16)
            | ((file_code & 0x000000FF) << 8)
            | ((link_code & 0xFF000000) >> 24)
        )
        link_kw = (
            (file_code & 0xFF000000)
            | ((link_code & 0x0000FF00) << 8)
            | (file_code & 0x0000FF00)
            | ((link_code & 0x00FF0000) >> 16)
        )
        return _u32(file_kw), _u32(link_kw)
    file_kw = (
        ((file_code & 0x0000FF00) << 16)
        | ((file_code & 0xFF000000) >> 8)
        | ((file_code & 0x000000FF) << 8)
        | ((file_code & 0x00FF0000) >> 16)
    )
    return _u32(file_kw), 0


def _encode_motion_start(frame: int, code: int) -> tuple[int, int]:
    frame = _u32(frame); code = _u32(code)
    kw = (code & 0xFF000000) | ((frame & 0x0000FF00) << 8) | ((code & 0x00FF0000) >> 8) | (frame & 0xFF)
    raw = ((code & 0xFF) << 24) | (frame & 0x00FF0000) | (code & 0x0000FF00) | ((frame & 0xFF000000) >> 24)
    return _u32(kw), _u32(raw)


def _encode_motion_end(frame: int, code: int) -> tuple[int, int]:
    frame = _u32(frame); code = _u32(code)
    kw = ((code & 0xFF) << 24) | ((frame & 0xFF000000) >> 8) | (code & 0x0000FF00) | ((frame & 0x00FF0000) >> 16)
    raw = ((code & 0x00FF0000) << 8) | ((frame & 0x0000FF00) << 8) | ((code & 0xFF000000) >> 16) | (frame & 0xFF)
    return _u32(kw), _u32(raw)


def _motion_base(index: int, *, talk: bool = False) -> int:
    if talk:
        if not 0 <= index < TALK_MOTION_INFO_MAX:
            raise ValueError("MODEL_CACHE_TALK_MOTION_INDEX_OOB")
        return OFF_TALK_MOTION_INFO + index * MOTION_INFO_SIZE
    if not 0 <= index < MOTION_INFO_MAX:
        raise ValueError("MODEL_CACHE_MOTION_INDEX_OOB")
    return MOTION_INFO_OFFSET + index * MOTION_INFO_SIZE


def _motion_state(command: str) -> int:
    state = 1  # TRUE in source before keyword refinement.
    for needle, name in REGULAR_WORDS:
        if needle in command:
            state = STATE[name]
    return state


def _talk_state(command: str) -> int:
    for needle, state in TALK_STATE.items():
        if needle in command:
            return state
    return 0


def _parse_motion_args(tokens: list[str]) -> dict[str, Any]:
    if len(tokens) < 2:
        raise ValueError("MODEL_CACHE_MOTION_REQUIRES_START_END")
    start = int(tokens[0]); end = int(tokens[1])
    if start < 0 or end < start:
        raise ValueError(f"MODEL_CACHE_MOTION_RANGE_INVALID:{start}:{end}")
    events: list[int] = []
    pos = 2
    while pos < len(tokens) and len(events) < 4 and tokens[pos] and tokens[pos][0].isdigit():
        events.append(int(tokens[pos])); pos += 1
    terminator = tokens[pos] if pos < len(tokens) else ""
    if pos < len(tokens):
        pos += 1
    repeat = terminator == "반복"
    key_code = 0
    if terminator and not terminator.startswith("(") and len(terminator.encode("ascii", "ignore")) == 1 and 32 <= ord(terminator[0]) <= 0x7F:
        key_code = ord(terminator[0])
    rate = 0
    if pos < len(tokens):
        m = re.fullmatch(r"\((-?\d+)\)", tokens[pos])
        if m:
            rate = max(0, min(100, int(m.group(1))))
    return {"start": start, "end": end, "events": events, "repeat": repeat, "key_code": key_code, "rate": rate}


def _write_motion(buf: bytearray, index: int, command: str, args: list[str], motion_frame: int, *, talk: bool = False) -> dict[str, Any]:
    parsed = _parse_motion_args(args)
    state = _talk_state(command) if talk else _motion_state(command)
    end = int(parsed["end"])
    if not talk and state == STATE["DEAD"] and end >= 8:
        end -= 8
    base = _motion_base(index, talk=talk)
    struct.pack_into("<I", buf, base + M_STATE, _u32(state))
    struct.pack_into("<I", buf, base + M_START, _u32(parsed["start"]))
    struct.pack_into("<I", buf, base + M_END, _u32(end))
    for i, event in enumerate(parsed["events"][:4]):
        struct.pack_into("<I", buf, base + M_EVENTS + i * 4, _u32((int(event) - int(parsed["start"])) * 160))
    struct.pack_into("<I", buf, base + M_REPEAT, 1 if parsed["repeat"] else 0)
    buf[base + M_KEY_CODE] = int(parsed["key_code"]) & 0xFF
    struct.pack_into("<i", buf, base + M_MOTION_FRAME, int(motion_frame))
    return {"index": index, "state": state, "start": int(parsed["start"]), "end": end, "rate": int(parsed["rate"]), "motion_frame": int(motion_frame)}


def _write_group(buf: bytearray, offset: int, values: list[str]) -> None:
    if len(values) > 4:
        raise ValueError("MODEL_CACHE_LOD_GROUP_LIMIT_4")
    struct.pack_into("<i", buf, offset, len(values))
    for i, value in enumerate(values):
        _put_cstr(buf, offset + 4 + i * 16, 16, value)


def _normalize_rates(buf: bytearray, motion_count: int, rates: list[int]) -> None:
    if motion_count <= CHRMOTION_EXT or rates[CHRMOTION_EXT] == 0:
        return
    count = min(motion_count, NPC_MOTION_INFO_MAX)
    active = list(rates)
    max_rate = 0; max_idx = CHRMOTION_EXT; total = 0
    for idx in range(CHRMOTION_EXT, count):
        if max_rate < active[idx]: max_rate = active[idx]; max_idx = idx
        total += active[idx]
    if total > 100:
        max_rate -= total - 100
        if max_rate <= 0:
            active[CHRMOTION_EXT] = 0
            return
        active[max_idx] = max_rate
    elif total < 100:
        active[max_idx] += 100 - total
    out = []
    for idx in range(CHRMOTION_EXT, count):
        out.extend([idx] * active[idx])
    out = out[:100]
    for idx in range(NPC_MOTION_INFO_MAX):
        struct.pack_into("<i", buf, OFF_NPC_MOTION_RATE + idx * 4, int(rates[idx]))
    for pos, value in enumerate(out):
        struct.pack_into("<i", buf, OFF_NPC_MOTION_RATE_CNT + pos * 4, int(value))


def _normalize_talk_rates(buf: bytearray, talk_count: int, rates: list[int], frames: list[int]) -> None:
    if talk_count <= CHRMOTION_EXT or rates[CHRMOTION_EXT] == 0:
        return
    for idx in range(TALK_MOTION_INFO_MAX):
        struct.pack_into("<i", buf, OFF_TALK_MOTION_RATE + idx * 4, int(rates[idx]))
    for group in range(TALK_MOTION_FILE_MAX):
        indices = [idx for idx in range(CHRMOTION_EXT, min(talk_count, TALK_MOTION_INFO_MAX)) if frames[idx] == group]
        if not indices:
            continue
        local = {idx: rates[idx] for idx in indices}
        total = sum(local.values())
        max_idx = max(indices, key=lambda x: local[x])
        if total > 100:
            local[max_idx] -= total - 100
            if local[max_idx] <= 0:
                return
        elif total < 100:
            local[max_idx] += 100 - total
        out: list[int] = []
        for idx in indices:
            out.extend([idx] * local[idx])
        for pos, value in enumerate(out[:100]):
            struct.pack_into("<i", buf, OFF_TALK_MOTION_RATE_CNT + (group * 100 + pos) * 4, int(value))


def _model_keyword_decode_ok(buf: bytes, file_code: int, link_code: int | None) -> bool:
    file_kw = struct.unpack_from("<I", buf, OFF_FILE_KEYWORD)[0]
    link_kw = struct.unpack_from("<I", buf, OFF_LINK_KEYWORD)[0]
    expected = _encode_model_keywords(file_code, link_code)
    return (file_kw, link_kw) == expected


def compile_model_cache(
    config_logical: str,
    config_bytes: bytes,
    *,
    item_catalog: dict[str, Any],
    skill_catalog: dict[str, Any],
    checksum_path_policy: str = CHECKSUM_PATH_POLICY_WIN32,
) -> tuple[bytes, dict[str, Any]]:
    """Compile a modern 95,268-byte .inx cache from source model-config text.

    The implementation mirrors ReadModelConfig/WriteModelCache for the fields the
    runtime serializes. Motion-source ASE/SMB merging is intentionally not done by
    this cache compiler; those physical files must already be bundle dependencies.
    """
    try:
        text = config_bytes.decode("cp949")
    except UnicodeDecodeError as exc:
        raise ValueError(f"MODEL_CACHE_CONFIG_NOT_CP949:{exc}") from exc

    config_logical = pathlib.PurePosixPath(str(config_logical).replace("\\", "/")).as_posix()
    cache_logical = _replace_ext(config_logical, "inx")
    checksum_cache_path = canonicalize_runtime_path(cache_logical, checksum_path_policy)
    file_code = get_speed_sum(checksum_cache_path)
    buf = bytearray(CACHE_SIZE)
    struct.pack_into("<I", buf, OFF_MOTION_COUNT, CHRMOTION_EXT)
    struct.pack_into("<I", buf, OFF_TALK_MOTION_COUNT, CHRMOTION_EXT)

    item_by_category: dict[str, int] = {}
    for row in item_catalog.get("entries") or []:
        name = str(row.get("last_category") or "")
        idx = int(row.get("index") or 0)
        if name and name not in item_by_category:
            item_by_category[name] = idx
    skill_by_name: dict[str, int] = {}
    for row in skill_catalog.get("entries") or []:
        name = str(row.get("name") or "")
        idx = int(row.get("index") or 0)
        if name and name.casefold() not in skill_by_name:
            skill_by_name[name.casefold()] = idx

    motion_count = CHRMOTION_EXT
    talk_count = CHRMOTION_EXT
    motion_source_count = 0
    last_motion: int | None = None
    npc_rates = [0] * NPC_MOTION_INFO_MAX
    talk_rates = [0] * TALK_MOTION_INFO_MAX
    talk_frames = [0] * TALK_MOTION_INFO_MAX
    refs: list[dict[str, str]] = []

    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        tokens = _tokenize(stripped)
        if not tokens:
            continue
        command = tokens[0]
        args = tokens[1:]
        known = KNOWN_COMMANDS.get(command)
        try:
            if known == "motion_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_MOTION_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known in {"motion_source", "talk_motion_source"}:
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); refs.append({"role": known, "path": logical})
                motion_source_count += 1
                if motion_source_count > 128: raise ValueError("MOTION_SOURCE_LIMIT_128")
            elif known == "model_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_MODEL_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known == "link_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_LINK_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known == "sub_motion_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_SUB_MODEL_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known in {"lod_high", "lod_default", "lod_low"}:
                offset = {"lod_high": OFF_HIGH_GROUP, "lod_default": OFF_DEFAULT_GROUP, "lod_low": OFF_LOW_GROUP}[known]
                _write_group(buf, offset, args[:4])
            elif known == "talk_link_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_TALK_LINK_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known == "talk_motion_file":
                if not args: raise ValueError("VALUE_REQUIRED")
                logical = _logical_join(config_logical, args[0]); _put_cstr(buf, OFF_TALK_MOTION_FILE, 64, logical); refs.append({"role": known, "path": logical})
            elif known == "equipped_weapon":
                if last_motion is None: raise ValueError("NO_PREVIOUS_MOTION")
                base = _motion_base(last_motion)
                if args and args[0] == "ALL":
                    struct.pack_into("<i", buf, base + M_ITEM_COUNT, 0)
                else:
                    values: list[int] = []
                    for name in args:
                        if name == "NONE": values.append(0xFF); continue
                        if name not in item_by_category: continue  # source silently ignores unknown names
                        idx = item_by_category[name]
                        if not 0 <= idx <= 0xFF:
                            raise ValueError(f"ITEM_CATEGORY_INDEX_NOT_BYTE_SAFE:{name}:{idx}")
                        values.append(idx)
                    if len(values) > MOTION_TOOL_MAX: raise ValueError("EQUIPPED_WEAPON_LIMIT_104")
                    struct.pack_into("<i", buf, base + M_ITEM_COUNT, len(values))
                    for i, value in enumerate(values): buf[base + M_ITEM_LIST + i] = value
            elif known == "applicable_job":
                if last_motion is None: raise ValueError("NO_PREVIOUS_MOTION")
                mask = 0
                for name in args:
                    mask |= JOB_MASKS.get(name.casefold(), 0)
                struct.pack_into("<I", buf, _motion_base(last_motion) + M_JOB_MASK, _u32(mask))
            elif known == "location":
                if last_motion is None: raise ValueError("NO_PREVIOUS_MOTION")
                pos = 0
                for name in args[:2]:
                    if name == "TOWN": pos |= 1
                    if name == "FIELD": pos |= 2
                state = struct.unpack_from("<I", buf, _motion_base(last_motion) + M_STATE)[0]
                if pos == 0 or state == STATE["SKILL"]: pos = 3
                struct.pack_into("<i", buf, _motion_base(last_motion) + M_MAP_POSITION, pos)
            elif known == "applicable_skill":
                if last_motion is None: raise ValueError("NO_PREVIOUS_MOTION")
                base = _motion_base(last_motion)
                state = struct.unpack_from("<I", buf, base + M_STATE)[0]
                if state == STATE["SKILL"]:
                    out: list[int] = []
                    for name in args:
                        idx = skill_by_name.get(name.casefold())
                        if idx is None: continue
                        if idx > 0xFF: raise ValueError(f"SKILL_INDEX_NOT_BYTE_SAFE:{name}:{idx}")
                        if len(out) >= MOTION_SKILL_MAX - 1: break
                        out.append(idx)
                    for i, value in enumerate(out): buf[base + M_SKILL_LIST + i] = value
                    buf[base + M_SKILL_LIST + len(out)] = 0
            elif known in {"model_name", "ignored"}:
                pass
            elif known is None and command.startswith("*") and "표정" in command:
                if motion_source_count <= 0: continue  # source requires MotionFileListCnt
                if talk_count >= TALK_MOTION_INFO_MAX: raise ValueError("TALK_MOTION_LIMIT_30")
                row = _write_motion(buf, talk_count, command, args, motion_source_count - 1, talk=True)
                talk_rates[talk_count] = int(row["rate"]); talk_frames[talk_count] = int(row["motion_frame"]); talk_count += 1
            elif known is None and command.startswith("*") and "동작" in command:
                if motion_count >= MOTION_INFO_MAX: raise ValueError("MOTION_LIMIT_512")
                row = _write_motion(buf, motion_count, command, args, motion_source_count, talk=False)
                if motion_count < NPC_MOTION_INFO_MAX: npc_rates[motion_count] = int(row["rate"])
                last_motion = motion_count; motion_count += 1
            # Unknown source lines are ignored by AddModelDecode; mirror that.
        except Exception as exc:
            raise ValueError(f"MODEL_CACHE_CONFIG_LINE_{line_no}:{command}:{exc}") from exc

    struct.pack_into("<I", buf, OFF_MOTION_COUNT, motion_count)
    struct.pack_into("<I", buf, OFF_TALK_MOTION_COUNT, talk_count)
    _normalize_rates(buf, motion_count, npc_rates)
    _normalize_talk_rates(buf, talk_count, talk_rates, talk_frames)

    link_file = bytes(buf[OFF_LINK_FILE:OFF_LINK_FILE + 64]).split(b"\0", 1)[0].decode("cp949", "strict")
    link_cache = _replace_ext(link_file, "inx") if link_file else ""
    # Source-exact asymmetry: the main cache checksum follows the selected
    # physical-path policy, while ModelKeyWordEncode() hashes szLinkFile as
    # serialized (after only replacing the extension).
    checksum_link_path = canonicalize_runtime_path(link_cache, CHECKSUM_PATH_POLICY_PRESERVE) if link_cache else ""
    link_code = get_speed_sum(checksum_link_path) if checksum_link_path else None
    file_kw, link_kw = _encode_model_keywords(file_code, link_code)
    struct.pack_into("<I", buf, OFF_FILE_KEYWORD, file_kw)
    struct.pack_into("<I", buf, OFF_LINK_KEYWORD, link_kw)

    encoded_motion_count = 0
    if motion_count > CHRMOTION_EXT and talk_count <= CHRMOTION_EXT:
        for idx in range(CHRMOTION_EXT, motion_count):
            base = _motion_base(idx)
            start = struct.unpack_from("<I", buf, base + M_START)[0]
            end = struct.unpack_from("<I", buf, base + M_END)[0]
            if start:
                kw, raw = _encode_motion_start(start, file_code); struct.pack_into("<II", buf, base + M_KW1, kw, raw)
            if end:
                kw, raw = _encode_motion_end(end, file_code); struct.pack_into("<II", buf, base + M_KW2, kw, raw)
            encoded_motion_count += 1

    data = bytes(buf)
    inspected = inspect_model_cache(
        data, logical_cache=cache_logical, checksum_path_policy=checksum_path_policy
    )
    if len(data) != CACHE_SIZE or not _model_keyword_decode_ok(data, file_code, link_code) or not inspected["valid"]:
        raise AssertionError("MODEL_CACHE_INTERNAL_ABI_OR_KEYWORD_VALIDATION_FAILED")
    return data, {
        "writer": "MODEL_CACHE_INX_SOURCE_NATIVE",
        "format": FORMAT,
        "source_parser": "ReadModelConfig/WriteModelCache",
        "source_config": config_logical,
        "logical_cache": cache_logical,
        "layout": "MODERN_172",
        "cache_size": CACHE_SIZE,
        "motion_count": motion_count,
        "talk_motion_count": talk_count,
        "motion_source_count": motion_source_count,
        "keyword_motion_records_encoded": encoded_motion_count,
        "file_code": f"0x{file_code:08X}",
        "link_code": f"0x{link_code:08X}" if link_code is not None else None,
        "checksum_path_policy": checksum_path_policy,
        "link_checksum_path_policy": CHECKSUM_PATH_POLICY_PRESERVE,
        "checksum_cache_path": checksum_cache_path,
        "checksum_link_path": checksum_link_path or None,
        "semantic_roundtrip_valid": bool(inspected["valid"]),
        "keyword_failure_count": len(inspected["keyword_failures"]),
        "reference_count": len(refs),
        "references": refs,
        "sha256": _sha(data),
        "source_evidence": [
            "Shared/formats/model_config/ModelConfigReader.inl",
            "Shared/formats/model_config/ModelCacheReader.inl",
            "Shared/formats/model_config/ModelCachePath.h",
            "Shared/formats/model_config/LegacyModelKeywordExact_client.inl",
            "SrcGame/src/systems/rendering/legacy_3d/smType.h",
        ],
    }
