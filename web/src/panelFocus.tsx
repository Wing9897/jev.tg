import type { MouseEvent, ReactNode } from "react";
import { useLocation, useNavigate, type NavigateFunction } from "react-router-dom";
import { isShellDialog, openShellDialog } from "./shellDialogs";

function isScrollable(node: HTMLElement) {
  const style = getComputedStyle(node);
  const overflow = `${style.overflowY} ${style.overflow}`;
  if (!/(auto|scroll)/.test(overflow)) return false;
  return node.scrollHeight > node.clientHeight + 1;
}

const flashTimers = new WeakMap<HTMLElement, number>();

/** Flash the panel. If its cell clips it, move only that panel's inner list. */
export function highlightPanel(id: string) {
  const target = document.getElementById(id);
  if (!target) return;

  const grid = target.closest(".console");
  const bounds = grid instanceof HTMLElement ? grid.getBoundingClientRect() : null;
  const rect = target.getBoundingClientRect();
  const clipped = bounds
    ? rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1
    : rect.top < -1 || rect.bottom > window.innerHeight + 1;
  if (clipped) {
    const inner = target.querySelector<HTMLElement>(".dense-list, .column-scroll");
    if (inner && isScrollable(inner)) {
      inner.scrollTop = 0;
    } else {
      let node = target.parentElement;
      while (node && node !== document.body && node !== document.documentElement) {
        if (isScrollable(node)) {
          const host = node.getBoundingClientRect();
          const next = target.getBoundingClientRect();
          if (next.top < host.top - 1 || next.bottom > host.bottom + 1) {
            node.scrollTop += next.top - host.top;
          }
          break;
        }
        node = node.parentElement;
      }
    }
  }

  const pending = flashTimers.get(target);
  if (pending) window.clearTimeout(pending);
  target.classList.remove("is-flash");
  window.requestAnimationFrame(() => {
    target.classList.add("is-flash");
    const timer = window.setTimeout(() => {
      target.classList.remove("is-flash");
      flashTimers.delete(target);
    }, 520);
    flashTimers.set(target, timer);
  });
}

function openPanelHash(
  event: MouseEvent<HTMLAnchorElement>,
  id: string,
  navigate: NavigateFunction,
  currentHash: string,
) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  if (isShellDialog(id)) {
    event.preventDefault();
    openShellDialog(id);
    if (currentHash !== `#${id}`) {
      navigate({ pathname: "/", search: window.location.search, hash: id });
    }
    return;
  }
  if (!document.getElementById(id)) return;
  event.preventDefault();
  if (currentHash === `#${id}`) {
    highlightPanel(id);
    return;
  }
  navigate({ pathname: "/", search: window.location.search, hash: id });
}

export function PanelLink({
  id,
  className,
  children,
  ariaLabel,
  beforeNavigate,
}: {
  id: string;
  className?: string;
  children: ReactNode;
  ariaLabel?: string;
  beforeNavigate?: () => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <a
      className={className}
      href={`#${id}`}
      aria-label={ariaLabel}
      onClick={(event) => {
        beforeNavigate?.();
        openPanelHash(event, id, navigate, location.hash);
      }}
    >
      {children}
    </a>
  );
}
