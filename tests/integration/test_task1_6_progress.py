"""Terminal-only progress reporting for the Task 1.6 end-to-end runner."""

from inspect import signature

from scripts.run_document_parser_e2e import _arguments, _PageProgress, main


def test_progress_defaults_are_disabled() -> None:
    assert signature(main).parameters["show_progress"].default is False
    args = _arguments(
        [
            "--mode",
            "replay_saved_raw",
            "--pdf",
            "input.pdf",
            "--output",
            "run",
            "--run-id",
            "run-1",
        ]
    )
    assert args.show_progress is False
    args = _arguments(
        [
            "--mode",
            "replay_saved_raw",
            "--pdf",
            "input.pdf",
            "--output",
            "run",
            "--run-id",
            "run-1",
            "--show-progress",
        ]
    )
    assert args.show_progress is True


def test_disabled_progress_produces_no_output(capsys) -> None:
    progress = _PageProgress([1, 2, 3], enabled=False)
    progress.batch_finished([1, 2, 3], succeeded=True)
    assert capsys.readouterr().out == ""


def test_enabled_progress_reports_actual_page_count(capsys) -> None:
    progress = _PageProgress(list(range(1, 11)), enabled=True)
    progress.batch_finished([1, 2, 3, 4, 5], succeeded=True)
    progress.batch_finished([6, 7, 8, 9, 10], succeeded=True)
    assert capsys.readouterr().out.splitlines() == [
        "PDF 解析进度：5/10 页 (50%)",
        "PDF 解析进度：10/10 页 (100%)",
    ]


def test_failed_batch_is_not_counted_and_resumed_success_is_counted(capsys) -> None:
    progress = _PageProgress(list(range(1, 11)), enabled=True)
    progress.batch_finished([1, 2, 3, 4, 5], succeeded=False)
    assert capsys.readouterr().out == ""

    progress.batch_finished([1, 2, 3, 4, 5], succeeded=True)
    progress.batch_finished([6, 7, 8, 9, 10], succeeded=True)
    assert capsys.readouterr().out.splitlines() == [
        "PDF 解析进度：5/10 页 (50%)",
        "PDF 解析进度：10/10 页 (100%)",
    ]
