# API pública que falta em `brinss-public-datasets`

Este aplicativo alcança módulos privados da biblioteca porque a API pública dela
não oferece o que ele precisa. Todo esse acesso está confinado em
[`src/br_publisher/library/adapter.py`](../src/br_publisher/library/adapter.py),
e `library/compat.py` falha na inicialização se algum símbolo sumir ou mudar de
assinatura.

Cada linha abaixo é um símbolo privado que hoje usamos, com a forma pública que o
substituiria. Quando essas entrarem, a troca é local ao adapter: nenhum outro
módulo deste projeto muda.

| Hoje (privado) | Proposta (público) |
| --- | --- |
| `_catalog.build_catalog`, `_catalog.ResourceEntry`, `_catalog.DatasetCatalog` | `brinss.datasets.catalog(name, *, source, cache_dir=None, force_refresh=False) -> Catalog`, com um `Resource` congelado (`period`, `url`, `resource_id`, `resource_name`, `format`) e `Catalog.entries` / `.entries_by_period` / `.min_period` / `.max_period` |
| `_families.FAMILIES`, `_families.DatasetFamily` | `brinss.datasets.describe_datasets() -> Mapping[str, DatasetInfo]` e `describe_dataset(name) -> DatasetInfo` (`key`, `title`) |
| `_cache._resource_filename` | `brinss.datasets.cached_path(resource, *, family, cache_dir=None) -> Path \| None` — onde o arquivo baixado está, **sem baixar** |
| `_cache.fetch_resource` | `brinss.datasets.fetch(resource, *, family, cache_dir=None, force_download=False) -> Path` |
| `_cache._load_registry` | `brinss.datasets.source_digest(resource, *, family, cache_dir=None) -> str \| None` — o SHA256 do registro, que sobrevive à exclusão do arquivo |
| `_reading.open_resource_chunks`, `_reading.resource_encodings` | `brinss.datasets.open_chunks(...)` e `brinss.datasets.encodings(path) -> list[str]` |
| `_log.LOGGER_NAME`, `format_bytes`, `format_seconds` | os mesmos nomes em `brinss.datasets` |

## Prioridade

**`cached_path` é a mais urgente**, e não por conveniência: é a única cuja quebra
é *silenciosa*. As outras levantam `AttributeError` ou `TypeError`. Se a regra de
nomenclatura de `_resource_filename` mudar, nada levanta exceção — todo mês em
cache passa a ser reportado como ausente e um `--sample` simplesmente não faz
nada. É por isso que `compat._check_filename_rule` compara o nome produzido
contra um valor conhecido, em vez de só conferir que a função existe.

Em segundo lugar, `open_chunks`/`encodings`: os docstrings dessas duas na
biblioteca já descrevem um chamador externo conduzindo o fallback de encoding —
elas já são um contrato público em tudo menos no nome.

## Nota sobre `DataSource`

`DataSource` **já é público** (`brinss.datasets.DataSource`) e não precisa de
nada. Registrando só o cuidado: o default da biblioteca é `DataSource.HF`, que é
o certo para quem lê e o errado para este aplicativo, que *constrói* o mirror.
O adapter fixa `DataSource.INSS` em `CATALOG_SOURCE`, com um teste que o pina.
