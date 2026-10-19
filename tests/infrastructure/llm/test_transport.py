"""Standard-library transport safety checks; no network connections."""

from urllib.error import HTTPError, URLError

import pytest

from engineering_rag.infrastructure.llm.api import LLMConnectionError, LLMError, LLMTimeoutError
from engineering_rag.infrastructure.llm.internal import transport


class Reply:
    status = 200

    def __init__(self, data: bytes = b"{}") -> None:
        self.data = data
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.data[:size]


class Opener:
    def __init__(self, response: Reply | Exception) -> None:
        self.response = response
        self.requests: list[object] = []

    def open(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def install(monkeypatch: pytest.MonkeyPatch, response: Reply | Exception) -> Opener:
    opener = Opener(response)

    def build(*handlers):
        assert isinstance(handlers[0], transport.ProxyHandler)
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], transport._RejectRedirect)
        assert (
            handlers[1].redirect_request(None, None, 302, "Found", {}, "https://other.invalid")
            is None
        )
        return opener

    monkeypatch.setattr(transport, "build_opener", build)
    return opener


def post() -> transport.HTTPResponse:
    return transport.UrllibHTTPTransport().post(
        "https://provider.invalid/v1/chat/completions",
        headers={"Authorization": "Bearer offline-test-value"},
        body=b"{}",
        timeout_seconds=3,
    )


def test_transport_uses_post_once_disables_proxy_and_redirect_and_caps_body(monkeypatch) -> None:
    reply = Reply()
    opener = install(monkeypatch, reply)
    assert post().body == b"{}"
    assert reply.read_sizes == [transport.MAX_RESPONSE_BYTES + 1]
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.get_method() == "POST"
    assert timeout == 3


def test_transport_rejects_oversized_body(monkeypatch) -> None:
    install(monkeypatch, Reply(b"a" * (transport.MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(LLMError, match="response_too_large"):
        post()


def test_http_error_body_is_not_read_or_exposed(monkeypatch) -> None:
    error = HTTPError("https://provider.invalid", 401, "offline-private-error", None, None)
    install(monkeypatch, error)
    response = post()
    assert response.status == 401
    assert response.body == b""


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("private-detail"), LLMTimeoutError),
        (URLError(TimeoutError("private-detail")), LLMTimeoutError),
        (URLError("private-detail"), LLMConnectionError),
        (OSError("private-detail"), LLMConnectionError),
    ],
)
def test_transport_errors_are_sanitized_and_single_attempt(monkeypatch, error, expected) -> None:
    opener = install(monkeypatch, error)
    with pytest.raises(expected) as observed:
        post()
    assert "private-detail" not in str(observed.value)
    assert len(opener.requests) == 1
