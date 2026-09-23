import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { formatTokens, formatUsd, spendPrefix } from "../billingFormat";
import { SETTINGS_CHANGED_EVENT } from "../channelSync";
import { useI18n } from "../i18n/context";
import { PanelLink } from "../panelFocus";
import type { BillingSummary } from "../types";

let cached: BillingSummary | null = null;
let inflight: Promise<BillingSummary> | null = null;

async function loadSummary(): Promise<BillingSummary> {
  if (inflight) return inflight;
  inflight = api
    .billingSummary()
    .then((value) => {
      cached = value;
      return value;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function useBillingSummary() {
  const [summary, setSummary] = useState<BillingSummary | null>(cached);

  const refresh = useCallback(() => {
    void loadSummary()
      .then(setSummary)
      .catch(() => {
        /* HUD is best-effort */
      });
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 8000);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener(SETTINGS_CHANGED_EVENT, onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener(SETTINGS_CHANGED_EVENT, onFocus);
    };
  }, [refresh]);

  return summary;
}

export function BillingAlerts() {
  const { m } = useI18n();
  const summary = useBillingSummary();
  const insufficient = summary?.analysisBackend !== "laya" && Boolean(summary?.hud.insufficientCredits);
  const low = summary?.analysisBackend !== "laya" && Boolean(summary?.hud.lowBalance);
  const credits = summary?.hud.lastCreditsRemaining;

  if (insufficient) {
    return (
      <p role="alert" className="page-gutter border-b border-rose/40 bg-rose/15 py-2 text-center text-sm text-rose">
        {summary?.lastInsufficientMessage || m.billing.insufficient}{" "}
        <PanelLink id="settings" className="underline underline-offset-2">
          {m.billing.view}
        </PanelLink>
      </p>
    );
  }
  if (low) {
    return (
      <p role="status" className="page-gutter border-b border-amber/40 bg-amber/10 py-2 text-center text-sm text-amber">
        {m.billing.low(credits ?? null)}{" "}
        <PanelLink id="settings" className="underline underline-offset-2">
          {m.billing.view}
        </PanelLink>
      </p>
    );
  }
  return null;
}

export function BillingChip() {
  const { m } = useI18n();
  const summary = useBillingSummary();
  const hud = summary?.hud;
  const credits = hud?.lastCreditsRemaining;
  const kind = hud?.todayUsdKind ?? "none";
  const laya = summary?.analysisBackend === "laya";

  return (
    <PanelLink id="settings" ariaLabel={m.billing.chipAria} className="billing-chip">
      {laya ? (
        <span>
          {m.billing.engineLaya} · {m.billing.layaFree}
        </span>
      ) : (
        <span>
          {m.billing.engineJev} · {m.billing.today} {spendPrefix(kind)}
          {formatUsd(hud?.todayUsd ?? 0)} · {formatTokens(hud?.todayTokens ?? 0)} tok
        </span>
      )}
      {laya ? (
        (hud?.todayUsd ?? 0) > 0 ? (
          <span>
            {m.billing.pastJev} {spendPrefix(kind)}
            {formatUsd(hud?.todayUsd ?? 0)}
          </span>
        ) : null
      ) : (
        <span>
          {m.billing.balance} {credits == null ? m.billing.balanceMissing : String(credits)}
        </span>
      )}
    </PanelLink>
  );
}
