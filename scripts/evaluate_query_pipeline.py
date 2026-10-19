"""Run Query evaluation, keeping fictional demonstrations separate from official metrics.

Example commands and manual annotation instructions: docs/task-6.5-query-evaluation.md.
Real runtimes are supplied by an explicit trusted composition factory, not guessed
from a model name or database address. No automatic indexing or model download.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path

from engineering_rag.contracts.common import ArtifactRef
from engineering_rag.contracts.evaluation import EvaluationRequest, EvaluationTarget
from engineering_rag.infrastructure.evaluation.api import create_evaluation_service, load_dataset
from engineering_rag.infrastructure.evaluation.internal.dataset import safe_read_json
from engineering_rag.infrastructure.evaluation.internal.offline import create_offline_runtime
from engineering_rag.infrastructure.evaluation.internal.run_models import (
    EvaluationRuntime,
    RunConfig,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--corpus-snapshot-id", required=True)
    parser.add_argument(
        "--mode",
        choices=["validate_only", "offline_test", "retrieval_eval", "llm_e2e_eval"],
        default="validate_only",
    )
    parser.add_argument("--variants", default="raw,rewrite,rewrite_expansion,rewrite_hyde,full")
    parser.add_argument("--ks", default="5,10,20")
    parser.add_argument("--relevance-threshold", type=int, default=2)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--fusion-strategy", choices=["rrf", "weighted_normalized"], default="rrf")
    parser.add_argument("--keyword-weight", type=float, default=0.5)
    parser.add_argument("--vector-weight", type=float, default=0.5)
    parser.add_argument("--keyword-index")
    parser.add_argument("--vector-collection")
    parser.add_argument("--embedding-model-id")
    parser.add_argument("--snapshot-manifest", type=Path)
    parser.add_argument("--require-verified", action="store_true")
    parser.add_argument("--code-revision")
    parser.add_argument(
        "--runtime-factory",
        help=(
            "trusted module:function(EvaluationRequest)->EvaluationRuntime; "
            "not imported for validate_only"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = {
        "mode": args.mode,
        "variants": args.variants,
        "ks": args.ks,
        "corpus_path": str(args.corpus),
        "corpus_snapshot_id": args.corpus_snapshot_id,
        "output_dir": str(args.output_dir),
        "run_id": args.run_id,
        "candidate_k": args.candidate_k,
        "relevance_threshold": args.relevance_threshold,
        "fusion_strategy": args.fusion_strategy,
        "keyword_weight": args.keyword_weight,
        "vector_weight": args.vector_weight,
        "require_verified": args.require_verified,
    }
    for name in (
        "keyword_index",
        "vector_collection",
        "embedding_model_id",
        "snapshot_manifest",
        "code_revision",
    ):
        if (value := getattr(args, name)) is not None:
            options[name] = str(value)
    try:
        manifest = safe_read_json(args.dataset / "manifest.json")
        request = EvaluationRequest(
            evaluation_type="retrieval",
            dataset=ArtifactRef(
                artifact_id=manifest["dataset_id"],
                artifact_type="query_golden_dataset",
                uri=str(args.dataset),
                media_type="application/json",
                schema_version="1.0",
                artifact_version=args.dataset_version,
                sha256=hashlib.sha256((args.dataset / "manifest.json").read_bytes()).hexdigest(),
            ),
            dataset_version=args.dataset_version,
            target=EvaluationTarget(component_id="query_pipeline", component_version="query-2.0"),
            config=options,
        )
        config = RunConfig.from_options(request.config)
        dataset = load_dataset(
            args.dataset,
            corpus_path=args.corpus,
            snapshot_id=args.corpus_snapshot_id,
            formal=args.require_verified,
        )
        runtime = None
        if args.mode != "validate_only" and args.runtime_factory:
            module_name, function_name = args.runtime_factory.split(":", 1)
            factory = getattr(importlib.import_module(module_name), function_name)
            runtime = factory(request.model_copy(deep=True))
            if not isinstance(runtime, EvaluationRuntime):
                raise ValueError("runtime factory must return EvaluationRuntime")
        elif args.mode == "offline_test" and dataset.manifest.is_test_fixture:
            runtime = create_offline_runtime(dataset.batch, config)
        create_evaluation_service(runtime=runtime).evaluate(request)
        output = args.output_dir / args.run_id
        result = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    except (ValueError, OSError, TypeError, KeyError, ImportError) as exc:
        parser.exit(2, f"evaluation input/configuration error: {exc}\n")
    print(f"{result['status']}: {output}")
    if result["is_simulation"]:
        print("OFFLINE SIMULATION ONLY; real retrieval quality NOT RUN")
    return 2 if result["status"] in {"NOT RUN", "PARTIAL"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
