"""将 GB 50010 ChunkBatch 写入 Elasticsearch 并执行 BM25 检索。

本示例只调用 ``keyword_retrieval`` 模块公开 API，不直接构造 Elasticsearch DSL，因而也可
作为其他模块接入 ``KeywordRetrievalService`` 的参考。默认输入是 Task 2 生成的语义清洗版
ChunkBatch；路径、索引名、查询和过滤条件均可通过命令行覆盖。

运行前先启动仓库提供的本地 Elasticsearch：

    docker compose -f docker-compose.elasticsearch.yml up -d

推荐显式设置服务地址，并排除本机代理：

    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
    ELASTICSEARCH_URL=http://127.0.0.1:9200 \
      python examples/keyword_retrieval_gb50010.py index

常用命令：

    # 入库完整文档快照。
    python examples/keyword_retrieval_gb50010.py index

    # 普通 BM25 检索。
    python examples/keyword_retrieval_gb50010.py search \
      --query "承载能力极限状态" --top-k 10

    # 指定标准、版本、条文和内容类型过滤。
    python examples/keyword_retrieval_gb50010.py search \
      --query "结构重要性系数 内力设计值" \
      --standard-code "GB 50010-2010" --edition "2015年版" \
      --clause-number 3.3.2 --content-type clause

    # 入库后连续运行普通检索和文档过滤检索。
    python examples/keyword_retrieval_gb50010.py demo

    # 只删除该 document_id 在目标索引中的 Chunk，不删除整个索引。
    python examples/keyword_retrieval_gb50010.py delete-document \
      --document-id doc-dab4ba42814d5a878df723d32b346337

所有命令都要求环境变量 ``ELASTICSEARCH_URL``。默认索引为
``engineering-rag-gb50010-v6``，与模块通用默认索引隔离。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from engineering_rag.contracts.chunks import ChunkBatch, ChunkContentType
from engineering_rag.contracts.retrieval import (
    IndexRequest,
    KeywordSearchRequest,
    RetrievalResult,
    SearchFilters,
)
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_keyword_retrieval_service,
)

# 根据脚本位置解析项目根目录，避免把某台开发机的绝对路径写入代码。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH_PATH = (
    PROJECT_ROOT / "data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json"
)
DEFAULT_INDEX_NAME = "engineering-rag-gb50010-v6"
DEFAULT_QUERY = "承载能力极限状态"


def _load_batch(path: Path) -> ChunkBatch:
    """读取并通过公共 Chunk V1 契约完整校验输入文件。

    使用 ``model_validate_json`` 而非普通 ``json.loads``，可以在连接 Elasticsearch 前发现
    schema_version、来源引用、页码范围、ID 或 embedding_text 等契约问题。
    """

    if not path.is_file():
        raise FileNotFoundError(f"ChunkBatch 文件不存在：{path}")
    return ChunkBatch.model_validate_json(path.read_text(encoding="utf-8"))


def _load_config() -> ElasticsearchKeywordConfig:
    """从环境变量加载私有 Elasticsearch 配置，并给出明确的缺失配置错误。"""

    config = ElasticsearchKeywordConfig.from_env()
    if config.url is None:
        raise RuntimeError("缺少 ELASTICSEARCH_URL；例如设置为 http://127.0.0.1:9200")
    return config


def _index_batch(*, batch_path: Path, index_name: str, replace_document: bool) -> ChunkBatch:
    """校验并写入一个 ChunkBatch，返回已校验的批次供 demo 后续检索使用。"""

    batch = _load_batch(batch_path)
    request = IndexRequest(
        index_name=index_name,
        # operation_id 用于本次调用追踪，不承担 Chunk 幂等身份；幂等性由 chunk_id 保证。
        operation_id=f"gb50010-v6-index-{uuid4().hex}",
        replace_document=replace_document,
    )

    print(f"输入文件：{batch_path}")
    print(f"Document ID：{batch.document_id}")
    print(f"待写入 Chunk：{len(batch.chunks)}")
    print(f"目标索引：{index_name}")

    config = _load_config()
    # 上下文管理器确保官方 Elasticsearch 客户端在成功或异常时都被关闭。
    with create_keyword_retrieval_service(config) as service:
        result = service.index(batch, request)

    print(result.model_dump_json(indent=2))
    if result.failures:
        raise RuntimeError(
            f"入库存在失败：{len(result.failures)}/{result.attempted}；详情见上述 IndexResult"
        )
    if result.indexed != len(batch.chunks):
        raise RuntimeError(
            f"入库数量不一致：indexed={result.indexed}, expected={len(batch.chunks)}"
        )

    print(f"入库成功：{result.indexed}/{result.attempted}")
    return batch


def _search(
    *,
    index_name: str,
    query: str,
    top_k: int,
    filters: SearchFilters,
    content_chars: int,
) -> list[RetrievalResult]:
    """通过公开 search() API 执行 BM25 检索并打印公共 RetrievalResult。"""

    request = KeywordSearchRequest(
        query=query,
        top_k=top_k,
        filters=filters,
        index_name=index_name,
    )
    config = _load_config()
    with create_keyword_retrieval_service(config) as service:
        results = service.search(request)

    # content_chars=0 表示输出完整 content；正数适合终端快速检查命中结果。
    def display_content(result: RetrievalResult) -> str:
        if content_chars == 0 or len(result.content) <= content_chars:
            return result.content
        return f"{result.content[:content_chars]}……"

    payload = [
        {
            "rank": result.rank,
            "score": result.score,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "standard_code": result.standard.standard_code,
            "edition": result.standard.edition,
            "clause_number": result.clause_number,
            "page_start": result.page_start,
            "page_end": result.page_end,
            "content": display_content(result),
        }
        for result in results
    ]
    print(f"查询：{query}")
    print(f"返回数量：{len(results)}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return results


def _filters_from_args(args: argparse.Namespace) -> SearchFilters:
    """把可重复的 CLI 过滤参数转换为公共 SearchFilters。"""

    return SearchFilters(
        document_ids=args.document_id,
        standard_codes=args.standard_code,
        editions=args.edition,
        clause_numbers=args.clause_number,
        content_types=args.content_type,
        is_explanation=args.is_explanation,
        is_mandatory=args.is_mandatory,
    )


def _delete_document(*, index_name: str, document_id: str) -> None:
    """精确删除一个文档的 Chunk；不会删除索引、其他文档或数据卷。"""

    config = _load_config()
    with create_keyword_retrieval_service(config) as service:
        result = service.delete_document(document_id, index_name)
    print(result.model_dump_json(indent=2))


def _add_search_options(parser: argparse.ArgumentParser) -> None:
    """为 search 子命令集中声明查询和元数据过滤参数。"""

    parser.add_argument("--query", default=DEFAULT_QUERY, help="BM25 查询文本")
    parser.add_argument("--top-k", type=int, default=10, help="返回结果数量，默认 10")
    parser.add_argument(
        "--content-chars",
        type=int,
        default=500,
        help="每条命中展示的 content 字符数；0 表示完整输出",
    )
    parser.add_argument(
        "--document-id",
        action="append",
        default=[],
        help="精确过滤 document_id；可重复传入",
    )
    parser.add_argument(
        "--standard-code",
        action="append",
        default=[],
        help="精确过滤标准代码；可重复传入",
    )
    parser.add_argument(
        "--edition",
        action="append",
        default=[],
        help="精确过滤标准版本；可重复传入",
    )
    parser.add_argument(
        "--clause-number",
        action="append",
        default=[],
        help="精确过滤条文编号；可重复传入",
    )
    parser.add_argument(
        "--content-type",
        action="append",
        choices=[item.value for item in ChunkContentType],
        default=[],
        help="过滤 Chunk 内容类型；可重复传入",
    )
    # BooleanOptionalAction 同时生成 --is-explanation/--no-is-explanation，并以 None 表示不筛选。
    parser.add_argument(
        "--is-explanation",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="筛选条文说明或非条文说明；不传表示不筛选",
    )
    parser.add_argument(
        "--is-mandatory",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="筛选强制性状态；不传表示不筛选",
    )


def _build_parser() -> argparse.ArgumentParser:
    """创建命令行解析器。"""

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--index",
        default=DEFAULT_INDEX_NAME,
        help=f"Elasticsearch 索引名，默认 {DEFAULT_INDEX_NAME}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="校验并写入 ChunkBatch")
    index_parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH_PATH)
    index_parser.add_argument(
        "--replace-document",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="把批次视为完整文档快照；默认启用",
    )

    search_parser = subparsers.add_parser("search", help="执行 BM25 关键词检索")
    _add_search_options(search_parser)

    demo_parser = subparsers.add_parser("demo", help="依次执行入库、普通检索和文档过滤检索")
    demo_parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH_PATH)
    demo_parser.add_argument("--query", default=DEFAULT_QUERY)
    demo_parser.add_argument("--top-k", type=int, default=10)
    demo_parser.add_argument("--content-chars", type=int, default=500)

    delete_parser = subparsers.add_parser(
        "delete-document", help="精确删除指定 document_id 的 Chunk"
    )
    delete_parser.add_argument("--document-id", required=True)
    return parser


def main() -> int:
    """解析命令并执行对应公开服务调用。"""

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "index":
        _index_batch(
            batch_path=args.batch,
            index_name=args.index,
            replace_document=args.replace_document,
        )
        return 0

    if args.command == "search":
        if args.content_chars < 0:
            parser.error("--content-chars 不能小于 0")
        _search(
            index_name=args.index,
            query=args.query,
            top_k=args.top_k,
            filters=_filters_from_args(args),
            content_chars=args.content_chars,
        )
        return 0

    if args.command == "demo":
        if args.content_chars < 0:
            parser.error("--content-chars 不能小于 0")
        batch = _index_batch(
            batch_path=args.batch,
            index_name=args.index,
            replace_document=True,
        )
        print("\n=== 普通 BM25 检索 ===")
        _search(
            index_name=args.index,
            query=args.query,
            top_k=args.top_k,
            filters=SearchFilters(),
            content_chars=args.content_chars,
        )
        print("\n=== 当前 Document 精确过滤检索 ===")
        _search(
            index_name=args.index,
            query=args.query,
            top_k=args.top_k,
            filters=SearchFilters(document_ids=[batch.document_id]),
            content_chars=args.content_chars,
        )
        return 0

    if args.command == "delete-document":
        _delete_document(index_name=args.index, document_id=args.document_id)
        return 0

    # argparse 的 required=True 已保证不会到达这里；保留防御性分支便于静态检查。
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
