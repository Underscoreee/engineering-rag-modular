# Generation 接口（Task 7.2）

## 职责与边界

接收问题与已检索证据，构建有预算的上下文，通过注入的 StructuredLLMClient 生成结构化
答案，经独立 CitationMapper/AnswerValidator 返回 AnswerResult 与可追溯引用。
不调用 Query/检索、数据库、PDF、Chunking；未实现完整逐句蕴含、段落引用覆盖或工程事实证明。

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

RetrievalResult 2.0 必填标准名称、标准代码/document_id/pages 等来源信息缺失时拒绝；
标准名称和代码纯空白同样拒绝，在调用模型前返回 invalid_evidence。
clause_id/number 允许 null，不补猜。is_explanation=true 是说明，false 非说明，null 未知；
is_mandatory=true/false 是来源明确判定，null 不代表非强制。content_type 复用 ChunkContentType。
历史 1.0 的受控读取与旧消费者升级要求见 [ADR-RR-001](../../../../docs/adr-retrieval-result-v2.md)。

GenerationSettings（不包含凭证）：

| 参数 | 含义 / 默认值 |
| --- | --- |
| llm | 必填既有 StructuredLLMConfig：模型/可信版本、timeout、输出 token 上限、temperature |
| provider | 必填，由组合入口读取既有配置传入，用于结果模型信息 |
| max_context_chars | 默认 48000：序列化应用 input + output_schema 的字符估算上限 |
| max_answer_chars | 默认 12000：answer、limitations 与可选 quotes 的总字符上限 |
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

Prompt 版本 engineering-generation-1.1。固定 instructions 仅来自应用常量；
question/history/evidence 分别序列化为不可信数据，嵌入证据的指令不提升到系统。
要求保留原始数值、单位、否定条件、适用范围，区分正文/说明与强制性三态，不猜版本效力。
不自行添加 Expansion/HyDE 或历史回答；但公共 RetrievalResult 本身无法证明调用方是否
把虚构内容冒充真实召回，因此调用方仍须保证输入来源可信。

## 输出、引用与 grounding

模型输出私有 GenerationOutput：answer、evidence_ids、grounding_status、limitations，
以及可选 quotes（默认 []）。每个 quote 仅有 evidence_id、quoted_text，其他来源字段拒绝。
正式执行 response.validate_output(request, GenerationOutput)，绑定
request_id/model_id/可信 revision/Schema 并严格校验，不仅检查 JSON 语法。

AnswerResult（外层 1.0，不变）：

- 空证据或全部整块跳过：固定 insufficient_evidence 文本、空引用、model=null、warnings，
  不调用 LLM。
- grounded/partially_grounded 必须引用至少一个本次有效 ID；insufficient_evidence 必须无
  已使用 ID。未知 ID 或明显状态矛盾显式失败，不替换证据。
- grounded 还要求整份 answer 等于某一已引用 content 的完整文本（仅容许安全空白差异），且没有 limitations
  或跳过证据；否则保守降为 partially_grounded 并加 warning。一个有效 ID 不证明逐句支持。
- insufficient_evidence 不发布模型可能编造的确定结论，返回固定不足文本。
- 按模型 evidence_ids 的首次使用列表顺序去重，映射 C1/C2…；真实 chunk/document/clause/
  page 范围只能从注册表获得，不让模型自由生成来源。缺失 clause_id 保留 null。
- 没有 quote 时 quoted_text=null；提供 quote 时必须通过下述原文校验。
- 映射后由 AnswerValidator 严格重校验 AnswerResult/Citation、请求绑定、来源字段、原文和
  状态；无证据的安全分支同样校验。仅成功结果返回，错误不静默清理或替换。

grounded 仅在整答案复制完整证据的窄条件下保留；子串可能遗漏前置否定或适用条件，不能
据此保留 grounded。即使完整复制，也不等于相关性、适用性或法律效力已证明。
所有有依据的结果均附来源/引文校验不等于逐句语义证明的 warning。未验证自由回答的每个
数值/条文号，也未实现段落级引用覆盖；这些不是本轮验收已通过的能力。

## CitationMapper 与 AnswerValidator（内部组件）

固定数据流：ContextBuilder → StructuredLLMClient → 正式私有输出校验 → CitationMapper
→ AnswerValidator → AnswerResult。组件不导出为新的跨模块 Protocol，公开 generate 签名不变。

```python
# Generation 内部入口，其他模块只调用 generate：
# CitationMapper.map(output: GenerationOutput, context: GenerationContext) -> CitationMapping
# AnswerValidator(max_answer_chars=...).validate(
#     answer, context=context, mapping=mapping, limitations=...
# ) -> AnswerResult
```

CitationMapper 使用**实际进入 Prompt 的同一个注册表**，逐字段比对 Prompt 行与来源对象，
捕获模型复制绕过校验、同 chunk_id 冲突、来源属性被改、注册表多出未入 Prompt 对象等问题。
只按 evidence_ids 的首次使用顺序去重，不修改证据内容、score 或 rank，不合并不同来源。
CitationMapping 仅保存有序 ID/Citation 和原 Context 对象绑定，不另建证据注册表。
即使不同请求都使用 E1，也不能跨请求复用映射；模型响应另由 validate_output 绑定 request_id。

Citation 来源只取注册表的 chunk_id/document_id/clause_id/pages，缺失可选身份保持 null。
页范围必须等于原记录的**完整范围**，没有逐页引文定位证据时不缩小范围。
标准名称/代码/条文编号、is_explanation/is_mandatory/content_type 在同一 Context 原样保留
并检查，不加入现有公共 Citation。下游需要这些属性时按 evidence_chunk_id 回查本次输入；
公共 Citation 没有这些独立字段，不伪称已扩充或全部序列化入 Citation。

### 原文引文规则

- 私有 quotes 为模型的不可信提议，ID 必须同时在当前注册表和本次 evidence_ids 中。
- 同 ID 完全相同的 quote 去重，不同 quote 报 quote_conflict；不把多个片段拼成伪造原文。
- 首先检查原始 content 子串；仅允许 ASCII 空格、tab、CR/LF 连续排版空白折叠为一个空格，
  保持词之间边界，不删除空白后把 `1 2` 匹配成 `12`。
- 拒绝截断数字、正负号或 LaTeX 命令/转义序列的子串，如 `0.1` 不能引用 `0.10`。
  不进行数值模糊匹配、Unicode/比较符号替换、数学等价或语义相似度判断。
- Formula/Table 的原文以 Chunk.content 实际保存的字符串为准。JSON 内容不自动解码成另一个
  语义视图，LaTeX 必须采用已存转义形式；无法字面匹配的引文拒绝，不伪称已验证。
- quoted_text 保存模型原提议，不自动改写成匹配版本；空白引文、错值、错符号等显式失败。
- AnswerValidator 会再次检查引文，不能仅凭 Mapper 结果或 citation_id 就放行。

AnswerValidator 用严格 Pydantic 校验拒绝页码字符串/bool、非法字段/版本、空白答案、非法
Citation；拒绝未映射/重复冲突引用、错误 document/clause/pages 和跨请求映射。
insufficient_evidence 只允许既有固定不足文本及空引用。限制说明保留于 warnings。
结构化引用中的伪造标准名/编号通过 extra=forbid 拒绝；自由回答中提到的所有标准/条文号
尚无通用语义核验，不把该限制伪装成已完成的事实校验。

## 错误、重试与生命周期

GenerationError.code 包括 invalid_request、invalid_evidence、evidence_conflict、
context_budget、invalid_output、unknown_evidence_id、grounding_conflict、output_budget、
citation_mapping、invalid_registry、source_metadata_conflict、orphan_quote、quote_conflict、
quote_mismatch、citation_scope、citation_conflict、invalid_answer、model_failure，
以及既有适配器的 authentication/permission/quota/
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
  --output-dir data/eval/task7_2/runs/real-example-v1 --allow-real-api
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

## Task 7.3 组合验证（不是新公共 API）

`scripts.rag_e2e_smoke` 通过上述公开工厂连接真实 Query → Hybrid → Generation。
检索后端使用 ES/Milvus，ContextBuilder/Mapper/Validator 仍在 Generation 内部执行；
没有让 Generation 主动检索。8 类 workflow probe 无人工标签，不能作为质量金标。

```bash
# 显式授权创建本次独有的新目标以及真实 API 计费；两目标存在任一个就拒绝写入。
.venv/bin/python -m scripts.rag_e2e_smoke --env-file .env \
  --corpus data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
  --keyword-index test_task73_your_unique_run --vector-collection test_task73_your_unique_run \
  --output-dir data/eval/task7_3/runs/your-unique-run --create-isolated

# 重跑仅允许显式选择 test_task73_ 目标；完整校验双后端快照后只读复用，不再入库。
# 进程级模型预算对照，不修改 .env 或任何检索算法；仍可能失败且实际调用计费。
ERAG_LLM_MAX_OUTPUT_TOKENS=8192 ERAG_LLM_TIMEOUT_SECONDS=60 \
.venv/bin/python -m scripts.rag_e2e_smoke --env-file .env \
  --corpus data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
  --keyword-index test_task73_your_unique_run --vector-collection test_task73_your_unique_run \
  --output-dir data/eval/task7_3/runs/your-unique-recheck --reuse-isolated

.venv/bin/python -m pytest tests/integration/test_rag_e2e_workflow.py -q
```

输出目录必须全新、非 symlink；不清理索引/Collection、不覆盖历史产物。凭证不落盘。
保存实际召回/入 Prompt IDs、来源标记、Citation、模型/usage/耗时及失败阶段；不默认保存
完整 Prompt 或供应商响应。全部样本失败/部分失败会以非零退出，不把单模块成功当 E2E 成功。
人工复核示例沿用 Task 6.5 格式：`examples/generation_evaluation/task73-review/`。
正式 Recall/MRR/nDCG/答案质量须待人工标注，详见 `docs/task-7.3-rag-validation.md`。
