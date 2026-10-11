# Architecture Task 1.2 — MinerU 本地真实 PDF 测试报告

日期：2026-10-11（Asia/Shanghai）  
状态：**完成真实本地执行，17/18 案例成功；P024 为已复现的引擎失败，不属于全绿发布**

## 1. 基线与冻结边界

- 开始时 Git HEAD 为 `5928f7d2dfabd7cb6519cc6b7b6a555fc44c2c83`；`document-schema-v2.4^{commit}` 为 `ebd9b29b3bb475401c8e91a30303ae46a8c119aa`。
- `git diff --quiet document-schema-v2.4 -- src/engineering_rag/contracts` 返回 0。本任务未修改冻结 Pydantic Schema 或公共 Protocol。
- 开始前完整 pytest 为 181 passed；Task 1.1 独立缺陷审计为 6 passed。旋转/CropBox 与 FileRef size/SHA 边界未回退。
- 真实 PDF 共 441 页，154,122,112 bytes，SHA256 为 `43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`。所有页号均为原 PDF 的 1-based 物理页号。

## 2. 本地部署

环境为 WSL2 Linux 6.18.40.1、Python 3.11.17、Intel i7-8550U（8 logical CPUs）、11.68 GiB RAM、4 GiB swap；运行前可用磁盘约 943 GiB。`nvidia-smi` 返回 NVML 被操作系统阻止，因此按 CPU/ONNX 路线执行。

MinerU 安装在 Git 忽略的 `.local/mineru-runtime/.venv`，与主 `.venv` 隔离：

```text
mineru==4.0.12
docvortex==0.5.16
onnxruntime==1.31.0
Python 3.11.17
tier=basic, small_backend=onnx, ocr_mode=ocr
```

官方 `MinerU-4_models_onnx` 从 Hugging Face 模型仓下载到 `.local/mineru-runtime/state/models/`；模型目录约 819 MiB，独立环境约 666 MiB。`mineru-kit models verify --tier basic --small-backend onnx` 实测输出 `MinerU-4_models_onnx: ok`。完整环境、`version --json`、`parse --help`、模型配置和 GPU 失败信息保存在 `data/eval/task1_2_mineru/environment.json`；直接依赖与实际完整包快照分别为 `requirements/mineru-task1-2.txt` 和 `.lock`。

使用的是官方文档所述的无状态 `mineru-kit parse`、`--pages`、`--tier basic --ocr-mode ocr` 与 ZIP/MiddleJson 输出；实际协议为 `docvortex.middle` 2.0、producer 4.0.12。参考：[Quick Start](https://opendatalab.github.io/MinerU/quick_start/)、[输出协议](https://opendatalab.github.io/MinerU/reference/output_files/)、[模型档位](https://opendatalab.github.io/MinerU/usage/tiers/)。软件许可证是带额外商业条件的 MinerU License；商业部署前需按[官方许可证](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)复核规模与服务署名条件。

仅软件依赖和模型下载访问网络；PDF、页面图和识别结果没有上传到外部解析服务。

## 3. 真实运行结果

首次 P016 MiddleJson 烟测成功，原始源页保留为 `page_idx=15`，输出 6 个有 bbox 的 block，并识别标题及 1.0.1～1.0.4 文本。随后执行全部 18 个案例、21 个模式；跨页案例额外分成单页，共 24 次引擎调用。

| 案例 | 模式 | 状态 | wall time（秒） | 结果摘要 |
|---|---|---:|---:|---|
| P001 | single | succeeded | 23.69 | 封面文字/标题候选 |
| P002 | single | succeeded | 7.49 | 内封信息候选 |
| P003 | single | succeeded | 8.12 | 公告文本候选 |
| P009 | single | succeeded | 9.05 | 中文目录候选 |
| P012 | single | succeeded | 9.14 | 英文目录候选 |
| P016 | single | succeeded | 8.86 | 6 blocks；正文条文编号可读 |
| P024 | single | **failed** | 26.83 | OCR/MFR 后报 `Unsupported warp settings` |
| P028029 | paired / individual | succeeded | 26.43 / 32.09 | 3.5.2、续表、表注及 3.5.3 HTML |
| P037038 | paired / individual | succeeded | 40.53 / 56.72 | 多级表头 HTML；续表和表注 |
| P050 | single | succeeded | 30.56 | 7 个展示公式，编号 6.2.1-1～7 |
| P126127 | paired / individual | succeeded | 15.97 / 22.55 | 9.1.2/续表及后续 9.1.3 文本 |
| P275 | single | succeeded | 8.60 | 用词说明文本候选 |
| P276 | single | succeeded | 8.20 | 引用标准文本候选 |
| P277 | single | succeeded | 7.78 | 说明封面候选 |
| P278 | single | succeeded | 10.36 | 修订说明候选 |
| P279 | single | succeeded | 9.76 | 说明目次候选 |
| P282 | single | succeeded | 18.62 | 条文说明正文候选 |
| P301 | single | succeeded | 27.97 | 1 个无 `tag` 展示公式候选 |

模式统计为 20 succeeded / 1 failed；调用统计为 23 succeeded / 1 failed。成功推理累计引擎耗时 360.18 秒，单次 6.60～39.51 秒。子进程全局观测最大 RSS 为 3,140,380 KiB；该数是进程级累计最大值，不冒充每案例独立峰值。23 份 normalized JSON 含 26 个页输出、161 text、17 paragraph_title、11 doc_title、16 table、8 equation 等候选。

根目录为 `data/eval/task1_2_mineru/runs/final/`。每个成功调用均有 `manifest.json`、`input_pages.json`、stdout/stderr、原始 ZIP、MiddleJson、Markdown、structured/model JSON、normalized JSON、诊断、V2.4 partial JSON 和 bbox overlay。共验证 23 份 normalized、23 份 V2.4 文档和 26 张 overlay。P024 保留失败 manifest 与 stderr，未用模拟结果填充。`run-summary.json` 因一个真实失败而使批量命令退出码为 1，这是预期的诚实失败语义。

## 4. 重点人工检查

- **中文正文 P016：** 标题和 1.0.1～1.0.4 顺序正确，中文可读；MinerU 给出的仍是通用文本块，不代表 Clause 已识别。overlay 显示 bbox 与扫描正文区域一致。
- **公式 P050：** 7 个公式都有真实 LaTeX 和末尾 `\tag{6.2.1-n}`；符号解释仍混在普通文本中。本阶段只映射独立公式，不做符号语义关联。
- **公式 P301：** 识别到 `E_c=...`，原始 LaTeX 无 `tag`。适配器因此写 `equation_number=null`、`equation_number_status=unknown`，不会把案例提示当作“已确认无号”。
- **公式 P024：** basic/ONNX 可重复失败于 `Unsupported warp settings`。最小后续动作是向上游提交不含 PDF 内容的堆栈/几何复现信息或在许可下测试修复版本；当前不能声称该页可解析。
- **表 P028–029：** 引擎分别输出“表3.5.2”和“续表3.5.2”，续页保留 2 条表注，随后另有表3.5.3；HTML 单元结构存在。
- **表 P037–038：** 4.2.2-2 首片和续片均保留 rowspan/colspan HTML，续页表注存在。paired 与 individual 的结构长度一致，但标题空格/括号 OCR 有轻微差异。
- **表 P126–127：** 9.1.2 两页均有 HTML，续表结束后的 9.1.3 是独立文本。引擎没有提供跨页共享 table identity。

三组表格在连续双页和独立单页模式下都没有原生跨页逻辑 ID。Task 1.2 适配器按物理片段分别建立 `structure_only` LogicalTable，不猜测合并；真正聚合属于 Task 1.3。

## 5. 私有适配与冻结 V2.4

私有适配器位于 `document_parser/internal/mineru/`：安全 subprocess、超时和 ZIP 防穿越；严格读取观察到的 MiddleJson 4.x；保留原页、引擎顺序、原始对象、HTML/表注/LaTeX；将 normalized top-left bbox 按协议页宽高转换为 PDF points。

映射策略是保守 partial：`page_type=unknown`，不生成 Section/Clause/强制性，所有候选 `unverified`；无可信 bbox 或缺 immutable asset 的元素留 sidecar；表格 `data/raw_grid=null`、`structure_only`；公式 ID 使用来源稳定 UUID，编号只从真实末尾 tag 提取。所有映射结果均通过冻结 Pydantic 校验和 JSON roundtrip。

已知边界：模型没有置信度；图片缺冻结 ArtifactRef 所需的稳定资产契约；HTML 不等于 V2.4 RawGrid；MiddleJson 的通用标题不能自动成为规范章节；P024 引擎失败。本阶段没有实现跨页表、公式符号解释、PageType、Clause 或条文说明关联。

## 6. 结论

最终回归实测：Document Parser 独立测试 62 passed；Task 1.1 六项审计 6 passed；contracts 独立测试 114 passed；完整 pytest 188 passed；其余六个业务模块独立测试各 1 passed；`ruff check .` 和 `ruff format --check .` 均通过。产物验证器再次得到 `normalized=23, documents=23`。最终仍确认冻结 contracts 相对 tag 无差异。

MinerU 4.0.12 已能在此 CPU/WSL 环境中可重复、本地解析大多数所选工程扫描规范页面，并输出可复核结构化原始数据。最低验收门槛已达到，但不是全绿：P024 仍是明确 blocker，所有 18 例都未有人工作为金标，因此不报告 CER、F1、TEDS 或“准确率”。后续应先验收本报告和 P024 风险，再由维护者决定 Task 1.3；本任务不自行开始后续算法。
