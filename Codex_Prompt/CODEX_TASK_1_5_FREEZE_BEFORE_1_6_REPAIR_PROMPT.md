# Architecture Task 1.5 — 进入 Task 1.6 前的四项语义来源修复

你是 Engineering RAG 项目的 Python 架构与 Document Parser 开发工程师。请基于当前 Task 1.5 仓库执行最小范围修复，**不修改已经 Frozen 的 Document Schema V2.4 及 Protocol**，不提前开发 Task 1.6。

## 开始前

1. 阅读根目录 `AGENTS.md`、`docs/schema-v2.4-freeze-record.md`、`TASK_1_5_CODEX_PROMPT.md`、`docs/task-1.5-semantic-structure.md` 和本次 `TASK_1_5_INDEPENDENT_REVIEW.md`。
2. 将 `test_task15_independent_gaps.py` 放入 `tests/audit/`，检查当前虚拟环境、源码和现有真实回放数据。
3. 运行修复前基线 `python -m pytest -q`，独立运行四个新增反例并保存实际失败日志。注意真实集成测试需显式 `ENGINEERING_RAG_RUN_REAL_MINERU=1`。
4. 绝不通过删除/跳过/修改测试预期或硬编码 GB 50010 某页来让测试通过。

## 修复任务

### A. 页面分区判定：不能仅凭编号推断规范正文

重点排查 `internal/semantic/page_zone_classifier.py`：

- 在没有可核验证据证明位于规范正文区间时，`_has_clause_or_heading` 不能将页面无条件标为 `body`；同一模式在条文说明页也大量出现。
- 已核验的说明封面、说明目录、已经建立的相邻连续页分区、可追溯的页面证据可以用来推断 `explanation_body`；不确定时标 `unknown`。
- 从单独真实物理页 301 的 MinerU 原始结构化结果重放，无可信 `known_explanation_cover_page` 时不得错误输出 `body`。
- 保留真实 16 页及有明确正文章节起始证据的正例识别，不可为了保守而全部改成 `unknown`。
- 不在公共 Schema 新增页面分区字段；诊断记录在原有 `page_type_basis` 和 Parser 私有 sidecar。

### B. 未分类页面也要保留结构候选的 pending 索引

排查 `internal/semantic/assembler.py`：

- `_build_clauses()` 中 `group is None` 不可静默跳过带有实质文本/公式/表格的 Block；创建语义待审查关系，记录 block_id、物理页、bbox 来源、原因以及阻止关联的条件。
- 不对 unknown 尝试强制创建 Clause，不为跨页续文编造上一页编号。
- 过滤纯页脚等无需挂接的装饰性内容时要给出明确政策；待关联关系可按连续块合并，避免海量无用 sidecar。
- 后续补充相邻页重放时同一 Block 可被合法消费，pending 自动消失；来源引用不能重复消费。

### C. 合并解析批次时验证真实来源一致性

排查 `scripts/assemble_mineru_clauses.py` → `_merge_documents` 和相关适配入口：

- 对输入的 `document_id`、`source_file.file_id`、`source_file.sha256`、`page_count`、规范 `standard_code` / `edition`、bbox 坐标系统一校验。
- 任意源 PDF 身份冲突必须以明确异常中止，禁止取第一批元数据掩盖后续批次。
- 对页面序号、Block ID、Table ID、跨页表 fragment 引用进行合并完整性检查。
- 对必要 SHA-256 不可验证的输入采用保守策略（拒绝或要求可信上游 manifest），记录可审计原因，绝不能默认同一个 `document_id` 就是同一文件。

### D. 安全 Block 切分添加 bbox 几何证据校验

排查 `internal/semantic/block_splitter.py` → `split_body_block()`：

- `TextSpanEvidence` 的每个子 bbox 必须位于原始 Block bbox 中（允许明确、很小的浮点容差，不允许 y=20–40 的 Block 被拆成 y=220–270 的子 Block）。
- 继续要求 text spans 恰好覆盖原文、顺序、区间非重叠、保留 old→new ID lineage。
- 多行/旋转或复杂版面条件下无法获得可靠 bbox，必须回退保留原 Block + 待拆分诊断，而不是推造几何位置。

## 数据交付修复

- 交付包引用的 `TASK_1_5_IMPLEMENTATION_REPORT.md` 当前缺失。请补充真实实现报告或将清单改为存在且可检验的报告路径。
- 原始 MinerU 输入与已有结果保持只读。修复回放另存独立版本目录，提供 diff/manifest。

## 测试和验收

修复后至少运行以下命令（如当前开发环境须先安装项目，遵循 README）：

```bash
python -m pytest tests/audit/test_task15_independent_gaps.py -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest -q
ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration/test_task1_5_real_semantics.py -q
ruff check .
ruff format --check .
```

特别注意：修复后真实集成预期应根据正确的 page-zone 策略更新或扩充合理正例，但**不能**退化为默认将规范正文/条文说明全部标为 unknown。每次运行保持 Document Schema V2.4 校验、稳定身份和 PDF 物理页来源信息正确。

最后提交修复摘要、代码 diff、四项反例通过日志、完整回归和真实结果、Ruff 检查、报告路径，以及 `PASS/PARTIAL/BLOCKED` 结论。完成后停止，不自行进入 Task 1.6。
