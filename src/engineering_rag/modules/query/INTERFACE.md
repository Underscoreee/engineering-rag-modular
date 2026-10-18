# Query 接口

## 职责与非职责

`plan()` 形成结构化检索计划；`execute()` 通过注入的 Hybrid Protocol 检索。
Task 6.1 已实现独立的内部 Understanding（见下节）；公开入口仍只有 Protocol 与 DTO，
没有可实例化的完整 QueryService 或工厂。Rewrite、Expansion、HyDE、plan/execute 均未实现。

## Task 6.1：内部 Understanding（已实现）

此入口供 Query 内部后续阶段与独立测试使用，不是供其他业务模块绕过公开 API 的新契约：

```python
from engineering_rag.modules.query.internal.config import UnderstandingConfig
from engineering_rag.modules.query.internal.understanding import QueryUnderstanding

# llm、catalog 由组合层通过公共 Protocol 注入；没有默认真实适配器。
# llm_config 是 StructuredLLMConfig；scope 是 CatalogIndexScope（可信部署配置）。
understanding = QueryUnderstanding(
    llm=llm,
    catalog=catalog,
    config=UnderstandingConfig(llm=llm_config, scope=scope),
)
result = understanding.understand(request)  # QueryRequest -> UnderstandingResult
```

输入复用 QueryRequest，问题不可空白；不截断原问题。默认预算：问题 8000 字符、历史
8 条/合计 16000 字符、每项列表过滤 32 值、目录最多 128 次查询，超限明确失败。
`max_attempts=2`（可设 1），输出纠正与超时/连接重试共享预算；适配器必须遵守
StructuredLLMConfig 的超时/token 预算且不得内部隐藏重试。本阶段不执行 mode/top_k 检索。

输出是严格的私有 Pydantic 类型，包含 processing_intent、新 SearchFilters、索引对 scope、
完整 catalog_matches（含目录/快照/测试标记）、decisions（候选及原文区间、采用/拒绝/忽略原因）、
attempts（请求 ID、耗时、状态、可空用量）、diagnostics/degraded、模型/配置/提示版本。
semantic_intent 保持 unknown；clause_existence_verified 始终 false。结果可 JSON 往返。

调用流程：结构化 LLM → validate_output → 原文证据核对 → validate_for 目录核验 → 范围求交。
两类处理意图由结构化模型决定，不用关键词代替理解；本地词形检查仅用于过滤候选证据。
模型不允许输出 document_id。代码/名称/可信别名/版次/修订经目录解析成已入库文档身份；
多个标准分别验证，用 document_ids 保留标准与版次的配对。调用方提供的文档/标准范围也核验，
已核验的调用方唯一文档可以消除版本歧义。仅有 edition 的调用方过滤可保留，但不构成身份证明。

证据使用 Python 字符偏移 [start,end)，quote 必须与原始用户文本完全一致，候选值须位于
对应证据中。不得拼接不同轮次的标准属性；助手历史不是可信范围。保守首版不自动采用历史
推断的精确过滤：本轮有范围则忽略旧候选并留诊断，仅有历史标准而无明确/已验证范围则要求
澄清。模型遗漏明显标准代码时拒绝无约束成功；该 guard 不是完整标准注册表。

列表同字段 OR、跨字段 AND，与已有条件求交，空交集报错；布尔 null 不筛选，不等于 false。
只有明确的“条文说明/强制性条文”等证据才能产生对应筛选，不根据应/必须推断强制性。
条文只验证格式、原文和文档范围，不验证存在性。输入及调用方 filters 不被修改。

错误：内部 `UnderstandingError.code` 区分 input_budget、invalid_output、invalid_evidence、
model_failure、unmatched_scope、ambiguous_scope、catalog_unavailable、scope_conflict。
错误附 attempts/decisions/catalog_matches，真实异常通过 __cause__ 保留。失败不生成成功结果，
也不通过清空 filters 降级。测试目录默认拒绝，仅离线测试显式 allow_test_catalog=True。

副作用仅限注入能力的有界调用；不读写索引/文件、不连接数据库，不默认记录问题或历史。
相同候选和目录快照下范围合并稳定；模型输出、随机关联 ID 和耗时不承诺逐字一致。
服务不持有逐请求可变状态，配置深拷贝；客户端和目录的生命周期/并发安全由注入方负责。
私有结果含原文证据，应受控保存，不应当作普通日志输出。

实际实现、保守策略及离线验收见
[Task 6.1 说明](../../../../docs/task-6.1-query-understanding.md)。

## 公开接口

导入路径：`engineering_rag.modules.query.api`。

```python
class QueryService(Protocol):
    def plan(self, request: QueryRequest) -> RetrievalPlan: ...
    def execute(self, request: QueryRequest) -> QueryResult: ...
```

输入 QueryRequest 保持原字段：question、history、filters、options、trace；
QueryOptions 仍接受 keyword/vector/hybrid，默认 hybrid，top_k 默认 10。

RetrievalPlan 使用 Literal `schema_version="2.0"`，含 original_question、rewritten_queries、
hypothetical_document、原有语义 intent、**必填 processing_intent**、retrieval_mode、
hybrid_request。语义 QueryIntent 五类保持不变；ProcessingIntent 只接受 acquisition/exploratory，
缺失、null 或 unknown 都拒绝，不能根据旧 intent 猜测。

QueryResult 使用 Literal `schema_version="2.0"`，仍只有 plan 与 evidence；evidence 内
RetrievalResult 保持检索 1.0。没有新增 warnings、clarification 或其他结果字段。

两路查询分别在 hybrid_request.keyword.query 与 vector.query；它们可不同，过滤按同一已验证
范围复制。candidate_k 仍是每路共享召回数，Hybrid 覆盖子请求 top_k；最终 top_k 独立。
RRF 公共权重只允许 0.5/0.5，可变权重使用 weighted_normalized。详见 Hybrid 接口。

## 失败与执行语义

已采纳的首版执行政策：只支持 hybrid，其他 mode 在未来服务中明确报 unsupported，不能
自动改 mode 或用零权重模拟。现有 DTO 没有删除单路值，也没有在本次提前实现模式判断。

LLM 只能抽取候选；格式与原文依据验证后，以可信目录匹配标准/版本/document_id。
显式范围不得扩大；交集为空须报 scope conflict，不能传空数组解除限制。未匹配、歧义、
目录不可用、输出非法、模型失败、Hybrid 失败均走明确异常，保留原因，不伪装空 evidence。
Understanding 已使用上述最小异常体系；后续检索执行失败尚未实现。

plan 不检索，但未来可以产生有预算的 LLM 调用；execute 只读检索，不写数据库。
相同模型输入不承诺逐字确定，需记录配置与提示版本。当前 Protocol 没有 execute(plan)，
外部先 plan 再 execute(request) 可能重新规划。

## 依赖、版本与示例

公共依赖唯一来源是 engineering_rag.contracts。query.api 重导出 QueryService、ProcessingIntent、
QueryIntent、QueryRequest/Result、RetrievalPlan、StructuredLLMClient、StandardMetadataCatalog
以及两个迁移函数。Query 内不得导入其他业务模块的具体实现、internal 或数据库客户端。

新增依赖能力（均只有声明，没有真实适配器）：

```python
class StructuredLLMClient(Protocol):
    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse: ...


class StandardMetadataCatalog(Protocol):
    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch: ...
```

LLM 请求携带 stage、JSON input、Pydantic 模型生成的 output_schema、模型配置、超时、
Token 预算和可空 trace；响应的 data 必须经 validate_output(request, OutputModel) 才能
作为结构化业务 DTO 使用。OutputModel 必须 extra=forbid；未知用量为 null，不伪造零。
ValidationError/ValueError 表示输出或绑定校验失败；未来适配器须明确传播调用/超时/连接错误。
端点和密钥由未来适配器管理，不在 DTO 中；本模块没有 SDK、模型下载或直接网络调用。

目录 Lookup 按标准代码/名称/别名、版次/修订或可信显式 ID 查询指定双索引范围，Match 返回
unique/ambiguous/not_found/unavailable、catalog_id/snapshot_id 和 is_test_fixture。
调用方使用 validate_for(request) 校验请求、范围与候选映射；global record 不代表已入库。
目录不支持条文存在性验证。离线夹具在契约/Query 测试中，不能用于生产过滤。

详细字段、验证规则和未决事项见 [ADR-Q-001](../../../../docs/adr-task6-query-prerequisites.md)。

## 版本与显式迁移

QueryService 方法签名不变；计划/结果序列化升级到 2.0，QueryRequest、检索 1.0、Document
Frozen 2.4 不变。旧严格消费者无法读取新字段，升级需协调调用方。

```python
from engineering_rag.contracts import ProcessingIntent, migrate_query_result_v1

# 接口示例：legacy_payload 是解析后的 V1 JSON，decision 来自明确的人工/应用决定。
decision = ProcessingIntent.ACQUISITION
# result_v2 = migrate_query_result_v1(legacy_payload, processing_intent=decision)
```

另有 migrate_retrieval_plan_v1(payload, *, processing_intent)。缺少或非法处理意图时拒绝，
不做自动推断；原语义意图、请求和证据保留。迁移函数只返回新模型，不覆写旧文件。
新读取器不自动接受 V1；更高/未知版本和混合新旧字段拒绝。

```python
# 接口示例，query_service 为未来注入实现；当前不能实际调用。
# plan = query_service.plan(request)  # 不检索
# result = query_service.execute(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/query/tests -q`。

新增契约测试：

```bash
python -m pytest tests/contracts/test_query_v2.py tests/contracts/test_structured_llm.py \
  tests/contracts/test_metadata_catalog.py -q
python -m pytest tests/architecture -q
```

合法虚构 JSON 见 examples/query_result.v2.example.json；不是实际 Query 执行结果。
真实 LLM 供应商、适配器、数据传输政策、生产目录和目录更新方式均未实现/未决定。

