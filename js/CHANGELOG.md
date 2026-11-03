# Changelog

All notable changes to the `kolavid` npm package. The package follows [Semantic Versioning](https://semver.org/).

## 0.1.0 (2026-11-02)

First release, for the KolaVid REST API v1 (`https://kolavid.com/api/v1`).

- `new KolaVid({ apiKey, baseUrl, timeoutMs, maxRetries, fetch })`; the key defaults to `KOLAVID_API_KEY` in Node.
- `videos.create`, `videos.get`, `videos.list`, `videos.wait`, `videos.download` (ArrayBuffer), `videos.downloadBlob`,
  `videos.fileResponse` (stream), and `me()`. `downloadToFile` in `kolavid/node` streams a video to disk.
- Typed errors: `AuthenticationError` (401), `InsufficientCreditsError` (402, `pricingUrl`), `PermissionDeniedError`
  (403), `NotFoundError` (404), `ValidationError` (422, `details`), `RateLimitError` (429, `retryAfter`),
  `VideoInProgressError` (429 on create), `ServerError` (5xx), `APIConnectionError`, `APITimeoutError`,
  `VideoNotReadyError`, `VideoFailedError`, `WaitTimeoutError`.
- Retries on rate limits, server errors and broken connections, honouring `Retry-After`. A create is only retried
  when it surely made nothing (429 with Retry-After, or 503). Every call takes an `AbortSignal`.
- No dependencies: the global `fetch` (Node 18+, browsers, Deno, Bun, edge workers). ESM with TypeScript types.
