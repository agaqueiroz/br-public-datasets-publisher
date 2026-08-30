"""The repository's naming law: one Parquet per period per family."""

from __future__ import annotations

from collections.abc import Container


def path_in_repo(family_key: str, period: str) -> str:
    return f"data/{family_key}/{period}.parquet"


def parse_repo_path(path: str, known_families: Container[str]) -> tuple[str, str] | None:
    """The inverse of ``path_in_repo``, or None for anything else in the repo."""
    parts = path.split("/")
    if len(parts) != 3 or parts[0] != "data" or not parts[2].endswith(".parquet"):
        return None
    family_key, period = parts[1], parts[2].removesuffix(".parquet")
    return (family_key, period) if family_key in known_families else None


def manifest_key(family_key: str, period: str) -> str:
    return f"{family_key}/{period}"


def split_key(key: str) -> tuple[str, str]:
    family_key, _, period = key.partition("/")
    return family_key, period
