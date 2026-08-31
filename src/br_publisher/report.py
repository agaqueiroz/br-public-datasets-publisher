"""The narration of a run: header, fsync'd checkpoints, summary block.

The Reporter owns the durable handler, which used to be a module global -- the
one piece of the old script that made two runs in one process impossible to
reason about.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path

from .domain.plan import Plan
from .domain.recipe import CONVERSION_RECIPE, PARQUET_CACHE_WARN_BYTES
from .infra.fsio import utcnow
from .library import format_bytes, format_seconds
from .logging_setup import DurableFileHandler
from .ports import BuildStore
from .settings import Settings


class Reporter:
    def __init__(self, logger: logging.Logger, handler: DurableFileHandler | None = None) -> None:
        self._logger = logger
        self._handler = handler
        self._started_at = time.perf_counter()

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def info(self, message: str, *args: object) -> None:
        self._logger.info(message, *args)

    def warning(self, message: str, *args: object) -> None:
        self._logger.warning(message, *args)

    def error(self, message: str, *args: object) -> None:
        self._logger.error(message, *args)

    def exception(self, message: str, *args: object) -> None:
        # A thin delegate; every caller is inside an except block.
        self._logger.exception(message, *args)  # noqa: LOG004

    def checkpoint(self, message: str, *args: object) -> None:
        """Log a line that has to be readable after a power cut."""
        self._logger.info(message, *args)
        if self._handler is not None:
            self._handler.sync()

    def header(
        self,
        settings: Settings,
        *,
        cache_root: Path,
        family_keys: Sequence[str],
        log_path: Path | None,
    ) -> None:
        profile = settings.profile
        self.info("=" * 72)
        self.info("publish-to-hf  inicio %s  modo=%s", utcnow(), profile.header_label(reconcile=settings.reconcile))
        self.info("  repo             %s", settings.repo_id if profile.uses_hub else "(nenhum)")
        self.info("  familias         %s", ", ".join(family_keys))
        self.info("  periodos         %s", ", ".join(settings.periods) if settings.periods else "todos")
        self.info("  cache downloads  %s", cache_root)
        self.info("  cache parquet    %s", settings.parquet_dir)
        self.info("  receita          %s", CONVERSION_RECIPE)
        self.info("  log              %s", log_path or "(sem arquivo)")
        self.info("=" * 72)

    def commit(self, number: int, files: int, size: int, ref: str) -> None:
        self.checkpoint("commit %d: %d arquivo(s) + manifesto, %s%s", number, files, format_bytes(size), ref)

    def summary(
        self,
        settings: Settings,
        plan: Plan,
        *,
        commits: int,
        builds: BuildStore,
        log_path: Path | None,
    ) -> None:
        profile = settings.profile
        self.info("-" * 72)
        self.checkpoint("%s", plan.status)
        self.info("  %-16s %d", profile.summary_verb, len(plan.uploads))
        self.info("  %-16s %d", "pulados", len(plan.skipped))
        self.info("  %-16s %d", "falhas", len(plan.failures))
        if plan.notes:
            self.info("  %-16s %d", "apontamentos", len(plan.notes))
        if plan.reconciled:
            self.info("  %-16s %d", "reconciliados", len(plan.reconciled))
        self.info(
            "  %-16s %s convertidos, %s reaproveitados do cache",
            "bytes",
            format_bytes(plan.written_bytes),
            format_bytes(plan.reused_bytes),
        )
        if profile.may_publish:
            self.info("  %-16s %d", "commits", commits)
        self.info("  %-16s %s", "duracao", format_seconds(time.perf_counter() - self._started_at))
        self.info("  %-16s %s", "parou em", plan.last_item or "(nada processado)")
        for family_key, period, error in plan.failures:
            self.info("  falha    %s/%s: %s", family_key, period, error)
        for family_key, period, note in plan.notes:
            self.info("  aponta   %s/%s: %s", family_key, period, note)

        total = builds.total_bytes()
        self.info("  %-16s %s em %s", "cache parquet", format_bytes(total), builds.data_root)
        if total >= PARQUET_CACHE_WARN_BYTES:
            self.warning(
                "o cache de parquet ja ocupa %s; use --prune-parquet para apagar o que ja esta publicado.",
                format_bytes(total),
            )
        if log_path is not None:
            self.info("  %-16s %s", "log", log_path)
        self.info("-" * 72)

        if not profile.may_publish and profile.mode.value == "dry-run" and plan.uploads:
            self.info("nada foi enviado (dry run). repita com --push para publicar.")
