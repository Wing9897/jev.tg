import { memo, useEffect, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useReducedMotion } from "framer-motion";
import { formatWhen } from "../billingFormat";
import { useI18n } from "../i18n/context";
import { messages, type Locale } from "../i18n/messages";
import type { HitExtract, HitImage } from "../types";

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

const imageUrlCache = new WeakMap<HitImage, string>();

function stableImageUrl(image: HitImage) {
  const cached = imageUrlCache.get(image);
  if (cached) return cached;
  const url = `data:${image.mime};base64,${image.base64}`;
  imageUrlCache.set(image, url);
  return url;
}

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

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function wantsReducedMotion(hookValue: boolean | null) {
  if (hookValue === true) return true;
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export type HitPreview = {
  urls: string[];
  index: number;
  label: string;
};

export type HitBubbleEvent = {
  animationName: string;
  elapsedTime: number;
};

export function HitLightbox({
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

export const ResultCard = memo(function ResultCard({
  hit,
  bornDelayMs,
  fresh,
  categoryText,
  locale,
  onOpenImage,
  onBubbleEnd,
}: {
  hit: HitExtract;
  bornDelayMs: number | null;
  fresh: boolean;
  categoryText: string;
  locale: Locale;
  onOpenImage: (urls: string[], index: number, label: string, trigger: HTMLElement) => void;
  onBubbleEnd: (event: HitBubbleEvent) => boolean;
}) {
  const reduceMotion = useReducedMotion();
  const bornDelay = useRef<number | null | undefined>(undefined);
  if (bornDelay.current === undefined) {
    bornDelay.current = bornDelayMs != null && !wantsReducedMotion(reduceMotion) ? bornDelayMs : null;
  }
  const [popDone, setPopDone] = useState(false);
  const [imageIndex, setImageIndex] = useState(0);
  const [imageSwap, setImageSwap] = useState(false);
  const popDelay = bornDelay.current;
  const showPop = popDelay != null && !popDone;
  const m = messages[locale];
  const images = hit.images ?? [];
  const imageCount = images.length;
  const shownIndex = imageCount === 0 ? 0 : Math.min(imageIndex, imageCount - 1);
  const shown = images[shownIndex];
  const fadeImage = imageSwap && !wantsReducedMotion(reduceMotion);
  function moveImage(event: MouseEvent<HTMLButtonElement>, next: number) {
    event.preventDefault();
    event.stopPropagation();
    if (next < 0 || next >= imageCount || next === shownIndex) return;
    if (!wantsReducedMotion(reduceMotion)) setImageSwap(true);
    setImageIndex(next);
  }
  const sender = hit.senderName || m.stage.unknownSender;
  const title = hit.taskName || m.stage.taskFallback;
  const titleColor = taskTone(hit.taskId, hit.taskName);
  return (
    <article
      data-hit-id={hit.id}
      className={showPop ? "result-card is-born" : "result-card"}
      style={showPop ? { animationDelay: `${popDelay}ms` } : undefined}
      onAnimationEnd={(event) => {
        if (onBubbleEnd(event)) setPopDone(true);
      }}
    >
      {shown ? (
        <div className="hit-media">
          <button
            type="button"
            className="hit-media-btn"
            aria-label={m.stage.enlargeImage}
            onClick={(event) => onOpenImage(images.map((item) => stableImageUrl(item)), shownIndex, title, event.currentTarget)}
          >
            <img
              key={`${hit.id}-${shownIndex}`}
              className={fadeImage ? "is-swap" : undefined}
              src={stableImageUrl(shown)}
              alt=""
              width={320}
              height={160}
              decoding="async"
              loading="lazy"
            />
          </button>
          {imageCount > 1 ? (
            <>
              <button
                type="button"
                className="hit-media-nav is-prev"
                aria-label={m.stage.prevImage}
                disabled={shownIndex <= 0}
                onMouseDown={(event) => event.preventDefault()}
                onClick={(event) => moveImage(event, shownIndex - 1)}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <path d="M14.5 6 8.5 12l6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <button
                type="button"
                className="hit-media-nav is-next"
                aria-label={m.stage.nextImage}
                disabled={shownIndex >= imageCount - 1}
                onMouseDown={(event) => event.preventDefault()}
                onClick={(event) => moveImage(event, shownIndex + 1)}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <path d="M9.5 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      <div className="hit-body">
        <div className="hit-head">
          <div className="hit-title-line">
            <p className="hit-title" style={titleColor ? { color: titleColor } : undefined} title={title}>
              {title}
            </p>
            {fresh ? <span className="hit-new">{m.stage.hitNew}</span> : null}
          </div>
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
