/**
 * Node helpers (import from "kolavid/node"): save a finished video to disk without holding it in memory.
 *
 *     import { KolaVid } from "kolavid";
 *     import { downloadToFile } from "kolavid/node";
 *
 *     const saved = await downloadToFile(new KolaVid(), videoId, "out/");  // out/kolavid-<id>.mp4
 */
import { mkdir, open, rename, stat, unlink } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

import type { KolaVid, VideoRef } from "./client.js";
import type { RequestOptions } from "./types.js";

export interface DownloadedFile {
  /** Where the MP4 was saved. */
  path: string;
  /** Its size in bytes. */
  bytes: number;
}

async function isDirectory(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

/**
 * Stream the finished MP4 to `path`: a file name, or a folder (ending in "/" or existing) for kolavid-<id>.mp4.
 * The file is written whole or not at all. Throws VideoNotReadyError / VideoFailedError when there is no file.
 */
export async function downloadToFile(
  client: KolaVid,
  video: VideoRef,
  path = ".",
  options: RequestOptions & { timeoutMs?: number } = {},
): Promise<DownloadedFile> {
  const response = await client.videos.fileResponse(video, options);
  const id = typeof video === "string" ? video : video.id;
  const target = path.endsWith("/") || path.endsWith("\\") || (await isDirectory(path)) ? join(path, `kolavid-${id}.mp4`) : path;
  await mkdir(dirname(target), { recursive: true });
  const partial = join(dirname(target), `.${basename(target)}.part`);
  const file = await open(partial, "w");
  let bytes = 0;
  try {
    if (response.body) {
      const reader = response.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          await file.write(value);
          bytes += value.byteLength;
        }
      }
    } else {
      const data = new Uint8Array(await response.arrayBuffer());
      await file.write(data);
      bytes = data.byteLength;
    }
    await file.close();
    await rename(partial, target);
  } catch (error) {
    await file.close().catch(() => undefined);
    await unlink(partial).catch(() => undefined);
    throw error;
  }
  return { path: target, bytes };
}
