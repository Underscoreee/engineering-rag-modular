# Chunking 模块接口

Chunking 将通过校验的 Document Schema V2.4 转换成稳定的 Chunk V1。实现采用
Clause-first：Clause 是普通文本的首要逻辑边界，PDF 页面不是 Chunk 边界。

## 职责边界

模块负责：按 `ClauseContent.content_units` 装配正文与列表项；隔离正文/条文说明；为
表格、FormulaGroup 和有可检索图题的 Figure 建立原子子 Chunk；切分超长条文；保留
来源、标准、章节、条号和强制性元数据；为未归入 Clause 的有效正文生成 paragraph
Chunk。

模块不负责 PDF/OCR、MinerU、页面/章节/条文识别、表格或公式重识别、跨页对象合并、
强制性推断、图像理解、Embedding、索引、检索或 LLM。它只依赖公共 `contracts`，不
导入 Document Parser 私有代码，也不产生外部写入。

## 公开 API

所有调用方只从公开入口导入：

```python
from engineering_rag.modules.chunking.api import (
    Chunk,
    ChunkBatch,
    ChunkingConfig,
    ChunkingService,
    Document,
    create_chunking_service,
)
```

`ChunkingService` 的唯一公共能力定义在
`engineering_rag.contracts.protocols`：

```python
class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...
```

`create_chunking_service() -> ChunkingService` 返回当前无状态实现。调用方应依赖 Protocol
或由编排器注入实例，不应导入 `modules.chunking.internal`。

## 输入

`document` 必须是合法的 Document V2.4。Chunker 只处理已声明的 `body` 与
`explanation_body` 页面内容：

- `clauses.normative` 生成 `is_explanation=false`；
- `clauses.explanations` 生成 `is_explanation=true`；
- 同号正文与说明拥有不同 `logical_chunk_id`；
- `content_units` 是权威装配来源，`plain_text` 只保留为合法缓存/兜底，不用于重新识别
  结构；
- partial Document 可以输入；只处理其中已声明且引用完整的内容，不臆造未处理页。

`ChunkingConfig`：

| 字段 | 约束与语义 |
|---|---|
| `strategy_id` | 必填、非空；进入稳定身份计算与批次元数据 |
| `max_tokens` | 正整数，默认实验值 `800`；不是冻结的架构常量 |
| `overlap_tokens` | Chunk V1 固定为 `0`，其他值拒绝 |
| `options` | V1 尚未定义扩展项，必须为空 |

V1 的 token 数由内置、无第三方依赖的确定性估算器计算；它是切分预算和回归指标，
不是特定 Embedding 模型 tokenizer 的承诺。

## 输出契约

`ChunkBatch` 包含 `schema_version="1.0"`、`document_id`、有序 `chunks`、
`chunking_version` 和 `strategy_id`。当前实现版本为 `clause-first-1.0.0`。

每个 `Chunk` 的关键字段为：

- 身份：`chunk_id`（物理片段）、`logical_chunk_id`（逻辑条文/段落）、
  `document_id`、`chunking_version`；
- 文本：`content`、`context_header`、`embedding_text`、`token_count`；
- 类型：`clause | paragraph | table | formula | figure`；旧枚举值 `text/mixed` 仅保留
  契约兼容，本实现不生成；
- 来源：`page_start/page_end`、有序 `source_refs/source_block_ids`；
- 语义：嵌套 `standard`（含 `standard_name/standard_code/edition`）、`section_path`、
  `section_id`、`clause_id/clause_number`、`is_explanation/is_mandatory`；
- 关系：`parent_chunk_id`、`table_id`、`figure_id`、`formula_ids`、
  `related_asset_ids`；
- 超限：`exceeds_max_tokens`。

`embedding_text` 始终等于 `context_header + "\n\n" + content`（无 header 时等于
`content`）。Header 包含规范名/标准号、完整 Section 路径、条文说明标志和条号，不写回
原始 `content`。`is_mandatory` 原样继承，`None` 不会被关键词推断为 bool。

## 边界与原子对象规则

- 正常 Clause 生成一个主要 clause Chunk；body/list_item 保持在同一条文中。
- 跨页 Clause 保持同一 `logical_chunk_id`，页范围从真实 Block 来源计算。
- 超过预算时依次按已有内容单元/自然段、句子、最后 token window 切分；不 overlap。
  物理 `chunk_id` 不同，`logical_chunk_id` 相同。
- 顶层 `LogicalTable` 每个 `table_id` 只生成一个 table Chunk，跨页 fragment 不再次
  拆分。`content` 只序列化 `table_number/title/columns/data/notes`；`raw_grid`、识别状态、
  单元格位置及来源定位继续保留在 Document 或 Chunk provenance，不进入检索正文。
- 一个 FormulaGroup 生成一个 formula Chunk。`content` 只序列化各 Equation 的
  `equation_number/latex` 及共享符号说明的 `latex/content`；Formula/Group ID、识别状态、
  OCR text 等仍由 Document 和 Chunk metadata 追踪，Chunking 不重识别公式。
- 表格或公式超过预算仍保持完整，并设置 `exceeds_max_tokens=true`。
- 有可检索图题的 Image 可生成 figure Chunk；纯图片资产不编造描述。
- 原子 Chunk 与其所属 Clause 共享 `logical_chunk_id`，并用 `parent_chunk_id` 指向第一
  个主要 Clause Chunk；超长条文的兄弟片段不使用 parent 关系。
- body/explanation_body 上未被 Clause 消费的有效 Body 生成 paragraph Chunk；明确的
  重复页眉、页脚纯页码不生成 Chunk。

## 顺序、身份、幂等和来源

输出顺序固定为正文 Clause、条文说明 Clause、未归属段落；Clause 依其首个来源的物理
页和 reading order 排序，原子子 Chunk 按 ContentUnit 顺序稳定生成。ID 由文档身份、
正文/说明作用域、Clause/Block 身份、完整配置摘要与实现版本确定性派生。同一合法
Document、相同配置和相同 `chunking_version` 重复执行，Chunk 顺序、ID、正文及元数据
完全一致。

每个 Chunk 至少有一个 `SourceRef`；`source_block_ids` 必须与其顺序完全一致，bbox 和
物理页直接来自 Document。Chunking 不修改输入 Document，也不访问文件、网络、模型或
数据库。

## 错误和部分成功

以下情况同步抛出 `ValueError`（私有实现可使用其子类），不返回伪成功批次：无效
Document/Config、悬空 Section/Block/Table/Formula/Asset 引用、引用类型不匹配、同一
原子对象被多个 Clause 重复消费、非空未知 `options`。这是纯内存全批次操作；没有持久化
副作用、Checkpoint 或重试语义。partial Document 的“部分成功”仅指对其已声明有效范围
生成一个合法 `ChunkBatch`，不代表未声明页已处理。

## 最小调用示例

```python
from engineering_rag.contracts.chunks import ChunkingConfig
from engineering_rag.modules.chunking.api import create_chunking_service

chunker = create_chunking_service()
batch = chunker.chunk(
    document,
    ChunkingConfig(strategy_id="clause-first-v1", max_tokens=800),
)
for chunk in batch.chunks:
    print(chunk.chunk_id, chunk.content_type, chunk.page_start, chunk.page_end)
```

依赖注入时直接声明 `ChunkingService`，由编排层传入 `chunker`；Parser 不主动调用本模块，
本模块也不写检索索引。

## 版本和兼容策略

- 输入：Document Schema V2.4（FROZEN，未修改）。
- 输出：Chunk / ChunkBatch Schema V1，`schema_version="1.0"`。
- Python 能力接口：`ChunkingService.chunk(Document, ChunkingConfig) -> ChunkBatch`。
- 实现：`chunking_version="clause-first-1.0.0"`。

改变 Chunk 字段或验证语义需升级 Chunk Schema 并更新示例、契约测试和 ADR；改变切分/ID
结果但不改变 Schema 时需升级 `chunking_version`。不得静默迁移旧持久化批次。

## 测试

```bash
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest -q
ruff check .
ruff format --check .
```

9 个可维护 Golden Cases 位于 `evaluation/golden_cases.v1.json`；真实 Document 回归测试
需要仓库内保存产物，并由专用环境变量显式启用。
