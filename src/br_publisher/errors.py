"""The failures this application knows how to explain.

Every one of these carries a message the user reads on stderr, so they are all
written in the same unaccented Portuguese as the CLI's help and log lines.
"""

from __future__ import annotations


class PublisherError(Exception):
    """Base for everything this application raises on purpose."""


class UsageError(PublisherError):
    """The flags cannot produce a run. Reported before anything is set up.

    This is raised while settings are built, ahead of the logging setup, so a
    run that cannot start never leaves a log file behind claiming it did.
    """


class ManifestError(PublisherError):
    """The Hub's manifest could not be read as a trustworthy record.

    Never degrade this into an empty manifest: that would reclassify every
    published month as "novo" and re-upload the whole dataset.
    """


class LibraryIncompatibleError(PublisherError):
    """The installed brinss no longer matches what the adapter reaches for.

    Raised by ``library.compat.check_library`` at startup rather than as an
    AttributeError at month 40 of a --push.
    """
