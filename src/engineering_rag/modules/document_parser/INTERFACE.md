# Document Parser 接口（Document V2.4 FROZEN / Task 1.5）

## 职责与非职责

Parser 最终负责从源 PDF 识别物理页类型、Block、Section、正文/说明 Clause，以及跨页表格的逻辑聚合，输出合法 V2.4 `Document`。Task 1.1 提供安全 PDF 读取与基础 OCR；Task 1.2 新增可选、本地、进程隔离的 MinerU 4.x 私有适配路径；Task 1.3 增加复杂表格恢复；Task 1.4 增加行间公式、印刷编号、保守分组和“式中”符号解释结构化；Task 1.5 在 Parser 私有层增加证据驱动的页面分区、Section/Clause、跨页内容引用及正文—条文说明关联。数学求解、Chunking、检索和 LLM 仍不在职责内；Parser 不调用 Chunking，不写检索索引，也不凭措辞判定强制性。

## 公开路径与签名

`engineering_rag.modules.document_parser.api` 重导出 `engineering_rag.contracts.protocols.DocumentParser`：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...
```

生产入口：

```python
from engineering_rag.modules.document_parser.api import create_document_parser

parser = create_document_parser(file_store, ocr_backend="rapidocr")
document = parser.parse(request)
```

MinerU 是可选私有后端，通过 `create_document_parser(..., document_engine="mineru", mineru_executable=..., mineru_home=...)` 注入；请求还必须显式设置 `config.options.document_engine="mineru"`。工厂和具体类的构造不会打开文件、加载模型或联网。MinerU 推理使用本地 `mineru-kit parse`，不调用外部解析 API。公开 Protocol 的方法签名没有变化。

`ParseRequest.source_file: FileRef` 必填；`supplied_standard`、`config`、`trace` 可空。返回值必须是 `schema_version="2.4"` 的完整或部分 Document。表格的完整结构仅在顶层 `tables[]`；Page Block 只保存物理片段。公式的权威内容在公式 Block；Clause ContentUnit 只引用 Block/Table/Formula/Asset。正文证据只有经过外部人工或权威流程核验后才能写入 `mandatory_evidence`。

## 校验、错误和部分成功

Pydantic 字段错误或悬空引用抛 `ValidationError`。Task 1.1 对缺失标准元数据、资源读取失败、非 PDF、损坏/加密 PDF、非法页码、资源上限、OCR 缺失和非法 bbox 提供明确异常；`on_page_error=continue` 时把页保留为 `not_processed` 并写入冻结 `ContractError` warnings。输出始终为 `processing.partial=true`、`is_complete_document_ocr=false`；未选页的空 blocks 不等于空白。OCR 与文本层 Block 均为 `unverified`，Page 为 `partially_transcribed`。

`ParseConfig.options` 当前支持：`page_selection`（如 `1,16,24` 或 `1-3`）、`dpi`（72～400）、`ocr_backend`、`on_page_error`、`force_ocr`、`min_text_layer_chars`、`max_pdf_bytes`、`max_selected_pages`、`max_page_pixels`，以及私有 MinerU 选项 `document_engine`、`engine_timeout_seconds`、`engine_output_dir`、`mineru_tier`、`semantic_structure`、`semantic_explanation_cover_page`。未知选项会被拒绝。未显式选页且页数超过上限时拒绝执行，避免无界处理大 PDF。语义装配默认关闭；显式启用时才在同一次 `parse()` 内生成 Section/Clause。仅选取说明正文、未包含说明封面时，应同时传入从同一文档已核验的说明封面物理页锚点，否则不应假定正文/说明分组。

MinerU 路径严格读取 `docvortex.middle` 2.0，要求 producer 为 MinerU 4.x，并将源 `page_idx` 加一恢复原 PDF 物理页码。MiddleJson 归一化 bbox 按该页 PDF point 尺寸映射到 `pdf_points/top_left`；缺失或非法 bbox 的元素只留在 raw sidecar/诊断中，不伪造位置。命令超时、非零退出、协议版本不兼容和不安全 ZIP 都是显式失败。成功输出仍为 `partial=true`、全部识别候选为 `unverified`。

MinerU 表格 HTML 只由有资源上限的本地解析器读取，不执行脚本、不请求外部资源；嵌套/多个表、非法跨度和超限输入显式失败。原始物理格位写入 `RawTableGrid`，跨行/跨列覆盖位不会复制工程值；派生 `columns`/`data` 保留字符串、空值、单位、符号和精度。只有显式编号表注进入 `notes`，未编号表注保留在 sidecar 和诊断。自动跨页合并同时要求原始物理页相邻、显式续表标识、表号一致和列签名相容；证据不足或冲突时不合并。续页重复表头保留在 raw grid/sidecar，但不进入派生数据行。

MinerU 公式只接受原生 `equation` block；正文行内数学仍属于 Body。每个公式由源文件、原始物理页和源 block index 生成稳定 ID，不依赖 LaTeX 文本。只有公式原生 `\\tag{...}` 或具备右侧对齐证据的 number region 才能形成 `printed` 编号；正文引用、条文号和单位括号不作为编号。无可靠编号保持 `unknown + null`，机器流程不会产生 `confirmed_absent` 或 `verified`。多条公式仅在共享后续“式中”证据时合组，否则单公式单组。原始公式图片、单式 bbox、编号证据、符号来源和疑点保留在私有 sidecar；路径穿越、外链、缺 bbox、超限 LaTeX 和不支持协议显式诊断或拒绝。

若 `FileRef.size_bytes` 或 `sha256` 已声明，Parser 在流式复制时核对实际字节数与增量 SHA-256；不一致抛私有 `SourceIntegrityError`，未声明字段维持可选语义。原生文字层 bbox 经 PyMuPDF `rotation_matrix` 转到可视页面坐标，并与 CropBox 可视区域求交；部分裁切和完全不可见块写入私有诊断。`diagnostics.json` 的 OCR 页面包含 confidence count/min/max/mean 摘要，但 confidence 不会把 Block 提升为 `verified`。

Task 1.5 语义层先判页面分区，再识别 Title Block 中的章/节，并仅从 Body Block 段首的三段式条文号建立 Clause。分项号、表号、公式号、正文引用和页码不会创建 Clause。跨页仅在物理页连续、内容组一致且存在已确认前置 Clause 时延续；孤立续页、缺父 Section、来源冲突均进入私有 pending sidecar。跨页表格以一个 table ContentUnit 引用全部 fragments；完整公式组以一个 formula ContentUnit 引用组内全部公式 ID。说明条文只在当前 Document 存在唯一同号正文条文时建立 `explains_clause_id`。`is_mandatory` 默认保持 null。

`plain_text` 只调用冻结的 `derive_clause_plain_text()` 生成；选页边界或来源不完整时保留三字段为 null 并写 review warning。静态 DTO 校验只证明声明之间自洽，不能证明页面分类、条文、表格或公式识别完整且准确。真实质量必须由带来源、版次和人工复核状态的 Golden Dataset 评估；本阶段不伪造准确率。

## 副作用、幂等、排序与依赖

`parse` 只通过注入的 `FileStore.read` 读取源文件，不写索引。源流按块复制到自动清理的临时目录；只处理选页。Document ID 基于 File 身份和标准版次，Block/Table/Formula/FormulaGroup ID 基于来源哈希、物理页和源锚点，均不使用 OCR 文本哈希。相同 raw 重放不会重复公式 Block，LaTeX 修正不改变身份。基础路径 reading order 是确定性几何启发式；MinerU 路径按原始 block 顺序建立唯一 reading order。实现仅依赖 contracts、自身 internal 和注入的 FileStore Protocol；导入 API 不接触外部服务。指定 `engine_output_dir` 时会保存本地 raw/log sidecar；否则使用自动清理的临时目录。

## Task 1.5 私有回放与副产物

`scripts/assemble_mineru_clauses.py` 只重放有界的本地 MinerU MiddleJson 和 Task 1.3/1.4 私有装配器，输出合法 V2.4 partial Document、来源 lineage、pending links、章节/条文摘要和页面 overlay。原始 JSON 不覆盖、不上传。脚本不是新的公共 Protocol；`DocumentParser.parse` 签名不变。普通单元测试使用离线合成 fixture，真实产物测试由 `ENGINEERING_RAG_RUN_REAL_MINERU=1` 显式启用。

## 接口示例与版本

Python API 版本 1；Document 持久化 Schema 为 **2.4 FROZEN**。Task 1.5 仅使用冻结已有的 PageType、Section、Clause 与 ContentUnit 字段，公共 Schema/Protocol 未变。页面、条文、公式和表格机器结果均为 `unverified` 候选，整体仍为 partial Document。旧版及 `2.4-proposal` 必须显式迁移和核验，破坏性变更另立版本和 ADR。

常规安装与独立测试：`python -m pip install -e '.[dev,parser-ocr]'`，然后运行 `python -m pytest src/engineering_rag/modules/document_parser/tests -q`。MinerU 使用独立虚拟环境和 `requirements/mineru-task1-2.txt`，不会成为主项目导入依赖。
