"""Whether a month needs work -- the one thing the three modes genuinely disagree on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .manifest import (
    REASON_FORCED,
    REASON_NEW,
    REASON_RECIPE_CHANGED,
    REASON_SAMPLE,
    REASON_SOURCE_CHANGED,
    REASON_UNCHANGED,
    Decision,
    Manifest,
)


class UploadDecider(Protocol):
    def decide(self, family_key: str, period: str, digest: str, *, reusable: bool) -> Decision: ...


@dataclass(frozen=True, slots=True)
class ManifestDecider:
    """Dry-run and --push: the manifest and the conversion recipe decide.

    The reason is returned rather than logged here so the dry run and the real
    run present exactly the same decisions.
    """

    manifest: Manifest
    recipe: str
    force: bool = False

    def decide(self, family_key: str, period: str, digest: str, *, reusable: bool) -> Decision:
        entry = self.manifest.get(family_key, period)
        if entry is None:
            return Decision(True, REASON_NEW)
        if entry.source_sha256 != digest:
            return Decision(True, REASON_SOURCE_CHANGED)
        if entry.conversion != self.recipe:
            return Decision(True, REASON_RECIPE_CHANGED)
        if self.force:
            return Decision(True, REASON_FORCED)
        return Decision(False, REASON_UNCHANGED)


@dataclass(frozen=True, slots=True)
class SampleDecider:
    """--sample: there is no manifest, so the build cache alone decides.

    A month already converted is skipped; anything else is "amostra". This is
    the whole reason --sample used to need its own branch in _process_one.
    """

    force: bool = False

    def decide(self, family_key: str, period: str, digest: str, *, reusable: bool) -> Decision:
        if reusable and not self.force:
            return Decision(False, REASON_UNCHANGED)
        return Decision(True, REASON_SAMPLE)
