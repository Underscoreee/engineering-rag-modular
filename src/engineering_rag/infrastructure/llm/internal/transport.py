"""One HTTP POST, no redirects/proxy discovery/retries; bounded response size."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .errors import LLMConnectionError, LLMError, LLMTimeoutError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes = field(repr=False)


class HTTPTransport(Protocol):
    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HTTPResponse: ...


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


class UrllibHTTPTransport:
    """Timeout is a socket-operation timeout, not a promised full-stage SLA.

    Python/OS DNS resolution may exceed socket timeout. No retry or automatic
    proxy forwarding is performed. A redirect response is returned as failure;
    the Authorization header is never forwarded to another target.
    """

    def post(
        self, url: str, *, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HTTPResponse:
        try:
            opener = build_opener(ProxyHandler({}), _RejectRedirect())
            request = Request(url, data=body, headers=dict(headers), method="POST")
            with opener.open(request, timeout=timeout_seconds) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise LLMError("response_too_large")
                return HTTPResponse(status=response.status, body=data)
        except HTTPError as exc:
            status = exc.code
            exc.close()  # Do not read, log, serialize or propagate provider error bodies.
            return HTTPResponse(status=status, body=b"")
        except TimeoutError:
            raise LLMTimeoutError("timeout") from None
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeoutError("timeout") from None
            raise LLMConnectionError("connection") from None
        except OSError:
            raise LLMConnectionError("connection") from None
