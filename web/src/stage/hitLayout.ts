import { intlTag, type Locale } from "../i18n/messages";
import type { HitExtract } from "../types";

export const HIT_LAYOUT_KEY = "jev.hitLayout";
export const HIT_NEW_MS = 60 * 60 * 1000;
export const HIT_NEW_TICK_MS = 60_000;

const HIT_GAP = 8;
const HIT_COL_MIN = 300;

export type HitLayout = "masonry" | "aligned";

export type HitDayGroup = {
  key: string;
  items: HitExtract[];
};

export function readHitLayout(): HitLayout {
  try {
    const raw = localStorage.getItem(HIT_LAYOUT_KEY);
    if (raw === "masonry" || raw === "aligned") return raw;
  } catch {
    /* private mode or blocked storage */
  }
  return "masonry";
}

export function storeHitLayout(next: HitLayout) {
  try {
    localStorage.setItem(HIT_LAYOUT_KEY, next);
  } catch {
    /* ignore quota / private mode */
  }
}

function hitColumnCount(width: number) {
  if (width <= HIT_COL_MIN) return 1;
  return Math.max(1, Math.floor((width + HIT_GAP) / (HIT_COL_MIN + HIT_GAP)));
}

export function hitBubblePlaying(card: HTMLElement) {
  if (!card.classList.contains("is-born")) return false;
  return card.getAnimations().some((anim) => anim instanceof CSSAnimation && anim.animationName === "hit-bubble");
}

/** Card border-box can stay stuck on the image strip; size the brick from media plus body. */
function brickHeight(card: HTMLElement) {
  let content = 0;
  for (const child of card.children) {
    if (child instanceof HTMLElement) content += child.offsetHeight;
  }
  if (content <= 0) return card.offsetHeight;
  const border = Math.max(0, card.offsetHeight - card.clientHeight);
  return content + border;
}

function hitBrickCards(root: HTMLElement) {
  return Array.from(root.children).filter(
    (node): node is HTMLElement => node instanceof HTMLElement && node.classList.contains("result-card"),
  );
}

export function clearHitBricks(root: HTMLElement) {
  root.style.height = "";
  for (const card of hitBrickCards(root)) {
    card.style.left = "";
    card.style.top = "";
    card.style.width = "";
    card.style.height = "";
    card.style.containIntrinsicSize = "";
    card.style.contentVisibility = "";
  }
}

export function packHitBricks(root: HTMLElement) {
  const width = root.clientWidth;
  if (width <= 0) return;
  const cards = hitBrickCards(root);
  if (!cards.length) {
    root.style.height = "0px";
    return;
  }
  const cols = hitColumnCount(width);
  const colWidth = (width - HIT_GAP * (cols - 1)) / cols;
  const xs: number[] = [];
  const ws: number[] = [];
  let cursor = 0;
  for (let col = 0; col < cols; col += 1) {
    const columnWidth = col === cols - 1 ? width - cursor : Math.round(colWidth);
    xs.push(cursor);
    ws.push(Math.max(0, columnWidth));
    cursor += columnWidth + HIT_GAP;
  }
  const measureWidth = Math.min(...ws);
  const bubbling = new Set(cards.filter(hitBubblePlaying));
  cards.forEach((card) => {
    card.style.left = "0px";
    card.style.top = "0px";
    card.style.width = `${measureWidth}px`;
    card.style.height = "auto";
    card.style.containIntrinsicSize = "none";
    if (!bubbling.has(card)) card.style.contentVisibility = "visible";
  });
  const measured = cards.map((card) => brickHeight(card));
  const heights = new Array<number>(cols).fill(0);
  cards.forEach((card, index) => {
    let col = 0;
    for (let next = 1; next < cols; next += 1) {
      if (heights[next] < heights[col]) col = next;
    }
    const y = heights[col];
    card.style.left = `${xs[col]}px`;
    card.style.width = `${ws[col]}px`;
    card.style.top = `${y}px`;
    const height = ws[col] === measureWidth ? measured[index] : brickHeight(card);
    card.style.height = `${height}px`;
    card.style.containIntrinsicSize = `${height}px`;
    heights[col] = y + height + HIT_GAP;
  });
  cards.forEach((card) => {
    if (!bubbling.has(card)) card.style.contentVisibility = "";
  });
  root.style.height = `${Math.max(0, Math.max(...heights) - HIT_GAP)}px`;
}

function localDayKey(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function hitMessageMs(hit: HitExtract) {
  if (!hit.timestamp) return null;
  const ms = Date.parse(hit.timestamp);
  return Number.isFinite(ms) ? ms : null;
}

export function hitIsFresh(hit: HitExtract, nowMs: number) {
  const ms = hitMessageMs(hit);
  if (ms == null) return false;
  return nowMs - ms < HIT_NEW_MS;
}

export function groupHitsByMessageDay(items: HitExtract[]): HitDayGroup[] {
  const ranked = items.map((item, index) => ({ item, index, ms: hitMessageMs(item) }));
  ranked.sort((a, b) => {
    if (a.ms == null && b.ms == null) return a.index - b.index;
    if (a.ms == null) return 1;
    if (b.ms == null) return -1;
    if (a.ms !== b.ms) return b.ms - a.ms;
    return a.index - b.index;
  });
  const groups: HitDayGroup[] = [];
  for (const row of ranked) {
    const key = row.ms == null ? "" : localDayKey(new Date(row.ms));
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(row.item);
    else groups.push({ key, items: [row.item] });
  }
  return groups;
}

export function dayChipLabel(key: string, locale: Locale, todayLabel: string, yesterdayLabel: string, now: Date) {
  if (!key) return null;
  if (key === localDayKey(now)) return todayLabel;
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (key === localDayKey(yesterday)) return yesterdayLabel;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString(intlTag(locale), {
    month: "short",
    day: "numeric",
    ...(year === now.getFullYear() ? {} : { year: "numeric" }),
  });
}
