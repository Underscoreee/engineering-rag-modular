from pathlib import Path

from pydantic import TypeAdapter

from engineering_rag.contracts.answers import AnswerResult, validate_answer_citations
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.documents import Document
from engineering_rag.contracts.retrieval import RetrievalResult

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_every_public_example_round_trips() -> None:
    for name in ("document.example.json", "document.partial.example.json"):
        document = Document.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
        assert Document.model_validate_json(document.model_dump_json()) == document
    batch = ChunkBatch.model_validate_json(
        (EXAMPLES / "chunk_batch.example.json").read_text(encoding="utf-8")
    )
    assert ChunkBatch.model_validate_json(batch.model_dump_json()) == batch
    adapter = TypeAdapter(list[RetrievalResult])
    evidence = adapter.validate_json(
        (EXAMPLES / "retrieval.example.json").read_text(encoding="utf-8")
    )
    assert adapter.validate_json(adapter.dump_json(evidence)) == evidence
    answer = AnswerResult.model_validate_json(
        (EXAMPLES / "answer.example.json").read_text(encoding="utf-8")
    )
    assert AnswerResult.model_validate_json(answer.model_dump_json()) == answer
    assert validate_answer_citations(answer, evidence) == []
