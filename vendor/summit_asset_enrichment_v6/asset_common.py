#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

TEXT_EXTS = {'.txt', '.ini', '.inf', '.npc', '.spm', '.zhoon', '.lst', '.cfg', '.conf', '.part', '.lua', '.msg', '.sin', '.fnt', '.fx'}
CLIENT_ASSET_EXTS = {
    '.inx', '.smd', '.smb', '.ase', '.bmp', '.tga', '.dds', '.png', '.jpg', '.jpeg',
    '.pkg', '.wav', '.ogg', '.mp3', '.ini', '.inf', '.txt', '.lst', '.cht', '.rgx', '.rxg'
}
SERVER_CONTENT_EXTS = {'.inf', '.npc', '.zhoon', '.spm', '.spp', '.spc', '.txt', '.ini'}
BLOCKED_BASENAMES = {
    'blesscastle.dat', 'game.exe', 'pstale.exe', 'psupdate.exe', 'psupdate.patch.exe',
    'server.exe', 'gameserver.exe', 'database.dll', 'pristonsqldll.dll'
}
BLOCKED_SUFFIXES = {'.exe', '.dll', '.pdb', '.reg'}
BINARY_REF_EXT_RE = re.compile(
    rb'(?i)\.(?:inx|smd|smb|ase|bmp|tga|dds|png|jpg|jpeg|ini|inf|npc|zhoon|spm|spp|spc|wav|pkg)'
)
_BINARY_REF_ALLOWED = set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ .()-\\/')
ITEM_CODE_RE = re.compile(r'(?i)\b(?:[A-Z]{1,3}\d{2,4}|F0\d{3})\b')


def norm_rel(value: str) -> str:
    value = value.replace('\\', '/').replace('//', '/')
    value = value.strip().lstrip('./').lstrip('/')
    while '//' in value:
        value = value.replace('//', '/')
    return value


def norm_key(value: str) -> str:
    return norm_rel(value).casefold()


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_legacy_text(path: Path) -> Tuple[str, str]:
    data = path.read_bytes()
    # Preserve bytes on copy; decoding is only for analysis.
    for enc in ('utf-8-sig', 'cp949', 'cp1252', 'latin1'):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode('latin1', errors='replace'), 'latin1-replace'


def extract_binary_refs(path: Path, max_bytes: int = 8 * 1024 * 1024) -> List[str]:
    """Extract probable embedded asset paths without catastrophic regex backtracking.

    Locate known extensions first, then scan backward at most 240 bytes for
    path-safe ASCII characters. This stays linear even on long printable runs.
    """
    data = path.read_bytes()[:max_bytes]
    out: List[str] = []
    seen = set()
    for m in BINARY_REF_EXT_RE.finditer(data):
        start = m.start() - 1
        floor = max(0, m.start() - 240)
        while start >= floor and data[start] in _BINARY_REF_ALLOWED:
            start -= 1
        start += 1
        raw = data[start:m.end()]
        value = raw.decode('latin1', errors='ignore').strip('\x00 ').replace('\\', '/')
        value = norm_rel(value)
        if not value or Path(value).stem.strip() == '':
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def extract_text_refs(path: Path) -> List[str]:
    text, _ = read_legacy_text(path)
    out: List[str] = []
    seen = set()
    # explicit paths with known extensions
    rx = re.compile(r'(?i)(?:[A-Za-z0-9_ .()\-]+[\\/])*[A-Za-z0-9_ .()\-]+\.(?:inx|smd|smb|ase|bmp|tga|dds|png|jpg|jpeg|ini|inf|npc|zhoon|spm|spp|spc|wav|ogg|mp3|bgm|pkg|part|lua|msg|sin|fnt|fx|zif|sct)')
    for s in rx.findall(text):
        s = norm_rel(s)
        if not s:
            continue
        k = s.casefold()
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def extract_item_codes(path: Path) -> List[str]:
    try:
        text, _ = read_legacy_text(path)
    except OSError:
        return []
    return sorted({m.group(0).upper() for m in ITEM_CODE_RE.finditer(text)})


class CaseIndex:
    """Case-insensitive relative-path index for Linux trees with Windows-era assets."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.files: Dict[str, Path] = {}
        self.dirs: Dict[str, Path] = {}
        self.basename: Dict[str, List[Path]] = {}
        self.stem: Dict[str, List[Path]] = {}
        if self.root.exists():
            self._build()

    def _build(self) -> None:
        for base, dirs, files in os.walk(self.root):
            b = Path(base)
            try:
                rel_dir = b.relative_to(self.root).as_posix()
            except ValueError:
                continue
            self.dirs[norm_key(rel_dir)] = b
            for name in files:
                p = b / name
                rel = p.relative_to(self.root).as_posix()
                self.files[norm_key(rel)] = p
                self.basename.setdefault(name.casefold(), []).append(p)
                self.stem.setdefault(p.stem.casefold(), []).append(p)

    def find(self, rel: str) -> Optional[Path]:
        return self.files.get(norm_key(rel))

    def find_dir(self, rel: str) -> Optional[Path]:
        return self.dirs.get(norm_key(rel))

    def find_basename(self, name: str) -> List[Path]:
        return list(self.basename.get(Path(name).name.casefold(), []))

    def find_stem(self, stem: str, suffixes: Optional[Sequence[str]] = None) -> List[Path]:
        items = list(self.stem.get(Path(stem).stem.casefold(), []))
        if suffixes:
            ss = {x.casefold() if x.startswith('.') else '.' + x.casefold() for x in suffixes}
            items = [p for p in items if p.suffix.casefold() in ss]
        return items

    def iter_dir_files(self, rel_dir: str) -> Iterator[Path]:
        d = self.find_dir(rel_dir)
        if not d:
            return
        for p in d.rglob('*'):
            if p.is_file():
                yield p

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


@dataclass
class Validation:
    status: str  # AUTO, REVIEW, BLOCKED
    reason: str
    format_name: str = ''


def _has_peer_suffix(target_parent: Path, suffix: str) -> bool:
    if not target_parent.exists():
        return False
    suffix = suffix.casefold()
    try:
        for p in target_parent.iterdir():
            if p.is_file() and p.suffix.casefold() == suffix:
                return True
    except OSError:
        return False
    return False


def validate_candidate(source: Path, target: Path, *, source_label: str = '', allow_dds: bool = False,
                       allow_stage072: bool = False) -> Validation:
    name = source.name.casefold()
    suffix = source.suffix.casefold()
    relish = source.as_posix().casefold()

    if name in BLOCKED_BASENAMES or suffix in BLOCKED_SUFFIXES:
        return Validation('BLOCKED', 'runtime/binary/config state is excluded from asset migration')
    if 'blesscastle.dat' in relish:
        return Validation('BLOCKED', 'BlessCastle.dat is serialized runtime/config state, not merge content')

    size = source.stat().st_size
    if suffix == '.inx':
        if size == 95268:
            return Validation('AUTO', 'Summit/ExMachina-generation INX size matches sizeof(smMODELINFO)=95,268', 'INX')
        if size == 67084:
            return Validation('BLOCKED', 'Priston-generation INX is 67,084 bytes and is not binary-compatible with current Summit loader', 'INX')
        return Validation('REVIEW', f'unrecognized INX size {size}; expected 95,268 for Summit generation', 'INX')

    if suffix == '.spp':
        if size == 2400:
            return Validation('AUTO', 'canonical 200 x 12-byte start-point table', 'SPP')
        if size == 600:
            return Validation('BLOCKED', 'legacy 50-record SPP (600 bytes), not canonical 200-record Summit layout', 'SPP')
        return Validation('REVIEW', f'unrecognized SPP size {size}', 'SPP')

    if suffix == '.spc':
        if size == 50400:
            return Validation('AUTO', 'canonical 100 x 504-byte fixed-character placement table', 'SPC')
        return Validation('REVIEW', f'unrecognized SPC size {size}; expected 50,400', 'SPC')

    if suffix in {'.smd', '.smb'}:
        head = source.read_bytes()[:96].decode('latin1', errors='ignore')
        if 'SMD Stage data Ver 0.72' in head:
            if allow_stage072 and source_label.casefold() in {'previous_client', 'summit_previous', 'summit'}:
                return Validation('AUTO', 'Stage 0.72 accepted only from explicitly trusted Summit-lineage source', 'SMD_STAGE_072')
            return Validation('REVIEW', 'Stage 0.72 has WORD/DWORD StageArea source divergence; require lineage/runtime validation', 'SMD_STAGE_072')
        if 'SMD Model data Ver 0.62' in head:
            return Validation('AUTO', 'Model 0.62 container recognized', 'SMD_MODEL_062')
        # Some files may have wrapper/preamble; do not reject blindly.
        return Validation('REVIEW', 'SMD/SMB header not recognized in first 96 bytes', 'SMD_OR_SMB')

    if suffix == '.dds':
        if allow_dds or _has_peer_suffix(target.parent, '.dds'):
            return Validation('AUTO', 'DDS allowed because target subtree already uses DDS or --allow-dds was supplied', 'DDS')
        return Validation('REVIEW', 'DDS donor asset requires target-pipeline compatibility/conversion review', 'DDS')

    if suffix in {'.spm', '.npc', '.inf', '.zhoon', '.txt', '.ini'}:
        return Validation('AUTO', 'legacy text/config copied byte-for-byte; encoding is intentionally preserved', suffix[1:].upper())

    if suffix in CLIENT_ASSET_EXTS or suffix in SERVER_CONTENT_EXTS:
        return Validation('AUTO', 'recognized asset extension and destination is missing', suffix[1:].upper())

    return Validation('REVIEW', f'extension {suffix or "<none>"} not on automatic asset allowlist')


def safe_copy(source: Path, target: Path, *, overwrite: bool = False) -> None:
    """Copy bytes atomically and treat metadata preservation as best-effort.

    Old Priston trees can carry timestamps/metadata that some filesystems reject via
    shutil.copy2(). The asset contract is byte identity, so copy bytes first, verify
    later, and only then try to preserve metadata without making metadata failure fatal.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(target)

    fd, tmp_name = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.summit-part', dir=str(target.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(source, tmp)
        try:
            shutil.copystat(source, tmp, follow_symlinks=True)
        except OSError:
            # Metadata is not part of the asset payload; byte hash is verified by apply.
            pass
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        os.replace(tmp, target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def load_csv(path: Path) -> List[dict]:
    with path.open('r', encoding='utf-8-sig', errors='replace', newline='') as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: List[dict], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow(row)


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')
