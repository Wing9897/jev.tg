import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { api, errorText } from "../api";
import { notifyChannelsChanged } from "../channelSync";
import { Dialog } from "../components/Dialog";
import { Field, SearchBox } from "../components/fields";
import { intlTag, type UiErrorKey } from "../i18n/messages";
import { useI18n } from "../i18n/context";
import { closeShellDialog, openShellDialog, subscribeShellDialog, type ShellDialog } from "../shellDialogs";
import { useSse } from "../sse";
import type { Channel, LoginNext, SseEnvelope, TelegramStatus } from "../types";

function shownError(value: string | null, errors: Record<UiErrorKey, string>) {
  if (!value) return null;
  if (value === "qr" || value === "qrLogin" || value === "apiId" || value === "apiHash" || value === "phone" || value === "code" || value === "password") {
    return errors[value];
  }
  return value;
}

export default function TelegramPage() {
  const { locale, m } = useI18n();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [phoneCodeHash, setPhoneCodeHash] = useState<string | null>(null);
  const [step, setStep] = useState<string>("disconnected");
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrImage, setQrImage] = useState<string | null>(null);
  const [qrExpiresAt, setQrExpiresAt] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [qrPollId, setQrPollId] = useState(0);
  const [qrWaiting, setQrWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [shell, setShell] = useState<ShellDialog | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);
  const [channelsOpen, setChannelsOpen] = useState(false);
  const [channelSaving, setChannelSaving] = useState(false);
  const loginUiRef = useRef(false);
  const surfaced2fa = useRef(false);
  const channelSaveRef = useRef(false);
  const refreshRef = useRef<() => Promise<void>>(async () => {});

  async function refresh() {
    const [telegram, channelResp] = await Promise.all([api.telegram(), api.channels()]);
    setStatus(telegram);
    setChannels(channelResp.channels);
    if (telegram.apiId) setApiId(String(telegram.apiId));
    if (telegram.phone) setPhone(telegram.phone);
    setStep((current) => {
      if (telegram.status === "connected") return "connected";
      if (["code_required", "qr_required", "2fa_required"].includes(current)) return current;
      if (telegram.status === "qr_required") return "disconnected";
      return telegram.status;
    });
    setLoading(false);
  }

  useEffect(() => {
    void refresh().catch((err: unknown) => {
      setError(errorText(err));
      setLoading(false);
    });
  }, []);

  useLayoutEffect(() => subscribeShellDialog((id) => {
    setShell(id);
    if (id === "telegram") setLoginOpen(true);
    else setChannelsOpen(false);
  }), []);

  refreshRef.current = refresh;

  useSse((event: SseEnvelope) => {
    if (event.type !== "telegram_status") return;
    const next = String(event.payload.status ?? "");
    const lastError = event.payload.lastError;
    if (typeof lastError === "string" && lastError) setError(lastError);
    if (next === "connected") {
      loginUiRef.current = false;
      setQrOpen(false);
      setQrPollId(0);
      setQrWaiting(false);
      setStep("connected");
      void refreshRef.current();
      return;
    }
    if (loginUiRef.current || ["code_required", "qr_required", "2fa_required"].includes(step)) return;
    if (next) {
      setStep(next);
      setStatus((current) => (current ? { ...current, status: next as TelegramStatus["status"] } : current));
    }
  });

  useEffect(() => {
    if (!qrUrl) {
      setQrImage(null);
      return;
    }
    let cancelled = false;
    void QRCode.toDataURL(qrUrl, { width: 240, margin: 2, errorCorrectionLevel: "M" })
      .then((url) => {
        if (!cancelled) setQrImage(url);
      })
      .catch(() => {
        if (!cancelled) {
          setQrImage(null);
          setError("qr");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [qrUrl]);

  useEffect(() => {
    if (step === "2fa_required") {
      if (!surfaced2fa.current) {
        surfaced2fa.current = true;
        if (shell !== "telegram") {
          openShellDialog("telegram");
          return;
        }
      }
      setLoginOpen(false);
      return;
    }
    surfaced2fa.current = false;
    if (qrOpen) {
      setLoginOpen(false);
      return;
    }
    if (step === "code_required" && shell === "telegram") setLoginOpen(true);
  }, [qrOpen, step, shell]);

  useEffect(() => {
    if (!qrOpen || qrPollId === 0) return;
    let cancelled = false;
    setQrWaiting(true);
    const poll = async () => {
      while (!cancelled) {
        try {
          const resp = await api.waitQr(20);
          if (cancelled) return;
          if (resp.nextStep === "qr_required") {
            setQrUrl(resp.qrUrl ?? null);
            setQrExpiresAt(resp.qrExpiresAt ?? null);
            setError(null);
            continue;
          }
          if (resp.nextStep === "2fa_required") {
            loginUiRef.current = true;
            setQrOpen(false);
            setQrPollId(0);
            setQrWaiting(false);
            setQrUrl(null);
            setStep("2fa_required");
            setError(null);
            return;
          }
          if (resp.nextStep === "connected") {
            loginUiRef.current = false;
            setQrOpen(false);
            setQrPollId(0);
            setQrWaiting(false);
            setQrUrl(null);
            setStep("connected");
            setCode("");
            setPassword("");
            setError(null);
            void refreshRef.current();
            return;
          }
          setQrWaiting(false);
          setError("qrLogin");
          return;
        } catch (err) {
          if (cancelled) return;
          const message = errorText(err);
          if (/timed out|timeout|abort|failed to fetch|network/i.test(message)) continue;
          setQrWaiting(false);
          setError(message);
          return;
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      setQrWaiting(false);
    };
  }, [qrOpen, qrPollId]);

  function applyLogin(resp: LoginNext) {
    setStep(resp.nextStep);
    if (resp.phoneCodeHash) setPhoneCodeHash(resp.phoneCodeHash);
    setQrUrl(resp.qrUrl ?? null);
    setQrExpiresAt(resp.qrExpiresAt ?? null);
    if (resp.nextStep === "connected") {
      setCode("");
      setPassword("");
      void refresh();
    }
  }

  function credentials(): { apiId: number; apiHash: string } | null {
    const parsedId = Number(apiId);
    if (!apiId.trim() || !Number.isFinite(parsedId) || parsedId <= 0) {
      setError("apiId");
      return null;
    }
    if (!apiHash.trim() && !status?.hasApiHash) {
      setError("apiHash");
      return null;
    }
    return { apiId: parsedId, apiHash: apiHash.trim() };
  }

  function closeQr() {
    loginUiRef.current = false;
    setQrOpen(false);
    setQrPollId(0);
    setQrWaiting(false);
    setQrUrl(null);
    setStep((current) => (current === "qr_required" ? "disconnected" : current));
  }

  async function startPhone(event: FormEvent) {
    event.preventDefault();
    const creds = credentials();
    if (!creds) return;
    if (!phone.trim()) {
      setError("phone");
      return;
    }
    setBusy(true);
    setError(null);
    loginUiRef.current = true;
    try {
      const resp = await api.loginPhone({ ...creds, phone: phone.trim() });
      applyLogin(resp);
      if (resp.nextStep === "connected" || resp.nextStep === "error") loginUiRef.current = false;
    } catch (err) {
      loginUiRef.current = false;
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function startQr() {
    const creds = credentials();
    if (!creds) return;
    setBusy(true);
    setError(null);
    setQrUrl(null);
    setQrExpiresAt(null);
    setQrImage(null);
    loginUiRef.current = true;
    setQrOpen(true);
    setQrPollId(0);
    setQrWaiting(false);
    setStep("qr_required");
    try {
      const resp = await api.loginQr(creds);
      if (resp.nextStep === "qr_required") {
        setQrUrl(resp.qrUrl ?? null);
        setQrExpiresAt(resp.qrExpiresAt ?? null);
        setStep("qr_required");
        setQrPollId((current) => current + 1);
        return;
      }
      setQrOpen(false);
      applyLogin(resp);
      if (resp.nextStep !== "2fa_required") loginUiRef.current = false;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    if (!code.trim()) {
      setError("code");
      return;
    }
    setBusy(true);
    setError(null);
    loginUiRef.current = true;
    try {
      const resp = await api.loginCode({ code: code.trim(), phoneCodeHash });
      applyLogin(resp);
      if (resp.nextStep === "connected") loginUiRef.current = false;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit2fa(event: FormEvent) {
    event.preventDefault();
    if (!password.trim()) {
      setError("password");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await api.login2fa({ password });
      applyLogin(resp);
      if (resp.nextStep === "connected") loginUiRef.current = false;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function closeChannels() {
    if (channelSaveRef.current) return;
    setChannelsOpen(false);
  }

  function selectShownChannels() {
    const visible = new Set(filtered.map((item) => item.platformId));
    setChannels((current) =>
      current.map((item) => (visible.has(item.platformId) ? { ...item, subscribed: true } : item)),
    );
  }

  function clearChannels() {
    setChannels((current) => current.map((item) => ({ ...item, subscribed: false })));
  }

  async function finishChannels() {
    if (channelSaveRef.current) return;
    const subscribedIds = channels.filter((item) => item.subscribed).map((item) => item.platformId);
    channelSaveRef.current = true;
    setChannelSaving(true);
    setBusy(true);
    setError(null);
    try {
      const resp = await api.saveChannels(subscribedIds);
      setChannels(resp.channels);
      notifyChannelsChanged(resp.channels);
      setChannelsOpen(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      channelSaveRef.current = false;
      setChannelSaving(false);
      setBusy(false);
    }
  }

  async function syncChannels() {
    setBusy(true);
    setError(null);
    try {
      const resp = await api.syncChannels();
      setChannels(resp.channels);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const qrExpiryLabel = useMemo(() => {
    if (!qrExpiresAt) return null;
    const date = new Date(qrExpiresAt);
    if (Number.isNaN(date.getTime())) return qrExpiresAt;
    return date.toLocaleTimeString(intlTag(locale), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }, [qrExpiresAt, locale]);

  const subscribedCount = channels.filter((item) => item.subscribed).length;
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return channels;
    return channels.filter(
      (item) => item.name.toLowerCase().includes(needle) || item.platformId.toLowerCase().includes(needle),
    );
  }, [channels, query]);

  const preview = channels
    .filter((item) => item.subscribed)
    .slice(0, 3)
    .map((item) => item.name)
    .join(m.listSep);

  const banner = shownError(error, m.telegram.errors);

  return (
    <>
      <Dialog
        open={loginOpen && shell === "telegram"}
        title="Telegram"
        onClose={() => {
          setLoginOpen(false);
          closeShellDialog("telegram");
        }}
        footer={
          <>
            <button type="button" className="dlg-btn" onClick={() => setChannelsOpen(true)} disabled={busy}>
              {m.telegram.channels(subscribedCount)}
            </button>
            {status?.status === "connected" ? (
              <button type="button" className="dlg-btn danger" onClick={() => void api.disconnectTelegram().then(refresh)}>
                {m.telegram.disconnect}
              </button>
            ) : null}
            <span className="dialog-foot-gap" />
            <button type="button" disabled={busy} className="dlg-btn" onClick={() => void startQr()}>
              {m.telegram.useQr}
            </button>
            <button type="submit" form="tg-phone-form" disabled={busy} className={step === "code_required" ? "dlg-btn" : "dlg-btn primary"}>
              {m.telegram.sendCode}
            </button>
            {step === "code_required" ? (
              <button type="submit" form="tg-code-form" disabled={busy} className="dlg-btn primary">
                {m.telegram.verify}
              </button>
            ) : null}
          </>
        }
      >
        <div className="dialog-stack">
          <p className="dialog-meta">
            <span>{loading ? m.telegram.loading : status?.status === "connected" ? m.telegram.connected : m.telegram.disconnected}</span>
            {status?.name ? <span>{status.name}</span> : null}
            <span>{m.telegram.subscribed(subscribedCount)}</span>
            {preview ? <span>{preview}</span> : null}
          </p>
          {status?.lastError ? <p className="dialog-warn">{m.telegram.lastError(status.lastError)}</p> : null}
          {error && !qrOpen && step !== "2fa_required" ? (
            <p role="alert" className="dialog-alert">
              {banner}
            </p>
          ) : null}
          <form id="tg-phone-form" className="dialog-stack" onSubmit={(event) => void startPhone(event)} aria-busy={busy}>
            <Field label="api_id" labelTitle={m.telegram.apiIdTitle}>
              <input
                className="field-input"
                value={apiId}
                onChange={(event) => setApiId(event.target.value)}
                inputMode="numeric"
                autoComplete="off"
              />
            </Field>
            <Field label="api_hash">
              <input
                type="password"
                className="field-input"
                value={apiHash}
                onChange={(event) => setApiHash(event.target.value)}
                autoComplete="off"
                placeholder={status?.hasApiHash ? m.telegram.apiHashSaved : ""}
              />
            </Field>
            <Field label={m.telegram.phone}>
              <input
                className="field-input"
                placeholder="+8869..."
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                autoComplete="tel"
              />
            </Field>
          </form>
          {step === "code_required" ? (
            <form id="tg-code-form" className="dialog-section" onSubmit={(event) => void submitCode(event)}>
              <Field label={m.telegram.codeLabel}>
                <input
                  className="field-input"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  autoComplete="one-time-code"
                  aria-label={m.telegram.codeAria}
                />
              </Field>
            </form>
          ) : null}
        </div>
      </Dialog>

      <Dialog
        open={channelsOpen && shell === "telegram"}
        title={m.telegram.channelTitle}
        onClose={closeChannels}
        wide
        footer={
          <button type="button" disabled={busy} className="dlg-btn primary" onClick={() => void finishChannels()}>
            {channelSaving ? m.saving : m.telegram.done}
          </button>
        }
      >
        <div className="dialog-pin">
          <div className="dialog-toolbar">
            <p className="dialog-meta">
              <span>
                {m.telegram.selectedOf(subscribedCount, channels.length)}
              </span>
              {query.trim() ? <span>{m.telegram.showing(filtered.length)}</span> : null}
              {channelSaving ? <span>{m.saving}</span> : null}
            </p>
            <div className="dialog-toolbar-actions">
              <button type="button" className="dlg-btn sm" onClick={selectShownChannels} disabled={busy || filtered.length === 0}>
                {m.telegram.selectAll}
              </button>
              <button type="button" className="dlg-btn sm" onClick={clearChannels} disabled={busy || channels.length === 0}>
                {m.telegram.clear}
              </button>
              <button type="button" className="dlg-btn sm" onClick={() => void syncChannels()} disabled={busy}>
                {m.telegram.resync}
              </button>
            </div>
          </div>
          <SearchBox label={m.telegram.searchChannels} placeholder={m.telegram.searchChannelsPlaceholder} value={query} onChange={setQuery} disabled={channelSaving} />
        </div>
        {error ? (
          <p role="alert" className="dialog-alert dialog-follow">
            {banner}
          </p>
        ) : null}
        <div className="pick-list is-tall dialog-follow" role="group" aria-label={m.telegram.channelListAria}>
          {channels.length === 0 ? (
            <p className="dialog-note is-center">{m.telegram.channelsEmpty}</p>
          ) : filtered.length === 0 ? (
            <p className="dialog-note is-center">{m.telegram.noDialogMatch(query)}</p>
          ) : (
            filtered.map((channel) => (
              <label key={channel.platformId} className="check-row">
                <input
                  type="checkbox"
                  checked={channel.subscribed}
                  disabled={channelSaving}
                  onChange={(event) =>
                    setChannels((current) =>
                      current.map((item) =>
                        item.platformId === channel.platformId ? { ...item, subscribed: event.target.checked } : item,
                      ),
                    )
                  }
                />
                <span className="min-w-0 truncate">{channel.name}</span>
                <span className="ml-auto shrink-0 font-mono text-slate-500">{channel.platformId}</span>
              </label>
            ))
          )}
        </div>
      </Dialog>
      <Dialog
        open={qrOpen && shell === "telegram"}
        title={m.telegram.qrTitle}
        onClose={closeQr}
        footer={
          error ? (
            <button type="button" disabled={busy} className="dlg-btn primary" onClick={() => void startQr()}>
              {m.telegram.qrRetry}
            </button>
          ) : null
        }
      >
        <div className="dialog-stack">
          <p className="field-hint">{m.telegram.qrHelp}</p>
          {error ? (
            <p role="alert" className="dialog-alert">
              {banner}
            </p>
          ) : null}
          <div className="flex flex-col items-center gap-2">
            {qrImage ? (
              <img src={qrImage} alt={m.telegram.qrAlt} className="h-60 w-60 rounded-lg bg-white p-2" />
            ) : (
              <div className="flex h-60 w-60 items-center justify-center rounded-lg border border-line text-slate-500">{m.telegram.qrGenerating}</div>
            )}
            {qrExpiryLabel ? <p className="dialog-meta">{m.telegram.qrExpires(qrExpiryLabel)}</p> : null}
            {qrWaiting ? <p className="dialog-note">{m.telegram.qrWaiting}</p> : null}
          </div>
        </div>
      </Dialog>
      <Dialog
        open={step === "2fa_required" && shell === "telegram"}
        title={m.telegram.twoFaTitle}
        onClose={() => {
          loginUiRef.current = false;
          setStep("disconnected");
          setPassword("");
        }}
        footer={
          <button type="submit" form="tg-2fa-form" disabled={busy} className="dlg-btn primary">
            {m.telegram.submitPassword}
          </button>
        }
      >
        <form id="tg-2fa-form" className="dialog-stack" onSubmit={(event) => void submit2fa(event)}>
          {error ? (
            <p role="alert" className="dialog-alert">
              {banner}
            </p>
          ) : null}
          <Field label={m.telegram.cloudPassword} hint={m.telegram.twoFaHint} labelTitle={m.telegram.twoFaTitleAttr}>
            <input
              type="password"
              className="field-input"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              aria-label={m.telegram.twoFaAria}
            />
          </Field>
        </form>
      </Dialog>
    </>
  );
}
