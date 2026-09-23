import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { messages, type Locale, type Messages } from "./messages";
import { getLocale, setLocale, subscribeLocale } from "./store";

type I18nValue = {
  locale: Locale;
  setLocale: (next: Locale) => void;
  m: Messages;
};

const I18nContext = createContext<I18nValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocal] = useState<Locale>(getLocale);

  useEffect(() => subscribeLocale(() => setLocal(getLocale())), []);

  const value = useMemo<I18nValue>(() => ({ locale, setLocale, m: messages[locale] }), [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n requires LocaleProvider");
  return value;
}
