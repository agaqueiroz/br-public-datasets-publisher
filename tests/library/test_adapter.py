"""The canary.

These tests deliberately import the real private modules of brinss -- they are,
with test_compat.py, the only ones exempted from the import ban enforced by
tests/test_boundaries.py. Their job is to fail loudly the day the library
renames something, instead of letting a run silently report every cached month
as missing.
"""

from __future__ import annotations

import pandas as pd
import pytest
from brinss.datasets import _cache
from brinss.datasets._catalog import ResourceEntry

from br_publisher.library import BrinssLibrary
from br_publisher.library.models import SourceResource


def _entry(period: str = "2024-06", name: str = "Perfil das Unidades Junho 2024") -> ResourceEntry:
    return ResourceEntry(
        period=pd.Period(period, freq="M"),
        url="https://fixtures.test/res.csv",
        resource_id=f"res-{period}",
        resource_name=name,
        package_slug="slug",
        format="CSV",
    )


def _resource(entry: ResourceEntry, family_key: str = "perfil_unidades") -> SourceResource:
    return SourceResource(
        family_key=family_key,
        period=str(entry.period),
        url=entry.url,
        resource_id=entry.resource_id,
        resource_name=entry.resource_name,
        format=entry.format,
        native=entry,
    )


def test_cached_path_finds_a_file_written_under_the_library_layout(tmp_path):
    # Pinned against the real _cache helpers, so a rename there fails the suite
    # instead of silently reporting every cached month as missing.
    entry = _entry()
    path = tmp_path / "files" / "perfil_unidades" / _cache._resource_filename(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"conteudo")

    library = BrinssLibrary(cache_dir=tmp_path)
    assert library.cached_path(_resource(entry)) == path


def test_cached_path_is_none_when_nothing_was_downloaded(tmp_path):
    library = BrinssLibrary(cache_dir=tmp_path)
    assert library.cached_path(_resource(_entry())) is None


def test_known_digest_reads_the_registry_the_library_writes(tmp_path):
    entry = _entry()
    filename = _cache._resource_filename(entry)
    _cache._save_registry(tmp_path, {f"perfil_unidades/{filename}": "sha256:abc"})

    library = BrinssLibrary(cache_dir=tmp_path)
    assert library.known_digest(_resource(entry)) == "sha256:abc"


def test_known_digest_is_none_without_a_registry(tmp_path):
    library = BrinssLibrary(cache_dir=tmp_path)
    assert library.known_digest(_resource(_entry())) is None


def test_the_root_honours_an_explicit_cache_dir(tmp_path):
    assert BrinssLibrary(cache_dir=tmp_path).root == tmp_path


def test_the_root_honours_brinss_data_home(tmp_path, monkeypatch):
    # The precedence rule belongs to the library; re-reading the env var here
    # would create a second source of truth that could disagree with it.
    monkeypatch.setenv("BRINSS_DATA_HOME", str(tmp_path))
    assert BrinssLibrary().root == tmp_path


def test_families_are_translated_into_our_own_type():
    families = BrinssLibrary().families()
    assert "perfil_unidades" in families
    family = families["perfil_unidades"]
    assert family.key == "perfil_unidades"
    assert isinstance(family.title, str) and family.title


def test_a_wrapped_resource_hands_the_original_entry_back():
    # Rebuilding one would work today and break the day upstream adds a field.
    entry = _entry()
    library = BrinssLibrary()
    assert library._native(_resource(entry)) is entry


def test_a_resource_without_a_handle_is_rebuilt_well_enough_to_name_a_file():
    library = BrinssLibrary()
    bare = SourceResource(
        family_key="perfil_unidades",
        period="2024-06",
        url="https://fixtures.test/res.csv",
        resource_id="res-2024-06",
        resource_name="Perfil das Unidades Junho 2024",
        format="CSV",
    )
    assert _cache._resource_filename(library._native(bare)) == _cache._resource_filename(_entry())


def test_encodings_delegates_to_the_library(tmp_path):
    path = tmp_path / "res.csv"
    path.write_bytes("cabecalho;acentuado\r\n1;2\r\n".encode("latin-1"))
    assert BrinssLibrary().encodings(path)


def test_encodings_of_a_spreadsheet_is_empty(tmp_path):
    # The converter turns [] into a single attempt with encoding=None.
    xlsx = pytest.importorskip("openpyxl")
    path = tmp_path / "res.xlsx"
    workbook = xlsx.Workbook()
    workbook.active.append(["a", "b"])
    workbook.save(path)
    assert BrinssLibrary().encodings(path) == []


def test_resource_for_returns_none_for_an_unknown_family():
    assert BrinssLibrary().resource_for("familia_que_nao_existe", "2024-06") is None
