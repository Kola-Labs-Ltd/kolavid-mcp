"""Errors raised by the KolaVid client.

The API answers errors as JSON with ``detail`` (a sentence to show) and usually ``error`` (a code). A request that
fails field validation has ``detail`` as a list of problems instead; those become ``ValidationError.details``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "KolaVidError",
    "APIConnectionError",
    "APITimeoutError",
    "APIError",
    "AuthenticationError",
    "InsufficientCreditsError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "VideoInProgressError",
    "ServerError",
    "VideoNotReadyError",
    "VideoFailedError",
    "WaitTimeoutError",
]

DEFAULT_PRICING_URL = "https://kolavid.com/pricing"


class KolaVidError(Exception):
    """Base class for every error this package raises."""


class APIConnectionError(KolaVidError):
    """The API could not be reached (DNS, refused connection, TLS, dropped connection)."""


class APITimeoutError(APIConnectionError):
    """The API did not answer within the client's timeout."""


class APIError(KolaVidError):
    """The API answered with an error status.

    Attributes:
        status_code: the HTTP status.
        message: the API's sentence (``detail``), safe to show to a person.
        code: the API's error code (``error``), for example ``"insufficient_credits"``; may be ``None``.
        body: the parsed JSON body (or ``None``).
        headers: the response headers, lower-cased names.
    """

    def __init__(self, message: str, *, status_code: int, code: Optional[str] = None,
                 body: Any = None, headers: Optional[Mapping[str, str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.body = body
        self.headers: Dict[str, str] = dict(headers or {})

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status_code})"


class AuthenticationError(APIError):
    """401: the API key is missing, wrong or revoked."""


class InsufficientCreditsError(APIError):
    """402: not enough credits for that length. ``pricing_url`` is where to buy more."""

    @property
    def pricing_url(self) -> str:
        if isinstance(self.body, dict) and isinstance(self.body.get("pricing_url"), str):
            return self.body["pricing_url"]
        return DEFAULT_PRICING_URL


class PermissionDeniedError(APIError):
    """403: the account is closed."""


class NotFoundError(APIError):
    """404: no such video in this account, or an expired file link."""


class ValidationError(APIError):
    """422: a field is wrong, the link can't be read, or the request was refused under the content rules.

    ``details`` lists field problems as the API gave them (``{"loc": [...], "msg": "...", "type": "..."}``); it is
    empty when the API answered with a single sentence.
    """

    @property
    def details(self) -> List[Dict[str, Any]]:
        detail = self.body.get("detail") if isinstance(self.body, dict) else None
        return [item for item in detail if isinstance(item, dict)] if isinstance(detail, list) else []


class RateLimitError(APIError):
    """429: more than 60 requests a minute with one key (``retry_after`` seconds), or another video is being made."""

    @property
    def retry_after(self) -> Optional[float]:
        return parse_retry_after(self.headers.get("retry-after"))


class VideoInProgressError(RateLimitError):
    """429 on create: another video of this account is still being made. An account makes one video at a time;
    wait for it (``client.videos.wait``) and try again."""


class ServerError(APIError):
    """5xx: something went wrong at KolaVid."""


class VideoNotReadyError(KolaVidError):
    """The video has no file yet (it is still being made, or it failed)."""

    def __init__(self, message: str, video: Any = None) -> None:
        super().__init__(message)
        self.video = video


class VideoFailedError(VideoNotReadyError):
    """The video failed; ``video.error`` says why. Failed videos use no credits."""


class WaitTimeoutError(KolaVidError):
    """``videos.wait`` gave up before the video finished; ``video`` is its last known state."""

    def __init__(self, message: str, video: Any = None) -> None:
        super().__init__(message)
        self.video = video


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds from a Retry-After header (the API sends whole seconds); ``None`` if absent or unreadable."""
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except ValueError:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        try:
            when = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, seconds)


def _message_from(body: Any, status_code: int) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list):
            parts = []
            for problem in detail:
                if not isinstance(problem, dict):
                    continue
                loc = [str(part) for part in problem.get("loc") or [] if part != "body"]
                msg = str(problem.get("msg") or "").strip()
                parts.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
            if any(parts):
                return "; ".join(part for part in parts if part)
        for key in ("message", "error"):
            if isinstance(body.get(key), str) and body[key].strip():
                return body[key].strip()
    if isinstance(body, str) and body.strip() and len(body) < 500:
        return body.strip()
    return f"KolaVid API error {status_code}"


def error_for(status_code: int, body: Any, headers: Mapping[str, str], *, creating: bool = False) -> APIError:
    """The error to raise for an API error response."""
    message = _message_from(body, status_code)
    code = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), str) else None
    kind: type = APIError
    if status_code == 401:
        kind = AuthenticationError
    elif status_code == 402:
        kind = InsufficientCreditsError
    elif status_code == 403:
        kind = PermissionDeniedError
    elif status_code == 404:
        kind = NotFoundError
    elif status_code in (400, 422):
        kind = ValidationError
    elif status_code == 429:
        # The per-key rate limit names Retry-After; "one video at a time" does not.
        kind = VideoInProgressError if creating and "retry-after" not in headers else RateLimitError
    elif status_code >= 500:
        kind = ServerError
    return kind(message, status_code=status_code, code=code, body=body, headers=headers)
