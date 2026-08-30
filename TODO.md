# TODO

Pendências conhecidas, em ordem aproximada de valor. O desenho e as decisões
estão em [PLAN.md](PLAN.md).

## Validar o YAML do card com `huggingface_hub.DatasetCard`

`DatasetCardRenderer.render` monta o bloco `configs:` do dataset card com
`str.join` sobre uma lista de linhas
([`src/br_publisher/infra/card.py`](src/br_publisher/infra/card.py)).
Funciona, mas nada valida o YAML resultante: um erro de indentação ou uma chave
com nome errado só aparece como um viewer vazio no Hub, e o teste atual
(`tests/infra/test_card.py`) confere apenas a forma das linhas que nós mesmos
escrevemos — ele passaria com um YAML sintaticamente quebrado.

Trocar por `huggingface_hub.DatasetCard` / `DatasetCardData`, que já é
dependência do projeto (nenhuma dependência nova é necessária — e, em
particular, **não** é motivo para trazer a biblioteca `datasets`; ver a seção
"Avaliação: a biblioteca `datasets` simplifica isto?" no PLAN.md). O corpo em
Markdown continua sendo nosso; o que muda é que o front matter passa a ser
serializado por quem define o formato.

Esboço:

```python
from huggingface_hub import DatasetCard, DatasetCardData

card = DatasetCard.from_template(
    card_data=DatasetCardData(
        configs=[
            {"config_name": key, "data_files": [{"split": "train", "path": f"data/{key}/*.parquet"}]}
            for key in family_keys
        ],
        language=["pt"],
        license="mit",
    ),
    template_str=BODY,
)
```

Ao fazer, verificar:

- `DatasetCardData` preserva a chave `configs` na serialização (é parte da
  especificação do card de dataset, mas confirmar na versão instalada);
- a ordem das famílias continua estável, para o diff do card não virar ruído;
- o teste passa a fazer `yaml.safe_load` do front matter e a afirmar a estrutura
  desserializada, em vez de comparar linhas — é isso que a troca compra;
- o `test_acceptance_network.py::test_every_published_family_is_a_readable_config`
  continua verde contra um repositório descartável.

## Outras pendências

- **Limpeza na biblioteca irmã** (`libraries/brinss_public_datasets`): remover
  `scripts/publish_to_hf.py`, `tests/test_publish_to_hf.py`, o grupo de
  dependências `publish`, `pythonpath = ["scripts"]` e `huggingface-hub`/
  `pyarrow` do grupo `dev`; reescrever a seção "Publicação em Parquet no Hugging
  Face" do README como ponteiro para este repositório. Adicionar
  `line-length = 120` em `[tool.ruff]` lá, para travar o estilo que já existe.
- **`logging.getLogger("brinss.publish")` está repetido em três módulos** — `infra/build_cache.py`,
  `infra/hub.py` e `infra/parquet.py` — em vez de importar `logging_setup.LOGGER_NAME`. O nome está
  correto (é o namespace da biblioteca, filho de `brinss`, e não muda com a renomeação deste
  projeto), mas a duplicação é frágil: se o namespace mudar, os três continuam escrevendo num logger
  sem handler, silenciosamente. Consertar importando a constante — atentando para a ordem de import,
  já que `logging_setup` importa de `library`.
- **Promover a API privada de `brinss`** aos símbolos listados em
  [docs/upstream-api.md](docs/upstream-api.md), e então apagar
  `library/compat.py` e simplificar `library/adapter.py`.
- **Publicar `brinss-public-datasets` no PyPI** e remover a tabela
  `[tool.uv.sources]` do `pyproject.toml`.
- Retry/backoff em 5xx e rate limiting do Hub.
- `--resume-from` explícito (hoje o índice de build já retoma sozinho).
- `schema_version = 2` do manifesto, se e quando a receita de conversão mudar.
