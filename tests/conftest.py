from __future__ import annotations

from pathlib import Path

import pytest

from br_publisher.cli import build_parser
from br_publisher.domain.recipe import CONVERSION_RECIPE
from br_publisher.infra.build_cache import BuildCache
from br_publisher.infra.card import DatasetCardRenderer
from br_publisher.infra.parquet import StreamingParquetConverter
from br_publisher.library.models import Family, SourceResource
from br_publisher.report import Reporter
from br_publisher.settings import Settings
from br_publisher.usecases.publish import PublishContext

from .fakes import FakeCatalog, FakeReader, FakeSourceStore, InMemoryRepository, quiet_reporter

FAMILY_KEYS = (
    "beneficios_concedidos",
    "beneficios_emitidos",
    "beneficios_indeferidos",
    "beneficios_mantidos_ativos",
    "beneficios_mantidos_cessados",
    "beneficios_mantidos_suspensos",
    "comunicacoes_acidente_trabalho",
    "perfil_unidades",
)

FAMILIES = {key: Family(key=key, title=key.replace("_", " ").capitalize()) for key in FAMILY_KEYS}


@pytest.fixture
def make_csv_bytes():
    """Copied from the library's own conftest rather than shared.

    A pytest plugin or a path hack reaching into the sibling checkout would
    couple two repositories through a test fixture -- a worse coupling than the
    one the anti-corruption layer exists to fix. It is eight lines.
    """

    def _make(rows: list[dict], *, delimiter: str = ";", encoding: str = "latin-1") -> bytes:
        headers = list(rows[0].keys())
        lines = [delimiter.join(headers)]
        lines.extend(delimiter.join(str(row[header]) for header in headers) for row in rows)
        return ("\r\n".join(lines) + "\r\n").encode(encoding)

    return _make


def make_settings(**overrides) -> Settings:
    """Real parsed args behind a real Settings, so a renamed flag breaks the tests."""
    argv = list(overrides.pop("argv", ["--no-log-file"]))
    namespace = build_parser(FAMILY_KEYS).parse_args(argv)
    for key, value in overrides.items():
        if not hasattr(namespace, key):
            raise AttributeError(f"a flag {key!r} nao existe no parser")
        setattr(namespace, key, value)
    return Settings.from_namespace(namespace, known_families=FAMILY_KEYS)


@pytest.fixture
def settings():
    return make_settings


def make_resource(
    period: str = "2024-06",
    family_key: str = "perfil_unidades",
    name: str = "Perfil das Unidades Junho 2024",
) -> SourceResource:
    return SourceResource(
        family_key=family_key,
        period=period,
        url="https://fixtures.test/res.csv",
        resource_id=f"res-{period}",
        resource_name=name,
        format="CSV",
    )


@pytest.fixture
def resource():
    return make_resource


def make_context(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    resources: dict[str, tuple[SourceResource, ...]] | None = None,
    store: FakeSourceStore | None = None,
    repository: InMemoryRepository | None = None,
    converter: object | None = None,
    decider: object | None = None,
    reporter: Reporter | None = None,
) -> PublishContext:
    settings = settings or make_settings(parquet_dir=str(tmp_path / "tmp"))
    catalog = FakeCatalog(FAMILIES, resources or {})
    store = store if store is not None else FakeSourceStore(tmp_path / "cache")
    repository = repository if repository is not None else InMemoryRepository()
    builds = BuildCache.load(settings.parquet_dir, recipe=CONVERSION_RECIPE)
    from br_publisher.domain.deciders import ManifestDecider, SampleDecider
    from br_publisher.settings import Mode

    if decider is None:
        decider = (
            SampleDecider(force=settings.force)
            if settings.mode is Mode.SAMPLE
            else ManifestDecider(repository.manifest, CONVERSION_RECIPE, force=settings.force)
        )
    return PublishContext(
        settings=settings,
        profile=settings.profile,
        catalog=catalog,
        store=store,
        builds=builds,
        converter=converter or StreamingParquetConverter(reader=FakeReader()),
        repository=repository,
        decider=decider,
        card=DatasetCardRenderer(families=FAMILIES),
        reporter=reporter or quiet_reporter(),
        recipe=CONVERSION_RECIPE,
    )


@pytest.fixture
def context():
    return make_context
