from __future__ import annotations
import json, pathlib, uuid
from .utils import append_jsonl, utc_now


VALID_RESULTS = {"PASS", "FAIL", "SKIP"}


class CertificationRegistry:
    def __init__(self, directory: pathlib.Path):
        self.directory = pathlib.Path(directory)
        self.path = self.directory / "assets.jsonl"

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid certification JSONL: {self.path}: {exc}") from exc
        return out

    def add(self, *, asset_id: str, asset_path: str, family: str, test: str, layer: str, result: str, source_sha256: str | None = None, artifact_sha256: str | None = None, notes: str = "", metadata: dict | None = None) -> dict:
        result = result.upper()
        if result not in VALID_RESULTS:
            raise ValueError(f"invalid certification result: {result}")
        row = {
            "certification_id": "CERT-" + uuid.uuid4().hex[:12].upper(),
            "timestamp": utc_now(),
            "asset_id": asset_id,
            "asset_path": asset_path,
            "family": family,
            "test": test,
            "layer": layer,
            "result": result,
            "source_sha256": source_sha256,
            "artifact_sha256": artifact_sha256,
            "notes": notes,
            "metadata": metadata or {},
        }
        append_jsonl(self.path, row)
        return row

    def latest(self, asset_id: str | None = None) -> dict[tuple[str, str, str], dict]:
        latest = {}
        for r in self.records():
            if asset_id and r.get("asset_id") != asset_id:
                continue
            key = (r.get("asset_id", ""), r.get("test", ""), r.get("layer", ""))
            latest[key] = r
        return latest

    def latest_result(self, asset_id: str, test: str, layer: str, *, source_sha256: str | None = None) -> str | None:
        row = self.latest(asset_id).get((asset_id, test, layer))
        if not row:
            return None
        if source_sha256 is not None and str(row.get("source_sha256") or "").casefold() != str(source_sha256).casefold():
            return None
        return row.get("result")
