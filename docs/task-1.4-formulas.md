# Architecture Task 1.4 — MinerU 工程公式结构化报告

日期：2026-10-12（Asia/Shanghai）  
结论：**PASS（结构与来源门槛通过；全部机器数学内容仍为 unverified）**

## 范围与来源

本阶段只使用本地 MinerU 4.0.12 basic/ONNX、`ocr` 模式和 `docvortex.middle` 2.0，不调用远程服务。原 PDF 共 441 页，SHA256 为 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。冻结 V2.4 `contracts/` 与公共 `DocumentParser` Protocol 未修改。

页 50、301 直接重放 Task 1.2 的真实 ZIP/MiddleJson。页 24 的 Task 1.2 原始运行以及本次同配置重试均在 MinerU 内部报 `Unsupported warp settings`，`auto` OCR 模式同样失败；本机 standard tier 缺少本地模型。随后仅把原 PDF 物理页 24 在本地按 200 DPI 栅格化为保持原 PDF points 尺寸的单页 PDF，再用同一 MinerU basic/ocr 成功解析。派生 PDF SHA256 为 `3acb726f8845d53df22eaaf70782cab5f2f2e2fb03c32c0df404d32e769adf43`，MiddleJson `page_idx=0` 显式映射回原物理页 24。原始失败日志、派生输入、成功 stdout/stderr、两个 PDF hash 和映射均保存在 Task 1.4 本地 provenance 中。

## 保守映射规则

- 只把 MinerU 原生 `equation` block 映射为公式，正文 `equation_inline` 保持在 Body 来源中。
- Block/FormulaGroup/Equation ID 基于原 PDF 身份、物理页和源 block index，不使用 LaTeX 哈希；重放或 OCR 文本修正不改变身份。
- 默认单公式单组。只有多式后存在共享且相邻的“式中”解释证据时才合组；`aligned/cases` 不按 `\\` 拆分。
- MinerU equation 原生 `\\tag{...}` 是本次真实数据的印刷编号证据。编号格式必须满足层级数字及可选末级连字符；正文引用、单位、表号、条文号和冲突候选被拒绝。当前 MinerU 不提供单独 number bbox，sidecar 明确记录此限制。
- 无编号机器候选一律为 `equation_number=null/status=unknown`。`confirmed_absent` 只允许外部人工核验且 Equation 为 verified，本算法从不自动产生。
- LaTeX 原样保留，不自动纠正 `l/1`、`0/O`、符号或数学含义；不平衡括号和易混字符只写诊断。
- “式中”按原 block 顺序和几何邻接解析，在下一公式、标题、条文/编号段或页尾停止。Body block 不删除；结构化解释是带 sidecar 来源的派生视图。
- 公式图片路径必须为 raw bundle 内的有界相对路径；拒绝绝对路径、`..`、URL 和越界解析。缺 bbox 或超限内容只留 raw/诊断，不伪造 V2.4 Block。

## 三页真实结果

| 案例 | 物理页 | 组/Equation | 印刷编号 | 符号条目 | 结果 |
|---|---:|---:|---|---:|---|
| GB-E332 | 24 | 1 / 2 | 3.3.2-1、3.3.2-2 | 6 | 栅格回退真实运行成功 |
| GB-E621 | 50 | 2 / 7 | 6.2.1-1～6.2.1-7 | 8 | Task 1.2 raw 直接重放成功 |
| GB-EEXPL | 301 | 1 / 1 | null / unknown | 0 | 未擅自标 confirmed_absent |

人工查看三张 overlay 后确认：绿色框仅覆盖真实公式组区域，橙色框覆盖实际“式中”来源块；页 301 的公式没有附加邻近正文或编号。编号位于 MinerU 公式图和 `\\tag` 内，但没有独立编号框，因此 overlay 不画虚构的蓝色 number bbox。

产物位于 `data/eval/task1_4_formulas/runs/final/`，包含每页原始 MiddleJson 副本、公式图片、sidecar、公式检查视图、完整 partial Document、manifest、diagnostics 和 overlay PNG。普通 pytest 不读取这些真实文件；显式集成测试由 `ENGINEERING_RAG_RUN_REAL_MINERU=1` 开启。

## 可复现命令

```bash
python scripts/assemble_mineru_formulas.py \
  --all-cases \
  --input-root data/eval/task1_2_mineru/runs/final \
  --page24-fallback-root data/eval/task1_4_formulas/preflight/P024-fallback-run \
  --page24-derived-pdf data/eval/task1_4_formulas/preflight/P024-rasterized.pdf \
  --pdf '混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf' \
  --expected-sha256 43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682 \
  --output data/eval/task1_4_formulas/runs/final

ENGINEERING_RAG_RUN_REAL_MINERU=1 \
  python -m pytest -q tests/integration/test_task1_4_real_formulas.py
```

## Known Issues

- 页 24 不能由 MinerU 直接处理，只能通过已明确记录的本地栅格回退；不能把该结果用于评价原始 PDF 直读稳定性。
- MinerU 没有独立编号 bbox，`printed` 依据原生 equation `\\tag` 和公式图片；编号仍为 machine-unverified。
- 页 24 最后一个符号说明、页 50 第二组最后一个说明在本页底部被截断；没有跨页明确归属证据，本阶段不自动续接。
- 页 50 第二组的符号分隔符被 OCR 为 `1`。实现保留原字符串并写 ambiguity diagnostic，不静默改成顿号。
- 页 301 LaTeX 含单位括号但没有公式编号；状态正确保持 unknown。没有人工 Gold，因此不计算检测率、编号准确率或 LaTeX 准确率。
- 本阶段不实现 Clause、Section、强制性、公式纠错/求解、Chunking、检索或 LLM。

## 测试结果

- 开发前基线：`207 passed, 4 skipped`。
- Task 1.4 的 32 项合成正反规格：`32 passed`；真实三页集成：`4 passed`。
- Parser 独立测试：`113 passed`；Task 1.1 六项历史缺陷：`6 passed`；契约测试：`114 passed`。
- 七个业务模块均可独立运行；Parser 为 113 passed，其余六个模块各 1 passed。
- 默认完整 pytest：`239 passed, 8 skipped`；8 项是默认关闭的 Task 1.3/1.4 真实产物集成。
- 启用 `ENGINEERING_RAG_RUN_REAL_MINERU=1` 的完整 pytest：`247 passed`。
- `ruff check .`、`ruff format --check .` 和 `git diff --check` 均通过；178 个文件格式正确。
- 相对冻结 tag，`src/engineering_rag/contracts/` 与公共 Protocol 零差异。
