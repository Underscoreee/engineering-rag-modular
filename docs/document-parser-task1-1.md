# Document Parser Task 1.1 实现说明

Task 1.1 打通 `ParseRequest → FileStore.read → PyMuPDF → 文本层/RapidOCR → partial Document V2.4`。公开 `DocumentParser.parse(ParseRequest) -> Document` 没有变化，冻结 contracts 未修改。

## 行为与配置

- PDF 流按 1 MiB 块复制到自动清理的临时目录，先检查大小、PDF 头、密码保护和页数。
- 外部页码始终从 1 开始；Document `page_count` 是源 PDF 总页数，所有页面都有清单。
- 只渲染 `page_selection`；未选页为 `not_processed + blocks=[]`。
- 足够完整的文本层直接使用真实 PyMuPDF bbox；无文本层或稀疏文本层执行整页 OCR。混合页面的独立图像区域检测尚未实现并写入诊断。
- OCR 像素 bbox 按实际 raster 宽高映射到页面可视 `PDF Points + top_left` 坐标；原生文字层 bbox 使用 PyMuPDF `rotation_matrix` 转换，并与 CropBox 可视区域求交。部分裁切或完全不可见文字块会进入私有诊断。
- 自动内容全部是 `unverified` provisional body Block，页面为 `unknown/partially_transcribed`，Document 始终 `partial=true/is_complete_document_ocr=false`。
- `on_page_error=raise` 立即失败；`continue` 保留失败页为 `not_processed` 并增加 `ContractError` warning。
- 未提供 `supplied_standard` 时拒绝解析，不根据文件名猜标准身份。
- `FileRef` 已声明的 `size_bytes` 和 `sha256` 在流式复制时与实际输入核对；未声明字段不强制补造或改写。
- OCR confidence 仅在私有 diagnostics 中记录 count/min/max/mean 摘要，不改变冻结 DTO 或人工核验状态。

支持的私有配置和资源上限见 Parser `INTERFACE.md`。默认最多选 20 页、DPI 200、单页 4000 万像素、PDF 256 MiB；大文件不会被整体读入 Python bytes，也不会默认 OCR 全本。

## ID 与可重复性

Document ID 由 `FileRef.file_id + standard_code + edition + revision` 的命名空间 UUID 生成。Block ID 使用 Document ID、物理页码、提取方法、来源索引和几何锚点，不使用 OCR 文本；同源、同实现、同配置输出可重复。OCR/布局版本改变时 Block 几何锚点可能改变，本阶段不声称跨 Parser 版本稳定。

## 诊断 CLI

```bash
python scripts/inspect_pdf_document_parser.py \
  --pdf "/path/to/混凝土结构设计规范(2015年版) GB 50010-2010_纯图版.pdf" \
  --pages 1,16 \
  --dpi 200 \
  --standard-name "混凝土结构设计规范" \
  --standard-code "GB 50010-2010" \
  --edition "2015年版" \
  --out-dir outputs/parser_task1_1
```

输出 `document.partial.json`、`diagnostics.json`、每个 OCR 页的 overlay PNG 和 `summary.md`。`outputs/` 已忽略，不提交真实 PDF、OCR 图像或解析产物。

## 明确未实现

Task 1.1 不实现页面类型分类、多栏版面、表格/跨页续表、公式/LaTeX、Section、Clause、正文/说明分组、mandatory evidence、全本恢复调度或准确率评估。根目录候选清单和 Parser evaluation 文件都只是 `candidate_pending_human_review`，不能进入准确率分母。
