"""Durable writes -- an abrupt shutdown is the failure model here, not an exception."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Hash a file in chunks -- the heavier resources run to several GB."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON so an interrupted run never leaves a half-file behind.

    ``os.replace`` alone is not enough. It makes the *rename* atomic, but the
    bytes can still be sitting in the page cache when the machine loses power,
    and what survives is a truncated file under the final name. The fsync is
    what turns "renamed" into "durable".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    with partial.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(path)


def json_bytes(payload: dict[str, Any]) -> bytes:
    """The exact byte form this tool commits JSON in, so every writer agrees."""
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
