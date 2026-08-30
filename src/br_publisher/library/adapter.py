"""The only module in this application allowed to import brinss's private API.

The publisher needs things ``brinss``'s public surface does not offer:
per-resource catalogue entries, the on-disk name a cached source has, the SHA
registry that outlives the file itself, and a chunked reader. Until those are
published (see ``docs/upstream-api.md``) they are reached through the private
modules -- here, and only here. A rename upstream breaks this file and the two
tests that pin it, which is the whole point.

Verified against brinss-public-datasets 0.1.x; see ``compat.check_library``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Final

import pandas as pd
from brinss.datasets import _cache, _catalog, _log, _reading
from brinss.datasets._families import FAMILIES
from brinss.datasets.enums import ColumnDtype, DataSource, XlsxEngine

from .models import Family, SourceResource

LIBRARY_LOGGER_NAME: Final[str] = _log.LOGGER_NAME

# The portal, never the mirror. The library defaults to DataSource.HF, which is
# the right default for a reader and exactly wrong here: this tool *builds* that
# mirror. Reading it to publish it would be circular, and the manifest records
# the SHA256 of the file on dadosabertos.inss.gov.br -- the source of record.
CATALOG_SOURCE: Final[DataSource] = DataSource.INSS

# The library's own formatters, reached through one alias each. The script used
# to carry near-identical copies; a divergence there would make two log lines
# about the same number disagree.
format_bytes = _log.format_bytes
format_seconds = _log.format_seconds
get_library_logger = _log.get_logger


class BrinssLibrary:
    """Implements SourceCatalog, SourceStore and SourceReader over brinss.

    One class for all three ports because they share one cache root and one set
    of catalogues; splitting them would mean threading that state through three
    constructors for no gain.
    """

    def __init__(self, *, cache_dir: str | os.PathLike | None = None, force_refresh: bool = False) -> None:
        self._cache_root = _cache.get_cache_root(cache_dir)
        self._force_refresh = force_refresh
        self._catalogs: dict[str, _catalog.DatasetCatalog] = {}

    # -- SourceCatalog ----------------------------------------------------

    @property
    def root(self) -> Path:
        """The resolved download cache -- explicit dir > BRINSS_DATA_HOME > platformdirs."""
        return self._cache_root

    def families(self) -> Mapping[str, Family]:
        """Every family the library knows, keyed the way --familia expects."""
        return {key: Family(key=key, title=family.title) for key, family in FAMILIES.items()}

    def resources(self, family_key: str) -> tuple[SourceResource, ...]:
        """Every published month of one family, oldest first; hits CKAN or its cache."""
        catalog = self._catalog(family_key)
        return tuple(self._wrap(family_key, entry) for entry in catalog.entries)

    def resource_for(self, family_key: str, period: str) -> SourceResource | None:
        """One month, or None -- used by --reconciliar to name an orphan's origin."""
        try:
            catalog = self._catalog(family_key)
        except KeyError:
            return None
        entry = catalog.entries_by_period.get(pd.Period(period, freq="M"))
        return None if entry is None else self._wrap(family_key, entry)

    # -- SourceStore ------------------------------------------------------

    def cached_path(self, resource: SourceResource) -> Path | None:
        """Where the downloaded source sits, or None if it was never fetched.

        This borrows the library's naming rule instead of downloading, so a dry
        run stays cheap. Without it, previewing the plan would have to pull tens
        of GB purely to hash bytes it then throws away.
        """
        path = self._cache_root / "files" / resource.family_key / _cache._resource_filename(self._native(resource))
        return path if path.exists() else None

    def known_digest(self, resource: SourceResource) -> str | None:
        """The source SHA256 from registry.json, which outlives the file itself.

        The library records a resource's hash on first download and keeps it
        even after the file is deleted, so a month whose source is long gone can
        still be identified for free.
        """
        registry = _cache._load_registry(self._cache_root)
        return registry.get(f"{resource.family_key}/{_cache._resource_filename(self._native(resource))}")

    def fetch(self, resource: SourceResource) -> Path:
        """Download the source (or reuse the cached copy), returning its path."""
        return _cache.fetch_resource(
            self._native(resource), family_key=resource.family_key, cache_dir=self._cache_root
        )

    # -- SourceReader -----------------------------------------------------

    def encodings(self, path: Path) -> list[str]:
        """The encodings worth trying for a source, best first; empty for a spreadsheet."""
        return _reading.resource_encodings(path)

    def open_chunks(
        self, path: Path, resource: SourceResource, *, encoding: str | None = None
    ) -> AbstractContextManager[Iterator[pd.DataFrame]]:
        """Stream a source as DataFrame chunks; the archive stays open for the block."""
        return _reading.open_resource_chunks(
            path,
            self._native(resource),
            columns=None,
            engine=XlsxEngine.OPENPYXL,
            dtype=ColumnDtype.STRING,
            encoding=encoding,
        )

    # -- internals --------------------------------------------------------

    def _catalog(self, family_key: str) -> _catalog.DatasetCatalog:
        if family_key not in self._catalogs:
            self._catalogs[family_key] = _catalog.build_catalog(
                FAMILIES[family_key],
                cache_dir=self._cache_root,
                source=CATALOG_SOURCE,
                force_refresh=self._force_refresh,
            )
        return self._catalogs[family_key]

    def _wrap(self, family_key: str, entry: _catalog.ResourceEntry) -> SourceResource:
        return SourceResource(
            family_key=family_key,
            period=str(entry.period),
            url=entry.url,
            resource_id=entry.resource_id,
            resource_name=entry.resource_name,
            format=entry.format,
            native=entry,
        )

    def _native(self, resource: SourceResource) -> _catalog.ResourceEntry:
        """The library entry a resource came from, rebuilt only if it has none.

        A resource built by a test has no handle; one that came out of ``_wrap``
        always does, and handing back the original is what keeps this adapter
        correct on the day upstream adds a field to ResourceEntry.
        """
        if isinstance(resource.native, _catalog.ResourceEntry):
            return resource.native
        return _catalog.ResourceEntry(
            period=pd.Period(resource.period, freq="M"),
            url=resource.url,
            resource_id=resource.resource_id,
            resource_name=resource.resource_name,
            package_slug="",
            format=resource.format,
        )
