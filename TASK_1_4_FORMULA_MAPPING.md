# Task 1.4 — MinerU 原始公式 → V2.4 Frozen 映射规则

## 1. 数据流与职责

```text
GB 扫描 PDF（真实页号、PDF SHA256）
     ↓
Task 1.2 已部署的本地 MinerU（版本 / tier / parse_mode）
     ↓
MiddleJson + 公式原始图片/区域 + 可用文本/LaTeX + 日志
     ↓
Parser 私有 CandidateEquation / NumberEvidence / SymbolEvidence
     ↓
公式编号空间匹配 → 保守分组 → “式中”解释关联 → 几何/页码校正
     ↓
已有 Document V2.4 的 pages[].blocks[] + 公式组
     ↓
重新 model_validate + JSON roundtrip + sidecar / overlay / diagnostics
```

**不写顶层 `formulas[]`**；V2.4 没有此字段。公式权威内容位于 `PageBlock.ocr.formula_group.equations[]`。

## 2. 冻结模型字段映射

| 来源/含义 | V2.4 目的字段 | 约束 | 额外 raw sidecar |
|---|---|---|---|
| 源 PDF + page idx | `pages[].page_number` | **原始 PDF 物理页**，1 起 | 选页临时 PDF 索引映射 |
| 公式区域 | `PageBlock.bbox` | PDF points, top_left，界内 | 每条公式和编号的局部 bbox |
| 公式块 | `block_type="formula"` | 不得与已有同一源块重复 | 原生 MinerU block id / block index |
| 公式组身份 | `formula_group_id` | 文档内唯一、稳定 | 分组依据、组建版本 |
| 原始 LaTeX | `Equation.latex` | 可为空；不能改写语义 | raw 转写、图片与置信信息 |
| 公式识别状态 | `Equation.recognition_status` | 机器默认 unverified | model tier、转写警告 |
| 印刷公式编号 | `equation_number` | 无证据为 `null` | 编号原文及 bbox |
| 编号状态 | `equation_number_status` | printed / confirmed_absent / unknown | number matcher 正反证据 |
| 唯一方程身份 | `formula_id` | 稳定，不用 LaTeX 哈希 | 锚点与人工 ID 映射台账 |
| 符号解释 | `symbol_explanations.items[]` | 原文符号+latex?+description，不拆 unit | “式中”原段落和行 / bbox |
| 渲染顺序 | `reading_order` | 整页唯一，和现有 block 统一排序 | OCR line/span order |
| 来源诊断 | Document 现有 processing warning（若能合法表达）| 不扩展 Schema | 完整 source snippet / confidence |

## 3. V2.4 有效示意（仅公式 Block 片段）

下面的公式内容与 ID 仅为**合成演示**，不表示已对真实 GB 页面完成 OCR：

```json
{
  "block_id": "p050_formula_group_001",
  "block_type": "formula",
  "bbox": {"x_min": 105.0, "y_min": 104.0, "x_max": 320.0, "y_max": 150.0},
  "reading_order": 6,
  "recognition_status": "unverified",
  "bbox_status": "detected",
  "extraction_method": "mineru",
  "formula_group_id": "fg-p050-001",
  "ocr": {
    "formula_group": {
      "equations": [
        {
          "formula_id": "eq-p050-001",
          "equation_number": "6.2.1-1",
          "equation_number_status": "printed",
          "latex": "\\sigma_c = f_c ",
          "text": null,
          "recognition_status": "unverified"
        }
      ],
      "symbol_explanations": null
    }
  }
}
```

注意上面只是 PageBlock 形状示意，完整 Document 仍需满足 Page、Processing、Document 的全部必填字段和关系约束；示意 bbox 不能作为真实 PDF 输出。

## 4. 三态编号原则（Frozen validator）

| 机器/人工证据 | `equation_number` | `equation_number_status` | `recognition_status` |
|---|---|---|---|
| 印刷编号被模型/图像证据识别 | 真实字符串 | `printed` | `unverified`（未人工核验时） |
| 附近没有识别到编号 | `null` | `unknown` | `unverified` 或 `not_transcribed` |
| 人工已核对确实无印刷编号，且 LaTeX 核验 | `null` | `confirmed_absent` | `verified` |
| 公式只有图像，不能转录 | `null` | `unknown` | `not_transcribed` |
| 公式编号有相互冲突候选 | `null` | `unknown` | `unverified`（如有可用 LaTeX） |

`verified` 的方程要求 `latex` 非空且 `equation_number_status != unknown`。`not_transcribed` 不允许填 LaTeX。非公式 PageBlock 禁止含 `formula_group_id` / `ocr.formula_group`。

## 5. 版面和分组策略

- 组 ID 不是公式编号：连续公式可能同组且各有不同印刷编号。默认一个方程一个组，只有可靠的排版与共享符号解释证据才归组。
- 一个有 `aligned` 或 `cases` 的多行 LaTeX 仍可能是**一条公式**，按真实印刷编号数和框对应关系判定，不按源码换行切段。
- `Equation` 没有单式 bbox。每式 bbox、编号 bbox、公式图片、原 OCR span、坐标单位与缩放矩阵都保留到 sidecar。
- 对于 Task 1.2 的已有公式 Block，必须更新/复用它而非在相同来源上新增重复块。
- “式中”解释归属靠邻近几何、页内阅读顺序和无冲突边界；在读到新条文标题、下一公式组或其它明确边界时停止。没足够证据则保留 Body + raw，而不强行附到最近的公式。
- 长释义经 OCR 换行会连续拼接，不遗漏单位，不将 `单位` 写成新的未定义属性。
- 正文中的行内公式保持 Body/私有 spans，不机械转换为 Formula Block。

## 6. 真实测试场景与预期问题

| 实体样本 | 实际可见特点 | 检查 |
|---|---|---|
| GB 50010 PDF 物理 24 页 | 两条独立编号公式与长“式中”段 | 编号关联、解释归属、保留其它正文 |
| GB 50010 PDF 物理 50 页 | `6.2.1-1` 到 `6.2.1-7` 的密集公式和变量说明 | 多编号不串号，折行/单位/多组不误拆 |
| GB 50010 PDF 物理 301 页 | 条文说明含无紧邻印刷编号的公式 | 未核验机器结果仍 `unknown`；不自动标 `confirmed_absent` |

这些现象来自对原扫描图的抽查，不是 MinerU 实测精度。案例上 `page_number` 使用 PDF 的物理页号，而不是扫描图页脚号码。

## 7. 不能无损映射的内容

**不要修改公共 V2.4 来适配 MinerU。** 下面内容保留在 Parser 私有产物：单方程精细 bbox、编号框、候选多分数、OCR 模型置信度、公式 crop、未确认的“式中”原文、行内数学表达式 span 及无法归组的 block。

不能以 `verified` 或 `processing.partial=false` 掩盖缺失；Document JSON 合法仅证明契约有效，不证明数学识别正确。
