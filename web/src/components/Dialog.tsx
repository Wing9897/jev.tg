import { useEffect, useId, useLayoutEffect, useRef, useState, type AnimationEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../i18n/context";

let scrollLocks = 0;
let dialogSeq = 0;
const dialogStack: number[] = [];

function lockDocumentScroll() {
  scrollLocks += 1;
  document.documentElement.style.overflow = "hidden";
  document.body.style.overflow = "hidden";
}

function unlockDocumentScroll() {
  scrollLocks = Math.max(0, scrollLocks - 1);
  if (scrollLocks > 0) return;
  document.documentElement.style.overflow = "";
  document.body.style.overflow = "";
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean | "xl";
}) {
  const { m } = useI18n();
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [present, setPresent] = useState(open);
  const [closing, setClosing] = useState(false);
  const shown = open || present || closing;

  useLayoutEffect(() => {
    if (open) {
      setPresent(true);
      setClosing(false);
      return;
    }
    if (!present) return;
    if (prefersReducedMotion()) {
      setPresent(false);
      setClosing(false);
      return;
    }
    setClosing(true);
  }, [open, present]);

  useEffect(() => {
    if (!shown) return;
    const id = ++dialogSeq;
    dialogStack.push(id);
    lockDocumentScroll();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (dialogStack[dialogStack.length - 1] !== id) return;
      event.preventDefault();
      onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      const index = dialogStack.lastIndexOf(id);
      if (index >= 0) dialogStack.splice(index, 1);
      window.removeEventListener("keydown", onKey);
      unlockDocumentScroll();
    };
  }, [shown]);

  useEffect(() => {
    if (!open || closing) return;
    const body = panelRef.current?.querySelector<HTMLElement>(".dialog-body");
    body?.querySelector<HTMLElement>("input:not([type='checkbox']), select, textarea")?.focus({ preventScroll: true });
  }, [open, closing, title]);

  useEffect(() => {
    if (!closing) return;
    const timer = window.setTimeout(() => {
      setClosing(false);
      setPresent(false);
    }, 280);
    return () => window.clearTimeout(timer);
  }, [closing]);

  function finishClose(event: AnimationEvent<HTMLDivElement>) {
    if (!closing) return;
    if (event.target !== event.currentTarget) return;
    if (event.animationName !== "dialog-out") return;
    setClosing(false);
    setPresent(false);
  }

  if (!shown) return null;

  return createPortal(
    <div
      className={`dialog-backdrop${closing ? " is-closing" : ""}`}
      onMouseDown={() => onCloseRef.current()}
      onAnimationEnd={finishClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`dialog-panel${wide === "xl" ? " is-xwide" : wide ? " is-wide" : ""}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="dialog-close" onClick={() => onCloseRef.current()}>
            {m.close}
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
