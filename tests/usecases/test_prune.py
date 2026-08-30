from __future__ import annotations

from br_publisher.domain.manifest import Manifest, ManifestEntry
from br_publisher.domain.recipe import CONVERSION_RECIPE
from br_publisher.infra.build_cache import BuildCache, BuildRecord
from br_publisher.usecases.prune import PruneBuildCache


def _record(**overrides) -> BuildRecord:
    defaults = {
        "source_sha256": "sha256:abc",
        "source_url": "https://fixtures.test/res.csv",
        "resource_id": "res",
        "rows": 2,
        "columns": 2,
        "parquet_bytes": 4,
        "conversion": CONVERSION_RECIPE,
        "built_at": "2024-06-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return BuildRecord(**defaults)


def _entry(**overrides) -> ManifestEntry:
    return ManifestEntry(
        source_sha256=overrides.pop("source_sha256", "sha256:abc"),
        source_url="https://fixtures.test/res.csv",
        resource_id="res",
        conversion=overrides.pop("conversion", CONVERSION_RECIPE),
        **overrides,
    )


def _seed(tmp_path, period: str, record: BuildRecord) -> BuildCache:
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    local = cache.path_for("perfil_unidades", period)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"data")
    cache.put("perfil_unidades", period, record)
    return cache


def test_prune_removes_only_what_the_manifest_confirms(tmp_path):
    cache = _seed(tmp_path, "2024-06", _record())
    _seed(tmp_path, "2024-07", _record())
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)

    manifest = Manifest({"perfil_unidades/2024-06": _entry()})
    files, freed = PruneBuildCache(cache, manifest, CONVERSION_RECIPE)()

    assert (files, freed) == (1, 4)
    assert not cache.path_for("perfil_unidades", "2024-06").exists()
    assert cache.path_for("perfil_unidades", "2024-07").exists()


def test_a_stale_source_hash_is_kept(tmp_path):
    # Deleting it would throw away work the next run still needs.
    cache = _seed(tmp_path, "2024-06", _record())
    manifest = Manifest({"perfil_unidades/2024-06": _entry(source_sha256="sha256:outro")})
    assert PruneBuildCache(cache, manifest, CONVERSION_RECIPE)() == (0, 0)
    assert cache.path_for("perfil_unidades", "2024-06").exists()


def test_a_manifest_entry_on_an_old_recipe_is_kept(tmp_path):
    cache = _seed(tmp_path, "2024-06", _record())
    manifest = Manifest({"perfil_unidades/2024-06": _entry(conversion="v0|antigo")})
    assert PruneBuildCache(cache, manifest, CONVERSION_RECIPE)() == (0, 0)


def test_a_build_record_on_an_old_recipe_is_kept(tmp_path):
    cache = _seed(tmp_path, "2024-06", _record(conversion="v0|antigo"))
    manifest = Manifest({"perfil_unidades/2024-06": _entry()})
    assert PruneBuildCache(cache, manifest, CONVERSION_RECIPE)() == (0, 0)


def test_an_unpublished_month_is_kept(tmp_path):
    cache = _seed(tmp_path, "2024-06", _record())
    assert PruneBuildCache(cache, Manifest.empty(), CONVERSION_RECIPE)() == (0, 0)


def test_an_already_deleted_file_is_not_counted_twice(tmp_path):
    cache = _seed(tmp_path, "2024-06", _record())
    cache.path_for("perfil_unidades", "2024-06").unlink()
    manifest = Manifest({"perfil_unidades/2024-06": _entry()})
    assert PruneBuildCache(cache, manifest, CONVERSION_RECIPE)() == (0, 0)
