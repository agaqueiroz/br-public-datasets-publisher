from __future__ import annotations

import json

from br_publisher.domain.recipe import BUILD_INDEX_NAME, CONVERSION_RECIPE
from br_publisher.infra.build_cache import BuildCache, BuildRecord


def _record(**overrides) -> BuildRecord:
    defaults = {
        "source_sha256": "sha256:abc",
        "source_url": "https://fixtures.test/res.csv",
        "resource_id": "res-2024-06",
        "rows": 2,
        "columns": 2,
        "parquet_bytes": 10,
        "conversion": CONVERSION_RECIPE,
        "built_at": "2024-06-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return BuildRecord(**defaults)


def _cache_with(tmp_path, record: BuildRecord, *, contents: bytes = b"0123456789") -> BuildCache:
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    local = cache.path_for("perfil_unidades", "2024-06")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(contents)
    cache.put("perfil_unidades", "2024-06", record)
    return cache


def test_a_recorded_parquet_is_reusable(tmp_path):
    cache = _cache_with(tmp_path, _record())
    assert cache.is_reusable("perfil_unidades", "2024-06", "sha256:abc") is True


def test_a_new_source_invalidates_the_cached_parquet(tmp_path):
    cache = _cache_with(tmp_path, _record())
    assert cache.is_reusable("perfil_unidades", "2024-06", "sha256:zzz") is False


def test_a_recipe_bump_invalidates_the_cached_parquet(tmp_path):
    cache = _cache_with(tmp_path, _record(conversion="v0|antigo"))
    assert cache.is_reusable("perfil_unidades", "2024-06", "sha256:abc") is False


def test_a_truncated_parquet_is_not_reused(tmp_path):
    # The index entry is intact, the bytes are not: exactly what a power cut
    # leaves behind. The size check is the only thing that catches it.
    cache = _cache_with(tmp_path, _record(parquet_bytes=999))
    assert cache.is_reusable("perfil_unidades", "2024-06", "sha256:abc") is False


def test_a_deleted_parquet_is_not_reused(tmp_path):
    cache = _cache_with(tmp_path, _record())
    cache.path_for("perfil_unidades", "2024-06").unlink()
    assert cache.is_reusable("perfil_unidades", "2024-06", "sha256:abc") is False


def test_an_unknown_month_is_not_reusable(tmp_path):
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    assert cache.is_reusable("perfil_unidades", "2099-01", "sha256:abc") is False


def test_the_index_survives_a_reload(tmp_path):
    _cache_with(tmp_path, _record())
    reloaded = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    assert reloaded.record_for("perfil_unidades", "2024-06") == _record()


def test_a_corrupt_index_starts_over_instead_of_failing(tmp_path):
    # Tolerating corruption is right here and wrong for the manifest: losing the
    # index costs a reconversion, misreading the manifest re-uploads everything.
    (tmp_path / BUILD_INDEX_NAME).write_text("{ truncado", encoding="utf-8")
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    assert cache.record_for("perfil_unidades", "2024-06") is None


def test_an_index_without_entries_starts_over(tmp_path):
    (tmp_path / BUILD_INDEX_NAME).write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    cache = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    assert list(cache.iter_records()) == []


def test_a_leftover_temp_index_does_not_shadow_the_good_one(tmp_path):
    _cache_with(tmp_path, _record())
    (tmp_path / f"{BUILD_INDEX_NAME}.tmp").write_text("{ truncado", encoding="utf-8")
    reloaded = BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE)
    assert reloaded.record_for("perfil_unidades", "2024-06") is not None


def test_drop_frees_the_bytes_and_reports_them(tmp_path):
    cache = _cache_with(tmp_path, _record())
    assert cache.drop("perfil_unidades", "2024-06") == 10
    assert cache.drop("perfil_unidades", "2024-06") == 0


def test_total_bytes_counts_only_parquet(tmp_path):
    cache = _cache_with(tmp_path, _record())
    (cache.data_root / "ruido.txt").write_bytes(b"xxxx")
    assert cache.total_bytes() == 10


def test_total_bytes_of_an_untouched_cache(tmp_path):
    assert BuildCache.load(tmp_path, recipe=CONVERSION_RECIPE).total_bytes() == 0


def test_a_build_record_becomes_a_manifest_entry_without_the_local_detail(tmp_path):
    entry = _record().to_manifest_entry()
    assert entry.rows == 2
    assert entry.source_sha256 == "sha256:abc"
    assert "built_at" not in entry.to_payload()
