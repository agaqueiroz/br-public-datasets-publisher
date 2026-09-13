# br-public-datasets-publisher

## AVISO LEGAL

Este é um projeto pessoal, não oficial, e para fins de estudos, sem garantias de atualização e tem com fonte única, sem alterações, os Portais de Dados Abertos do Governo Federal.

## Objetivo

Converte os datasets abertos do INSS para Parquet e republicá-los no Hugging Face.

Consome a biblioteca [brinss-public-datasets](https://github.com/agaqueiroz/brinss-public-datasets)
para catalogar, baixar e ler os arquivos do portal, e cuida do resto: conversão em
streaming, cache local dos Parquet, manifesto de procedência e commits em lote no Hub.

```bash
uv run publish-to-hf              # dry run
uv run publish-to-hf --sample     # converte o que ja esta em cache, sem tocar no Hub
uv run publish-to-hf --push       # publica de fato
```

Publicar exige um token de escrita, em `HF_TOKEN` ou gravado por `hf auth login`.

## Rodadas dirigidas

Sem `--familia` e `--periodo` uma rodada percorre todas as famílias e todos os
meses do catálogo — o que, junto com `--force`, significa reconverter e reenviar
tudo. Os dois aceitam repetição e recortam o trabalho:

```bash
uv run publish-to-hf --push --force --periodo 2026-07 --familia beneficios_mantidos_ativos --familia beneficios_mantidos_cessados --familia beneficios_mantidos_suspensos
```

`--force` é o que torna a republicação possível: um mês cujo SHA da fonte e cuja
receita de conversão não mudaram é classificado como `inalterado` e pulado. Ele
também ignora o Parquet já convertido em `tmp/`, então não é preciso limpar o
cache à mão.

Vale ensaiar antes com os mesmos argumentos menos o `--push`: a saída traz uma
linha `PLAN data/<familia>/<mes>.parquet (forcado)` por mês que seria enviado. O
ensaio não converte, então os apontamentos abaixo não aparecem nele.

Um mês grande leva tempo. `beneficios_mantidos_cessados` são 30 GB de CSV e mais
de cem milhões de linhas: dezenas de minutos só de conversão, antes do upload.

## Apontamentos

O resumo de cada rodada traz, ao lado de `falhas`, uma contagem de
`apontamentos` — o que não impediu a publicação mas merece um olhar. Hoje há um:
a contagem de colunas de um mês difere da do mês anterior já publicado.

```
  aponta   beneficios_mantidos_ativos/2026-07: queda de 18 para 2 colunas; confira antes de publicar
```

Mudança de esquema na origem é comum e legítima — `beneficios_emitidos` passou
de 14 para 15 colunas, `perfil_unidades` varia bem mais que isso — então isso
relata em vez de recusar. A recusa fica com o leitor da biblioteca, que
interrompe o mês quando um CSV não pode ser lido sem perda de colunas: é o caso
de um arquivo cujo cabeçalho e cujos registros usam delimitadores diferentes,
que o pandas leria descartando as colunas excedentes em silêncio. Aí o mês entra
em `falhas` e nada é enviado.

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
