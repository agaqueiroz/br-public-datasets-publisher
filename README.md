# br-public-datasets-publisher

Converte os datasets abertos do INSS para Parquet e publica no Hugging Face.

Consome a biblioteca [brinss-public-datasets](https://github.com/agaqueiroz/brinss-public-datasets)
para catalogar, baixar e ler os arquivos do portal, e cuida do resto: conversão em
streaming, cache local dos Parquet, manifesto de procedência e commits em lote no Hub.

```bash
uv run publish-to-hf              # dry run
uv run publish-to-hf --sample     # converte o que ja esta em cache, sem tocar no Hub
uv run publish-to-hf --push       # publica de fato
```

Publicar exige um token de escrita, em `HF_TOKEN` ou gravado por `hf auth login`.

## Desenvolvimento

Enquanto `brinss-public-datasets` não está no PyPI, o `pyproject.toml` a resolve
por caminho relativo (`[tool.uv.sources]`), então os dois repositórios precisam
ser clonados lado a lado:

```
<raiz>/
  applications/br_public_datasets_publisher/   # este repositório
  libraries/brinss_public_datasets/            # github.com/agaqueiroz/brinss-public-datasets
```

```bash
uv sync           # instala o projeto e o grupo dev
uv run pytest     # testes (os marcados `network` ficam de fora por padrão)
uv run ruff check .
```

Veja `PLAN.md` para o desenho e `TODO.md` para o que ficou pendente.
