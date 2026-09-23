import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n/context";
import type { SseStatus } from "../sse";

export function ConnectionStatus({ sse, telegram }: { sse: SseStatus; telegram: string | null }) {
  const { m } = useI18n();
  const sseLabel = sse === "open" ? m.conn.live : sse === "reconnecting" ? m.conn.reconnecting : m.conn.connecting;
  const tgLabel = telegram == null ? "…" : telegram === "connected" ? m.conn.tgOn : m.conn.tgOff;

  return (
    <div className="conn-status" role="status" aria-label={m.conn.aria}>
      <span className={`status-lamp ${sse === "open" ? "is-live" : "is-wait"}`} aria-hidden="true" />
      <span>
        {m.conn.stream} <strong>{sseLabel}</strong>
      </span>
      <span>
        TG <strong>{tgLabel}</strong>
      </span>
    </div>
  );
}

export function AnalysisToggle() {
  const [paused, setPaused] = useState<boolean | null>(null);
  const saving = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void api
      .settings()
      .then((value) => {
        if (!cancelled) setPaused(Boolean(value.analysisPaused));
      })
      .catch(() => {
        if (!cancelled) setPaused(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggle() {
    if (paused == null || saving.current) return;
    const next = !paused;
    saving.current = true;
    setPaused(next);
    void api
      .saveSettings({ analysisPaused: next })
      .then((saved) => setPaused(Boolean(saved.analysisPaused)))
      .catch(() => setPaused(!next))
      .finally(() => {
        saving.current = false;
      });
  }

  const { m } = useI18n();
  const actionLabel = paused == null ? m.conn.pauseLoading : paused ? m.conn.start : m.conn.pause;

  return (
    <button
      type="button"
      className={`icon-btn${paused ? " is-paused" : ""}`}
      onClick={toggle}
      disabled={paused == null}
      aria-pressed={paused === true}
      aria-label={actionLabel}
      title={actionLabel}
    >
      {paused ? <PlayMark /> : <PauseMark />}
    </button>
  );
}

function PauseMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M8 5.5v13M16 5.5v13" strokeLinecap="round" />
    </svg>
  );
}

function PlayMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M8 5.5v13l11-6.5L8 5.5Z" strokeLinejoin="round" />
    </svg>
  );
}
