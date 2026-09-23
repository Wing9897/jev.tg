import { intlTag, messages } from "./i18n/messages";
import { getLocale } from "./i18n/store";
import type { UsdKind } from "./types";

export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs === 0) return "$0.00";
  if (abs < 0.01) return `$${value.toFixed(6)}`;
  if (abs < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokens(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "0";
  return Math.round(value).toLocaleString(intlTag(getLocale()));
}

export function usdKindLabel(kind: UsdKind | string | null | undefined): string {
  const labels = messages[getLocale()].billing;
  if (kind === "actual") return labels.kindActual;
  if (kind === "mixed") return labels.kindMixed;
  if (kind === "estimate") return labels.kindEstimate;
  return "";
}

export function spendPrefix(kind: UsdKind | string | null | undefined): string {
  if (kind === "actual") return "";
  if (kind === "none" || !kind) return "";
  return messages[getLocale()].estimatePrefix;
}

export function formatWhen(iso?: string | null, withSeconds = true): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(intlTag(getLocale()), {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" as const } : {}),
  });
}
