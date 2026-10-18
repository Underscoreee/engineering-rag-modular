# Query 接口

## 职责与非职责

`plan()` 形成结构化检索计划；`execute()` 通过注入的 Hybrid Protocol 检索。
当前仍只有 Protocol 与 DTO，没有可实例化的 Query 服务、工厂、意图识别、改写、Expansion
或 HyDE。Task 6.0.1 只准备了类型化依赖和版本迁移，不表示这些业务能力已实现。

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
没有新增尚无调用方的大量 Query 异常类；细分错误由后续业务阶段实现。

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
端点和密钥由未来适配器管理，不在 DTO 中；本任务没有 SDK、模型下载或网络调用。

目录 Lookup 按标准代码/名称/别名、版次/修订或可信显式 ID 查询指定双索引范围，Match 返回
unique/ambiguous/not_found/unavailable、catalog_id/snapshot_id 和 is_test_fixture。
调用方使用 validate_for(request) 校验请求、范围与候选映射；global record 不代表已入库。
目录不支持条文存在性验证。测试夹具只在 tests/contracts，不能用于生产过滤。

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

