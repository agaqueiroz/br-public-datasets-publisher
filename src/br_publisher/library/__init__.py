"""The anti-corruption layer around brinss.

Everything outside this package speaks ``Family``/``SourceResource`` and the
ports in ``br_publisher.ports``; only ``adapter`` knows brinss internals.
"""

from __future__ import annotations

from .adapter import LIBRARY_LOGGER_NAME, BrinssLibrary, format_bytes, format_seconds, get_library_logger
from .compat import check_library, installed_version
from .models import Family, SourceResource

__all__ = [
    "LIBRARY_LOGGER_NAME",
    "BrinssLibrary",
    "Family",
    "SourceResource",
    "check_library",
    "format_bytes",
    "format_seconds",
    "get_library_logger",
    "installed_version",
]
