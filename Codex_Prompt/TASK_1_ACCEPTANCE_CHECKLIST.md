# Document Parser Task 1 验收与质量门禁

使用方式：每个子任务只在自己满足所有必需检查后申请验收；本清单记录证据**及未达项**，不是预先宣布已通过。

## 0. 前置冻结状态

- [ ] Git 工作区、分支与当前 commit 已记录；存在有效 Document Schema V2.4 冻结记录；若要求 Git Tag，已核实 `document-schema-v2.4`。
- [ ] `Document.schema_version` 仍仅为 `"2.4"`；公共 Protocol 签名未变；冻结 DTO/Validator 未改动。
- [ ] `AGENTS.md` 已由正式 Freeze Release 同步当前阶段，不再与 Task 1 冲突。

## Task 1.1：PDF→真实 OCR→Partial Document

- [ ] PyMuPDF 正确返回真实 PDF 总页数/尺寸；GB 50010 示例为 441 页（需要实际访问上传 PDF 才算通过）。
- [ ] 真实的中文 OCR 引擎安装/模型状态可见；能在至少一个真实扫描样本上运行，不使用 Fake 输出冒充。
- [ ] 合成无文字层扫描 PDF（经测试确认）能触发 OCR；有文本层的测试 PDF 能读取真实文字。
- [ ] `FileStore.read(FileRef)` 注入，源文件不篡改；失败可诊断。
- [ ] DPI、旋转/裁剪页、像素 bbox→PDF Points 坐标有独立测试；无假 bbox。
- [ ] `pages[].page_number` 1-based；选页真实处理，未选择/未处理页面保持 `not_processed`。
- [ ] OCR Block 只标 `unverified`；复杂版面尚未识别不得宣称完整；Document `partial=true`、`is_complete_document_ocr=false`。
- [ ] `Document.model_validate_json()` 通过；不存在悬空来源引用与 ID 冲突。
- [ ] CLI 输出 partial JSON、诊断、bbox overlay；真实页与 synthetic/fake 测试证据分开记录。
- [ ] 原有全部 tests、Parser 独立 tests、架构 tests、Ruff lint/format 通过（未安装则记录为待验收）。

## Task 1.2：PageType 与布局

- [ ] 13+unknown PageType 可对真实页面分类，unknown 用于低置信度或混合难例。
- [ ] title/body/table/image/formula 候选真实 bbox 与 reading_order 可视化复核。
- [ ] OCR 普通文字、公式、表格区域不会不加状态区分就错误声称 verified。
- [ ] 使用有人审标签的样本报告页面分类宏 F1、版面布局检测指标及分母。

## Task 1.3：逻辑表格

- [ ] 同一个续表对应一个顶层 Table 与多个物理 Table Block。
- [ ] columns/data 行列完备且原文保真、notes 序号/内容正确、raw_grid span 无重叠。
- [ ] 28–29 / 37–38 / 126–127 的真实候选经过人审才计入准确率；续表关系与 9.1.3 边界正确。
- [ ] 未读出单元格/含糊数字保持不确定状态，不补造。

## Task 1.4：公式

- [ ] 有号/确认为无号/编号未知三态分清，均有 `formula_id`。
- [ ] 多公式和跨行 LaTeX、符号说明、每个公式来源 block/page 可追溯。
- [ ] 第 301 页确认无印刷编号的状态来源可复核，无凭空生成公式编号。

## Task 1.5：Clause

- [ ] 章节父子关系正确、正文与说明编号空间不冲突。
- [ ] 条文可跨页，`content_units` 只引用权威对象（Block/Table/Formula/Asset）。
- [ ] `plain_text` 可正确派生与校验，含表格与“式中”符号解释。
- [ ] 没有核验证据的 `is_mandatory` 均为 null；出现官方证据时有可核实来源与状态。

## Task 1.6：全链路评估

- [ ] Golden Dataset 每条真实标签具备审核状态，未审核候选不进入分母。
- [ ] 按页面类型、OCR CER、布局、表格、公式、Clause、来源完整率分别报告指标/分母。
- [ ] 真实批量运行报告耗时、内存、失败页、重试与 partial 结果；能恢复或明确报告不能恢复。
- [ ] 在固定测试配置下可复现，Schema V2.4 100% 校验通过；不能把 Schema 正确率当 OCR 准确率。

## 每一轮提交的测试记录模板

```text
Task: 1.x
Commit / Git branch:
Freeze tag / commit verified:
Python / PyMuPDF / OCR engine versions:
Chosen pages / document SHA256:
Real OCR executed? yes/no; backend & model:
Unit tests:
Integration tests (synthetic scanned pdf):
Real GB50010 smoke tests:
Full pytest:
Ruff lint / format:
Outcomes / skipped / blockers:
Incorrect or uncertain evidence examples:
Next task requested? NO — wait for user approval
```
