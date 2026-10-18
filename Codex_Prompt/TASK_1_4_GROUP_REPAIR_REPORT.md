# Task 1.4 完整公式语义 Block 修复报告

日期：2026-10-12  
结论：**PASS（Task 1.4 补充修复范围）**

## 1. 输入、边界与重放方式

- 从 MinerU 4.0.12 的真实本地 `normalized.json` 重新执行
  `MinerUParseResult -> assemble_mineru_formulas() -> adapt_to_v24()`，没有手工编辑目标 JSON。
- 原 PDF SHA256：
  `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。
- 原 MiddleJson SHA256：
  `ee6f5172f6f112c7c0dd0e486a5c3fdec39d9e877f82267761030422ba0c7630`；重放前后不变。
- `git diff document-schema-v2.4 -- src/engineering_rag/contracts` 无差异；冻结的
  Document Schema V2.4、Protocol 和公共验证逻辑未修改。
- 未实现 Task 1.5、Clause/Section 识别、Chunking、检索或 LLM 算法。

## 2. 修复前后统计

| 项目 | 修复前 `document.fixed` | 修复后 `document.grouped` |
|---|---:|---:|
| PageBlock 总数 | 15 | 7 |
| Formula Block / FormulaGroup | 7 | 2 |
| Equation | 7 | 7 |
| 普通 Body（含印刷页码） | 8 | 5 |
| 独立条件 Body | 2 | 0 |
| 独立符号解释 Body | 1（截断项） | 0 |
| 组 A / B 共享解释 | 6 / 2 | 6 / 2 |

最终普通 Body 仅保留第 2、3、4、5 款和印刷页码“35”。

## 3. FormulaGroup 结果

### 组 A

- Block ID：`block-7e43ec7515fd58c0aaa5b6277b8f1df6`
- FormulaGroup ID：`formula-group-697cdf34ea6858229fcf26b77cb94c84`
- bbox（PDF points）：`x=51.6500..349.5114, y=81.7512..391.2378`
- Equation：`6.2.1-1`～`6.2.1-5`
- 共享解释：`σc`、`fc`、`ε0`、`εcu`、`fcu,k`、`n`，恰好一份。

### 组 B

- Block ID：`block-30a4969a526b57a48e9ed75fe0b6135c`
- FormulaGroup ID：`formula-group-525c9a052ee958a9a9538aa1f2c8d935`
- bbox（PDF points）：`x=51.6500..349.8998, y=440.8724..518.5361`
- Equation：`6.2.1-6`、`6.2.1-7`
- 共享解释：`σsi / σpi`、`σp0i`，恰好一份。

七个稳定 Formula ID：

1. `formula-902a227f35095ad99b6ab9ebe83f7dc8`
2. `formula-675ff57db384551c8140fb58148eb7f5`
3. `formula-c6ff35f214235086972c347ea0d5dc36`
4. `formula-66666724821a5705968d24a933709b24`
5. `formula-1237603f51ab558baf76e1decac6b575`
6. `formula-a3cf8a6a0ccd582baba6a7ec3b0f602c`
7. `formula-607c66d69999534b991abedcf8228cbf`

## 4. 条件关联与来源消费

| 来源 index | 标准化条件 | 目标公式 | 处置 |
|---:|---|---|---|
| 2 | `当 ε_c ≤ ε_0 时` | `6.2.1-1` | Body 消费；原 `\\ll`、bbox 和可视纠错证据保留在 sidecar |
| 4 | `当 ε_0 < ε_c ≤ ε_cu 时` | `6.2.1-2` | Body 消费；原 OCR 和 bbox 保留在 sidecar |

`6.2.1-3`～`6.2.1-5` 没有继承条件。含条件的 `Equation.text` 由条件、一个可读
编号和去掉末尾 `\\tag{}` 的完整公式表达组成；原 `Equation.latex`（含 `\\tag{}`）不变，
避免可读文本重复编号。

符号说明 source index 9～14、19～20 的当前可见 OCR 均已完整存入组级
`symbol_explanations`，因此全部从 Page Body 视图消费。每条来源的原文、bbox、内容范围、
目标组及 Item 索引保存在 consumption report 和 semantic sidecar。

## 5. 跨页未完结与保守处理

- source index 20 的 `σp0i` 说明只识别到“第 i 层纵向预应力筋截面重心处混凝土法向应”。
- 当前可见文本已完整进入组 B，因而不再作为重复 Body；sidecar 仍标记
  `cross_page_incomplete=true`、`review_status=needs_review`，未补造下一页文本。
- 组 B 首项符号之间的 OCR 分隔符 `1` 和组 A `εcu` 说明末尾的 OCR `i` 保持原样及诊断，
  未凭工程常识静默修正。
- 合成测试证明混合普通正文的说明来源不会被消费，其解析出的不可靠 Item 也不会进入
  FormulaGroup；无法安全迁移的既有 Body 引用会抛出 `FormulaReferenceMigrationError`。

## 6. bbox、lineage 与引用完整性

- 组级 bbox 是条件、逐式 bbox 和已消费解释 bbox 的并集，并通过页面边界校验。
- sidecar 分别记录 equation、equation number、condition、symbol explanation 组件 bbox。
  MinerU 编号位于公式图片内部、没有独立编号 bbox，因此编号组件明确复用公式图片 bbox并记录诊断。
- lineage 保存此前逐式 Block/FormulaGroup ID 到新组级 ID 的映射；Formula ID 不变。
- 私有引用迁移器只迁移 Formula ContentUnit，去重合并后的 source Block ID；若普通 Body/
  List Item 引用将被消费的条件或解释来源，则安全失败，不制造悬空或类型错误引用。

## 7. 测试结果

| 检查 | 实际结果 |
|---|---|
| 新增语义组修复 + 原 32 项公式测试 | `41 passed` |
| Document Parser 独立测试 | `122 passed` |
| 第 50 页真实产物集成测试 | `6 passed` |
| 默认完整 pytest | `248 passed, 10 skipped` |
| 启用真实 MinerU 产物的完整 pytest | `258 passed` |
| 其余六个业务模块独立测试 | 各 `1 passed` |
| `ruff check .` | 通过 |
| `ruff format --check .` | `184 files already formatted` |
| `git diff --check` | 通过 |
| V2.4 校验及 JSON round trip | 通过 |
| 测试用 Clause / ContentUnit 与 `derive_clause_plain_text()` | 条件、编号、公式、共享解释完整且不重复 |
| 连续两次真实重放 | 四个交付产物 SHA256 完全一致 |

确定性产物 SHA256：

- `document.grouped.partial.json`：
  `d6fcb78b87f02b1a6b2ff284a4bca3e85550ac76fd91440aa400fb29d6f49628`
- `formula_semantic_group_sidecar.json`：
  `dbf9b8ad580f89faf51bf6a32371f2612f6b3f869b2377ddc535205657c0be12`
- `formula_source_consumption_report.json`：
  `9cab60ffa7cec8ca88423a0759d3e2c5a4760b041ea61417e728481d826cf855`
- `page-0050-formulas-grouped.png`：
  `a338f5cfa95bdc0b586fced9e25e78e79782819e27b950cfe1c4fecdd9f94d3e`

