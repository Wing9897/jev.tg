type WorkerStatus = "idle" | "packing" | "judging" | "done" | "error";

type TelegramStep = "disconnected" | "connecting" | "code_required" | "qr_required" | "2fa_required" | "connected" | "error";

export interface WorkerState {
  workerId: number;
  status: WorkerStatus;
  batchId: string | null;
  taskName: string | null;
  messageCount: number;
}

export interface Tag {
  id: string;
  key: string;
  label: string;
  description: string;
  createdAt: string;
  updatedAt: string;
}

export interface Task {
  id: string;
  name: string;
  prompt: string;
  batchSize: number;
  hitThreshold: number;
  tagIds: string[];
  tags: Tag[];
  channelIds: string[];
  enabled: boolean;
  priority: number;
  createdAt: string;
  updatedAt: string;
  pool: { total: number; analyzed: number };
  usage?: TaskUsage;
}

interface TaskUsage {
  calls: number;
  inputTokens: number;
  outputTokens: number;
  tokens: number;
  spendUsd: number;
  usdKind: UsdKind;
}

export interface HitImage {
  mime: string;
  base64: string;
}

export interface HitExtract {
  id: string;
  batchId: string;
  messageId: string;
  taskId: string;
  taskName?: string | null;
  status: "hit";
  noul?: number | null;
  category?: string | null;
  categoryConfidence?: number | null;
  chatName?: string | null;
  senderName?: string | null;
  content?: string | null;
  timestamp?: string | null;
  ordinal?: number | null;
  images?: HitImage[];
  hitCount?: number | null;
  messageCount?: number | null;
  createdAt?: string;
  updatedAt?: string;
  completedAt?: string | null;
}

export interface BatchResult {
  id: string;
  taskId: string;
  taskName?: string | null;
  status: "queued" | "running" | "hit" | "miss" | "error";
  messageCount: number;
  hitCount?: number | null;
  noul?: number | null;
  confidence?: number | null;
  category?: string | null;
  categoryConfidence?: number | null;
  errorMessage?: string | null;
  timeStart?: string | null;
  timeEnd?: string | null;
  workerId?: number | null;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
}

export interface Channel {
  platformId: string;
  name: string;
  subscribed: boolean;
}

export interface TelegramStatus {
  id: string;
  name: string;
  status: TelegramStep;
  phone?: string | null;
  apiId?: number | null;
  hasApiHash: boolean;
  lastError?: string | null;
  lastConnectedAt?: string | null;
  sessionFile: string;
}

export interface Settings {
  typesafeApiKeySet: boolean;
  model: string;
  concurrency: number;
  dataDir: string;
  jevCalls: number;
  jevHits: number;
  jevMisses: number;
  jevTokens: number;
  inputUsdPerMtok: number;
  outputUsdPerMtok: number;
  lowCreditsThreshold: number;
  analysisMaxAgeDays: number;
  analysisBackend: "jev" | "laya";
  analysisPaused: boolean;
  lastCreditsRemaining?: number | null;
  lastCreditsAt?: string | null;
  updatedAt: string;
}

export type UsdKind = "none" | "actual" | "estimate" | "mixed";

interface BillingWindow {
  calls: number;
  successCalls: number;
  errorCalls: number;
  inputTokens: number;
  outputTokens: number;
  tokens: number;
  usd: number;
  usdActual: number;
  usdEstimated: number;
  usdKind: UsdKind;
}

export interface BillingSummary {
  today: BillingWindow;
  sevenDays: BillingWindow;
  allTime: BillingWindow;
  lastCreditsRemaining: number | null;
  lastCreditsAt: string | null;
  insufficientCredits: boolean;
  lowBalance: boolean;
  lastInsufficientAt: string | null;
  lastInsufficientMessage: string | null;
  analysisBackend: "jev" | "laya";
  rates: {
    inputUsdPerMtok: number;
    outputUsdPerMtok: number;
    note: string;
  };
  hud: {
    todayUsd: number;
    todayUsdKind: UsdKind;
    todayTokens: number;
    allTimeUsd: number;
    allTimeUsdKind: UsdKind;
    lastCreditsRemaining: number | null;
    insufficientCredits: boolean;
    lowBalance: boolean;
  };
}

export interface BillingUsageRow {
  id: string;
  createdAt: string;
  taskId?: string | null;
  batchId?: string | null;
  model?: string | null;
  backend?: string | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
  tokens?: number | null;
  costUsd?: number | null;
  estimatedCostUsd?: number | null;
  spendUsd?: number | null;
  usdKind: UsdKind;
  success: boolean;
  errorCode?: string | null;
  errorMessage?: string | null;
  creditsRemaining?: number | null;
}

export interface BillingUsagePage {
  items: BillingUsageRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface HitResultsPage {
  items: HitExtract[];
  limit: number;
  nextCursor: string | null;
  hasMore: boolean;
  total: number;
}

export interface StageSnapshot {
  workers: WorkerState[];
  concurrency: number;
  queue: BatchResult[];
  results: HitExtract[];
  activeTasks: number;
  jevCalls: number;
  jevHits: number;
  jevMisses: number;
  jevTokens: number;
  model: string;
  analysisBackend?: "jev" | "laya";
  typesafeApiKeySet: boolean;
  telegramStatus: TelegramStep;
  messageCount: number;
  recentBatchError?: BatchResult | null;
}

export interface LoginNext {
  nextStep: TelegramStep;
  phoneCodeHash?: string | null;
  qrUrl?: string | null;
  qrExpiresAt?: string | null;
}

export interface SseEnvelope {
  type: string;
  payload: Record<string, unknown>;
}
