"""What a run did, accumulated as it goes so an interrupt keeps the partial result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

STATUS_OK: Final[str] = "CONCLUIDO COM SUCESSO"
STATUS_FAILED: Final[str] = "CONCLUIDO COM FALHAS"
STATUS_INTERRUPTED: Final[str] = "INTERROMPIDO"


@dataclass
class Plan:
    """A collecting parameter: partial results survive a KeyboardInterrupt."""

    uploads: list[tuple[str, str, str]] = field(default_factory=list)  # family, period, reason
    skipped: list[tuple[str, str]] = field(default_factory=list)  # family, period
    failures: list[tuple[str, str, str]] = field(default_factory=list)  # family, period, error
    reconciled: list[tuple[str, str]] = field(default_factory=list)  # family, period
    written_bytes: int = 0
    reused_bytes: int = 0
    last_item: str | None = None
    status: str = STATUS_OK
