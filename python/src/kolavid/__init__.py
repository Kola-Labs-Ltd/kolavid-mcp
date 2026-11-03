"""Official Python client for the KolaVid API (https://kolavid.com/developers).

    from kolavid import KolaVid

    client = KolaVid()  # reads KOLAVID_API_KEY
    video = client.videos.create(prompt="How vaccines work, for 12-year-olds", length_minutes=2)
    video = client.videos.wait(video.id)
    if video.status == "completed":
        client.videos.download(video.id, "vaccines.mp4")
"""

from ._client import DEFAULT_BASE_URL, KolaVid, Videos
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    InsufficientCreditsError,
    KolaVidError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
    VideoFailedError,
    VideoInProgressError,
    VideoNotReadyError,
    WaitTimeoutError,
)
from ._http import HttpxTransport, Response, Transport, UrllibTransport
from ._types import Account, Video
from ._version import __version__

__all__ = [
    "KolaVid",
    "Videos",
    "Video",
    "Account",
    "DEFAULT_BASE_URL",
    "Transport",
    "UrllibTransport",
    "HttpxTransport",
    "Response",
    "KolaVidError",
    "APIError",
    "APIConnectionError",
    "APITimeoutError",
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
    "__version__",
]
