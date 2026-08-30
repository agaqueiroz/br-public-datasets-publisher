"""The guard the whole design rests on.

An AST walk, not a grep and not a ruff rule alone: ruff's banned-api catches the
dotted form ``import brinss.datasets._cache`` but not ``from brinss.datasets
import _cache``, which is exactly the form the old script used.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "br_publisher"

# The one module allowed to know brinss internals, plus the self-check that
# names them. See br_publisher/library/adapter.py.
ALLOWED = {SRC / "library" / "adapter.py", SRC / "library" / "compat.py"}


def _private_brinss_imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not module.startswith("brinss"):
                continue
            if any(part.startswith("_") for part in module.split(".")):
                found.add(module)
            for alias in node.names:
                if alias.name.startswith("_"):
                    found.add(f"{module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("brinss") and any(
                    part.startswith("_") for part in alias.name.split(".")
                ):
                    found.add(alias.name)
    return found


def _modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_the_source_tree_is_not_empty():
    assert _modules()


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(SRC)))
def test_only_the_adapter_imports_the_private_api_of_brinss(path):
    if path in ALLOWED:
        return
    offending = _private_brinss_imports(ast.parse(path.read_text(encoding="utf-8")))
    assert offending == set(), (
        f"{path.relative_to(SRC)} importa a API privada de brinss ({sorted(offending)}). "
        "Passe pela camada anticorrupcao em br_publisher.library."
    )


def test_the_adapter_really_does_import_the_private_api():
    """If this ever passes empty, the exemption above stopped meaning anything."""
    adapter = SRC / "library" / "adapter.py"
    assert _private_brinss_imports(ast.parse(adapter.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(SRC)))
def test_datasets_is_never_imported_from_src(path):
    """`datasets` is a dev dependency for the network acceptance test only.

    Its push_to_hub owns the shard naming and replaces a whole config, which is
    incompatible with the one-file-per-month layout this tool maintains.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "datasets":
            pytest.fail(f"{path.relative_to(SRC)} importa `datasets`")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "datasets":
                    pytest.fail(f"{path.relative_to(SRC)} importa `datasets`")


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(SRC)))
def test_huggingface_hub_is_confined_to_the_hub_module(path):
    """Keeping the SDK in one module is what lets the commit tests use a double."""
    if path.name == "hub.py":
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        module = ""
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
        elif isinstance(node, ast.Import):
            module = node.names[0].name
        if module.split(".")[0] == "huggingface_hub":
            pytest.fail(f"{path.relative_to(SRC)} importa huggingface_hub fora de infra/hub.py")


def test_the_token_is_never_read_from_the_environment_directly():
    """Reading os.environ alone rejected a user authenticated by `hf auth login`.

    get_token() also walks OIDC, HUGGING_FACE_HUB_TOKEN, the token file and
    Colab secrets, so the environment is only one of five sources.
    """
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        assert "HF_TOKEN" not in text or path.name in {"hub.py", "main.py"}, path
        assert 'environ["HF_TOKEN"]' not in text
        assert "environ.get(\"HF_TOKEN\")" not in text
