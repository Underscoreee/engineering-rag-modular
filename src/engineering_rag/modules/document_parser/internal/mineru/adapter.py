"""Version-aware local MinerU 4.x adapter."""

from __future__ import annotations

import json
from pathlib import Path

from .models import MinerUParseRequest, MinerUParseResult
from .normalizer import normalize_middle_json, read_middle_json
from .runner import MinerUExecutionError, run_local, safe_extract_zip


class MinerUAdapter:
    engine_id = "mineru"

    def __init__(self, executable: Path, mineru_home: Path) -> None:
        self._executable = executable
        self._mineru_home = mineru_home

    def probe_version(self) -> str:
        output = self._mineru_home / "probe"
        result = run_local(
            [str(self._executable), "version", "--json"],
            timeout_seconds=30,
            stdout_path=output / "stdout.log",
            stderr_path=output / "stderr.log",
            mineru_home=self._mineru_home,
        )
        del result
        try:
            payload = json.loads((output / "stdout.log").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MinerUExecutionError("MinerU version output is not JSON") from exc
        version = payload.get("mineru_version") if isinstance(payload, dict) else None
        if not isinstance(version, str) or not version.startswith("4."):
            raise MinerUExecutionError(f"MinerU 4.x required, found {version!r}")
        return version

    def parse(self, request: MinerUParseRequest, *, bundle: bool = False) -> MinerUParseResult:
        self.probe_version()
        raw_dir = request.output_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        output = raw_dir / ("mineru-output.zip" if bundle else "middle_json.json")
        command = [
            str(self._executable),
            "parse",
            str(request.source_pdf),
            "-o",
            str(output),
            "--pages",
            _page_spec(request.source_pages or request.original_pages),
            "--format",
            "zip" if bundle else "middle_json",
            "--tier",
            request.tier,
            "--ocr-mode",
            request.ocr_mode,
        ]
        run = run_local(
            command,
            timeout_seconds=request.timeout_seconds,
            stdout_path=request.output_dir / "stdout.log",
            stderr_path=request.output_dir / "stderr.log",
            mineru_home=self._mineru_home,
        )
        artifacts = [output]
        if bundle:
            extracted = safe_extract_zip(output, raw_dir / "bundle")
            artifacts.extend(extracted)
            middle = raw_dir / "bundle" / "middle_json.json"
        else:
            middle = output
        if not middle.is_file():
            raise MinerUExecutionError("MinerU succeeded without middle_json.json")
        schema_id, schema_version, producer, pages, diagnostics = normalize_middle_json(
            read_middle_json(middle),
            expected_pages=request.original_pages,
            page_idx_to_original=(
                dict(
                    zip(
                        (page - 1 for page in request.source_pages),
                        request.original_pages,
                        strict=True,
                    )
                )
                if request.source_pages is not None
                else None
            ),
        )
        return MinerUParseResult(
            schema_id=schema_id,
            schema_version=schema_version,
            producer_version=producer,
            tier=request.tier,
            parse_mode=request.ocr_mode,
            source_sha256=request.source_sha256,
            pages=pages,
            raw_middle_json=middle,
            stdout_log=run.stdout_path,
            stderr_log=run.stderr_path,
            elapsed_seconds=run.elapsed_seconds,
            raw_artifacts=artifacts,
            diagnostics=diagnostics,
        )


def _page_spec(pages: list[int]) -> str:
    return ",".join(str(page) for page in pages)
