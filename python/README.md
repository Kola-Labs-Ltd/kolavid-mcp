# KolaVid Python SDK

The official Python client for the [KolaVid API](https://kolavid.com/developers). Turn a prompt, an article or a web
page into a narrated whiteboard explainer video from your own code.

- Python 3.9+
- No dependencies (the standard library's `urllib`); optional `httpx` transport
- Typed (`py.typed`), with dataclasses for videos and the account

## Install

```bash
pip install kolavid
```

## API key

Make a key in KolaVid under **Account > API keys** (<https://kolavid.com/app/account?tab=api>). It starts with
`kv_live_` and is shown once. Keep it out of your code:

```bash
export KOLAVID_API_KEY=kv_live_...
```

A key acts as your account: videos use your credits (60 credits per minute of video, taken when the video is
finished; a failed video costs nothing) and appear in your KolaVid library.

## Quickstart

```python
from kolavid import KolaVid

client = KolaVid()  # reads KOLAVID_API_KEY

video = client.videos.create(prompt="How vaccines work, for 12-year-olds", length_minutes=2)
print("Started", video.id, video.app_url)

video = client.videos.wait(video.id, on_progress=lambda v: print(v.status, v.progress))
if video.status == "completed":
    path = client.videos.download(video.id, "vaccines.mp4")
    print("Saved", path)
else:
    print("Failed:", video.error)
```

A video takes about 2 to 4 minutes.

## Making videos

```python
# From a topic, with instructions
client.videos.create(prompt="Photosynthesis for a Year 7 class, friendly tone")

# Explain your own text (up to 100,000 characters)
client.videos.create(text=open("article.txt").read(), prompt="Keep it to the three main points")

# Explain a public web page (up to three links, separated by spaces)
client.videos.create(source_url="https://example.com/blog/post")

# Options
client.videos.create(
    prompt="Compound interest",
    length_minutes=3,       # 1 to 5, default 1
    aspect_ratio="9:16",    # "16:9" (default), "9:16" or "1:1"
    voice="Kore",           # "female" (default), "male", or a voice by name
    language="Spanish",     # narration language, default English
)
```

Give at least one of `prompt`, `text` or `source_url` (not both `text` and `source_url`). An account makes one video
at a time.

## Checking, listing and downloading

```python
video = client.videos.get(video_id)
video.status        # "queued", "making", "completed" or "failed"
video.progress      # 0 to 100
video.video_url     # the MP4 once completed; works for 24 hours without a key
video.error         # why it failed

for v in client.videos.list(limit=10, status="completed"):
    print(v.completed_at, v.title, v.video_url)

client.videos.download(video_id, "out/")           # saves out/kolavid-<id>.mp4
client.videos.download(video_id, "lesson.mp4")     # or a file name

account = client.me()
print(account.email, account.credits, account.plan)  # plan: free, starter, creator or studio
```

`videos.wait(id, poll_interval=5, timeout=900)` polls until the video is completed or failed and returns it; it
raises `WaitTimeoutError` (with `.video`) if the timeout passes first. `timeout=None` waits for ever.

## Errors

Every error is a `kolavid.KolaVidError`. Errors from the API are `kolavid.APIError` with `status_code`, `message`
(a sentence you can show), `code` and `body`.

| Error | When |
|---|---|
| `AuthenticationError` | 401: missing, wrong or revoked key |
| `InsufficientCreditsError` | 402: not enough credits; `.pricing_url` is where to buy more |
| `PermissionDeniedError` | 403: the account is closed |
| `NotFoundError` | 404: no such video in this account |
| `ValidationError` | 422: a field is wrong, the link can't be read, or the request was refused; `.details` lists field problems |
| `RateLimitError` | 429: more than 60 requests a minute; `.retry_after` in seconds |
| `VideoInProgressError` | 429 on create: another video is still being made (a `RateLimitError`) |
| `ServerError` | 5xx |
| `APIConnectionError`, `APITimeoutError` | no answer from KolaVid |
| `VideoNotReadyError`, `VideoFailedError` | `download` before the video is finished, or after it failed |

```python
import kolavid

try:
    client.videos.create(prompt="The water cycle", length_minutes=5)
except kolavid.InsufficientCreditsError as error:
    print(error.message, "Buy more at", error.pricing_url)
except kolavid.VideoInProgressError:
    print("Another video is being made; try again when it is done.")
```

## Retries and timeouts

The client asks again (up to `max_retries`, default 2) after a rate limit, a 5xx answer or a broken connection,
waiting as long as the API's `Retry-After` says, otherwise a short growing pause. A `create` is retried only when it
surely made nothing (the per-key rate limit, or 503 unavailable), never after a timeout or a dropped connection, so a
retry never makes two videos.

```python
client = KolaVid(api_key="kv_live_...", timeout=30, max_retries=4)
```

## httpx

```bash
pip install "kolavid[httpx]"
```

```python
import httpx
from kolavid import KolaVid, HttpxTransport

client = KolaVid(transport=HttpxTransport(httpx.Client(proxy="http://proxy:3128")))
```

Any object with the `request` and `stream` methods of `kolavid.Transport` works as a transport, which makes the
client easy to fake in your own tests.

## Development

```bash
python3 -m unittest            # from python/; no network needed
python3 -m build               # sdist and wheel in dist/
```

MIT licence. Copyright Kola Labs Ltd.
