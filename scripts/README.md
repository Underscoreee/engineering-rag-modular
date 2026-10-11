# Scripts

Task 1.2 提供以下有界、本地 MinerU 工具：

- `mineru_env_check.py`：记录主机、MinerU、模型与命令帮助。
- `prepare_mineru_eval_cases.py`：只渲染案例清单声明的页面。
- `run_mineru_cases.py`：运行显式案例/模式，支持超时、重试与 dry-run。
- `visualize_mineru_results.py`：把归一化 bbox 叠加到原 PDF 页。
- `validate_mineru_outputs.py`：用私有模型和冻结 Document V2.4 回读产物。

这些工具不会上传 PDF，也不会默认分析整份文档。MinerU 使用独立环境；常规项目测试无需安装它。
