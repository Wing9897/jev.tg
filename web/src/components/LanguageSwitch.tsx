import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LOCALE_LABEL, LOCALES, type Locale } from "../i18n/messages";
import { useI18n } from "../i18n/context";

export function LanguageSwitch() {
  const { locale, setLocale, m } = useI18n();
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState({ top: 0, right: 8 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    place();
    const onPointer = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    };
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    const current = menuRef.current?.querySelector<HTMLButtonElement>("[aria-checked='true']");
    current?.focus();
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  function place() {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setBox({ top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) });
  }

  function toggle() {
    if (!open) place();
    setOpen((current) => !current);
  }

  function choose(next: Locale) {
    setLocale(next);
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`icon-btn${open ? " is-open" : ""}`}
        aria-label={m.lang.button}
        title={m.lang.button}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={toggle}
      >
        <LangMark />
      </button>
      {open
        ? createPortal(
            <div
              ref={menuRef}
              id={menuId}
              role="menu"
              aria-label={m.lang.menu}
              className="lang-menu"
              style={{ top: box.top, right: box.right }}
            >
              {LOCALES.map((code) => {
                const current = code === locale;
                return (
                  <button
                    key={code}
                    type="button"
                    role="menuitemradio"
                    aria-checked={current}
                    className={current ? "is-current" : undefined}
                    onClick={() => choose(code)}
                  >
                    <span>{LOCALE_LABEL[code]}</span>
                    {current ? (
                      <span className="lang-mark" aria-hidden="true">
                        ✓
                      </span>
                    ) : (
                      <span className="lang-mark" aria-hidden="true" />
                    )}
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

function LangMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 5h8M8 3v2" strokeLinecap="round" />
      <path d="m5 8 6 6M4 14l6-6 2-3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="m22 21-5-10-5 10M14 17h6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
