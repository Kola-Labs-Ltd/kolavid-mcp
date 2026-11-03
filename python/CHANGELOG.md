# Changelog

All notable changes to the `kolavid` Python package. The package follows [Semantic Versioning](https://semver.org/).

## 0.1.0 (2026-11-02)

First release, for the KolaVid REST API v1 (`https://kolavid.com/api/v1`).

- `KolaVid` client: API key from `api_key=` or `KOLAVID_API_KEY`, `base_url`, `timeout`, `max_retries`.
- `videos.create`, `videos.get`, `videos.list`, `videos.wait`, `videos.download`, and `me()`.
- `Video` and `Account` dataclasses; unknown API fields are kept in `.raw`.
- Errors by status: `AuthenticationError` (401), `InsufficientCreditsError` (402, `pricing_url`),
  `PermissionDeniedError` (403), `NotFoundError` (404), `ValidationError` (422, `details`), `RateLimitError` (429,
  `retry_after`), `VideoInProgressError` (429 on create), `ServerError` (5xx), plus `APIConnectionError`,
  `APITimeoutError`, `VideoNotReadyError`, `VideoFailedError` and `WaitTimeoutError`.
- Retries on rate limits, server errors and broken connections, honouring `Retry-After`. A create is only retried
  when it surely made nothing (429 with Retry-After, or 503).
- No dependencies: the standard library's urllib by default, httpx through `HttpxTransport` when installed.
