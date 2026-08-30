# Estruturar o `publish_to_hf.py` como aplicativo CLI gerenciado por UV

## Contexto

O diretório `br_public_datasets_publisher/` contém hoje apenas este `PLAN.md`. O código a
estruturar é o `scripts/publish_to_hf.py` da biblioteca irmã `brinss-public-datasets` (1365 linhas),
que continua lá e é a **fonte de verdade** desta migração — a cópia que existia aqui foi removida.
Esse script faz tudo — parsing
de ~20 flags, logging durável com fsync, conversão em streaming para Parquet, cache local de build,
manifesto de proveniência, commits em lote no Hugging Face, renderização do dataset card e a
orquestração de três modos (dry-run, `--sample`, `--push`) — num só módulo, com o `argparse.Namespace`
atravessando dez assinaturas de função.

Dois problemas concretos motivam a mudança:

1. **Manutenção.** Toda decisão de modo é um `if args.sample` / `if not args.push` espalhado por seis
   lugares que precisam lembrar o que cada um implica. Testar o laço de publicação exige montar um
   `Namespace` real e monkeypatchar módulos privados de terceiros.
2. **Acoplamento à API privada da biblioteca.** O script importa `_cache`, `_catalog`, `_reading`,
   `_log` e `_families`. A API pública de `brinss` (`load_dataset`, `list_periods`, enums, exceções)
   **não é suficiente** — não expõe entradas de catálogo por recurso, o caminho do arquivo baixado, o
   registro de SHA256 nem o leitor em chunks. Quando a biblioteca for para o PyPI, esse acoplamento
   passa a ser entre distribuições, e uma renomeação interna quebra o publisher em runtime.

O acoplamento mais perigoso é `_cache._resource_filename`: se a regra de nomenclatura mudar, nada
levanta exceção — todo mês em cache passa a ser reportado como ausente e um `--sample` simplesmente
não faz nada.

**Resultado pretendido nesta iteração:** projeto UV completo, com a árvore de arquivos, as interfaces
de alto nível, **todo o código migrado e funcionando** (dry-run, `--sample`, `--push`) e **os 58 testes
migrados**, verdes.

## Decisões já tomadas

| Decisão | Escolha |
| --- | --- |
| Escopo | Esqueleto + migração completa, incluindo os testes |
| API privada da lib | Camada anticorrupção num único módulo + self-check de compatibilidade |
| CLI | `argparse` — flags e textos em português preservados na íntegra |
| Destino | Protocol `DatasetRepository` com `HuggingFaceRepository` + `OfflineRepository` (null object) |

Regra que governa o desenho: **todo seam precisa de duas implementações que existam de fato** — uma
real e outra (fake de teste ou null object de um modo real). O que tiver só uma continua sendo função.

## Árvore de arquivos

```
br_public_datasets_publisher/
├── pyproject.toml            # uv_build, deps, [project.scripts], ruff + pytest
├── uv.lock                   # versionado: isto é aplicação, o lock é o artefato
├── .python-version           # 3.12
├── .gitignore                # __pycache__, .venv, tmp/, logs/, dist/
├── LICENSE, README.md        # README absorve a seção "Publicação em Parquet..." da lib
├── docs/upstream-api.md      # lista de símbolos a promover a API pública na biblioteca
├── src/br_publisher/
│   ├── __init__.py           # só a versão; sem re-exports (é app, não lib)
│   ├── __main__.py           # `python -m br_publisher`
│   ├── main.py               # composition root: argv -> Settings -> deps -> use case -> exit code
│   ├── cli.py                # build_parser(): as ~20 flags, verbatim, e nada mais
│   ├── settings.py           # Settings/LogSettings congelados, Mode, ModeProfile, normalize_periods
│   ├── ports.py              # todos os Protocols num arquivo: o catálogo de seams numa tela
│   ├── errors.py             # PublisherError, UsageError, ManifestError, LibraryIncompatibleError
│   ├── logging_setup.py      # DurableFileHandler + configure_logging(); sem global de módulo
│   ├── report.py             # Reporter: header, checkpoints com fsync, bloco de resumo
│   ├── library/              # CAMADA ANTICORRUPÇÃO
│   │   ├── __init__.py       # re-exporta a superfície; não vaza nomes privados
│   │   ├── models.py         # Family, SourceResource — espelhos congelados dos tipos da lib
│   │   ├── adapter.py        # O ÚNICO módulo que pode importar brinss.datasets._*
│   │   └── compat.py         # check_library(): faixa de versão + cada símbolo privado usado
│   ├── domain/               # puro, sem I/O
│   │   ├── recipe.py         # CONVERSION_RECIPE, COMPRESSION, PERIOD_COLUMN, MANIFEST_SCHEMA_VERSION
│   │   ├── keys.py           # path_in_repo, parse_repo_path, manifest_key
│   │   ├── manifest.py       # Manifest, ManifestEntry, REASON_*, find_orphans, published_families
│   │   ├── deciders.py       # UploadDecider: ManifestDecider | SampleDecider
│   │   └── plan.py           # Plan, RunStatus (STATUS_*)
│   ├── infra/                # tudo que toca disco, socket ou relógio
│   │   ├── fsio.py           # write_json_atomic, sha256_file, utcnow
│   │   ├── build_cache.py    # BuildCache + BuildRecord + índice de build
│   │   ├── parquet.py        # StreamingParquetConverter, write_row_groups, to_publishable
│   │   ├── hub.py            # HuggingFaceRepository + CommitBatch + has_token(); único import de hf
│   │   ├── offline.py        # OfflineRepository: null object de --sample e --no-hub
│   │   └── card.py           # DatasetCardRenderer
│   └── usecases/
│       ├── publish.py        # PublishDatasets: laço de execução, falha por mês isolada
│       ├── reconcile.py      # ReconcileOrphans (--reconciliar)
│       └── prune.py          # PruneBuildCache (--prune-parquet)
└── tests/
    ├── conftest.py           # make_csv_bytes (cópia), fixture settings(), ctx()
    ├── fakes.py              # InMemoryRepository, FakeCatalog, FakeSourceStore, RecordingHubClient
    ├── test_boundaries.py    # AST sobre src/: ninguém além de library/adapter.py importa _*
    ├── test_main.py          # códigos de saída 0/1/2 via main(argv)
    ├── test_settings.py      # combinações de flags, normalização de período, matriz de ModeProfile
    ├── library/              # test_adapter.py (canário contra a lib real), test_compat.py
    ├── domain/               # test_keys, test_manifest, test_deciders
    ├── infra/                # test_fsio, test_parquet, test_build_cache, test_hub, test_card
    └── usecases/             # test_publish, test_reconcile, test_prune
```

`library/` é pacote e não módulo único para que `adapter.py` fique pequeno o bastante para ser
revisado em cinco minutos a cada release da biblioteca — tipos espelho e self-check saem dele.

## Interfaces de alto nível

### Camada anticorrupção

`library/models.py` — tipos nossos, não deles:

```python
@dataclass(frozen=True, slots=True)
class Family:
    key: str
    title: str

@dataclass(frozen=True, slots=True)
class SourceResource:
    """Um mês de uma família no portal — espelho de brinss.datasets._catalog.ResourceEntry.

    ``period`` é texto "AAAA-MM", não pandas.Period: o layout do repo, as chaves do
    manifesto e as linhas de log falam texto, e carregar um tipo do pandas pelo
    domínio é o que fazia o script importar pandas em toda parte.

    ``native`` guarda o ResourceEntry original como handle opaco, para devolver ao
    leitor exatamente o objeto de onde veio; reconstruí-lo funcionaria hoje e
    quebraria no dia em que a lib ganhar um campo. Fora de __eq__ e __repr__.
    """
    family_key: str
    period: str
    url: str
    resource_id: str
    resource_name: str
    format: str
    native: object | None = field(default=None, repr=False, compare=False)
```

`library/adapter.py` — classe `BrinssLibrary` implementando `SourceCatalog`, `SourceStore` e
`SourceReader` de uma vez (compartilham a mesma raiz de cache e a mesma instância de catálogo):

```python
class BrinssLibrary:
    def __init__(self, *, cache_dir: Path | None = None, force_refresh: bool = False) -> None: ...
    # SourceCatalog
    @property
    def root(self) -> Path: ...                                        # _cache.get_cache_root
    def families(self) -> Mapping[str, Family]: ...                    # _families.FAMILIES
    def resources(self, family_key: str) -> tuple[SourceResource, ...]  # _catalog.build_catalog
    def resource_for(self, family_key: str, period: str) -> SourceResource | None
    # SourceStore
    def cached_path(self, r: SourceResource) -> Path | None: ...       # _cache._resource_filename
    def known_digest(self, r: SourceResource) -> str | None: ...       # _cache._load_registry
    def fetch(self, r: SourceResource) -> Path: ...                    # _cache.fetch_resource
    # SourceReader
    def encodings(self, path: Path) -> list[str]: ...                  # _reading.resource_encodings
    def open_chunks(self, path, r, *, encoding=None) -> AbstractContextManager[Iterator[pd.DataFrame]]
```

`library/compat.py` — `check_library()` roda antes de qualquer trabalho e faz três verificações, da
mais barata para a mais cara: (1) versão instalada dentro da faixa fixada; (2) cada par
`(módulo, atributo)` de `REQUIRED_SYMBOLS` ainda existe; (3) `_resource_filename` ainda produz o nome
que este app procura em disco — a falha silenciosa que vale pagar para detectar. Levanta
`LibraryIncompatibleError`, que `main()` traduz em código 2.

A fronteira é imposta **duas vezes**, porque uma não basta:
- `tests/test_boundaries.py` percorre `src/` com `ast` e falha se qualquer módulo além de
  `library/adapter.py` mencionar `brinss.datasets._*` num import — inclusive na forma
  `from brinss.datasets import _cache`, que o ruff **não** pega;
- `[tool.ruff.lint.flake8-tidy-imports.banned-api]` bane as formas pontilhadas, com `per-file-ignores`
  para `adapter.py`, `compat.py` e `tests/library/`.

### Ports (`ports.py`)

`SourceCatalog`, `SourceStore`, `SourceReader`, `ParquetConverter`, `BuildStore`, `DatasetRepository`,
`CardRenderer`, `HubClient`. Todos `Protocol` (não ABC: não há implementação compartilhada a herdar, e
ABC obrigaria todo fake de teste a importar a base).

`DatasetRepository` é o port central e **é dono do manifesto**, porque o invariante "o manifesto só
pode reivindicar um mês depois que o commit dele pousou" só é aplicável onde o commit acontece:

```python
class DatasetRepository(Protocol):
    @property
    def manifest(self) -> Manifest: ...
    @property
    def commits(self) -> int: ...
    def ensure_exists(self) -> None: ...
    def load_manifest(self) -> Manifest: ...
    def list_parquet(self) -> dict[str, int]: ...
    def stage(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None: ...
    def flush(self) -> None: ...
    def replace_manifest(self, entries: Mapping[str, ManifestEntry], message: str) -> None: ...
    def write_card(self, markdown: str, *, overwrite: bool) -> None: ...
```

`HubClient` nomeia a fatia de `HfApi` realmente usada (`create_repo`, `create_commit`, `file_exists`,
`hf_hub_download`, `list_repo_tree`, `upload_file`) — é isso que permite aos testes de commit injetar
um dublê sem importar `huggingface_hub`.

### Domínio

`Manifest` é **entidade, não value object**: deliberadamente não é frozen. `adopt()` é o único mutador
e só pode ser chamado depois que o commit pousou. Congelá-lo empurraria esse invariante para quem
rebinda a variável — exatamente o erro que deixou 25 meses presos como "novo" permanente.

`ManifestEntry` guarda o SHA256 da **origem**, nunca do Parquet: Parquet não é byte-reproducível entre
versões do pyarrow, então hashear a saída faria toda execução parecer uma mudança.

As razões em português (`"novo"`, `"origem mudou"`, `"conversao mudou"`, `"inalterado"`, `"forcado"`,
`"amostra"`, `"fonte nao baixada"`) viram constantes `REASON_*`.

### Os três modos

`--sample`, dry-run e `--push` diferem em **capacidades**, não em algoritmo — o `_process_one` atual
prova isso: os ramos compartilham resolver origem → hashear → materializar → contabilizar, e divergem
só em (a) se pode baixar, (b) o que decide "precisa de trabalho", (c) se envia. Portanto **não** há
hierarquia `PublishMode`; três subclasses reimplementando o mesmo esqueleto é como se ganha um bug que
só aparece no `--sample`. Em vez disso:

1. **`ModeProfile`** — uma tabela congelada resolvida uma vez das flags
   (`may_download`, `may_convert`, `may_publish`, `uses_hub`, `summary_verb`, `header_label`),
   substituindo todo `if args.sample` espalhado. Nos testes, vira uma parametrização.
2. **Null Object** — `OfflineRepository` implementa `DatasetRepository` com manifesto vazio, listagem
   vazia e `stage` que não faz nada. `--sample` e `--no-hub` recebem um; os use cases perdem todo
   `if not args.no_hub and not args.sample`. É a maior redução de ramificação disponível.
3. **Strategy, só na decisão** — `UploadDecider` com `ManifestDecider` (manifesto + receita decidem) e
   `SampleDecider` (sem manifesto: só o cache de build decide). Duas classes de ~10 linhas, zero
   esqueleto duplicado. Esse Strategy se paga; um por modo inteiro, não.
4. **Um `if` sobrevive e fica:** `if not profile.may_convert: registra o PLAN e retorna`. Esconder isso
   atrás de um `NullConverter` deixaria a linha "PLAN" mais difícil de achar do que o ramo que ela
   substitui.

### Use case e composition root

```python
@dataclass(frozen=True, slots=True)
class PublishContext:
    settings: Settings; profile: ModeProfile
    catalog: SourceCatalog; store: SourceStore; builds: BuildStore
    converter: ParquetConverter; repository: DatasetRepository
    decider: UploadDecider; card: CardRenderer; reporter: Reporter

class PublishDatasets:
    def __init__(self, ctx: PublishContext) -> None: ...
    def __call__(self) -> Plan: ...
    def _process(self, resource: SourceResource, plan: Plan) -> None: ...
    def _materialize(self, r, digest) -> tuple[Path, BuildRecord, bool]: ...
    def _finish(self, plan: Plan) -> Plan: ...

class ExitCode(IntEnum):
    OK = 0; FAILURES = 1; USAGE = 2

def main(argv: list[str] | None = None) -> int: ...
def build_context(settings: Settings, reporter: Reporter) -> PublishContext: ...
```

`build_context` é função simples de propósito: um contêiner de DI para um binário com uma única
fiação compra indireção e nada mais.

### Configuração

`Settings` congelado, construído uma vez de `argv`, nunca mutado. `_validate(args) -> int` vira
`UsageError(mensagem)` levantada dentro de `Settings.from_namespace`, capturada uma vez em `main`,
impressa em stderr, devolvida como código 2 — mesmas mensagens, mesmo código, um só ponto de saída. A
validação continua rodando **antes** do setup de logging: uma execução que não pode começar não deve
deixar um arquivo de log alegando que começou.

**Nenhuma variável de ambiente nova.** `HF_TOKEN` continua sendo lido só via
`huggingface_hub.get_token()` em `infra/hub.has_token()` — nunca `os.environ`, porque ler o ambiente
direto rejeitava uma sessão legítima de `hf auth login` (um teste pode afirmar que `os.environ["HF_TOKEN"]`
não aparece no repo). `BRINSS_DATA_HOME` e `BRINSS_CATALOG_TTL_SECONDS` continuam sendo da biblioteca,
honrados passando `settings.cache_dir` (possivelmente `None`) ao adapter. E nada de
`BRINSS_PUBLISH_REPO`: o repositório de destino é o valor mais consequente de uma execução e precisa
ficar visível no `--help`, na linha de comando e no cabeçalho do log.

## Padrões aplicados — e os rejeitados

**Se pagam:** Anti-corruption Layer (`library/adapter.py`); Ports via Protocol (todo port tem ≥2
implementações reais); Null Object (`OfflineRepository`); Strategy estreito (`UploadDecider`);
Repository (`DatasetRepository`, dono do invariante do commit); value objects congelados; composition
root (`build_context`); collecting parameter (`Plan`, já presente e correto — resultados parciais
sobrevivem a um `KeyboardInterrupt`).

**Rejeitados de propósito:** hierarquia de classes por modo (triplicaria o esqueleto); contêiner de DI;
ABCs no lugar de Protocols; Command+undo sobre `CommitBatch` (o histórico git do Hub *é* o undo);
Observer/event bus (o `logging` já é um, e a durabilidade quer `fsync` explícito em três pontos
nomeados, não fan-out); Unit of Work sobre o índice de build (agruparia justamente as escritas que não
podem ser agrupadas — `write_json_atomic` a cada registro *é* o contrato de retomada);
`Result`/`Either` (o modelo de falha é "loga este mês e segue", um `try/except` num call site);
pipeline genérico de conversão; `pydantic-settings` (o argparse já valida, e binding implícito de env
var é justamente o que este app não deve ter); port para o portal CKAN (é trabalho da biblioteca);
descoberta de repositórios por entry point; `py.typed`/publicação no PyPI (é ferramenta de mantenedor).

## Avaliação: a biblioteca `datasets` simplifica isto?

**Como dependência de runtime, não — e adotá-la destruiria o modelo incremental. Como dependência de
desenvolvimento, sim, e vale a pena: é o verificador que falta.**

`datasets` 5.0.1 (jul/2026, `>=3.10`) oferece `Dataset.push_to_hub(repo_id, config_name=..., split=...,
max_shard_size="500MB", num_shards=...)`, que converte para Parquet, envia por HTTP e cuida do card.
Parece cobrir metade do que este app faz. Não cobre, por cinco motivos — e o primeiro sozinho decide.

1. **O layout de arquivos é dela, não nosso, e não é endereçável por mês.** `push_to_hub` fragmenta um
   *split* inteiro em shards nomeados `data/{split}-00000-of-00042.parquet` (o padrão literal no fonte é
   `data/{split}-[0-9][0-9][0-9][0-9][0-9]-of-[0-9][0-9][0-9][0-9][0-9]*.parquet`). O nome carrega o
   **total** de shards. Publicar um mês novo muda o total, e portanto renomeia **todos** os arquivos da
   família: `-of-00042` vira `-of-00043`. Uma atualização de 1 arquivo vira reenvio da família inteira —
   dezenas de GB nas famílias pesadas. Todo o desenho aqui repousa em `data/<família>/<AAAA-MM>.parquet`
   ser um nome estável: é o que o manifesto indexa, o que `parse_repo_path` inverte e o que permite
   `needs_upload` decidir mês a mês. A alternativa — um `config_name` por mês — daria 291 configs e um
   bloco `configs:` inutilizável no viewer do Hub.
2. **A semântica é substituir, não acrescentar.** `push_to_hub` casa o glob do split e emite
   `CommitOperationDelete` para o que não está no lote novo. Nosso modelo é aditivo, com o manifesto como
   fonte de verdade e o invariante "o manifesto viaja no mesmo commit dos arquivos que descreve". São
   modelos de consistência incompatíveis, não uma diferença de API.
3. **Ela reescreve o card.** `push_to_hub` importa `DatasetCard`/`DatasetCardData` e regrava o YAML de
   `configs`/`dataset_info` do `README.md`. O `_maybe_upload_card` atual existe justamente para **nunca**
   sobrescrever um card editado na web — só com `--update-card`. Adotar `datasets` significaria perder
   citações e notas escritas à mão a cada execução.
4. **Ela não sabe nada de proveniência.** Não há onde guardar o SHA256 do arquivo **de origem**, que é o
   que decide se um mês mudou. O `dataset_info` que ela grava descreve a saída dela — e hashear a saída é
   exatamente o que este projeto rejeita, porque Parquet não é byte-reproducível entre versões do pyarrow.
   Sem manifesto não há retomada, não há `--reconciliar`, e não há como distinguir "novo" de "inalterado".
5. **Ela não lê estas fontes.** `datasets` não tem builder de XLSX — só csv/json/parquet/arrow/text/sql e
   afins. E os arquivos do INSS têm linhas de banner, membros de zip e encoding a farejar; é precisamente
   para isso que `brinss.datasets._reading` existe. Usar `datasets` para ler significaria reimplementar o
   que a biblioteca irmã já resolve, perdendo a propriedade central do script: *dirigir o pipeline de
   leitura da própria biblioteca em vez de reimplementá-lo*.

Some-se o peso: `datasets` arrasta `dill`, `multiprocess`, `xxhash`, `fsspec`, `tqdm` e afins para uma
ferramenta de mantenedor cujo laço de escrita são ~40 linhas de `pyarrow.parquet.ParquetWriter`.

**O uso que vale a pena — `datasets` no grupo `dev`, como teste de aceitação.** Nada hoje verifica que o
que foi publicado é legível pelo consumidor. O bloco `configs:` que `build_dataset_card` escreve à mão é
testado apenas quanto à forma (um `config_name` por família); se o glob estiver errado, o viewer do Hub
mostra vazio e a suíte passa. `datasets` é o que os consumidores vão usar, então verificar com ela é
verificar o contrato de verdade:

```python
@pytest.mark.network
def test_o_hub_le_o_que_publicamos():
    ds = load_dataset(REPO_ID, name="beneficios_concedidos", split="train", streaming=True)
    row = next(iter(ds))
    assert row["periodo_referencia"] == "2024-06"   # texto, nao o ordinal 653
    assert row["cid"].startswith("0")               # zeros a esquerda sobreviveram
```

Esses dois asserts cobrem os dois defeitos reais que o código documenta — o `pandas.Period` virando um
inteiro sem sentido fora do pandas, e a inferência de tipos comendo zeros à esquerda de CID/CBO/CNAE —
do lado de fora, como um terceiro os veria. Fica sob o marcador `network`, já desselecionado por padrão.

Uma última nota, para não confundir as ferramentas: se um dia quisermos validar o YAML do card em vez de
montá-lo com `str.join`, a ferramenta certa é `huggingface_hub.DatasetCard`/`DatasetCardData`, que **já é
dependência**. Não é motivo para trazer `datasets`.

## `pyproject.toml`

```toml
[project]
name = "br-public-datasets-publisher"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Faixa de minor fechada porque este app alcança módulos privados de brinss;
    # library/compat.py é a trava fina, esta é a grossa.
    "brinss-public-datasets>=0.1,<0.2",
    "huggingface-hub>=1.28",
    "pandas>=2.2",
    "pyarrow>=17.0",
]

[project.scripts]
publish-to-hf = "br_publisher.main:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    # Só para o teste de aceitação marcado `network`: lê o repositório publicado do
    # jeito que um consumidor leria. Ver "Avaliação: a biblioteca datasets...".
    # Nunca importada por src/ -- test_boundaries.py também afirma isso.
    "datasets>=5.0",
]

[build-system]
requires = ["uv_build>=0.12.3,<0.13.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "br_publisher"

# Enquanto brinss-public-datasets não está no PyPI. Apagar esta tabela no dia em que
# publicar: o pin acima já diz o que é aceitável e `uv lock` resolve do índice.
[tool.uv.sources]
brinss-public-datasets = { path = "../../libraries/brinss_public_datasets", editable = true }

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["network: requires internet access (deselected by default)"]
addopts = "-m 'not network' --strict-markers"

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM", "C4", "RUF", "TID", "PTH", "LOG", "G"]
```

Notas:
- `huggingface-hub` e `pyarrow` viram dependências reais aqui, deixando de ser grupo opcional lá.
- `openpyxl`/`xlrd` **não** são declarados: vêm transitivamente por `brinss-public-datasets`, que é
  dona da leitura. `pandas` **é** declarado porque este código chama `pd.Period`/`pd.DataFrame`.
- **Adicionar config de ruff, sim.** A biblioteca irmã não tem nenhuma, o que significa ruff nos
  defaults: `select = ["E4","E7","E9","F"]` e `line-length = 88`. `E501` não está nesse conjunto, então
  ninguém nunca viu erro de comprimento — mas o código tem linhas de até 123 colunas. No instante em
  que alguém rodar `ruff format`, tudo reflui para 88 e todo diff futuro vira ruído. Fixar 120 trava o
  estilo que já existe.
- `G` e `LOG` no `select` de propósito: impõem os args `%`-lazy de log que o código já usa.
- **Sem mypy.** Sobre pandas/pyarrow/huggingface-hub o atrito de stubs é caro para o benefício; os
  Protocols já documentam os seams. Se um dia valer, rodar `pyright` em modo básico só sobre `domain/`,
  `ports.py` e `settings.py`, que são puros.
- Versionar o `uv.lock`.

## Testes

`tests/conftest.py` ganha uma **cópia** de `make_csv_bytes` (8 linhas, sem dependências) em vez de
qualquer mecanismo de compartilhamento — um plugin pytest ou hack de path para alcançar o `conftest.py`
da irmã acoplaria dois repositórios por uma fixture, acoplamento pior do que o que este desenho existe
para resolver. As demais fixtures da lib não são usadas por `test_publish_to_hf.py`.

Mapeamento dos 58 testes:

| Testes atuais | Novo lar | Mudança |
| --- | --- | --- |
| `path_in_repo`/`parse_repo_path` | `domain/test_keys.py` | só o import |
| `needs_upload_*` ×5 | `domain/test_deciders.py` | reescrever contra `ManifestDecider.decide` → `Decision`; mesmas razões em português |
| `find_orphans`, `published_families` ×2 | `domain/test_manifest.py` | `dict` vira `Manifest` |
| `normalize_periodos_*` ×6 | `test_settings.py` | `SystemExit` → `UsageError`; o código de saída passa a ser afirmado uma vez, em `main` |
| `sha256_file` | `infra/test_fsio.py` | só o import |
| `to_publishable_*` ×3 | `infra/test_parquet.py` | só o import (o teste de cópia rasa fica: fixa um incidente real de memória) |
| dataset card | `infra/test_card.py` | vira `DatasetCardRenderer.render(...)` |
| `test_format_bytes` ×4 | **apagar** | testa `_log.format_bytes` por um alias; pertence ao `test_logging.py` da lib |
| `cached_source_finds_a_file_...` | `library/test_adapter.py` | **promovido a canário** — continua importando o `_cache` real, isento do ban |
| `CommitBatch` ×5 | `infra/test_hub.py` | quase verbatim; `_RecordingApi` vira `RecordingHubClient` satisfazendo o Protocol `HubClient` |
| `_load_manifest` + manifesto inconfiável ×4 | **dividir**: regras de parsing → `domain/test_manifest.py` (puras, sem API falsa); "repo sem manifesto" → `infra/test_hub.py` |
| `run_refuses_to_publish_when_manifest_unreadable` | `test_main.py` | mantém como e2e real (ainda patcha `HfApi`) |
| `_ensure_parquet` ×3, invalidação ×4, prune | `infra/test_build_cache.py`, `usecases/test_prune.py` | **melhora**: o teste de "não reabre a origem" troca monkeypatch de `_reading` por um `ExplodingReader` injetado — deixa de depender de interno de terceiro |
| `_write_parquet` ×4 | `infra/test_parquet.py` | só o import (os quatro fixam incidentes reais de crash/corrupção) |
| `write_json_atomic`, `.tmp` órfão, índice corrompido | `infra/test_fsio.py`, `infra/test_build_cache.py` | só o import |
| `_reconcile` ×3 | `usecases/test_reconcile.py` | **reescrever, bem menor**: `FakeSourceStore` + `FakeCatalog` no lugar de monkeypatch de `_cache` e `SimpleNamespace` |
| `--sample` ×4 | `usecases/test_publish.py` | `_process_one(...)` com nove posicionais vira `PublishDatasets(ctx)._process(...)`; `batch=None` vira `OfflineRepository` |
| mês que explode | `usecases/test_publish.py` | injetar converter que levanta para um período |
| rejeições de CLI ×4 grupos | `test_main.py` | **continuam chamando `main([...])` verbatim** — código de saída e o texto exato em português são o contrato com o usuário |

Testes novos que os seams pagam: `test_boundaries.py` (o guarda em que o desenho inteiro se apoia —
afirma também que `datasets` não é importada de `src/`, só dos testes `network`);
`library/test_compat.py` (`monkeypatch.delattr` → erro nomeando o símbolo sumido; e a checagem de forma
de `_resource_filename`); `test_settings.py::test_mode_profile_matrix`;
`usecases/test_publish.py::test_offline_repository_never_stages`;
`test_main.py::test_incompatible_library_exits_2`.

## Sequência de migração

Cada passo termina com a suíte verde. Nada é apagado antes de o substituto estar testado.

0. **Golden master.** Copiar de volta `scripts/publish_to_hf.py` da biblioteca irmã para a raiz deste
   projeto (a cópia local foi removida; o original lá é a fonte de verdade). `.gitignore`,
   `.python-version`, `LICENSE`, README stub, `pyproject.toml` acima *sem* `[project.scripts]`. Copiar
   `tests/test_publish_to_hf.py` da lib como está + `make_csv_bytes` num `conftest.py` novo.
   `pythonpath = ["."]` temporário no pytest para `import publish_to_hf` continuar funcionando com o
   arquivo na raiz. `uv sync --group dev && uv run pytest` verde **antes de mover qualquer coisa** —
   esta é a linha de base de todos os passos seguintes.
1. **Camada anticorrupção primeiro** (maior risco, todo o resto depende): `library/` + `errors.py`.
   Reescrever os seis imports privados de `publish_to_hf.py` para passar por `BrinssLibrary`. Adicionar
   `test_boundaries.py` e `library/test_compat.py`. Verde com o script ainda num arquivo só.
2. **Domínio puro:** `keys.py`, `recipe.py`, `manifest.py` (introduzindo `Manifest`/`ManifestEntry`),
   `plan.py`. Mecânico; `publish_to_hf.py` reimporta para os testes antigos passarem.
3. **Infra:** `fsio.py`, `parquet.py`, `build_cache.py`, `card.py`. Introduzir `ConversionResult` e
   `BuildRecord`; `_ensure_parquet` se divide em `BuildCache.is_reusable` + materializador que recebe um
   `ParquetConverter`.
4. **Port remoto:** `DatasetRepository`, `HuggingFaceRepository` (envolvendo `CommitBatch` inalterado),
   `OfflineRepository`, `HubClient`. Migrar os testes de commit.
5. **Settings e parser:** `cli.py`, `settings.py`, `_validate` → `UsageError`. `run(args)` vira
   `run(settings, ctx)`. É o passo que toca mais call sites — fazer num commit só.
6. **Use cases e composition root:** `usecases/`, `main.py` com `build_context`/`ExitCode`,
   `logging_setup.py` e `report.py` (matando o global `_LOG_HANDLER`), `deciders.py` ligado.
7. **Corte:** apagar `publish_to_hf.py`, adicionar `[project.scripts]`, remover o `pythonpath`
   temporário, reescrever `test_publish_to_hf.py` nos arquivos por módulo e apagá-lo.

## Verificação

1. `uv sync --group dev` — resolve com a lib pelo `[tool.uv.sources]` local.
2. `uv run pytest` — os 58 testes migrados verdes (contagem final maior, com os novos).
3. `uv run ruff check .` — inclusive o ban de imports privados.
4. `uv run python -c "from br_publisher.library.compat import check_library; check_library()"` — o
   self-check passa contra a lib instalada.
5. `uv run publish-to-hf --help` — as ~20 flags e os textos em português idênticos aos de hoje.
6. `uv run publish-to-hf --no-hub` — dry-run offline, sem tocar no Hub; conferir cabeçalho e resumo.
7. **Teste de aceitação que a suíte unitária não dá:** rodar `python publish_to_hf.py --sample --limite 3`
   *antes* do corte (passo 7) guardando a saída, e `uv run publish-to-hf --sample --limite 3` depois,
   contra o mesmo cache de downloads — comparar os bytes dos Parquet produzidos e o `build-index.json`.
8. `uv run publish-to-hf --push --limite 2 --repo <repo descartável> --create-repo` — só com aprovação
   explícita sua; toca o Hugging Face de verdade.
9. `uv run pytest -m network` logo depois do passo 8 — o `load_dataset` sobre o repo descartável fecha o
   laço: confirma que o bloco `configs:` do card está correto e que `periodo_referencia` e os códigos com
   zero à esquerda chegam como texto do lado do consumidor.

## Fora do escopo desta iteração

- **Limpeza na biblioteca irmã** (apagar `scripts/publish_to_hf.py`, `tests/test_publish_to_hf.py`, o
  grupo `publish`, `pythonpath = ["scripts"]`, e reescrever a seção do README como ponteiro para este
  repo). É outro repositório — confirmar antes.
- **`git init`** aqui: o diretório não é repositório git. Digo quando chegar a hora; não inicializo sem
  você pedir.
- `docs/upstream-api.md` fica **escrito** (é barato e é o mapa da dívida), mas promover os símbolos a
  API pública em `brinss` é trabalho lá: `catalog()`+`Resource` públicos, `describe_datasets()`,
  `cached_path()`, `fetch()`, `source_digest()`, `open_chunks()`+`encodings()`, e
  `LOGGER_NAME`/`format_bytes`/`format_seconds`.
- Retry/backoff em 5xx do Hub; conversão paralela; `--resume-from`; `schema_version = 2` do manifesto ou
  qualquer bump de receita (não misturar migração de dados com refatoração); logging estruturado;
  barras de progresso; arquivo de config TOML; mypy; segunda implementação de `DatasetRepository`.
