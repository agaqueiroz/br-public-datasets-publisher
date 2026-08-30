"""Parse, validate, wire, run. The only place that maps an error to an exit code."""

from __future__ import annotations

import sys
from enum import IntEnum

from .cli import build_parser
from .domain.deciders import ManifestDecider, SampleDecider
from .domain.recipe import CONVERSION_RECIPE
from .errors import LibraryIncompatibleError, ManifestError, UsageError
from .infra.build_cache import BuildCache
from .infra.card import DatasetCardRenderer
from .infra.hub import HuggingFaceRepository, build_client, has_token
from .infra.offline import OfflineRepository
from .infra.parquet import StreamingParquetConverter
from .library import BrinssLibrary, check_library
from .logging_setup import configure_logging
from .ports import DatasetRepository
from .report import Reporter
from .settings import Mode, Settings
from .usecases.publish import PublishContext, PublishDatasets


class ExitCode(IntEnum):
    OK = 0
    FAILURES = 1  # a month blew up, or a --periodo matched nothing
    USAGE = 2  # bad flags, no token, unreadable manifest, incompatible library


def main(argv: list[str] | None = None) -> int:
    try:
        check_library()
    except LibraryIncompatibleError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return ExitCode.USAGE

    library = BrinssLibrary()
    known_families = sorted(library.families())

    namespace = build_parser(known_families).parse_args(argv)
    try:
        settings = Settings.from_namespace(namespace, known_families=known_families)
    except UsageError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return ExitCode.USAGE

    if settings.profile.may_publish and not has_token():
        print(
            "erro: --push exige um token de escrita. Defina HF_TOKEN ou rode `hf auth login`.",
            file=sys.stderr,
        )
        return ExitCode.USAGE

    logger, handler, log_path = configure_logging(settings.log)
    reporter = Reporter(logger, handler)

    try:
        ctx = build_context(settings, reporter)
    except ManifestError as exc:
        reporter.error("%s", exc)
        reporter.error(
            "nada foi publicado: um manifesto ilegivel faria o aplicativo reenviar o dataset inteiro."
        )
        return ExitCode.USAGE

    reporter.header(
        settings, cache_root=ctx.store.root, family_keys=settings.families, log_path=log_path
    )

    plan, unmatched = PublishDatasets(ctx)()
    reporter.summary(
        settings, plan, commits=ctx.repository.commits, builds=ctx.builds, log_path=log_path
    )
    return ExitCode.FAILURES if (plan.failures or unmatched) else ExitCode.OK


def build_context(settings: Settings, reporter: Reporter) -> PublishContext:
    """Assemble the real implementations.

    Kept as a plain function on purpose: a DI container for one binary with one
    wiring buys indirection and nothing else. This is the single place that
    names a concrete class.
    """
    library = BrinssLibrary(cache_dir=settings.cache_dir, force_refresh=settings.force_refresh)
    builds = BuildCache.load(settings.parquet_dir, recipe=CONVERSION_RECIPE)
    repository = _build_repository(settings, reporter)

    decider = (
        SampleDecider(force=settings.force)
        if settings.mode is Mode.SAMPLE
        else ManifestDecider(manifest=repository.manifest, recipe=CONVERSION_RECIPE, force=settings.force)
    )

    return PublishContext(
        settings=settings,
        profile=settings.profile,
        catalog=library,
        store=library,
        builds=builds,
        converter=StreamingParquetConverter(reader=library),
        repository=repository,
        decider=decider,
        card=DatasetCardRenderer(families=library.families()),
        reporter=reporter,
        recipe=CONVERSION_RECIPE,
    )


def _build_repository(settings: Settings, reporter: Reporter) -> DatasetRepository:
    if not settings.profile.uses_hub:
        return OfflineRepository()

    repository = HuggingFaceRepository(
        build_client(),
        settings.repo_id,
        commit_size=settings.commit_size,
        on_commit=reporter.commit,
    )
    if settings.profile.may_publish and settings.create_repo:
        repository.ensure_exists()
    manifest = repository.load_manifest()
    reporter.info(
        "manifesto: %d entrada(s); repositorio: %d parquet.", len(manifest), len(repository.list_parquet())
    )
    return repository


if __name__ == "__main__":
    raise SystemExit(main())
