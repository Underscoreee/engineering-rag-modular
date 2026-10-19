# Vector Retrieval 接口

## 职责与边界

本模块将 `ChunkBatch.embedding_text` 编码后持久化到 Milvus，提供 COSINE 向量检索、公共
元数据过滤和按文档删除。它不拆分或修改 Chunk，不解析 PDF，不调用 Elasticsearch，也不
执行融合、Rerank、查询改写或生成。公共 DTO/Protocol 只来自 `engineering_rag.contracts`；
Milvus、模型和向量均为模块私有实现。

## 安装与配置

```bash
python -m pip install -e '.[dev,vector-retrieval]'
```

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `MILVUS_URI` | 无 | 工厂创建客户端时必填 |
| `MILVUS_TOKEN` | 无 | 可选认证 token，不写日志 |
| `ENGINEERING_RAG_VECTOR_COLLECTION` | `engineering_rag_chunks_v1` | 默认 Collection |
| `ENGINEERING_RAG_MILVUS_TIMEOUT` | `30` | 超时秒数 |
| `ENGINEERING_RAG_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 模型标识 |
| `ENGINEERING_RAG_EMBEDDING_REVISION` | `7999e1d…a620` | 固定模型 commit revision |
| `ENGINEERING_RAG_EMBEDDING_DEVICE` | `cpu` | 推理设备 |
| `ENGINEERING_RAG_EMBEDDING_CACHE_DIR` | 标准缓存 | 模型缓存 |
| `ENGINEERING_RAG_EMBEDDING_BATCH_SIZE` | `32` | 编码批大小 |
| `ENGINEERING_RAG_EMBEDDING_DIMENSION` | 模型实测值 | 可选维度断言 |
| `ENGINEERING_RAG_VECTOR_WRITE_BATCH_SIZE` | `128` | upsert 批大小 |
| `ENGINEERING_RAG_VECTOR_MAX_TOP_K` | `100` | 查询上限 |

导入模块不会连接数据库或下载模型。默认 Provider 在首次编码时惰性加载并复用模型。工厂
拥有的客户端由上下文管理器或 `close()` 关闭；注入客户端由调用方管理。

## 公开 API

导入路径：`engineering_rag.modules.vector_retrieval.api`。

```python
class VectorRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: VectorSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...


def create_vector_retrieval_service(
    config: VectorRetrievalConfig | None = None,
    *,
    client: MilvusClientProtocol | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> MilvusVectorRetrievalService: ...
```

`client/provider` 是模块内部依赖注入点。生产默认使用官方 `pymilvus` 和
`SentenceTransformerEmbeddingProvider`，单元测试使用确定性替身。

## Embedding 与兼容性

- 文档严格使用 `Chunk.embedding_text`；不序列化完整 Chunk、不修改语义内容。
- 默认 BGE small zh v1.5、CPU、归一化，真实输出 512 维。
- 查询使用可配置中文检索指令；文档不加查询前缀。
- 每批校验数量、维度和有限值，不生成零向量或截断。
- 请求携带 `embedding_model_id` 时必须匹配当前 Provider。

Collection 私有版本为 `vector-collection-v1`，名字须匹配
`^[A-Za-z_][A-Za-z0-9_]*$`。Schema 包含：`chunk_id` 主键、FLOAT_VECTOR、原始 content、
文档/逻辑 Chunk 身份、标准/Clause/页码/三态字段，以及 JSON 形式的
`source_refs/source_block_ids/section_path/provenance`。过滤字段建立 INVERTED 索引；向量使用
HNSW（M=16、efConstruction=200）和 COSINE。

模型 ID/revision、真实维度、归一化、查询指令、度量和 Schema 版本保存在 Collection
description。复用前还校验完整字段集合、向量维度和 `chunk_id` 主键。任一不兼容均报错，
不自动删除 Collection；即使维度相同也不混用不同模型。

## 索引、检索与删除语义

`index()` 对非空批次分批编码、严格按顺序配对并 upsert。重复 `chunk_id` 不产生副本。
`replace_document=True` 时，全部新行确认成功后才以强一致查询删除同文档的陈旧主键；写入
失败不清理旧数据。空批次返回零计数且无副作用。Milvus RPC 无逐条失败明细时直接抛明确
异常，不能伪造完全成功。

`search()` 只编码查询一次，使用 HNSW `ef=64`、COSINE 和 `Strong` 读取。支持
`SearchFilters` 全部字段：document、标准代码、版次、条文号、内容类型、说明状态和强制性
三态。同字段多值为 IN，不同字段为 AND；字段来自白名单，值按 JSON 字面量安全转义。
返回真实相似度，按降序排列，`rank` 从 1 开始，`retrieval_source="vector"`、
`score_type="cosine_similarity"`，不转换为 BM25 分数。

Task 7.0.1 的结果契约为 `RetrievalResult 2.0`。`OUTPUT_FIELDS` 从既有 entity 读取
`is_explanation/content_type/mandatory_state`；前两项缺失时为 null，类型/枚举非法时报错。
mandatory_state 仅接受严格整数 -1/0/1，分别返回 null/false/true；缺字段表示未知，
存在但为 null、bool、字符串、浮点或其他整数则抛 VectorResponseError，不使用 bool(state)。
只增加结果投射，Collection Schema、查询过滤、Embedding、COSINE、top_k、排序均不变。

`delete_document()` 只删除转义后的精确 `document_id`；Collection 不存在返回
`index_existed=false`。配置、依赖、模型、向量、Collection 缺失/冲突、连接、后端与响应
错误均明确区分，基础设施失败不会伪装为空命中。

公共 `RetrievalResult` 当前没有 `source_refs/source_block_ids` 字段，因此来源完整保存在
Milvus entity，但返回只能投射契约已有字段。单文档快照查询当前上限 16384 个 Chunk；更大
文档需后续增加 query iterator。V1 不做跨 Collection 迁移。

## 示例与测试

```python
with create_vector_retrieval_service() as service:
    service.index(batch, IndexRequest(index_name="engineering_rag_chunks_v1", operation_id="i-1"))
    results = service.search(
        VectorSearchRequest(query="混凝土承载力", top_k=10, index_name="engineering_rag_chunks_v1")
    )
```

完整虚构示例：`python examples/vector_retrieval.example.py`。

```bash
docker compose -f docker-compose.milvus.yml up -d
curl -fsS http://127.0.0.1:9091/healthz
python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q
MILVUS_URI=http://127.0.0.1:19530 \
  python -m pytest -vv -rs tests/integration/test_vector_retrieval_integration.py
NO_PROXY=127.0.0.1,localhost MILVUS_URI=http://127.0.0.1:19530 \
ENGINEERING_RAG_RUN_REAL_EMBEDDING=1 \
  python -m pytest -vv -rs tests/integration/test_vector_embedding_smoke.py
docker compose -f docker-compose.milvus.yml stop
```

Milvus、etcd、MinIO 使用命名卷；`stop` 不删除数据。测试 Collection 使用 UUID，只清理精确
名称。禁止 `down -v`。服务关闭认证且仅绑定回环地址，只能用于本机测试。未启用的真实测试
会 skip，不能报告为 PASS。Chunk、请求及索引/删除结果仍为 `1.0`，RetrievalResult 为 `2.0`。
当前 Collection 已保存来源字段，无需迁移数据库；新读取器支持历史结果 JSON 1.0，
旧严格消费者不支持新增字段，须协调升级。版本与持久化政策见
[RetrievalResult V2 ADR](../../../../docs/adr-retrieval-result-v2.md)。
