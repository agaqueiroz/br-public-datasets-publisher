"""Every flag, resolved once into a frozen object.

Replaces the ``argparse.Namespace`` that used to be threaded through ten
function signatures -- which is how ``args.sample`` ended up being read in six
places that each had to remember what it implied.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

from .domain.recipe import DEFAULT_COMMIT_SIZE
from .errors import UsageError


class Mode(StrEnum):
    DRY_RUN = "dry-run"
    SAMPLE = "sample"
    PUSH = "push"


@dataclass(frozen=True, slots=True)
class ModeProfile:
    """What a mode is allowed to do, resolved once from the flags.

    Replaces every ``if args.sample`` / ``if not args.push`` scattered through
    the old script with one table you can read -- and, in tests, parametrize
    over.
    """

    mode: Mode
    may_download: bool
    may_convert: bool
    may_publish: bool
    uses_hub: bool
    summary_verb: str

    @classmethod
    def of(cls, mode: Mode, *, no_hub: bool = False) -> ModeProfile:
        if mode is Mode.SAMPLE:
            # --sample never downloads: that is the whole reason it exists,
            # since a full run pulls tens of GB from the portal.
            return cls(mode, False, True, False, False, "gerados")
        if mode is Mode.PUSH:
            return cls(mode, True, True, True, True, "enviados")
        return cls(mode, False, False, False, not no_hub, "a enviar")

    def header_label(self, *, reconcile: bool) -> str:
        return f"{self.mode.value}+reconciliar" if reconcile else self.mode.value


@dataclass(frozen=True, slots=True)
class LogSettings:
    directory: Path
    file: Path | None
    enabled: bool
    verbose: bool

    def resolve_path(self) -> Path | None:
        """The log file for this run: --log-file wins, else --log-dir/publish-<stamp>.log."""
        if not self.enabled:
            return None
        if self.file is not None:
            return self.file
        return self.directory / f"publish-{time.strftime('%Y%m%d-%H%M%S')}.log"


@dataclass(frozen=True, slots=True)
class Settings:
    repo_id: str
    mode: Mode
    no_hub: bool
    families: tuple[str, ...]
    periods: tuple[str, ...] | None
    parquet_dir: Path
    cache_dir: Path | None
    force: bool
    force_refresh: bool
    limit: int | None
    commit_size: int
    create_repo: bool
    update_card: bool
    reconcile: bool
    prune_parquet: bool
    log: LogSettings

    @property
    def profile(self) -> ModeProfile:
        return ModeProfile.of(self.mode, no_hub=self.no_hub)

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace, *, known_families: Sequence[str]) -> Settings:
        """Build settings from parsed args, raising UsageError on anything impossible.

        This runs ahead of the logging setup on purpose: a run that cannot start
        should not leave a log file behind claiming it did.
        """
        if ns.no_hub and ns.push:
            raise UsageError("--no-hub e --push sao incompativeis (publicar exige ler o manifesto).")
        if ns.sample and ns.push:
            raise UsageError("--sample e --push sao incompativeis (--sample so escreve localmente).")
        for flag, requested in (("--reconciliar", ns.reconciliar), ("--prune-parquet", ns.prune_parquet)):
            if requested and (ns.sample or ns.no_hub):
                raise UsageError(f"{flag} precisa consultar o Hub (incompativel com --sample e --no-hub).")

        mode = Mode.SAMPLE if ns.sample else (Mode.PUSH if ns.push else Mode.DRY_RUN)
        return cls(
            repo_id=ns.repo,
            mode=mode,
            no_hub=bool(ns.no_hub),
            families=tuple(ns.familia or known_families),
            periods=normalize_periods(ns.periodo),
            parquet_dir=Path(ns.parquet_dir),
            cache_dir=Path(ns.cache_dir) if ns.cache_dir else None,
            force=bool(ns.force),
            force_refresh=bool(ns.force_refresh),
            limit=ns.limite,
            commit_size=ns.commit_size or DEFAULT_COMMIT_SIZE,
            create_repo=bool(ns.create_repo),
            update_card=bool(ns.update_card),
            reconcile=bool(ns.reconciliar),
            prune_parquet=bool(ns.prune_parquet),
            log=LogSettings(
                directory=Path(ns.log_dir),
                file=Path(ns.log_file) if ns.log_file else None,
                enabled=not ns.no_log_file,
                verbose=bool(ns.verbose),
            ),
        )


def normalize_periods(values: Sequence[str] | None) -> tuple[str, ...] | None:
    """Normalize the --periodo values, rejecting anything unparseable.

    Round-tripping through ``pd.Period`` also repairs the usual "2024-6" typo,
    which would otherwise match no catalogue entry at all and leave the run
    looking like a legitimate "nothing to do".
    """
    if not values:
        return None
    normalized = []
    for value in values:
        try:
            period = pd.Period(value, freq="M")
        except ValueError as exc:
            raise UsageError(f"periodo invalido: {value!r} ({exc}).") from exc
        if pd.isna(period):
            raise UsageError(f"periodo invalido: {value!r}.")
        normalized.append(str(period))
    return tuple(normalized)
