# Task 7：Generation 接口审查与最小契约建议

审查日期：2026-10-19（Asia/Shanghai）。代码基线：`a6e46a0`，开始时 Git 工作区干净。

状态：**接口审查完成；完整业务实现 BLOCKED，等待 C 类公共契约决策**。
依照任务书第 3.1 节及执行步骤 3–4，未擅自修改契约，也未开始依赖缺失来源语义的生成流程。
本轮只新增本审查报告；未修改源码、测试、`.env`、数据库或 Document V2.4。

## 1. A / B / C / D 审查分类

| 分类 | 实际情况 | 决策 |
| --- | --- | --- |
| A：已有能力 | GenerationRequest、AnswerResult、Citation、GroundingStatus、GenerationService、StructuredLLMClient 及本地输出校验均存在 | 复用，不重复定义 |
| B：内部缺失 | generation.api 只重导出 DTO/Protocol；internal 只有包初始化，无 ContextBuilder、Prompt、CitationMapper、AnswerValidator、服务实现或工厂 | 本可在 Generation 内补齐，但须先确认 C 类来源语义 |
| C：公共输入缺口 | RetrievalResult 不传递 Chunk 的 is_explanation、is_mandatory、content_type | 正文/说明区分及已知属性保留无法完整实现；提交建议，等待批准 |
| D：外部环境 | 当前本地 LLM 配置可通过校验，provider=deepseek、model_id=deepseek-flash；已有真实兼容适配器 | 不缺配置；本轮因 C 类阻塞未调用真实模型，不把历史 Smoke 当成本次 Generation 测试 |

## 2. 真实公共接口和字段

唯一接口来自 `contracts/protocols.py`：

```python
class GenerationService(Protocol):
    def generate(self, request: GenerationRequest) -> AnswerResult: ...
```

`modules/generation/api.py` 当前仅导出上述 Protocol、GenerationRequest、AnswerResult；
没有可调用的生产 generate 实现或 create_generation_service 工厂。

公共请求来自 `contracts/answers.py`：

- `question: NonEmptyStr`。
- `evidence: list[RetrievalResult]`，不是完整 Chunk，也不接收 QueryResult。
- `history: list[ConversationTurn] = []`。
- `config: GenerationConfig | None`，其中有 config_id、max_output_tokens、temperature。
- `trace: TraceContext | None`。

回答已有 `schema_version`、`answer`、`citations`、`grounding_status`、`model`、`warnings`。
状态已有 grounded / partially_grounded / insufficient_evidence，**证据不足状态不缺失**。
错误不应伪装成 grounded；空证据可以走已有 insufficient_evidence，无须为此改 Schema。

Citation 已有 citation_id、evidence_chunk_id、document_id、clause_id、page_start/page_end、
quoted_text。现有 validate_answer_citations 检查 Chunk/Document/Clause 身份及页码范围，
但不检查回答内标记、重复引用、引文子串、段落覆盖及 grounded 状态一致性。这些属 B 类，
可以在 Generation 内额外验证，不需要修改公共 helper。

Citation 没有标准名称、标准代码、版次或 clause_number，但可以通过 evidence_chunk_id
关联输入证据；必要时服务端按真实元数据渲染引用文字。**本次不以此要求扩展 Citation**。
当前公共引用只支持答案级列表；段落关系可在私有模型和 answer 的引用标记中表达。

## 3. C 类缺口：来源语义在进入 Generation 前丢失

Chunk 已有：content_type、is_explanation、is_mandatory、source_refs/source_block_ids。
RetrievalResult 实际仅有：身份、content、standard、clause_id/number、页码、score/rank、
retrieval_source、score_type、index_name。`retrieval_source` 表示 keyword/vector/hybrid，
**不是正文/条文说明类型**。

丢失的数据流：

```text
Chunk（存在正文/说明、强制性等标记）
  → ES / Milvus（存储并支持这些字段的过滤）
  → Keyword _convert_hits / Vector _to_result（投射到 RetrievalResult）
  → Hybrid / QueryResult.evidence（公共模型不包含这些字段）
  → GenerationRequest.evidence（无法恢复原始标记）
```

对应代码证据：

- `contracts/chunks.py`：原始属性存在。
- `contracts/retrieval.py`：RetrievalResult 无这些字段，继承 extra='forbid'。
- `keyword_retrieval/internal/searcher.py::_convert_hits`：未映射这些属性。
- `vector_retrieval/internal/searcher.py::OUTPUT_FIELDS/_to_result`：未读取/返回这些属性。
- `hybrid_retrieval/internal/candidate_merger.py::_assert_same_identity`：仅比较现有公共字段。
- `contracts/answers.py::GenerationRequest`：仅接收该投射后的证据，没有其他可信元数据入口。

已用虚构 RetrievalResult 实际复现：分别添加 is_explanation=True、is_mandatory=None、
content_type='clause'，均抛 Pydantic `extra_forbidden`；不是只补一段 Prompt 就能传递。

还核对了真实已保存的 Task 6.6 查询产物与原始 ChunkBatch：

| Chunk | 条文 / PDF 物理页 | 原始 is_explanation | 返回 DTO 是否有该字段 |
| --- | --- | --- | --- |
| chunk-b890e9f9c95b5e14a11f9ffe68f70f04 | 4.2.6 / 40–41 | false | 否 |
| chunk-8f33271e6fb15b87b60953bd3f7d11ce | 4.2.6 / 306 | true | 否 |
| chunk-d5c7c0f4561159aa88f395d1c01fb6e6 | 6.7.4 / 338 | true | 否 |

上述三条原始 content_type 均为 clause，is_mandatory 均为 null。相同条文编号确实同时
存在正文和说明，不能根据 clause_number、文本措辞、页码大小、opaque ID 或模型常识判定。
审查工具读取原始语料只是证明信息丢失；不意味着 Generation 获准回查语料文件或数据库。

这影响任务第 5.2 / 5.4 节的真实属性保留、第 6.1 节及第 9.4 节的正文/说明区分，以及
要求保留已知强制性属性的通用场景。缺字段可以安全表示为“未知”，但不能凭此宣称这些
正例能力已完整实现；也不能默认为正文、非强制，或把说明当作正文。

## 4. 最小公共契约建议（仅提案，未实施）

建议先批准一个窄范围的检索结果元数据准备变更，在唯一 RetrievalResult 中保留：

```python
# 拟议字段，尚未加入公共模型。
is_explanation: bool | None = None
is_mandatory: bool | None = None
```

is_explanation 的 true/false 只能来自原始可信字段；null 表示历史结果或输入未提供，
**不能以 false 充当缺省未知**。is_mandatory 的 null 保持现有“未判定”语义。
建议同时传递 `content_type: ChunkContentType | None = None`，便于完整保留现有结构类型；
它不是通过内容猜测的类型，也不是要求改变 Chunking 的语义文本。

同步范围只限批准后的元数据契约和映射，不改检索算法：

1. 明确 RetrievalResult 的序列化版本及迁移政策。新增字段会影响 extra='forbid' 的旧消费者，
   不能因有默认值就宣称旧读取器完全兼容；还需检查嵌套 QueryResult/GenerationRequest 等。
2. Keyword 从现存 _source 映射；Vector 从现存 Collection 读取相应字段，mandatory_state
   按 -1→null、0→false、1→true 映射，无效值拒绝，不能用 bool(-1)。
3. Hybrid 保留并核对双方来源属性，遇冲突不能按分支顺序掩盖；不改变 RRF/归一化/排序。
4. Query 透传新增已验证字段，不改理解、改写或增强策略；同步相关 fixtures、契约和迁移测试。
5. 不扩展 Document V2.4，不更改 Chunk Schema，不为此重建或清空已有数据库。

不建议新增第二套同名 DTO、将裸字典塞进公共模型、注入整份语料绕开契约，或让 Generation
访问检索 internal/数据库。上述任何公共变化都必须获得维护者批准后才可实施。

另一可选决策是维护者明确接受“来源类别未知”的受限实现：不声称已区分正文与说明、已保留
强制性标记，答案记录限制。这会降低本任务原目标，需要明确批准，不能当成完整 Task 7 PASS。

## 5. 批准后的内部设计方向（尚未实现）

- 服务与工厂只依赖 canonical Protocol，注入现有 StructuredLLMClient 和私有配置；
  Generation 不导入供应商/检索实现，不在导入或构造时连接外部服务。
- ContextBuilder 按 rank 稳定组织、拒绝同 ID 不同来源、相同证据去重；明确字符/请求预算，
  优先整块选择，不截断公式、表格或条文；只收录本次提供 evidence，不读取 HyDE/Expansion。
- Prompt 把应用指令与问题/历史/证据数据隔离；私有结构化输出关联请求级证据 ID、状态和
  限制。继续调用 response.validate_output，而不是把任意 data 当成合法回答。
- CitationMapper 在服务端从本次注册表派生 Citation 的真实身份、页码和可核对引文；
  未知/跨请求引用明确失败，不静默替换；按首次出现顺序去重和渲染标记。
- AnswerValidator 复用 validate_answer_citations，额外核验标记、引文、非空、重复、状态
  一致性与结果 Schema；只保证确定性完整性，不声称证明每句话的语义蕴含。
- 空证据不调用 LLM；无关、部分、冲突等使用既有 grounding_status 与 warnings 明示限制。
- 日志只记录 trace、预算、数量、模型、耗时、usage、状态和安全错误，不记原文或密钥。
- Evaluation 当前只有 Query/检索评估实现；Generation 评估 DTO 的枚举存在不代表已实现
  答案质量评估。真实模型 Smoke 与人工语义核验分开报告，不在本 Task 扩建评估系统。

## 6. 本轮测试和未执行项

以下为审查时实际执行的**现有基线**，不是新 Generation 功能的通过证据：

| 命令 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m pytest src/engineering_rag/modules/generation/tests -q` | 1 passed；仅 Protocol 声明检查 |
| `.venv/bin/python -m pytest tests/contracts -q` | 175 passed |
| `.venv/bin/python -m pytest tests/architecture -q` | 13 passed |
| `.venv/bin/python -m pytest -q` | 1103 passed / 24 skipped，59.03 秒 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 383 files already formatted |

Generation 新业务测试、真实 LLM Generation Smoke、检索到答案的端到端测试：**NOT RUN**，
原因是 C 类契约决策尚未批准，不是因为缺少 API Key。本轮未付费调用模型，没有生成虚假答案。
24 个既有 skip 未当作通过。无公共 Schema、Protocol、Parser、Chunking、检索或 Query 修改。

待维护者决定：批准检索结果来源元数据及相应版本/映射准备工作，或明确接受受限的未知来源
模式。决定前停在接口审查，不自动实施提案，不宣称 Task 7 已完成，不进入后续任务。
