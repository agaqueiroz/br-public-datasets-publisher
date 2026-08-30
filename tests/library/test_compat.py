from __future__ import annotations

import importlib

import pytest
from brinss.datasets import _cache

from br_publisher.errors import LibraryIncompatibleError
from br_publisher.library import check_library, compat


def test_the_installed_library_passes_the_self_check():
    check_library()


def test_a_missing_symbol_is_named_in_the_error(monkeypatch):
    # Without this, a rename upstream surfaces as an AttributeError at month 40
    # of a --push, with the manifest half written.
    monkeypatch.delattr(_cache, "_resource_filename")
    with pytest.raises(LibraryIncompatibleError, match="_resource_filename"):
        check_library()


def test_a_missing_module_is_reported_as_incompatible(monkeypatch):
    monkeypatch.setattr(
        compat, "REQUIRED_SYMBOLS", (("brinss.datasets._modulo_que_sumiu", "qualquer"),)
    )
    with pytest.raises(LibraryIncompatibleError, match="_modulo_que_sumiu"):
        check_library()


def test_a_resource_entry_that_lost_a_field_is_reported(monkeypatch):
    monkeypatch.setattr(compat, "REQUIRED_ENTRY_FIELDS", frozenset({"campo_inexistente"}))
    with pytest.raises(LibraryIncompatibleError, match="campo_inexistente"):
        check_library()


def test_a_changed_filename_rule_is_caught_even_though_it_never_raises(monkeypatch):
    # This is the silent failure worth paying for: a changed naming rule does
    # not raise, it just reports every cached month as missing and makes a
    # --sample run quietly do nothing.
    monkeypatch.setattr(_cache, "_resource_filename", lambda entry: "outro-nome.csv")
    with pytest.raises(LibraryIncompatibleError, match="nome do arquivo em cache mudou"):
        check_library()


def test_a_version_outside_the_supported_range_is_rejected(monkeypatch):
    monkeypatch.setattr(compat, "installed_version", lambda: "9.9.9")
    with pytest.raises(LibraryIncompatibleError, match="fora da faixa suportada"):
        check_library()


def test_an_editable_checkout_without_metadata_still_runs(monkeypatch):
    monkeypatch.setattr(compat, "installed_version", lambda: None)
    check_library()


def test_every_private_module_the_adapter_imports_is_listed():
    """The list must not drift behind the adapter it protects."""
    import ast
    from pathlib import Path

    source = Path(compat.__file__).with_name("adapter.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("brinss"):
            for alias in node.names:
                if alias.name.startswith("_"):
                    imported.add(f"{node.module}.{alias.name}")
                    imported.add(alias.name)

    listed = {module for module, _ in compat.REQUIRED_SYMBOLS}
    for name in ("_cache", "_catalog", "_log", "_reading"):
        if name in imported:
            assert f"brinss.datasets.{name}" in listed, f"{name} nao esta em REQUIRED_SYMBOLS"


def test_the_probe_matches_what_the_library_actually_produces():
    entry_module = importlib.import_module("brinss.datasets._catalog")
    assert hasattr(entry_module, "ResourceEntry")


def test_a_new_required_parameter_is_caught_before_the_run_starts(monkeypatch):
    """The failure that motivated _check_call_shapes.

    brinss 0.1 gave build_catalog a required keyword-only ``source``. The symbol
    still existed, so the old existence-only check passed and the run died with
    a TypeError after the log header was already written.
    """
    monkeypatch.setattr(
        compat,
        "REQUIRED_CALL_KEYWORDS",
        (("brinss.datasets._catalog", "build_catalog", frozenset({"cache_dir", "force_refresh"})),),
    )
    with pytest.raises(LibraryIncompatibleError, match="parametro"):
        check_library()


def test_a_keyword_the_adapter_passes_disappearing_is_caught(monkeypatch):
    monkeypatch.setattr(
        compat,
        "REQUIRED_CALL_KEYWORDS",
        (("brinss.datasets._catalog", "build_catalog", frozenset({"parametro_inexistente"})),),
    )
    with pytest.raises(LibraryIncompatibleError, match="nao aceita mais"):
        check_library()


def test_the_adapter_reads_the_portal_and_never_the_mirror():
    """Reading the HF mirror to publish the HF mirror would be circular.

    The library defaults ``source`` to DataSource.HF, which is right for a
    reader and exactly wrong here: the manifest records the SHA256 of the file
    on dadosabertos.inss.gov.br, the source of record.
    """
    from brinss.datasets.enums import DataSource

    from br_publisher.library.adapter import CATALOG_SOURCE

    assert CATALOG_SOURCE is DataSource.INSS
