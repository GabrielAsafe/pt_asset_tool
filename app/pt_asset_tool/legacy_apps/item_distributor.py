from __future__ import annotations

import dataclasses
from pathlib import Path
import re
from typing import Any

from .common import atomic_write_bytes, backup_file, item_distributor_bucket, sha256_file

FORMAT = "PT_LEGACY_ITEM_DISTRIBUTOR_V1"
APPLY_CONFIRM = "APPLY ITEM DISTRIBUTION"
EDIT_CONFIRM = "APPLY POSTBOX EDIT"
SPEC_NAMES = (
    "Non Spec", "Fighter", "Mechanician", "Archer", "Pikeman",
    "Atalanta", "Knight", "Magician", "Priestess",
)
_QUEUE_RE = re.compile(r'^\s*(\S+)\s+(\S+)\s+(-?\d+)\s+"(.*)"\s*$')


@dataclasses.dataclass(frozen=True)
class QueueEntry:
    character: str
    item_code: str
    spec_index: int
    message: str

    @property
    def spec_name(self) -> str:
        return SPEC_NAMES[self.spec_index] if 0 <= self.spec_index < len(SPEC_NAMES) else f"Unknown({self.spec_index})"

    def legacy_line(self) -> str:
        # The .NET original does not escape quotes.  Refuse them rather than emit
        # an ambiguous queue line.
        if '"' in self.message or "\r" in self.message or "\n" in self.message:
            raise ValueError("POSTBOX_MESSAGE_MUST_NOT_CONTAIN_QUOTES_OR_NEWLINES")
        return f'{self.character} {self.item_code} {self.spec_index} "{self.message}"'


def _postbox_path(server_root: Path, account: str) -> Path:
    return Path(server_root) / "Postbox" / str(item_distributor_bucket(account)) / f"{account}.dat"


def _character_path(server_root: Path, character: str) -> Path:
    return Path(server_root) / "DataServer" / "userdata" / str(item_distributor_bucket(character)) / f"{character}.dat"


def parse_queue_text(text: str) -> list[QueueEntry]:
    out: list[QueueEntry] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        m = _QUEUE_RE.match(raw)
        if not m:
            raise ValueError(f"INVALID_POSTBOX_LINE:{lineno}")
        out.append(QueueEntry(m.group(1), m.group(2), int(m.group(3)), m.group(4)))
    return out


def read_queue(server_root: Path, account: str) -> dict[str, Any]:
    path = _postbox_path(server_root, account)
    if not path.is_file():
        return {"format": FORMAT, "status": "EMPTY", "path": str(path), "entries": [], "sha256": None}
    raw = path.read_bytes()
    # Legacy writer uses StreamWriter default encoding.  UTF-8 is the usual .NET
    # default; utf-8-sig also accepts a BOM if one is present.
    text = raw.decode("utf-8-sig", errors="replace")
    entries = parse_queue_text(text)
    return {
        "format": FORMAT,
        "status": "PASS",
        "path": str(path),
        "sha256": sha256_file(path),
        "entries": [dataclasses.asdict(x) | {"spec_name": x.spec_name} for x in entries],
        "raw_text": text,
    }


def plan_distribution(
    server_root: Path,
    *,
    account: str,
    character: str,
    item_code: str,
    spec_index: int = 0,
    message: str = "",
    quantity: int = 1,
    mode: str = "append",
) -> dict[str, Any]:
    account = account.strip()
    character = character.strip()
    item_code = item_code.strip()
    if not account or not character or not item_code:
        raise ValueError("ACCOUNT_CHARACTER_ITEM_REQUIRED")
    if not 0 <= int(spec_index) < len(SPEC_NAMES):
        raise ValueError("SPEC_INDEX_RANGE:0..8")
    if not 1 <= int(quantity) <= 10000:
        raise ValueError("QUANTITY_RANGE:1..10000")
    if mode not in {"append", "legacy_overwrite"}:
        raise ValueError("MODE_MUST_BE_APPEND_OR_LEGACY_OVERWRITE")
    char_path = _character_path(server_root, character)
    queue_path = _postbox_path(server_root, account)
    entry = QueueEntry(character, item_code, int(spec_index), message)
    line = entry.legacy_line()
    old = queue_path.read_text(encoding="utf-8-sig", errors="replace") if queue_path.is_file() else ""
    additions = "".join(line + "\r\n" for _ in range(int(quantity)))
    new_text = additions if mode == "legacy_overwrite" else old + additions
    return {
        "format": FORMAT,
        "status": "READY" if char_path.is_file() else "BLOCKED",
        "reason": None if char_path.is_file() else "CHARACTER_USERDATA_NOT_FOUND",
        "server_root": str(Path(server_root).resolve()),
        "account": account,
        "character": character,
        "character_path": str(char_path),
        "character_exists": char_path.is_file(),
        "item_code": item_code,
        "spec_index": int(spec_index),
        "spec_name": entry.spec_name,
        "message": message,
        "quantity": int(quantity),
        "mode": mode,
        "queue_path": str(queue_path),
        "queue_existed": queue_path.is_file(),
        "queue_sha256_before": sha256_file(queue_path) if queue_path.is_file() else None,
        "old_text": old,
        "new_text": new_text,
        "legacy_difference": (
            "The historical ItemDistributor used File.CreateText and overwrote any existing queue. "
            "PT Asset Tool defaults to append; choose legacy_overwrite only when exact legacy behavior is required."
        ),
        "write_authorized": False,
    }


def apply_distribution(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != APPLY_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{APPLY_CONFIRM}")
    if plan.get("status") != "READY":
        raise ValueError(f"PLAN_NOT_READY:{plan.get('reason')}")
    path = Path(str(plan["queue_path"]))
    expected = plan.get("queue_sha256_before")
    actual = sha256_file(path) if path.is_file() else None
    if actual != expected:
        raise ValueError("POSTBOX_DRIFTED_SINCE_PLAN")
    backup = backup_file(path, backup_root, label="item_distributor")
    atomic_write_bytes(path, str(plan["new_text"]).encode("utf-8"))
    return {
        "format": FORMAT,
        "status": "PASS",
        "path": str(path),
        "backup": str(backup) if backup else None,
        "sha256_before": actual,
        "sha256_after": sha256_file(path),
        "mode": plan.get("mode"),
        "quantity": plan.get("quantity"),
    }


def plan_queue_edit(server_root: Path, account: str, text: str) -> dict[str, Any]:
    # Parse before allowing a write; the historical editor accepted arbitrary text.
    entries = parse_queue_text(text)
    path = _postbox_path(server_root, account)
    return {
        "format": FORMAT,
        "status": "READY",
        "path": str(path),
        "sha256_before": sha256_file(path) if path.is_file() else None,
        "entries": [dataclasses.asdict(x) for x in entries],
        "new_text": "".join(x.legacy_line() + "\r\n" for x in entries),
        "write_authorized": False,
    }


def apply_queue_edit(plan: dict[str, Any], *, confirmation: str, backup_root: Path) -> dict[str, Any]:
    if confirmation != EDIT_CONFIRM:
        raise ValueError(f"CONFIRMATION_REQUIRED:{EDIT_CONFIRM}")
    path = Path(str(plan["path"]))
    actual = sha256_file(path) if path.is_file() else None
    if actual != plan.get("sha256_before"):
        raise ValueError("POSTBOX_DRIFTED_SINCE_PLAN")
    backup = backup_file(path, backup_root, label="item_distributor_edit")
    atomic_write_bytes(path, str(plan["new_text"]).encode("utf-8"))
    return {"format": FORMAT, "status": "PASS", "path": str(path), "backup": str(backup) if backup else None, "sha256_after": sha256_file(path)}
