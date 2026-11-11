"""V26 read-only model/material library, bounded unpack of Blender archives.

External archives are never changed; extraction is only into pt_build.  This
module deliberately does NOT infer content from filenames alone: candidate
kinds are suggestions until the .blend is inspected inside Blender.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import stat
import tempfile
from zipfile import ZipFile, BadZipFile

MAX_ARCHIVE_BYTES = 450_000_000
MAX_TOTAL_UNPACKED = 1_300_000_000
MAX_FILE_BYTES = 400_000_000
MAX_ENTRIES = 1200
MAX_RATIO = 200
CATEGORIES = ('ARVORE', 'PLANTA', 'PEDRA', 'MATERIAL', 'DESCONHECIDO')


@dataclass(frozen=True)
class LibraryEntry:
    name: str
    kind: str
    path: str
    source: str
    ready: bool
    reason: str


def classify_name(name: str) -> str:
    lower = name.casefold()
    if 'tree' in lower or 'sapling' in lower:
        return 'ARVORE'
    if 'boulder' in lower or lower.startswith('tiger_rock'):
        return 'PEDRA'
    if 'celandine' in lower:
        return 'PLANTA'
    if any(x in lower for x in ('bark', 'ground', 'rocks', 'rock_face', 'cobblestone',
        'mud', 'marble', 'cliff', 'metal', 'sand', 'stone', 'wood', 'snow', 'leather', 'fabric')):
        return 'MATERIAL'
    return 'DESCONHECIDO'


def scan_library(root: Path) -> list[LibraryEntry]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        return []
    results = []
    # Only the library root, not a recursive scan of arbitrary user dirs.
    for p in sorted(root.iterdir(), key=lambda x: x.name.casefold()):
        if p.is_symlink() or not p.is_file():
            continue
        lower = p.name.casefold()
        kind = classify_name(p.name)
        is_zip = lower.endswith('.blend.zip')
        is_model = is_zip or lower.endswith(('.blend', '.glb'))
        is_material = lower.endswith(('.exr', '.hdr', '.png', '.jpg', '.jpeg')) or lower.endswith('.zip')
        if not is_model and not is_material:
            continue
        if is_model and kind == 'DESCONHECIDO':
            kind = 'PLANTA' if 'plant' in lower else 'DESCONHECIDO'
        # A Poly Haven .blend.zip can contain only a node/material setup.
        # Never offer such archives as tree models just because they are .blend.
        if kind == 'MATERIAL' or not is_model:
            kind = 'MATERIAL'
            is_model = False
        results.append(LibraryEntry(p.name, kind, str(p),
                                    'BLEND_ZIP' if is_zip else ('BLEND' if lower.endswith('.blend') else
                                    'GLB' if lower.endswith('.glb') else 'MATERIAL'),
                                    is_model, '' if is_model else 'MATERIAL_NAO_E_MODELO_3D'))
    return results


def model_entries(root: Path, category: str = 'ARVORE') -> list[LibraryEntry]:
    return [e for e in scan_library(root) if e.ready and e.kind == category]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def find_model_archive_blend(path: Path) -> str:
    """Return safe single .blend entry (reject ambiguous archives)."""
    with ZipFile(path) as z:
        safe = _checked_members(z)
        blend = [i.filename for i in safe if i.filename.casefold().endswith('.blend')]
        if len(blend) != 1:
            raise ValueError(f'ARQUIVO_BLEND_AMBIGUO:{len(blend)}')
        return blend[0]


def _checked_members(z: ZipFile):
    infos = z.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise ValueError('ZIP_NUM_ENTRADAS_INVALIDO')
    total = 0
    names = set()
    for info in infos:
        raw = info.filename
        rel = PurePosixPath(raw)
        if (not raw or '\\' in raw or rel.is_absolute() or '..' in rel.parts or
            any(s in ('', '.') for s in rel.parts) or ':' in raw or raw.startswith('/')):
            raise ValueError('ZIP_CAMINHO_INSEGURO')
        key = str(rel).casefold()
        if key in names:
            raise ValueError('ZIP_CAMINHO_DUPLICADO')
        names.add(key)
        mode = (info.external_attr >> 16)
        if stat.S_ISLNK(mode):
            raise ValueError('ZIP_SYMLINK_PROIBIDO')
        if info.file_size > MAX_FILE_BYTES:
            raise ValueError('ZIP_ENTRADA_MUITO_GRANDE')
        if info.file_size and info.file_size / max(1, info.compress_size) > MAX_RATIO:
            raise ValueError('ZIP_RAZAO_COMPRESSAO_SUSPEITA')
        total += info.file_size
        if total > MAX_TOTAL_UNPACKED:
            raise ValueError('ZIP_DEMASIADO_GRANDE')
    return infos


def prepare_model(source: Path, library_root: Path, cache_root: Path) -> Path:
    """Cache a safe .blend from a user-owned .blend.zip, or return a local .blend/.glb.

    Does not read or write anywhere outside the given validated roots except
    the read-only input path.  Cache is keyed by content SHA, not filename.
    """
    library_root = library_root.expanduser().resolve(strict=True)
    source = source.expanduser()
    if source.is_symlink() or not source.is_file() or source.parent.resolve() != library_root:
        raise ValueError('MODELO_FORA_BIBLIOTECA_OU_LINK')
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('MODELO_MUITO_GRANDE')
    suffix = source.name.casefold()
    if suffix.endswith(('.blend', '.glb')):
        return source.resolve()
    if not suffix.endswith('.blend.zip'):
        raise ValueError('MODELO_FORMATO_NAO_SUPORTADO')
    cache_root = cache_root.expanduser().resolve()
    if cache_root.is_symlink():
        raise ValueError('CACHE_LINK_PROIBIDO')
    digest = _sha256_file(source)
    dest = cache_root / digest
    marker = dest / '.v26_complete.json'
    if marker.is_file():
        state = json.loads(marker.read_text(encoding='utf-8'))
        selected = dest.joinpath(*PurePosixPath(state['blend']).parts)
        if state.get('source_sha256') == digest and selected.is_file() and not selected.is_symlink():
            return selected
        raise ValueError('CACHE_INCONSISTENTE_NAO_REUTILIZAR')
    if dest.exists():
        raise ValueError('CACHE_PARCIAL_NAO_SOBRESCREVER')
    cache_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.v26_unpack_', dir=cache_root))
    try:
        with ZipFile(source) as z:
            infos = _checked_members(z)
            blends = [i.filename for i in infos if i.filename.casefold().endswith('.blend')]
            if len(blends) != 1:
                raise ValueError(f'ARQUIVO_BLEND_AMBIGUO:{len(blends)}')
            for info in infos:
                target = staging.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as infile, target.open('xb') as outfile:
                    copied = 0
                    while True:
                        block = infile.read(1024 * 1024)
                        if not block:
                            break
                        copied += len(block)
                        if copied > info.file_size:
                            raise ValueError('ZIP_TAMANHO_INESPERADO')
                        outfile.write(block)
                    if copied != info.file_size:
                        raise ValueError('ZIP_TRUNCADO')
        (staging / '.v26_complete.json').write_text(json.dumps({
            'source_sha256': digest, 'source_name': source.name,
            'blend': blends[0], 'version': 1}, indent=2), encoding='utf-8')
        os.replace(staging, dest)
    except Exception:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dest.joinpath(*PurePosixPath(blends[0]).parts)


def inventory(root: Path) -> dict:
    records = [asdict(e) for e in scan_library(root)]
    return {'format':'PT_ETERVALE_ASSET_LIBRARY_V26',
            'library_root':str(root.expanduser().resolve()),
            'model_candidates':sum(e['ready'] for e in records),
            'material_files':sum(not e['ready'] for e in records),
            'entries':records}
