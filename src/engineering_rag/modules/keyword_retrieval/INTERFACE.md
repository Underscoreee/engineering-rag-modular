# Keyword Retrieval 接口

## 职责与非职责

维护关键词索引并执行关键词搜索。不负责 Chunking、向量化、融合或生成；Task 0 不接入 Elasticsearch/BM25。

## 公开接口

导入路径：`engineering_rag.modules.keyword_retrieval.api`。

```python
class KeywordRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: KeywordSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...
```

搜索要求非空 query、`top_k > 0`；过滤与字段权重均结构化。结果按 rank 升序、rank 从 1 开始，`score_type` 必须声明，分数仅在相同实现/查询内解释。

## 失败、副作用与幂等性

索引与删除有副作用。`operation_id` 是重试幂等键；同键同载荷不可重复写入，同键不同载荷应冲突。`IndexResult` 可表达逐 Chunk 失败；空命中返回空列表，索引不存在应报 not-found，二者不同。删除不存在文档可返回 0，但必须报告 `index_existed`。

## 依赖、版本与示例

后端客户端仅可存在于本模块 internal 并由组合层注入配置。API 版本 1，Schema `1.x`。

```python
# 接口示例，service 为未来注入实现。
results = service.search(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q`。

