export const CONCURRENCY_MIN = 1;
export const CONCURRENCY_MAX = 16;
export const CONCURRENCY_DEFAULT = 4;

export function clampConcurrency(value: number) {
  if (!Number.isFinite(value)) return CONCURRENCY_DEFAULT;
  return Math.max(CONCURRENCY_MIN, Math.min(CONCURRENCY_MAX, Math.round(value)));
}
