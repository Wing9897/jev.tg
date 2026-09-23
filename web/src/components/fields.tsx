import type { ReactNode } from "react";
import { useI18n } from "../i18n/context";

export function Field({
  label,
  hint,
  labelTitle,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  labelTitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <div className="field-label" title={labelTitle}>
        {label}
      </div>
      {children}
      {hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  label,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const { m } = useI18n();
  return (
    <input
      className="field-input search-input"
      value={value}
      placeholder={placeholder ?? m.search}
      aria-label={label}
      disabled={disabled}
      autoComplete="off"
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export function matchesQuery(query: string, ...parts: Array<string | null | undefined>) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return parts.some((part) => (part ?? "").toLowerCase().includes(needle));
}
