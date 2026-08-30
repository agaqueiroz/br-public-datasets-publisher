from __future__ import annotations

import pytest

from br_publisher.domain.manifest import (
    Manifest,
    ManifestEntry,
    find_orphans,
    published_families,
)
from br_publisher.domain.recipe import CONVERSION_RECIPE, MANIFEST_SCHEMA_VERSION
from br_publisher.errors import ManifestError

from ..conftest import FAMILY_KEYS


def _entry(**overrides) -> ManifestEntry:
    return ManifestEntry(
        source_sha256=overrides.pop("source_sha256", "sha256:abc"),
        source_url="https://fixtures.test/res.csv",
        resource_id="res",
        conversion=CONVERSION_RECIPE,
        **overrides,
    )


def test_find_orphans_lists_published_files_the_manifest_forgot():
    manifest = Manifest({"perfil_unidades/2024-06": _entry()})
    repo_files = {
        "data/perfil_unidades/2024-06.parquet": 10,
        "data/perfil_unidades/2024-07.parquet": 20,
        "data/beneficios_concedidos/2024-01.parquet": 30,
    }
    assert find_orphans(repo_files, manifest, FAMILY_KEYS) == [
        ("data/beneficios_concedidos/2024-01.parquet", "beneficios_concedidos", "2024-01"),
        ("data/perfil_unidades/2024-07.parquet", "perfil_unidades", "2024-07"),
    ]


def test_find_orphans_ignores_what_is_not_a_published_parquet():
    repo_files = {"manifest.json": 1, "data/README.md": 2, "data/desconhecida/2024-06.parquet": 3}
    assert find_orphans(repo_files, Manifest.empty(), FAMILY_KEYS) == []


def test_published_families_only_lists_what_the_manifest_has():
    manifest = Manifest(
        {
            "perfil_unidades/2024-06": _entry(),
            "beneficios_concedidos/2024-01": _entry(),
            "familia_que_nao_existe/2024-01": _entry(),
        }
    )
    assert published_families(manifest, FAMILY_KEYS) == ["beneficios_concedidos", "perfil_unidades"]


def test_published_families_of_an_empty_manifest():
    assert published_families(Manifest.empty(), FAMILY_KEYS) == []


def test_a_manifest_round_trips_through_its_payload():
    original = Manifest({"perfil_unidades/2024-06": _entry(rows=5, columns=2, parquet_bytes=99)})
    restored = Manifest.from_payload(original.to_payload())
    assert restored.entries() == original.entries()


def test_an_adopted_entry_keeps_its_flag_and_null_row_count():
    entry = _entry(rows=None, columns=None, parquet_bytes=42, adopted=True)
    payload = Manifest({"perfil_unidades/2024-06": entry}).to_payload()
    assert payload["entries"]["perfil_unidades/2024-06"]["adopted"] is True
    assert payload["entries"]["perfil_unidades/2024-06"]["rows"] is None


def test_a_normal_entry_does_not_carry_an_adopted_key():
    payload = Manifest({"perfil_unidades/2024-06": _entry()}).to_payload()
    assert "adopted" not in payload["entries"]["perfil_unidades/2024-06"]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema_version": MANIFEST_SCHEMA_VERSION},
        {"schema_version": MANIFEST_SCHEMA_VERSION, "entries": []},
        {"schema_version": 99, "entries": {}},
        "nao e um objeto",
    ],
)
def test_an_untrustworthy_manifest_is_an_error_not_an_empty_one(payload):
    # Degrading into an empty manifest would reclassify every published month as
    # "novo" and re-upload the whole dataset.
    with pytest.raises(ManifestError):
        Manifest.from_payload(payload)


def test_adopt_is_the_only_way_entries_appear():
    manifest = Manifest.empty()
    assert len(manifest) == 0
    manifest.adopt({"perfil_unidades/2024-06": _entry()})
    assert len(manifest) == 1
    assert manifest.get("perfil_unidades", "2024-06") is not None


def test_entries_returns_a_copy_so_callers_cannot_smuggle_one_in():
    manifest = Manifest.empty()
    manifest.entries()["perfil_unidades/2024-06"] = _entry()
    assert len(manifest) == 0
