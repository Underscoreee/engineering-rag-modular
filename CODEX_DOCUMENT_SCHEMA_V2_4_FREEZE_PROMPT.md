# Codex 执行指令：正式冻结 Document Schema V2.4

> **用户/维护者已明确批准将 Document Schema V2.4 标记为 `Frozen`。**
>
> 冻结基于用户提交的修复后项目源码 `task0-2(1).zip`。独立复核已得到：完整 pytest `127 passed`，旧的 6 项冻结缺陷回归测试 `6 passed`，契约测试 `114 passed`，Parser/Chunking 接口测试 `2 passed`。仓库自身验收报告记录 Ruff check 和 format check 通过；外部复核环境未安装 Ruff，因此请在你当前项目环境再次真实执行并记录 Ruff 结果。上述数字是**审查基线**，不是允许你跳过复测的理由。

## 一、任务目标及严格范围

本任务只做 **Architecture Task 0.2 最终冻结登记（Freeze Release）**，将已通过测试的 Document Schema V2.4 从 `READY_FOR_REVIEW` 变为正式 `FROZEN`。

只允许进行：

1. 核验当前工作区是 Task 0.2 **修复后的**代码版本，检查旧 6 项缺陷修复仍然存在。
2. 重新运行必要的契约测试、独立模块测试、全量测试及 Ruff；真实记录结果。
3. 更新文档中的冻结状态、维护者确认、日期、版本基线、后续变更规则。
4. 生成可追溯的冻结记录，且在 Git 环境满足条件时创建安全的本地提交与**带注释版本标签**。
5. 完成后停止并报告结果，等待新的 Document Parser 开发任务。

**禁止：**

- 修改任何公共 Pydantic Schema 字段、Enum、Protocol 方法签名、默认值、跨引用校验逻辑或 `PLAIN_TEXT_RENDERER_VERSION`。
- 修改已有 Golden/合成 JSON 的结构与含义以“配合冻结”。
- 对外宣称已实现 OCR、版面检测、表格解析、公式识别、跨页聚合算法或 Chunking 算法。它们目前仍是待开发能力。
- 借冻结之名顺带重构七个模块、安装/接入 Elasticsearch、Milvus、模型或服务。
- 静默兼容 `2.4-proposal`、V2.3、Task 0.1 候选 JSON；它们仍须通过未来显式迁移机制转换。
- 强制推送 Git、覆盖已有 tag、提交未经用户授权的其他文件。

## 二、执行前检查

按顺序执行：

1. 阅读根目录 `AGENTS.md`、`README.md`、`docs/data-contracts.md`、`docs/architecture-decisions.md`、`docs/schema-changelog.md`、`docs/schema-freeze-checklist.md`、根目录 `V2_4_FREEZE_CHECKLIST.md`、`docs/id-policy.md`、`docs/artifact-policy.md`。
2. 阅读 `src/engineering_rag/contracts/documents.py`、`artifacts.py`、`protocols.py` 和 `tests/contracts/test_freeze_gaps.py`，确认此前 P1/P2 修复实际存在。
3. 检查 `git status --short`、当前分支与当前 HEAD；识别是否存在与本任务无关的未提交改动。不要清除或覆盖用户改动。
4. 检查 `Document.schema_version`、`DOCUMENT_SCHEMA_VERSION` 和 `ArtifactManifest.schema_version` 正式为 `2.4`，并确认公共 Schema 只有一份权威来源。
5. 记录实际 Python、pytest、Ruff 的版本及环境。优先按照 `pyproject.toml`/README 使用正常安装环境。若仅能 `PYTHONPATH=src` 验证，要如实说明。

如果当前代码与用户提交的修复版明显不一致、旧 6 项回归测试未通过、版本不是 2.4 或存在可证实的兼容性风险，**立即停止冻结，不改成 FROZEN**，报告具体阻塞项并等待修复。

## 三、最终必须重新执行的验证

按当前项目环境运行（根据 venv 的 Python 位置调整，不能把命令不存在当作测试通过）：

```bash
python -m pytest tests/contracts/test_freeze_gaps.py -q
python -m pytest tests/contracts -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest src/engineering_rag/modules/chunking/tests -q
python -m pytest -q
ruff check .
ruff format --check .
```

独立确认：

- 旧 6 项缺陷对应反例均通过。
- 正文 Clause 只能引用正文 Page；条文说明 Clause 只能引用说明正文 Page。
- complete OCR 状态不得包含 not_processed 的 Block/公式/表格片段。
- plain_text renderer 包含符号解释并与缓存摘要一致。
- ArtifactManifest 和 Document 的 parser_version、双方声明的 Asset hash/size 一致。
- Section.structure_path 与编号及父子关系一致。
- `examples/document.example.json`、`examples/document.partial.example.json`、`examples/artifact_manifest.example.json` 能通过相应 Pydantic 校验与 JSON 往返。
- 已确认的 7 项 ADR 落实：稳定 ID、不可变 Manifest、可替换 Parser 技术选型边界、可空 `raw_grid`、引用式 ContentUnit、`mandatory_evidence`、保留已决定暂不精简字段。

**通过条件：** 全量测试和必要反例无失败、无跳过关键验证；Ruff 真实通过。与复核基线测试数不同不一定失败，但必须说明增减原因。Ruff 如果不可用，请先按项目既有开发依赖安装；仍无法验证则标记为阻塞，不要编造通过记录。

## 四、正式写入冻结状态：需要同步的文件

在**确认以上门槛通过且已获得本 Prompt 所载的维护者批准**后，执行以下只针对状态/文档的修改：

### 4.1 `AGENTS.md`

把“当前阶段 Architecture Task 0.2 冻结候选、未经维护者确认不得称为 Frozen”改为：

- **Document Schema V2.4：FROZEN（维护者确认）**。
- Architecture Task 0.2 的契约工作已经完成，后续阶段为 **Document Parser 模块的独立实现，尚未开始**。
- 公共字段、模型结构、Protocol、校验语义为受控 API；后续仅允许经过评估的向后兼容修复。破坏性变更必须升级 Schema 版本并编写明确迁移流程及回归测试。
- 长期有效的模块化单体、单一数据契约、跨模块依赖方向和接口规则必须完整保留。
- Task 0 阶段不得开发业务算法的历史描述可保留为“Task 0/0.2 的阶段限制”，但不能写成永久禁止新阶段 Parser 开发的全局规则。

### 4.2 `README.md`

- 将“待维护者确认”“冻结候选”“不是 Frozen”同步修改为已经正式冻结。
- 明确 Parser/Chunking 目前仍只有协议/骨架，不能写成生产解析能力已经完成。
- 提供权威冻结记录与数据契约文档链接。

### 4.3 `docs/schema-freeze-checklist.md`（唯一权威验收记录）

- 设置 `status = FROZEN`、`ready_to_freeze = true`、`maintainer_approved = true`（按原文风格组织）。
- 填写真实冻结日期（ISO 日期）、批准依据“用户/维护者在本次会话明确同意冻结 V2.4”，不要杜撰签名或审批系统 ID。
- 逐项更新实际最新测试结果和环境；外部复核的 127 / 114 / 6 / 2 可列入独立复核依据，但当前 Codex 的复测数字以其真实输出为准。
- 如存在 Git commit SHA / tag 则填写真实值。若工作区非 Git 仓库或当前条件不允许打 tag，写“未创建（原因）”，不得臆造。
- 明确上次 3 项 P1 + 3 项 P2 缺陷已修复且通过反例测试，无残余冻结阻塞。
- 不能把“该 Schema 已冻结”等价为 “OCR 实现已完成”或“实际业务数据已通过完整 OCR”。

### 4.4 根目录 `V2_4_FREEZE_CHECKLIST.md`

此文件目前仍写着 `NOT VERIFIED` / `DRAFT`，与 `docs/schema-freeze-checklist.md` 冲突。请以 `docs/schema-freeze-checklist.md` 为权威记录，将根目录文件改成**简洁的导航说明或同步的 Frozen 摘要**。不能留下互相矛盾的两份冻结状态。

### 4.5 `docs/architecture-decisions.md`

- 将“尚待维护者确认”一节替换成“维护者已确认正式冻结”的记录，7 项 ADR 保持 `Adopted`。
- 说明 V2.4 冻结后的变更控制规则。
- 保留 Task 0.1 候选与最终 V2.4 的不兼容性记录。

### 4.6 `docs/data-contracts.md`、`docs/schema-changelog.md`

- 标题和描述从“冻结候选”更新为“Document Schema V2.4 — Frozen”；保留字段契约及 Schema 演进事实，不做语义变更。
- `schema-changelog.md` 新增“2026-10-11（或当前实际批准日期）维护者已验收冻结”的变更记录，真实完成日期不得凭空提前。

### 4.7 冻结发布记录 `docs/schema-v2.4-freeze-record.md`

新建一个简洁的冻结发布记录，至少列出：

- Release：`Document Schema V2.4 — Frozen`
- Status：`FROZEN`
- Maintainer decision：用户明确批准
- Freeze date：实际日期
- 代码权威入口：`engineering_rag.contracts.documents`、`engineering_rag.contracts.artifacts`、`engineering_rag.contracts.protocols`
- 核心公开协议签名：`DocumentParser.parse(ParseRequest) -> Document` 与 `ChunkingService.chunk(Document, ChunkingConfig) -> ChunkBatch`
- ADR：ADR-001～ADR-007，全部 Adopted
- 冻结测试证据：复测命令、结果、Python/pytest/Ruff 版本
- Git 状态：实际 SHA、tag 或明确尚未建立 Git 版本标记
- 兼容声明：V2.3、`2.4-proposal`、Task 0.1 候选 JSON 不可静默升级，必须显式迁移
- 实现边界：真实 Parser / OCR / Chunking 算法尚未开发
- 变更政策：破坏性变更升级至后续 Schema 版本，并提供迁移与测试

更新 `README.md` 指向它。

**不要**为了把历史 Task Prompt 中的旧表述改成 FROZEN 而修改 `ARCHITECTURE_TASK_0_1_PROMPT.md`、`ARCHITECTURE_TASK_0_2_PROMPT.md` 或旧审查报告；它们是历史记录。只需使当前权威文档保持一致。

## 五、Git 版本冻结标记（仅在仓库实际支持时）

先检查是否处于 Git 仓库，确认工作树情况及现有 tag：

```bash
git status --short
git tag -l 'document-schema-v2.4'
```

如果 Git 仓库存在、最终测试全部通过且没有与本次相关的未解决冲突：

1. **只提交本次冻结登记所修改的文档**，不要顺便提交无关用户改动；提交信息建议：`docs(schema): freeze Document Schema v2.4`。
2. 在包含冻结文档的提交上创建**本地 annotated tag**：`document-schema-v2.4`。标签说明包含维护者批准与测试证据摘要。
3. **如果 tag 已存在**，核实它指向的版本和本次源码是否一致；不一致则停止并报告，禁止删除/覆盖/force 更新。
4. 不执行 `git push` / `git push --tags`，除非用户另外明确授权。
5. 用真实 `git rev-parse HEAD` 和 `git rev-parse document-schema-v2.4^{commit}` 记录提交身份。若冻结记录需要填写 SHA 而提交 SHA 只能在提交后生成，请用第二个仅文档修订提交补充并清楚解释标签指向，或优先采用“冻结记录中提供标签名，SHA 由 tag 解析”的策略；不能通过自引用文档造成无穷的提交循环。

如果当前材料是从 ZIP 解压的目录而**没有 `.git`**：不创建虚假的仓库历史、不伪造提交或 tag；仍按用户授权完成文档冻结，并在报告注明**代码文档已冻结、Git 发行标签需在实际开发仓库中创建**。

## 六、冻结后检验与停机点

1. 重新搜索当前权威文件中的 `READY_FOR_REVIEW`、`NOT VERIFIED`、`尚待维护者确认`、`冻结候选`，消除当前状态冲突；历史段落若保留，应明确标识为历史而非现状。
2. 再运行全量 pytest 与 Ruff，确认文档改动没有影响代码验证。
3. 检查 `contracts/*.py` 与测试/示例 JSON 的核心内容没有因“冻结登记”而发生不必要变更。
4. 输出冻结公告：`Document Schema V2.4 — FROZEN`，注明日期、Git SHA/tag（仅当真实存在）、测试结果和文档修改清单。
5. 说明下一阶段将是 Document Parser 模块的独立开发，**本次不开始 Parser 算法开发**。
6. 完成即停止，等待下一项任务指令。

## 七、最终汇报格式

请按照以下顺序汇报：

- **冻结状态**：`FROZEN` 或 `BLOCKED`；如果 BLOCKED，具体理由。
- **维护者批准**：已由用户明确批准。
- **最终测试结果**：全部 pytest、6 项修复测试、Ruff lint/format、示例数据校验；每项必须写实际结果。
- **修改文档列表**：列出最终文件路径。
- **源代码变化**：应为“无公共 Schema/Protocol 行为变更”。若不是，说明原因并停止冻结。
- **版本与 Git 信息**：schema_version `2.4`；冻结日期；实际提交 SHA、tag 或明确未创建。
- **兼容政策与 ADR**：七项 Adopted，破坏性变更需要新 Schema 版本及迁移。
- **下一阶段**：Document Parser 独立实现尚未开始。

**验收最终语句：**

> 经维护者批准且重新通过冻结门槛，Document Schema V2.4 的公共 Pydantic 数据契约、Protocol、文档及测试基线正式标记为 **FROZEN**。该冻结不代表文档解析、OCR、Chunking 等模块已经实现。
