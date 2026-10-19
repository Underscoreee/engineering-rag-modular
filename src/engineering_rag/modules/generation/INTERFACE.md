# Generation 接口（Task 7.1）

## 职责与边界

接收问题与已检索证据，构建有预算的上下文，通过注入的 StructuredLLMClient 生成结构化
答案，返回 AnswerResult 和最小安全引用。不调用 Query/检索、数据库、PDF、Chunking。
完整逐句蕴含、段落引用覆盖与质量评估留待 Task 7.2，不在本阶段声称完成。

## 公开入口与契约

导入：`engineering_rag.modules.generation.api`。

```python
class GenerationService(Protocol):
    def generate(self, request: GenerationRequest) -> AnswerResult: ...


def create_generation_service(
    *, llm: StructuredLLMClient, settings: GenerationSettings
) -> DefaultGenerationService: ...
```

同入口导出 DefaultGenerationService、GenerationSettings、GenerationError 及既有 DTO/Protocol。
GenerationSettings 仅是模块运行配置，不是另一套公共 GenerationConfig。

GenerationRequest（不变）：

- question：必填非空字符串；纯空白或不能容纳系统/问题的预算会失败。
- evidence：必填 list[RetrievalResult]，允许空列表；空证据不调用模型。
- history：可选有序 ConversationTurn 列表，仅供对话理解，不是证据。
- config：可选既有 GenerationConfig（config_id、max_output_tokens、temperature），仅覆盖
  本次对应参数，不覆盖 provider/model/timeout 或上下文预算。
- trace：可选 TraceContext，透传至模型并记录 trace_id。

RetrievalResult 2.0 必填标准名称/document_id/pages 等来源信息缺失时拒绝；
clause_id/number 允许 null，不补猜。is_explanation=true 是说明，false 非说明，null 未知；
is_mandatory=true/false 是来源明确判定，null 不代表非强制。content_type 复用 ChunkContentType。
历史 1.0 的受控读取与旧消费者升级要求见 [ADR-RR-001](../../../../docs/adr-retrieval-result-v2.md)。

GenerationSettings（不包含凭证）：

| 参数 | 含义 / 默认值 |
| --- | --- |
| llm | 必填既有 StructuredLLMConfig：模型/可信版本、timeout、输出 token 上限、temperature |
| provider | 必填，由组合入口读取既有配置传入，用于结果模型信息 |
| max_context_chars | 默认 48000：序列化应用 input + output_schema 的字符估算上限 |
| max_answer_chars | 默认 12000：answer 与 limitations 的总字符上限 |
| max_history_chars / max_history_turns | 默认 4000 / 8，允许 0 |
| max_attempts | 默认 2，允许 1～2，没有 HTTP 层隐藏重试 |

现有 token 工具属于 Chunking 私有实现，不能跨模块引用。因此使用明确的字符预算，
不是 tokenizer，不声称字符等于 token，也不是供应商完整上下文窗口保证。传输外壳、
重复系统指令等开销不在此计数中；部署者须保守配置余量。输出 token 单独沿用既有配置。

## 上下文、排序与安全

ContextBuilder 为私有实现，返回 payload、E1/E2…注册表、估算用量、跳过证据及原因、
省略历史数，不修改公共模型。具体行为：

1. 重校验请求快照，按 rank 稳定排序（同 rank 保持输入顺序），不比较跨来源 score。
2. 按 chunk_id 去重；除 rank/score/backend/index 外，内容或来源身份/属性不同即
   evidence_conflict，不把不同 Chunk 合并，也不从编号/页码/ID 推断未知属性。
3. 逐请求注册表只保留实际纳入的本次检索证据，不共享可变状态。被跳过的 ID 不可引用，
   所以 E 编号允许不连续。
4. 保留系统规则和当前问题，优先高排名完整证据。超预算整块跳过，继续尝试后续较小块。
   公式、适用条件、符号、表头、数据、表注、条文 content 原样保存，不截断或重建原文。
5. 剩余预算保留最近完整连续历史后缀，恢复原顺序；历史回答/引用不自动当作当前证据。

Prompt 版本 engineering-generation-1.0。固定 instructions 仅来自应用常量；
question/history/evidence 分别序列化为不可信数据，嵌入证据的指令不提升到系统。
要求保留原始数值、单位、否定条件、适用范围，区分正文/说明与强制性三态，不猜版本效力。
不自行添加 Expansion/HyDE 或历史回答；但公共 RetrievalResult 本身无法证明调用方是否
把虚构内容冒充真实召回，因此调用方仍须保证输入来源可信。

## 输出、引用与 grounding

模型输出私有 GenerationOutput：answer、evidence_ids、grounding_status、limitations，
extra=forbid。正式执行 response.validate_output(request, GenerationOutput)，绑定
request_id/model_id/可信 revision/Schema 并严格校验，不仅检查 JSON 语法。

AnswerResult（外层 1.0，不变）：

- 空证据或全部整块跳过：固定 insufficient_evidence 文本、空引用、model=null、warnings，
  不调用 LLM。
- grounded/partially_grounded 必须引用至少一个本次有效 ID；insufficient_evidence 必须无
  已使用 ID。未知 ID 或明显状态矛盾显式失败，不替换证据。
- 模型 grounded 但存在 limitations 或跳过证据：降为 partially_grounded 并加 warning。
- insufficient_evidence 不发布模型可能编造的确定结论，返回固定不足文本。
- 按模型 evidence_ids 的首次使用列表顺序去重，映射 C1/C2…；真实 chunk/document/clause/
  page 范围只能从注册表获得，不让模型自由生成来源。缺失 clause_id 保留 null。
- quoted_text=null：不伪造引文，不声称完成原文子串或逐句引文校验。
- 组装后调用既有 validate_answer_citations，检查来源身份和页范围。

grounded 是经结构与明显矛盾检查后的模型支持声明，不是逐句语义正确或法律效力证明。
本阶段不验证 answer 自由文本中每个数值/条文号的真实性，也不做段落级引用覆盖。

## 错误、重试与生命周期

GenerationError.code 包括 invalid_request、invalid_evidence、evidence_conflict、
context_budget、invalid_output、unknown_evidence_id、grounding_conflict、output_budget、
citation_mapping、model_failure，以及既有适配器的 authentication/permission/quota/
rate_limit/server_error/timeout/connection/refused/truncated_output/model_mismatch/invalid_json。

超时、连接和 ValueError 类结构化错误按 max_attempts 有界重试。认证、限流、服务端错误及
明确来源/状态矛盾不重试；错误不伪装成正常答案。不无限重试、无缓存答案兜底。
注入客户端由调用方管理；模块不实例化供应商 SDK，导入/构造不访问网络。

上下文构造确定性；生成不承诺结果确定性或幂等，API 和重试可能计费。
默认 logging 事件 generation_attempt 仅含 trace/model、数量、预算、耗时、usage、状态；
不记录问题、证据、答案或密钥。service.calls 返回最近 100 次尝试的诊断深拷贝。
未知用量为 null，无模型调用不新增 calls。

## 最小真实调用

```python
from pathlib import Path
from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.infrastructure.llm.api import LLMSettings, OpenAICompatibleLLMClient
from engineering_rag.modules.generation.api import GenerationSettings, create_generation_service

# 组合入口创建基础设施；Generation 内部只依赖 contracts。
runtime = LLMSettings.from_env()  # 不自动加载 .env
generator = create_generation_service(
    llm=OpenAICompatibleLLMClient(runtime),
    settings=GenerationSettings(
        provider=runtime.provider,
        llm=runtime.structured_config("generation-production"),
        max_attempts=runtime.max_attempts,
    ),
)
request = GenerationRequest.model_validate_json(
    Path("examples/generation_request.example.json").read_bytes()
)
answer = generator.generate(request)  # 实际 API 调用；示例证据明确为虚构
```

显式加载 .env 的真实 API 示例 Smoke（会计费，只写新目录）：

```bash
.venv/bin/python -m scripts.generation_smoke --env-file .env \
  --request examples/generation_request.example.json \
  --output-dir data/eval/task7_1/runs/real-example-v1 --allow-real-api
```

产物 answer.json、report.json 保存模型、用量、耗时与最小引用校验，
human_verified_real_evidence=false。它不是人工核验真实规范或答案语义质量验收。

## 版本与独立测试

Generation Protocol/请求/答案、RetrievalResult 2.0、Document Frozen 2.4、Chunk 1.0
均未修改。独立测试只用 Fake LLM/HTTP transport，无网络，不能冒充真实模型验证。

```bash
.venv/bin/python -m pytest src/engineering_rag/modules/generation/tests -q
.venv/bin/python -m pytest tests/contracts tests/architecture tests/infrastructure/llm -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
```
