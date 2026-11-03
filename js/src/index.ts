/**
 * Official JavaScript and TypeScript client for the KolaVid API (https://kolavid.com/developers).
 *
 *     import { KolaVid } from "kolavid";
 *
 *     const kolavid = new KolaVid(); // reads KOLAVID_API_KEY
 *     const started = await kolavid.videos.create({ prompt: "How vaccines work, for 12-year-olds", lengthMinutes: 2 });
 *     const video = await kolavid.videos.wait(started.id);
 *     if (video.status === "completed") console.log(video.videoUrl);
 */
export { KolaVid, Videos, DEFAULT_BASE_URL, CLIENT_NAME, type VideoRef } from "./client.js";
export {
  KolaVidError,
  APIError,
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  InsufficientCreditsError,
  PermissionDeniedError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  VideoInProgressError,
  ServerError,
  VideoNotReadyError,
  VideoFailedError,
  WaitTimeoutError,
  type FieldProblem,
} from "./errors.js";
export type {
  Account,
  AspectRatio,
  ClientOptions,
  CreateVideoParams,
  FetchLike,
  ListVideosParams,
  RequestOptions,
  Video,
  VideoStatus,
  WaitOptions,
} from "./types.js";
export { VERSION } from "./version.js";
export { KolaVid as default } from "./client.js";
