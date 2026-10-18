# Task 1.4 公式上下文与去重修复报告

日期：2026-10-12  
结论：**PASS（Task 1.4 修复范围）**

## 1. 范围与冻结边界

- 输入为本地 MinerU 4.0.12 对 GB 50010—2010（2015 年版）物理第 50 页的既有真实
  MiddleJson；未重新运行 OCR，也未调用外部 API。
- 原 PDF SHA256：
  `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。
- 原 MiddleJson SHA256：
  `ee6f5172f6f112c7c0dd0e486a5c3fdec39d9e877f82267761030422ba0c7630`；修复前后不变。
- `git diff document-schema-v2.4 -- src/engineering_rag/contracts` 无差异；冻结的
  Document Schema V2.4、Protocol 和校验逻辑均未修改。
- 未实现 Clause/Section 识别、Task 1.5、Chunking、检索或 LLM 算法。

## 2. 修复前复现

- 基线公式合成测试：`32 passed`；完整基线：`239 passed, 8 skipped`。
- 新增修复测试第一次运行：`6 failed`，分别复现 `Equation.text` 为空、首条件仍为
  `\\ll`、大 FormulaGroup 跨越第二条件、解释 Body 重复、无 dedup sidecar、条件歧义
  无诊断。随后另补充混合正文保护测试。
- 原文档为 17 个 PageBlock、2 个 FormulaGroup。`6.2.1-1`～`6.2.1-5` 共用一个
  y=99.27..215.47 points 的大框，第二条件 Body 位于该框内部。

## 3. 实施结果

### 3.1 条件关联

- 引入 Parser 私有 `FormulaApplicabilityLink`，记录条件 ID、原始 Block ID、页码、
  source index、原 OCR、标准化文本、bbox、目标 formula ID、几何/顺序证据、复核状态和诊断。
- `6.2.1-1` 仅绑定 `当 ε_c ≤ ε_0 时`。原 OCR `\\ll` 原样保留在 sidecar；修正由
  PDF 第 50 页可视证据、原 PDF hash、页号、source index 和印刷公式号共同限定，不进行全局替换。
- `6.2.1-2` 仅绑定 `当 ε_0 < ε_c ≤ ε_cu 时`。
- `6.2.1-3`～`6.2.1-5` 的 `Equation.text` 保持 `null`，没有继承分支条件。
- 两个条件的源 Body 均保留，以维持页面 OCR 忠实性和后续条文识别证据。
- `Equation.text` 采用“适用条件 + 公式号 + 完整原始 LaTeX”；7 条
  `Equation.latex` 均未改写。

### 3.2 阅读顺序与公式框

- MiddleJson 对 7 条公式均提供独立 bbox，因此将两个大组拆为 7 个单公式 PageBlock，
  未推测或伪造坐标。
- 修复后顺序为：条件 1、公式 1、条件 2、公式 2、公式 3、公式 4、公式 5；后续
  公式 6、公式 7 也各自使用原生 bbox。
- 已有公式 ID 不变；原先首公式/公式 6 的 Block ID 不变。新增单式 Block ID 继续由
  source SHA、页码、source index 和 raw type 确定性生成。

### 3.3 符号解释去重

- 新增 Parser 私有 `FormulaSemanticCoverage`，逐源 Block 记录 raw OCR、bbox、内容 hash、
  对应 FormulaGroup/Item、覆盖状态、处置和原因。
- 首组 source index 9～14 的 6 个完整解释 Block，以及次组 source index 19 的完整解释
  Block，从最终 Document 中移除；权威语义仅保留于 `symbol_explanations.items`。
- 首组 6 项只挂载在公式 5 的权威 FormulaGroup，私有 `explanation_scope` 指向公式 1～5；
  次组 2 项只挂载在公式 7 的权威 FormulaGroup，scope 指向公式 6～7，因此不串组。
- source index 20 在页底被截断且无结束标点，处置为 `dedup_unresolved`，原 Body 保留，
  不假称完整消费。原始 OCR、bbox、Block ID 和 Item 映射均可由 coverage sidecar 追溯。
- 修复后 Document 为 15 个 PageBlock、7 个 FormulaBlock；共消费 7 个完整重复说明 Body，
  保留 1 个不完整说明 Body。

## 4. 验证

| 检查 | 实际结果 |
|---|---|
| 新增条件/去重回归 + 原 32 项公式测试 | `39 passed` |
| Document Parser 独立测试 | `120 passed` |
| 第 50 页真实产物集成测试 | `5 passed` |
| 默认完整 pytest | `246 passed, 9 skipped` |
| 启用真实 MinerU 产物的完整 pytest | `255 passed` |
| `ruff check .` | 通过 |
| `ruff format --check .` | `181 files already formatted` |
| V2.4 `Document.model_validate_json` / JSON round trip | 通过 |
| 测试用 Clause + `derive_clause_plain_text()` | 条件、完整公式和两组解释均存在，完整解释不重复 |
| 相同输入连续重放 | 四个交付产物 SHA256 完全一致 |

确定性产物 SHA256：

- `document.fixed.partial.json`：
  `d0cbbb06a5da1dcca0da03dc386f0c5cae64af4fb194c32fa9b8816ef8772a64`
- `formula_context_sidecar.json`：
  `811a79e7bb169e182e06873d4c462cd9d2aa33057d552be126ec14d8e213c730`
- `formula_dedup_coverage.json`：
  `b317eb3ebe3fa84073dc5ec32e805323e4b4ef6d2703435e5c3601eaf62d63c6`
- `page-0050-formulas-fixed.png`：
  `cf5827fc488eee7af826faaac1ae3d8629384f9fff35f28ad8c44d41dbc8d40c`

## 5. 保留问题

- source index 20 的第二组说明在本页只识别到“混凝土法向应”，缺少跨页证据；公开
  `symbol_explanations` 保留该不完整候选，源 Body 同时保留并明确标记 `dedup_unresolved`。
- 第二组首个符号之间的分隔符仍是 MinerU OCR 的 `1`，继续保留歧义诊断，不静默改字。
- 所有公式和解释仍为 machine-unverified；本次视觉核验只授权修正第一条件的关系符，
  不提升整个公式或 Document 的 verified/complete 状态。

