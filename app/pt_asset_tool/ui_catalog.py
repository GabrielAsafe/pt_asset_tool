from __future__ import annotations

import json
import os
import pathlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

UI_VERSION = "1.0.4"
BROWSER_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}
CONVERTIBLE_IMAGE_EXTS = {".tga"}
IMAGE_EXTS = BROWSER_IMAGE_EXTS | CONVERTIBLE_IMAGE_EXTS
TEXTURE_EXTS = IMAGE_EXTS | {".dds"}
MODEL_EXTS = {".smd"}
CONFIG_EXTS = {".inx", ".inf", ".ini", ".txt", ".lst"}
MOTION_EXTS = {".smb"}
AUDIO_EXTS = {".wav", ".ogg", ".mp3", ".mid", ".bgm"}
PACKAGE_EXTS = {".pkg", ".gpk", ".cab"}
SYSTEM_BINARY_EXTS = {".exe", ".dll", ".ocx", ".sys"}
OPERATIONAL_EXTS = {".log", ".rep", ".cl", ".dmp", ".tmp"}
NOISE_EXTS = {".bak", ".old", ".orig"}
HIDDEN_VISIBILITY_TIERS = {"OPERATIONAL", "USER_DATA", "INSTALLER_SYSTEM", "NOISE"}
EFFECT_SCRIPT_EXTS = {".part", ".lua"}

EXTENSION_DESCRIPTIONS = {
    ".smd": "Modelo 3D / Stage SMD",
    ".smb": "Skeleton e animações",
    ".inx": "Configuração, binding e MotionInfo",
    ".inf": "Configuração/metadata auxiliar",
    ".bmp": "Imagem/textura BMP",
    ".tga": "Imagem/textura TGA",
    ".dds": "Textura DDS",
    ".png": "Imagem PNG",
    ".jpg": "Imagem JPEG",
    ".jpeg": "Imagem JPEG",
    ".gif": "Imagem GIF",
    ".webp": "Imagem WebP",
    ".ico": "Ícone",
    ".wav": "Áudio/efeito sonoro",
    ".ase": "Modelo/cena ASCII 3D (ASE)",
    ".pkg": "Pacote de effect/assets",
    ".gpk": "Pacote de assets",
    ".cab": "Pacote de sistema/instalador (normalmente DirectX/runtime)",
    ".exe": "Executável/runtime do cliente",
    ".dll": "Biblioteca runtime do cliente",
    ".log": "Log operacional",
    ".bak": "Backup/artefato auxiliar",
    ".db": "Base/cache auxiliar",
    ".sin": "Dados runtime do jogo",
    ".part": "Fragmento/parte de pacote",
    ".ini": "Configuração INI",
    ".txt": "Texto/configuração",
    ".lst": "Lista/configuração",
}

UI_PATH_HINTS = {
    "interface", "native", "settings", "party", "postbox", "shop", "bellatra",
    "guidemap", "clanimage", "emoji", "fonts", "streaming",
}


UI_TOPLEVEL_PREFIXES = (
    "arrow", "bpheader", "chk-", "cw", "default", "eachbox", "ico_", "infectado",
    "line", "loading", "logo", "mapbox", "map-cd", "mbox", "m_", "mk-",
    "more_informations", "npc", "party",
)
UI_SUBROLE_HINTS = {
    "interface": "PANEL", "native": "NATIVE_UI", "settings": "SETTINGS_UI", "party": "PARTY_UI",
    "postbox": "POSTBOX_UI", "shop": "SHOP_UI", "bellatra": "BELLATRA_UI", "guidemap": "MAP_UI",
    "clanimage": "CLAN_UI", "emoji": "EMOJI", "fonts": "FONT", "streaming": "STREAMING_UI",
}

# Path-based UI semantics.  These rules describe the client hierarchy and do
# not grant writer/runtime authority.  They deliberately precede the broad
# UI_SUBROLE_HINTS so a path such as Image/Sinimage/Inter/Chat gets the useful
# functional role CHAT rather than the generic PANEL role.
UI_PATH_ROLE_RULES = (
    ("/startimage/opening/npc/", "FRONTEND_NPC"),
    ("/startimage/opening/", "LOGIN"),
    ("/startimage/login/loading/", "LOADING"),
    ("/startimage/loading/", "LOADING"),
    ("/startimage/messagebox/", "MESSAGE_BOX"),
    ("/startimage/sky/", "FRONTEND_SCENE"),
    ("/image/sinimage/inter/chat/", "CHAT"),
    ("/image/sinimage/inter/buttoninfo/", "TOOLTIP"),
    ("/image/sinimage/inter/singage/", "GAUGE"),
    ("/image/sinimage/inter/skillicon/", "SKILL"),
    ("/image/sinimage/inter/restart/", "RESPAWN"),
    ("/image/sinimage/status/", "CHARACTER_STATUS"),
    ("/image/sinimage/npc/", "NPC_DIALOG"),
    ("/image/sinimage/inven/", "INVENTORY"),
    ("/image/sinimage/quest/", "QUEST"),
    ("/image/sinimage/shopall/", "SHOP"),
    ("/image/sinimage/indishop/", "SHOP"),
    ("/image/sinimage/messagebox/", "MESSAGE_BOX"),
    ("/image/sinimage/cursor/", "CURSOR"),
    ("/image/sinimage/help/", "HELP"),
    ("/image/sinimage/skill/", "SKILL"),
    ("/image/sinimage/premium/", "PREMIUM"),
    ("/image/sinimage/siege/", "SIEGE"),
)

PLAYER_BODY_RE = re.compile(r"(?i)^[c6w]?[tm][mf]b[a-z]")
PLAYER_HEAD_RE = re.compile(r"(?i)^[c6w]?[tm][mf]h[a-z]")


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").strip("/")


def extension_description(ext: str) -> str:
    ext = (ext or "").lower()
    if not ext:
        return "Arquivo sem extensão"
    return EXTENSION_DESCRIPTIONS.get(ext, "Tipo de arquivo não catalogado")


def _role_for_entity_file(ext: str) -> str:
    if ext == ".smd":
        return "MODEL"
    if ext == ".smb":
        return "ANIMATION"
    if ext in {".inx", ".inf"}:
        return "CONFIG"
    if ext in TEXTURE_EXTS:
        return "TEXTURE"
    if ext == ".wav":
        return "AUDIO"
    if ext == ".ase":
        return "SOURCE_3D"
    return "SUPPORT"



def infer_physical_family(rel: str, ext: str) -> str:
    """Physical/runtime family, independent from the functional path category."""
    ext = (ext or "").casefold()
    low = "/" + _norm(rel).casefold() + "/"
    if ext in AUDIO_EXTS:
        return "AUDIO"
    if ext in TEXTURE_EXTS:
        return "TEXTURE"
    if ext == ".smd":
        return "MODEL"
    if ext == ".smb":
        return "MOTION"
    if ext == ".inx":
        return "MODEL_METADATA"
    if ext in EFFECT_SCRIPT_EXTS:
        return "EFFECT_SCRIPT"
    if ext == ".fnt":
        return "FONT_DATA"
    if ext == ".fx":
        return "SHADER"
    if ext == ".zif":
        return "COMPRESSED_ITEM_DATA"
    if ext == ".sct":
        return "FIELD_DATA"
    if ext == ".cab":
        return "SYSTEM_PACKAGE"
    if ext in {".pkg", ".gpk"}:
        return "GAME_PACKAGE"
    if ext in SYSTEM_BINARY_EXTS:
        return "RUNTIME_BINARY"
    if ext in {".msg", ".sin", ".ini", ".inf", ".txt", ".lst", ".dat", ".json", ".xml"}:
        return "DATA"
    return "OTHER"

def infer_folder_bucket(rel: str, category: str) -> tuple[str, str]:
    """Return a useful folder facet label + root path for catalog navigation.

    The goal is not to infer runtime semantics from names. It exposes the
    client hierarchy itself so a user can narrow e.g. NPC -> Ahin or
    MONSTER -> Acero without turning folder names into writer authority.
    """
    path = _norm(rel)
    parts = pathlib.PurePosixPath(path).parts
    low = [x.lower() for x in parts]

    def after(marker: tuple[str, ...]) -> tuple[str, str] | None:
        n = len(marker)
        for i in range(0, len(low) - n + 1):
            if tuple(low[i:i+n]) == marker and i + n < len(parts):
                name = parts[i+n]
                return name, "/".join(parts[:i+n+1])
        return None

    cat = (category or "").upper()
    # UI benefits from one additional hierarchy level.  "Items" or "Inter"
    # alone are too broad; expose Items/Defense and Inter/Chat as selectable
    # folders while keeping the facet grounded in the physical tree.
    if cat == "UI":
        for marker in (("image", "sinimage"), ("startimage",)):
            n = len(marker)
            for i in range(0, len(low) - n + 1):
                if tuple(low[i:i+n]) != marker or i + n >= len(parts):
                    continue
                first = parts[i+n]
                depth = 1
                if first.lower() in {"items", "inter"} and i + n + 1 < len(parts) - 1:
                    depth = 2
                chosen = parts[i+n:i+n+depth]
                return "/".join(chosen), "/".join(parts[:i+n+depth])
    candidates: list[tuple[str, ...]] = []
    if cat == "AUDIO":
        # Keep audio folders structural. Do not expose class/person names as
        # folder facets; class ownership has its own dedicated filter.
        for marker in (("sound", "character"), ("wav", "effects", "player"), ("sound",), ("wav",), ("audio",)):
            n = len(marker)
            for i in range(0, len(low) - n + 1):
                if tuple(low[i:i+n]) == marker:
                    label = "/".join(parts[i:i+n])
                    return label, "/".join(parts[:i+n])
    if cat == "NPC":
        candidates = [("char", "npc"), ("image", "sinimage", "npc"), ("npc",)]
    elif cat == "MONSTER":
        candidates = [("char", "monster"), ("char", "monsters"), ("monster",), ("monsters",)]
    elif cat == "CHARACTER":
        candidates = [("char",), ("character",), ("player",)]
    elif cat == "ITEM":
        candidates = [("image", "sinimage", "items"), ("items",)]
    elif cat == "UI":
        candidates = [("image", "sinimage"), ("startimage",)]
    elif cat in {"MAP", "MAP_FIELD"}:
        candidates = [("field",), ("game", "maps"), ("map",), ("stage",)]
    elif cat == "EFFECT":
        candidates = [("effect", "assaeffect"), ("effect",)]
    for marker in candidates:
        hit = after(marker)
        if hit:
            return hit
    parent = pathlib.PurePosixPath(path).parent
    if parent.as_posix() not in {".", ""}:
        return parent.name, parent.as_posix()
    return "(raiz)", ""


def infer_visibility_tier(rel: str, ext: str, category: str = "", role: str = "") -> str:
    """Classify catalog visibility without deleting or mutating client files.

    The default UI hides only operational/system/user noise. Content/reference
    assets remain visible even when their extension is uncommon.
    """
    path = _norm(rel)
    low = path.casefold()
    name = pathlib.PurePosixPath(path).name.casefold()
    ext = (ext or "").casefold()
    parts = set(pathlib.PurePosixPath(low).parts)

    if name == "thumbs.db" or ext in NOISE_EXTS or name.endswith(".bak"):
        return "NOISE"
    if ext in OPERATIONAL_EXTS or any(x in low for x in ("/logs/", "/log/", "debugtrace", "debug_trace", "trace.log")):
        return "OPERATIONAL"
    if ext == ".cab" or "directx" in parts or "redist" in parts or "installer" in parts:
        return "INSTALLER_SYSTEM"
    if ext in SYSTEM_BINARY_EXTS:
        return "INSTALLER_SYSTEM"
    if any(x in low for x in ("savedata", "clandata", "userdata", "user_data", "screenshots/")):
        return "USER_DATA"
    if str(role).upper() in {"SYSTEM_PACKAGE"}:
        return "INSTALLER_SYSTEM"
    if str(category).upper() in {"UI", "CHARACTER", "MONSTER", "NPC", "ITEM", "MAP", "EFFECT", "MODEL", "TEXTURE", "MOTION"}:
        return "AUTHORABLE"
    if ext in {".ase", ".inx", ".inf", ".ini", ".txt", ".lst", ".sin", ".msg", ".sct", ".pkg", ".gpk"}:
        return "REFERENCE"
    return "RUNTIME_SUPPORT"


def infer_semantics(rel: str, ext: str) -> tuple[str, str]:
    """Return broad category + role. These are UI hints, never format authority."""
    path = _norm(rel)
    low = "/" + path.lower() + "/"
    stem = pathlib.PurePosixPath(path).stem
    parts = set(path.lower().split("/"))

    # Strong UI/function evidence wins over filename tokens such as ha01.
    # This prevents message-box/button families (including historical habox)
    # from ever being promoted to CHARACTER by broad name heuristics.
    if any(token in parts for token in {"messagebox", "button", "buttons", "habox", "chipbutton"}):
        if ext in TEXTURE_EXTS or ext in MODEL_EXTS:
            return "UI", "MESSAGE_BOX" if ("messagebox" in parts or "habox" in parts) else "UI_COMPONENT"

    # Image/Sinimage/Items mixes inventory UI art with world drop assets.
    # Keep the two concepts separate: icons are UI, DropItem is a world/item
    # family and may contain SMD/ASE as well as textures.
    if "/image/sinimage/items/dropitem/" in low:
        if ext == ".smd":
            return "ITEM", "DROP_MODEL"
        if ext == ".ase":
            return "ITEM", "DROP_SOURCE_3D"
        if ext in TEXTURE_EXTS:
            return "ITEM", "DROP_TEXTURE"
        return "ITEM", "DROP_SUPPORT"
    item_icon_roles = {
        "/image/sinimage/items/defense/": "ITEM_ICON_DEFENSE",
        "/image/sinimage/items/weapon/": "ITEM_ICON_WEAPON",
        "/image/sinimage/items/accessory/": "ITEM_ICON_ACCESSORY",
        "/image/sinimage/items/premium/": "ITEM_ICON_PREMIUM",
    }
    for marker, item_role in item_icon_roles.items():
        if marker in low:
            if ext in TEXTURE_EXTS:
                return "UI", item_role
            # Rare non-image files in icon folders stay in ITEM rather than
            # being mislabeled as UI bitmaps.
            return "ITEM", _role_for_entity_file(ext)

    for marker, ui_role in UI_PATH_ROLE_RULES:
        if marker in low:
            return "UI", ui_role

    if "/image/sinimage/inter/" in low:
        return "UI", "HUD"

    # Runtime entity trees are semantic evidence only after the known frontend
    # / UI trees above have had a chance to claim paths containing words such
    # as "npc".  This prevents StartImage/Opening/npc and Sinimage/NPC from
    # polluting the runtime NPC category while retaining char/npc as a real
    # physical entity hierarchy.
    if "/monster/" in low or "/monsters/" in low:
        return "MONSTER", _role_for_entity_file(ext)
    if "/npc/" in low or "/npcs/" in low:
        return "NPC", _role_for_entity_file(ext)

    for hint, subrole in UI_SUBROLE_HINTS.items():
        if hint in parts:
            return "UI", subrole
    pure = pathlib.PurePosixPath(path)
    if len(pure.parts) == 2 and pure.parts[0].lower() == "image" and ext in TEXTURE_EXTS:
        n = pure.name.lower()
        if any(n.startswith(prefix) for prefix in UI_TOPLEVEL_PREFIXES):
            return "UI", "UI_TEXTURE"
    if "/sinimage/items/" in low:
        if ext in TEXTURE_EXTS:
            return "UI", "ITEM_ICON"
        return "ITEM", _role_for_entity_file(ext)
    if "/assaeffect/" in low or "/effect/" in low:
        if ext in EFFECT_SCRIPT_EXTS:
            return "EFFECT", "EFFECT_SCRIPT"
        if ext in {".pkg", ".gpk"}:
            return "EFFECT", "GAME_PACKAGE"
        return "EFFECT", "EFFECT"
    if "/field/" in low or "/map/" in low or "/stage/" in low:
        if ext == ".sin":
            return "MAP", "RUNTIME_DATA"
        return "MAP", "WORLD"
    # Audio remains AUDIO even when physically stored below char/player trees.
    # Character ownership is a separate dependency-backed facet.
    if ext in AUDIO_EXTS:
        return "AUDIO", "CHARACTER_AUDIO" if ("/char/" in low or "/character/" in low or "/player/" in low) else "AUDIO"
    if "/char/" in low or "/character/" in low or "/player/" in low:
        if ext == ".smb":
            return "CHARACTER", "SKELETON_MOTION"
        if ext in {".inx", ".inf"}:
            return "CHARACTER", "CONFIG"
        if PLAYER_HEAD_RE.match(stem):
            return "CHARACTER", "HEAD"
        if PLAYER_BODY_RE.match(stem):
            return "CHARACTER", "BODY"
        if ext == ".smd":
            return "CHARACTER", "MODEL"
        return "CHARACTER", "SUPPORT"
    if ext in AUDIO_EXTS:
        return "AUDIO", "AUDIO"
    if ext in EFFECT_SCRIPT_EXTS:
        return "EFFECT", "EFFECT_SCRIPT"
    if ext == ".sin":
        if "warp" in parts or "warpgate" in parts:
            return "MAP", "WARP_DATA"
        if "event" in parts or "events" in parts:
            return "MAP", "EVENT_DATA"
        return "DATA", "RUNTIME_DATA"
    if ext == ".msg":
        return "DATA", "RUNTIME_DATA"
    if ext == ".fnt":
        return "UI", "FONT"
    if ext == ".fx":
        return "SHADER", "SHADER"
    if ext == ".zif":
        return "ITEM", "ITEM_ANIMATION_DATA"
    if ext == ".sct":
        return "MAP", "FIELD_DATA"
    if ext in MOTION_EXTS:
        return "MOTION", "SKELETON_MOTION"
    if ext in MODEL_EXTS:
        return "MODEL", "MODEL"
    if ext in TEXTURE_EXTS:
        return "TEXTURE", "TEXTURE"
    if ext in CONFIG_EXTS:
        return "CONFIG", "CONFIG"
    if ext == ".cab":
        return "SYSTEM", "SYSTEM_PACKAGE"
    if ext in {".pkg", ".gpk"}:
        return "PACKAGE", "GAME_PACKAGE"
    if ext in SYSTEM_BINARY_EXTS:
        return "SYSTEM", "RUNTIME_BINARY"
    if ext in OPERATIONAL_EXTS:
        return "SYSTEM", "OPERATIONAL_LOG"
    if ext in NOISE_EXTS or pathlib.PurePosixPath(path).name.casefold() == "thumbs.db":
        return "SYSTEM", "NOISE"
    return "OTHER", "UNKNOWN"


def sniff_physical_hint(path: pathlib.Path, ext: str) -> str:
    if ext == ".smd":
        try:
            with path.open("rb") as f:
                head = f.read(64)
            if b"SMD Model data Ver 0.72" in head:
                return "SMD_MODEL_072"
            if b"SMD Model data Ver 0.62" in head:
                return "SMD_MODEL_062"
            return "SMD_UNKNOWN"
        except OSError:
            return "SMD_UNREADABLE"
    if ext == ".smb":
        return "SMB"
    if ext in TEXTURE_EXTS:
        return "TEXTURE"
    return ""


def infer_capabilities(rel: str, ext: str, category: str, role: str, physical_hint: str = "") -> list[str]:
    """Return only capabilities provable from the catalog scan itself.

    Model0.62 actions depend on registry family/binding/source semantics and are
    enriched lazily by the UI backend for the selected asset. Extension-only
    guessing previously exposed invalid Structural/Bindings/Motions buttons.
    """
    caps = ["inspect"]
    if ext == ".smd" and physical_hint == "SMD_MODEL_072":
        caps += [
            "view_stage072", "paint_stage072", "validate_stage072_preview",
            "validate_stage072_uv_roundtrip", "validate_stage072_geometry_roundtrip",
        ]
    return sorted(set(caps))


@dataclass
class CatalogStats:
    file_count: int = 0
    total_bytes: int = 0
    indexed_at: float = 0.0


class UIStateStore:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"format": "PT_ASSET_UI_STATE_V1", "version": UI_VERSION, "revision": 0, "assets": {}}
        self._load()

    def _load(self) -> None:
        with self._lock:
            try:
                if self.path.is_file():
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("assets"), dict):
                        raw.setdefault("revision", 0)
                        self._data = raw
            except Exception:
                # Broken UI metadata must never block the asset tool.
                pass


    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._data.get("revision") or 0)

    def get(self, rel: str) -> dict[str, Any]:
        with self._lock:
            v = self._data.get("assets", {}).get(_norm(rel), {})
            return dict(v) if isinstance(v, dict) else {}

    def update(self, rel: str, patch: dict[str, Any]) -> dict[str, Any]:
        rel = _norm(rel)
        allowed = {"favorite", "role_override", "category_override", "character_override", "tags", "notes"}
        clean: dict[str, Any] = {}
        for k, v in patch.items():
            if k not in allowed:
                continue
            if k == "favorite":
                clean[k] = bool(v)
            elif k in {"role_override", "category_override", "character_override"}:
                clean[k] = str(v or "")[:80]
            elif k == "notes":
                clean[k] = str(v or "")[:4000]
            elif k == "tags":
                if isinstance(v, list):
                    clean[k] = sorted({str(x).strip()[:48] for x in v if str(x).strip()})[:40]
                elif isinstance(v, str):
                    clean[k] = sorted({x.strip()[:48] for x in v.split(",") if x.strip()})[:40]
        with self._lock:
            assets = self._data.setdefault("assets", {})
            current = dict(assets.get(rel, {}))
            current.update(clean)
            current["updated_at"] = time.time()
            assets[rel] = current
            self._data["revision"] = int(self._data.get("revision") or 0) + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
            return dict(current)


class CatalogIndex:
    def __init__(self, client_root: pathlib.Path, state: UIStateStore):
        self.client_root = client_root.resolve()
        self.state = state
        self.assets: list[dict[str, Any]] = []
        self.by_path: dict[str, dict[str, Any]] = {}
        self.stats = CatalogStats()
        self.revision = 0
        self.source_mode = "UNINITIALIZED"
        self.source_signature: dict[str, Any] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _physical_hint_from_inventory(record: dict[str, Any], ext: str) -> str:
        kind = str(record.get("kind") or "").upper()
        if ext == ".smd":
            if kind == "SMD_STAGE_072":
                return "SMD_MODEL_072"
            if kind.startswith("SMD_MODEL_062") or str(record.get("compatibility_family") or "").upper().startswith("SMD_MODEL_062"):
                return "SMD_MODEL_062"
            return "SMD_UNKNOWN"
        if ext == ".smb":
            return "SMB"
        if ext in TEXTURE_EXTS:
            return "TEXTURE"
        return ""

    def rebuild_from_inventory(self, inventory_path: pathlib.Path, *, registry_meta_path: pathlib.Path | None = None) -> CatalogStats:
        """Populate the UI catalog from the persisted physical census.

        The runtime registry already stores relative path, size, mtime and physical
        inspection for every client file. Re-reading that JSON avoids a second
        rglob/stat/header-sniff pass on every UI start. Explicit Reindex remains
        the operation that refreshes the persisted census from disk.
        """
        inventory_path = pathlib.Path(inventory_path)
        raw = json.loads(inventory_path.read_text(encoding="utf-8"))
        saved_root = pathlib.Path(str(raw.get("canonical_client_root") or "")).expanduser()
        try:
            if saved_root.resolve() != self.client_root:
                raise ValueError("CATALOG_INVENTORY_CLIENT_ROOT_MISMATCH")
        except OSError:
            raise ValueError("CATALOG_INVENTORY_CLIENT_ROOT_MISMATCH")
        records = raw.get("records")
        if not isinstance(records, list):
            raise ValueError("CATALOG_INVENTORY_RECORDS_INVALID")
        rows: list[dict[str, Any]] = []
        total = 0
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rel = _norm(str(rec.get("relative_path") or ""))
            if not rel:
                continue
            ext = str(rec.get("extension") or pathlib.PurePosixPath(rel).suffix).lower()
            category, role = infer_semantics(rel, ext)
            folder, folder_path = infer_folder_bucket(rel, category)
            meta = self.state.get(rel)
            category_effective = meta.get("category_override") or category
            role_effective = meta.get("role_override") or role
            physical_hint = self._physical_hint_from_inventory(rec, ext)
            row = {
                "path": rel,
                "name": pathlib.PurePosixPath(rel).name,
                "ext": ext,
                "size": int(rec.get("size") or 0),
                "mtime_ns": int(rec.get("mtime_ns") or 0),
                "category": category_effective,
                "role": role_effective,
                "inferred_category": category,
                "inferred_role": role,
                "physical_family": infer_physical_family(rel, ext),
                "folder": folder,
                "folder_path": folder_path,
                "extension_description": extension_description(ext),
                "favorite": bool(meta.get("favorite")),
                "tags": list(meta.get("tags") or []),
                "notes": str(meta.get("notes") or ""),
                "character": str(meta.get("character_override") or ""),
                "inferred_character": "",
                "character_evidence": [],
                "character_candidates": [],
                "physical_hint": physical_hint,
                "capabilities": infer_capabilities(rel, ext, category, role, physical_hint),
                "previewable": ext in IMAGE_EXTS,
            }
            row["visibility_tier"] = infer_visibility_tier(rel, ext, category_effective, role_effective)
            row["system_operational"] = row["visibility_tier"] in HIDDEN_VISIBILITY_TIERS
            row["_search_text"] = " ".join([
                rel, category_effective, role_effective, row.get("character", ""), folder, folder_path,
                row["extension_description"], row["visibility_tier"],
                " ".join(row["tags"]), row["notes"],
            ]).casefold()
            rows.append(row)
            total += int(row["size"])
        source_signature: dict[str, Any] = {}
        meta_path = pathlib.Path(registry_meta_path) if registry_meta_path else inventory_path.parent / "registry_meta.json"
        try:
            if meta_path.is_file():
                meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
                source_signature = dict(meta_raw.get("client_signature") or {})
        except Exception:
            source_signature = {}
        with self._lock:
            self.assets = rows
            self.by_path = {r["path"]: r for r in rows}
            self.stats = CatalogStats(len(rows), total, time.time())
            self.source_mode = "PERSISTED_RUNTIME_REGISTRY"
            self.source_signature = source_signature
            self.revision += 1
            return self.stats

    def rebuild(self) -> CatalogStats:
        rows: list[dict[str, Any]] = []
        total = 0
        for p in sorted(self.client_root.rglob("*"), key=lambda x: x.as_posix().lower()):
            try:
                if not p.is_file():
                    continue
                rel = p.relative_to(self.client_root).as_posix()
                st = p.stat()
            except OSError:
                continue
            ext = p.suffix.lower()
            physical_hint = sniff_physical_hint(p, ext)
            category, role = infer_semantics(rel, ext)
            folder, folder_path = infer_folder_bucket(rel, category)
            meta = self.state.get(rel)
            category_effective = meta.get("category_override") or category
            role_effective = meta.get("role_override") or role
            row = {
                "path": rel,
                "name": p.name,
                "ext": ext,
                "size": int(st.st_size),
                "mtime_ns": int(st.st_mtime_ns),
                "category": category_effective,
                "role": role_effective,
                "inferred_category": category,
                "inferred_role": role,
                "physical_family": infer_physical_family(rel, ext),
                "folder": folder,
                "folder_path": folder_path,
                "extension_description": extension_description(ext),
                "favorite": bool(meta.get("favorite")),
                "tags": list(meta.get("tags") or []),
                "notes": str(meta.get("notes") or ""),
                "character": str(meta.get("character_override") or ""),
                "inferred_character": "",
                "character_evidence": [],
                "character_candidates": [],
                "physical_hint": physical_hint,
                "capabilities": infer_capabilities(rel, ext, category, role, physical_hint),
                "previewable": ext in IMAGE_EXTS,
            }
            row["visibility_tier"] = infer_visibility_tier(rel, ext, category_effective, role_effective)
            row["system_operational"] = row["visibility_tier"] in HIDDEN_VISIBILITY_TIERS
            row["_search_text"] = " ".join([
                rel, category_effective, role_effective, row.get("character", ""), folder, folder_path,
                row["extension_description"], row["visibility_tier"],
                " ".join(row["tags"]), row["notes"],
            ]).casefold()
            rows.append(row)
            total += int(st.st_size)
        with self._lock:
            self.assets = rows
            self.by_path = {r["path"]: r for r in rows}
            self.stats = CatalogStats(len(rows), total, time.time())
            self.source_mode = "PHYSICAL_SCAN"
            self.source_signature = {}
            self.revision += 1
            return self.stats

    def get_asset(self, rel: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.by_path.get(_norm(rel))
            return dict(row) if row else None

    def apply_state_update(self, rel: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        rel = _norm(rel)
        with self._lock:
            if rel not in self.by_path:
                return None
        meta = self.state.update(rel, patch)
        with self._lock:
            row = self.by_path.get(rel)
            if not row:
                return None
            row["favorite"] = bool(meta.get("favorite"))
            row["tags"] = list(meta.get("tags") or [])
            row["notes"] = str(meta.get("notes") or "")
            row["category"] = meta.get("category_override") or row["inferred_category"]
            row["role"] = meta.get("role_override") or row["inferred_role"]
            row["character"] = meta.get("character_override") or row.get("inferred_character") or ""
            row["visibility_tier"] = infer_visibility_tier(rel, row.get("ext", ""), row["category"], row["role"])
            row["system_operational"] = row["visibility_tier"] in HIDDEN_VISIBILITY_TIERS
            row["_search_text"] = " ".join([
                str(row.get("path") or ""), str(row.get("category") or ""), str(row.get("role") or ""), str(row.get("character") or ""),
                str(row.get("folder") or ""), str(row.get("folder_path") or ""),
                str(row.get("extension_description") or ""), str(row.get("visibility_tier") or ""),
                " ".join(row.get("tags") or []), str(row.get("notes") or ""),
            ]).casefold()
            self.revision += 1
            return dict(row)

    def apply_character_index(self, index: dict[str, Any]) -> None:
        by_path = index.get("by_path") or {}
        with self._lock:
            for row in self.assets:
                rel = str(row.get("path") or "")
                meta = self.state.get(rel)
                info = by_path.get(rel.casefold()) or {}
                inferred = str(info.get("owner") or "")
                row["inferred_character"] = inferred
                row["character"] = str(meta.get("character_override") or inferred)
                row["character_evidence"] = list(info.get("evidence") or [])
                row["character_candidates"] = list(info.get("candidates") or [])
                row["character_status"] = str(info.get("status") or "UNCLASSIFIED")
                row["character_filename_hint"] = str(info.get("filename_hint") or "")
                row["_search_text"] = " ".join([
                    str(row.get("path") or ""), str(row.get("category") or ""), str(row.get("role") or ""),
                    str(row.get("character") or ""), str(row.get("folder") or ""), str(row.get("folder_path") or ""),
                    str(row.get("extension_description") or ""), str(row.get("visibility_tier") or ""),
                    " ".join(row.get("tags") or []), str(row.get("notes") or ""),
                ]).casefold()
            self.by_path = {r["path"]: r for r in self.assets}

    def annotation_options(self) -> dict[str, list[str]]:
        with self._lock:
            rows = self.assets
            categories = sorted({str(r.get("category") or "") for r in rows if r.get("category")}, key=str.casefold)
            roles = sorted({str(r.get("role") or "") for r in rows if r.get("role")}, key=str.casefold)
            characters = sorted({str(r.get("character") or "") for r in rows if r.get("character")}, key=str.casefold)
        return {"categories": categories, "roles": roles, "characters": characters}

    def query(
        self,
        q: str = "",
        category: str = "",
        folder: str = "",
        role: str = "",
        character: str = "",
        ext: str = "",
        preview_status: str = "",
        favorites: bool = False,
        show_system: bool = False,
        allowed_paths: set[str] | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        q_tokens = [x.lower() for x in q.split() if x.strip()]
        category = category.strip().upper()
        folder = folder.strip()
        role = role.strip().upper()
        character = character.strip().casefold()
        ext = ext.strip().lower()
        preview_status = preview_status.strip().upper()
        no_extension = ext == "__no_ext__"
        if ext and not no_extension and not ext.startswith("."):
            ext = "." + ext
        page = max(1, int(page))
        page_size = min(500, max(10, int(page_size)))
        with self._lock:
            # rebuild() replaces the list atomically; retaining this reference is
            # a safe immutable snapshot and avoids copying tens of thousands of rows.
            src = self.assets
        if allowed_paths is not None:
            wanted = {_norm(x).casefold() for x in allowed_paths}
            src = [r for r in src if str(r.get("path") or "").casefold() in wanted]
        if not show_system:
            src = [r for r in src if str(r.get("visibility_tier") or "") not in HIDDEN_VISIBILITY_TIERS]
        out = []
        for r in src:
            if category and r["category"].upper() != category:
                continue
            if folder and r.get("folder_path", "") != folder:
                continue
            if role and r["role"].upper() != role:
                continue
            if character and str(r.get("character") or "").casefold() != character:
                continue
            if no_extension and r["ext"]:
                continue
            if ext and not no_extension and r["ext"] != ext:
                continue
            if preview_status:
                if str(r.get("ext") or "").casefold() != ".smd":
                    continue
                if str(r.get("smd_preview_status") or "MISSING").upper() != preview_status:
                    continue
            if favorites and not r["favorite"]:
                continue
            if q_tokens:
                hay = str(r.get("_search_text") or "")
                if not all(t in hay for t in q_tokens):
                    continue
            out.append(r)
        total = len(out)
        start = (page - 1) * page_size
        end = start + page_size
        cats = collections_count(src, "category")
        category_rows = [r for r in src if not category or r["category"].upper() == category]
        characters = collections_count(category_rows, "character")
        character_rows = [r for r in category_rows if not character or str(r.get("character") or "").casefold() == character]
        folders = collections_count(character_rows, "folder_path", label_key="folder")
        folder_rows = [r for r in character_rows if not folder or r.get("folder_path", "") == folder]
        roles = collections_count(folder_rows, "role")
        role_rows = [r for r in folder_rows if not role or r["role"].upper() == role]
        exts = collections_count(role_rows, "ext", description=True)
        previews = collections_count([r for r in role_rows if str(r.get("ext") or "").casefold() == ".smd"], "smd_preview_status")
        return {
            "items": [{k: v for k, v in x.items() if not k.startswith("_")} for x in out[start:end]],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "facets": {"categories": cats, "characters": characters, "folders": folders, "roles": roles, "extensions": exts},
            "performance": {"query_ms": round((time.perf_counter() - started) * 1000.0, 3), "revision": self.revision},
        }


def collections_count(
    rows: list[dict[str, Any]],
    key: str,
    *,
    label_key: str | None = None,
    description: bool = False,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for r in rows:
        v = str(r.get(key) or "")
        counts[v] = counts.get(v, 0) + 1
        if label_key and v not in labels:
            labels[v] = str(r.get(label_key) or v)
    result = []
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], (labels.get(kv[0]) or kv[0]).lower())):
        item = {"value": k, "count": v}
        if label_key:
            item["label"] = labels.get(k) or k
        if description:
            item["description"] = extension_description(k)
        result.append(item)
    return result
