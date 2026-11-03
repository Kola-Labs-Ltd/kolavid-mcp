// The few Node built-ins src/node.ts uses, declared here so the build needs no @types/node. Not shipped: dist/node.d.ts
// mentions none of these types.
declare module "node:fs/promises" {
  interface FileHandle {
    write(data: Uint8Array): Promise<unknown>;
    close(): Promise<void>;
  }
  export function open(path: string, flags: string): Promise<FileHandle>;
  export function mkdir(path: string, options?: { recursive?: boolean }): Promise<string | undefined>;
  export function rename(from: string, to: string): Promise<void>;
  export function unlink(path: string): Promise<void>;
  export function stat(path: string): Promise<{ isDirectory(): boolean; size: number }>;
}

declare module "node:path" {
  export function basename(path: string): string;
  export function dirname(path: string): string;
  export function join(...parts: string[]): string;
}
