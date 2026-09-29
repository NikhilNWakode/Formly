/** Small display helpers shared by the viewer chrome. */

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatSeconds(value: number): string {
  return value < 1 ? "<1s" : `${value.toFixed(1)}s`;
}
