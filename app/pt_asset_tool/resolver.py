from __future__ import annotations
import pathlib
from .utils import low_path, norm_path


class ClientResolver:
    def __init__(self, client_root: pathlib.Path):
        self.client_root = pathlib.Path(client_root).expanduser().resolve()
        self._index: dict[str, pathlib.Path] | None = None
        self.collisions: dict[str, list[pathlib.Path]] = {}

    def build_index(self):
        if not self.client_root.is_dir():
            raise FileNotFoundError(self.client_root)
        idx: dict[str, pathlib.Path] = {}
        collisions: dict[str, list[pathlib.Path]] = {}
        for p in self.client_root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(self.client_root).as_posix()
            key = low_path(rel)
            if key in idx and idx[key] != p:
                collisions.setdefault(key, [idx[key]]).append(p)
            else:
                idx[key] = p
        self._index = idx
        self.collisions = collisions
        return idx

    @property
    def index(self):
        return self._index if self._index is not None else self.build_index()

    def resolve(self, logical_path: str, required: bool = True) -> pathlib.Path | None:
        logical = norm_path(logical_path)
        # Prefer an exact-case physical path. The real client intentionally
        # contains a few files that differ only by case (mostly StartImage/sky).
        exact = self.client_root / pathlib.PurePosixPath(logical)
        if exact.is_file():
            return exact
        key = low_path(logical)
        # Build the index before checking collisions.
        _ = self.index
        if key in self.collisions:
            raise RuntimeError(f"case-insensitive client path collision without exact-case match: {logical_path}: {self.collisions[key]}")
        p = self.index.get(key)
        if p is None and required:
            raise FileNotFoundError(f"client asset not found: {logical}")
        return p
