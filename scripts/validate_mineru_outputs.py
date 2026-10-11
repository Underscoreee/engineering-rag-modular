#!/usr/bin/env python3
"""Validate normalized MinerU and partial V2.4 JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engineering_rag.contracts.documents import Document
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    normalized = sorted(args.root.rglob("normalized.json"))
    documents = sorted(args.root.rglob("document.v2.4.partial.json"))
    for path in normalized:
        MinerUParseResult.model_validate_json(path.read_text(encoding="utf-8"))
    for path in documents:
        document = Document.model_validate_json(path.read_text(encoding="utf-8"))
        Document.model_validate_json(document.model_dump_json())
    print(json.dumps({"normalized": len(normalized), "documents": len(documents)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
