# Evaluation

`engineering_rag.infrastructure.evaluation.api.EvaluationService.evaluate(EvaluationRequest) -> EvaluationReport` 统一描述 Parser、Chunking、Retrieval、Generation 的可复现评估。数据集、目标和版本必填，失败样本结构化保存。Task 0 不计算指标。

