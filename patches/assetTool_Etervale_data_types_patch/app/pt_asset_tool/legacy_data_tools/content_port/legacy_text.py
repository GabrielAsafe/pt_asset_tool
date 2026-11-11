from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

HANGUL_RANGES = ((0x1100,0x11FF),(0x3130,0x318F),(0xAC00,0xD7A3))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_hangul(text: str) -> bool:
    return any(any(a <= ord(ch) <= b for a,b in HANGUL_RANGES) for ch in text)


def hangul_count(text: str) -> int:
    return sum(1 for ch in text if any(a <= ord(ch) <= b for a,b in HANGUL_RANGES))


def decode_atom(data: bytes) -> tuple[str,str]:
    """Decode one lexical atom, not a whole file.

    Legacy files can mix CP949 directive bytes with Western strings. Decoding
    atoms independently is safer than assigning one codec to the entire file.
    """
    if not data:
        return "", "ascii"
    if all(b < 0x80 for b in data):
        return data.decode("ascii"), "ascii"
    # BOM is meaningful only for whole-file starts, but handling it here is harmless.
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            pass
    try:
        text = data.decode("utf-8")
        # Prefer UTF-8 when it contains plausible Unicode rather than mojibake.
        if "�" not in text:
            return text, "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp949")
        if has_hangul(text):
            return text, "cp949"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def decode_line_best(data: bytes) -> tuple[str,str]:
    """Best-effort display decoding for comments/raw lines.

    Structured parsers never depend on this function for directive identity.
    """
    if not data:
        return "", "ascii"
    # Whole-line UTF-8 first.
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc), "utf-8"
        except UnicodeDecodeError:
            pass
    # If CP949 is valid and actually produces Hangul it is strong evidence.
    try:
        cp = data.decode("cp949")
        if hangul_count(cp) >= 1:
            return cp, "cp949"
    except UnicodeDecodeError:
        pass
    # Mixed line: tokenize and decode atoms while retaining whitespace.
    chunks = re.split(br"(\s+)", data)
    rendered=[]
    codecs=set()
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.isspace():
            rendered.append(chunk.decode("ascii", errors="replace")); continue
        text, enc = decode_atom(chunk)
        rendered.append(text); codecs.add(enc)
    if rendered:
        return "".join(rendered), "+".join(sorted(codecs)) if codecs else "ascii"
    return data.decode("cp1252", errors="replace"), "cp1252"


@dataclass(frozen=True)
class ByteToken:
    raw: bytes
    text: str
    encoding: str
    quoted: bool = False


def strip_inline_comment(line: bytes) -> tuple[bytes, Optional[bytes]]:
    """Split // comment outside quoted strings."""
    in_quote=False
    i=0
    while i < len(line)-1:
        b=line[i]
        if b == 0x22:  # "
            in_quote=not in_quote
        if not in_quote and line[i:i+2] == b"//":
            return line[:i], line[i+2:]
        i += 1
    return line, None


def lex_bytes(line: bytes) -> list[ByteToken]:
    """Whitespace lexer compatible with legacy quoted values.

    Quotes are removed in the returned value, but `quoted` records their presence.
    Backslashes are not treated as escapes because legacy paths use them literally.
    """
    body,_ = strip_inline_comment(line.rstrip(b"\r\n"))
    out=[]
    i=0; n=len(body)
    while i<n:
        while i<n and body[i] in b" \t\r\n": i+=1
        if i>=n: break
        quoted=False
        if body[i] == 0x22:
            quoted=True; i+=1; start=i
            while i<n and body[i] != 0x22: i+=1
            raw=body[start:i]
            if i<n and body[i]==0x22: i+=1
        else:
            start=i
            while i<n and body[i] not in b" \t\r\n": i+=1
            raw=body[start:i]
        text,enc=decode_atom(raw)
        out.append(ByteToken(raw=raw,text=text,encoding=enc,quoted=quoted))
    return out


def iter_raw_lines(data: bytes) -> Iterator[bytes]:
    # splitlines(keepends=True) handles CRLF/LF/CR while retaining exact line bytes.
    yield from data.splitlines(keepends=True)
    if data and not data.endswith((b"\n",b"\r")):
        # splitlines already includes the final line, so nothing else is required.
        return
