from engineering_rag.modules.query.api import QueryService


def test_protocol_is_declaration_only() -> None:
    assert QueryService.__name__ == "QueryService"
    assert getattr(QueryService, "_is_protocol", False)
