# Hybrid Retrieval 接口

## 职责与非职责

通过注入的 Keyword/Vector Protocol 编排候选与融合。不创建后端客户端、不生成 embedding、不 rerank 或回答；Task 0 不实现 RRF/归一化算法。

## 公开接口

导入路径：`engineering_rag.modules.hybrid_retrieval.api`。

```python
class HybridRetrievalService(Protocol):
    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]: ...
```

请求显式包含两路请求、融合策略、候选数和最终 top_k。加权归一化权重非负且和为 1；RRF 不接收自定义数值权重。结果按最终 rank 升序，分数标为融合后的类型。

## 失败与执行语义

无持久化副作用。未来实现必须定义单路失败是整体失败还是带 warning 的部分结果，并保证不把原始异构分数直接相加。相同后端快照与请求应有确定排序。

## 依赖、版本与示例

构造函数未来只注入 `KeywordRetrievalService` 与 `VectorRetrievalService` Protocol；禁止导入其 internal。API 版本 1，Schema `1.x`。

```python
# 接口示例，hybrid 为未来注入实现。
results = hybrid.search(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q`。

