# Keyword Retrieval 接口

## 职责与边界

本模块把 `ChunkBatch` 持久化到 Elasticsearch，并执行原生 BM25 关键词检索、精确元数据
过滤和按文档删除。它不负责 Chunking、公式/表格再解析、Embedding、向量检索、混合融合、
Rerank、查询改写或生成。Elasticsearch 只存在于模块私有实现，上游通过公共 Protocol 或
本模块公开服务类调用。

## 安装、配置和生命周期

```bash
python -m pip install -e '.[keyword-retrieval]'
```

支持以下环境变量：

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `ELASTICSEARCH_URL` | 无 | 工厂自行创建客户端时必填 |
| `ELASTICSEARCH_API_KEY` | 无 | 可选 API Key；不会写日志 |
| `ENGINEERING_RAG_KEYWORD_INDEX` | `engineering-rag-chunks-v1` | 配置中的默认索引名；请求仍显式携带索引 |
| `ENGINEERING_RAG_ES_REQUEST_TIMEOUT` | `30` | 官方客户端请求超时（秒） |
| `ENGINEERING_RAG_ES_ANALYZER` | `standard` | Mapping 全文字段 Analyzer |
| `ENGINEERING_RAG_KEYWORD_MAX_TOP_K` | `100` | 查询上限，超限报错且不截断 |
| `ENGINEERING_RAG_ES_REFRESH` | `wait_for` | Bulk 刷新策略：`wait_for/true/false` |

模块导入和服务对象构造不连接网络。工厂创建的客户端可通过上下文管理器或 `close()` 关闭；
调用方注入的客户端由调用方管理，服务不会擅自关闭。

## 公开 API

导入路径：`engineering_rag.modules.keyword_retrieval.api`。

```python
class KeywordRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: KeywordSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...


class ElasticsearchKeywordRetrievalService:
    # 实现上述三个方法，另提供 close() 和上下文管理器。
    ...


def create_keyword_retrieval_service(
    config: ElasticsearchKeywordConfig | None = None,
    *,
    client: ElasticsearchClient | None = None,
) -> ElasticsearchKeywordRetrievalService: ...
```

公共请求/结果模型只来自 `engineering_rag.contracts`，本实现没有修改其字段或版本。

### `index()`

- 重新执行完整 Pydantic 校验；一条 Elasticsearch 文档对应一个物理 Chunk，`_id=chunk_id`。
- `replace_document=False`：幂等 upsert，不清理其他 Chunk。
- `replace_document=True`：非空批次代表完整文档快照。先写入所有新 Chunk；仅当 Bulk 全部
  成功后，删除同一 `document_id` 下已经不在新批次中的旧 Chunk。
- 空批次返回 `attempted=0/indexed=0`，不创建索引、不删除已有数据。
- Bulk 条目失败写入 `IndexResult.failures`，`indexed + failures == attempted`；存在任何失败时
  不执行陈旧 Chunk 清理。传输失败、响应损坏或清理失败则抛异常。
- `operation_id` 随 `IndexResult` 回传用于调用链追踪；持久化幂等性由确定性的 `chunk_id`
  保证，不把 `operation_id` 伪装成跨进程事务日志。

### `search()`

`KeywordSearchRequest` 必须有非空白查询，`top_k` 不得超过配置上限。支持公共
`SearchFilters` 的全部实际字段：`document_ids`、`standard_codes`、`editions`、
`clause_numbers`、`content_types`、`is_explanation`、`is_mandatory`。同一字段多个值为 OR，
不同字段之间为 AND；过滤使用 `bool.filter`，不参与 BM25 分数。

默认只查询私有 `search_text`（取 Chunk 的 `embedding_text`）。如提供 `field_weights`，键
只能是 `content`、`context_header`、`embedding_text`，权重进入 `multi_match`；任意字段名
不会直接进入 DSL。结果按 Elasticsearch `_score` 降序、同分 `chunk_id` 升序，`rank` 从 1
开始，`retrieval_source="keyword"`、`score_type="bm25"`。分数不归一化，也不承诺跨查询或
与向量分数可比。

`RetrievalResult` 从命中 `_source` 和真实 `_score` 构造。索引内仍保存完整 Chunk 来源字段；
但当前公共 `RetrievalResult` 没有 `source_refs/source_block_ids` 字段，因此返回值只能保留契约
已有的页码、文档、标准和条文身份，详见 Task 3 ADR。

### `delete_document()`

只以 `document_id` 精确删除指定索引内的 Chunk。索引存在但文档不存在返回删除数 0；索引
不存在返回 `index_existed=False`。这与 `search()` 不同：搜索不存在的索引会抛
`KeywordIndexNotFoundError`，不会伪装为空命中。

## Mapping 与 Analyzer

Mapping 版本 `keyword-index-v1`，`dynamic=strict`，默认 similarity 明确为 BM25。身份、标准、
条文、内容类型和来源 ID 使用 `keyword`，页码使用 `integer`，三态强制性使用可缺省的
`boolean`，`source_refs` 以禁用解析的结构化 `_source` 对象保存。`content`、
`context_header`、`embedding_text` 和私有 `search_text` 是使用同一配置 Analyzer 的文本字段。

默认 `standard` Analyzer 无插件要求，但中文词粒度有限。配置 IK 等插件 Analyzer 时，目标
Elasticsearch 必须已安装兼容插件；创建失败直接报错，不静默降级。已有索引必须携带匹配的
Mapping 版本和 Analyzer 元数据，否则抛 `KeywordIndexCompatibilityError`，绝不覆盖 Mapping。

## 错误和副作用

模块异常基类为 `KeywordRetrievalError`，并区分配置/依赖、非法实现级请求、缺失索引、
Mapping 不兼容、创建失败、连接、超时、后端拒绝和响应转换失败。原始 Elasticsearch 异常
保留为 `__cause__`。没有内存后端或故障时返回空列表的降级路径。

Elasticsearch 写入和删除是外部副作用。Bulk 与后续 delete-by-query 不是跨请求事务；若新
数据写入成功而清理失败，方法抛出明确异常，调用方可用同一快照安全重试。

## 最小示例

```python
from engineering_rag.contracts.retrieval import IndexRequest, KeywordSearchRequest
from engineering_rag.modules.keyword_retrieval.api import create_keyword_retrieval_service

with create_keyword_retrieval_service() as service:
    indexed = service.index(
        batch,
        IndexRequest(index_name="engineering-rag-chunks-v1", operation_id="ingest-001"),
    )
    results = service.search(
        KeywordSearchRequest(
            query="混凝土承载力",
            top_k=10,
            index_name="engineering-rag-chunks-v1",
        )
    )
```

可执行完整示例：`python examples/keyword_retrieval_elasticsearch.py`。

## 版本、测试和验证状态

公共 Chunk/检索 Schema 版本仍为 `1.0`；私有 Mapping 版本为 `keyword-index-v1`。改变公共
字段需升级公共 Schema；不兼容 Mapping 需新 Mapping 版本和显式迁移/重建索引。

```bash
python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q
python -m pytest -q
ELASTICSEARCH_URL=http://localhost:9200 \
  python -m pytest tests/integration/test_keyword_retrieval_elasticsearch.py -q
ruff check .
ruff format --check .
```

没有 `ELASTICSEARCH_URL` 时真实持久化测试明确跳过；单元测试使用注入式测试替身，不冒充
真实 Elasticsearch 验证。
