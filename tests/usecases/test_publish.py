from __future__ import annotations

import pyarrow.parquet as pq

from br_publisher.domain.manifest import (
    REASON_NOT_DOWNLOADED,
    REASON_SAMPLE,
    Manifest,
    ManifestEntry,
)
from br_publisher.domain.plan import STATUS_FAILED, Plan
from br_publisher.domain.recipe import CONVERSION_RECIPE
from br_publisher.infra.offline import OfflineRepository
from br_publisher.infra.parquet import StreamingParquetConverter
from br_publisher.usecases.publish import PublishDatasets

from ..conftest import make_context, make_resource, make_settings
from ..fakes import ExplodingReader, FakeReader, FakeSourceStore, InMemoryRepository, RaisingConverter

ROWS = [{"cid": "01234", "valor": "10"}, {"cid": "00987", "valor": "20"}]


def _seed_source(tmp_path, make_csv_bytes, name="res.csv"):
    path = tmp_path / "cache" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_csv_bytes(ROWS))
    return path


def _sample_ctx(
    tmp_path, make_csv_bytes, *, periods=("2024-06",), force=False, cached=True, repository=None, **kw
):
    resources = tuple(make_resource(period) for period in periods)
    store = FakeSourceStore(tmp_path / "cache")
    if cached:
        for index, resource in enumerate(resources):
            store.seed(resource, _seed_source(tmp_path, make_csv_bytes, f"res-{index}.csv"))
    settings = make_settings(
        sample=True, familia=["perfil_unidades"], parquet_dir=str(tmp_path / "tmp"), force=force
    )
    return make_context(
        tmp_path,
        settings=settings,
        resources={"perfil_unidades": resources},
        store=store,
        repository=repository if repository is not None else OfflineRepository(),
        **kw,
    )


# -- --sample -----------------------------------------------------------------


def test_sample_mirrors_the_repo_layout_under_the_parquet_dir(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes)
    plan, unmatched = PublishDatasets(ctx)()

    written = tmp_path / "tmp" / "data" / "perfil_unidades" / "2024-06.parquet"
    assert written.exists()
    assert plan.uploads == [("perfil_unidades", "2024-06", REASON_SAMPLE)]
    assert unmatched == []

    table = pq.read_table(written)
    assert table.column("periodo_referencia").to_pylist() == ["2024-06", "2024-06"]
    assert table.column("cid").to_pylist() == ["01234", "00987"]


def test_sample_skips_a_month_that_is_not_cached(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes, cached=False)
    plan, _ = PublishDatasets(ctx)()
    assert plan.uploads == []
    assert plan.skipped == [("perfil_unidades", "2024-06")]


def test_sample_never_downloads(tmp_path, make_csv_bytes):
    # FakeSourceStore.fetch raises unless given an on_fetch; reaching it fails.
    ctx = _sample_ctx(tmp_path, make_csv_bytes, cached=False)
    PublishDatasets(ctx)()
    assert ctx.store.fetches == []


def test_sample_reuses_an_already_converted_month(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes)
    PublishDatasets(ctx)()
    written = tmp_path / "tmp" / "data" / "perfil_unidades" / "2024-06.parquet"
    before = written.stat().st_mtime_ns

    again = _sample_ctx(tmp_path, make_csv_bytes)
    plan, _ = PublishDatasets(again)()

    assert plan.uploads == []
    assert plan.skipped == [("perfil_unidades", "2024-06")]
    assert written.stat().st_mtime_ns == before


def test_sample_does_not_reopen_the_source_on_a_cache_hit(tmp_path, make_csv_bytes):
    # Injecting the reader beats monkeypatching the library's internals: the
    # test stops depending on which entry point the code happens to use.
    PublishDatasets(_sample_ctx(tmp_path, make_csv_bytes))()
    ctx = _sample_ctx(
        tmp_path, make_csv_bytes, converter=StreamingParquetConverter(reader=ExplodingReader())
    )
    plan, _ = PublishDatasets(ctx)()
    assert plan.skipped == [("perfil_unidades", "2024-06")]


def test_sample_redoes_a_month_when_forced(tmp_path, make_csv_bytes):
    PublishDatasets(_sample_ctx(tmp_path, make_csv_bytes))()
    ctx = _sample_ctx(tmp_path, make_csv_bytes, force=True)
    plan, _ = PublishDatasets(ctx)()
    assert plan.uploads == [("perfil_unidades", "2024-06", REASON_SAMPLE)]


def test_the_offline_repository_never_stages_anything(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes)
    PublishDatasets(ctx)()
    assert ctx.repository.commits == 0
    assert len(ctx.repository.manifest) == 0


# -- dry run ------------------------------------------------------------------


def test_a_dry_run_plans_without_converting(tmp_path, make_csv_bytes):
    resource = make_resource()
    store = FakeSourceStore(tmp_path / "cache")
    store.seed(resource, _seed_source(tmp_path, make_csv_bytes))
    ctx = make_context(
        tmp_path,
        settings=make_settings(familia=["perfil_unidades"], parquet_dir=str(tmp_path / "tmp")),
        resources={"perfil_unidades": (resource,)},
        store=store,
        repository=InMemoryRepository(),
    )
    plan, _ = PublishDatasets(ctx)()

    assert plan.uploads == [("perfil_unidades", "2024-06", "novo")]
    assert not (tmp_path / "tmp" / "data").exists()
    assert ctx.repository.staged == []


def test_a_dry_run_reports_a_month_whose_source_is_not_downloaded(tmp_path):
    resource = make_resource()
    ctx = make_context(
        tmp_path,
        settings=make_settings(familia=["perfil_unidades"], parquet_dir=str(tmp_path / "tmp")),
        resources={"perfil_unidades": (resource,)},
        store=FakeSourceStore(tmp_path / "cache"),
        repository=InMemoryRepository(),
    )
    plan, _ = PublishDatasets(ctx)()
    assert plan.uploads == [("perfil_unidades", "2024-06", REASON_NOT_DOWNLOADED)]
    assert ctx.store.fetches == []


def test_an_unchanged_month_is_skipped(tmp_path, make_csv_bytes):
    from br_publisher.infra.fsio import sha256_file

    resource = make_resource()
    source = _seed_source(tmp_path, make_csv_bytes)
    store = FakeSourceStore(tmp_path / "cache")
    store.seed(resource, source)
    manifest = Manifest(
        {
            "perfil_unidades/2024-06": ManifestEntry(
                source_sha256=sha256_file(source),
                source_url=resource.url,
                resource_id=resource.resource_id,
                conversion=CONVERSION_RECIPE,
            )
        }
    )
    ctx = make_context(
        tmp_path,
        settings=make_settings(familia=["perfil_unidades"], parquet_dir=str(tmp_path / "tmp")),
        resources={"perfil_unidades": (resource,)},
        store=store,
        repository=InMemoryRepository(manifest),
    )
    plan, _ = PublishDatasets(ctx)()
    assert plan.uploads == []
    assert plan.skipped == [("perfil_unidades", "2024-06")]


# -- scope and failures -------------------------------------------------------


def test_a_requested_period_that_matches_nothing_is_reported(tmp_path):
    ctx = make_context(
        tmp_path,
        settings=make_settings(
            familia=["perfil_unidades"], periodo=["2099-01"], parquet_dir=str(tmp_path / "tmp")
        ),
        resources={"perfil_unidades": (make_resource("2024-06"),)},
        repository=InMemoryRepository(),
    )
    plan, unmatched = PublishDatasets(ctx)()
    assert unmatched == ["2099-01"]
    assert plan.status == STATUS_FAILED


def test_periodo_narrows_the_run(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes, periods=("2024-06", "2024-07"))
    ctx = make_context(
        tmp_path,
        settings=make_settings(
            sample=True,
            familia=["perfil_unidades"],
            periodo=["2024-07"],
            parquet_dir=str(tmp_path / "tmp"),
        ),
        resources=ctx.catalog._resources,
        store=ctx.store,
        repository=OfflineRepository(),
    )
    plan, unmatched = PublishDatasets(ctx)()
    assert unmatched == []
    assert [item[1] for item in plan.uploads] == ["2024-07"]


def test_a_month_that_blows_up_does_not_take_the_run_with_it(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(
        tmp_path,
        make_csv_bytes,
        periods=("2024-06", "2024-07"),
        converter=RaisingConverter("2024-06", inner=StreamingParquetConverter(reader=FakeReader())),
    )
    plan, _ = PublishDatasets(ctx)()

    assert plan.status == STATUS_FAILED
    assert [(f, p) for f, p, _ in plan.failures] == [("perfil_unidades", "2024-06")]
    assert (tmp_path / "tmp" / "data" / "perfil_unidades" / "2024-07.parquet").exists()


def test_the_limit_stops_the_run_early(tmp_path, make_csv_bytes):
    ctx = _sample_ctx(tmp_path, make_csv_bytes, periods=("2024-06", "2024-07", "2024-08"))
    ctx = make_context(
        tmp_path,
        settings=make_settings(
            sample=True, familia=["perfil_unidades"], limite=2, parquet_dir=str(tmp_path / "tmp")
        ),
        resources=ctx.catalog._resources,
        store=ctx.store,
        repository=OfflineRepository(),
    )
    plan, _ = PublishDatasets(ctx)()
    assert len(plan.uploads) == 2


def test_the_last_item_names_the_month_that_was_in_flight(tmp_path, make_csv_bytes):
    # On a power cut the last line of the log has to name the month that was in
    # flight, not the last one that finished.
    ctx = _sample_ctx(tmp_path, make_csv_bytes, periods=("2024-06", "2024-07"))
    plan, _ = PublishDatasets(ctx)()
    assert plan.last_item == "perfil_unidades/2024-07"


def test_an_empty_run_reports_nothing_processed(tmp_path):
    ctx = make_context(tmp_path, resources={}, repository=InMemoryRepository())
    plan, _ = PublishDatasets(ctx)()
    assert plan == Plan()


# -- apontamento: contagem de colunas -----------------------------------------


def _ctx_with_published_columns(tmp_path, make_csv_bytes, columns: int):
    # The seeded CSV converts to 3 columns: two of its own plus periodo_referencia.
    return _sample_ctx(
        tmp_path,
        make_csv_bytes,
        repository=InMemoryRepository(
            Manifest(
                {
                    "perfil_unidades/2024-05": ManifestEntry(
                        source_sha256="sha256:old",
                        source_url="https://fixtures.test/old.csv",
                        resource_id="old",
                        columns=columns,
                        conversion=CONVERSION_RECIPE,
                    )
                }
            )
        ),
    )


def test_a_collapse_in_column_count_becomes_an_apontamento(tmp_path, make_csv_bytes):
    # The 2026-07 mantidos months went out with 2 columns where every earlier
    # month had 18, and nothing in the run said so.
    plan, _ = PublishDatasets(_ctx_with_published_columns(tmp_path, make_csv_bytes, 18))()

    assert len(plan.notes) == 1
    family_key, period, note = plan.notes[0]
    assert (family_key, period) == ("perfil_unidades", "2024-06")
    assert "queda de 18 para 3 colunas" in note


def test_a_smaller_change_in_column_count_is_noted_more_plainly(tmp_path, make_csv_bytes):
    plan, _ = PublishDatasets(_ctx_with_published_columns(tmp_path, make_csv_bytes, 4))()

    assert [note for _, _, note in plan.notes] == ["4 colunas no mes anterior publicado, 3 agora"]


def test_an_apontamento_does_not_fail_the_month(tmp_path, make_csv_bytes):
    # The sources really do change shape -- beneficios_emitidos went from 14
    # columns to 15 -- so this reports rather than refuses. The hard stop for a
    # CSV that cannot be parsed without loss lives in the reader.
    plan, _ = PublishDatasets(_ctx_with_published_columns(tmp_path, make_csv_bytes, 18))()

    assert plan.failures == []
    assert (tmp_path / "tmp" / "data" / "perfil_unidades" / "2024-06.parquet").exists()


def test_an_unchanged_column_count_says_nothing(tmp_path, make_csv_bytes):
    plan, _ = PublishDatasets(_ctx_with_published_columns(tmp_path, make_csv_bytes, 3))()

    assert plan.notes == []


def test_the_first_month_of_a_family_has_nothing_to_compare_against(tmp_path, make_csv_bytes):
    plan, _ = PublishDatasets(_sample_ctx(tmp_path, make_csv_bytes))()

    assert plan.notes == []
