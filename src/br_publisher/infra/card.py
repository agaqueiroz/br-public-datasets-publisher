"""The dataset card, with one viewer config per family.

Without the ``configs`` block the Hub cannot tell eight unrelated datasets apart
and the preview shows nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from br_publisher.library.models import Family


@dataclass(frozen=True, slots=True)
class DatasetCardRenderer:
    families: Mapping[str, Family]

    def render(self, family_keys: Sequence[str]) -> str:
        lines = ["---", "configs:"]
        for key in family_keys:
            lines += [
                f"- config_name: {key}",
                "  data_files:",
                "  - split: train",
                f"    path: data/{key}/*.parquet",
            ]
        lines += [
            "language:",
            "- pt",
            "license: mit",
            "---",
            "",
            "# Datasets abertos do INSS, em Parquet",
            "",
            "Conversão dos datasets publicados em",
            "[dadosabertos.inss.gov.br](https://dadosabertos.inss.gov.br) para Parquet,",
            "gerada com a biblioteca",
            "[brinss-public-datasets](https://github.com/agaqueiroz/brinss-public-datasets).",
            "",
            "Um arquivo por mês, por família: `data/<família>/<AAAA-MM>.parquet`.",
            "",
            "## Tipos das colunas",
            "",
            "Todas as colunas de dados são **texto**. Os códigos do INSS (CID, CBO, CNAE,",
            "código IBGE de município) têm zeros à esquerda que a inferência de tipos",
            'destruiria — `"01234"` viraria `1234`. A coluna `periodo_referencia` é',
            "adicionada pela conversão e traz o mês de referência como `AAAA-MM`.",
            "",
            "## Famílias",
            "",
            "| Config | Descrição |",
            "| --- | --- |",
        ]
        lines += [f"| `{key}` | {self._title(key)} |" for key in family_keys]
        lines += [
            "",
            "## Procedência",
            "",
            "O `manifest.json` na raiz registra, para cada arquivo, o SHA256 do arquivo",
            "de origem no portal do INSS de que ele foi gerado, além do número de linhas",
            "e da receita de conversão usada. Entradas com `adopted: true` foram",
            "reconciliadas depois do envio: a origem foi conferida, mas a contagem de",
            "linhas daquele arquivo não foi recalculada.",
            "",
            "<!-- Gerado por br-public-datasets-publisher. Edições manuais são",
            "     preservadas: o card só é reescrito com --update-card. -->",
            "",
        ]
        return "\n".join(lines)

    def _title(self, key: str) -> str:
        family = self.families.get(key)
        return family.title if family is not None else key
