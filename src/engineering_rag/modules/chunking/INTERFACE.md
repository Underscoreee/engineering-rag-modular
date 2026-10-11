# Chunking 接口（消费 Document V2.4）

## 职责与非职责

未来 Chunker 仅消费已结构化的 V2.4 `Document`，依据 Clause 有序内容、顶层 Table 引用和来源 Block 构建 `ChunkBatch`。Task 0.1 没有切分算法。Chunker 不执行 PDF/OCR、章节或条文识别，也不合并跨页表格或写检索索引。

## 公开路径与签名

`engineering_rag.modules.chunking.api` 重导出唯一的 `engineering_rag.contracts.protocols.ChunkingService`：

```python
class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...
```

输入 `document` 必须通过 V2.4 校验；`ChunkingConfig.strategy_id` 和 `max_tokens>0` 必填，`overlap_tokens` 默认为 0 且小于上限。输出 `ChunkBatch` 保留现有 1.0 契约：批次 Document ID、策略/版本及物理/逻辑 Chunk ID、页码、来源引用；不携带 embedding 向量。

## 校验、错误和部分成功

无效输入、配置或悬空来源应明确失败。对 `processing.partial=true`，未来实现须明确拒绝或仅处理已确认内容并记录范围，不得把未处理页当空白，也不得返回伪成功批次。空 ChunkBatch 不能单独证明完整切分；未聚合表格片段不能当作完整表格。

## 副作用、幂等、排序与依赖

`chunk` 无外部写副作用；同一 Document、配置及实现版本应可重复。输出遵循 Clause 内容顺序及页面阅读顺序。`chunk_id` 是物理片段，`logical_chunk_id` 是逻辑单元。实现仅依赖 contracts 和自身 internal；Parser 与 Chunker 由组合入口注入，不导入对方 internal。

## 接口示例与版本

```python
# 接口示例：chunker 是未来注入实现，本仓库没有切分算法。
batch = chunker.chunk(document, config)
```

Python API 版本 1；输入 Document Schema 2.4，输出 ChunkBatch Schema 仍为 1.0。Chunk 输出契约未来若变更须单独升级版本和 ADR。

独立测试：`python -m pytest src/engineering_rag/modules/chunking/tests -q`。
