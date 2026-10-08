import type { HitExtract } from "../types";

export const HITS_PAGE_SIZE = 40;
export const HITS_IDLE_MS = 1500;
export const HITS_KEEP_MAX = 120;
export const HITS_KEEP_PAD = 40;
export const HITS_RELEASE_MIN = 16;
export const HITS_AT_TOP_PX = 48;

/** Start the next page while about one column viewport of mounted hits remains. Short columns still prefetch by 640px. */
export function hitsPrefetchEdge(clientHeight: number) {
  const view = Number.isFinite(clientHeight) ? Math.max(0, clientHeight) : 0;
  return Math.max(640, view);
}

/** A results page that was unmounted. `cursor` refetches it from the same API. */
type ParkedHitPage = {
  cursor: string | null;
  firstId: string;
  count: number;
};

export type HitsWindow = {
  items: HitExtract[];
  total: number;
  hasMore: boolean;
  /** Cursor that refetches the page beginning at `items[0]`. Null is the newest page. */
  mountedCursor: string | null;
  /** Newest parked page first. The last entry is the one just above the mounted window. */
  abovePages: ParkedHitPage[];
  aboveHeight: number;
  belowHeight: number;
  belowCount: number;
  /** New hits arrived while the newest page was unmounted. */
  headStale: boolean;
};

export const EMPTY_HITS_WINDOW: HitsWindow = {
  items: [],
  total: 0,
  hasMore: false,
  mountedCursor: null,
  abovePages: [],
  aboveHeight: 0,
  belowHeight: 0,
  belowCount: 0,
  headStale: false,
};

/** Same opaque cursor the results API uses to continue toward older hits. */
function encodeHitCursor(hit: HitExtract): string | null {
  if (!hit.batchId || !hit.messageId) return null;
  const sortAt = hit.completedAt || hit.updatedAt || "";
  const ordinal = Math.trunc(Number(hit.ordinal) || 0);
  const raw = `{"t":${JSON.stringify(sortAt)},"b":${JSON.stringify(hit.batchId)},"o":${ordinal},"m":${JSON.stringify(hit.messageId)}}`;
  const bytes = new TextEncoder().encode(raw);
  let binary = "";
  const step = 0x8000;
  for (let index = 0; index < bytes.length; index += step) {
    binary += String.fromCharCode(...bytes.subarray(index, index + step));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function sameItemIds(left: readonly HitExtract[], right: readonly HitExtract[]) {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index].id !== right[index].id) return false;
  }
  return true;
}

export function parkChunks(
  items: readonly HitExtract[],
  startCursor: string | null,
): { pages: ParkedHitPage[]; nextCursor: string | null } | null {
  if (!items.length) return { pages: [], nextCursor: startCursor };
  const pages: ParkedHitPage[] = [];
  let cursor = startCursor;
  for (let index = 0; index < items.length; index += HITS_PAGE_SIZE) {
    const chunk = items.slice(index, index + HITS_PAGE_SIZE);
    const first = chunk[0];
    const last = chunk[chunk.length - 1];
    if (!first?.id || !last?.id) return null;
    const next = encodeHitCursor(last);
    if (!next) return null;
    pages.push({ cursor, firstId: first.id, count: chunk.length });
    cursor = next;
  }
  return { pages, nextCursor: cursor };
}

export function heightShare(height: number, take: number, total: number) {
  if (height <= 0 || take <= 0 || total <= 0) return 0;
  return height * (Math.min(take, total) / total);
}

/**
 * Drop mounted hits outside the keep set, but only as a prefix and a suffix so
 * the cards that stay are still one cursor range. Images on dropped hits leave
 * React state; parked cursors can load them again.
 */
export function releaseOutside(
  view: HitsWindow,
  keepIds: ReadonlySet<string>,
  atTop: boolean,
): { view: HitsWindow; olderCursor: string | null } | null {
  if (!view.items.length || keepIds.size === 0) return null;
  let first = -1;
  let last = -1;
  for (let index = 0; index < view.items.length; index += 1) {
    if (!keepIds.has(view.items[index].id)) continue;
    if (first < 0) first = index;
    last = index;
  }
  if (first < 0) return null;
  const prefix = atTop ? [] : view.items.slice(0, first);
  let middle = view.items.slice(atTop ? 0 : first, last + 1);
  const suffix = view.items.slice(last + 1);
  if (!prefix.length && !suffix.length) return null;

  let abovePages = view.abovePages;
  let mountedCursor = view.mountedCursor;
  if (prefix.length) {
    const parked = parkChunks(prefix, view.mountedCursor);
    if (!parked?.nextCursor) {
      middle = view.items.slice(0, last + 1);
    } else {
      abovePages = [...view.abovePages, ...parked.pages];
      mountedCursor = parked.nextCursor;
    }
  }

  let belowCount = view.belowCount;
  let hasMore = view.hasMore;
  let olderCursor: string | null = null;
  let kept = middle;
  if (suffix.length) {
    const older = encodeHitCursor(middle[middle.length - 1]);
    if (older) {
      belowCount += suffix.length;
      hasMore = true;
      olderCursor = older;
    } else {
      kept = [...middle, ...suffix];
    }
  }
  if (kept.length === view.items.length) return null;
  return {
    olderCursor,
    view: {
      ...view,
      items: kept,
      hasMore,
      mountedCursor,
      abovePages,
      belowCount,
    },
  };
}
