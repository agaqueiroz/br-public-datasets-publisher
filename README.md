# br-public-datasets-publisher

## AVISO LEGAL

Este é um projeto pessoal, não oficial, e para fins de estudos, sem garantias de atualização e tem com fonte única, sem alterações, os Portais de Dados Abertos do Governo Federal.

## Objetivo

Converte os datasets abertos do INSS para Parquet e republicá-los no Hugging Face.

Consome a biblioteca [brinss-public-datasets](https://github.com/agaqueiroz/brinss-public-datasets)
para catalogar, baixar e ler os arquivos do portal, e cuida do resto: conversão em
streaming, cache local dos Parquet, manifesto de procedência e commits em lote no Hub.

## Como usar?

### Modos de execução

```bash
uv run publish-to-hf              # dry run
uv run publish-to-hf --sample     # converte o que ja esta em cache, sem tocar no Hub
uv run publish-to-hf --push       # publica de fato
```

Publicar exige um token de escrita, em `HF_TOKEN` ou gravado por `hf auth login`.

### Passo a passo: publicar um mês de um conjunto

O roteiro abaixo publica **um mês de um conjunto** e confere cada etapa antes de
enviar. É o jeito de validar um conjunto novo antes de carregar os demais meses
dele. Os comandos estão em PowerShell.

#### Preparação (uma vez)

1. **Conferir que a biblioteca é importada da pasta certa.** O caminho impresso deve
   terminar em `libraries\brinss-public-datasets\src\brinss\datasets\__init__.py`.

   ```powershell
   uv run python -c "import brinss.datasets as d; print(d.__file__)"
   ```

   Se falhar com `ModuleNotFoundError`, ou apontar para outra pasta, corrija o caminho
   em `[tool.uv.sources]` no `pyproject.toml` e reinstale:

   ```toml
   brinss-public-datasets = { path = "../../libraries/brinss-public-datasets", editable = true }
   ```

   ```powershell
   uv sync
   ```

2. **Cadastrar o conjunto na biblioteca.** O publicador só enxerga as famílias de
   `FAMILIES`, em `libraries/brinss-public-datasets/src/brinss/datasets/_families.py`.
   Uma entrada por conjunto, com a chave usada em `--familia` e o slug do pacote no
   CKAN:

   ```python
       "pessoal_ativo_consolidado": DatasetFamily(
           key="pessoal_ativo_consolidado",
           title="Quadro de Pessoal em atividade consolidado",
           slugs=("quadro-de-pessoal-em-atividade-consolidado",),
       ),
   ```

   | Chave (`--familia`) | Conjunto no portal | Slug no CKAN |
   | --- | --- | --- |
   | `pessoal_ativo_consolidado` | Quadro de Pessoal em atividade consolidado | `quadro-de-pessoal-em-atividade-consolidado` |
   | `ocupantes_funcoes_cargos` | Ocupantes de funções e cargos | `ocupantes-de-funcoes-e-cargos` |
   | `pessoal_sem_identificacao` | Dados do quadro de Pessoal sem identificação | `dados-do-quadro-de-pessoal-sem-identificacao` |
   | `requerimentos_solicitados` | Dados quantitativos de requerimentos administrativos solicitados | `dados-de-requerimentos-administrativos-solicitados-plano-de-dados-abertos-jun-2023-a-jun-2025` |
   | `requerimentos_pendentes` | Dados quantitativos de requerimentos administrativos pendentes de análise | `dados-de-requerimentos-administrativos-pendentes-plano-de-dados-abertos-jun-2023-a-jun-2025` |

   A instalação é editável, então não é preciso rodar `uv sync` de novo. Confirme que a
   família aparece entre as opções de `--familia`:

   ```powershell
   uv run publish-to-hf --help
   ```

3. **Conferir o token do Hugging Face.** Se não estiver logado, rode
   `uv run hf auth login` e cole um token com permissão de escrita.

   ```powershell
   uv run hf auth whoami
   ```

#### Um mês por conjunto

Defina a família e o mês e siga os passos 1 a 6. Os meses sugeridos abaixo cobrem, cada
um, um caso diferente do portal:

| Conjunto | Variáveis | Caso que o mês testa |
| --- | --- | --- |
| Quadro de Pessoal em atividade consolidado | `$F="pessoal_ativo_consolidado"; $P="2024-12"` | o CKAN diz XLSX, mas o arquivo é CSV |
| Ocupantes de funções e cargos | `$F="ocupantes_funcoes_cargos"; $P="2024-06"` | XLSX de fato |
| Dados do quadro de Pessoal sem identificação | `$F="pessoal_sem_identificacao"; $P="2026-08"` | mês mais recente, CSV |
| Requerimentos administrativos solicitados | `$F="requerimentos_solicitados"; $P="2023-12"` | o CKAN diz CSV, mas o arquivo é XLSX |
| Requerimentos administrativos pendentes de análise | `$F="requerimentos_pendentes"; $P="2024-07"` | nome do arquivo sem ano e mês (`PEND_072024`) |

```powershell
$F="pessoal_ativo_consolidado"; $P="2024-12"
```

1. **Ensaio**, sem baixar nem enviar.

   ```powershell
   uv run publish-to-hf --familia $F --periodo $P
   ```

   Espere a linha `PLAN  data/<familia>/<mes>.parquet (fonte ainda nao baixada)`,
   nenhum aviso de "periodo reivindicado por mais de um recurso" e `$LASTEXITCODE`
   igual a 0.

2. **Baixar e ler pela biblioteca.** O arquivo fica no mesmo cache que o publicador usa.

   ```powershell
   uv run python -c "from brinss.datasets import load_dataset; df = load_dataset('$F', periodo='$P', source='inss'); print(df.shape); print(list(df.columns)); print(df.head())"
   ```

   Confira que:
   - os nomes das colunas fazem sentido, sem `Unnamed: 0`, `Unnamed: 1`, que indicariam
     um cabeçalho lido na linha errada;
   - a quantidade de linhas é plausível;
   - num CSV, o log traz `CSV dialect for ...` com o delimitador escolhido.

   Anote o número de linhas.

3. **Converter para Parquet**, sem tocar no Hub.

   ```powershell
   uv run publish-to-hf --sample --familia $F --periodo $P
   ```

   Espere `gera  tmp\data\<familia>\<mes>.parquet (N linhas, …)`, com N igual ao
   número de linhas do passo 2.

4. **Conferir o Parquet.**

   ```powershell
   uv run python -c "import pyarrow.parquet as pq; t = pq.read_table('tmp/data/$F/$P.parquet'); print(t.num_rows); print(t.schema)"
   ```

   O número de linhas deve bater com o do passo 2. As colunas devem ser as mesmas,
   todas `string`, mais a `periodo_referencia`.

5. **Publicar.**

   ```powershell
   uv run publish-to-hf --push --update-card --familia $F --periodo $P
   ```

   Espere uma linha `push  data/<familia>/<mes>.parquet (…, novo)`, a linha do commit
   e um resumo sem `falhas`.

   O `--update-card` coloca a família nova no bloco `configs:` do dataset card. Sem
   ele, o Dataset Viewer do Hub não mostra o conjunto. Ele também reescreve o
   `README.md` do dataset no Hub, então edições manuais feitas lá se perdem.

6. **Conferir no Hub.**
   - O arquivo em
     `https://huggingface.co/datasets/agaqueiroz/brinss-public-datasets/tree/main/data/<familia>`.
   - A entrada `<familia>/<mes>` no `manifest.json`, com o SHA256 do arquivo de origem
     e a contagem de linhas.
   - A configuração `<familia>` no Dataset Viewer, com as linhas visíveis. O viewer
     pode levar alguns minutos para processar.

Se algum passo sair diferente do esperado, pare nesse conjunto e guarde a saída e o log
(em `logs/`).

> **`requerimentos_solicitados` 2026-04 está fora da carga por enquanto.** No CKAN, o
> recurso desse mês aponta para o arquivo dos pendentes (`PDA_ITEM_10_PEND_202604.csv`).
> Não há `--excluir`, então **não rode `requerimentos_solicitados` sem `--periodo`**
> até o INSS corrigir o link. O mês 2026-07 também está fora: o arquivo cadastrado
> responde 403 no S3. Veja o `TODO.md`.

### Rodadas dirigidas

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

Nestes casos (trabalho em lote) recomenda-se a sequência:

a) Se as famílias existirem em `_families.py` da biblioteca **brinss-public-datasets**:

1. Baixar as fontes para o cache. O ensaio (`uv run publish-to-hf` sem flags) **não**
   baixa nada, e o `--sample` só converte o que já está em cache. Um jeito é ler os
   meses pela biblioteca, que baixa para o mesmo cache do publicador:
   `uv run python -c "from brinss.datasets import load_dataset; load_dataset('$F', periodo='all', source='inss')"`.
   Isso também carrega os meses em memória: serve para conjuntos pequenos (pessoal,
   requerimentos), mas não para os `beneficios_mantidos_*`;
2. Converter tudo localmente com `uv run publish-to-hf --sample`;
3. Conferir as linhas e colunas mês a mês.
4. Só então, rodar o `uv run publish-to-hf --push`.

b) Se as famílias não existirem em `_families.py`, será necessário atualizar a biblioteca **brinss-public-datasets**.

### Apontamentos

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
  applications/br-public-datasets-publisher/   # este repositório
  libraries/brinss-public-datasets/            # github.com/agaqueiroz/brinss-public-datasets
```

```bash
uv sync           # instala o projeto e o grupo dev
uv run pytest     # testes (os marcados `network` ficam de fora por padrão)
uv run ruff check .
```

Veja `PLAN.md` para o desenho e `TODO.md` para o que ficou pendente.
