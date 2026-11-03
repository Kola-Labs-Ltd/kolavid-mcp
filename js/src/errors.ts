/**
 * Errors thrown by the KolaVid client. The API answers errors as JSON with `detail` (a sentence to show) and usually
 * `error` (a code); a request that fails field validation has `detail` as a list of problems (`ValidationError.details`).
 */

export const DEFAULT_PRICING_URL = "https://kolavid.com/pricing";

/** Base class for every error this package throws. */
export class KolaVidError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message);
    this.name = new.target.name;
    if (options && "cause" in options) (this as { cause?: unknown }).cause = options.cause;
  }
}

/** The API could not be reached (DNS, refused connection, TLS, CORS in a browser, dropped connection). */
export class APIConnectionError extends KolaVidError {}

/** The API did not answer within the client's timeout. */
export class APITimeoutError extends APIConnectionError {}

export interface FieldProblem {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
  [key: string]: unknown;
}

/** The API answered with an error status. `message` is the API's sentence, safe to show to a person. */
export class APIError extends KolaVidError {
  readonly status: number;
  /** The API's error code, for example "insufficient_credits"; may be undefined. */
  readonly code: string | undefined;
  /** The parsed JSON body (or the text, or null). */
  readonly body: unknown;
  /** Response headers, lower-case names. */
  readonly headers: Record<string, string>;

  constructor(message: string, init: { status: number; code?: string; body?: unknown; headers?: Record<string, string> }) {
    super(message);
    this.status = init.status;
    this.code = init.code;
    this.body = init.body ?? null;
    this.headers = init.headers ?? {};
  }
}

/** 401: the API key is missing, wrong or revoked. */
export class AuthenticationError extends APIError {}

/** 402: not enough credits for that length. `pricingUrl` is where to buy more. */
export class InsufficientCreditsError extends APIError {
  get pricingUrl(): string {
    const body = this.body as { pricing_url?: unknown } | null;
    return body && typeof body.pricing_url === "string" ? body.pricing_url : DEFAULT_PRICING_URL;
  }
}

/** 403: the account is closed. */
export class PermissionDeniedError extends APIError {}

/** 404: no such video in this account, or an expired file link. */
export class NotFoundError extends APIError {}

/** 422: a field is wrong, the link can't be read, or the request was refused under the content rules. */
export class ValidationError extends APIError {
  /** Field problems as the API gave them; empty when the API answered with a single sentence. */
  get details(): FieldProblem[] {
    const detail = (this.body as { detail?: unknown } | null)?.detail;
    return Array.isArray(detail) ? detail.filter((item): item is FieldProblem => !!item && typeof item === "object") : [];
  }
}

/** 429: more than 60 requests a minute with one key (`retryAfter` seconds), or another video is being made. */
export class RateLimitError extends APIError {
  get retryAfter(): number | undefined {
    return parseRetryAfter(this.headers["retry-after"]);
  }
}

/** 429 on create: another video of this account is still being made. Wait for it, then try again. */
export class VideoInProgressError extends RateLimitError {}

/** 5xx: something went wrong at KolaVid. */
export class ServerError extends APIError {}

/** The video has no file yet (it is still being made, or it failed). */
export class VideoNotReadyError extends KolaVidError {
  readonly video: unknown;
  constructor(message: string, video?: unknown) {
    super(message);
    this.video = video;
  }
}

/** The video failed; `video.error` says why. Failed videos use no credits. */
export class VideoFailedError extends VideoNotReadyError {}

/** `videos.wait` gave up before the video finished; `video` is its last known state. */
export class WaitTimeoutError extends KolaVidError {
  readonly video: unknown;
  constructor(message: string, video?: unknown) {
    super(message);
    this.video = video;
  }
}

/** Seconds from a Retry-After header (seconds or an HTTP date); undefined if absent or unreadable. */
export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (value === null || value === undefined || String(value).trim() === "") return undefined;
  const seconds = Number(String(value).trim());
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const when = Date.parse(String(value));
  return Number.isNaN(when) ? undefined : Math.max(0, (when - Date.now()) / 1000);
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const { detail, message, error } = body as { detail?: unknown; message?: unknown; error?: unknown };
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail)) {
      const parts = detail
        .filter((item): item is FieldProblem => !!item && typeof item === "object")
        .map((problem) => {
          const loc = (problem.loc ?? []).filter((part) => part !== "body").map(String);
          const msg = String(problem.msg ?? "").trim();
          return loc.length ? `${loc.join(".")}: ${msg}` : msg;
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
    for (const value of [message, error]) {
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  if (typeof body === "string" && body.trim() && body.length < 500) return body.trim();
  return `KolaVid API error ${status}`;
}

/** The error to throw for an API error response. */
export function errorFor(status: number, body: unknown, headers: Record<string, string>, creating = false): APIError {
  const message = messageFrom(body, status);
  const rawCode = body && typeof body === "object" ? (body as { error?: unknown }).error : undefined;
  const init = { status, code: typeof rawCode === "string" ? rawCode : undefined, body, headers };
  if (status === 401) return new AuthenticationError(message, init);
  if (status === 402) return new InsufficientCreditsError(message, init);
  if (status === 403) return new PermissionDeniedError(message, init);
  if (status === 404) return new NotFoundError(message, init);
  if (status === 400 || status === 422) return new ValidationError(message, init);
  if (status === 429) {
    // The per-key rate limit names Retry-After; "one video at a time" does not.
    return creating && !("retry-after" in headers)
      ? new VideoInProgressError(message, init)
      : new RateLimitError(message, init);
  }
  if (status >= 500) return new ServerError(message, init);
  return new APIError(message, init);
}
