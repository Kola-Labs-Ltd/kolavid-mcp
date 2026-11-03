# KolaVid JavaScript SDK

The official JavaScript and TypeScript client for the [KolaVid API](https://kolavid.com/developers). Turn a prompt,
an article or a web page into a narrated whiteboard explainer video from your own code.

- No dependencies: uses the global `fetch` (Node 18+, Deno, Bun, edge workers, browsers)
- ESM with TypeScript types
- Typed errors, retries that honour `Retry-After`, `AbortSignal` on every call

## Install

```bash
npm install kolavid
```

## API key

Make a key in KolaVid under **Account > API keys** (<https://kolavid.com/app/account?tab=api>). It starts with
`kv_live_` and is shown once. Keep it on your server:

```bash
export KOLAVID_API_KEY=kv_live_...
```

A key acts as your account: videos use your credits (60 credits per minute of video, taken when the video is
finished; a failed video costs nothing) and appear in your KolaVid library.

## Quickstart

```ts
import { KolaVid } from "kolavid";
import { downloadToFile } from "kolavid/node";

const kolavid = new KolaVid(); // reads KOLAVID_API_KEY

const started = await kolavid.videos.create({ prompt: "How vaccines work, for 12-year-olds", lengthMinutes: 2 });
console.log("Started", started.id, started.appUrl);

const video = await kolavid.videos.wait(started.id, { onProgress: (v) => console.log(v.status, v.progress) });
if (video.status === "completed") {
  const saved = await downloadToFile(kolavid, video.id, "vaccines.mp4");
  console.log("Saved", saved.path, saved.bytes, "bytes");
} else {
  console.log("Failed:", video.error);
}
```

A video takes about 2 to 4 minutes.

## Making videos

```ts
// From a topic, with instructions
await kolavid.videos.create({ prompt: "Photosynthesis for a Year 7 class, friendly tone" });

// Explain your own text (up to 100,000 characters)
await kolavid.videos.create({ text: articleText, prompt: "Keep it to the three main points" });

// Explain a public web page (up to three links, separated by spaces)
await kolavid.videos.create({ sourceUrl: "https://example.com/blog/post" });

// Options
await kolavid.videos.create({
  prompt: "Compound interest",
  lengthMinutes: 3,     // 1 to 5, default 1
  aspectRatio: "9:16",  // "16:9" (default), "9:16" or "1:1"
  voice: "Kore",        // "female" (default), "male", or a voice by name
  language: "Spanish",  // narration language, default English
});
```

Give at least one of `prompt`, `text` or `sourceUrl` (not both `text` and `sourceUrl`). An account makes one video
at a time.

## Checking, listing and downloading

```ts
const video = await kolavid.videos.get(videoId);
video.status;    // "queued" | "making" | "completed" | "failed"
video.progress;  // 0 to 100
video.videoUrl;  // the MP4 once completed; works for 24 hours without a key
video.error;     // why it failed

const finished = await kolavid.videos.list({ limit: 10, status: "completed" });

const mp4 = await kolavid.videos.download(videoId);        // ArrayBuffer
const blob = await kolavid.videos.downloadBlob(videoId);   // Blob (video/mp4)
const response = await kolavid.videos.fileResponse(videoId); // stream response.body yourself

const account = await kolavid.me(); // { email, credits, plan }; plan: free, starter, creator or studio
```

`videos.wait(id, { pollInterval: 5, timeout: 900 })` (seconds) polls until the video is completed or failed and
resolves to it; it throws `WaitTimeoutError` (with `.video`) if the timeout passes first. `timeout: null` waits for
ever. Pass `{ signal }` to stop any call.

In Node, `downloadToFile(client, id, path)` from `kolavid/node` streams the MP4 to a file (or into a folder as
`kolavid-<id>.mp4`) and never leaves a half-written file.

Returned objects use camelCase (`videoUrl`, `lengthMinutes`, `createdAt`); times are ISO 8601 strings. The API's
answer as it came is in `.raw`.

## Errors

Every error is a `KolaVidError`. Errors from the API are `APIError` with `status`, `message` (a sentence you can
show), `code` and `body`.

| Error | When |
|---|---|
| `AuthenticationError` | 401: missing, wrong or revoked key |
| `InsufficientCreditsError` | 402: not enough credits; `.pricingUrl` is where to buy more |
| `PermissionDeniedError` | 403: the account is closed |
| `NotFoundError` | 404: no such video in this account |
| `ValidationError` | 422: a field is wrong, the link can't be read, or the request was refused; `.details` lists field problems |
| `RateLimitError` | 429: more than 60 requests a minute; `.retryAfter` in seconds |
| `VideoInProgressError` | 429 on create: another video is still being made (a `RateLimitError`) |
| `ServerError` | 5xx |
| `APIConnectionError`, `APITimeoutError` | no answer from KolaVid |
| `VideoNotReadyError`, `VideoFailedError` | downloading before the video is finished, or after it failed |

```ts
import { InsufficientCreditsError, VideoInProgressError } from "kolavid";

try {
  await kolavid.videos.create({ prompt: "The water cycle", lengthMinutes: 5 });
} catch (error) {
  if (error instanceof InsufficientCreditsError) console.log(error.message, "Buy more at", error.pricingUrl);
  else if (error instanceof VideoInProgressError) console.log("Another video is being made; try again when it is done.");
  else throw error;
}
```

## Retries and timeouts

The client asks again (up to `maxRetries`, default 2) after a rate limit, a 5xx answer or a broken connection,
waiting as long as the API's `Retry-After` says, otherwise a short growing pause. A `create` is retried only when it
surely made nothing (the per-key rate limit, or 503 unavailable), never after a timeout or a dropped connection, so a
retry never makes two videos.

```ts
const kolavid = new KolaVid({ apiKey: process.env.KOLAVID_API_KEY, timeoutMs: 30_000, maxRetries: 4 });
```

Pass `fetch` to use another fetch (undici with a proxy, or a fake in your tests).

## Browsers

An API key in a web page can be read by anyone using the page, so the client refuses to start in a browser. Call
KolaVid from your server. If the key is the user's own (a tool they run themselves), pass
`{ dangerouslyAllowBrowser: true }`.

## CommonJS

The package is ESM. In CommonJS use `const { KolaVid } = await import("kolavid")`, or `require("kolavid")` on
Node 20.19+ / 22.12+.

## Development

```bash
npm run build   # tsc to dist/
npm test        # build, then node --test against dist/ with a fake fetch; no network needed
```

MIT licence. Copyright Kola Labs Ltd.
