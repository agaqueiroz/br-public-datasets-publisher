"""Delete cached Parquet the Hub demonstrably already has."""

from __future__ import annotations

from dataclasses import dataclass

from br_publisher.domain.keys import split_key
from br_publisher.domain.manifest import Manifest
from br_publisher.ports import BuildStore


@dataclass(frozen=True, slots=True)
class PruneBuildCache:
    """Only files whose manifest entry matches the index go.

    Both the source hash and the conversion recipe have to agree: anything else
    is either unpublished or stale, and deleting it would throw away work the
    next run still needs.
    """

    builds: BuildStore
    manifest: Manifest
    recipe: str

    def __call__(self) -> tuple[int, int]:
        published = self.manifest.entries()
        files = freed = 0
        for key, record in list(self.builds.iter_records()):
            entry = published.get(key)
            if entry is None or entry.source_sha256 != record.source_sha256:
                continue
            if entry.conversion != self.recipe or record.conversion != self.recipe:
                continue
            family_key, period = split_key(key)
            released = self.builds.drop(family_key, period)
            if released:
                freed += released
                files += 1
        return files, freed
