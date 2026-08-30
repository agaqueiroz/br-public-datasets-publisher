from __future__ import annotations

from br_publisher.domain.manifest import Manifest
from br_publisher.domain.plan import Plan
from br_publisher.domain.recipe import CONVERSION_RECIPE
from br_publisher.usecases.reconcile import ReconcileOrphans

from ..conftest import make_context, make_resource, make_settings
from ..fakes import FakeSourceStore, InMemoryRepository

ORPHAN = ("data/perfil_unidades/2024-06.parquet", "perfil_unidades", "2024-06")
REPO_FILES = {"data/perfil_unidades/2024-06.parquet": 4096}


def _ctx(tmp_path, *, push=False, store=None, resources=None):
    settings = make_settings(
        push=push, reconciliar=True, familia=["perfil_unidades"], parquet_dir=str(tmp_path / "tmp")
    )
    return make_context(
        tmp_path,
        settings=settings,
        resources=resources if resources is not None else {"perfil_unidades": (make_resource(),)},
        store=store or FakeSourceStore(tmp_path / "cache"),
        repository=InMemoryRepository(Manifest.empty(), REPO_FILES),
    )


def test_adoption_uses_the_download_registry_without_downloading(tmp_path):
    # The library keeps a resource's hash even after the file is deleted, so a
    # month whose source is long gone can still be identified for free.
    store = FakeSourceStore(tmp_path / "cache", digests={"perfil_unidades/2024-06": "sha256:abc"})
    ctx = _ctx(tmp_path, push=True, store=store)
    plan = Plan()

    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, plan)

    assert store.fetches == []
    (entries, message) = ctx.repository.manifest_replacements[0]
    entry = entries["perfil_unidades/2024-06"]
    assert entry.source_sha256 == "sha256:abc"
    assert entry.adopted is True
    assert entry.rows is None and entry.columns is None
    assert entry.parquet_bytes == 4096
    assert entry.conversion == CONVERSION_RECIPE
    assert message == "Reconciliar 1 arquivo(s) ja publicados"
    assert plan.reconciled == [("perfil_unidades", "2024-06")]


def test_adoption_falls_back_to_hashing_the_cached_source(tmp_path, make_csv_bytes):
    source = tmp_path / "cache" / "res.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(make_csv_bytes([{"a": "1"}]))
    store = FakeSourceStore(tmp_path / "cache")
    store.seed(make_resource(), source)

    ctx = _ctx(tmp_path, push=True, store=store)
    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, Plan())

    (entries, _) = ctx.repository.manifest_replacements[0]
    assert entries["perfil_unidades/2024-06"].source_sha256.startswith("sha256:")
    assert store.fetches == []


def test_a_dry_run_only_reports(tmp_path):
    store = FakeSourceStore(tmp_path / "cache", digests={"perfil_unidades/2024-06": "sha256:abc"})
    ctx = _ctx(tmp_path, push=False, store=store)
    plan = Plan()

    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, plan)

    assert ctx.repository.manifest_replacements == []
    assert plan.reconciled == []


def test_a_dry_run_never_downloads(tmp_path):
    # The standing rule: a dry run never fetches. FakeSourceStore.fetch raises,
    # so reaching it fails the test.
    ctx = _ctx(tmp_path, push=False)
    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, Plan())
    assert ctx.store.fetches == []
    assert ctx.repository.manifest_replacements == []


def test_push_downloads_only_when_the_hash_is_unavailable(tmp_path, make_csv_bytes):
    fetched = tmp_path / "baixado.csv"
    fetched.write_bytes(make_csv_bytes([{"a": "1"}]))
    store = FakeSourceStore(tmp_path / "cache", on_fetch=lambda resource: fetched)

    ctx = _ctx(tmp_path, push=True, store=store)
    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, Plan())

    assert store.fetches == ["perfil_unidades/2024-06"]
    assert ctx.repository.manifest_replacements


def test_an_orphan_with_no_catalogue_entry_is_ignored(tmp_path):
    ctx = _ctx(tmp_path, push=True, resources={"perfil_unidades": ()})
    plan = Plan()
    ReconcileOrphans(ctx)([ORPHAN], REPO_FILES, plan)
    assert ctx.repository.manifest_replacements == []
    assert plan.reconciled == []


def test_nothing_to_adopt_is_not_an_error(tmp_path):
    ctx = _ctx(tmp_path, push=True)
    ReconcileOrphans(ctx)([], {}, Plan())
    assert ctx.repository.manifest_replacements == []
