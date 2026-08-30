"""What the conversion produces, and the version stamp that describes it."""

from __future__ import annotations

from typing import Final

COMPRESSION: Final[str] = "zstd"
PERIOD_COLUMN: Final[str] = "periodo_referencia"

MANIFEST_SCHEMA_VERSION: Final[int] = 1
BUILD_INDEX_SCHEMA_VERSION: Final[int] = 1

MANIFEST_PATH: Final[str] = "manifest.json"
CARD_PATH: Final[str] = "README.md"
BUILD_INDEX_NAME: Final[str] = "build-index.json"

DEFAULT_REPO_ID: Final[str] = "agaqueiroz/brinss-public-datasets"

# Bumped whenever the conversion itself changes in a way that makes already
# published files stale (column typing, compression, the period column's
# representation). A mismatch forces a rewrite even when the source is
# untouched, which is the only way a recipe change ever reaches the Hub.
CONVERSION_RECIPE: Final[str] = f"v1|dtype=str|compression={COMPRESSION}|period=str"

# A batch is flushed once it reaches either bound. The file count keeps the
# commit log readable; the byte cap keeps any single commit from carrying an
# unreasonable payload, which matters on the families whose months run to
# gigabytes.
DEFAULT_COMMIT_SIZE: Final[int] = 25
COMMIT_BYTE_CAP: Final[int] = 2 * 1024**3

# Past this, the cache under tmp/ is worth mentioning out loud.
PARQUET_CACHE_WARN_BYTES: Final[int] = 5 * 1024**3
