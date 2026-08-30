"""The null object behind --sample and --no-hub.

Every ``if not args.no_hub and not args.sample`` the old script carried existed
because there was no repository object to talk to offline. There is one now, so
the use cases stopped asking.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from br_publisher.domain.manifest import Manifest, ManifestEntry


class OfflineRepository:
    """A DatasetRepository that knows nothing and publishes nothing."""

    def __init__(self) -> None:
        self._manifest = Manifest.empty()

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    @property
    def commits(self) -> int:
        return 0

    def ensure_exists(self) -> None:
        return None

    def load_manifest(self) -> Manifest:
        return self._manifest

    def list_parquet(self) -> dict[str, int]:
        return {}

    def stage(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None:
        return None

    def flush(self) -> None:
        return None

    def replace_manifest(self, entries: Mapping[str, ManifestEntry], message: str) -> None:
        return None

    def write_card(self, markdown: str, *, overwrite: bool) -> None:
        return None
