# Engineering RAG — Codex 项目级开发规范

> 本文件是长期有效的顶层开发约束。Codex 每次修改代码、接口、模型、文档和测试之前，必须先阅读本文件。任务指令与本文件冲突时，应明确说明冲突，不得自行忽略。

## 1. 项目目标和当前阶段

开发面向工程建设规范、标准、图集等 PDF 的 RAG 系统。核心质量要求：**结构准确、条文可追溯、标准版本可区分、引用可靠、检索评估可复现、模块可独立迭代**。

**当前阶段：Document Schema V2.4 已于 2026-10-11 正式冻结（FROZEN）；Architecture Task 1.1 的 PDF 读取、中文 OCR 与部分 Document 纵向闭环已完成实现并等待维护者验收。Task 1.2～1.6 尚未开始。**

这是从零开始的新项目，**不存在任何需要保留、迁移、兼容或引用的旧 Task 1～5 代码**。不得假设旧工程路径、模型或算法仍存在。

Architecture Task 0/0.2 阶段禁止实现 PDF/OCR 解析、Chunking 算法、Elasticsearch/Milvus 接入、Embedding、检索融合算法、查询改写/HyDE、LLM 调用、HTTP 服务、后台任务和部署设施。该限制是已完成阶段的历史边界；后续能力只能由维护者通过独立任务明确启动，不能因 Schema 已冻结而视为已经授权或实现。

## 2. 总体架构：模块化单体（Modular Monolith）

- **一个 Python 项目、一个部署单元**，不是多个独立运行的微服务。
- 业务模块共 7 个：`document_parser`、`chunking`、`keyword_retrieval`、`vector_retrieval`、`hybrid_retrieval`、`query`、`generation`。
- 横向基础能力：`contracts`、`file_store`、`orchestrator`、`evaluation`、`observability`、`config`。
- 模块之间通过进程内的**类型化 Python 接口**调用；使用 `typing.Protocol` 定义能力、使用依赖注入组装，不使用 HTTP/gRPC 进行模块间通信。
- 每个业务模块必须有稳定的公开 API、独立接口文档、独立测试；内部实现可替换。
- **编排器负责跨模块业务流程**。Parser 不主动调用 Chunking；Chunking 不主动写检索数据库；Generation 不主动执行检索。
- 公共模型和接口尽量稳定，具体库、算法、模型和数据存储属于模块内部。

### 依赖方向（必须遵守）

```text
       contracts：公共 Schema / Protocol
                 ▲
                 │
         各独立业务模块、基础适配器
                 ▲
                 │
         orchestrator / 组合入口
```

箭头指向被依赖层，实际 Python import 只能沿此方向或在本模块内部发生。

1. `contracts` 只能依赖标准库和数据校验相关依赖，**不得导入任何业务模块或基础设施实现**。
2. 一个业务模块可导入 `contracts` 和自己的代码，**不得导入其他业务模块的 `internal/`、具体实现类、数据库客户端和私有模型**。
3. `hybrid_retrieval`、`query`、`orchestrator` 如需使用其他能力，只能通过 `contracts` 声明的 Protocol 和依赖注入获取。
4. `generation` 接收已检索证据，不访问其他模块的检索内部实现。
5. 禁止循环依赖、隐式跨模块全局状态、在模块导入时自动连接外部服务。

## 3. 固定的仓库结构

采用**一个可安装的 `src` 布局 Python Package**，而非多套独立打包工程。

```text
engineering-rag/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .gitignore
├── src/engineering_rag/
│   ├── __init__.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── documents.py
│   │   ├── chunks.py
│   │   ├── retrieval.py
│   │   ├── queries.py
│   │   ├── answers.py
│   │   ├── tasks.py
│   │   ├── evaluation.py
│   │   └── protocols.py
│   ├── modules/
│   │   ├── document_parser/
│   │   ├── chunking/
│   │   ├── keyword_retrieval/
│   │   ├── vector_retrieval/
│   │   ├── hybrid_retrieval/
│   │   ├── query/
│   │   └── generation/
│   └── infrastructure/
│       ├── file_store/
│       ├── orchestrator/
│       ├── evaluation/
│       ├── observability/
│       └── config/
├── tests/
│   ├── contracts/
│   ├── architecture/
│   └── integration/
├── examples/
├── docs/
└── scripts/
```

各业务模块至少包含：`__init__.py`、`api.py`（公开入口/导出）、`INTERFACE.md`、`internal/__init__.py`、`tests/test_contract.py`。必要的目录必须可正常导入。跨模块只允许使用公开入口、共享 Schema 或 Protocol。

## 4. 公共数据契约规则（唯一事实来源）

- 公共跨模块模型集中于 `engineering_rag.contracts`，使用 **Pydantic v2**；禁止每个模块分别定义自己的 `Document`、`Chunk`、`RetrievalResult` 等同名公共模型。
- 所有公开能力协议集中于 `contracts/protocols.py`，使用 `typing.Protocol`；模块 `api.py` 可统一重导出。Protocol 只定义接口，**不等同于已经实现业务逻辑**。
- 持久化的公共模型应包含 `schema_version`，破坏兼容性时需显式版本变更。
- `document_id` 标识具体文档，不能用 `standard_code` 取代；同一个标准代码可以存在多个版本、修订版。
- ID 必须有确定的作用域和非空约束，引用关系应可校验。`chunk_id`（物理 Chunk）与 `logical_chunk_id`（逻辑条文单元）分别定义。
- 保留来源：源 PDF 的 `FileRef`、页码、Block 来源、标准版本、章节/条文身份；**PDF 物理页码从 1 开始**，印刷页码/页标签是另外的字段。
- `Document` 同时包含**页面版面视图**（Page/Block）与**语义结构视图**（Section/Clause）。跨页条文在语义视图中仍是一个 Clause。
- 页面分类固定为用户指定的 13 种类型 + `unknown`；页面内部区域可有独立类型，以支持混合页面。
- 正文条文和条文说明是不同实体；可通过 `explains_clause_id` 等字段关联。**不能仅依赖 `clause_number` 标识唯一条文**。
- `is_mandatory: bool | None`：`None` 表示未判定，禁止仅凭“应/必须”等词判定规范法律效力。
- 表格、图形、图片、公式尚未解析时也必须能以 Block/AssetRef 表示，不可静默丢弃。
- 对公共模型明确字段类型、必填性、空值语义、序列化方式、验证约束；优先采用 `extra='forbid'` 防止无意混入字段。
- 示例 JSON 必须能被实际 Pydantic 模型校验；所有示例规范内容应为**虚构的演示文本**，不能伪称是真实标准条文。

## 5. 各模块公开接口约定

每个 `INTERFACE.md` 必须包括：
1. 职责与非职责。
2. 公开 import 路径、Protocol、函数签名。
3. 输入/输出 Schema、必填字段与可选字段。
4. 参数校验、错误与异常、部分成功语义。
5. 副作用、幂等性、排序保证及可重复执行约定。
6. 依赖注入和允许依赖项。
7. 最小调用示例（未实现的场景明确标注“接口示例”）。
8. API/Schema 版本与兼容策略。
9. 本模块独立测试命令。

其他约束：

- 优先使用结构化 Request/Result 类型，不使用冗长的原始参数列表。
- 检索服务将索引维护（创建/写入/删除）与在线检索分离。
- BM25 分数与向量相似度不可默认直接相加；融合策略及权重应显式出现在请求契约中。
- Query 负责区分 `plan()`（仅生成检索计划）与 `execute()`（通过注入的检索接口执行）。
- Generation 仅接收证据并生成结果，引用必须指向真实证据身份。
- 会产生副作用的方法必须定义幂等性、失败与重试的语义。

## 6. Python 代码规范

- Python **3.11+**，UTF-8，`src` 布局、`pyproject.toml`、可编辑安装。
- Pydantic v2、`typing.Protocol`、pytest、Ruff（lint + format）。
- 所有公开方法与函数必须完整标注类型；优先 `list[T]`、`str | None`，减少无意义的 `Any`。
- 模块/函数/变量 `snake_case`；类 `PascalCase`；常量 `UPPER_CASE`；命名必须表达业务含义。
- 遵循单一职责、组合优于复杂继承；避免巨型函数、过度抽象和隐藏单例。
- 不允许 `except Exception: pass`、隐蔽失败、可变默认参数或导入时副作用。
- 注释及开发文档可以使用中文，公开 Python 标识符、Schema 字段统一使用英文。
- 不硬编码本机绝对路径、密钥、账号、服务地址；敏感配置不得写入 Git。
- 使用 `pathlib` 处理文件路径；输入异常应给出明确错误，不擅自改写原始用户文件。
- 日志应有 `trace_id` / `task_id` 关联能力；默认不记录整篇 PDF、用户问题全文或敏感上下文。
- 测试必须可重复；Task 0 不依赖网络、GPU、数据库、OCR、LLM 或模型下载。

## 7. 测试与文档约定

- 各模块测试必须能够**单独运行**，使用契约样例/测试替身，不依赖其他业务模块真实实现。
- `tests/contracts/`：Schema 验证、版本、序列化回环、引用关系、示例文件等。
- `tests/architecture/`：模块边界、非法跨模块内部导入、公共入口、接口文档检查等。
- `tests/integration/`：保留给后续真实集成；**Task 0 不做真实外部集成**。
- 必须能运行 `python -m pytest -q`、`ruff check .` 和 `ruff format --check .`，结果如实汇报。
- README 说明如何分别测试每个模块；不能将仅有 Protocol 的骨架宣称为功能已完成。
- 顶层文档至少包括：`docs/architecture.md`、`docs/data-contracts.md`、`docs/dependency-rules.md`、`docs/development-guide.md`、`docs/architecture-decisions.md`。

## 8. Codex 执行任务的一般流程

**开始前**：检查当前仓库文件，概述目标与改动计划。新仓库不查找、迁移旧代码。

**开发中**：
- 严守当前任务范围，不提前开发后续模块算法。
- 修改公共接口时，同步更新 Schema、示例、契约测试及接口文档。
- 不允许为绕过单模块测试而修改其他模块私有实现。
- 遇到未确定的架构细节，选取最小自洽设计，并写入 ADR，避免将假设隐藏在代码中。

**结束前**：
1. 运行 Ruff 和全部可用测试。
2. 验证七个业务模块可分别运行测试。
3. 验证 examples 中 JSON 与 Pydantic 模型相符。
4. 汇报变更文件、公共接口、实际执行的测试结果、遗留问题与后续建议。
5. **停在当前任务明确授权的范围；未经维护者启动后续任务，不实现业务算法。**

## 9. 顶层优先级

**清晰边界和可验证的数据契约 > 提前堆功能。** 每个模块都应能在固定输入输出条件下独立开发、独立测试和独立替换，而不牵连整个 RAG 系统。
