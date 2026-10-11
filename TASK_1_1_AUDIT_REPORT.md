# Engineering RAG — Document Parser Task 1.1 独立代码验收

审查输入：上传的 `task1-1.zip`。审查方式：解压源码、阅读实现和文档、独立执行 pytest、构造反例、使用真实 GB 50010 扫描 PDF 进行 Fake OCR 集成烟测。此报告不修改用户原项目。

## 1. 结论

**Task 1.1 已具备主要功能，但目前不建议正式验收进入 Task 1.2。** P1：旋转页面的可提取文本层坐标存在真实错误；P2：请求 FileRef 的可选大小与 SHA-256 未与实际读入文件核对；中文 OCR 在审查环境未安装、没有独立实测，不能将提交者报告视为独立确认。

不需要推翻架构，建议限定在 `document_parser` 私有实现中修复，并保持冻结 Document Schema V2.4 与对外 Protocol 不变。

## 2. 可重复运行的证据

| 项目 | 实际结果 | 说明 |
|---|---|---|
| 源码自带完整 pytest | **161 passed, 1 skipped** | `PYTHONPATH=src python -m pytest -q`；跳过项是 RapidOCR 真正识别测试（环境缺 `rapidocr_onnxruntime`） |
| 独立边界反例 | **6 failed** | 单独的 `test_task1_1_audit_gaps.py`；4 项坐标，2 项输入一致性 |
| 真实 GB 50010 PDF 读取与装配 | **通过（Fake OCR）** | 441 页，选取 PDF 第 16 页，仅该页一个模拟 OCR Block，其余 440 页标记 not_processed，完整 Document JSON 往返通过 |
| 本环境 PyMuPDF / Pillow | 已安装 | PDF 读取能力和坐标测试可复现 |
| 本环境 RapidOCR / ONNX Runtime | 未安装 | 真正中文 OCR **尚未独立验收** |
| Ruff | 未安装 | **未独立验证**；源码中的 Codex 报告记录已通过 |
| Git Tag / 冻结源码差异 | 压缩包未包含 `.git` | 文档自述冻结；无法独立确认 tag 或代码相对冻结提交的差异 |

提交者附带的 `docs/document-parser-task1-1-report.md` 记录在其环境下 `162 passed`、GB 50010 第 16 页 11 个真实 OCR Block 和 3.04 秒耗时；这是**随源码提交的报告**，不等于本次独立复现。压缩包没有包含该次 OCR overlay / JSON 实际运行产物。

## 3. P1 — 旋转 PDF 原生文字层 bbox 未进入统一可视页坐标

- 文件：`src/engineering_rag/modules/document_parser/internal/pdf_backend.py`，`extract_text_spans()`；依赖 `internal/parser.py` 的 text-layer 分支。
- 原因：PyMuPDF `page.get_text("blocks")` 返回的是未旋转的 page text 坐标；而页面 `page.rect`、PNG 渲染和 Document `width/height` 采用**已旋转的可视页**坐标。代码直接照搬 raw bbox，没有应用 `page.rotation_matrix`。
- 独立复现（项目自带 `make_text_pdf(['SHORT TEXT'], rotate=90)`）：原生 bbox 约 `(36.0, 52.7, 150.0, 77.4)`；渲染后可见 bbox 应约 `(162.6, 36.0, 187.4, 150.0)`。180°、270° 同样不一致。旋转 90° 加 CropBox 的较长文本甚至导致 Document `bbox exceeds page dimensions` 验证失败。
- 影响：混合扫描/数字 PDF 的高亮与块坐标错误，可能直接中断解析。现有旋转测试只验证 OCR 像素↔PDF 映射，而没测 **text-layer 分支**。
- 修复：在 `PdfDocument.extract_text_spans` 内将 raw rect 变换为最终 page.rect 坐标后构造 `BoundingBox`；对部分可见的裁剪文本明确处理可见区域交集（并记录必要警告），不得用随意截断掩盖错误；测试至少覆盖 0/90/180/270°、带/不带 CropBox，含 overlay 可视定位和 JSON 有效性。

## 4. P2 — FileRef 的 SHA-256 与大小没有验证

- 文件：`internal/parser.py` 的 `parse()` 与 `internal/pdf_backend.py` 的 `PyMuPdfBackend.open`/`_copy_bounded`。
- 现状：只根据申报的 `size_bytes` 与 `max_pdf_bytes` 比较，读取时检查实际文件是否超过限制，却不核实 `size_bytes` **相等**与 `sha256` **匹配**。
- 独立复现：742 字节的合成 PDF，传入 `size_bytes=1742`、`sha256='0'*64`，解析仍成功，错误源元数据被写入返回 Document。
- 影响：上游 FileStore 出现内容替换/截断、路径复用时，可把错误内容作为所声明原件的数据提取结果；文件身份可信度下降。
- 修复建议：对**有声明**的 `sha256`、`size_bytes` 使用流式复制时的真实字节数/增量 SHA-256 做一致性检查；无声明时不强制；抛可诊断 `SourceIntegrityError`（Parser 私有异常即可）；不要改变 `FileRef` 冻结模型，亦不要在不校验的情况下默默覆盖用户提交的元数据。

## 5. P2 — 质量信号没有进入可供排查的输出

- `OcrSpan.confidence` 和 `RecognizedFragment.confidence` 已从 OCR 返回并透传，但 `build_provisional_blocks()` 构造 Block 时丢弃该属性；`PageDiagnostic` 只有 block 数量、耗时、文字来源和 messages，没有 OCR confidence 摘要或逐 span 质量情况。
- 这不是当前冻结契约的验证失败，但会影响后续 Golden Dataset 错误定位。建议仅在 **Parser 私有 `ParserDiagnostics`** 或边车 JSON 输出 OCR 置信度摘要（不把置信度直接等同于 `verified`），不要改 V2.4 DTO。

## 6. Task 1.1 已实现并符合阶段边界的项目

- 保持 `DocumentParser.parse(ParseRequest)->Document` 以及冻结 V2.4 的模型与协议。
- 通过注入 FileStore 读取 PDF；按块拷贝到可自动清理的临时文件；限制 PDF 大小、DPI、像素和选页量；不默认渲染全部 441 页。
- 对纯扫描页调用可替换 OCR 适配器，无法提取文本层不视为 PDF 空白。Task 1.1 provisional Body Block、PageType unknown、partial 状态均符合阶段范围。
- 提供源 PDF 的全本 page_count、未处理页与逐页诊断；单元测试覆盖损坏/加密 PDF、选页错误、OCR 失败、bbox 边界、分支失败时的 partial 语义。
- 没有误报已经实现 PageType 分类、复杂表格、LaTeX、Section/Clause；它们仍属于后续阶段。

## 7. 验收前需完成的门禁

1. 使附带的 **6 个独立反例测试**通过，同时原有测试无回退。
2. 确保旋转/裁剪**原生文本层**与 OCR 像素映射都使用统一 bbox 约定，并对至少一个可视化 overlay 检查。
3. FileRef 有提供 size/hash 时验证真实输入，增加正常/不匹配的正反测试。
4. 在安装 RapidOCR / ONNX Runtime 的环境运行至少一个合成扫描件**真实 OCR**，以及 GB 50010 第 16 页**真实中文 OCR**，提供 JSON、diagnostics、overlay 及 OCR 版本；不要用 Fake OCR 替代。
5. 运行完整 pytest、Ruff lint/format；记录命令和结果。确认 `src/engineering_rag/contracts`、公共 Protocol 相对冻结版本没有变动。
6. 不推进 Task 1.2，等待维护者确认 Task 1.1 通过。

## 8. 独立测试执行方法

在项目根目录使用：

```bash
python -m pip install -e '.[dev,parser]'
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest -q /path/to/test_task1_1_audit_gaps.py
```

真实 OCR 需要额外安装 `.[parser-ocr]` 并记录实际可用的模型。反例测试不需要预先下载任何 OCR 模型。
