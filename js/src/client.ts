import {
  APIConnectionError,
  APITimeoutError,
  KolaVidError,
  NotFoundError,
  VideoFailedError,
  VideoNotReadyError,
  WaitTimeoutError,
  errorFor,
  parseRetryAfter,
} from "./errors.js";
import {
  toAccount,
  toVideo,
  type Account,
  type ClientOptions,
  type CreateVideoParams,
  type FetchLike,
  type ListVideosParams,
  type RequestOptions,
  type Video,
  type WaitOptions,
} from "./types.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://kolavid.com";
export const CLIENT_NAME = "sdk-js";
const DEFAULT_TIMEOUT_MS = 60_000;
const DEFAULT_DOWNLOAD_TIMEOUT_MS = 300_000;
const DEFAULT_MAX_RETRIES = 2;
/** A Retry-After longer than this (seconds) is not waited out; the RateLimitError is thrown instead. */
const MAX_RETRY_WAIT = 120;
/** Statuses worth asking again for. A create (POST) is retried only when it surely made nothing: the per-key rate limit
 * (429 with Retry-After) and 503 (the API or a link reader is unavailable; nothing was started). */
const RETRY_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const CREATE_RETRY_STATUSES = new Set([503]);

export type VideoRef = string | { id: string };

type Env = Record<string, string | undefined>;

function env(): Env {
  const process = (globalThis as { process?: { env?: Env } }).process;
  return (process && process.env) || {};
}

function isBrowser(): boolean {
  const g = globalThis as { window?: { document?: unknown } };
  return typeof g.window !== "undefined" && typeof g.window.document !== "undefined";
}

function videoId(video: VideoRef): string {
  const value = typeof video === "string" ? video : video && video.id;
  if (typeof value !== "string" || !value.trim()) throw new TypeError("A video id is needed.");
  return value.trim();
}

function lowerHeaders(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((value, name) => {
    out[name.toLowerCase()] = value;
  });
  return out;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function abortError(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
}

function sleepFor(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError(signal));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError(signal as AbortSignal));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

interface SendOptions extends RequestOptions {
  method?: string;
  query?: Record<string, string | number>;
  body?: Record<string, unknown>;
  creating?: boolean;
}

/** `client.videos`: start, check, list, wait for and download videos. */
export class Videos {
  constructor(private readonly client: KolaVid) {}

  /**
   * Start a video. Give at least one of `prompt`, `text` or `sourceUrl` (not both `text` and `sourceUrl`). Credits
   * (60 a minute) are taken only when the video is finished. Resolves to the new video (status "queued").
   *
   * Throws InsufficientCreditsError (402), ValidationError (422), VideoInProgressError (429: another video of this
   * account is still being made) and the other APIError kinds.
   */
  async create(params: CreateVideoParams, options: RequestOptions = {}): Promise<Video> {
    const { prompt, text, sourceUrl, lengthMinutes = 1, aspectRatio = "16:9", voice, language, extraBody } = params ?? {};
    if (![prompt, text, sourceUrl].some((value) => typeof value === "string" && value.trim())) {
      throw new TypeError("Give at least one of prompt, text or sourceUrl.");
    }
    const body: Record<string, unknown> = { length_minutes: lengthMinutes, aspect_ratio: aspectRatio };
    const fields: [string, string | undefined][] = [
      ["prompt", prompt], ["text", text], ["source_url", sourceUrl], ["voice", voice], ["language", language],
    ];
    for (const [name, value] of fields) if (value !== undefined && value !== null) body[name] = value;
    Object.assign(body, extraBody ?? {});
    const data = await this.client.send("/videos", { ...options, method: "POST", body, creating: true });
    return toVideo(data as Record<string, unknown>);
  }

  /** A video's status, progress and, once completed, its `videoUrl` (works for 24 hours, no key needed). */
  async get(video: VideoRef, options: RequestOptions = {}): Promise<Video> {
    const data = await this.client.send(`/videos/${encodeURIComponent(videoId(video))}`, options);
    return toVideo(data as Record<string, unknown>);
  }

  /** The newest videos (`limit` 1 to 100, default 25), optionally only one `status`. */
  async list(params: ListVideosParams = {}, options: RequestOptions = {}): Promise<Video[]> {
    const query: Record<string, string | number> = { limit: params.limit ?? 25 };
    if (params.status) query.status = params.status;
    const data = (await this.client.send("/videos", { ...options, query })) as { videos?: unknown } | null;
    const items = data && Array.isArray(data.videos) ? data.videos : [];
    return items.filter((item): item is Record<string, unknown> => !!item && typeof item === "object").map(toVideo);
  }

  /**
   * Poll until the video is completed or failed and resolve to it (check `video.status`; a failed video's `error`
   * says why). A video takes about 2 to 4 minutes. Throws WaitTimeoutError (with the last `video`) after `timeout`.
   */
  async wait(video: VideoRef, options: WaitOptions = {}): Promise<Video> {
    const { pollInterval = 5, timeout = 900, onProgress, signal } = options;
    if (!(pollInterval > 0)) throw new RangeError("pollInterval must be more than 0 seconds.");
    const deadline = timeout === null ? null : this.client.now() + timeout * 1000;
    for (;;) {
      const current = await this.get(video, { signal });
      onProgress?.(current);
      if (current.status === "completed" || current.status === "failed") return current;
      const now = this.client.now();
      if (deadline !== null && now >= deadline) {
        throw new WaitTimeoutError(
          `Video ${current.id} was still ${current.status} (${current.progress}%) after ${timeout} seconds.`, current);
      }
      const waitMs = deadline === null ? pollInterval * 1000 : Math.max(0, Math.min(pollInterval * 1000, deadline - now));
      await this.client.sleep(waitMs, signal);
    }
  }

  /**
   * The finished video's file as a fetch Response, to stream (`response.body`). Asks for the video first so the link
   * is fresh. Throws VideoNotReadyError while it is being made and VideoFailedError if it failed.
   */
  async fileResponse(video: VideoRef, options: RequestOptions & { timeoutMs?: number } = {}): Promise<Response> {
    const current = await this.get(video, options);
    if (current.status === "failed") {
      throw new VideoFailedError(`Video ${current.id} failed: ${current.error || "no reason given"}`, current);
    }
    if (current.status !== "completed" || !current.videoUrl) {
      throw new VideoNotReadyError(
        `Video ${current.id} is ${current.status || "not ready"} (${current.progress}%); wait for it first.`, current);
    }
    try {
      return await this.client.fetchFile(current.videoUrl, options);
    } catch (error) {
      // The link expired between asking and downloading: ask once more for a fresh one.
      if (!(error instanceof NotFoundError)) throw error;
      const fresh = await this.get(current.id, options);
      if (!fresh.videoUrl) throw error;
      return this.client.fetchFile(fresh.videoUrl, options);
    }
  }

  /** The finished MP4 in memory. In Node, `downloadToFile` from "kolavid/node" streams it to disk instead. */
  async download(video: VideoRef, options: RequestOptions & { timeoutMs?: number } = {}): Promise<ArrayBuffer> {
    const response = await this.fileResponse(video, options);
    return response.arrayBuffer();
  }

  /** The finished MP4 as a Blob (type video/mp4), for a browser download link or an upload. */
  async downloadBlob(video: VideoRef, options: RequestOptions & { timeoutMs?: number } = {}): Promise<Blob> {
    const response = await this.fileResponse(video, options);
    const blob = await response.blob();
    return blob.type ? blob : new Blob([blob], { type: "video/mp4" });
  }
}

/** A client for the KolaVid API (https://kolavid.com/developers). */
export class KolaVid {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxRetries: number;
  readonly videos: Videos;
  readonly #apiKey: string;
  readonly #fetch: FetchLike;
  readonly #defaultHeaders: Record<string, string>;
  readonly #browser: boolean;
  /** @internal Waiting between retries and polls; replaceable in tests. */
  sleep: (ms: number, signal?: AbortSignal) => Promise<void> = sleepFor;
  /** @internal The clock in milliseconds; replaceable in tests. */
  now: () => number = () => Date.now();

  constructor(options: ClientOptions = {}) {
    const vars = env();
    const key = (options.apiKey ?? vars.KOLAVID_API_KEY ?? "").trim();
    if (!key) {
      throw new KolaVidError(
        "No KolaVid API key. Pass { apiKey } or set KOLAVID_API_KEY. Make a key at https://kolavid.com/app/account?tab=api");
    }
    this.#browser = isBrowser();
    if (this.#browser && !options.dangerouslyAllowBrowser) {
      throw new KolaVidError(
        "Using a KolaVid API key in a browser shows it to anyone using the page. Call KolaVid from your server, or " +
          "pass { dangerouslyAllowBrowser: true } if the key is the user's own.");
    }
    let base = (options.baseUrl ?? vars.KOLAVID_BASE_URL ?? DEFAULT_BASE_URL).trim().replace(/\/+$/, "");
    if (base.endsWith("/api/v1")) base = base.slice(0, -"/api/v1".length);
    const maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    if (!(maxRetries >= 0)) throw new RangeError("maxRetries can't be negative.");
    const fetchImpl = options.fetch ?? (globalThis.fetch ? globalThis.fetch.bind(globalThis) : undefined);
    if (!fetchImpl) throw new KolaVidError("No fetch here. Use Node 18 or newer, or pass { fetch }.");
    this.#apiKey = key;
    this.#fetch = fetchImpl as FetchLike;
    this.#defaultHeaders = { ...(options.defaultHeaders ?? {}) };
    this.baseUrl = base;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = maxRetries;
    this.videos = new Videos(this);
  }

  /** The account the key acts for: email, credits and plan. */
  async me(options: RequestOptions = {}): Promise<Account> {
    return toAccount((await this.send("/me", options)) as Record<string, unknown>);
  }

  toString(): string {
    return `KolaVid(baseUrl=${this.baseUrl}, apiKey=${this.#apiKey.slice(0, 8)}...)`;
  }

  /** Keeps the key out of console.log / util.inspect. */
  toJSON(): Record<string, unknown> {
    return { baseUrl: this.baseUrl, timeoutMs: this.timeoutMs, maxRetries: this.maxRetries };
  }

  // --- plumbing -----------------------------------------------------------------------------------------------

  #headers(auth: boolean, json: boolean): Record<string, string> {
    const headers: Record<string, string> = {};
    // Browsers refuse a custom User-Agent, and the API's CORS preflight does not list X-KolaVid-Client yet, so a page
    // sends neither (a page's videos are counted as "api").
    if (!this.#browser) {
      headers["User-Agent"] = `kolavid-js/${VERSION}`;
      headers["X-KolaVid-Client"] = CLIENT_NAME;
    }
    Object.assign(headers, this.#defaultHeaders);
    if (auth) {
      headers.Authorization = `Bearer ${this.#apiKey}`;
      headers.Accept = "application/json";
    }
    if (json) headers["Content-Type"] = "application/json";
    return headers;
  }

  #backoff(attempt: number, headers?: Record<string, string>): number | null {
    const retryAfter = headers ? parseRetryAfter(headers["retry-after"]) : undefined;
    if (retryAfter !== undefined) return retryAfter <= MAX_RETRY_WAIT ? retryAfter * 1000 : null;
    return Math.min(8000, 500 * 2 ** attempt) * (0.75 + Math.random() * 0.25);
  }

  /** One fetch with the client's timeout; no answer at all becomes APIConnectionError / APITimeoutError. */
  async #fetchOnce(url: string, init: RequestInit, timeoutMs: number, signal?: AbortSignal): Promise<Response> {
    if (signal?.aborted) throw abortError(signal);
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const onAbort = () => controller.abort();
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      return await this.#fetch(url, { ...init, signal: controller.signal });
    } catch (error) {
      if (signal?.aborted) throw abortError(signal);
      if (timedOut) throw new APITimeoutError(`KolaVid did not answer within ${timeoutMs / 1000} seconds.`, { cause: error });
      const reason = error instanceof Error ? error.message : String(error);
      throw new APIConnectionError(`Could not reach KolaVid: ${reason}`, { cause: error });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  /** @internal An API call with retries; resolves to the parsed JSON body. */
  async send(path: string, options: SendOptions = {}): Promise<unknown> {
    const { method = "GET", query, body, creating = false, signal } = options;
    let url = `${this.baseUrl}/api/v1${path}`;
    if (query && Object.keys(query).length) {
      url += `?${new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])).toString()}`;
    }
    const init: RequestInit = {
      method,
      headers: this.#headers(true, body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    };
    for (let attempt = 0; ; attempt++) {
      let wait: number | null;
      try {
        const response = await this.#fetchOnce(url, init, this.timeoutMs, signal);
        if (response.ok) return readBody(response);
        const headers = lowerHeaders(response.headers);
        const retryable = creating
          ? CREATE_RETRY_STATUSES.has(response.status) || (response.status === 429 && "retry-after" in headers)
          : RETRY_STATUSES.has(response.status);
        wait = attempt < this.maxRetries && retryable ? this.#backoff(attempt, headers) : null;
        if (wait === null) throw errorFor(response.status, await readBody(response), headers, creating);
        await response.body?.cancel().catch(() => undefined);
      } catch (error) {
        // A create that may have reached the server is never sent twice (it could make two videos).
        if (!(error instanceof APIConnectionError) || creating || attempt >= this.maxRetries) throw error;
        wait = this.#backoff(attempt);
      }
      await this.sleep(wait ?? 0, signal);
    }
  }

  /** @internal A signed file link (no key is sent; the link carries its own signature), with retries. */
  async fetchFile(url: string, options: RequestOptions & { timeoutMs?: number } = {}): Promise<Response> {
    const timeoutMs = options.timeoutMs ?? Math.max(this.timeoutMs, DEFAULT_DOWNLOAD_TIMEOUT_MS);
    const init: RequestInit = { method: "GET", headers: this.#headers(false, false) };
    for (let attempt = 0; ; attempt++) {
      let wait: number | null;
      try {
        const response = await this.#fetchOnce(url, init, timeoutMs, options.signal);
        if (response.ok) return response;
        const headers = lowerHeaders(response.headers);
        wait = attempt < this.maxRetries && RETRY_STATUSES.has(response.status) ? this.#backoff(attempt, headers) : null;
        if (wait === null) throw errorFor(response.status, await readBody(response), headers);
        await response.body?.cancel().catch(() => undefined);
      } catch (error) {
        if (!(error instanceof APIConnectionError) || attempt >= this.maxRetries) throw error;
        wait = this.#backoff(attempt);
      }
      await this.sleep(wait ?? 0, options.signal);
    }
  }
}
