# ADR-RR-001：RetrievalResult 2.0 来源元数据与兼容策略

状态：Adopted（维护者授权 Task 7.0.1）；日期：2026-10-19。

## 决策

仅升级唯一的 `engineering_rag.contracts.RetrievalResult` 为 `schema_version="2.0"`：

| 字段 | 类型及默认值 | 来源含义 |
| --- | --- | --- |
| is_explanation | 严格 bool 或 null，默认 null | true 为已标记条文说明；false 为明确非说明；null 未知 |
| is_mandatory | 严格 bool 或 null，默认 null | true/false 为上游明确判定；null 未判定 |
| content_type | 既有 ChunkContentType 或 null，默认 null | 保留 Chunk 类型，不另建枚举 |

布尔字段不接受字符串或数字，不根据编号、文本、页码、ID 推断。非法枚举显式失败。
Document Frozen 2.4、Chunk 1.0、请求、IndexResult/DeleteResult、Protocol、Query 外层 2.0、
GenerationRequest 结构和全局 `SCHEMA_VERSION="1.0"` 均不变。

## 读取、写出与迁移

- 新建对象与未声明版本的输入默认 2.0；正常序列化只输出 2.0。
- 显式 1.0 且没有新字段的历史证据，通过同一模型的读取桥转换为 2.0，三个缺失属性均为 null。
  转换不修改输入字典，嵌套 QueryResult/GenerationRequest 走相同读取路径。
- 1.0 携带任一新字段属于混合格式，拒绝；未知版本拒绝，不回退猜测。
- 已发现历史持久化证据：`examples/retrieval.example.json` 及 Task 6.5/6.6 评估运行 JSON。
  原文件保持只读，读取时转换，不进行目录批量重写。新版虚构示例为
  `examples/retrieval.v2.example.json`。
- 需要另存历史记录时，显式调用 `migrate_retrieval_result_v1(payload)`，校验后由调用方另存
  新文件；该函数无 I/O、不回填未知值、不创建第二套 DTO。

```python
from engineering_rag.contracts import RetrievalResult, migrate_retrieval_result_v1

# historical_payload 为合法的显式 1.0 记录。
# migrated = migrate_retrieval_result_v1(historical_payload)
# new_json = migrated.model_dump_json()  # 2.0；不会写回原文件
# restored = RetrievalResult.model_validate_json(new_json)
```

旧消费者使用 `extra='forbid'`，可能拒绝新字段，也可能拒绝新版本。因此不声称新格式可被
旧消费者读取；Keyword/Vector/Hybrid、Query evidence 消费方、Generation 调用方、评估读取器
须协调升级同一 contracts 包。Query/Generation 外层形状不变不代表旧嵌套读取器兼容。
未发现仓库外消费者清单；部署前维护者仍需确认。没有实际旧版本写出需求，不提供会丢失
来源语义的 V1 writer，也不保留长期并行 DTO。

## 返回映射与融合

Elasticsearch 现有 `_source` 含两个 boolean 和 keyword content_type。缺失/null 保留未知，
非法值以 KeywordResponseError 失败；不改 Mapping、查询或重建索引。

Milvus 现有字段为 BOOL is_explanation、INT8 mandatory_state、VARCHAR content_type。
OUTPUT_FIELDS 请求这三项。严格整数 mandatory_state：-1→null，0→false，1→true；字段缺失
为 null，存在但为 null、bool、浮点、字符串或其他整数均报 VectorResponseError。其他两个字段
缺失/null 为未知，非法非空类型失败。不改 Collection、模型、向量、索引和搜索参数。

Hybrid 沿用既有候选合并器与异常类型，逐字段执行：相同已知保留；已知+未知取已知
（包括 false）；都未知取 null；不同已知抛 CandidateConflictError。输入对象不被修改。
不改变候选去重、BM25/COSINE、RRF、Min-Max、权重、top_k 或排序。

Query 原有 execute 直接传递公共对象，无需改业务代码。离线评估 FixtureRetrieval 的
Chunk→证据构造同步映射，固定排序/分数不变；它不代表真实数据库或真实 LLM 验证。

## 验证与限制

独立映射、兼容性、冲突与分数不变性测试，以及 Query.execute→JSON→GenerationRequest
离线契约测试覆盖上述约定。真实后端只读检查另行记录，不执行入库、删除、LLM 或生成。
既有 RetrievalResult 仍无 source_refs/source_block_ids，不在本任务扩充；数据库/Chunk
继续保存它们。本 ADR 不解决 Generation 业务实现、引用生成及未核验 Parser 内容质量。

实际测试与验收见 [Task 7.0.1 报告](task-7.0.1-retrieval-source-metadata.md)。
