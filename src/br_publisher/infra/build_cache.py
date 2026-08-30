"""The converted Parquet kept under tmp/, plus the index that describes it.

Conversion is the expensive half of a run -- reading a multi-hundred-MB XLSX
with openpyxl takes minutes -- and it used to be thrown away twice over: deleted
right after each commit, and again with the staging directory. Keeping it means
an interrupted run resumes instead of restarts.

The index is what makes the files on disk trustworthy. A Parquet whose name
merely exists proves nothing after a crash; one whose recorded source hash,
conversion recipe *and byte count* still match is the same file this tool would
produce right now.

The index is emphatically *not* the manifest: it answers "was this converted
here", never "was this published".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from br_publisher.domain.keys import manifest_key, path_in_repo, split_key
from br_publisher.domain.manifest import ManifestEntry
from br_publisher.domain.recipe import BUILD_INDEX_NAME, BUILD_INDEX_SCHEMA_VERSION, CONVERSION_RECIPE

from .fsio import write_json_atomic

LOGGER = logging.getLogger("brinss.publish")


@dataclass(frozen=True, slots=True)
class BuildRecord:
    source_sha256: str
    source_url: str
    resource_id: str
    rows: int
    columns: int
    parquet_bytes: int
    conversion: str
    built_at: str

    def to_manifest_entry(self) -> ManifestEntry:
        """The manifest's view of a build record: everything but the local detail."""
        return ManifestEntry(
            source_sha256=self.source_sha256,
            source_url=self.source_url,
            resource_id=self.resource_id,
            rows=self.rows,
            columns=self.columns,
            parquet_bytes=self.parquet_bytes,
            conversion=self.conversion,
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> BuildRecord | None:
        try:
            return cls(
                source_sha256=payload["source_sha256"],
                source_url=payload.get("source_url", ""),
                resource_id=payload.get("resource_id", ""),
                rows=payload.get("rows", 0),
                columns=payload.get("columns", 0),
                parquet_bytes=payload.get("parquet_bytes", 0),
                conversion=payload.get("conversion", ""),
                built_at=payload.get("built_at", ""),
            )
        except (KeyError, TypeError):
            return None


def empty_index() -> dict[str, Any]:
    return {"schema_version": BUILD_INDEX_SCHEMA_VERSION, "entries": {}}


class BuildCache:
    """The local Parquet cache and its index."""

    def __init__(self, root: Path, index: dict[str, Any], *, recipe: str = CONVERSION_RECIPE) -> None:
        self._root = root
        self._index = index
        self._recipe = recipe

    @classmethod
    def load(cls, root: Path | str, *, recipe: str = CONVERSION_RECIPE) -> BuildCache:
        root = Path(root)
        return cls(root, _load_build_index(root / BUILD_INDEX_NAME), recipe=recipe)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def index_path(self) -> Path:
        return self._root / BUILD_INDEX_NAME

    @property
    def data_root(self) -> Path:
        return self._root / "data"

    def path_for(self, family_key: str, period: str) -> Path:
        return self._root / path_in_repo(family_key, period)

    def record_for(self, family_key: str, period: str) -> BuildRecord | None:
        payload = self._index.get("entries", {}).get(manifest_key(family_key, period))
        return None if payload is None else BuildRecord.from_payload(payload)

    def is_reusable(self, family_key: str, period: str, source_sha256: str) -> bool:
        """Whether the cached Parquet can stand in for a fresh conversion."""
        record = self.record_for(family_key, period)
        if record is None:
            return False
        if record.source_sha256 != source_sha256 or record.conversion != self._recipe:
            return False
        local = self.path_for(family_key, period)
        if not local.exists():
            return False
        # The size check is what catches a file truncated by a power cut: the
        # index entry is intact, the bytes are not.
        return local.stat().st_size == record.parquet_bytes

    def put(self, family_key: str, period: str, record: BuildRecord) -> None:
        self._index.setdefault("entries", {})[manifest_key(family_key, period)] = record.to_payload()
        write_json_atomic(self.index_path, self._index)

    def iter_records(self) -> Iterator[tuple[str, BuildRecord]]:
        for key, payload in list(self._index.get("entries", {}).items()):
            record = BuildRecord.from_payload(payload)
            if record is not None:
                yield key, record

    def drop(self, family_key: str, period: str) -> int:
        """Delete one cached Parquet, returning the bytes freed (0 if it was gone)."""
        local = self.path_for(family_key, period)
        if not local.exists():
            return 0
        freed = local.stat().st_size
        local.unlink()
        return freed

    def total_bytes(self) -> int:
        if not self.data_root.exists():
            return 0
        return sum(path.stat().st_size for path in self.data_root.rglob("*.parquet"))

    def split_key(self, key: str) -> tuple[str, str]:
        return split_key(key)


def _load_build_index(path: Path) -> dict[str, Any]:
    """Read the build index, falling back to an empty one when it is unusable.

    Tolerating corruption is right *here* and wrong for the manifest: losing the
    index costs a reconversion, while misreading the manifest as empty would
    re-upload all 291 months.
    """
    if not path.exists():
        return empty_index()
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        LOGGER.warning("indice de build ilegivel (%s); recomecando vazio: %s", path, exc)
        return empty_index()
    if not isinstance(index, dict) or not isinstance(index.get("entries"), dict):
        LOGGER.warning("indice de build sem 'entries' (%s); recomecando vazio.", path)
        return empty_index()
    return index
