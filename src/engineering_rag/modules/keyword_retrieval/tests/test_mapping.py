import pytest

from engineering_rag.modules.keyword_retrieval.internal.config import ElasticsearchKeywordConfig
from engineering_rag.modules.keyword_retrieval.internal.errors import KeywordIndexCompatibilityError
from engineering_rag.modules.keyword_retrieval.internal.mapping import (
    build_index_definition,
    validate_existing_mapping,
)


def test_mapping_is_explicit_strict_and_uses_configured_analyzer() -> None:
    definition = build_index_definition(ElasticsearchKeywordConfig(analyzer="standard"))
    mappings = definition["mappings"]
    properties = mappings["properties"]

    assert mappings["dynamic"] == "strict"
    assert properties["chunk_id"] == {"type": "keyword"}
    assert properties["logical_chunk_id"] == {"type": "keyword"}
    assert properties["document_id"] == {"type": "keyword"}
    assert properties["search_text"] == {"type": "text", "analyzer": "standard"}
    assert properties["standard"]["properties"]["standard_code"] == {"type": "keyword"}
    assert properties["source_refs"] == {"type": "object", "enabled": False}
    assert definition["settings"]["index"]["similarity"]["default"] == {"type": "BM25"}


def test_mapping_records_analyzer_without_silent_fallback() -> None:
    definition = build_index_definition(ElasticsearchKeywordConfig(analyzer="ik_max_word"))

    assert definition["mappings"]["properties"]["search_text"]["analyzer"] == "ik_max_word"
    assert definition["mappings"]["_meta"]["analyzer"] == "ik_max_word"


def test_mapping_metadata_cannot_hide_an_incompatible_field() -> None:
    config = ElasticsearchKeywordConfig()
    mappings = build_index_definition(config)["mappings"]
    mappings["properties"]["document_id"] = {"type": "text"}

    with pytest.raises(KeywordIndexCompatibilityError, match="document_id"):
        validate_existing_mapping(
            {"chunks": {"mappings": mappings}},
            index_name="chunks",
            config=config,
        )


def test_mapping_accepts_elasticsearch_implied_object_type_normalization() -> None:
    config = ElasticsearchKeywordConfig()
    mappings = build_index_definition(config)["mappings"]
    del mappings["properties"]["standard"]["type"]
    del mappings["properties"]["source_refs"]["type"]

    validate_existing_mapping(
        {"chunks": {"mappings": mappings}},
        index_name="chunks",
        config=config,
    )
