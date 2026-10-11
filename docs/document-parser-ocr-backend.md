# Document Parser Task 1.1 OCR 后端

首个生产适配器采用 `rapidocr-onnxruntime` 1.x，以 ONNX Runtime 在 CPU 上执行中文文字检测、方向分类和识别。项目环境实测版本为 RapidOCR 1.4.4、ONNX Runtime 1.31.0；RapidOCR 为 Apache-2.0，ONNX Runtime 为 MIT。默认检测/分类/识别模型随 Python wheel 安装，本次运行没有额外下载权重，也不在模块 import 或工厂构造时加载模型。

安装：

```bash
python -m pip install -e '.[dev,parser-ocr]'
```

PyMuPDF 1.28.2 用于 PDF 几何和渲染，采用 AGPL-3.0 / Artifex 商业双许可；部署前必须由项目方确认适用许可。Pillow 只用于诊断 overlay 和测试扫描图像。

OCR 是 Parser 私有可替换 `PageTextRecognizer`，不会进入冻结公共契约。缺少依赖时抛出带安装指导的 `OcrUnavailableError`；引擎返回非法 polygon、非有限坐标或越界 bbox 时拒绝该页，不会静默裁剪成合法框。模型 confidence 以 count/min/max/mean 摘要写入 Parser 私有逐页 diagnostics；它不进入冻结 Document DTO，所有自动 OCR Block 仍是 `unverified`，不能视为人工核验。

测试中的 Fake OCR 只验证装配、失败恢复和坐标转换，不作为真实 OCR 证据。合成扫描件和 GB 50010 烟测必须实际调用 RapidOCR，并与 Fake 测试分开报告。
