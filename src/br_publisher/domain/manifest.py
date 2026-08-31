"""The Hub's record of what is published, and why a month does or does not need work."""

from __future__ import annotations

from collections.abc import Container, Mapping
from dataclasses import dataclass
from typing import Any, Final

from br_publisher.errors import ManifestError

from .keys import manifest_key, parse_repo_path, split_key
from .recipe import MANIFEST_PATH, MANIFEST_SCHEMA_VERSION

REASON_NEW: Final[str] = "novo"
REASON_SOURCE_CHANGED: Final[str] = "origem mudou"
REASON_RECIPE_CHANGED: Final[str] = "conversao mudou"
REASON_UNCHANGED: Final[str] = "inalterado"
REASON_FORCED: Final[str] = "forcado"
REASON_SAMPLE: Final[str] = "amostra"
REASON_NOT_DOWNLOADED: Final[str] = "fonte nao baixada"


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether one month has to be rebuilt, and the reason to log."""

    upload: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One published month's provenance: the SHA256 of the SOURCE it was built from.

    Hashing the Parquet output instead would be useless -- it is not
    byte-reproducible across pyarrow versions, so every run would look like a
    change.

    ``rows``/``columns`` are None on an adopted entry: recovering them means
    re-reading the source, which is the expensive half --reconciliar exists to
    skip.
    """

    source_sha256: str
    source_url: str
    resource_id: str
    rows: int | None = None
    columns: int | None = None
    parquet_bytes: int | None = None
    conversion: str = ""
    adopted: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_sha256": self.source_sha256,
            "source_url": self.source_url,
            "resource_id": self.resource_id,
            "rows": self.rows,
            "columns": self.columns,
            "parquet_bytes": self.parquet_bytes,
            "conversion": self.conversion,
        }
        if self.adopted:
            payload["adopted"] = True
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ManifestEntry:
        return cls(
            source_sha256=payload.get("source_sha256", ""),
            source_url=payload.get("source_url", ""),
            resource_id=payload.get("resource_id", ""),
            rows=payload.get("rows"),
            columns=payload.get("columns"),
            parquet_bytes=payload.get("parquet_bytes"),
            conversion=payload.get("conversion", ""),
            adopted=bool(payload.get("adopted", False)),
        )


class Manifest:
    """The Hub's record of what is published. Deliberately NOT a frozen dataclass.

    It is an entity with an ordering invariant, not a value: ``adopt`` is the
    only mutator and may only be called once the commit carrying those entries
    has landed. Making it frozen would push that invariant out to whoever
    rebinds the variable, which is exactly the mistake that once stranded 25
    months as a permanent "novo".
    """

    def __init__(self, entries: Mapping[str, ManifestEntry] | None = None) -> None:
        self._entries: dict[str, ManifestEntry] = dict(entries or {})

    @classmethod
    def empty(cls) -> Manifest:
        return cls()

    @classmethod
    def from_payload(cls, payload: object) -> Manifest:
        """Parse the manifest.json of the repo, raising rather than guessing.

        An unreadable manifest must never degrade into an empty one: that would
        reclassify every published month as "novo" and re-upload the whole
        dataset.
        """
        if not isinstance(payload, Mapping) or not isinstance(payload.get("entries"), Mapping):
            raise ManifestError(f"{MANIFEST_PATH} do repositorio nao traz um objeto 'entries'.")
        version = payload.get("schema_version")
        if version != MANIFEST_SCHEMA_VERSION:
            raise ManifestError(
                f"{MANIFEST_PATH} tem schema_version={version!r}; este aplicativo entende {MANIFEST_SCHEMA_VERSION}."
            )
        return cls({key: ManifestEntry.from_payload(value) for key, value in payload["entries"].items()})

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "entries": {key: entry.to_payload() for key, entry in self._entries.items()},
        }

    def get(self, family_key: str, period: str) -> ManifestEntry | None:
        return self._entries.get(manifest_key(family_key, period))

    def entries(self) -> Mapping[str, ManifestEntry]:
        return dict(self._entries)

    def adopt(self, entries: Mapping[str, ManifestEntry]) -> None:
        """Record entries whose commit has already landed. The only mutator."""
        self._entries.update(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries


def find_orphans(
    repo_files: Mapping[str, int], manifest: Manifest, known_families: Container[str]
) -> list[tuple[str, str, str]]:
    """Parquet the repo holds that the manifest does not record.

    With the manifest riding in the same commit as the data this should stay
    empty forever. When it does not, something published outside this tool -- or
    an older version of it -- and the run says so instead of silently
    re-uploading those months as "novo" on every pass.
    """
    entries = manifest.entries()
    orphans = []
    for path in sorted(repo_files):
        parsed = parse_repo_path(path, known_families)
        if parsed is None:
            continue
        family_key, period = parsed
        if manifest_key(family_key, period) not in entries:
            orphans.append((path, family_key, period))
    return orphans


def published_families(manifest: Manifest, known_families: Container[str]) -> list[str]:
    """The families that actually have files in the repo, for the card's configs.

    A config whose glob matches nothing is a broken entry in the viewer of the
    Hub, so a partial rollout must not advertise families it has not reached.
    """
    keys = {key.split("/", 1)[0] for key in manifest.entries()}
    return sorted(key for key in keys if key in known_families)


def previous_columns(manifest: Manifest, family_key: str, period: str) -> int | None:
    """How many columns the closest earlier month of this family was published with.

    The comparison this feeds is what turns a silent schema collapse into a line
    in the report: the mantidos months of 2026-07 went out with 2 columns where
    every earlier month had 18, and nothing in the run said so.

    Entries adopted by --reconciliar carry no counts -- recovering them means
    re-reading the source, which is the expensive half that flag exists to skip
    -- so they are passed over rather than treated as zero.
    """
    candidates = [
        (entry_period, entry.columns)
        for key, entry in manifest.entries().items()
        if (parts := split_key(key))[0] == family_key
        and (entry_period := parts[1]) < period
        and entry.columns is not None
    ]
    return max(candidates)[1] if candidates else None
