"""The flags, verbatim, and nothing else.

The names and the Portuguese help strings are the user-facing contract and are
carried over unchanged from the script this application replaces.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .domain.recipe import DEFAULT_COMMIT_SIZE, DEFAULT_REPO_ID

DEFAULT_PARQUET_DIR = Path("tmp")
DEFAULT_LOG_DIR = Path("logs")


def build_parser(known_families: Sequence[str] | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish-to-hf",
        description="Converte os datasets do INSS para Parquet e publica no Hugging Face.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=DEFAULT_REPO_ID, help=f"repositorio no Hub (padrao: {DEFAULT_REPO_ID})")
    parser.add_argument(
        "--push",
        action="store_true",
        help="publica de fato; sem esta flag o script so mostra o plano (dry run)",
    )
    parser.add_argument(
        "--familia",
        action="append",
        choices=sorted(known_families) if known_families else None,
        help="restringe a uma familia (repetivel; padrao: todas)",
    )
    parser.add_argument(
        "--periodo",
        action="append",
        help="restringe a um mes AAAA-MM (repetivel; padrao: todos do catalogo)",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="converte para parquet so o que ja esta em cache, gravando localmente e sem tocar no Hub",
    )
    parser.add_argument(
        "--parquet-dir",
        "--sample-dir",
        dest="parquet_dir",
        default=str(DEFAULT_PARQUET_DIR),
        help=f"cache local dos parquet convertidos (padrao: {DEFAULT_PARQUET_DIR})",
    )
    parser.add_argument(
        "--prune-parquet",
        action="store_true",
        help="apaga do cache local os parquet que o manifesto ja confirma publicados",
    )
    parser.add_argument(
        "--reconciliar",
        action="store_true",
        help="adota no manifesto os arquivos ja publicados que nao constam nele, sem reenviar",
    )
    parser.add_argument("--force", action="store_true", help="reenvia mesmo com o checksum inalterado")
    parser.add_argument("--force-refresh", action="store_true", help="ignora o cache do catalogo de periodos")
    parser.add_argument("--limite", type=int, help="para depois de N arquivos (util para uma primeira carga)")
    parser.add_argument(
        "--commit-size",
        type=int,
        default=DEFAULT_COMMIT_SIZE,
        help=f"quantos arquivos agrupar por commit (padrao: {DEFAULT_COMMIT_SIZE})",
    )
    parser.add_argument("--cache-dir", help="diretorio de cache dos downloads")
    parser.add_argument("--create-repo", action="store_true", help="cria o repositorio no Hub se nao existir")
    parser.add_argument(
        "--update-card",
        action="store_true",
        help="reescreve o README.md do dataset no Hub (por padrao ele so e criado se nao existir)",
    )
    parser.add_argument(
        "--no-hub",
        action="store_true",
        help="dry run sem consultar o Hub: trata todo periodo como novo (incompativel com --push)",
    )
    parser.add_argument(
        "--log-dir", default=str(DEFAULT_LOG_DIR), help=f"onde gravar o log (padrao: {DEFAULT_LOG_DIR})"
    )
    parser.add_argument("--log-file", help="caminho exato do arquivo de log (sobrepoe --log-dir)")
    parser.add_argument("--no-log-file", action="store_true", help="nao grava log em arquivo")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra no console tambem o nivel DEBUG")
    return parser
