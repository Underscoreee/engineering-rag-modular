# Architecture Task 1.1 验收报告

> 执行日期：2026-10-11。状态：**IMPLEMENTED — WAITING FOR MAINTAINER ACCEPTANCE**。本报告不启动 Task 1.2。

## 冻结与 Git 基线

- 当前分支：`main`；实施基线 HEAD：`addb49eca28800fba768b09819dd84a29a8162bc`。
- Annotated tag `document-schema-v2.4` 存在并解析到冻结提交 `ebd9b29b3bb475401c8e91a30303ae46a8c119aa`。
- tag 到实施基线之间只有上一轮任务材料；冻结 `src/engineering_rag/contracts` 无差异。
- 实施前基线：完整 pytest `127 passed`；Ruff lint 通过；format `115 files already formatted`。
- Task 1.1 没有修改公共 Pydantic DTO、Protocol 或 Validator，公开签名仍为 `DocumentParser.parse(ParseRequest) -> Document`。

## 引擎与依赖

- Python 3.11.17。
- PyMuPDF 1.28.2：PDF 几何、文本层与按页 raster；AGPL-3.0 / Artifex 商业双许可。
- RapidOCR-ONNXRuntime 1.4.4：Apache-2.0；CPU 实测。
- ONNX Runtime 1.31.0：MIT。
- 随 wheel 安装并离线加载的模型：`ch_PP-OCRv4_det_infer.onnx`、`ch_ppocr_mobile_v2.0_cls_infer.onnx`、`ch_PP-OCRv4_rec_infer.onnx`。本次未另行下载权重。
- Pillow 12.3.0：合成扫描图与 overlay。

## 分项测试证据

### 离线单元与 Fake OCR

- 命令：`pytest .../document_parser/tests --ignore=.../test_real_ocr.py -q`
- 结果：`54 passed`（Parser 独立测试共 55 项，其中 1 项为真实 OCR）。
- 覆盖：PDF 页数/尺寸/文本层/扫描层、选页、临时文件与资源限制、损坏/非 PDF/加密输入、FileStore 失败、空/失败/非法 bbox OCR、稳定 ID、reading order、partial/warnings、旋转、CropBox、不同缩放与坐标正反映射。

### 合成扫描件真实 OCR

- 命令：`pytest .../document_parser/tests/test_real_ocr.py -q`
- 结果：`1 passed`。
- 样本：DejaVu 字体渲染 `ENGINEERING PDF 2026` 到 PNG，再嵌入无文字层 PDF。
- 真实执行 RapidOCR，得到非空文本、实际 polygon/bbox；完整 Parser 输出通过 V2.4 回环。该测试不是 Fake OCR，也不冒充中文准确率证据。

### GB 50010 真实扫描 PDF

- 文件：`混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf`
- SHA-256：`43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`
- 大小：154,122,112 bytes；PyMuPDF 确认 441 页，未加密。
- 抽查第 1、16、282 页文本层长度均为 0，各有扫描图像。
- 实际烟测选页：第 16 页，160 DPI；其余 440 页明确为 `not_processed`。
- RapidOCR 输出 11 个非空中文 Block，最终单页诊断耗时约 3.26 秒；首批文本包括“1总则”“1.0.1为了在混凝土结构设计中贯彻执行国家的技术经济政策”等。
- 第 16 页尺寸为 388.346 × 583.937 PDF points；最大输出 bbox 为 x=351.446、y=286.570，均在页面范围内。
- Document 有 441 个 Page 条目，状态 `partial=true`、`is_complete_document_ocr=false`，第 16 页 `partially_transcribed`，全部 OCR Block 为 `unverified`，warnings 为 0。
- 私有诊断记录第 16 页 OCR 置信度 `count=11`、`min=0.998764`、`max=0.999960`、`mean=0.999716`；置信度只用于诊断，不提升冻结 DTO 的 verification status。
- `Document.model_validate_json()` 回环通过；overlay 目测与正文行位置吻合。
- 本地忽略输出：`outputs/parser_task1_1/{document.partial.json,diagnostics.json,page-016-overlay.png,summary.md}`。

## Task 1.1 审计缺口修复

- 修复前直接运行根目录审计文件，稳定复现 `6 failed`：旋转 90°/180°/270° 的三个文本层坐标失败、旋转叠加 CropBox 的 Document bbox 失败、SHA-256 不一致未拒绝、文件大小不一致未拒绝。
- 文本层 bbox 现在先应用 PyMuPDF `page.rotation_matrix` 转换到可见页坐标，再与 `page.rect` 求交；完全不可见的文本块被省略，部分可见的文本块被裁剪，二者都写入私有页级诊断。
- FileStore 输入以有界流复制到临时文件时同步计算实际字节数和 SHA-256；只在 `FileRef` 声明对应字段时校验，不匹配会在打开 PDF 前以明确的 `SourceIntegrityError` 拒绝。
- 新增常规测试目录内的审计回归，另覆盖正确声明、未声明可选完整性字段、CropBox 部分裁剪诊断及诊断 sidecar 传递。
- OCR confidence 以私有 `count/minimum/maximum/mean` 摘要输出；公共冻结 Schema、Protocol 与验证逻辑未改变。
- 修复后根目录原始审计测试 `6 passed`；常规 Parser 独立测试 `55 passed`。

## 最终门禁

| 门禁 | 实际结果 |
|---|---|
| 原始审计缺口测试 | 修复前 `6 failed`；修复后 `6 passed` |
| Parser 独立测试 | `55 passed` |
| contracts + architecture | `120 passed` |
| 完整 pytest | `181 passed` |
| Ruff lint | 通过 |
| Ruff format | `136 files already formatted` |
| `git diff --check` | 通过 |
| 冻结 contracts 差异 | 无 |

## 局限与风险

- Task 1.1 只把定位文字临时映射为 provisional body Block；没有页面分类和复杂多栏布局模型。
- 文本层达到阈值时优先使用文本层；混合页内独立扫描区域检测留待 Task 1.2，诊断会明确该限制。
- 未实现 LogicalTable/raw_grid/跨页续表、FormulaGroup/LaTeX、Section/Clause、正文与说明组织、mandatory evidence。
- 未运行 441 页全本 OCR，未建立人工 Golden，因此不报告 OCR CER 或结构准确率。
- RapidOCR 与 PyMuPDF 的部署许可、模型升级和质量阈值仍需项目方后续审查。
- Task 1.2～1.6 未开始，等待维护者验收 Task 1.1。
