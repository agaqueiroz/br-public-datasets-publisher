# TODO

Pendências conhecidas, em ordem aproximada de valor. Marque `- [x]` ao concluir. O
desenho e as decisões estão em [PLAN.md](PLAN.md).

## Adicionar os conjuntos de pessoal e de requerimentos

Cinco pacotes do portal ainda fora do Hub. O publicador só enxerga o que estiver em
`FAMILIES` na biblioteca irmã, então a maior parte do código muda **lá**
(`libraries/brinss-public-datasets/src/brinss/datasets/_families.py`). Aqui mudam só
dependência, testes e documentação.

| Chave (`--familia`) | Conjunto no portal | Pacote CKAN | Meses no portal |
| --- | --- | --- | --- |
| `pessoal_ativo_consolidado` | Quadro de Pessoal em atividade consolidado | `quadro-de-pessoal-em-atividade-consolidado` | 2023-06 a 2026-08 (39) |
| `ocupantes_funcoes_cargos` | Ocupantes de funções e cargos | `ocupantes-de-funcoes-e-cargos` | 2023-06 a 2026-08 (39) |
| `pessoal_sem_identificacao` | Dados do quadro de Pessoal sem identificação (dados sociais anonimizados) | `dados-do-quadro-de-pessoal-sem-identificacao` | 2023-06 a 2026-08 (39) |
| `requerimentos_solicitados` | Dados quantitativos de requerimentos administrativos solicitados | `dados-de-requerimentos-administrativos-solicitados-plano-de-dados-abertos-jun-2023-a-jun-2025` | 2023-06 a 2026-07 (38) |
| `requerimentos_pendentes` | Dados quantitativos de requerimentos administrativos pendentes de análise | `dados-de-requerimentos-administrativos-pendentes-plano-de-dados-abertos-jun-2023-a-jun-2025` | 2023-08 a 2026-07 (34; faltam 2024-12 e 2025-01) |

Peculiaridades já conferidas no CKAN (em 2026-09-13), e por que não quebram nada:

- **XLSX nos primeiros meses, CSV depois**: até 2024-08 nos três de pessoal, até 2025-06
  nos dois de requerimentos. O campo `format` do CKAN erra em vários meses:
  `pessoal_ativo_consolidado` 2024-09/10/12 e 2025-01/02 dizem XLSX e são CSV, e
  `requerimentos_*` 2023-12 diz CSV e é XLSX. A leitura decide pelos bytes
  (`_reading._open_source`), não pelo rótulo, e o nome em cache usa a extensão da URL.
- **O período vem do nome do recurso** ("atualização junho/2023", "Abril 2026",
  "Jul/2025"), num formato que `parse_periodo_from_name` já entende.
  `requerimentos_solicitados` 2024-06/07 e `requerimentos_pendentes` 2024-07 não têm
  AAAAMM no nome do arquivo (`PDA_ITEM_9_CRIA_AC+_062024.xlsx`), o que só importaria numa
  colisão de período.
- **Arquivos nominais**: `pessoal_ativo_consolidado` e `ocupantes_funcoes_cargos`
  (`..._Nominal_AAAAMM`) trazem nome de servidor. São públicos no portal, mas vale ter
  isso em mente ao republicar.

### Decisão em aberto: `requerimentos_solicitados` 2026-04

O INSS publica dois pacotes irmãos:

- **Solicitados** (item 9 do PDA): quantos requerimentos entraram no mês. Arquivos
  `PDA_ITEM_9_CRIA_AAAAMM.csv`, na pasta `…/requerimentos administrativos solicitados/`.
- **Pendentes de análise** (item 10): o estoque ainda sem análise. Arquivos
  `PDA_ITEM_10_PEND_AAAAMM.csv`, na pasta `…/pendentes de análise/`.

No pacote dos solicitados, o recurso "Abril 2026"
(`eed2e037-fc6b-4e2b-8a5e-041fe79b4e51`) aponta para o arquivo dos pendentes:

| Recurso no CKAN | Link cadastrado | Tamanho |
| --- | --- | --- |
| Solicitados, Março 2026 | `…solicitados/PDA_ITEM_9_CRIA_202603.csv` | ~28 MB |
| **Solicitados, Abril 2026** | **`…pendentes de análise/PDA_ITEM_10_PEND_202604.csv`** | **107,8 MB** |
| Solicitados, Maio 2026 | `…solicitados/PDA_ITEM_9_CRIA_202605.csv` | 28,1 MB |
| Pendentes, Abril 2026 | `…pendentes de análise/PDA_ITEM_10_PEND_202604.csv` | 107,8 MB |

O arquivo certo existe no bucket (`…solicitados/PDA_ITEM_9_CRIA_202604.csv`, 27,9 MB,
conferido por HEAD em 2026-09-13), mas não está cadastrado no CKAN. Publicado como está,
`data/requerimentos_solicitados/2026-04.parquet` seria uma cópia dos pendentes com outro
nome, e nada no caminho falharia.

- [ ] Decidir entre:
  - **Pular e avisar**: a biblioteca ignora um recurso cujo link cai na pasta ou no
    arquivo de outro conjunto, e emite um aviso. O mês entra sozinho quando o INSS
    corrigir o cadastro.
  - **Usar o arquivo certo do bucket**: troca pontual da URL desse recurso. O dado fica
    correto, mas a origem registrada no manifesto passa a ser uma URL que o CKAN não lista.
  - **Publicar como está** (regra "fonte única, sem alterações") e registrar só o
    apontamento.
  - **Pular só nesta carga**, sem mudar código. Uma rodada futura sem `--periodo` o
    publicaria errado.
- [ ] Implementar a opção escolhida.
- [ ] (Opcional) Avisar o INSS, pelo canal do portal, sobre o link trocado.

### 1. Pré-requisitos

- [x] PR #1 (apontamento de contagem de colunas) mergeado em `main`.
- [ ] Commitar e abrir o PR da correção de delimitadores na biblioteca. O trabalho está
      pronto e não commitado no diretório de trabalho de lá (ver o `TODO.md` da
      biblioteca). Os conjuntos novos são CSV nos meses recentes.
- [ ] Consertar o caminho da biblioteca: `pyproject.toml` (`[tool.uv.sources]`) e
      `uv.lock` apontam para `../../libraries/brinss_public_datasets`, mas o diretório é
      `brinss-public-datasets`. O `.venv` aponta para um checkout antigo em
      `Workspaces\Claude\libraries\...`, que não existe mais, e hoje `import brinss` falha.
      Corrigir o caminho, rodar `uv sync` e ajustar o diagrama de pastas na seção
      "Desenvolvimento" do README.
- [ ] Criar uma branch nova a partir de `main`, neste repositório e na biblioteca.

### 2. Código

- [ ] Biblioteca: adicionar as 5 entradas em `FAMILIES`
      (`src/brinss/datasets/_families.py`), com as chaves e slugs da tabela acima.
- [ ] Biblioteca: se houver loaders nomeados (`load_beneficios_*` em
      `datasets/__init__.py`), adicionar os equivalentes e atualizar README e docs.
- [ ] Biblioteca: testes do catálogo com um `package_show` gravado (fixture) de cada
      pacote, cobrindo o formato trocado e o nome "atualização mês/ano".
- [ ] Publicador: conferir que `tests/infra/test_card.py`,
      `tests/library/test_adapter.py` e `tests/library/test_compat.py` seguem verdes com as
      famílias novas. O card e o `--familia` derivam de `FAMILIES`.
- [ ] Publicador: citar os conjuntos novos no README, onde a lista de famílias aparecer.
- [ ] `uv run pytest` e `uv run ruff check .` verdes nos dois repositórios.

### 3. Validação manual: um mês por conjunto

Meses escolhidos para cobrir os casos diferentes:

| Família | Mês | Por quê |
| --- | --- | --- |
| `pessoal_ativo_consolidado` | 2024-12 | CKAN diz XLSX, o arquivo é CSV |
| `ocupantes_funcoes_cargos` | 2024-06 | XLSX de fato |
| `pessoal_sem_identificacao` | 2026-08 | mês mais recente, CSV |
| `requerimentos_solicitados` | 2023-12 | CKAN diz CSV, o arquivo é XLSX |
| `requerimentos_pendentes` | 2024-07 | arquivo sem AAAAMM no nome (`PEND_072024`) |

Roteiro por família (troque `F` pela família e `P` pelo mês):

1. **Ensaio**, sem baixar nem enviar. Espere
   `PLAN data/F/P.parquet (fonte ainda nao baixada)` e nenhum aviso de "periodo
   reivindicado por mais de um recurso".

   ```bash
   uv run publish-to-hf --familia F --periodo P
   ```

2. **Baixar e ler pela biblioteca**, para ver colunas, linhas e cabeçalho. Numa planilha
   com banner, confira que não vieram colunas `Unnamed: N`.

   ```bash
   uv run python -c "from brinss.datasets import load_dataset as l; df = l('F', periodo='P', source='inss'); print(df.shape); print(df.dtypes); print(df.head())"
   ```

3. **Converter do cache**, sem tocar no Hub. Gera `tmp/data/F/P.parquet`, e o log traz
   as linhas e o dialeto CSV escolhido.

   ```bash
   uv run publish-to-hf --sample --familia F --periodo P
   ```

4. **Conferir o Parquet**: as colunas batem com as do passo 2, mais `periodo_referencia`.

   ```bash
   uv run python -c "import pyarrow.parquet as pq; t = pq.read_table('tmp/data/F/P.parquet'); print(t.num_rows, t.schema)"
   ```

5. **Publicar**. O `--update-card` põe a família nova no bloco `configs:` do card. Sem
   ele, o viewer do Hub não mostra a família.

   ```bash
   uv run publish-to-hf --push --update-card --familia F --periodo P
   ```

6. **Conferir no Hub** (`agaqueiroz/brinss-public-datasets`): o arquivo em
   `data/F/P.parquet`, a entrada `F/P` no `manifest.json` e a config `F` no viewer.

- [ ] `pessoal_ativo_consolidado` 2024-12
- [ ] `ocupantes_funcoes_cargos` 2024-06
- [ ] `pessoal_sem_identificacao` 2026-08
- [ ] `requerimentos_solicitados` 2023-12
- [ ] `requerimentos_pendentes` 2024-07

### 4. Carga dos demais meses (automática, após a validação)

- [ ] Ensaio geral das 5 famílias: conferir as linhas `PLAN` e a ausência de avisos de
      catálogo.
- [ ] `--push` das 5 famílias, sem `--force`: os meses validados saem como `inalterado`.
      Respeitar a decisão sobre `requerimentos_solicitados` 2026-04.
- [ ] Revisar `falhas` e `apontamentos` no resumo. Uma mudança de colunas na passagem de
      XLSX para CSV é esperada, mas confira cada queda grande.
- [ ] Conferir no Hub a contagem de arquivos por família contra a tabela do topo.
- [ ] Marcar esta seção como concluída e mover o que sobrar para "Outras pendências".

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

- [ ] Fazer a troca.

Ao fazer, verificar:

- [ ] `DatasetCardData` preserva a chave `configs` na serialização (é parte da
      especificação do card de dataset, mas confirmar na versão instalada);
- [ ] a ordem das famílias continua estável, para o diff do card não virar ruído;
- [ ] o teste passa a fazer `yaml.safe_load` do front matter e a afirmar a estrutura
      desserializada, em vez de comparar linhas — é isso que a troca compra;
- [ ] o `test_acceptance_network.py::test_every_published_family_is_a_readable_config`
      continua verde contra um repositório descartável.

## Outras pendências

- [ ] **Limpeza na biblioteca irmã** (`libraries/brinss-public-datasets`): remover
      `scripts/publish_to_hf.py`, `tests/test_publish_to_hf.py`, o grupo de
      dependências `publish`, `pythonpath = ["scripts"]` e `huggingface-hub`/
      `pyarrow` do grupo `dev`; reescrever a seção "Publicação em Parquet no Hugging
      Face" do README como ponteiro para este repositório. Adicionar
      `line-length = 120` em `[tool.ruff]` lá, para travar o estilo que já existe.
- [ ] **`logging.getLogger("brinss.publish")` está repetido em três módulos** — `infra/build_cache.py`,
      `infra/hub.py` e `infra/parquet.py` — em vez de importar `logging_setup.LOGGER_NAME`. O nome está
      correto (é o namespace da biblioteca, filho de `brinss`, e não muda com a renomeação deste
      projeto), mas a duplicação é frágil: se o namespace mudar, os três continuam escrevendo num logger
      sem handler, silenciosamente. Consertar importando a constante — atentando para a ordem de import,
      já que `logging_setup` importa de `library`.
- [ ] **Promover a API privada de `brinss`** aos símbolos listados em
      [docs/upstream-api.md](docs/upstream-api.md), e então apagar
      `library/compat.py` e simplificar `library/adapter.py`.
- [ ] **Publicar `brinss-public-datasets` no PyPI** e remover a tabela
      `[tool.uv.sources]` do `pyproject.toml`.
- [ ] Retry/backoff em 5xx e rate limiting do Hub.
- [ ] `--resume-from` explícito (hoje o índice de build já retoma sozinho).
- [ ] `schema_version = 2` do manifesto, se e quando a receita de conversão mudar.
