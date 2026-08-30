"""Fail at startup, not at month 40, when the library moved under us."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from importlib import metadata
from typing import Final

from br_publisher.errors import LibraryIncompatibleError

DISTRIBUTION: Final[str] = "brinss-public-datasets"
SUPPORTED_MAJOR_MINOR: Final[tuple[int, int]] = (0, 1)

# The (module, attribute) pairs the adapter dereferences. Listed rather than
# inferred so a failure names the missing symbol instead of surfacing as an
# AttributeError deep inside a run.
REQUIRED_SYMBOLS: Final[tuple[tuple[str, str], ...]] = (
    ("brinss.datasets._cache", "get_cache_root"),
    ("brinss.datasets._cache", "fetch_resource"),
    ("brinss.datasets._cache", "_load_registry"),
    ("brinss.datasets._cache", "_resource_filename"),
    ("brinss.datasets._catalog", "build_catalog"),
    ("brinss.datasets._catalog", "ResourceEntry"),
    ("brinss.datasets._catalog", "DatasetCatalog"),
    ("brinss.datasets._reading", "open_resource_chunks"),
    ("brinss.datasets._reading", "resource_encodings"),
    ("brinss.datasets._log", "LOGGER_NAME"),
    ("brinss.datasets._log", "get_logger"),
    ("brinss.datasets._log", "format_bytes"),
    ("brinss.datasets._log", "format_seconds"),
    ("brinss.datasets._families", "FAMILIES"),
)

REQUIRED_ENTRY_FIELDS: Final[frozenset[str]] = frozenset(
    {"period", "url", "resource_id", "resource_name", "package_slug", "format"}
)

# The keyword arguments the adapter passes to each callable. Existence is not
# enough: brinss 0.1 grew a required keyword-only ``source`` on build_catalog,
# and because the symbol was still there the run got all the way past the log
# header before dying with a TypeError. A call the adapter makes has to be
# checked as a *call*.
REQUIRED_CALL_KEYWORDS: Final[tuple[tuple[str, str, frozenset[str]], ...]] = (
    ("brinss.datasets._cache", "fetch_resource", frozenset({"family_key", "cache_dir"})),
    (
        "brinss.datasets._catalog",
        "build_catalog",
        frozenset({"cache_dir", "source", "force_refresh"}),
    ),
    (
        "brinss.datasets._reading",
        "open_resource_chunks",
        frozenset({"columns", "engine", "dtype", "encoding"}),
    ),
)


@dataclass(frozen=True, slots=True)
class _Probe:
    """A fixed ResourceEntry whose cached filename this tool knows by heart."""

    resource_id: str = "res-probe"
    resource_name: str = "Perfil das Unidades Junho 2024"
    url: str = "https://exemplo.test/arquivo.csv"
    expected_filename: str = "res-probe__Perfil das Unidades Junho 2024.csv"


def installed_version() -> str | None:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None


def check_library() -> None:
    """Four checks, cheapest first, before any work starts.

    1. The installed version sits inside the supported minor range.
    2. Every private symbol the adapter dereferences still exists.
    3. Every call the adapter makes still accepts the keywords it passes, and
       has gained no *new* required parameter the adapter does not know about.
    4. ``_resource_filename`` still produces the name this tool looks for on
       disk. That last one is the silent failure worth paying for: a changed
       naming rule does not raise, it just reports every cached month as missing
       and makes a --sample run quietly do nothing.

    Raises LibraryIncompatibleError, which main() turns into exit code 2.
    """
    _check_version()
    _check_symbols()
    _check_call_shapes()
    _check_filename_rule()


def _check_version() -> None:
    version = installed_version()
    if version is None:
        # An editable checkout without metadata still runs; the symbol checks
        # below are the ones that actually protect us.
        return
    parts = version.split(".")
    try:
        found = (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return
    if found != SUPPORTED_MAJOR_MINOR:
        expected = ".".join(str(part) for part in SUPPORTED_MAJOR_MINOR)
        raise LibraryIncompatibleError(
            f"{DISTRIBUTION} {version} esta fora da faixa suportada ({expected}.x). "
            "Revise br_publisher/library/adapter.py antes de prosseguir."
        )


def _check_symbols() -> None:
    for module_name, attribute in REQUIRED_SYMBOLS:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise LibraryIncompatibleError(
                f"{DISTRIBUTION} nao expoe mais o modulo '{module_name}': {exc}"
            ) from exc
        if not hasattr(module, attribute):
            raise LibraryIncompatibleError(
                f"{DISTRIBUTION} nao expoe mais '{module_name}.{attribute}'; "
                "a camada anticorrupcao precisa ser revista."
            )

    entry = importlib.import_module("brinss.datasets._catalog").ResourceEntry
    missing = REQUIRED_ENTRY_FIELDS - set(getattr(entry, "__dataclass_fields__", {}))
    if missing:
        raise LibraryIncompatibleError(
            f"{DISTRIBUTION}: ResourceEntry perdeu o(s) campo(s) {', '.join(sorted(missing))}."
        )


def _check_call_shapes() -> None:
    """Verify each call the adapter makes, as a call rather than as a name.

    Two ways a signature can break us, and both have to be caught here:

    * a keyword the adapter passes disappears -- a TypeError at the call site;
    * a *new required* parameter appears. That is what brinss 0.1 did to
      ``build_catalog`` with ``source``, and because the symbol still existed
      the run got past the log header before dying. Worse, ``source`` defaults
      to the Hugging Face mirror on the reading side: had it been optional, this
      tool would have silently started building the mirror out of the mirror.
    """
    for module_name, attribute, keywords in REQUIRED_CALL_KEYWORDS:
        function = getattr(importlib.import_module(module_name), attribute)
        try:
            parameters = inspect.signature(function).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins have no signature
            continue

        missing = keywords - set(parameters)
        if missing:
            raise LibraryIncompatibleError(
                f"{DISTRIBUTION}: {module_name}.{attribute} nao aceita mais "
                f"{', '.join(sorted(missing))}; revise a camada anticorrupcao."
            )

        unknown_required = {
            name
            for name, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            and name not in keywords
            and name not in _POSITIONAL_ARGUMENTS.get((module_name, attribute), frozenset())
        }
        if unknown_required:
            raise LibraryIncompatibleError(
                f"{DISTRIBUTION}: {module_name}.{attribute} ganhou o(s) parametro(s) obrigatorio(s) "
                f"{', '.join(sorted(unknown_required))}, que a camada anticorrupcao nao passa."
            )


# What the adapter passes positionally, and therefore does not name above.
_POSITIONAL_ARGUMENTS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("brinss.datasets._cache", "fetch_resource"): frozenset({"entry"}),
    ("brinss.datasets._catalog", "build_catalog"): frozenset({"family"}),
    ("brinss.datasets._reading", "open_resource_chunks"): frozenset({"path", "entry"}),
}


def _check_filename_rule() -> None:
    catalog = importlib.import_module("brinss.datasets._catalog")
    cache = importlib.import_module("brinss.datasets._cache")
    import pandas as pd

    probe = _Probe()
    entry = catalog.ResourceEntry(
        period=pd.Period("2024-06", freq="M"),
        url=probe.url,
        resource_id=probe.resource_id,
        resource_name=probe.resource_name,
        package_slug="slug",
        format="CSV",
    )
    produced = cache._resource_filename(entry)
    if produced != probe.expected_filename:
        raise LibraryIncompatibleError(
            f"{DISTRIBUTION}: a regra de nome do arquivo em cache mudou "
            f"(esperado {probe.expected_filename!r}, obtido {produced!r}). "
            "Sem corrigir isso, todo mes em cache seria reportado como ausente."
        )
