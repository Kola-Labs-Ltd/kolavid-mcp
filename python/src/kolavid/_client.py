"""The KolaVid client: ``KolaVid(api_key=...)`` with ``videos`` and ``me()``."""

from __future__ import annotations

import json
import os
import random
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from ._errors import (
    APIConnectionError,
    KolaVidError,
    NotFoundError,
    VideoFailedError,
    VideoNotReadyError,
    WaitTimeoutError,
    error_for,
    parse_retry_after,
)
from ._http import Response, Transport, default_transport
from ._types import Account, Video
from ._version import __version__

__all__ = ["KolaVid", "Videos", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "https://kolavid.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_DOWNLOAD_TIMEOUT = 300.0
DEFAULT_MAX_RETRIES = 2
CLIENT_NAME = "sdk-python"
# A Retry-After longer than this is not waited out; the RateLimitError is raised instead.
MAX_RETRY_WAIT = 120.0

# Statuses worth asking again for. A create (POST) is retried only when the request surely made nothing: the per-key
# rate limit (429 with Retry-After) and 503 (the API or a link reader is unavailable; nothing was started).
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
CREATE_RETRY_STATUSES = frozenset({503})

VideoRef = Union[str, Video]


def _video_id(video: VideoRef) -> str:
    value = video.id if isinstance(video, Video) else video
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A video id is needed.")
    return value.strip()


def _decode(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return content.decode("utf-8", "replace")


class Videos:
    """``client.videos``: start, check, list, wait for and download videos."""

    def __init__(self, client: "KolaVid") -> None:
        self._client = client

    def create(self, prompt: Optional[str] = None, *, text: Optional[str] = None, source_url: Optional[str] = None,
               length_minutes: int = 1, aspect_ratio: str = "16:9", voice: Optional[str] = None,
               language: Optional[str] = None, extra_body: Optional[Mapping[str, Any]] = None) -> Video:
        """Start a video. Give at least one of ``prompt``, ``text`` or ``source_url`` (not both ``text`` and
        ``source_url``). Credits (60 a minute) are taken only when the video is finished.

        Returns the new video (status ``queued``); follow it with ``wait`` or ``get``.

        Raises ``InsufficientCreditsError`` (402), ``ValidationError`` (422), ``VideoInProgressError`` (429, another
        video of this account is still being made) and the other ``APIError`` kinds.
        """
        if not any((value or "").strip() for value in (prompt, text, source_url)):
            raise ValueError("Give at least one of prompt, text or source_url.")
        body: Dict[str, Any] = {"length_minutes": length_minutes, "aspect_ratio": aspect_ratio}
        for name, value in (("prompt", prompt), ("text", text), ("source_url", source_url), ("voice", voice),
                            ("language", language)):
            if value is not None:
                body[name] = value
        body.update(extra_body or {})
        return Video.from_dict(self._client._request("POST", "/videos", json_body=body, creating=True))

    def get(self, video: VideoRef) -> Video:
        """A video's status, progress and, once completed, its ``video_url`` (works for 24 hours, no key needed)."""
        video_id = urllib.parse.quote(_video_id(video), safe="")
        return Video.from_dict(self._client._request("GET", f"/videos/{video_id}"))

    def list(self, limit: int = 25, status: Optional[str] = None) -> List[Video]:
        """The newest videos (``limit`` 1 to 100). ``status`` is queued, making, completed or failed; with
        ``completed`` they are ordered by when they finished."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        data = self._client._request("GET", "/videos", params=params)
        items = data.get("videos") if isinstance(data, dict) else None
        return [Video.from_dict(item) for item in items or [] if isinstance(item, dict)]

    def wait(self, video: VideoRef, *, poll_interval: float = 5.0, timeout: Optional[float] = 900.0,
             on_progress: Optional[Callable[[Video], None]] = None) -> Video:
        """Poll until the video is completed or failed, and return it (check ``video.status``; a failed video's
        ``error`` says why). A video takes about 2 to 4 minutes. ``timeout=None`` waits for ever.

        Raises ``WaitTimeoutError`` (with the last ``video``) when ``timeout`` seconds pass first.
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be more than 0 seconds.")
        clock, sleep = self._client._clock, self._client._sleep
        deadline = None if timeout is None else clock() + timeout
        while True:
            current = self.get(video)
            if on_progress is not None:
                on_progress(current)
            if current.is_finished:
                return current
            now = clock()
            if deadline is not None and now >= deadline:
                raise WaitTimeoutError(
                    f"Video {current.id} was still {current.status} ({current.progress}%) after {timeout:g} seconds.",
                    video=current)
            sleep(poll_interval if deadline is None else max(0.0, min(poll_interval, deadline - now)))

    def download(self, video: VideoRef, path: Union[str, "os.PathLike[str]"] = ".", *,
                 timeout: Optional[float] = None) -> Path:
        """Save the finished MP4 at ``path`` (a file, or a folder for ``kolavid-<id>.mp4``) and return where it went.

        Asks for the video first, so the file link is fresh. Raises ``VideoNotReadyError`` while it is being made and
        ``VideoFailedError`` if it failed. The file is written whole or not at all.
        """
        current = self.get(video)
        if current.is_failed:
            raise VideoFailedError(f"Video {current.id} failed: {current.error or 'no reason given'}", video=current)
        if not current.is_completed or not current.video_url:
            raise VideoNotReadyError(f"Video {current.id} is {current.status or 'not ready'} "
                                     f"({current.progress}%); wait for it first.", video=current)
        target = Path(os.fspath(path)).expanduser()
        if target.is_dir() or str(path).endswith(("/", os.sep)):
            target = target / f"kolavid-{current.id}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client._download(current.video_url, target, timeout)
        except NotFoundError:
            # The link expired between asking and downloading: ask once more for a fresh one.
            fresh = self.get(current.id)
            if not fresh.video_url:
                raise
            self._client._download(fresh.video_url, target, timeout)
        return target


class KolaVid:
    """A client for the KolaVid API (https://kolavid.com/developers).

    Args:
        api_key: a key from Account > API keys (``kv_live_...``). Defaults to the ``KOLAVID_API_KEY`` environment
            variable.
        base_url: the site, default ``https://kolavid.com`` (or ``KOLAVID_BASE_URL``).
        timeout: seconds to wait for each API answer (default 60).
        max_retries: how many times to ask again after a rate limit, a server error or a broken connection
            (default 2). Waits as long as the API's Retry-After says.
        transport: the HTTP layer; defaults to the standard library. See ``kolavid.HttpxTransport``.
        default_headers: extra headers for every request.
    """

    def __init__(self, api_key: Optional[str] = None, *, base_url: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES,
                 transport: Optional[Transport] = None, default_headers: Optional[Mapping[str, str]] = None) -> None:
        key = (api_key if api_key is not None else os.environ.get("KOLAVID_API_KEY", "")).strip()
        if not key:
            raise KolaVidError("No KolaVid API key. Pass api_key=... or set KOLAVID_API_KEY. Make a key at "
                               "https://kolavid.com/app/account?tab=api")
        base = (base_url or os.environ.get("KOLAVID_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        if base.endswith("/api/v1"):
            base = base[: -len("/api/v1")]
        if max_retries < 0:
            raise ValueError("max_retries can't be negative.")
        self._api_key = key
        self.base_url = base
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self._transport = transport if transport is not None else default_transport()
        self._default_headers = dict(default_headers or {})
        self._sleep: Callable[[float], None] = time.sleep
        self._clock: Callable[[], float] = time.monotonic
        self.videos = Videos(self)

    def __repr__(self) -> str:
        return f"KolaVid(base_url={self.base_url!r}, api_key='{self._api_key[:8]}...')"

    def __enter__(self) -> "KolaVid":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def me(self) -> Account:
        """The account the key acts for: email, credits and plan."""
        return Account.from_dict(self._request("GET", "/me"))

    # --- plumbing ----------------------------------------------------------------------------------------------

    def _headers(self, *, auth: bool = True, json_body: bool = False) -> Dict[str, str]:
        headers = {"User-Agent": f"kolavid-python/{__version__}", "X-KolaVid-Client": CLIENT_NAME}
        headers.update(self._default_headers)
        if auth:
            headers["Authorization"] = f"Bearer {self._api_key}"
            headers["Accept"] = "application/json"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _url(self, path: str, params: Optional[Mapping[str, Any]] = None) -> str:
        url = f"{self.base_url}/api/v1{path}"
        return f"{url}?{urllib.parse.urlencode(params)}" if params else url

    def _backoff(self, attempt: int, response: Optional[Response]) -> Optional[float]:
        """Seconds to wait before the next try, or None to give up now."""
        if response is not None:
            wait = parse_retry_after(response.headers.get("retry-after"))
            if wait is not None:
                return wait if wait <= MAX_RETRY_WAIT else None
        return min(8.0, 0.5 * (2 ** attempt)) * random.uniform(0.75, 1.0)

    def _retryable(self, response: Response, creating: bool) -> bool:
        if creating:
            return response.status_code in CREATE_RETRY_STATUSES or (
                response.status_code == 429 and "retry-after" in response.headers)
        return response.status_code in RETRY_STATUSES

    def _request(self, method: str, path: str, *, params: Optional[Mapping[str, Any]] = None,
                 json_body: Optional[Mapping[str, Any]] = None, creating: bool = False) -> Any:
        url = self._url(path, params)
        body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        headers = self._headers(json_body=body is not None)
        attempt = 0
        while True:
            try:
                response = self._transport.request(method, url, headers=headers, body=body, timeout=self.timeout)
            except APIConnectionError:
                # A create that may have reached the server is never sent twice (it could make two videos).
                if creating or attempt >= self.max_retries:
                    raise
                wait = self._backoff(attempt, None)
            else:
                if 200 <= response.status_code < 300:
                    return _decode(response.content)
                if attempt >= self.max_retries or not self._retryable(response, creating):
                    raise error_for(response.status_code, _decode(response.content), response.headers,
                                    creating=creating)
                wait = self._backoff(attempt, response)
                if wait is None:
                    raise error_for(response.status_code, _decode(response.content), response.headers,
                                    creating=creating)
            attempt += 1
            self._sleep(wait or 0.0)

    def _download(self, url: str, target: Path, timeout: Optional[float]) -> None:
        """Stream a signed file link to ``target`` through a temporary file. The link needs no key, so none is sent
        (it may redirect to file storage)."""
        headers = self._headers(auth=False)
        partial = target.with_name(f".{target.name}.part")
        attempt = 0
        while True:
            try:
                with open(partial, "wb") as sink:
                    response = self._transport.stream("GET", url, headers=headers,
                                                      timeout=timeout or max(self.timeout, DEFAULT_DOWNLOAD_TIMEOUT),
                                                      sink=sink)
            except APIConnectionError:
                partial.unlink(missing_ok=True)
                if attempt >= self.max_retries:
                    raise
                wait = self._backoff(attempt, None)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            else:
                if 200 <= response.status_code < 300:
                    os.replace(partial, target)
                    return
                partial.unlink(missing_ok=True)
                if attempt >= self.max_retries or response.status_code not in RETRY_STATUSES:
                    raise error_for(response.status_code, _decode(response.content), response.headers)
                wait = self._backoff(attempt, response)
                if wait is None:
                    raise error_for(response.status_code, _decode(response.content), response.headers)
            attempt += 1
            self._sleep(wait or 0.0)

