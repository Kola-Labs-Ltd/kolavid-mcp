// The KolaVid JS client (built dist/) against a fake fetch. Nothing here reaches kolavid.com.
// Run: npm run build && node --test test/
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test, describe } from "node:test";
import { readFileSync } from "node:fs";

import KolaVidDefault, {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  InsufficientCreditsError,
  KolaVid,
  KolaVidError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServerError,
  VERSION,
  ValidationError,
  VideoFailedError,
  VideoInProgressError,
  VideoNotReadyError,
  WaitTimeoutError,
} from "../dist/index.js";
import { downloadToFile } from "../dist/node.js";

const KEY = "kv_live_test_0123456789abcdefghijklmnopqrstuvwx";
const VID = "4d018ec2-1111-2222-3333-444455556666";
const BASE = "https://kolavid.com/api/v1";

function videoBody(status = "completed", progress = 100, extra = {}) {
  return {
    id: VID, status, progress, title: "How vaccines work", length_minutes: 2, aspect_ratio: "16:9",
    created_at: "2026-11-02T12:00:00Z", completed_at: status === "completed" ? "2026-11-02T12:03:10Z" : null,
    video_url: status === "completed" ? `${BASE}/files/${VID}/video?expires=1&sig=abc` : null,
    thumbnail_url: null, share_url: null, app_url: `https://kolavid.com/app/jobs/${VID}`, error: null, ...extra,
  };
}

const json = (status, body, headers = {}) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status, headers: { "content-type": "application/json", ...headers },
  });
const bytes = (data, status = 200) => new Response(data, { status, headers: { "content-type": "video/mp4" } });

/** A fetch that answers each call with the next queued Response (or throws the next queued error). */
function fakeFetch(...answers) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET", headers: { ...(init.headers ?? {}) }, body: init.body, signal: init.signal });
    if (!answers.length) throw new Error(`unexpected request ${init.method} ${url}`);
    const next = answers.shift();
    if (typeof next === "function") return next(url, init);
    if (next instanceof Error) throw next;
    return next;
  };
  fn.calls = calls;
  return fn;
}

function clientWith(...answers) {
  const fetch = fakeFetch(...answers);
  const client = new KolaVid({ apiKey: KEY, fetch });
  client.sleeps = [];
  client.sleep = async (ms) => {
    client.sleeps.push(ms);
  };
  return { client, fetch };
}

describe("setup", () => {
  test("the key comes from KOLAVID_API_KEY when not given", async () => {
    const before = process.env.KOLAVID_API_KEY;
    process.env.KOLAVID_API_KEY = KEY;
    try {
      const fetch = fakeFetch(json(200, { email: "a@b.c", credits: 1, plan: "free" }));
      await new KolaVid({ fetch }).me();
      assert.equal(fetch.calls[0].headers.Authorization, `Bearer ${KEY}`);
    } finally {
      if (before === undefined) delete process.env.KOLAVID_API_KEY;
      else process.env.KOLAVID_API_KEY = before;
    }
  });

  test("no key is a clear error", () => {
    const before = process.env.KOLAVID_API_KEY;
    delete process.env.KOLAVID_API_KEY;
    try {
      assert.throws(() => new KolaVid({ fetch: fakeFetch() }), (error) => error instanceof KolaVidError && /KOLAVID_API_KEY/.test(error.message));
    } finally {
      if (before !== undefined) process.env.KOLAVID_API_KEY = before;
    }
  });

  test("the key is never shown in full", () => {
    const client = new KolaVid({ apiKey: KEY, fetch: fakeFetch() });
    assert.ok(!String(client).includes(KEY));
    assert.ok(!JSON.stringify(client).includes(KEY));
    assert.ok(!Object.values(client).some((value) => value === KEY));
  });

  test("baseUrl may be given with or without the API path", async () => {
    for (const baseUrl of ["http://localhost:8000", "http://localhost:8000/", "http://localhost:8000/api/v1"]) {
      const fetch = fakeFetch(json(200, { email: "", credits: 0, plan: "free" }));
      await new KolaVid({ apiKey: KEY, baseUrl, fetch }).me();
      assert.equal(fetch.calls[0].url, "http://localhost:8000/api/v1/me");
    }
  });

  test("the default export is the client and the version matches package.json", () => {
    assert.equal(KolaVidDefault, KolaVid);
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    assert.equal(VERSION, pkg.version);
    assert.match(readFileSync(new URL("../CHANGELOG.md", import.meta.url), "utf8"), new RegExp(`## ${VERSION.replace(/\./g, "\\.")}`));
  });
});

describe("requests", () => {
  test("create sends the fields and the SDK headers", async () => {
    const created = { id: VID, status: "queued", created_at: "2026-11-02T12:00:00Z", app_url: `https://kolavid.com/app/jobs/${VID}`, status_url: `${BASE}/videos/${VID}` };
    const { client, fetch } = clientWith(json(201, created));
    const video = await client.videos.create({
      prompt: "How vaccines work, for 12-year-olds", lengthMinutes: 2, aspectRatio: "9:16", voice: "Kore", language: "Spanish",
    });
    const call = fetch.calls[0];
    assert.equal(call.method, "POST");
    assert.equal(call.url, `${BASE}/videos`);
    assert.deepEqual(JSON.parse(call.body), {
      length_minutes: 2, aspect_ratio: "9:16", prompt: "How vaccines work, for 12-year-olds", voice: "Kore", language: "Spanish",
    });
    assert.equal(call.headers["User-Agent"], `kolavid-js/${VERSION}`);
    assert.equal(call.headers["X-KolaVid-Client"], "sdk-js");
    assert.equal(call.headers["Content-Type"], "application/json");
    assert.equal(call.headers.Authorization, `Bearer ${KEY}`);
    assert.equal(video.id, VID);
    assert.equal(video.status, "queued");
    assert.equal(video.statusUrl, `${BASE}/videos/${VID}`);
    assert.equal(video.videoUrl, null);
  });

  test("text or a link alone leaves out what was not given; extraBody is passed on", async () => {
    const { client, fetch } = clientWith(json(201, { id: VID, status: "queued" }), json(201, { id: VID, status: "queued" }));
    await client.videos.create({ text: "An article." });
    await client.videos.create({ sourceUrl: "https://example.com/post", extraBody: { future_field: true } });
    assert.deepEqual(JSON.parse(fetch.calls[0].body), { length_minutes: 1, aspect_ratio: "16:9", text: "An article." });
    assert.deepEqual(JSON.parse(fetch.calls[1].body), {
      length_minutes: 1, aspect_ratio: "16:9", source_url: "https://example.com/post", future_field: true,
    });
  });

  test("create with nothing to explain is refused before any request", async () => {
    const { client, fetch } = clientWith();
    await assert.rejects(client.videos.create({ prompt: "  " }), TypeError);
    assert.equal(fetch.calls.length, 0);
  });

  test("get maps a finished video to camelCase and keeps the raw answer", async () => {
    const { client, fetch } = clientWith(json(200, videoBody("completed", 100, { new_field: "kept" })));
    const video = await client.videos.get(VID);
    assert.equal(fetch.calls[0].url, `${BASE}/videos/${VID}`);
    assert.equal(video.status, "completed");
    assert.equal(video.lengthMinutes, 2);
    assert.equal(video.completedAt, "2026-11-02T12:03:10Z");
    assert.equal(video.appUrl, `https://kolavid.com/app/jobs/${VID}`);
    assert.equal(video.raw.new_field, "kept");
  });

  test("ids are escaped and a video object works as an id", async () => {
    const { client, fetch } = clientWith(json(200, videoBody()), json(200, videoBody()));
    await client.videos.get("a/b?c");
    await client.videos.get({ id: VID });
    assert.equal(fetch.calls[0].url, `${BASE}/videos/a%2Fb%3Fc`);
    assert.equal(fetch.calls[1].url, `${BASE}/videos/${VID}`);
  });

  test("list sends limit and status", async () => {
    const { client, fetch } = clientWith(json(200, { videos: [videoBody(), videoBody("making", 40)] }), json(200, { videos: [] }));
    const videos = await client.videos.list({ limit: 5, status: "completed" });
    assert.equal(fetch.calls[0].url, `${BASE}/videos?limit=5&status=completed`);
    assert.deepEqual(videos.map((v) => v.status), ["completed", "making"]);
    assert.deepEqual(await client.videos.list(), []);
    assert.equal(fetch.calls[1].url, `${BASE}/videos?limit=25`);
  });

  test("me is the account", async () => {
    const { client } = clientWith(json(200, { email: "you@example.com", credits: 4880, plan: "starter" }));
    const account = await client.me();
    assert.equal(account.email, "you@example.com");
    assert.equal(account.credits, 4880);
    assert.equal(account.plan, "starter");
  });
});

describe("errors and retries", () => {
  test("401 is an AuthenticationError", async () => {
    const { client } = clientWith(json(401, { detail: "Invalid or missing API key. Send Authorization: Bearer kv_live_..." }));
    await assert.rejects(client.me(), (error) => error instanceof AuthenticationError && error.status === 401 && /Invalid or missing/.test(error.message));
  });

  test("402 has the pricing page", async () => {
    const { client, fetch } = clientWith(json(402, { detail: "Not enough credits.", error: "insufficient_credits", pricing_url: "https://kolavid.com/pricing" }));
    await assert.rejects(client.videos.create({ prompt: "x" }), (error) =>
      error instanceof InsufficientCreditsError && error.code === "insufficient_credits" && error.pricingUrl === "https://kolavid.com/pricing");
    assert.equal(fetch.calls.length, 1);
  });

  test("403, 404 and 5xx kinds", async () => {
    await assert.rejects(clientWith(json(403, { detail: "Closed." })).client.me(), PermissionDeniedError);
    await assert.rejects(clientWith(json(404, { detail: "Video not found." })).client.videos.get("nope"), NotFoundError);
    const client = new KolaVid({ apiKey: KEY, maxRetries: 0, fetch: fakeFetch(new Response("<html>oops</html>", { status: 500 })) });
    await assert.rejects(client.me(), (error) => error instanceof ServerError && error.message === "<html>oops</html>");
  });

  test("422 field problems are details", async () => {
    const body = { detail: [{ loc: ["body", "length_minutes"], msg: "Input should be less than or equal to 5", type: "less_than_equal" }] };
    const { client } = clientWith(json(422, body));
    await assert.rejects(client.videos.create({ prompt: "x", lengthMinutes: 9 }), (error) =>
      error instanceof ValidationError && error.details[0].loc[1] === "length_minutes" &&
      error.message === "length_minutes: Input should be less than or equal to 5");
  });

  test("a rate limit is waited out as Retry-After says", async () => {
    const { client, fetch } = clientWith(json(429, { detail: "Too many requests." }, { "Retry-After": "7" }), json(200, { email: "a@b.c", credits: 0, plan: "free" }));
    assert.equal((await client.me()).email, "a@b.c");
    assert.deepEqual(client.sleeps, [7000]);
    assert.equal(fetch.calls.length, 2);
  });

  test("a create is retried after the per-key rate limit", async () => {
    const { client, fetch } = clientWith(json(429, { detail: "Too many requests." }, { "Retry-After": "2" }), json(201, { id: VID, status: "queued" }));
    assert.equal((await client.videos.create({ prompt: "x" })).id, VID);
    assert.deepEqual(client.sleeps, [2000]);
    assert.equal(fetch.calls.length, 2);
  });

  test("a rate limit after the last retry is thrown with retryAfter", async () => {
    const limited = () => json(429, { detail: "Too many requests." }, { "Retry-After": "3" });
    const { client, fetch } = clientWith(limited(), limited(), limited());
    await assert.rejects(client.me(), (error) => error instanceof RateLimitError && error.retryAfter === 3);
    assert.equal(fetch.calls.length, 3);
    assert.deepEqual(client.sleeps, [3000, 3000]);
  });

  test("a Retry-After too long to wait is thrown at once", async () => {
    const { client, fetch } = clientWith(json(429, { detail: "Slow down." }, { "Retry-After": "3600" }));
    await assert.rejects(client.me(), RateLimitError);
    assert.equal(fetch.calls.length, 1);
  });

  test("another video being made is not retried", async () => {
    const { client, fetch } = clientWith(json(429, { detail: "You already have a video in progress. Wait for it to finish before starting another.", error: "rate_limited" }));
    await assert.rejects(client.videos.create({ prompt: "x" }), (error) =>
      error instanceof VideoInProgressError && error instanceof RateLimitError && error.retryAfter === undefined);
    assert.equal(fetch.calls.length, 1);
  });

  test("server errors and dropped connections are retried for reads", async () => {
    const { client, fetch } = clientWith(json(503), new TypeError("fetch failed"), json(200, { email: "a@b.c", credits: 1, plan: "free" }));
    assert.equal((await client.me()).plan, "free");
    assert.equal(fetch.calls.length, 3);
    assert.equal(client.sleeps.length, 2);
    assert.ok(client.sleeps.every((ms) => ms > 0 && ms <= 8000));
  });

  test("a create is never sent twice when it may have made a video", async () => {
    for (const first of [json(500, { detail: "boom" }), json(502), json(504), new TypeError("fetch failed")]) {
      const { client, fetch } = clientWith(first, json(201, { id: VID, status: "queued" }));
      await assert.rejects(client.videos.create({ prompt: "x" }), KolaVidError);
      assert.equal(fetch.calls.length, 1);
    }
  });

  test("a create is retried when the API is unavailable", async () => {
    const { client, fetch } = clientWith(json(503, { detail: "Links can't be read right now." }), json(201, { id: VID, status: "queued" }));
    assert.equal((await client.videos.create({ prompt: "x" })).status, "queued");
    assert.equal(fetch.calls.length, 2);
  });

  test("a network failure is an APIConnectionError and a slow answer an APITimeoutError", async () => {
    const down = new KolaVid({ apiKey: KEY, maxRetries: 0, fetch: fakeFetch(new TypeError("fetch failed")) });
    await assert.rejects(down.me(), (error) => error instanceof APIConnectionError && !(error instanceof APITimeoutError));
    const hang = (url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
    const slow = new KolaVid({ apiKey: KEY, maxRetries: 0, timeoutMs: 20, fetch: fakeFetch(hang) });
    await assert.rejects(slow.me(), APITimeoutError);
  });

  test("the caller's AbortSignal stops a call without retries", async () => {
    const controller = new AbortController();
    const hang = (url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
    const fetch = fakeFetch(hang);
    const client = new KolaVid({ apiKey: KEY, fetch });
    const call = client.me({ signal: controller.signal });
    controller.abort(new Error("stop"));
    await assert.rejects(call, (error) => error.message === "stop");
    assert.equal(fetch.calls.length, 1);
  });
});

describe("wait", () => {
  function clocked(...answers) {
    const { client, fetch } = clientWith(...answers);
    let now = 1_000_000;
    client.now = () => now;
    client.sleep = async (ms) => {
      now += ms;
    };
    return { client, fetch, elapsed: () => now - 1_000_000 };
  }

  test("polls until completed", async () => {
    const { client, fetch, elapsed } = clocked(json(200, videoBody("queued", 0)), json(200, videoBody("making", 50)), json(200, videoBody()));
    const seen = [];
    const video = await client.videos.wait(VID, { pollInterval: 10, onProgress: (v) => seen.push(v.progress) });
    assert.equal(video.status, "completed");
    assert.deepEqual(seen, [0, 50, 100]);
    assert.equal(elapsed(), 20_000);
    assert.equal(fetch.calls.length, 3);
  });

  test("a failed video is returned with its reason", async () => {
    const { client } = clocked(json(200, videoBody("failed", 100, { error: "Stopped before it was finished." })));
    const video = await client.videos.wait(VID);
    assert.equal(video.status, "failed");
    assert.equal(video.error, "Stopped before it was finished.");
  });

  test("gives up after the timeout", async () => {
    const making = Array.from({ length: 10 }, () => json(200, videoBody("making", 30)));
    const { client, fetch, elapsed } = clocked(...making);
    await assert.rejects(client.videos.wait(VID, { pollInterval: 5, timeout: 12 }), (error) =>
      error instanceof WaitTimeoutError && error.video.progress === 30);
    assert.equal(elapsed(), 12_000);
    assert.equal(fetch.calls.length, 4);
  });
});

describe("download", () => {
  test("download returns the bytes without sending the key", async () => {
    const { client, fetch } = clientWith(json(200, videoBody()), bytes("MP4DATA"));
    const data = await client.videos.download(VID);
    assert.equal(new TextDecoder().decode(data), "MP4DATA");
    const fileCall = fetch.calls[1];
    assert.equal(fileCall.url, videoBody().video_url);
    assert.equal(fileCall.headers.Authorization, undefined);
    assert.equal(fileCall.headers["X-KolaVid-Client"], "sdk-js");
  });

  test("downloadBlob is a video/mp4 Blob", async () => {
    const { client } = clientWith(json(200, videoBody()), new Response("X", { status: 200 }));
    const blob = await client.videos.downloadBlob(VID);
    assert.equal(blob.size, 1);
    assert.match(blob.type, /video\/mp4|text\/plain/);
  });

  test("an expired link is asked for again once", async () => {
    const fresh = videoBody("completed", 100, { video_url: `${BASE}/files/x/video?expires=2&sig=new` });
    const { client, fetch } = clientWith(json(200, videoBody()), json(404, { detail: "This link has expired." }), json(200, fresh), bytes("NEW"));
    assert.equal(new TextDecoder().decode(await client.videos.download(VID)), "NEW");
    assert.equal(fetch.calls[3].url, fresh.video_url);
  });

  test("a video still being made or failed has no file", async () => {
    await assert.rejects(clientWith(json(200, videoBody("making", 40))).client.videos.download(VID), (error) =>
      error instanceof VideoNotReadyError && !(error instanceof VideoFailedError) && error.video.progress === 40);
    await assert.rejects(clientWith(json(200, videoBody("failed", 100, { error: "Could not finish." }))).client.videos.download(VID),
      (error) => error instanceof VideoFailedError && /Could not finish/.test(error.message));
  });

  test("downloadToFile streams to a file or into a folder, leaving nothing half-written", async () => {
    const folder = await mkdtemp(join(tmpdir(), "kolavid-sdk-"));
    try {
      const big = new Uint8Array(600_000).fill(7);
      let { client } = clientWith(json(200, videoBody()), bytes(big));
      const saved = await downloadToFile(client, VID, join(folder, "out", "vaccines.mp4"));
      assert.equal(saved.bytes, 600_000);
      assert.equal((await readFile(saved.path)).length, 600_000);
      assert.deepEqual(await readdir(join(folder, "out")), ["vaccines.mp4"]);

      ({ client } = clientWith(json(200, videoBody()), bytes("X")));
      const intoFolder = await downloadToFile(client, VID, folder);
      assert.equal(intoFolder.path, join(folder, `kolavid-${VID}.mp4`));

      const broken = new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array([1, 2, 3]));
          controller.error(new Error("connection reset"));
        },
      });
      ({ client } = clientWith(json(200, videoBody()), new Response(broken, { status: 200 })));
      await assert.rejects(downloadToFile(client, VID, join(folder, "broken.mp4")), /connection reset/);
      assert.deepEqual((await readdir(folder)).sort(), [`kolavid-${VID}.mp4`, "out"]);
    } finally {
      await rm(folder, { recursive: true, force: true });
    }
  });
});

describe("browsers", () => {
  test("a page needs dangerouslyAllowBrowser and then sends no User-Agent or client header", async () => {
    globalThis.window = { document: {} };
    try {
      assert.throws(() => new KolaVid({ apiKey: KEY, fetch: fakeFetch() }), /browser/);
      const fetch = fakeFetch(json(200, { email: "", credits: 0, plan: "free" }));
      await new KolaVid({ apiKey: KEY, fetch, dangerouslyAllowBrowser: true }).me();
      assert.equal(fetch.calls[0].headers["User-Agent"], undefined);
      assert.equal(fetch.calls[0].headers["X-KolaVid-Client"], undefined);
      assert.equal(fetch.calls[0].headers.Authorization, `Bearer ${KEY}`);
    } finally {
      delete globalThis.window;
    }
  });
});
