"""Wire this application into the logger of the library, and open the run's log file."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from .library import LIBRARY_LOGGER_NAME, get_library_logger
from .settings import LogSettings

LOGGER_NAME = f"{LIBRARY_LOGGER_NAME}.publish"


class DurableFileHandler(logging.FileHandler):
    """A file handler whose checkpoint lines survive the crash that caused them.

    ``StreamHandler.emit`` already flushes every record, which is enough when
    the process is killed. It is not enough when the machine loses power: the
    bytes are in the page cache, not on the disk. The lines that answer "where
    did it stop" ask for an fsync explicitly -- doing it for every record would
    make the log cost more than the work it describes.
    """

    def sync(self) -> None:
        if self.stream is None:
            return
        self.flush()
        with contextlib.suppress(OSError, ValueError):  # pragma: no cover - platform dependent
            os.fsync(self.stream.fileno())


def configure_logging(settings: LogSettings) -> tuple[logging.Logger, DurableFileHandler | None, Path | None]:
    """Attach handlers and return the logger, the durable handler and the log path.

    ``brinss.publish`` propagates to ``brinss``, which the library has already
    given a stderr handler -- so this application's messages and the library's
    ("Downloading...", "Using cached file...") share one stream in one format.
    The file handler is attached to ``brinss`` and ``pooch`` for the same
    reason: what went wrong is usually a download or a read, not this tool.
    """
    get_library_logger()  # installs the stderr handler once
    console_level = logging.DEBUG if settings.verbose else logging.INFO
    handler: DurableFileHandler | None = None
    path = settings.resolve_path()

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = DurableFileHandler(path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s"))

    for name in (LIBRARY_LOGGER_NAME, "pooch"):
        logger = logging.getLogger(name)
        for existing in logger.handlers:
            existing.setLevel(console_level)
        if handler is not None:
            logger.addHandler(handler)
        # DEBUG on the logger, INFO on the console handler: the file gets the
        # detail without the terminal being buried in it.
        logger.setLevel(logging.DEBUG if handler is not None else console_level)

    return logging.getLogger(LOGGER_NAME), handler, path
