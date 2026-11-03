"""The API's objects as dataclasses. The API only ever adds fields, so unknown fields are kept in ``raw``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

__all__ = ["Video", "Account", "VideoStatus", "FINISHED_STATUSES"]

# "queued", "making", "completed" or "failed" (stopped videos are "failed" too).
VideoStatus = str
FINISHED_STATUSES = frozenset({"completed", "failed"})


def parse_time(value: Any) -> Optional[datetime]:
    """An ISO 8601 time from the API ("2026-11-02T12:00:00Z") as an aware datetime; ``None`` if absent."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python 3.9/3.10 fromisoformat takes only 3 or 6 fraction digits.
    if "." in text:
        head, _, rest = text.partition(".")
        digits = ""
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        text = f"{head}.{(digits + '000000')[:6]}{rest}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class Video:
    """A video, as ``GET /api/v1/videos/{id}`` describes it.

    ``create`` answers with fewer fields (id, status, created_at, app_url, status_url); the others are ``None``
    until you ``get`` or ``wait`` for the video.
    """

    id: str
    status: VideoStatus
    progress: int = 0
    title: Optional[str] = None
    length_minutes: Optional[int] = None
    aspect_ratio: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    share_url: Optional[str] = None
    app_url: Optional[str] = None
    status_url: Optional[str] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_finished(self) -> bool:
        """True once the video is completed or failed."""
        return self.status in FINISHED_STATUSES

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Video":
        return cls(
            id=str(data.get("id") or ""),
            status=str(data.get("status") or ""),
            progress=_int(data.get("progress")) or 0,
            title=data.get("title"),
            length_minutes=_int(data.get("length_minutes")),
            aspect_ratio=data.get("aspect_ratio"),
            created_at=parse_time(data.get("created_at")),
            completed_at=parse_time(data.get("completed_at")),
            video_url=data.get("video_url"),
            thumbnail_url=data.get("thumbnail_url"),
            share_url=data.get("share_url"),
            app_url=data.get("app_url"),
            status_url=data.get("status_url"),
            error=data.get("error"),
            raw=dict(data),
        )


@dataclass
class Account:
    """The account an API key acts for (``GET /api/v1/me``). ``plan`` is free, starter, creator or studio."""

    email: str
    credits: float
    plan: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        try:
            credits = float(data.get("credits") or 0)
        except (TypeError, ValueError):
            credits = 0.0
        return cls(email=str(data.get("email") or ""), credits=credits, plan=str(data.get("plan") or "free"),
                   raw=dict(data))
