# Orchestrator

`engineering_rag.infrastructure.orchestrator.api.Orchestrator` 声明同步 `run_ingestion(IngestionRequest) -> TaskRecord` 和 `run_question(QuestionRequest) -> AnswerResult`。同步 ingestion 返回时任务必须处于终态；编排器只通过 Protocol 注入能力，不导入业务 internal。Task 0 无流程实现。

