"""Test doubles for every port.

They inherit nothing: the ports are Protocols, so a fake only has to have the
right shape. That is the point of choosing Protocols over ABCs.
"""

from __future__ import annotations

import contextlib
import io
import logging
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pandas as pd

from br_publisher.domain.manifest import Manifest, ManifestEntry
from br_publisher.infra.parquet import ConversionResult
from br_publisher.library.models import Family, SourceResource
from br_publisher.report import Reporter


def quiet_reporter() -> Reporter:
    logger = logging.getLogger("brinss.publish.test")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return Reporter(logger)


class FakeCatalog:
    def __init__(
        self, families: Mapping[str, Family], resources: Mapping[str, Sequence[SourceResource]]
    ) -> None:
        self._families = dict(families)
        self._resources = {key: tuple(value) for key, value in resources.items()}

    def families(self) -> Mapping[str, Family]:
        return self._families

    def resources(self, family_key: str) -> tuple[SourceResource, ...]:
        return self._resources.get(family_key, ())

    def resource_for(self, family_key: str, period: str) -> SourceResource | None:
        for resource in self._resources.get(family_key, ()):
            if resource.period == period:
                return resource
        return None


class FakeSourceStore:
    """A source store backed by a plain dict of resource key -> path."""

    def __init__(
        self,
        root: Path,
        *,
        cached: Mapping[str, Path] | None = None,
        digests: Mapping[str, str] | None = None,
        on_fetch: object | None = None,
    ) -> None:
        self._root = root
        self._cached = dict(cached or {})
        self._digests = dict(digests or {})
        self._on_fetch = on_fetch
        self.fetches: list[str] = []

    @property
    def root(self) -> Path:
        return self._root

    def _key(self, resource: SourceResource) -> str:
        return f"{resource.family_key}/{resource.period}"

    def seed(self, resource: SourceResource, path: Path) -> None:
        self._cached[self._key(resource)] = path

    def cached_path(self, resource: SourceResource) -> Path | None:
        path = self._cached.get(self._key(resource))
        return path if path is not None and path.exists() else None

    def known_digest(self, resource: SourceResource) -> str | None:
        return self._digests.get(self._key(resource))

    def fetch(self, resource: SourceResource) -> Path:
        self.fetches.append(self._key(resource))
        if self._on_fetch is None:
            raise AssertionError("fetch nao deveria ter sido chamado")
        return self._on_fetch(resource)


class FakeReader:
    """Reads a seeded CSV the way the library would, minus the portal quirks."""

    def __init__(self, chunks: Sequence[pd.DataFrame] | None = None, encodings: list[str] | None = None) -> None:
        self._chunks = chunks
        self._encodings = encodings if encodings is not None else ["utf-8-sig", "cp1252", "latin-1"]
        self.opened: list[tuple[Path, str | None]] = []

    def encodings(self, path: Path) -> list[str]:
        return list(self._encodings)

    @contextlib.contextmanager
    def open_chunks(
        self, path: Path, resource: SourceResource, *, encoding: str | None = None
    ) -> Iterator[Iterator[pd.DataFrame]]:
        self.opened.append((path, encoding))
        if self._chunks is not None:
            yield iter(self._chunks)
            return
        raw = path.read_bytes().decode(encoding or "latin-1")
        frame = pd.read_csv(io.StringIO(raw), sep=";", dtype=str)
        frame.insert(0, "periodo_referencia", pd.Period(resource.period, freq="M"))
        yield iter([frame])


class ExplodingReader:
    """A reader that fails if anyone opens the source. Pins the cache-hit path."""

    def encodings(self, path: Path) -> list[str]:
        raise AssertionError("a origem nao deveria ter sido reaberta")

    def open_chunks(self, path, resource, *, encoding=None):
        raise AssertionError("a origem nao deveria ter sido reaberta")


class RaisingConverter:
    """Blows up for one period, so the run loop's isolation can be observed."""

    def __init__(self, period: str, inner: object | None = None) -> None:
        self._period = period
        self._inner = inner

    def convert(self, resource: SourceResource, source: Path, destination: Path) -> ConversionResult:
        if resource.period == self._period:
            raise ValueError("xlsx corrompido")
        if self._inner is None:
            raise AssertionError("sem conversor interno")
        return self._inner.convert(resource, source, destination)


class InMemoryRepository:
    """A DatasetRepository that records instead of committing."""

    def __init__(
        self,
        manifest: Manifest | None = None,
        repo_files: Mapping[str, int] | None = None,
        *,
        commit_size: int = 25,
    ) -> None:
        self._manifest = manifest if manifest is not None else Manifest.empty()
        self._repo_files = dict(repo_files or {})
        self._commit_size = commit_size
        self._pending: list[tuple[str, ManifestEntry]] = []
        self.staged: list[tuple[Path, str]] = []
        self.commits = 0
        self.cards: list[tuple[str, bool]] = []
        self.manifest_replacements: list[tuple[dict, str]] = []
        self.created = False

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def ensure_exists(self) -> None:
        self.created = True

    def load_manifest(self) -> Manifest:
        return self._manifest

    def list_parquet(self) -> dict[str, int]:
        return dict(self._repo_files)

    def stage(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None:
        self.staged.append((local, target))
        self._pending.append((key, entry))
        if len(self._pending) >= self._commit_size:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        self._manifest.adopt(dict(self._pending))
        self._pending.clear()
        self.commits += 1

    def replace_manifest(self, entries: Mapping[str, ManifestEntry], message: str) -> None:
        self.manifest_replacements.append((dict(entries), message))
        self._manifest.adopt(dict(entries))

    def write_card(self, markdown: str, *, overwrite: bool) -> None:
        self.cards.append((markdown, overwrite))


class RecordingHubClient:
    """Satisfies the HubClient Protocol, so drift in HfApi shows up as a mismatch."""

    def __init__(self, *, existing: set[str] | None = None, fail_on_commit: bool = False) -> None:
        self.commits: list[dict] = []
        self.uploads: list[dict] = []
        self.existing = set(existing or ())
        self.fail_on_commit = fail_on_commit
        self.created: list[str] = []
        self.downloads: list[str] = []
        self.tree: list[object] = []

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object:
        self.created.append(repo_id)
        return object()

    def create_commit(self, *, repo_id, repo_type, operations, commit_message) -> object:
        if self.fail_on_commit:
            raise RuntimeError("hub fora do ar")
        self.commits.append(
            {"repo_id": repo_id, "operations": list(operations), "commit_message": commit_message}
        )

        class _Info:
            oid = "abcdef1234567890"

        return _Info()

    def file_exists(self, repo_id: str, filename: str, **kwargs: object) -> bool:
        return filename in self.existing

    def hf_hub_download(self, **kwargs: object) -> str:
        self.downloads.append(str(kwargs.get("filename")))
        return str(self._download_path)

    def list_repo_tree(self, repo_id, *, path_in_repo, repo_type, recursive):
        return list(self.tree)

    def upload_file(self, **kwargs: object) -> None:
        self.uploads.append(dict(kwargs))

    def seed_manifest_download(self, path: Path) -> None:
        self._download_path = path
        self.existing.add("manifest.json")
