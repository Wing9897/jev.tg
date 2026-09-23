export type ShellDialog = "telegram" | "settings" | "tags";

let active: ShellDialog | null = null;
const listeners = new Set<(id: ShellDialog | null) => void>();

export function isShellDialog(id: string): id is ShellDialog {
  return id === "telegram" || id === "settings" || id === "tags";
}

export function openShellDialog(id: ShellDialog) {
  active = id;
  listeners.forEach((listener) => listener(id));
}

export function closeShellDialog(id?: ShellDialog) {
  if (id && active !== id) return;
  if (active === null) return;
  active = null;
  listeners.forEach((listener) => listener(null));
}

export function subscribeShellDialog(listener: (id: ShellDialog | null) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
