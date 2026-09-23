import { useEffect, useRef } from "react";
import type { SseEnvelope } from "./types";

export type SseStatus = "connecting" | "open" | "reconnecting";

const EVENT_NAMES = [
  "worker_update",
  "workers_snapshot",
  "batch_hit",
  "batch_miss",
  "batch_error",
  "ingest",
  "queue_update",
  "queue_take",
  "telegram_status",
];

export function useSse(onEvent: (event: SseEnvelope) => void, onStatus?: (status: SseStatus) => void) {
  const onEventRef = useRef(onEvent);
  const onStatusRef = useRef(onStatus);
  onEventRef.current = onEvent;
  onStatusRef.current = onStatus;

  useEffect(() => {
    let stopped = false;
    let source: EventSource | null = null;
    let timer = 0;
    let delay = 800;

    const handler = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(String(event.data)) as SseEnvelope;
        if (parsed?.type) onEventRef.current(parsed);
      } catch {
        /* keep-alives / malformed */
      }
    };

    const connect = () => {
      if (stopped) return;
      onStatusRef.current?.("connecting");
      const next = new EventSource("/api/events");
      source = next;
      for (const name of EVENT_NAMES) {
        next.addEventListener(name, handler as EventListener);
      }
      next.onmessage = handler;
      next.onopen = () => {
        delay = 800;
        onStatusRef.current?.("open");
      };
      next.onerror = () => {
        next.close();
        if (stopped) return;
        onStatusRef.current?.("reconnecting");
        timer = window.setTimeout(connect, delay);
        delay = Math.min(Math.round(delay * 1.7), 12_000);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (source) {
        for (const name of EVENT_NAMES) {
          source.removeEventListener(name, handler as EventListener);
        }
        source.close();
      }
    };
  }, []);
}
