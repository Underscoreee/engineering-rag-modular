# Task 6.0.1 实施与验收报告

日期：2026-10-18。结论：**契约与离线验证 PASS；完整回归 PARTIAL（已有 Parser 夹具路径阻塞）**。
开始时工作区干净；未提交 Git，未安装新依赖、访问模型、数据库或修改任何真实数据。

## 决策与实现

- 保留 QueryIntent 五类语义；新增 ProcessingIntent，仅 acquisition/exploratory。
- RetrievalPlan.processing_intent 必填；RetrievalPlan/QueryResult 局部主版本 Literal 2.0。
  QueryResult 没有新增结果状态字段；QueryRequest/Options、检索 1.0、Chunk 1.0、Document 2.4 不变。
- 提供显式 V1 迁移，必须由调用方提供处理意图，严格校验旧数据并保留语义、请求、证据；
  旧消费者不能直接读取新版字段；没有提供猜测式迁移或隐式降级。
- StructuredLLMClient.generate 及请求/响应/配置/用量 DTO 已提供。Response 是传输结构，
  validate_output 绑定请求/模型并验证应用 Pydantic 输出模型，拒绝额外字段、类型错误及非有限 JSON。
  尚无真实模型适配器、业务 Prompt 或 SDK。
- StandardMetadataCatalog.lookup 和目录 DTO 已提供。四种匹配状态、版本快照、测试数据标记、
  在库双索引范围和精确元数据/可信别名映射均可校验。全球有效标准不等于已入库。
  不承诺条文存在性，没有生产目录；夹具只在 tests/contracts 中且 is_test_fixture=true。
- 首版 Hybrid-only 与范围异常政策已写入 ADR；没有实现模式判断、Understanding、改写、
  Expansion、HyDE、plan 或 execute。QueryResult 中 evidence=[] 只用于未来正常无命中。

详见 [ADR-Q-001](adr-task6-query-prerequisites.md) 和
[Query 接口](../src/engineering_rag/modules/query/INTERFACE.md)。

## 文件清单

| 文件 | 修改目的 |
| --- | --- |
| src/engineering_rag/contracts/queries.py | 处理意图和局部版本 2.0 |
| src/engineering_rag/contracts/query_migrations.py（新增） | 显式 V1 迁移，严格私有旧版读取模型 |
| src/engineering_rag/contracts/llm.py（新增） | LLM DTO 与纯输出校验 |
| src/engineering_rag/contracts/catalog.py（新增） | 目录请求/记录/匹配 DTO 与响应绑定 |
| src/engineering_rag/contracts/protocols.py | 新增两个依赖 Protocol，已有签名未改 |
| src/engineering_rag/contracts/__init__.py | 唯一公共根导出 |
| src/engineering_rag/modules/query/api.py | 重导出公共类型/Protocol/迁移函数 |
| src/engineering_rag/modules/query/INTERFACE.md | 输入输出、版本迁移、依赖、政策与未实现边界 |
| examples/query_result.v2.example.json（新增） | 合法虚构 V2 示例，不伪称真实执行 |
| tests/contracts/test_query_v2.py（新增） | 新/旧版本、枚举、迁移、严格旧消费者 |
| tests/contracts/test_structured_llm.py（新增） | 离线替身、输出/绑定/用量/预算反例 |
| tests/contracts/test_metadata_catalog.py（新增） | 虚构目录、四态、范围与元数据反例 |
| tests/architecture/test_query_dependency_contracts.py（新增） | 公共身份、Protocol、无 Query 业务实现、示例校验 |
| docs/adr-task6-query-prerequisites.md（新增） | 正式决策、兼容与未决事项 |
| docs/architecture-decisions.md | ADR 索引 |
| docs/architecture.md、docs/data-contracts.md、README.md | 新契约状态与边界 |
| docs/query-task6-interface-audit.md | 保留历史审查并追加 6.0.1 当前状态 |
| docs/query-task6-dataflow-design.md、docs/query-task6-roadmap.md | 同步已落地契约及后续边界 |
| 本报告（新增） | 实际测试和回归阻塞记录 |

经 git diff 验证：Document/Chunk/检索模型、Parser、Chunking、Keyword、Vector、Hybrid、
Generation 和 pyproject.toml 没有变更。Protocol 文件只追加依赖声明，原 Parser 等签名未变。

## 实际命令与结果

执行环境为项目 `.venv`，所有测试不设置真实集成环境变量。

| 命令/检查 | 结果 |
| --- | --- |
| 修改前 contracts + architecture + Query 独立测试 | 126 passed |
| 新增四份测试文件 | 59 passed（版本迁移、LLM、目录、架构/示例） |
| python -m pytest tests/contracts tests/architecture -q | 184 passed |
| python -m pytest src/engineering_rag/modules/query/tests -q | 1 passed；仅 Protocol 基线 |
| Chunking/Keyword/Vector/Hybrid/Query/Generation 分别独立 pytest | 分别 36/30/9/34/1/1 passed |
| python -m pytest src/engineering_rag/modules/document_parser/tests -q | 3 个收集错误，见下文 |
| python -m pytest -q | 5 个收集错误，退出码 2；没有完整执行，不报告全量通过数量 |
| ruff check . / ruff format --check . | 均通过 |
| git diff --check | 通过 |
| 文档相对链接、两路不同 query 的 V2 Python 示例 | 校验/执行通过 |
| query_result.v2.example.json | Pydantic 校验及 JSON 往返通过 |
| 真实 LLM / 生产目录 / 真实数据库集成 | 未执行；本任务只授权契约与离线替身 |

### 现有回归阻塞的证据

当前 HEAD 已把以下文件收录在 Codex_Prompt/，根目录没有相应文件：

```text
Codex_Prompt/TASK_1_3_TEST_CASES.json
Codex_Prompt/TASK_1_4_TEST_CASES.json
Codex_Prompt/TASK_1_5_TEST_CASES.json
```

但 Parser 的 test_table_reconstruction.py、test_formula_reconstruction.py、
test_semantic_structure.py 仍按项目根目录路径 read_text，产生 FileNotFoundError。
全量收集时 tests/audit/test_task15_independent_gaps.py 和 test_task15_source_integrity.py
又导入 semantic 测试，因此总计 5 个收集错误。

上述 Parser 测试、案例文件和路径均不在本次 diff 中。本任务没有搬回文件、创建临时根目录
副本、修改测试、跳过测试或改变 Parser 逻辑。修复这一既有夹具路径需维护者另行安排；
该阻塞不应被契约测试通过掩盖。

## Task 6.1 启动条件

接口层已具备：ProcessingIntent、Query V2 和迁移、LLM/目录 Protocol、离线替身、
Hybrid-only 与异常政策，可在维护者启动后开发离线 Query Understanding。

真实 LLM 适配器/模型与数据传输政策、生产目录来源/更新和入库同步、条文存在性独立证据、
人工 Query Golden Dataset 仍未具备；真实集成验收受这些条件限制。仓库完整回归还受上述
Parser 测试路径问题阻塞。本阶段停止，不自行进入 Task 6.1。
