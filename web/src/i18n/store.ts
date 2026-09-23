import { messages, type Locale } from "./messages";

const STORAGE_KEY = "jev.locale";

const listeners = new Set<() => void>();

function isLocale(value: string | null): value is Locale {
  return value === "zh-Hant" || value === "zh-Hans" || value === "en";
}

function readStored(): Locale {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (isLocale(raw)) return raw;
  } catch {
    /* private mode or blocked storage */
  }
  return "zh-Hant";
}

let locale: Locale = readStored();

function applyDom(next: Locale) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = next;
  document.title = messages[next].docTitle;
}

applyDom(locale);

export function getLocale(): Locale {
  return locale;
}

export function setLocale(next: Locale) {
  if (next === locale) return;
  locale = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore quota / private mode */
  }
  applyDom(next);
  for (const listener of listeners) listener();
}

export function subscribeLocale(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
