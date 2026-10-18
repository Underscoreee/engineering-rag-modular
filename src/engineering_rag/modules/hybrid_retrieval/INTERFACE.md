# Hybrid Retrieval 接口

## 职责与边界

本模块顺序调用注入的 `KeywordRetrievalService` 与 `VectorRetrievalService`，按物理
`chunk_id` 合并候选、校验身份一致性，并使用 RRF 或分路 Min-Max 加权融合生成统一的
`RetrievalResult`。它不创建 Elasticsearch/Milvus 客户端，不执行 BM25、Embedding、索引、
Query Rewrite、HyDE、Rerank 或 Generation，也不导入其他业务模块的 `internal/`。

模块无持久化副作用。底层检索异常会原样传播，不会伪装成空结果或静默降级为单路成功。

## 公开入口和依赖注入

导入路径：`engineering_rag.modules.hybrid_retrieval.api`。

```python
class HybridRetrievalService(Protocol):
    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]: ...


def create_hybrid_retrieval_service(
    keyword_service: KeywordRetrievalService,
    vector_service: VectorRetrievalService,
    config: HybridRetrievalConfig | None = None,
) -> DefaultHybridRetrievalService: ...
```

工厂只接收公共 Protocol。真实 Elasticsearch/Milvus 服务应由组合根通过各自公开 `api.py`
创建后注入；单元测试可以注入纯内存测试替身。导入 Hybrid 模块不会连接数据库或加载模型。

`HybridRetrievalConfig` 当前只包含公共请求没有表达的 `rrf_k=60`，必须是正整数。

## 请求、候选数和过滤规则

公共 `HybridSearchRequest` 的真实字段是：

| 字段 | 语义 |
| --- | --- |
| `keyword` | 完整 `KeywordSearchRequest`，保留 query、filters、field weights 和索引名 |
| `vector` | 完整 `VectorSearchRequest`，保留 query、filters、模型 ID 和 Collection 名 |
| `fusion_strategy` | `rrf` 或 `weighted_normalized` |
| `keyword_weight` / `vector_weight` | 分路权重 |
| `candidate_k` | 每一路实际召回的候选上限 |
| `top_k` | 融合后最终返回数，且不得大于 `candidate_k` |

执行时复制两路子请求，只将各自 `top_k` 设置为共享的 `candidate_k`，不修改调用者对象。
公共契约允许两路具有不同 query、filters 和索引名，因此 Hybrid 原样保留这些差异，不擅自
覆盖。调用顺序固定为 Keyword → Vector → 合并 → 融合 → 截断。

两路均正常返回空列表时结果为 `[]`；一路正常为空时，另一路候选仍参与融合。任一路抛出
连接、超时、索引、模型或响应异常时，调用整体失败，另一种情况不得冒充双路融合成功。

## 候选合并与一致性

- 只用 `chunk_id` 去重，不用 `logical_chunk_id`；同一逻辑条文的不同物理 Chunk 会保留。
- 排名以两路返回列表的实际位置从 1 计数，不盲信结果对象内可能异常的 `rank` 值。
- 同一路重复返回同一 `chunk_id`、返回错误 `retrieval_source` 或非有限分数会报错。
- 同一 `chunk_id` 跨路出现时，`logical_chunk_id/document_id/content/standard/clause/page`
  等关键身份必须一致，否则抛 `CandidateConflictError`，不任意选择一份。
- `score/rank/retrieval_source/score_type/index_name` 是分路检索差异，不作为身份冲突。

## RRF

公共策略值为 `rrf`，默认且当前唯一合法公开权重为 0.5/0.5：

```text
score(d) = wk / (60 + keyword_rank(d))
         + wv / (60 + vector_rank(d))
```

未被某一路召回时该路贡献为 0。RRF 不读取 BM25 或 cosine 原始分数；结果是倒数排名融合值，
不是概率，也不归一化到 0～1。内部纯函数支持合法的非负、和为 1 的权重用于算法测试，
但冻结的 `HybridSearchRequest` 明确拒绝 RRF 非默认权重，因此公开服务不能暴露该能力。

## Min-Max 加权融合

任务书称其为 `weighted_sum`，但冻结公共枚举的真实合法值是
`weighted_normalized`。实现严格使用后者，不添加别名或修改 Schema。BM25 和 cosine
分数分别按当前候选范围归一化：

```text
normalized = (score - branch_min) / (branch_max - branch_min)
hybrid = keyword_weight * normalized_keyword
       + vector_weight * normalized_vector
```

- 两路分数均是越大越相关，且绝不放在同一范围归一化。
- 只有一个候选或该路所有分数相同时，已召回候选的归一化值为 0.5。
- 未被该路召回的候选贡献为 0；该路无候选时整路贡献为 0。
- 权重必须有限、非负、不能同时为 0，并且和为 1。
- NaN/无穷源分数或融合分数会明确报错。

Min-Max 分数依赖本次查询的候选范围，不是置信概率，也不能跨查询比较；它与 RRF 分数没有
相同数值语义。更高级的分数校准不属于 V1。

## 排序与结果映射

两种策略均按融合分数降序排列；同分按 `chunk_id` 升序，截取 `top_k` 后将 `rank` 从 1
连续重排。结果保留选定候选的 Chunk、文档、标准、条文和页码字段，并设置：

- `retrieval_source="hybrid"`
- RRF：`score_type="rrf"`
- Min-Max 加权：`score_type="min_max_weighted_sum"`
- `index_name="hybrid(keyword=<ES index>;vector=<Milvus collection>)"`

公共 `RetrievalResult` 没有两路原始分数/排名、双索引字段或 `source_refs` 字段，因此 V1
不会伪造这些字段；分路证据只存在于本次调用的内部候选账本。两路公共结果本身也不携带
Chunk 的完整来源引用，这是现有契约限制。

## 示例

```python
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    KeywordSearchRequest,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service

hybrid = create_hybrid_retrieval_service(keyword_service, vector_service)
results = hybrid.search(
    HybridSearchRequest(
        keyword=KeywordSearchRequest(
            query="设备基础检修空间",
            top_k=10,
            index_name="engineering-rag-chunks-v1",
        ),
        vector=VectorSearchRequest(
            query="设备基础检修空间",
            top_k=10,
            index_name="engineering_rag_chunks_v1",
        ),
        fusion_strategy=FusionStrategy.RECIPROCAL_RANK_FUSION,
        candidate_k=50,
        top_k=10,
    )
)
```

连接真实两路服务的完整示例：

```bash
ELASTICSEARCH_URL=http://127.0.0.1:9200 \
MILVUS_URI=http://127.0.0.1:19530 \
python examples/hybrid_retrieval.example.py
```

示例假定相应 Elasticsearch Index 与 Milvus Collection 已完成同一 ChunkBatch 的入库，不会
自动启动 Docker 或写索引。

## 版本、测试与已知限制

公共检索 Schema 为 `1.0`；模块实现版本为首个 Hybrid V1。相同请求和相同两路有序结果会
产生确定输出。

```bash
python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q
python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q
python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q
python -m pytest -q
ruff check .
ruff format --check .
```

当前没有经过人工核验、适用于真实检索相关性评价的 Golden Dataset，因此没有声称 RRF 或
Min-Max 哪一个效果更好。后续评估至少需要 query、相关 `chunk_id`、相关等级和标准版本身份，
再计算 Recall@K、MRR 与 nDCG@K。
