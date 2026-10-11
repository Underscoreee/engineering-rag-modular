from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.tasks import TaskRecord


def test_terminal_task_requires_finish_time() -> None:
    with pytest.raises(ValidationError):
        TaskRecord(
            task_id="t",
            task_type="ingestion",
            status="completed",
            created_at=datetime.now(UTC),
        )


def test_failed_task_requires_error() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        TaskRecord(
            task_id="t",
            task_type="ingestion",
            status="failed",
            created_at=now,
            started_at=now,
            finished_at=now,
        )
