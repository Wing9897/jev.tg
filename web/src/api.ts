import type {
  BillingSummary,
  BillingUsagePage,
  Channel,
  LoginNext,
  Settings,
  HitResultsPage,
  StageSnapshot,
  Tag,
  Task,
  TelegramStatus,
} from "./types";

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: {
    typesafeApiKey?: string;
    model?: string;
    concurrency?: number;
    inputUsdPerMtok?: number;
    outputUsdPerMtok?: number;
    lowCreditsThreshold?: number;
    analysisMaxAgeDays?: number;
    analysisPaused?: boolean;
    analysisBackend?: "jev" | "laya";
  }) => request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  billingSummary: (backend?: "jev" | "laya") => {
    const search = new URLSearchParams();
    if (backend) search.set("backend", backend);
    const suffix = search.toString() ? `?${search}` : "";
    return request<BillingSummary>(`/api/v1/billing/summary${suffix}`);
  },
  billingUsage: (params?: { limit?: number; offset?: number; taskId?: string; backend?: "jev" | "laya" }) => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.offset != null) search.set("offset", String(params.offset));
    if (params?.taskId) search.set("taskId", params.taskId);
    if (params?.backend) search.set("backend", params.backend);
    const suffix = search.toString() ? `?${search}` : "";
    return request<BillingUsagePage>(`/api/v1/billing/usage${suffix}`);
  },
  stage: () => request<StageSnapshot>("/api/stage"),
  results: (params?: { limit?: number; cursor?: string; q?: string; taskId?: string; category?: string; minNoul?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const q = params?.q?.trim();
    if (q) search.set("q", q);
    if (params?.taskId) search.set("taskId", params.taskId);
    if (params?.category) search.set("category", params.category);
    const minNoul = params?.minNoul?.trim();
    if (minNoul) search.set("minNoul", minNoul);
    const suffix = search.toString() ? `?${search}` : "";
    return request<HitResultsPage>(`/api/results${suffix}`);
  },
  telegram: () => request<TelegramStatus>("/api/telegram"),
  loginPhone: (body: { apiId: number; apiHash: string; phone: string }) =>
    request<LoginNext>("/api/telegram/login/phone", { method: "POST", body: JSON.stringify(body) }),
  loginCode: (body: { code: string; phoneCodeHash?: string | null }) =>
    request<LoginNext>("/api/telegram/login/code", { method: "POST", body: JSON.stringify(body) }),
  login2fa: (body: { password: string }) =>
    request<LoginNext>("/api/telegram/login/2fa", { method: "POST", body: JSON.stringify(body) }),
  loginQr: (body: { apiId: number; apiHash: string }) =>
    request<LoginNext>("/api/telegram/login/qr", { method: "POST", body: JSON.stringify(body) }),
  waitQr: (timeoutSeconds = 20) =>
    request<LoginNext>("/api/telegram/login/qr/wait", {
      method: "POST",
      body: JSON.stringify({ timeoutSeconds }),
    }),
  disconnectTelegram: () => request<TelegramStatus>("/api/telegram/disconnect", { method: "POST" }),
  channels: () => request<{ channels: Channel[] }>("/api/telegram/channels"),
  syncChannels: () => request<{ synced: number; channels: Channel[] }>("/api/telegram/channels/sync", { method: "POST" }),
  saveChannels: (subscribedIds: string[]) =>
    request<{ channels: Channel[] }>("/api/telegram/channels", {
      method: "PUT",
      body: JSON.stringify({ subscribedIds }),
    }),
  tasks: () => request<{ tasks: Task[] }>("/api/tasks"),
  createTask: (body: Partial<Task> & { name: string; prompt: string }) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
  updateTask: (id: string, body: Partial<Task>) =>
    request<Task>(`/api/tasks/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteTask: (id: string) => request<{ ok: boolean }>(`/api/tasks/${id}`, { method: "DELETE" }),
  tags: () => request<{ tags: Tag[] }>("/api/tags"),
  createTag: (body: { key?: string; label: string; description?: string }) =>
    request<Tag>("/api/tags", { method: "POST", body: JSON.stringify(body) }),
  updateTag: (id: string, body: Partial<Pick<Tag, "key" | "label" | "description">>) =>
    request<Tag>(`/api/tags/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteTag: (id: string) => request<{ ok: boolean }>(`/api/tags/${id}`, { method: "DELETE" }),
};
