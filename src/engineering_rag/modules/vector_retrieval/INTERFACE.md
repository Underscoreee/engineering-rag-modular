# Vector Retrieval 接口

## 职责与非职责

维护向量索引并以查询文本搜索；embedding 属于未来模块内部行为。它不拆分文档、不执行关键词检索或融合；Task 0 不接入模型/Milvus。

## 公开接口

导入路径：`engineering_rag.modules.vector_retrieval.api`。

```python
class VectorRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: VectorSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...
```

请求含查询文本、正整数 top_k、过滤器、索引名和可选模型 ID。结果按 rank 升序，必须标明向量分数类型；不得假设与 BM25 分数同尺度。

## 失败、副作用与幂等性

索引/删除副作用、`operation_id` 幂等与部分失败规则同关键词模块。空命中不是索引不存在。模型或索引版本不匹配应显式失败，不得静默换模型。

## 依赖、版本与示例

仅依赖 contracts、本模块 internal 和经注入的未来适配器。API 版本 1，Schema `1.x`。

```python
# 接口示例，service 为未来注入实现。
results = service.search(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q`。

