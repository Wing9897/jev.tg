import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { api, errorText } from "../api";
import { formatTokens, formatUsd, formatWhen, spendPrefix, usdKindLabel } from "../billingFormat";
import { clampConcurrency, CONCURRENCY_DEFAULT, CONCURRENCY_MAX, CONCURRENCY_MIN } from "../concurrency";
import { Dialog } from "../components/Dialog";
import { Field } from "../components/fields";
import { notifySettingsChanged } from "../channelSync";
import { useI18n } from "../i18n/context";
import { closeShellDialog, subscribeShellDialog } from "../shellDialogs";
import type { BillingSummary, BillingUsageRow, Settings } from "../types";

function parseMaxAgeDays(raw: string) {
  const trimmed = raw.trim();
  if (!trimmed) return 0;
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(3650, Math.floor(value));
}

/** Display-only stand-in. Never the stored key, and never sent on save. */
const SAVED_KEY_MASK = "••••••••••••••••";

function draftFromMaskedField(next: string): string | null {
  if (next === SAVED_KEY_MASK) return null;
  if (next.includes(SAVED_KEY_MASK)) return next.replaceAll(SAVED_KEY_MASK, "");
  if (/^•*$/.test(next)) return "";
  return next;
}

export default function SettingsPage() {
  const { m } = useI18n();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [keyFocused, setKeyFocused] = useState(false);
  const [model, setModel] = useState("jev-1.13.0");
  const [backend, setBackend] = useState<"jev" | "laya">("jev");
  const [concurrency, setConcurrency] = useState(CONCURRENCY_DEFAULT);
  const [inputRate, setInputRate] = useState("0.42");
  const [outputRate, setOutputRate] = useState("0");
  const [lowThreshold, setLowThreshold] = useState("0");
  const [maxAgeDays, setMaxAgeDays] = useState("0");
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [ledger, setLedger] = useState<BillingUsageRow[]>([]);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const [usageBackend, setUsageBackend] = useState<"jev" | "laya" | null>(null);
  const [billingReady, setBillingReady] = useState(false);
  const billingGen = useRef(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const pageSize = 20;

  async function loadBilling(offset: number, which: "jev" | "laya") {
    const gen = ++billingGen.current;
    const [nextSummary, page] = await Promise.all([
      api.billingSummary(which),
      api.billingUsage({ limit: pageSize, offset, backend: which }),
    ]);
    if (gen !== billingGen.current) return;
    setSummary(nextSummary);
    setLedger(page.items);
    setLedgerTotal(page.total);
    setLedgerOffset(page.offset);
    setUsageBackend(which);
  }

  useLayoutEffect(() => subscribeShellDialog((id) => {
    setDetailsOpen(id === "settings");
  }), []);

  useEffect(() => {
    void (async () => {
      try {
        const value = await api.settings();
        setSettings(value);
        setModel(value.model);
        setBackend(value.analysisBackend === "laya" ? "laya" : "jev");
        setConcurrency(clampConcurrency(value.concurrency));
        setInputRate(String(value.inputUsdPerMtok ?? 0.42));
        setOutputRate(String(value.outputUsdPerMtok ?? 0));
        setLowThreshold(String(value.lowCreditsThreshold ?? 0));
        setMaxAgeDays(String(value.analysisMaxAgeDays ?? 0));
        setBillingReady(true);
      } catch (err) {
        setError(errorText(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!billingReady) return;
    void loadBilling(0, backend).catch((err) => setError(errorText(err)));
  }, [billingReady, backend]);

  useEffect(() => {
    if (!detailsOpen) setKeyFocused(false);
  }, [detailsOpen]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const typedKey = apiKey.trim();
      const next = await api.saveSettings({
        typesafeApiKey: typedKey && typedKey !== SAVED_KEY_MASK ? typedKey : undefined,
        model,
        analysisBackend: backend,
        concurrency: clampConcurrency(concurrency),
        inputUsdPerMtok: Number(inputRate),
        outputUsdPerMtok: Number(outputRate),
        lowCreditsThreshold: Number(lowThreshold),
        analysisMaxAgeDays: parseMaxAgeDays(maxAgeDays),
      });
      setSettings(next);
      setApiKey("");
      setKeyFocused(false);
      setInputRate(String(next.inputUsdPerMtok));
      setOutputRate(String(next.outputUsdPerMtok));
      setLowThreshold(String(next.lowCreditsThreshold));
      setMaxAgeDays(String(next.analysisMaxAgeDays ?? 0));
      setConcurrency(clampConcurrency(next.concurrency));
      setBackend(next.analysisBackend === "laya" ? "laya" : "jev");
      setMessage(next.analysisBackend === "laya" ? "saved-laya" : "saved");
      notifySettingsChanged();
      await loadBilling(ledgerOffset, backend);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  async function clearKey() {
    if (!window.confirm(m.settings.confirmClear)) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const next = await api.saveSettings({ typesafeApiKey: "" });
      setSettings(next);
      setApiKey("");
      setKeyFocused(false);
      setMessage("cleared");
      notifySettingsChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  const usagePending = loading || usageBackend !== backend;
  const notice =
    message === "saved"
      ? m.settings.saved
      : message === "saved-laya"
        ? m.settings.savedLaya
        : message === "cleared"
          ? m.settings.cleared
          : message;
  const savedBackend = settings?.analysisBackend === "laya" ? "laya" : "jev";
  const layaForm = backend === "laya";
  const emptyUsage = !layaForm && !usagePending && (summary?.allTime.calls ?? 0) === 0;
  // Same split as server billing `_backend_scope`: Laya rows only, or every row that is not Laya.
  const ledgerRows = ledger.filter((row) => (layaForm ? row.backend === "laya" : row.backend !== "laya"));
  const backendDirty = !loading && settings != null && backend !== savedBackend;
  const keyIsSet = Boolean(settings?.typesafeApiKeySet);
  const showSavedKeyMask = keyIsSet && apiKey === "" && !keyFocused;

  return (
    <Dialog
      open={detailsOpen}
      title={m.settings.title}
      onClose={() => closeShellDialog("settings")}
      wide="xl"
      footer={
        <>
          {settings?.typesafeApiKeySet && !layaForm ? (
            <button type="button" disabled={saving} className="dlg-btn danger" onClick={() => void clearKey()}>
              {m.settings.clearKey}
            </button>
          ) : null}
          <span className="dialog-foot-gap" />
          <button type="submit" form="settings-form" disabled={saving || loading} className="dlg-btn primary">
            {saving ? m.saving : m.settings.save}
          </button>
        </>
      }
    >
      <form id="settings-form" className="dialog-stack" onSubmit={(event) => void save(event)}>
        {loading ? <p className="dialog-note">{m.settings.loading}</p> : null}
        {error ? (
          <p role="alert" className="dialog-alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="dialog-ok">
            {notice}
          </p>
        ) : null}

        <div className="settings-columns">
          <div className="settings-col">
            <Field label={m.settings.backend} hint={layaForm ? m.settings.layaHint : undefined}>
              <select
                className="field-input"
                value={backend}
                onChange={(event) => setBackend(event.target.value === "laya" ? "laya" : "jev")}
              >
                <option value="jev">{m.settings.backendJev}</option>
                <option value="laya">{m.settings.backendLaya}</option>
              </select>
            </Field>
            {backendDirty ? (
              <p role="status" className="dialog-warn">
                {m.settings.unsavedBackend(savedBackend === "laya" ? m.settings.backendLaya : m.settings.backendJev)}
              </p>
            ) : layaForm ? (
              <p className="dialog-note">{m.settings.layaActive}</p>
            ) : null}
            {layaForm ? null : (
              <>
                <Field label={m.settings.key} labelTitle={m.settings.keyTitle}>
                  <input
                    type="password"
                    className="field-input"
                    placeholder={keyIsSet ? m.settings.keySet : m.settings.keyMissing}
                    value={showSavedKeyMask ? SAVED_KEY_MASK : apiKey}
                    onFocus={() => setKeyFocused(true)}
                    onBlur={() => setKeyFocused(false)}
                    onChange={(event) => {
                      const next = event.target.value;
                      if (!showSavedKeyMask) {
                        setApiKey(next === SAVED_KEY_MASK ? "" : next);
                        return;
                      }
                      const draft = draftFromMaskedField(next);
                      if (draft === null) return;
                      setKeyFocused(true);
                      setApiKey(draft);
                    }}
                    autoComplete="off"
                    spellCheck={false}
                    data-key-mask={showSavedKeyMask ? "1" : undefined}
                  />
                </Field>
                <Field label={m.settings.model}>
                  <select className="field-input" value={model} onChange={(event) => setModel(event.target.value)}>
                    <option value="jev-1.13.0">{m.settings.modelPin}</option>
                    <option value="jev-latest">jev-latest</option>
                  </select>
                </Field>
              </>
            )}
            <Field
              label={m.settings.concurrencyLegend}
              hint={layaForm ? m.settings.layaConcurrency : m.settings.concurrencyHint}
              labelTitle={m.settings.concurrencyTitle}
            >
              <div className="inline-control">
                <label className="sr-only" htmlFor="concurrency-range">
                  {m.settings.rangeAria}
                </label>
                <input
                  id="concurrency-range"
                  type="range"
                  min={CONCURRENCY_MIN}
                  max={CONCURRENCY_MAX}
                  step={1}
                  className="range-input"
                  value={concurrency}
                  onChange={(event) => setConcurrency(clampConcurrency(Number(event.target.value)))}
                />
                <label className="sr-only" htmlFor="concurrency-input">
                  {m.settings.numberAria}
                </label>
                <input
                  id="concurrency-input"
                  type="number"
                  min={CONCURRENCY_MIN}
                  max={CONCURRENCY_MAX}
                  className="field-input field-input-narrow"
                  value={concurrency}
                  onChange={(event) => setConcurrency(clampConcurrency(Number(event.target.value)))}
                />
              </div>
            </Field>
            <Field
              label={m.settings.maxAge}
              hint={m.settings.maxAgeHint}
              labelTitle={m.settings.maxAgeTitle}
            >
              <input
                type="number"
                min={0}
                max={3650}
                step={1}
                inputMode="numeric"
                className="field-input font-mono"
                value={maxAgeDays}
                placeholder="0"
                onChange={(event) => setMaxAgeDays(event.target.value)}
              />
            </Field>
            <Field label={m.settings.dataDir}>
              <input className="field-input" value={settings?.dataDir ?? ""} readOnly />
            </Field>
          </div>

          <div className="settings-col">
            {layaForm ? null : (
              <dl className="stat-strip">
                <div>
                  <dt>{m.settings.calls}</dt>
                  <dd>{settings?.jevCalls ?? 0}</dd>
                </div>
                <div>
                  <dt>{m.settings.hits}</dt>
                  <dd>{settings?.jevHits ?? 0}</dd>
                </div>
                <div>
                  <dt>{m.settings.misses}</dt>
                  <dd>{settings?.jevMisses ?? 0}</dd>
                </div>
                <div>
                  <dt>tokens</dt>
                  <dd>{settings?.jevTokens ?? 0}</dd>
                </div>
              </dl>
            )}

            {layaForm ? (
              <p className="dialog-note">{m.settings.layaSpend}</p>
            ) : (
              <section className="dialog-section">
                <div className="section-head">
                  <h3 title={m.settings.pricingTitleAttr}>{m.settings.pricingTitle}</h3>
                  <p className="field-hint">{m.settings.pricingHint}</p>
                </div>
                <div className="settings-rates">
                  <Field label={m.settings.inputRate}>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      className="field-input font-mono"
                      value={inputRate}
                      onChange={(event) => setInputRate(event.target.value)}
                    />
                  </Field>
                  <Field label={m.settings.outputRate}>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      className="field-input font-mono"
                      value={outputRate}
                      onChange={(event) => setOutputRate(event.target.value)}
                    />
                  </Field>
                  <Field label={m.settings.lowThreshold}>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      className="field-input font-mono"
                      value={lowThreshold}
                      onChange={(event) => setLowThreshold(event.target.value)}
                    />
                  </Field>
                </div>
              </section>
            )}
          </div>
        </div>

        <section className="dialog-section" aria-labelledby="billing-heading">
          <div className="section-head">
            <h3 id="billing-heading">{m.settings.billingTitle}</h3>
            <p className="field-hint">{layaForm ? m.settings.billingIntroLaya : m.settings.billingIntro}</p>
          </div>

          {!layaForm && summary?.insufficientCredits ? (
            <p role="alert" className="dialog-alert">
              {summary.lastInsufficientMessage || m.settings.insufficient}
            </p>
          ) : null}
          {!layaForm && summary?.lowBalance ? (
            <p role="status" className="dialog-warn">
              {m.settings.lowBalance(summary.lastCreditsRemaining)}
            </p>
          ) : null}

          {layaForm ? null : usagePending ? (
            <p className="dialog-note">{m.settings.loadingUsage}</p>
          ) : emptyUsage ? (
            <p className="dialog-empty">{m.settings.emptyUsage}</p>
          ) : (
            <div className="usage-grid">
              <WindowCard title={m.settings.today} window={summary?.today} />
              <WindowCard title={m.settings.sevenDays} window={summary?.sevenDays} />
              <WindowCard title={m.settings.allTime} window={summary?.allTime} />
            </div>
          )}

          {layaForm ? null : (
            <dl className="meta-grid">
              <div>
                <dt>{m.settings.creditsLeft}</dt>
                <dd>{summary?.lastCreditsRemaining == null ? m.settings.creditsMissing : String(summary.lastCreditsRemaining)}</dd>
              </div>
              <div>
                <dt>{m.settings.creditsAt}</dt>
                <dd>{formatWhen(summary?.lastCreditsAt)}</dd>
              </div>
            </dl>
          )}

          <div className="section-head">
            <h3>{m.settings.ledger}</h3>
          </div>
          {usagePending ? (
            <p className="dialog-note">{m.settings.loadingLedger}</p>
          ) : ledgerRows.length === 0 ? (
            <p className="dialog-empty">{layaForm ? m.settings.emptyLedgerLaya : m.settings.emptyLedger}</p>
          ) : (
            <div className="ledger-scroll">
              <table className="ledger-table">
                <thead>
                  <tr>
                    <th>{m.settings.colTime}</th>
                    <th>{m.settings.colResult}</th>
                    <th>{m.settings.colModel}</th>
                    <th>{m.settings.colInput}</th>
                    <th>{m.settings.colOutput}</th>
                    <th>{m.settings.colSpend}</th>
                    <th>{m.settings.colBalance}</th>
                  </tr>
                </thead>
                <tbody>
                  {ledgerRows.map((row) => {
                    const local = row.backend === "laya";
                    return (
                      <tr key={row.id}>
                        <td className="font-mono text-slate-400">{formatWhen(row.createdAt)}</td>
                        <td>
                          {row.success ? (
                            <span className="text-lime">{m.settings.success}</span>
                          ) : (
                            <span className="text-rose">{row.errorCode || m.settings.failed}</span>
                          )}
                        </td>
                        <td className="font-mono">{local ? "—" : row.model || "—"}</td>
                        <td className="font-mono">{local ? "—" : formatTokens(row.inputTokens)}</td>
                        <td className="font-mono">{local ? "—" : formatTokens(row.outputTokens)}</td>
                        <td className="font-mono">
                          {local
                            ? m.settings.layaSpend
                            : row.spendUsd == null
                              ? "—"
                              : `${spendPrefix(row.usdKind)}${formatUsd(row.spendUsd)}`}
                        </td>
                        <td className="font-mono">{local || row.creditsRemaining == null ? "—" : String(row.creditsRemaining)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!usagePending && ledgerRows.length > 0 && ledgerTotal > pageSize ? (
            <div className="pager">
              <span>
                {ledgerOffset + 1}–{Math.min(ledgerOffset + pageSize, ledgerTotal)} / {ledgerTotal}
              </span>
              <div className="pager-actions">
                <button
                  type="button"
                  className="dlg-btn sm"
                  disabled={ledgerOffset <= 0}
                  onClick={() => void loadBilling(Math.max(0, ledgerOffset - pageSize), backend)}
                >
                  {m.settings.prev}
                </button>
                <button
                  type="button"
                  className="dlg-btn sm"
                  disabled={ledgerOffset + pageSize >= ledgerTotal}
                  onClick={() => void loadBilling(ledgerOffset + pageSize, backend)}
                >
                  {m.settings.next}
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </form>
    </Dialog>
  );
}

function WindowCard({
  title,
  window,
}: {
  title: string;
  window?: { calls: number; tokens: number; usd: number; usdKind: string } | null;
}) {
  const { m } = useI18n();
  const kind = window?.usdKind && window.usdKind !== "none" ? usdKindLabel(window.usdKind) : "";
  return (
    <div className="usage-card">
      <p className="field-label">{title}</p>
      <p className="amount">
        {spendPrefix(window?.usdKind)}
        {formatUsd(window?.usd ?? 0)}
      </p>
      <p className="sub">{m.settings.callsTok(window?.calls ?? 0, formatTokens(window?.tokens), kind)}</p>
    </div>
  );
}
