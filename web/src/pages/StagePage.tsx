import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MutableRefObject, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api, errorText } from "../api";
import { notifyTasksSnapshot, SETTINGS_CHANGED_EVENT, TASKS_CHANGED_EVENT } from "../channelSync";
import { formatWhen } from "../billingFormat";
import { BillingChip } from "../components/BillingHud";
import { AnalysisToggle, ConnectionStatus } from "../components/ConnectionStatus";
import { matchesQuery, SearchBox } from "../components/fields";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { clampConcurrency, CONCURRENCY_DEFAULT } from "../concurrency";
import { useI18n } from "../i18n/context";
import { intlTag, messages, type Locale } from "../i18n/messages";
import { PanelLink } from "../panelFocus";
import { openShellDialog } from "../shellDialogs";
import { MAX_SIMULTANEOUS_FLIGHTS, type Flight } from "../stage/flights";
import { useSse, type SseStatus } from "../sse";
import type { BatchResult, HitExtract, HitImage, SseEnvelope, StageSnapshot, Tag, Task, WorkerState } from "../types";

const BATCH_FAIL = "\0batch-fail";
const BATCH_ERROR_HIDE_MS = 10_000;
const SNAP = { type: "tween" as const, duration: 0.16, ease: "easeOut" as const };
const HIT_FLY = { type: "tween" as const, duration: 0.3, ease: "easeOut" as const };
const MISS_FADE = { type: "tween" as const, duration: 0.18, ease: "easeOut" as const };
const HANDOFF = { type: "tween" as const, duration: 0.3, ease: "easeOut" as const };
const ROW_FADE = { type: "tween" as const, duration: 0.18, ease: "easeOut" as const };

type QueueHandoff = {
  id: string;
  taskName: string;
  messageCount: number;
  x: number;
  y: number;
  dx: number;
  dy: number;
  width: number;
};

function isLiveBatch(worker: WorkerState) {
  return Boolean(worker.batchId && (worker.status === "packing" || worker.status === "judging"));
}

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function asBatch(payload: Record<string, unknown>): BatchResult {
  return payload as unknown as BatchResult;
}

function asHit(raw: unknown): HitExtract {
  const payload = (raw ?? {}) as Record<string, unknown>;
  const images: HitImage[] = Array.isArray(payload.images)
    ? payload.images.flatMap((item) => {
        const image = (item ?? {}) as Record<string, unknown>;
        const mime = String(image.mime ?? "");
        const base64 = String(image.base64 ?? "");
        return mime && base64 ? [{ mime, base64 }] : [];
      })
    : [];
  return {
    id: String(payload.id ?? ""),
    batchId: String(payload.batchId ?? ""),
    messageId: String(payload.messageId ?? ""),
    taskId: String(payload.taskId ?? ""),
    taskName: (payload.taskName as string | null) ?? null,
    status: "hit",
    noul: payload.noul == null ? null : Number(payload.noul),
    category: (payload.category as string | null) ?? null,
    categoryConfidence: payload.categoryConfidence == null ? null : Number(payload.categoryConfidence),
    chatName: (payload.chatName as string | null) ?? null,
    senderName: (payload.senderName as string | null) ?? null,
    content: (payload.content as string | null) ?? null,
    timestamp: (payload.timestamp as string | null) ?? null,
    ordinal: payload.ordinal == null ? null : Number(payload.ordinal),
    images,
    hitCount: payload.hitCount == null ? null : Number(payload.hitCount),
    messageCount: payload.messageCount == null ? null : Number(payload.messageCount),
    createdAt: payload.createdAt ? String(payload.createdAt) : undefined,
    updatedAt: payload.updatedAt ? String(payload.updatedAt) : undefined,
    completedAt: payload.completedAt ? String(payload.completedAt) : null,
  };
}

function asWorker(payload: Record<string, unknown>, fallback?: WorkerState): WorkerState {
  return {
    workerId: Number(payload.workerId ?? fallback?.workerId ?? 0),
    status: (payload.status as WorkerState["status"]) ?? fallback?.status ?? "idle",
    batchId: (payload.batchId as string | null) ?? null,
    taskName: (payload.taskName as string | null) ?? fallback?.taskName ?? null,
    messageCount: Number(payload.messageCount ?? fallback?.messageCount ?? 0),
  };
}

function asWorkerList(raw: unknown): WorkerState[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => asWorker((item ?? {}) as Record<string, unknown>));
}

const HITS_PAGE_SIZE = 40;
const HITS_SCROLL_EDGE = 280;
const FRESH_MS = 460;

const imageUrlCache = new WeakMap<HitImage, string>();

function stableImageUrl(image: HitImage) {
  const cached = imageUrlCache.get(image);
  if (cached) return cached;
  const url = `data:${image.mime};base64,${image.base64}`;
  imageUrlCache.set(image, url);
  return url;
}

function sameTags(a: Tag[], b: Tag[]) {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].id !== b[i].id || a[i].key !== b[i].key || a[i].label !== b[i].label || a[i].updatedAt !== b[i].updatedAt) return false;
  }
  return true;
}

function sameTasks(a: Task[], b: Task[]) {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    const left = a[i];
    const right = b[i];
    if (left.id !== right.id || left.name !== right.name || left.enabled !== right.enabled || left.updatedAt !== right.updatedAt) return false;
    if (left.priority !== right.priority || left.batchSize !== right.batchSize || left.hitThreshold !== right.hitThreshold) return false;
    if (left.pool.total !== right.pool.total || left.pool.analyzed !== right.pool.analyzed) return false;
    if ((left.usage?.calls ?? 0) !== (right.usage?.calls ?? 0) || (left.usage?.tokens ?? 0) !== (right.usage?.tokens ?? 0)) return false;
    if (left.channelIds.join("\0") !== right.channelIds.join("\0") || left.tagIds.join("\0") !== right.tagIds.join("\0")) return false;
  }
  return true;
}

function stageViewSame(current: StageSnapshot | null, next: StageSnapshot) {
  if (!current) return false;
  if (
    current.activeTasks !== next.activeTasks ||
    current.concurrency !== next.concurrency ||
    current.jevCalls !== next.jevCalls ||
    current.jevHits !== next.jevHits ||
    current.jevMisses !== next.jevMisses ||
    current.jevTokens !== next.jevTokens ||
    current.model !== next.model ||
    current.analysisBackend !== next.analysisBackend ||
    current.typesafeApiKeySet !== next.typesafeApiKeySet ||
    current.telegramStatus !== next.telegramStatus ||
    current.messageCount !== next.messageCount ||
    current.workers.length !== next.workers.length ||
    current.queue.length !== next.queue.length
  ) {
    return false;
  }
  for (let i = 0; i < current.workers.length; i += 1) {
    const left = current.workers[i];
    const right = next.workers[i];
    if (
      left.workerId !== right.workerId ||
      left.status !== right.status ||
      left.batchId !== right.batchId ||
      left.taskName !== right.taskName ||
      left.messageCount !== right.messageCount
    ) {
      return false;
    }
  }
  for (let i = 0; i < current.queue.length; i += 1) {
    const left = current.queue[i];
    const right = next.queue[i];
    if (left.id !== right.id || left.status !== right.status || left.messageCount !== right.messageCount || left.taskName !== right.taskName) {
      return false;
    }
  }
  return true;
}

type HitFilter = { query: string; taskId: string; category: string; minNoul: string };

type HitsView = {
  items: HitExtract[];
  total: number;
  hasMore: boolean;
  accounted: string[];
};

function categoryLabel(tags: Tag[], key?: string | null) {
  if (!key) return "other";
  if (key.toLowerCase() === "other") return "other";
  return tags.find((item) => item.key === key)?.label || key;
}

const CHIP_TONES: { color: string; background: string }[] = [
  { color: "#a5f3fc", background: "rgba(6, 182, 212, 0.28)" },
  { color: "#fde68a", background: "rgba(234, 179, 8, 0.28)" },
  { color: "#ddd6fe", background: "rgba(139, 92, 246, 0.32)" },
  { color: "#fecdd3", background: "rgba(244, 63, 94, 0.28)" },
  { color: "#fed7aa", background: "rgba(234, 88, 12, 0.3)" },
  { color: "#a7f3d0", background: "rgba(16, 185, 129, 0.28)" },
  { color: "#fbcfe8", background: "rgba(219, 39, 119, 0.3)" },
  { color: "#bfdbfe", background: "rgba(37, 99, 235, 0.32)" },
];

const TASK_TONES = ["#67e8f9", "#facc15", "#c4b5fd", "#fb7185", "#fb923c", "#34d399", "#f472b6", "#60a5fa"];

const HIT_GAP = 8;
const HIT_COL_MIN = 300;

function paletteIndex(seed: string, size: number) {
  let hash = 5381;
  for (let i = 0; i < seed.length; i += 1) hash = Math.imul(hash, 33) ^ seed.charCodeAt(i);
  return (hash >>> 0) % size;
}

function categoryTone(name: string): CSSProperties | undefined {
  const label = name.trim();
  if (!label || label.toLowerCase() === "other") return undefined;
  const tone = CHIP_TONES[paletteIndex(label, CHIP_TONES.length)];
  return { color: tone.color, background: tone.background };
}

function taskTone(taskId: string, taskName?: string | null) {
  const seed = taskId.trim() || (taskName ?? "").trim();
  if (!seed) return undefined;
  return TASK_TONES[paletteIndex(seed, TASK_TONES.length)];
}

function hitColumnCount(width: number) {
  if (width <= HIT_COL_MIN) return 1;
  return Math.max(1, Math.floor((width + HIT_GAP) / (HIT_COL_MIN + HIT_GAP)));
}

function packHitBricks(root: HTMLElement) {
  const width = root.clientWidth;
  if (width <= 0) return;
  const cards = Array.from(root.children).filter(
    (node): node is HTMLElement => node instanceof HTMLElement && node.classList.contains("result-card"),
  );
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
  cards.forEach((card, index) => {
    const col = index % cols;
    card.style.left = `${xs[col]}px`;
    card.style.width = `${ws[col]}px`;
    card.style.contentVisibility = "visible";
  });
  const heights = new Array<number>(cols).fill(0);
  const measured = cards.map((card) => card.offsetHeight);
  cards.forEach((card) => {
    card.style.contentVisibility = "";
  });
  cards.forEach((card, index) => {
    const col = index % cols;
    const y = heights[col];
    card.style.top = `${y}px`;
    card.style.height = `${measured[index]}px`;
    card.style.containIntrinsicSize = `${measured[index]}px`;
    heights[col] = y + measured[index] + HIT_GAP;
  });
  root.style.height = `${Math.max(0, Math.max(...heights) - HIT_GAP)}px`;
}

function minNoulValue(raw: string): number | null {
  const text = raw.trim().replace(",", ".");
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function hitMatches(item: HitExtract, filters: HitFilter) {
  if (!matchesQuery(filters.query, item.content, item.senderName, item.chatName)) return false;
  if (filters.taskId && item.taskId !== filters.taskId) return false;
  if (filters.category && (item.category || "") !== filters.category) return false;
  const min = minNoulValue(filters.minNoul);
  if (min != null && (item.noul ?? 0) < min) return false;
  return true;
}

function flyingHitIds(flights: Flight[], pending: HitExtract[]) {
  const ids = new Set<string>();
  for (const item of flights) {
    if (item.kind === "hit" && item.hit) ids.add(item.hit.id);
  }
  for (const card of pending) {
    if (card.id) ids.add(card.id);
  }
  return ids;
}

function dedupeHits(cards: HitExtract[]) {
  const seen = new Set<string>();
  const items: HitExtract[] = [];
  for (const card of cards) {
    if (!card.id || seen.has(card.id)) continue;
    seen.add(card.id);
    items.push(card);
  }
  return items;
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

type HitDayGroup = {
  key: string;
  items: HitExtract[];
};

function groupHitsByMessageDay(items: HitExtract[]): HitDayGroup[] {
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

function dayChipLabel(key: string, locale: Locale, todayLabel: string, yesterdayLabel: string, now: Date) {
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

export default function StagePage({ taskPanel }: { taskPanel: ReactNode }) {
  const reduceMotion = useReducedMotion();
  const resultsRef = useRef<HTMLElement | null>(null);
  const aiCoreRef = useRef<HTMLDivElement>(null);
  const queueNodes = useRef(new Map<string, HTMLDivElement>());
  const stageRef = useRef<StageSnapshot | null>(null);
  const claimedBatches = useRef(new Set<string>());
  const reduceMotionRef = useRef(false);
  const flightsRef = useRef<Flight[]>([]);
  const pendingHits = useRef<HitExtract[]>([]);
  const flyingCount = useRef(0);
  const landedIds = useRef(new Set<string>());
  const ingestBuf = useRef({ n: 0, last: "", pending: 0, timer: 0 });
  const liveEpoch = useRef(0);

  const [stage, setStage] = useState<StageSnapshot | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const tasksRef = useRef<Task[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  tasksRef.current = tasks;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<HitFilter>({ query: "", taskId: "", category: "", minNoul: "" });
  const [applied, setApplied] = useState<HitFilter>({ query: "", taskId: "", category: "", minNoul: "" });
  const [hitsView, setHitsView] = useState<HitsView>({ items: [], total: 0, hasMore: false, accounted: [] });
  const [hitsLoading, setHitsLoading] = useState(true);
  const [hitsLoadingMore, setHitsLoadingMore] = useState(false);
  const hitsScrollRef = useRef<HTMLDivElement | null>(null);
  const hitsCursorRef = useRef<string | null>(null);
  const hitsHasMoreRef = useRef(false);
  const hitsGenRef = useRef(0);
  const hitsBusyRef = useRef(false);
  const hitsMoreFailedRef = useRef(false);
  const appliedFiltersRef = useRef<HitFilter>(applied);
  const hitRowsRef = useRef<HitExtract[]>([]);
  const loadHitsRef = useRef<(mode: "replace" | "more") => Promise<void>>(async () => {});
  appliedFiltersRef.current = applied;
  hitRowsRef.current = hitsView.items;
  const [flights, setFlights] = useState<Flight[]>([]);
  const [sseStatus, setSseStatus] = useState<SseStatus>("connecting");
  const [ingest, setIngest] = useState({ count: 0, last: "" });
  const [lastErrorBatch, setLastErrorBatch] = useState<string | null>(null);
  const [batchErrorFading, setBatchErrorFading] = useState(false);
  const [batchErrorShownAt, setBatchErrorShownAt] = useState(0);
  const [impact, setImpact] = useState(0);
  const [freshIds, setFreshIds] = useState<Record<string, number>>({});
  const [handoffs, setHandoffs] = useState<QueueHandoff[]>([]);

  useEffect(() => {
    if (Object.keys(freshIds).length === 0) return;
    const timer = window.setTimeout(() => {
      const cutoff = Date.now() - FRESH_MS;
      setFreshIds((current) => {
        const next: Record<string, number> = {};
        for (const [id, at] of Object.entries(current)) {
          if (at >= cutoff) next[id] = at;
        }
        return Object.keys(next).length === Object.keys(current).length ? current : next;
      });
    }, FRESH_MS);
    return () => window.clearTimeout(timer);
  }, [freshIds]);

  flightsRef.current = flights;
  stageRef.current = stage;
  reduceMotionRef.current = Boolean(reduceMotion);

  useEffect(() => {
    if (handoffs.length === 0) return;
    const ids = new Set(handoffs.map((item) => item.id));
    const timer = window.setTimeout(() => {
      setHandoffs((current) => current.filter((item) => !ids.has(item.id)));
    }, 480);
    return () => window.clearTimeout(timer);
  }, [handoffs]);

  const placeResults = useCallback((cards: HitExtract[]) => {
    const filtersNow = appliedFiltersRef.current;
    const fresh = cards.filter((card) => card.id && hitMatches(card, filtersNow));
    if (!fresh.length) return;
    setFreshIds((current) => {
      const next = { ...current };
      for (const card of fresh) next[card.id] = Date.now();
      return next;
    });
    setHitsView((current) => {
      const seen = new Set(current.items.map((item) => item.id));
      const incoming = fresh.filter((card) => !seen.has(card.id));
      if (!incoming.length) return current;
      const accounted = new Set(current.accounted);
      let add = 0;
      for (const card of incoming) {
        if (accounted.has(card.id)) accounted.delete(card.id);
        else add += 1;
      }
      return {
        ...current,
        items: [...incoming, ...current.items],
        total: current.total + add,
        accounted: [...accounted],
      };
    });
  }, []);

  const launchOutcome = useCallback(
    (hits: HitExtract[], miss: BatchResult | null) => {
      if (miss) {
        const from = aiCoreRef.current?.getBoundingClientRect();
        if (!reduceMotion && from) {
          setFlights((current) => [
            ...current.filter((item) => item.id !== miss.id),
            { id: miss.id, kind: "miss", batch: miss, from },
          ]);
        }
      }
      const cards = hits.filter((card) => card.id);
      if (!cards.length) return;
      if (reduceMotion || !aiCoreRef.current) {
        placeResults(cards);
        return;
      }
      const room = Math.max(0, MAX_SIMULTANEOUS_FLIGHTS - flyingCount.current);
      const now = cards.slice(0, room);
      const queueRoom = Math.max(0, 8 - pendingHits.current.length);
      const queued = cards.slice(room, room + queueRoom);
      const overflow = cards.slice(room + queued.length);
      pendingHits.current.push(...queued);
      if (overflow.length) placeResults(overflow);
      if (!now.length) return;
      flyingCount.current += now.length;
      const from = aiCoreRef.current.getBoundingClientRect();
      const to = resultsRef.current?.getBoundingClientRect();
      setFlights((current) => [
        ...current,
        ...now.map((card) => ({ id: card.id, kind: "hit" as const, hit: card, from, to })),
      ]);
    },
    [placeResults, reduceMotion],
  );

  const batchErrorTimer = useRef(0);
  const batchErrorFadeTimer = useRef(0);
  const batchErrorGen = useRef(0);

  const revealBatchError = useCallback((message: string | null | undefined) => {
    const text = message?.trim() ? message.trim() : BATCH_FAIL;
    const gen = (batchErrorGen.current += 1);
    window.clearTimeout(batchErrorTimer.current);
    window.clearTimeout(batchErrorFadeTimer.current);
    setBatchErrorFading(false);
    setBatchErrorShownAt(Date.now());
    setLastErrorBatch(text);
    batchErrorTimer.current = window.setTimeout(() => {
      if (batchErrorGen.current !== gen) return;
      setBatchErrorFading(true);
      batchErrorFadeTimer.current = window.setTimeout(() => {
        if (batchErrorGen.current !== gen) return;
        setLastErrorBatch(null);
        setBatchErrorFading(false);
      }, reduceMotionRef.current ? 0 : 280);
    }, BATCH_ERROR_HIDE_MS);
  }, []);

  useEffect(() => () => {
    window.clearTimeout(batchErrorTimer.current);
    window.clearTimeout(batchErrorFadeTimer.current);
  }, []);

  const refresh = useCallback(async (quiet = false) => {
    try {
      let attempt = 0;
      while (attempt < 3) {
        const epoch = liveEpoch.current;
        const [snapshot, taskResp, tagResp] = await Promise.all([
          api.stage(),
          api.tasks().then(
            (body) => body,
            () => null,
          ),
          api.tags().catch(() => ({ tags: [] as Tag[] })),
        ]);
        if (taskResp) {
          if (!sameTasks(tasksRef.current, taskResp.tasks)) {
            tasksRef.current = taskResp.tasks;
            setTasks(taskResp.tasks);
            notifyTasksSnapshot(taskResp.tasks);
          }
        } else if (tasksRef.current.length > 0) {
          tasksRef.current = [];
          setTasks([]);
        }
        setTags((current) => (sameTags(current, tagResp.tags) ? current : tagResp.tags));
        if (liveEpoch.current !== epoch && attempt < 2) {
          attempt += 1;
          continue;
        }
        const extra = ingestBuf.current.pending;
        ingestBuf.current.pending = 0;
        setStage((current) => {
          const serverCount = snapshot.messageCount ?? 0;
          const optimistic = (current?.messageCount ?? 0) + extra;
          const next: StageSnapshot = {
            ...snapshot,
            concurrency: clampConcurrency(snapshot.concurrency ?? snapshot.workers.length ?? CONCURRENCY_DEFAULT),
            messageCount: extra > 0 ? Math.max(serverCount, optimistic) : serverCount,
            results: [],
          };
          return stageViewSame(current, next) ? current : next;
        });
        setError(null);
        break;
      }
    } catch (err) {
      if (!quiet) setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onTasks = () => void refresh(true);
    window.addEventListener(TASKS_CHANGED_EVENT, onTasks);
    window.addEventListener(SETTINGS_CHANGED_EVENT, onTasks);
    return () => {
      window.removeEventListener(TASKS_CHANGED_EVENT, onTasks);
      window.removeEventListener(SETTINGS_CHANGED_EVENT, onTasks);
    };
  }, [refresh]);

  useEffect(() => {
    const delay = sseStatus === "open" ? 25000 : 4000;
    const timer = window.setInterval(() => void refresh(true), delay);
    return () => window.clearInterval(timer);
  }, [refresh, sseStatus]);

  const openedOnce = useRef(false);
  useEffect(() => {
    if (sseStatus !== "open") return;
    if (!openedOnce.current) {
      openedOnce.current = true;
      return;
    }
    void refresh(true);
  }, [sseStatus, refresh]);

  const onEvent = useCallback(
    (event: SseEnvelope) => {
      if (event.type !== "ingest") liveEpoch.current += 1;
      const payload = event.payload;
      if (event.type === "workers_snapshot") {
        const workers = asWorkerList(payload.workers);
        for (const worker of workers) {
          if (isLiveBatch(worker) && worker.batchId) claimedBatches.current.add(worker.batchId);
        }
        const concurrency = clampConcurrency(Number(payload.concurrency ?? workers.length ?? CONCURRENCY_DEFAULT));
        setStage((current) => (current ? { ...current, workers, concurrency } : current));
        return;
      }
      if (event.type === "worker_update") {
        const next = asWorker(payload);
        if (next.batchId && (next.status === "packing" || next.status === "judging")) {
          claimedBatches.current.add(next.batchId);
        }
        setStage((current) => {
          if (!current) return current;
          const workers = current.workers.some((item) => item.workerId === next.workerId)
            ? current.workers.map((item) => (item.workerId === next.workerId ? { ...item, ...next } : item))
            : [...current.workers, next].sort((a, b) => a.workerId - b.workerId);
          return { ...current, workers };
        });
      }
      if (event.type === "queue_update") {
        const batch = asBatch(payload);
        setStage((current) => {
          if (!current) return current;
          if (current.queue.some((item) => item.id === batch.id)) return current;
          return { ...current, queue: [...current.queue, batch] };
        });
      }
      if (event.type === "queue_take") {
        const id = String(payload.id ?? "");
        const claimed = id ? claimedBatches.current.has(id) : false;
        if (id) claimedBatches.current.delete(id);
        const node = id ? queueNodes.current.get(id) : undefined;
        const core = aiCoreRef.current;
        if (claimed && !reduceMotionRef.current && node && core) {
          const from = node.getBoundingClientRect();
          const to = core.getBoundingClientRect();
          const batch = stageRef.current?.queue.find((item) => item.id === id);
          if (from.width > 0 && from.height > 0) {
            setHandoffs((current) => {
              if (current.some((item) => item.id === id)) return current;
              return [
                ...current,
                {
                  id,
                  taskName: batch?.taskName || "",
                  messageCount: batch?.messageCount ?? 0,
                  x: from.left,
                  y: from.top,
                  dx: to.left + to.width / 2 - (from.left + from.width / 2),
                  dy: to.top + to.height / 2 - (from.top + from.height / 2),
                  width: from.width,
                },
              ];
            });
          }
        }
        setStage((current) => (current ? { ...current, queue: current.queue.filter((item) => item.id !== id) } : current));
      }
      if (event.type === "telegram_status") {
        const status = String(payload.status ?? "");
        setStage((current) => (current && status ? { ...current, telegramStatus: status as StageSnapshot["telegramStatus"] } : current));
      }
      if (event.type === "ingest") {
        ingestBuf.current.n += 1;
        ingestBuf.current.pending += 1;
        ingestBuf.current.last = String(payload.chatName ?? "");
        if (!ingestBuf.current.timer) {
          ingestBuf.current.timer = window.setTimeout(() => {
            const add = ingestBuf.current.pending;
            ingestBuf.current.pending = 0;
            ingestBuf.current.timer = 0;
            setIngest({ count: ingestBuf.current.n, last: ingestBuf.current.last });
            if (add > 0) {
              setStage((current) =>
                current ? { ...current, messageCount: (current.messageCount ?? 0) + add } : current,
              );
            }
          }, 180);
        }
      }
      if (event.type === "batch_error") {
        const batch = asBatch(payload);
        revealBatchError(batch.errorMessage);
        setStage((current) =>
          current ? { ...current, queue: current.queue.filter((item) => item.id !== batch.id) } : current,
        );
      }
      if (event.type === "batch_hit" || event.type === "batch_miss") {
        const batch = asBatch(payload);
        const hit = event.type === "batch_hit";
        setStage((current) =>
          current
            ? {
                ...current,
                queue: current.queue.filter((item) => item.id !== batch.id),
                jevHits: current.jevHits + (hit ? 1 : 0),
                jevMisses: current.jevMisses + (hit ? 0 : 1),
                jevCalls: current.jevCalls + 1,
              }
            : current,
        );
        const cards =
          hit && Array.isArray(payload.hits)
            ? payload.hits.map(asHit).filter((card) => card.id && hitMatches(card, appliedFiltersRef.current))
            : [];
        launchOutcome(cards, hit ? null : batch);
      }
    },
    [launchOutcome, revealBatchError],
  );
  useSse(onEvent, setSseStatus);

  const loadHits = useCallback(async (mode: "replace" | "more") => {
    if (mode === "more" && (hitsBusyRef.current || !hitsHasMoreRef.current || !hitsCursorRef.current)) return;
    const gen = mode === "replace" ? (hitsGenRef.current += 1) : hitsGenRef.current;
    const cursor = mode === "more" ? hitsCursorRef.current : null;
    if (mode === "replace") {
      hitsCursorRef.current = null;
      hitsHasMoreRef.current = false;
    }
    hitsBusyRef.current = true;
    const filtersNow = appliedFiltersRef.current;
    const baselineIds = new Set(hitRowsRef.current.map((item) => item.id));
    if (mode === "replace") {
      setHitsLoading(true);
      setHitsView((current) => ({ ...current, items: [], hasMore: false }));
    } else {
      setHitsLoadingMore(true);
    }
    try {
      const page = await api.results({
        limit: HITS_PAGE_SIZE,
        cursor: cursor ?? undefined,
        q: filtersNow.query,
        taskId: filtersNow.taskId,
        category: filtersNow.category,
        minNoul: filtersNow.minNoul,
      });
      if (hitsGenRef.current !== gen) return;
      const hidden = flyingHitIds(flightsRef.current, pendingHits.current);
      const pageItems = page.items.map((item) => asHit(item));
      let hasMore = Boolean(page.hasMore && page.nextCursor);
      if (mode === "more") {
        const seen = new Set(hitRowsRef.current.map((item) => item.id));
        const incoming = pageItems.filter((item) => item.id && !seen.has(item.id) && !hidden.has(item.id));
        if (!incoming.length) hasMore = false;
      }
      if (!pageItems.length) hasMore = false;
      hitsMoreFailedRef.current = false;
      hitsCursorRef.current = hasMore ? page.nextCursor : null;
      hitsHasMoreRef.current = hasMore;
      if (mode === "replace") {
        setHitsView((current) => {
          const pageIds = new Set(pageItems.map((item) => item.id));
          const arrived = current.items.filter((item) => item.id && !baselineIds.has(item.id) && hitMatches(item, filtersNow));
          const prepend = arrived.filter((item) => !pageIds.has(item.id) && !hidden.has(item.id));
          const visible = pageItems.filter((item) => item.id && !hidden.has(item.id));
          return {
            items: dedupeHits([...prepend, ...visible]),
            total: page.total + prepend.length,
            hasMore,
            accounted: pageItems.filter((item) => hidden.has(item.id)).map((item) => item.id),
          };
        });
      } else {
        setHitsView((current) => {
          const seen = new Set(current.items.map((item) => item.id));
          const incoming = pageItems.filter((item) => item.id && !seen.has(item.id) && !hidden.has(item.id));
          return {
            ...current,
            items: [...current.items, ...incoming],
            hasMore,
            accounted: [
              ...current.accounted,
              ...pageItems.filter((item) => hidden.has(item.id) && !current.accounted.includes(item.id)).map((item) => item.id),
            ],
          };
        });
      }
    } catch (err) {
      if (hitsGenRef.current !== gen) return;
      if (mode === "more") hitsMoreFailedRef.current = true;
      setError(errorText(err));
    } finally {
      if (hitsGenRef.current === gen) {
        hitsBusyRef.current = false;
        setHitsLoading(false);
        setHitsLoadingMore(false);
      }
    }
  }, []);

  loadHitsRef.current = loadHits;

  useEffect(() => {
    const textChanged = filters.query !== applied.query || filters.minNoul !== applied.minNoul;
    const selectChanged = filters.taskId !== applied.taskId || filters.category !== applied.category;
    if (!textChanged && !selectChanged) return;
    const timer = window.setTimeout(() => setApplied(filters), textChanged ? 280 : 0);
    return () => window.clearTimeout(timer);
  }, [filters, applied]);

  const appliedKey = `${applied.query}\0${applied.taskId}\0${applied.category}\0${applied.minNoul}`;
  useEffect(() => {
    hitsScrollRef.current?.scrollTo({ top: 0 });
    void loadHitsRef.current("replace");
  }, [appliedKey]);

  useEffect(() => {
    const el = hitsScrollRef.current;
    if (!el || hitsLoading || hitsLoadingMore || !hitsView.hasMore || hitsMoreFailedRef.current) return;
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (gap > HITS_SCROLL_EDGE) return;
    void loadHitsRef.current("more");
  }, [hitsView.items, hitsView.hasMore, hitsLoading, hitsLoadingMore]);

  const onHitsScroll = useCallback(() => {
    const el = hitsScrollRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight > HITS_SCROLL_EDGE) return;
    hitsMoreFailedRef.current = false;
    void loadHitsRef.current("more");
  }, []);

  const categories = useMemo(() => {
    const map = new Map<string, string>();
    for (const tag of tags) map.set(tag.key, tag.label);
    for (const item of hitsView.items) {
      if (item.category && !map.has(item.category)) {
        map.set(item.category, categoryLabel(tags, item.category));
      }
    }
    return [...map.entries()];
  }, [hitsView.items, tags]);

  function landHit(flight: Flight) {
    if (landedIds.current.has(flight.id)) return;
    landedIds.current.add(flight.id);
    setFlights((current) => current.filter((item) => item.id !== flight.id));
    if (flight.kind !== "hit" || !flight.hit) return;
    flyingCount.current = Math.max(0, flyingCount.current - 1);
    setImpact((value) => value + 1);
    placeResults([flight.hit]);
    const next = pendingHits.current.shift();
    if (!next) return;
    const from = aiCoreRef.current?.getBoundingClientRect();
    if (!from) {
      const rest = pendingHits.current.splice(0);
      placeResults([next, ...rest]);
      return;
    }
    flyingCount.current += 1;
    const to = resultsRef.current?.getBoundingClientRect();
    setFlights((current) => [...current, { id: next.id, kind: "hit", hit: next, from, to }]);
  }

  const workers = stage?.workers ?? [];
  const concurrency = clampConcurrency(stage?.concurrency ?? (workers.length || CONCURRENCY_DEFAULT));
  const queue = stage?.queue ?? [];
  const jobs = workers.filter((item) => item.status === "packing" || item.status === "judging" || item.status === "error");
  const queuedIds = new Set(queue.map((item) => item.id));
  const handoffIds = new Set(handoffs.map((item) => item.id));
  const shownJobs = jobs.filter((job) => !job.batchId || (!queuedIds.has(job.batchId) && !handoffIds.has(job.batchId)));
  const busy = jobs.filter((item) => item.status === "packing" || item.status === "judging").length;
  const load = Math.min(1, busy / Math.max(1, concurrency));
  const judging = jobs.some((item) => item.status === "judging");
  const packing = jobs.some((item) => item.status === "packing");
  const aiMode = judging ? "is-judging" : packing ? "is-packing" : jobs.some((item) => item.status === "error") ? "is-error" : "is-idle";
  const storedMessages = stage?.messageCount ?? 0;
  const { m, locale } = useI18n();
  const engineLaya = stage?.analysisBackend === "laya";
  const engineLabel = engineLaya ? m.stage.engineLaya : m.stage.engineJev;
  const batchError = lastErrorBatch === BATCH_FAIL ? m.stage.batchFail : lastErrorBatch;

  return (
    <div className="stage-root">
      <div className="stage-metrics" aria-label={m.stage.aria}>
          <span>
            {m.stage.tasks} <strong>{stage?.activeTasks ?? 0}</strong>
          </span>
          <span>
            {m.stage.parallel} <strong>{loading && !stage ? "…" : `${busy}/${concurrency}`}</strong>
          </span>
          <span>
            {engineLabel} <strong>{stage?.jevCalls ?? 0}</strong>
          </span>
          {!engineLaya && stage?.model ? (
            <span title={m.stage.modelTitle}>{stage.model}</span>
          ) : null}
          <span>
            {m.stage.hits} <strong>{stage?.jevHits ?? 0}</strong> / {m.stage.misses} <strong>{stage?.jevMisses ?? 0}</strong>
          </span>
          <span title={m.stage.inboxTitle}>
            {m.stage.inbox} <strong>{loading && !stage ? "…" : `${storedMessages} (${ingest.count})`}</strong>
          </span>
          {loading ? <span>{m.stage.loading}</span> : null}
          {!loading && stage && stage.analysisBackend !== "laya" && !stage.typesafeApiKeySet ? (
            <StatusWarn href="#settings" link={m.stage.viewSettings}>
              {m.stage.needKey}
            </StatusWarn>
          ) : null}
          {!loading && stage && stage.telegramStatus !== "connected" ? (
            <StatusWarn href="#telegram" link={m.stage.viewTelegram}>
              {m.stage.needTelegram}
            </StatusWarn>
          ) : null}
          <span className="stage-metrics-end">
            <ConnectionStatus sse={sseStatus} telegram={stage?.telegramStatus ?? null} />
            <BillingChip />
            <AnalysisToggle />
            <span className="shell-actions" role="group" aria-label={m.stage.shellAria}>
              <button type="button" className="icon-btn" aria-label={m.stage.telegram} title={m.stage.telegram} onClick={() => openShellDialog("telegram")}>
                <TelegramMark />
              </button>
              <button type="button" className="icon-btn" aria-label={m.stage.settings} title={m.stage.settings} onClick={() => openShellDialog("settings")}>
                <SettingsMark />
              </button>
              <button type="button" className="icon-btn" aria-label={m.stage.tags} title={m.stage.tags} onClick={() => openShellDialog("tags")}>
                <TagsMark />
              </button>
            </span>
            <LanguageSwitch />
          </span>
      </div>

      {error || lastErrorBatch ? (
        <div className="toast-stack">
          {error ? (
            <p role="alert" className="holo-toast border-rose/40 text-rose">
              {error}
            </p>
          ) : null}
          {batchError ? (
            <motion.p
              role="status"
              data-batch-error=""
              data-revealed-at={batchErrorShownAt || undefined}
              className="holo-toast border-amber/30 text-amber"
              animate={{ opacity: batchErrorFading && !reduceMotion ? 0 : 1 }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.28, ease: "easeOut" }}
            >
              {m.stage.recentBatch(batchError)}
            </motion.p>
          ) : null}
        </div>
      ) : null}

      <div className="console">
        <div className="console-rail">
        <section className="holo-frame" aria-labelledby="worker-heading">
          <div className="column-head">
            <h2 id="worker-heading">{engineLabel}</h2>
            <span className="engine-head-meta">
              <PanelLink id="settings" className="engine-tune">
                {m.stage.adjustParallel}
              </PanelLink>
              <span className="count-badge">{m.stage.parallelBadge(busy, concurrency)}</span>
            </span>
          </div>
          <div className="engine-face">
            <AiPresence
              coreRef={aiCoreRef}
              mode={aiMode}
              load={load}
              busy={busy}
              concurrency={concurrency}
              engineLabel={engineLabel}
            />
          </div>
          <div className="column-scroll engine-batches" aria-label={m.stage.queue}>
            <AnimatePresence initial={false}>
              {shownJobs.map((job) => (
                <motion.article
                  key={job.batchId ?? `worker-${job.workerId}`}
                  className={`queue-card is-${job.status}`}
                  initial={false}
                  animate={{ opacity: 1 }}
                  exit={reduceMotion ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, transition: ROW_FADE }}
                >
                  <p className="truncate text-[13px] font-medium">{job.taskName || m.stage.batch}</p>
                  <p className="font-mono text-xs text-cyan">
                    {m.stage.workerStatus[job.status]}
                    {job.messageCount ? m.stage.jobCount(job.messageCount) : ""}
                  </p>
                </motion.article>
              ))}
              {queue.map((item) => (
                <motion.div
                  key={item.id}
                  ref={(node) => {
                    if (node) queueNodes.current.set(item.id, node);
                    else queueNodes.current.delete(item.id);
                  }}
                  className="queue-card"
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, transition: { duration: 0 } }}
                  transition={SNAP}
                >
                  <p className="truncate text-[13px] font-medium">{item.taskName || m.stage.unnamedTask}</p>
                  <p className="font-mono text-xs text-cyan">{m.stage.queued(item.messageCount)}</p>
                </motion.div>
              ))}
            </AnimatePresence>
            {queue.length === 0 && handoffs.length === 0 ? <p className="engine-queue-empty">{m.stage.queueEmpty}</p> : null}
          </div>
        </section>
        <div id="tasks" className="rail-cell module-anchor">
          {taskPanel}
        </div>
        </div>

        <aside ref={resultsRef} className="holo-frame well-frame console-hits" aria-labelledby="results-heading">
          {impact > 0 && !reduceMotion ? <div key={impact} className="well-flash" /> : null}
          <div className="column-head">
            <h2 id="results-heading">{m.stage.results}</h2>
            <span className="count-badge">{hitsLoading && hitsView.items.length === 0 ? "…" : hitsView.total}</span>
          </div>
          <div className="hits-toolbar" role="search" aria-label={m.stage.filterAria}>
            <SearchBox
              label={m.stage.searchLabel}
              placeholder={m.stage.searchPlaceholder}
              value={filters.query}
              onChange={(query) => setFilters((current) => ({ ...current, query }))}
            />
            <label className="sr-only" htmlFor="filter-task">
              {m.stage.filterTask}
            </label>
            <select
              id="filter-task"
              className="field-input"
              value={filters.taskId}
              onChange={(event) => setFilters((current) => ({ ...current, taskId: event.target.value }))}
            >
              <option value="">{m.stage.allTasks}</option>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.name}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="filter-cat">
              {m.stage.filterCategory}
            </label>
            <select
              id="filter-cat"
              className="field-input"
              value={filters.category}
              onChange={(event) => setFilters((current) => ({ ...current, category: event.target.value }))}
            >
              <option value="">{m.stage.allCategories}</option>
              {categories.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="filter-noul">
              {m.stage.minNoul}
            </label>
            <input
              id="filter-noul"
              className="field-input hits-noul"
              placeholder="noul ≥"
              inputMode="decimal"
              value={filters.minNoul}
              onChange={(event) => setFilters((current) => ({ ...current, minNoul: event.target.value }))}
            />
          </div>
          <HitsPane
            items={hitsView.items}
            loading={hitsLoading}
            loadingMore={hitsLoadingMore}
            freshIds={freshIds}
            tags={tags}
            locale={locale}
            scrollRef={hitsScrollRef}
            onScroll={onHitsScroll}
          />
        </aside>
      </div>

      <AnimatePresence>
        {handoffs.map((item) => (
          <motion.div
            key={item.id}
            className="queue-card queue-handoff"
            style={{ width: item.width }}
            initial={{ x: item.x, y: item.y, opacity: 1 }}
            animate={{ x: item.x + item.dx, y: item.y + item.dy, opacity: 0 }}
            transition={HANDOFF}
            onAnimationComplete={() => setHandoffs((current) => current.filter((row) => row.id !== item.id))}
          >
            <p className="truncate text-[13px] font-medium">{item.taskName || m.stage.unnamedTask}</p>
            <p className="font-mono text-xs text-cyan">{m.stage.queued(item.messageCount)}</p>
          </motion.div>
        ))}
        {flights.map((flight) =>
          flight.kind === "hit" && flight.hit ? (
            <motion.div
              key={`hit-${flight.id}`}
              className="hit-packet pointer-events-none fixed top-0 left-0 z-50 w-52 rounded-lg border border-lime/40 bg-raised/95 p-2.5"
              initial={{ x: flight.from.left + flight.from.width / 2 - 104, y: flight.from.top, opacity: 1, scale: 0.96 }}
              animate={{
                x: (flight.to?.left ?? flight.from.left) + 12,
                y: (flight.to?.top ?? flight.from.top) + 36,
                opacity: 1,
                scale: 1,
              }}
              exit={{ opacity: 0, transition: { type: "tween", duration: 0.08, ease: "easeOut" } }}
              transition={HIT_FLY}
              onAnimationComplete={() => landHit(flight)}
            >
              <p className="text-[11px] text-lime">{m.stage.hit}</p>
              <p className="truncate text-sm font-medium">{flight.hit.taskName}</p>
              <p className="truncate text-xs text-slate-300">{flight.hit.content || m.stage.noText}</p>
              <p className="font-mono text-xs">noul {pct(flight.hit.noul)}</p>
            </motion.div>
          ) : flight.kind === "miss" && flight.batch ? (
            <MissBurst key={`miss-${flight.id}`} flight={flight} onDone={() => setFlights((current) => current.filter((item) => item.id !== flight.id))} />
          ) : null,
        )}
      </AnimatePresence>
    </div>
  );
}

function StatusWarn({ href, link, children }: { href: string; link: string; children: string }) {
  const id = href.replace(/^#/, "");

  return (
    <span className="status-warn">
      <span className="status-warn-text" title={children}>
        {children}
      </span>
      <PanelLink id={id}>{link}</PanelLink>
    </span>
  );
}

function MissBurst({ flight, onDone }: { flight: Flight; onDone: () => void }) {
  const { m } = useI18n();
  return (
    <motion.div
      className="pointer-events-none fixed z-40 w-52 rounded-lg border border-rose/30 bg-raised/90 p-2.5"
      style={{ top: 0, left: 0 }}
      initial={{ x: flight.from.left + flight.from.width / 2 - 104, y: flight.from.top, opacity: 1, scale: 1 }}
      animate={{ opacity: 0, y: flight.from.top + 6, scale: 0.98 }}
      transition={MISS_FADE}
      onAnimationComplete={onDone}
    >
      <p className="text-[11px] text-rose">{m.stage.miss}</p>
      <p className="text-sm">{flight.batch?.taskName}</p>
    </motion.div>
  );
}

const AiPresence = memo(function AiPresence({
  coreRef,
  mode,
  load,
  busy,
  concurrency,
  engineLabel,
}: {
  coreRef: RefObject<HTMLDivElement>;
  mode: string;
  load: number;
  busy: number;
  concurrency: number;
  engineLabel: string;
}) {
  const { m } = useI18n();
  const statusKey = mode.replace("is-", "");
  const status =
    statusKey === "idle" || statusKey === "packing" || statusKey === "judging" || statusKey === "done" || statusKey === "error"
      ? m.stage.workerStatus[statusKey]
      : busy
        ? m.stage.running
        : m.stage.idle;
  return (
    <div className={`ai-presence ${mode}`} style={{ "--ai-load": String(load) } as CSSProperties}>
      <div className="ai-core-wrap">
        <div
          ref={coreRef}
          className="ai-core"
          aria-live="polite"
          aria-label={m.stage.aiAria(engineLabel, status, busy, concurrency)}
        >
          <span className="ai-core-glow" aria-hidden="true" />
          <span className="ai-core-ring" aria-hidden="true" />
          <span className="ai-core-pupil" aria-hidden="true" />
        </div>
      </div>
      <div className="ai-side">
        <p className="ai-core-caption">{busy ? m.stage.running : m.stage.standby}</p>
        <p className="ai-meter-label">
          {m.stage.parallelMeter} <strong>{busy}</strong>/{concurrency}
        </p>
        <div className="ai-meter" aria-hidden="true">
          <div className="ai-meter-fill" style={{ transform: `scaleX(${load})` }} />
        </div>
      </div>
    </div>
  );
});

type HitPreview = {
  urls: string[];
  index: number;
  label: string;
};

function HitLightbox({
  preview,
  onClose,
  onIndex,
}: {
  preview: HitPreview;
  onClose: () => void;
  onIndex: (index: number) => void;
}) {
  const { m } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const onIndexRef = useRef(onIndex);
  onCloseRef.current = onClose;
  onIndexRef.current = onIndex;
  const count = preview.urls.length;
  const index = count ? Math.min(Math.max(preview.index, 0), count - 1) : 0;
  const multiple = count > 1;
  const indexRef = useRef(index);
  const countRef = useRef(count);
  indexRef.current = index;
  countRef.current = count;

  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        const total = countRef.current;
        if (total < 2) return;
        event.preventDefault();
        const next = event.key === "ArrowLeft" ? indexRef.current - 1 : indexRef.current + 1;
        if (next >= 0 && next < total) onIndexRef.current(next);
        return;
      }
      if (event.key !== "Tab") return;
      const root = rootRef.current;
      if (!root) return;
      const items = Array.from(root.querySelectorAll<HTMLElement>("button:not([disabled])"));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = active instanceof Node && root.contains(active);
      if (event.shiftKey) {
        if (active === first || !inside) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !inside) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    const active = document.activeElement;
    if (!(active instanceof HTMLButtonElement) || !root?.contains(active) || !active.disabled) return;
    closeRef.current?.focus({ preventScroll: true });
  }, [index]);

  const src = preview.urls[index];
  if (!src) return null;

  return createPortal(
    <div
      ref={rootRef}
      className="hit-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={m.stage.imageViewer}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCloseRef.current();
      }}
    >
      {multiple ? (
        <button
          type="button"
          className="dialog-close hit-lightbox-nav is-prev"
          onClick={() => onIndex(index - 1)}
          disabled={index <= 0}
        >
          {m.stage.prevImage}
        </button>
      ) : null}
      <img className="hit-lightbox-img" src={src} alt={preview.label} />
      {multiple ? (
        <button
          type="button"
          className="dialog-close hit-lightbox-nav is-next"
          onClick={() => onIndex(index + 1)}
          disabled={index >= count - 1}
        >
          {m.stage.nextImage}
        </button>
      ) : null}
      <button ref={closeRef} type="button" className="dialog-close hit-lightbox-close" onClick={() => onCloseRef.current()}>
        {m.close}
      </button>
    </div>,
    document.body,
  );
}

const ResultCard = memo(function ResultCard({
  hit,
  fresh,
  categoryText,
  locale,
  onOpenImage,
}: {
  hit: HitExtract;
  fresh: boolean;
  categoryText: string;
  locale: Locale;
  onOpenImage: (urls: string[], index: number, label: string, trigger: HTMLElement) => void;
}) {
  const m = messages[locale];
  const images = hit.images ?? [];
  const sender = hit.senderName || m.stage.unknownSender;
  const title = hit.taskName || m.stage.taskFallback;
  const titleColor = taskTone(hit.taskId, hit.taskName);
  return (
    <article className={`result-card${fresh ? " is-fresh" : ""}`}>
      {images.length ? (
        <div className="hit-media">
          {images.map((image, index) => (
            <button
              key={`${hit.id}-${index}`}
              type="button"
              className="hit-media-btn"
              aria-label={m.stage.enlargeImage}
              onClick={(event) => onOpenImage(images.map((item) => stableImageUrl(item)), index, title, event.currentTarget)}
            >
              <img src={stableImageUrl(image)} alt="" width={320} height={160} decoding="async" loading="lazy" />
            </button>
          ))}
        </div>
      ) : null}
      <div className="hit-body">
        <div className="hit-head">
          <p className="hit-title" style={titleColor ? { color: titleColor } : undefined} title={title}>
            {title}
          </p>
          <span className="hit-cat" style={categoryTone(categoryText)} title={categoryText}>
            {categoryText}
          </span>
        </div>
        <p className="hit-meta">
          <span>{sender}</span>
          <span className="hit-quiet">{formatWhen(hit.timestamp, false)}</span>
          <span className="hit-noul font-mono text-cyan">noul {pct(hit.noul)}</span>
          <span className="hit-quiet">{m.stage.thisBatch(hit.hitCount ?? "—", hit.messageCount ?? "—")}</span>
        </p>
        {hit.chatName ? <p className="hit-chat">{hit.chatName}</p> : null}
        <p className="hit-text">{hit.content || m.stage.noText}</p>
      </div>
    </article>
  );
});

const HitsPane = memo(function HitsPane({
  items,
  loading,
  loadingMore,
  freshIds,
  tags,
  locale,
  scrollRef,
  onScroll,
}: {
  items: HitExtract[];
  loading: boolean;
  loadingMore: boolean;
  freshIds: Record<string, number>;
  tags: Tag[];
  locale: Locale;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  onScroll: () => void;
}) {
  const m = messages[locale];
  const groups = useMemo(() => groupHitsByMessageDay(items), [items]);
  const [dayClock, setDayClock] = useState(() => Date.now());
  const previewTrigger = useRef<HTMLElement | null>(null);
  const [preview, setPreview] = useState<HitPreview | null>(null);
  const openHitImage = useCallback((urls: string[], index: number, label: string, trigger: HTMLElement) => {
    if (!urls.length) return;
    previewTrigger.current = trigger;
    setPreview({ urls, index, label });
  }, []);
  const closeHitImage = useCallback(() => {
    const trigger = previewTrigger.current;
    previewTrigger.current = null;
    setPreview(null);
    requestAnimationFrame(() => {
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    });
  }, []);
  const moveHitImage = useCallback((index: number) => {
    setPreview((current) => (current ? { ...current, index } : current));
  }, []);
  useEffect(() => {
    const current = new Date(dayClock);
    const nextMidnight = new Date(current.getFullYear(), current.getMonth(), current.getDate() + 1, 0, 0, 1);
    const timer = window.setTimeout(() => setDayClock(Date.now()), Math.max(1000, nextMidnight.getTime() - Date.now()));
    return () => window.clearTimeout(timer);
  }, [dayClock]);
  useLayoutEffect(() => {
    const host = scrollRef.current;
    if (!host) return;
    let lastWidth = -1;
    const pack = () => {
      host.querySelectorAll<HTMLElement>(".hit-grid").forEach((grid) => packHitBricks(grid));
      lastWidth = host.clientWidth;
    };
    pack();
    const observer = new ResizeObserver(() => {
      if (Math.abs(host.clientWidth - lastWidth) < 1) return;
      pack();
    });
    observer.observe(host);
    let cancelFonts = false;
    const fonts = document.fonts;
    void fonts.ready.then(() => {
      if (cancelFonts || scrollRef.current !== host) return;
      pack();
    });
    return () => {
      cancelFonts = true;
      observer.disconnect();
    };
  }, [items, locale, scrollRef]);
  const now = new Date(dayClock);
  return (
    <>
      <div ref={scrollRef} className="column-scroll hits-scroll" onScroll={onScroll}>
        {items.length === 0 ? (
          loading ? (
            <p className="hit-more" role="status">
              {m.stage.loading}
            </p>
          ) : (
            <p className="hit-empty px-2 py-6 text-center text-[13px] leading-relaxed text-slate-500">{m.stage.emptyHits}</p>
          )
        ) : (
          <div className="hit-days">
            {groups.map((group) => {
              const label = dayChipLabel(group.key, locale, m.stage.dayToday, m.stage.dayYesterday, now);
              return (
                <section key={group.key || "undated"} className="hit-day">
                  {label ? (
                    <p className="hit-day-chip">
                      <span>{label}</span>
                    </p>
                  ) : null}
                  <div className="hit-grid">
                    {group.items.map((item) => (
                      <ResultCard
                        key={item.id}
                        hit={item}
                        fresh={freshIds[item.id] != null}
                        categoryText={categoryLabel(tags, item.category)}
                        locale={locale}
                        onOpenImage={openHitImage}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
        {loadingMore ? (
          <p className="hit-more" role="status">
            {m.stage.loadingMore}
          </p>
        ) : null}
      </div>
      {preview ? <HitLightbox preview={preview} onClose={closeHitImage} onIndex={moveHitImage} /> : null}
    </>
  );
});

function TelegramMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M21.6 4.4 2.9 11.4c-1.1.4-1.1 1.1-.2 1.4l4.7 1.5 1.8 5.5c.2.6.1.9.8.9.4 0 .6-.2.9-.4l2.5-2.4 5.3 3.9c.9.6 1.6.3 1.9-.9l3.4-15.7c.4-1.4-.5-2-1.4-1.8ZM8.8 13.8l9.9-6.2c.5-.3.9-.1.5.3l-8.1 7.3-.3 3.2-2-4.6Z"
      />
    </svg>
  );
}

function SettingsMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.2v2.2M12 18.6V21M4.8 6.2l1.6 1.6M17.6 16.2l1.6 1.6M3.2 12h2.2M18.6 12H21M4.8 17.8l1.6-1.6M17.6 7.8l1.6-1.6" />
    </svg>
  );
}

function TagsMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 12.2V5.2h7l9 9-7 7-9-9Z" />
      <circle cx="8.2" cy="8.6" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}
