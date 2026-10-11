# Codex：Architecture Task 1.1 独立验收问题修复

你是 Engineering RAG 项目的 Python Parser 工程师。本次只在已完成的 Task 1.1 源码上进行**最小缺陷修复和再验收**，不能提前实现 Task 1.2。首先阅读 `AGENTS.md`、`docs/schema-v2.4-freeze-record.md`、`TASK_1_1_AUDIT_REPORT.md`，并在仓库根目录先运行基线测试。将 `test_task1_1_audit_gaps.py` 放到 `src/engineering_rag/modules/document_parser/tests/`（或正常的测试目录），先证明反例在原代码下失败，再开始修改。

## 1. P1：原生文字层的旋转/CropBox bbox

`internal/pdf_backend.py` 的 `PdfDocument.extract_text_spans()` 直接把 `page.get_text('blocks')` 的 bbox 当成可视页面坐标，而 `page.rect`/渲染图片采用旋转后可视坐标。请用 PyMuPDF 正式坐标矩阵（如 `page.rotation_matrix`）完成坐标系转换，并正确处理 CropBox；拒绝无面积/无效坐标，不伪造完整可见范围。对部分落在裁切边界之外的原生文字块，应按经过验证的可视区域处理策略记录诊断，不要硬靠删掉文字或修改冻结 bbox 约束通过。

**必须增加测试**：0/90/180/270°、with/without crop；短文字确保精确几何坐标与真正可视位置一致；长文字触及页面边界时不应无故造成整个 Document 失败；验证 OCR pixel→PDF 坐标回归不受影响。

## 2. P2：源 PDF 的 FileRef 元数据一致性

目前 `FileRef.sha256`、`size_bytes` 声明与实际读入字节不一致时，仍会输出一个合法 Document。请在私有 PDF 读取/流式临时文件拷贝期间累计实际字节数和 SHA256，**只校验用户真实声明过的字段**。错误抛出明确 Parser 私有异常，信息指出 size/hash 哪一个不一致，且不泄露文件内容。确保临时资源异常清理；不新增公共 DTO 字段、不直接改写 `FileRef` 的源数据。

**测试**：合法 hash/size 通过；单独错误 hash、单独错误大小都拒绝；未声明的字段维持兼容；大于 `max_pdf_bytes` 仍提前拒绝。

## 3. 质量诊断改进（不改变 Frozen Schema）

审查 `OcrSpan.confidence` → `RecognizedFragment.confidence` 的信息丢失。若能在不扩大公共接口范围的前提下实现，请在 Parser 私有 `ParserDiagnostics` 或 `diagnostics.json` 增加 confidence 摘要或定位到 OCR 片段的质量信息（不把置信度当成 `recognition_status=verified`），并增加 Fake OCR 单测。若不做，说明原因及留待 Task 1.2 的实施项。

## 4. 必须遵守

- 严禁修改 `src/engineering_rag/contracts/*`、`src/engineering_rag/contracts/protocols.py`、冻结文件的语义和公开的 `DocumentParser.parse(ParseRequest)->Document`。
- 不实现表格识别、公式、Chapter、Clause 或分类模型；选中 OCR 页面继续输出 V2.4 `partial` Document 与 `unverified` provisional Block。
- 修复后运行 `python -m pytest -q`、`ruff check .`、`ruff format --check .`，真实 OCR 环境可用时做合成扫描和 GB 50010 第 16 页**真实 OCR** 烟测，记录真实耗时/页数/输出。
- 若上传包没有 `.git`，不能声明已验证冻结 Git tag；以项目真实仓库中的记录核查。
- 报告修改文件、六项独立反例测试、完整测试、Ruff 和真实 OCR 的**实际**结果。无法复现的项目明确报告而非声称通过。
- 完成后停止，等待维护者验收，不自行进入 Task 1.2。
