/** The API's objects. The API only ever adds fields; the full answer is kept in `raw`. */

/** "queued", "making", "completed" or "failed" (stopped videos are "failed" too). */
export type VideoStatus = "queued" | "making" | "completed" | "failed";

export type AspectRatio = "16:9" | "9:16" | "1:1";

/** A video, as GET /api/v1/videos/{id} describes it. `create` answers with fewer fields; the rest are null until you
 * `get` or `wait` for the video. Times are ISO 8601 strings in UTC ("2026-11-02T12:00:00Z"). */
export interface Video {
  id: string;
  status: VideoStatus;
  /** 0 to 100. */
  progress: number;
  title: string | null;
  lengthMinutes: number | null;
  aspectRatio: AspectRatio | string | null;
  createdAt: string | null;
  completedAt: string | null;
  /** The MP4 once completed; works for 24 hours without a key. Ask again for a fresh link. */
  videoUrl: string | null;
  thumbnailUrl: string | null;
  /** The public page, if the video was shared in the app. */
  shareUrl: string | null;
  /** The video in the KolaVid app. */
  appUrl: string | null;
  /** Where to poll the video (only in the answer to `create`). */
  statusUrl: string | null;
  /** Why it failed, when status is "failed". */
  error: string | null;
  /** The API's answer as it came. */
  raw: Record<string, unknown>;
}

/** The account an API key acts for (GET /api/v1/me). */
export interface Account {
  email: string;
  credits: number;
  /** "free", "starter", "creator" or "studio". */
  plan: string;
  raw: Record<string, unknown>;
}

export interface CreateVideoParams {
  /** The topic and any instructions: audience, tone, what to cover. */
  prompt?: string;
  /** Source text to explain (an article, notes, a script). Up to 100,000 characters. */
  text?: string;
  /** A public web page to explain (up to three, separated by spaces). */
  sourceUrl?: string;
  /** 1 to 5. Default 1. */
  lengthMinutes?: number;
  /** "16:9" (default), "9:16" or "1:1". */
  aspectRatio?: AspectRatio;
  /** "female" (default), "male", or a voice by name: Kore, Leda, Aoede, Zephyr, Puck, Charon, Fenrir, Orus... */
  voice?: string;
  /** Narration language, for example "Spanish". Default English. */
  language?: string;
  /** Extra JSON fields for API options newer than this package. */
  extraBody?: Record<string, unknown>;
}

export interface ListVideosParams {
  /** 1 to 100, default 25. */
  limit?: number;
  /** Only videos with this status; "completed" lists them by when they finished. */
  status?: VideoStatus;
}

export interface RequestOptions {
  /** Cancels the call (and any waiting between retries or polls). */
  signal?: AbortSignal;
}

export interface WaitOptions extends RequestOptions {
  /** Seconds between checks. Default 5. */
  pollInterval?: number;
  /** Seconds to wait in all before throwing WaitTimeoutError. Default 900; null waits for ever. */
  timeout?: number | null;
  /** Called with each state seen. */
  onProgress?: (video: Video) => void;
}

/** Any fetch-compatible function (the global fetch, undici, node-fetch, a test fake). */
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface ClientOptions {
  /** A key from Account > API keys (kv_live_...). Defaults to process.env.KOLAVID_API_KEY in Node. */
  apiKey?: string;
  /** The site, default https://kolavid.com (or process.env.KOLAVID_BASE_URL). */
  baseUrl?: string;
  /** Milliseconds to wait for each API answer. Default 60,000. */
  timeoutMs?: number;
  /** How many times to ask again after a rate limit, a server error or a broken connection. Default 2. */
  maxRetries?: number;
  /** The fetch to use. Default: the global fetch (Node 18+, browsers, Deno, Bun, workers). */
  fetch?: FetchLike;
  /** Extra headers for every request. */
  defaultHeaders?: Record<string, string>;
  /** Allow use in a browser, where the key is visible to anyone using the page. Default false. */
  dangerouslyAllowBrowser?: boolean;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function int(value: unknown): number | null {
  const number = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(number) ? Math.trunc(number) : null;
}

export function toVideo(data: Record<string, unknown>): Video {
  return {
    id: String(data.id ?? ""),
    status: String(data.status ?? "") as VideoStatus,
    progress: int(data.progress) ?? 0,
    title: str(data.title),
    lengthMinutes: int(data.length_minutes),
    aspectRatio: str(data.aspect_ratio),
    createdAt: str(data.created_at),
    completedAt: str(data.completed_at),
    videoUrl: str(data.video_url),
    thumbnailUrl: str(data.thumbnail_url),
    shareUrl: str(data.share_url),
    appUrl: str(data.app_url),
    statusUrl: str(data.status_url),
    error: str(data.error),
    raw: { ...data },
  };
}

export function toAccount(data: Record<string, unknown>): Account {
  const credits = Number(data.credits ?? 0);
  return {
    email: String(data.email ?? ""),
    credits: Number.isFinite(credits) ? credits : 0,
    plan: String(data.plan ?? "free"),
    raw: { ...data },
  };
}
