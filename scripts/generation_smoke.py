"""Explicit real-API smoke with fictional evidence; never a human-gold evaluation.

Run from the repository root with ``python -m scripts.generation_smoke``.
Uses the existing literal .env loader and provider adapter, not another LLM client.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from time import monotonic

from scripts._query_smoke_runtime import load_env_file, safe_error_code, write_json

from engineering_rag.contracts.answers import GenerationRequest, validate_answer_citations
from engineering_rag.infrastructure.llm.api import LLMSettings, OpenAICompatibleLLMClient
from engineering_rag.modules.generation.api import GenerationSettings, create_generation_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--request", type=Path, default=Path("examples/generation_request.example.json")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-real-api", action="store_true", help="Explicitly allow billable API calls"
    )
    args = parser.parse_args()
    if not args.allow_real_api:
        parser.error("--allow-real-api is required; no API call was made")
    settings = None
    client = None
    service = None
    started = monotonic()
    try:
        output = args.output_dir.absolute()
        if output.exists() or any(part.is_symlink() for part in (output, *output.parents)):
            raise ValueError("output must be a new non-symlink directory")
        values = dict(os.environ)
        if args.env_file:
            values = load_env_file(args.env_file, values)
        settings = LLMSettings.from_env(values)
        if args.request.is_symlink() or not args.request.is_file():
            raise ValueError("request must be a regular file")
        raw = args.request.read_bytes()
        request = GenerationRequest.model_validate_json(raw)
        client = OpenAICompatibleLLMClient(settings)
        service = create_generation_service(
            llm=client,
            settings=GenerationSettings(
                llm=settings.structured_config("generation-smoke"),
                provider=settings.provider,
                max_attempts=settings.max_attempts,
            ),
        )
        answer = service.generate(request)
        if not answer.citations or validate_answer_citations(answer, request.evidence):
            raise ValueError("smoke requires mapped input evidence citations")
        output.mkdir(parents=True, exist_ok=False)
        secrets = [settings.api_key.get_secret_value()]
        write_json(output / "answer.json", answer.model_dump(mode="json"), secrets)
        write_json(
            output / "report.json",
            {
                "status": "PASS",
                "test_kind": "real_api_with_example_evidence",
                "human_verified_real_evidence": False,
                "semantic_correctness_human_review": "NOT RUN",
                "provider": settings.provider,
                "model_id": settings.model_id,
                "elapsed_seconds": monotonic() - started,
                "request_sha256": hashlib.sha256(raw).hexdigest(),
                "generation_calls": service.calls,
                "adapter_calls": client.calls,
                "answer_schema_valid": True,
                "citation_identity_valid": True,
                "grounding_status": answer.grounding_status,
            },
            secrets,
        )
        print(f"PASS: real API with example evidence; artifacts: {output}")
        return 0
    except Exception as exc:
        # Never echo validation inputs, provider bodies, environment or secrets.
        print(f"BLOCKED: {safe_error_code(exc)}; no successful smoke result claimed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
