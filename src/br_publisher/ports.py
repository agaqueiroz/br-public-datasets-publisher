"""Every seam in one file, so the catalogue of them fits on one screen.

These are Protocols rather than ABCs on purpose: there is no runtime registry
and no shared implementation to inherit, and an ABC would force every test fake
to import the base class.

The rule that decided which of these exist: a port earns its place only when it
has two implementations that actually exist -- a real one, and either a test
fake or a null object used by a real mode.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pandas as pd

if TYPE_CHECKING:
    from br_publisher.domain.manifest import Manifest, ManifestEntry
    from br_publisher.infra.build_cache import BuildRecord
    from br_publisher.infra.parquet import ConversionResult
    from br_publisher.library.models import Family, SourceResource


class SourceCatalog(Protocol):
    """Which months exist upstream."""

    def families(self) -> Mapping[str, Family]: ...

    def resources(self, family_key: str) -> tuple[SourceResource, ...]: ...

    def resource_for(self, family_key: str, period: str) -> SourceResource | None: ...


class SourceStore(Protocol):
    """Where a month's source file lives locally, and what it hashes to."""

    @property
    def root(self) -> Path: ...

    def cached_path(self, resource: SourceResource) -> Path | None: ...

    def known_digest(self, resource: SourceResource) -> str | None: ...

    def fetch(self, resource: SourceResource) -> Path: ...


class SourceReader(Protocol):
    """Streaming access to a source file, so a 25 GiB month never lands in memory."""

    def encodings(self, path: Path) -> list[str]: ...

    def open_chunks(
        self, path: Path, resource: SourceResource, *, encoding: str | None = None
    ) -> AbstractContextManager[Iterator[pd.DataFrame]]: ...


class ParquetConverter(Protocol):
    def convert(self, resource: SourceResource, source: Path, destination: Path) -> ConversionResult:
        """Turn one source file into one Parquet, returning its row and column counts."""
        ...


class BuildStore(Protocol):
    """The local Parquet cache: answers "was this converted here", never "was this published"."""

    @property
    def root(self) -> Path: ...

    @property
    def data_root(self) -> Path: ...

    def path_for(self, family_key: str, period: str) -> Path: ...

    def record_for(self, family_key: str, period: str) -> BuildRecord | None: ...

    def is_reusable(self, family_key: str, period: str, source_sha256: str) -> bool: ...

    def put(self, family_key: str, period: str, record: BuildRecord) -> None: ...

    def iter_records(self) -> Iterator[tuple[str, BuildRecord]]: ...

    def drop(self, family_key: str, period: str) -> int: ...

    def total_bytes(self) -> int: ...


class DatasetRepository(Protocol):
    """The published side. Hugging Face today; a null object offline.

    It owns the manifest, because the invariant "the manifest may only claim a
    month once its commit landed" is only enforceable where the commit happens.
    """

    @property
    def manifest(self) -> Manifest: ...

    @property
    def commits(self) -> int: ...

    def ensure_exists(self) -> None: ...

    def load_manifest(self) -> Manifest: ...

    def list_parquet(self) -> dict[str, int]: ...

    def stage(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None: ...

    def flush(self) -> None: ...

    def replace_manifest(self, entries: Mapping[str, ManifestEntry], message: str) -> None: ...

    def write_card(self, markdown: str, *, overwrite: bool) -> None: ...


class CardRenderer(Protocol):
    def render(self, family_keys: Sequence[str]) -> str: ...


class HubClient(Protocol):
    """The slice of HfApi this tool uses.

    Naming it is what lets the commit tests hand in a recording double without
    importing huggingface_hub at all.
    """

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object: ...

    def create_commit(self, *, repo_id: str, repo_type: str, operations: list, commit_message: str) -> object: ...

    def file_exists(self, repo_id: str, filename: str, **kwargs: object) -> bool: ...

    def hf_hub_download(self, **kwargs: object) -> str: ...

    def list_repo_tree(
        self, repo_id: str, *, path_in_repo: str, repo_type: str, recursive: bool
    ) -> Iterable[object]: ...

    def upload_file(self, **kwargs: object) -> None: ...
