"""The HTTP layer. The default transport uses only the standard library (urllib); ``HttpxTransport`` uses httpx when it
is installed. Tests pass their own transport, so no test touches the network.

A transport has two methods:

- ``request(method, url, headers=..., body=..., timeout=...) -> Response``: the whole answer in memory.
- ``stream(method, url, headers=..., timeout=..., sink=...) -> Response``: a 2xx body is written to ``sink`` (a binary
  file) and ``Response.content`` is empty; any other status has its body in ``content`` and writes nothing.

Transports raise ``APIConnectionError`` / ``APITimeoutError`` when there is no HTTP answer at all.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import IO, Any, Dict, Mapping, Optional

from ._errors import APIConnectionError, APITimeoutError

__all__ = ["Response", "Transport", "UrllibTransport", "HttpxTransport", "default_transport"]

CHUNK = 1024 * 256


@dataclass
class Response:
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    content: bytes = b""


def _lower(headers: Any) -> Dict[str, str]:
    if headers is None:
        return {}
    items = headers.items() if hasattr(headers, "items") else headers
    return {str(name).lower(): str(value) for name, value in items}


class Transport:
    """The interface (duck-typed: any object with these two methods works)."""

    def request(self, method: str, url: str, *, headers: Mapping[str, str], body: Optional[bytes],
                timeout: float) -> Response:  # pragma: no cover - interface
        raise NotImplementedError

    def stream(self, method: str, url: str, *, headers: Mapping[str, str], timeout: float,
               sink: IO[bytes]) -> Response:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


class UrllibTransport(Transport):
    """Standard library HTTP. Honours the usual proxy environment variables."""

    def __init__(self, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        handlers = [urllib.request.HTTPSHandler(context=ssl_context)] if ssl_context is not None else []
        self._opener = urllib.request.build_opener(*handlers)

    def _open(self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float):
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            return self._opener.open(request, timeout=timeout), None
        except urllib.error.HTTPError as error:
            try:
                content = error.read() or b""
            except (OSError, http.client.HTTPException):
                content = b""
            finally:
                error.close()
            return None, Response(error.code, _lower(error.headers), content)
        except Exception as error:  # URLError, socket errors, TLS errors, RemoteDisconnected...
            if _is_timeout(error):
                raise APITimeoutError(f"KolaVid did not answer within {timeout:g} seconds.") from error
            reason = getattr(error, "reason", error)
            raise APIConnectionError(f"Could not reach KolaVid: {reason}") from error

    def request(self, method: str, url: str, *, headers: Mapping[str, str], body: Optional[bytes],
                timeout: float) -> Response:
        answer, failed = self._open(method, url, headers, body, timeout)
        if failed is not None:
            return failed
        try:
            with answer:
                return Response(answer.status, _lower(answer.headers), answer.read())
        except Exception as error:
            if _is_timeout(error):
                raise APITimeoutError(f"KolaVid did not answer within {timeout:g} seconds.") from error
            raise APIConnectionError(f"The connection to KolaVid broke: {error}") from error

    def stream(self, method: str, url: str, *, headers: Mapping[str, str], timeout: float,
               sink: IO[bytes]) -> Response:
        answer, failed = self._open(method, url, headers, None, timeout)
        if failed is not None:
            return failed
        try:
            with answer:
                while True:
                    chunk = answer.read(CHUNK)
                    if not chunk:
                        break
                    sink.write(chunk)
                return Response(answer.status, _lower(answer.headers), b"")
        except Exception as error:
            if _is_timeout(error):
                raise APITimeoutError(f"The download stopped: no data for {timeout:g} seconds.") from error
            raise APIConnectionError(f"The download broke: {error}") from error


class HttpxTransport(Transport):
    """HTTP through httpx (``pip install "kolavid[httpx]"``). Pass your own ``httpx.Client`` to share a pool or set
    proxies; otherwise one is made and closed with the client."""

    def __init__(self, client: Any = None) -> None:
        import httpx  # noqa: F401 - fail early if it isn't installed

        self._httpx = httpx
        self._owned = client is None
        self._client = client if client is not None else httpx.Client(follow_redirects=True)

    def _convert(self, error: Exception, timeout: float) -> Exception:
        if isinstance(error, self._httpx.TimeoutException):
            return APITimeoutError(f"KolaVid did not answer within {timeout:g} seconds.")
        return APIConnectionError(f"Could not reach KolaVid: {error}")

    def request(self, method: str, url: str, *, headers: Mapping[str, str], body: Optional[bytes],
                timeout: float) -> Response:
        try:
            answer = self._client.request(method, url, headers=dict(headers), content=body, timeout=timeout)
        except self._httpx.HTTPError as error:
            raise self._convert(error, timeout) from error
        return Response(answer.status_code, _lower(answer.headers), answer.content)

    def stream(self, method: str, url: str, *, headers: Mapping[str, str], timeout: float,
               sink: IO[bytes]) -> Response:
        try:
            with self._client.stream(method, url, headers=dict(headers), timeout=timeout) as answer:
                if answer.status_code >= 300:
                    return Response(answer.status_code, _lower(answer.headers), answer.read())
                for chunk in answer.iter_bytes(CHUNK):
                    sink.write(chunk)
                return Response(answer.status_code, _lower(answer.headers), b"")
        except self._httpx.HTTPError as error:
            raise self._convert(error, timeout) from error

    def close(self) -> None:
        if self._owned:
            self._client.close()


def default_transport() -> Transport:
    return UrllibTransport()
