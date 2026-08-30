"""The run loop: one month at a time, with a failure isolated to the month it hit."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from br_publisher.domain.keys import manifest_key, path_in_repo
from br_publisher.domain.manifest import (
    REASON_NOT_DOWNLOADED,
    Manifest,
    find_orphans,
    published_families,
)
from br_publisher.domain.plan import STATUS_FAILED, STATUS_INTERRUPTED, Plan
from br_publisher.infra.build_cache import BuildRecord
from br_publisher.infra.fsio import sha256_file, utcnow
from br_publisher.library import format_bytes, format_seconds
from br_publisher.library.models import SourceResource
from br_publisher.ports import (
    BuildStore,
    CardRenderer,
    DatasetRepository,
    ParquetConverter,
    SourceCatalog,
    SourceStore,
)
from br_publisher.report import Reporter
from br_publisher.settings import ModeProfile, Settings

from .prune import PruneBuildCache
from .reconcile import ReconcileOrphans


@dataclass(frozen=True, slots=True)
class PublishContext:
    """Everything the run loop needs, assembled once by main.build_context()."""

    settings: Settings
    profile: ModeProfile
    catalog: SourceCatalog
    store: SourceStore
    builds: BuildStore
    converter: ParquetConverter
    repository: DatasetRepository
    decider: object
    card: CardRenderer
    reporter: Reporter
    recipe: str


class PublishDatasets:
    """Convert and publish every requested month.

    A month that blows up is recorded and the run moves on -- a corrupt XLSX used
    to abort the whole run at whatever month it hit. KeyboardInterrupt and any
    unhandled exception still exit through _finish, so the pending commit batch
    is not lost.
    """

    def __init__(self, ctx: PublishContext) -> None:
        self._ctx = ctx
        self._matched_periods: set[str] = set()

    def __call__(self) -> tuple[Plan, list[str]]:
        ctx = self._ctx
        plan = Plan()
        families = ctx.settings.families

        if ctx.settings.prune_parquet:
            files, freed = PruneBuildCache(ctx.builds, ctx.repository.manifest, ctx.recipe)()
            ctx.reporter.info("prune: %d parquet removido(s), %s liberados.", files, format_bytes(freed))

        try:
            resources = {key: ctx.catalog.resources(key) for key in families}

            orphans = self._report_orphans()
            if ctx.settings.reconcile:
                ReconcileOrphans(ctx)(orphans, ctx.repository.list_parquet(), plan)

            for family_key in families:
                for resource in resources[family_key]:
                    period = resource.period
                    if ctx.settings.periods is not None:
                        if period not in ctx.settings.periods:
                            continue
                        self._matched_periods.add(period)

                    if ctx.settings.limit and len(plan.uploads) >= ctx.settings.limit:
                        ctx.reporter.info("limite de %d arquivos atingido; parando.", ctx.settings.limit)
                        return self._finish(plan)

                    plan.last_item = f"{family_key}/{period}"
                    # Logged *before* the work, not after: on a power cut the
                    # last line of the log has to name the month that was in
                    # flight, not the last one that finished.
                    ctx.reporter.checkpoint("iniciando %s", plan.last_item)
                    try:
                        self._process(resource, plan)
                    except Exception as exc:
                        ctx.reporter.exception("falha em %s/%s", family_key, period)
                        plan.failures.append((family_key, period, f"{type(exc).__name__}: {exc}"))
                        plan.status = STATUS_FAILED

                if ctx.profile.may_publish:
                    # Keep every commit within one family, so the message reads well.
                    ctx.repository.flush()
        except KeyboardInterrupt:
            plan.status = STATUS_INTERRUPTED
            ctx.reporter.warning("interrompido; publicando o que ja foi convertido.")
        except Exception:
            plan.status = STATUS_FAILED
            ctx.reporter.exception(
                "erro nao tratado; encerrando pelo caminho normal para nao perder o lote pendente"
            )

        return self._finish(plan)

    def _process(self, resource: SourceResource, plan: Plan) -> None:
        """Handle one month: decide, convert if needed, and stage it for a commit."""
        ctx = self._ctx
        family_key, period = resource.family_key, resource.period
        target = path_in_repo(family_key, period)

        source = ctx.store.cached_path(resource)
        if source is None and not ctx.profile.may_download:
            if ctx.profile.mode.value == "sample":
                plan.skipped.append((family_key, period))
                ctx.reporter.info("  skip  %s/%s (nao esta em cache)", family_key, period)
                return
            # Cannot know whether it changed without the bytes, and a dry run is
            # not worth a multi-GB download.
            plan.uploads.append((family_key, period, REASON_NOT_DOWNLOADED))
            ctx.reporter.info("  PLAN  %s (fonte ainda nao baixada)", target)
            return
        if source is None:
            source = ctx.store.fetch(resource)

        digest = sha256_file(source)
        reusable = ctx.builds.is_reusable(family_key, period, digest)
        decision = ctx.decider.decide(family_key, period, digest, reusable=reusable)

        if not decision.upload:
            plan.skipped.append((family_key, period))
            record = ctx.builds.record_for(family_key, period)
            if record is not None and reusable:
                plan.reused_bytes += record.parquet_bytes
            ctx.reporter.info("  skip  %s/%s (%s)", family_key, period, decision.reason)
            return

        plan.uploads.append((family_key, period, decision.reason))
        if not ctx.profile.may_convert:
            # A dry run must not convert. Hiding this behind a NullConverter
            # would make the "PLAN" line harder to find than the branch it
            # replaced.
            ctx.reporter.info("  PLAN  %s (%s)", target, decision.reason)
            return

        local, record, reused = self._materialize(resource, digest, source)
        size = record.parquet_bytes
        if reused:
            plan.reused_bytes += size
        else:
            plan.written_bytes += size

        if not ctx.profile.may_publish:
            return

        ctx.reporter.info(
            "  push  %s (%s linhas, %s, %s)", target, f"{record.rows:,}", format_bytes(size), decision.reason
        )
        ctx.repository.stage(local, target, manifest_key(family_key, period), record.to_manifest_entry(), size)

    def _materialize(
        self, resource: SourceResource, digest: str, source: Path
    ) -> tuple[Path, BuildRecord, bool]:
        """The cached Parquet for one month, converting it only if needed.

        The third element says whether the file was reused. On a reuse the row
        and byte counts come from the index, so a re-upload never has to reopen a
        frame it already converted.
        """
        ctx = self._ctx
        family_key, period = resource.family_key, resource.period
        local = ctx.builds.path_for(family_key, period)

        if not ctx.settings.force and ctx.builds.is_reusable(family_key, period, digest):
            record = ctx.builds.record_for(family_key, period)
            assert record is not None  # is_reusable said so
            ctx.reporter.info("  cache %s/%s (parquet ja convertido)", family_key, period)
            return local, record, True

        started_at = time.perf_counter()
        result = ctx.converter.convert(resource, source, local)
        record = BuildRecord(
            source_sha256=digest,
            source_url=resource.url,
            resource_id=resource.resource_id,
            rows=result.rows,
            columns=result.columns,
            parquet_bytes=local.stat().st_size,
            conversion=ctx.recipe,
            built_at=utcnow(),
        )
        # Parquet first, index second. The only inconsistency a crash can leave
        # is "file is there, index does not know", which costs one reconversion.
        # The other order leaves the index vouching for a possibly truncated file.
        ctx.builds.put(family_key, period, record)
        ctx.reporter.info(
            "  gera  %s (%s linhas, %s, %s)",
            local,
            f"{record.rows:,}",
            format_bytes(record.parquet_bytes),
            format_seconds(time.perf_counter() - started_at),
        )
        return local, record, False

    def _report_orphans(self) -> list[tuple[str, str, str]]:
        ctx = self._ctx
        repo_files = ctx.repository.list_parquet()
        known = ctx.catalog.families()
        orphans = [
            item
            for item in find_orphans(repo_files, ctx.repository.manifest, known)
            if item[1] in ctx.settings.families
            and (ctx.settings.periods is None or item[2] in ctx.settings.periods)
        ]
        if not orphans:
            return orphans
        ctx.reporter.warning(
            "%d arquivo(s) no repositorio sem entrada no manifesto; serao reenviados como 'novo'.",
            len(orphans),
        )
        for path, _, _ in orphans[:10]:
            ctx.reporter.warning("  orfao %s", path)
        if len(orphans) > 10:
            ctx.reporter.warning("  ... e mais %d.", len(orphans) - 10)
        ctx.reporter.warning("use --reconciliar para adota-los no manifesto sem reconverter nem reenviar.")
        return orphans

    def _finish(self, plan: Plan) -> tuple[Plan, list[str]]:
        """Land the last batch, refresh the card, then report what is unmatched."""
        ctx = self._ctx
        if ctx.profile.may_publish:
            try:
                ctx.repository.flush()
            except Exception:
                ctx.reporter.exception("falha ao publicar o ultimo lote")
                plan.failures.append(("-", "-", "falha no commit final"))
                plan.status = STATUS_FAILED
            if ctx.repository.commits:
                try:
                    self._write_card(ctx.repository.manifest)
                except Exception:
                    ctx.reporter.exception("falha ao atualizar o dataset card (os dados ja estao publicados)")

        unmatched = sorted(set(ctx.settings.periods or ()) - self._matched_periods)
        if unmatched:
            ctx.reporter.error("nenhum recurso encontrado para: %s.", ", ".join(unmatched))
            if plan.status not in (STATUS_FAILED, STATUS_INTERRUPTED):
                plan.status = STATUS_FAILED
        return plan, unmatched

    def _write_card(self, manifest: Manifest) -> None:
        ctx = self._ctx
        known = ctx.catalog.families()
        families = published_families(manifest, known) or sorted(known)
        ctx.repository.write_card(ctx.card.render(families), overwrite=ctx.settings.update_card)
