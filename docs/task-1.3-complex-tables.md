# Architecture Task 1.3 — MinerU 复杂表格与跨页续表

日期：2026-10-12（Asia/Shanghai）  
状态：**PASS（机器候选仍为 unverified；不表示 OCR 内容已人工核准）**

## 范围与真实来源

本阶段只重放 Task 1.2 已保存的 MinerU 4.0.12 / `docvortex.middle` 2.0 本地输出，不重新解析全本 PDF，也不调用外部 API。源 PDF 共 441 页，SHA256 为 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。输入路径为 `data/eval/task1_2_mineru/runs/final/`；Task 1.3 产物为 `data/eval/task1_3_tables/runs/final/`。

冻结的 Document V2.4 Schema 和公共 Protocol 未修改。实现位于 `document_parser/internal/tables/`，由 MinerU 私有 V2.4 adapter 调用；Parser 公开签名仍是 `parse(ParseRequest) -> Document`。

## HTML 与格网保真政策

- 使用标准库 `HTMLParser`，不执行脚本、不加载图片/链接、不访问网络。
- 单个输入必须恰有一个非嵌套 `<table>`；多个表、嵌套表、未闭合结构、超大 HTML、超过行列/单元格/span 上限的输入显式拒绝。
- occupancy 算法按源 `tr/th/td` 恢复 `row/col/rowspan/colspan`；遇到 rowspan 时跳过已占位置。行宽不齐或 span 超出显式源行时标为 `partial`，不补空格。
- 单元格文本仅做空白折叠，保留 `≥/≤/±/—/%`、单位、原精度及公式文本；业务值不转数值。
- `raw_grid.complete` 只表示格位覆盖完整。全部机器文字和表格仍为 `unverified`。
- 原 HTML、局部格网、诊断和未编号表注保存在 sidecar。V2.4 没有 cell bbox，不能从只有 table bbox 的 MinerU 输出中伪造单元格 PDF 坐标。

## 表头、行头与数据展开

显式 `th/thead` 优先决定表头层数。实际 MinerU HTML 只使用 `td`，因此只有在存在表题且首个印刷行完整覆盖所有列时，才把首行作为机器推断表头，并写入诊断。多行表头按每列从上到下收集实际覆盖节点形成 `header_path`；同一 rowspan/colspan 单元不会重复加入路径。

纵向行头仅在表头词或纵向合并结构提供版式证据时标为 `row_header`。数据 rowspan 的文字只出现在起始记录，后续覆盖记录写 `null`；不会复制共享条件。数据 colspan 同样只在起始列保留文字，其他覆盖列为 `null`。所有合并关系仍完整保存在 `raw_grid`。

没有可信表头时保留 raw grid，但输出 `columns=[]`、`data=null`、`structure_only`。能保真展开但未经人工核验时输出 `unverified`。

## 跨页续表规则

自动合并必须同时满足：原 PDF 物理页相邻、下一片有明确“续表”标识、表号一致、列数一致，并且至少一半规范化表头签名相容。以下任一条件阻止合并：新表号、非相邻源页、列数/表头显著冲突、表号或表头证据缺失、仅有页邻接。

每个物理 fragment 保留独立 PageBlock、原 HTML、label 和来源 block ID。合并后使用一个稳定 `table_id`，fragment index 从 0 连续。续页重复表头保留在全局 raw grid 和 sidecar，但从规范化 data 中排除。不同 fragment 的列拓扑无法安全统一时不构造全局 raw grid。

表号来自实际 caption。只有带真实阿拉伯编号的表注进入 `LogicalTable.notes`；“注：……”未编号文本完整留在 sidecar，`notes=null`。

## 三组真实结果

| 案例 | 目标逻辑表 | fragments | raw grid | data | notes | paired/individual |
|---|---|---:|---:|---:|---:|---|
| GB-T352，页 28–29 | 3.5.2 | 2 | 9×2 complete | 7 | 2 | 结构与内容摘要一致 |
| GB-T4222，页 37–38 | 4.2.2-2 | 2 | 20×6 complete | 18 | null | 仅表题括号 OCR 不同 |
| GB-T912，页 126–127 | 9.1.2 | 2 | 13×3 complete | 11 | null | 结构与内容摘要一致 |

同页其他表没有被误合并：GB-T352 的表 3.5.3 保持独立；GB-T4222 的表 4.2.2-1 保持独立。三个目标表的 paired 与 individual 重放产生相同稳定 table/block ID。

人工核查记录：

- 3.5.2 首片第一条数据的环境类别在 MinerU HTML 中为空；输出保留空字符串，没有根据上下文补成“一”。两条真实编号表注进入 V2.4 notes。
- 4.2.2-2 保留 `colspan=2` 表头和大量数据 rowspan。paired 标题为 `（N/mm²）`，individual 为 `(N/mm²）`，未静默修正。未编号表注只保存在 sidecar。若干钢筋符号 OCR 可疑，全部仍是 unverified。
- 9.1.2 保留跨页 rowspan/colspan。第 127 页后续 `9.1.3` 仍是独立 body Block，不属于表格 fragments/data。

每个模式均保存 provenance、Task 1.2 manifest/命令、normalized 与 MiddleJson 哈希、raw HTML、fragments、tables、partial Document、diagnostics、PDF table-bbox overlay 和逻辑格网 SVG。实际候选没有人工金标，因此不计算 CER、TEDS、F1 或“准确率”。

最新重放的 Task 1.3 后处理耗时为 0.244～0.314 秒/模式（含 Document 组装、JSON/sidecar 和可视化落盘）；每个模式的精确值保存在对应 `manifest.json`。该数值不包含 Task 1.2 MinerU 推理时间，后者作为独立字段原样保留。

## 可复现命令

```bash
python scripts/assemble_mineru_tables.py \
  --all-cases --mode both \
  --input-root data/eval/task1_2_mineru/runs/final \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --expected-sha256 43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682 \
  --output data/eval/task1_3_tables/runs/final

ENGINEERING_RAG_RUN_REAL_MINERU=1 \
  python -m pytest -q tests/integration/test_task1_3_real_tables.py
```

普通 pytest 使用合成 HTML，不需要 MinerU、模型、真实 PDF 或网络；真实产物回归必须显式设置环境变量。

## 测试结果

- 开发前完整基线：`188 passed`。
- Parser 模块独立测试：`81 passed`；Task 1.1 历史缺陷回归：`6 passed`。
- 七个业务模块均可独立测试：Parser `81 passed`，其余六个模块各 `1 passed`。
- 显式真实产物集成：`4 passed`。
- 默认完整回归：`207 passed, 4 skipped`；跳过项正是需要显式环境变量的真实产物测试。
- 启用 `ENGINEERING_RAG_RUN_REAL_MINERU=1` 的完整回归：`211 passed`。
- `ruff check .` 通过；`ruff format --check .` 通过，166 个文件格式正确。
- 相对冻结 tag `document-schema-v2.4`，`src/engineering_rag/contracts/` 和公共 Protocol 无差异。

## Known Issues 与后续边界

- MinerU HTML 不提供单元格 PDF bbox，因此 SVG 是逻辑格网图，PDF overlay 只显示真实 table Block bbox。
- 实际 HTML 使用 `td` 而非 `th`，首行表头属于有诊断的机器推断，不能视为人工金标。
- `raw_grid.complete` 不代表 OCR 文字准确。空白、钢筋符号、公式化表头和标点仍需人工审阅。
- 跨页末行若未来出现断格/断字，本阶段不会自动拼接。
- 本阶段不实现公式语义、Clause、Section、强制性、Chunking、检索或 LLM。
