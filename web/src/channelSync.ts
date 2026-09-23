import type { Channel, Task } from "./types";

export const CHANNELS_CHANGED_EVENT = "jev-channels-changed";
export const TASKS_CHANGED_EVENT = "jev-tasks-changed";
export const TASKS_SNAPSHOT_EVENT = "jev-tasks-snapshot";
export const SETTINGS_CHANGED_EVENT = "jev-settings-changed";

export function notifyChannelsChanged(channels: Channel[]) {
  window.dispatchEvent(new CustomEvent<Channel[]>(CHANNELS_CHANGED_EVENT, { detail: channels }));
}

export function notifyTasksChanged() {
  window.dispatchEvent(new CustomEvent(TASKS_CHANGED_EVENT));
}

export function notifyTasksSnapshot(tasks: Task[]) {
  window.dispatchEvent(new CustomEvent<Task[]>(TASKS_SNAPSHOT_EVENT, { detail: tasks }));
}

export function notifySettingsChanged() {
  window.dispatchEvent(new CustomEvent(SETTINGS_CHANGED_EVENT));
}
