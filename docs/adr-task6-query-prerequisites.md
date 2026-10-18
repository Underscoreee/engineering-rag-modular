# ADR-Q-001：Query 处理意图与依赖契约

- 状态：**Adopted（Task 6.0.1 授权范围）**。
- 日期：2026-10-18。
- 上下文：[Task 6.0 审查](query-task6-interface-audit.md)、[数据流](query-task6-dataflow-design.md)、[路线](query-task6-roadmap.md)。
- 本次只落地 DTO、Protocol、纯校验/显式迁移及离线测试，不提供 Query 服务业务流程。

## 1. 双维度意图与局部主版本升级

`QueryIntent` 五个值保持原样：fact_lookup、requirement、comparison、explanation、unknown，
表示问题的语义意图；它们不与获取性/探索性一一对应。新增独立 `ProcessingIntent`，仅有
acquisition、exploratory。`RetrievalPlan.processing_intent` 必填、不可为 null、不设默认值，
不得从旧语义意图推断。Semantic unknown 依然合法，但 processing unknown 不合法。

RetrievalPlan 和含该计划的 QueryResult 同步使用 Literal `schema_version="2.0"`；
QueryResult 仍只有 schema_version、plan、evidence，没有增加警告或澄清字段。
QueryRequest/QueryOptions 字段不变；共享 SCHEMA_VERSION、检索/Chunk 版本仍为 1.0，
Document 仍为 Frozen 2.4。以 Query 局部常量 QUERY_SCHEMA_VERSION 管理此次变更，
不能全局改 common.SCHEMA_VERSION 牵动其他模型。

选择主版本升级的原因：严格旧读取方会拒绝 processing_intent；新增必填项也无法无损从旧数据
推断。只改版本默认字符串不足以保证正确性，因此新版读取器拒绝显式 V1，且缺少处理意图
时拒绝构造新版计划。未显式传版本的新版 Python 构造仍默认 2.0，但必须提供处理意图。

### 显式迁移

[query_migrations.py](../src/engineering_rag/contracts/query_migrations.py) 提供：

```python
migrate_retrieval_plan_v1(payload, *, processing_intent) -> RetrievalPlan
migrate_query_result_v1(payload, *, processing_intent) -> QueryResult
```

payload 为已解析的旧 JSON Mapping。函数使用私有严格 V1 读取模型，保留原问题、改写、HyDE、
语义意图、检索请求与证据，要求调用方显式给出有依据的处理意图，不写文件、不推理。
旧模型允许省略默认 schema_version，迁移读取器也接受；未知版本、混用新字段、额外字段或非法
旧模式/请求组合拒绝。迁移不会自动用于 model_validate，也不写回原输入。调用方应另存新版
Artifact 并记录意图决定依据，旧文件保持只读；没有决定依据时保留 V1，不能编造 acquisition。

新版 QueryResult 内的 RetrievalResult 仍是检索 1.0，不能把所有嵌套版本一起改成 2.0。
严格旧消费者即使不检查版本，也会拒绝新字段；不提供“删字段降级”来假称语义无损。
消费 QueryResult 的上层与后续 Orchestrator、序列化读取方需要协调升级；QueryRequest、
Hybrid、Keyword、Vector 的请求与执行逻辑无需调整。不存在需要新增的 RetrievalRequest。

## 2. 供应商无关 StructuredLLMClient

DTO 位于 [llm.py](../src/engineering_rag/contracts/llm.py)，Protocol 统一位于
[protocols.py](../src/engineering_rag/contracts/protocols.py)，根 contracts 重导出。
这是未来 Query 与 Generation 都可使用的跨模块生成基础能力，因此放在全局 contracts；
意图识别结果、Prompt、改写保护项仍应留在未来 Query 内部。

```python
class StructuredLLMClient(Protocol):
    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse: ...
```

| 类型 | 主要字段与语义 |
| --- | --- |
| StructuredLLMConfig | config_id、model_id、可空 model_revision、temperature=0、必填正 timeout_seconds/max_output_tokens |
| StructuredLLMRequest | Literal 1.0、request_id、stage、input JSON 对象、output_schema JSON 对象、config、可空 trace |
| StructuredLLMResponse | Literal 1.0、回传 request_id、实际 model_id/可空 model_revision、data JSON 对象、可空 usage/provider_request_id |
| LLMTokenUsage | 可空 input_tokens/output_tokens/total_tokens；未知用 null，0 只表示已知为零；非负严格整数，三项都已知时校验总数 |

端点、认证和 SDK 配置归后续基础设施适配器，由组合根注入，不进入 DTO。配置的模型标识是
调用方选择的标识，不指定真实供应商；实际后端标识需由适配器显式映射并如实验证，不可伪造版本。

### 两层验证边界

构造 Response 只表示 JSON 传输 DTO 合法，**不表示输出满足任务 Schema 或业务事实正确**。
调用方必须用 `response.validate_output(request, OutputModel)` 生成业务 DTO：

1. 重新校验 Response，绑定 request_id、model_id 与显式要求的 revision。
2. 要求 request.output_schema 等于 OutputModel.model_json_schema()，防止更换验证目标。
3. 要求 OutputModel 使用 extra=forbid，严格校验 JSON 类型和输出字段。
4. 后续 Query 再验证原文依据、范围匹配和工程语义。类型校验不能代替事实核验。

首版接受应用 Pydantic 模型生成的 Schema，不实现任意 JSON Schema 解释器；未引入 jsonschema
或任何模型 SDK。JSON 无效/Schema 失败使用 Pydantic ValidationError，响应绑定失败使用
ValueError。未来适配器需以 TimeoutError、ConnectionError 或保留原因的调用异常报告模型
失败，不能返回伪造的合法 data。本任务没有预建大量未使用的异常类。

每次 generate 表示一次模型尝试；超时和 Token 是请求预算，不是本 DTO 能执行的限流器。
重试在后续显式有界编排中处理，不在 Protocol 中隐藏无限重试。真实供应商、Prompt、数据
传输政策、模型能力/温度支持和资源关闭方式由后续适配任务决定。

## 3. 可信标准目录 StandardMetadataCatalog

DTO 位于 [catalog.py](../src/engineering_rag/contracts/catalog.py)。目录映射是标准身份的
共享能力，可供未来组合/查询范围验证复用，放入公共 contracts；没有实现生产目录或匹配算法。

```python
class StandardMetadataCatalog(Protocol):
    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch: ...
```

| 类型 | 主要字段与约束 |
| --- | --- |
| CatalogIndexScope | keyword_index + vector_collection，表示同一知识库的一对索引 |
| StandardMetadataRecord | record_id、既有 StandardMetadata（代码/名称/版次/修订）、aliases、可空 document_id、indexed_scopes |
| StandardMetadataLookup | request_id、scope；可选 standard_code/name、edition、revision、显式 document_id、trace；至少有代码、名称或 ID 一个选择条件 |
| StandardMetadataMatch | Literal 1.0、request_id、catalog_id、snapshot_id、必填 is_test_fixture、status、candidates、可空 reason |

status 固定 unique/ambiguous/not_found/unavailable，分别要求 1 个、至少 2 个、0 个、0 个
候选。可用结果必须声明 snapshot_id；不可用必须给 reason，不能伪装 not_found。
成功候选必须有可信 document_id 和入库范围，身份不能重复。

已知全球标准可以有 record，但 indexed_scopes 为空时不表示已收录；document_id 也不能根据
LLM 输入创造。`validate_for(lookup)` 绑定请求、检查当前知识库索引对、代码/版次/修订/ID
的精确一致性及名称/可信别名映射；不允许仅因全局名称有效就返回可过滤的在库候选。
规范化应由未来受控适配器明确实施，首版契约校验不做隐含模糊匹配。

快照是可信适配器的声明而非在线健康证明；生产适配器需要保证快照与双索引入库事实一致。
本接口**不提供条文存在性验证**，没有 clause 字段或“全部条文已收录”暗示。后续确需条文
核验时必须另行定义证据来源/能力，不能用目录匹配成功推断条文存在。

测试目录仅在 tests/contracts 中以少量 TEST 编号和虚构记录实现，响应显式 is_test_fixture=true。
该标记是来源声明而非真实性鉴定器，真实调用方仍应只注入可信来源；本任务没有生产目录数据、
全量国家标准表或数据文件格式。生产源、更新/复核机制、知识库同步政策仍未决定。

## 4. 已采纳、待后续实现的业务政策

- 首版 Query 仅通过 HybridRetrievalService.search 检索；keyword/vector 在 DTO 中保留，
  未来实现遇到它们明确报 unsupported，不自动切换或用零权重/空分支模拟。
- LLM 只提供候选，经过格式、原文依据、可信目录验证后才构造过滤；显式范围不得扩大。
  模型不得生成可信 document_id 或数据库 DSL。
- 范围求交为空必须中止，不能将空数组当作“无约束”；同一可信范围复制到两路。
- 显式标准未匹配、歧义、目录不可用/无法必要验证、结构化输出非法、LLM 调用失败、
  Hybrid 失败应与正常无命中区分；未来 Query 用最小异常类型及错误码，保留原始原因。
- 首版 QueryResult 不新增警告/澄清字段；正常无命中才允许空 evidence，其他失败走异常。
- 真实检索结果才是证据，HyDE 从来不是规范原文，后续实现不能将它作为引用。

这些是正式政策，**本次没有编写 Query Understanding、改写、扩展、HyDE、plan 或 execute**。

## 5. Task 6.1 条件与未决事项

已满足：双意图公共表示、显式旧版迁移、LLM DTO/Protocol 与校验边界、目录 DTO/Protocol
与离线夹具、Hybrid-only 和范围异常政策。6.1 可以基于注入替身独立开发和验收接口逻辑。

真实模型验收仍需独立明确供应商/模型适配器、数据传输政策、运行配置；真实范围匹配仍需
可信生产目录及其与入库快照的同步。它们不阻塞本次契约验收，但会阻塞真实集成的通过声明。
Query 意图/相关性人工金标仍需 6.5 建设。下一阶段须由维护者单独启动。
