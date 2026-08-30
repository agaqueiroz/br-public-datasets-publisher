"""Our mirrors of the library's types, so the rest of the app never sees theirs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Family:
    """One dataset family, as this tool needs it: a key, a title, nothing else."""

    key: str
    title: str


@dataclass(frozen=True, slots=True)
class SourceResource:
    """One month of one family upstream -- our mirror of the library's ResourceEntry.

    ``period`` is "YYYY-MM" text, not a ``pandas.Period``: the repo layout, the
    manifest keys and the log lines all speak text, and carrying a pandas type
    through the domain is what made the old script import pandas everywhere.

    ``native`` keeps the library's own entry as an opaque handle, so the reader
    can be handed back exactly the object the resource was built from.
    Reconstructing one in the adapter would work today and break the day
    upstream adds a field. It is excluded from equality and repr so a test can
    build a resource without one.
    """

    family_key: str
    period: str
    url: str
    resource_id: str
    resource_name: str
    format: str
    native: object | None = field(default=None, repr=False, compare=False)
