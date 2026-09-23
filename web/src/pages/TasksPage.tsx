import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorText } from "../api";
import { formatTokens, formatUsd, spendPrefix } from "../billingFormat";
import { CHANNELS_CHANGED_EVENT, notifyTasksChanged, TASKS_SNAPSHOT_EVENT } from "../channelSync";
import { Dialog } from "../components/Dialog";
import { Field, matchesQuery, SearchBox } from "../components/fields";
import { useI18n } from "../i18n/context";
import { PanelLink } from "../panelFocus";
import { MAX_TASK_TAGS, tagPickDisabled } from "../taskTagCap";
import { builtinTaskTemplates } from "../taskTemplates";
import type { Channel, Tag, Task } from "../types";

const DEFAULT_BATCH_SIZE = 50;

const emptyForm = {
  name: "",
  prompt: "",
  batchSize: DEFAULT_BATCH_SIZE,
  hitThreshold: 0.65,
  enabled: true,
  priority: 0,
  channelIds: [] as string[],
  tagIds: [] as string[],
};

export default function TasksPage() {
  const { locale, m } = useI18n();
  const templates = builtinTaskTemplates(locale);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [channelQuery, setChannelQuery] = useState("");
  const [tagQuery, setTagQuery] = useState("");
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState("");
  const channelReq = useRef(0);

  function applySubscribed(list: Channel[], req: number) {
    if (req !== channelReq.current) return;
    setChannels(list.filter((item) => item.subscribed));
  }

  async function loadChannels() {
    const req = ++channelReq.current;
    const channelResp = await api.channels().catch(() => ({ channels: [] as Channel[] }));
    applySubscribed(channelResp.channels, req);
  }

  async function load(announce = false) {
    const req = ++channelReq.current;
    const [taskResp, channelResp, tagResp] = await Promise.all([
      api.tasks(),
      api.channels().catch(() => ({ channels: [] as Channel[] })),
      api.tags().catch(() => ({ tags: [] as Tag[] })),
    ]);
    setTasks(taskResp.tasks);
    setTags(tagResp.tags);
    applySubscribed(channelResp.channels, req);
    setLoading(false);
    if (announce) notifyTasksChanged();
  }

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(errorText(err));
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<Channel[]>).detail;
      if (!Array.isArray(detail)) {
        void loadChannels();
        return;
      }
      const req = ++channelReq.current;
      applySubscribed(detail, req);
    };
    window.addEventListener(CHANNELS_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(CHANNELS_CHANGED_EVENT, onChanged);
  }, []);

  useEffect(() => {
    const onSnapshot = (event: Event) => {
      const detail = (event as CustomEvent<Task[]>).detail;
      if (!Array.isArray(detail)) return;
      setTasks(detail);
    };
    window.addEventListener(TASKS_SNAPSHOT_EVENT, onSnapshot);
    return () => window.removeEventListener(TASKS_SNAPSHOT_EVENT, onSnapshot);
  }, []);

  function startCreate() {
    setEditing(null);
    setForm(emptyForm);
    setTemplateId("");
    setError(null);
    setChannelQuery("");
    setTagQuery("");
    setFormOpen(true);
    void loadChannels();
  }

  function applyTemplate(id: string) {
    setTemplateId(id);
    if (!id) {
      setForm((current) => ({ ...current, name: "", prompt: "" }));
      return;
    }
    const picked = builtinTaskTemplates(locale).find((item) => item.id === id);
    if (!picked) return;
    setForm((current) => ({ ...current, name: picked.name, prompt: picked.prompt }));
  }

  function startEdit(task: Task) {
    setEditing(task.id);
    setTemplateId("");
    setForm({
      name: task.name,
      prompt: task.prompt,
      batchSize: task.batchSize,
      hitThreshold: task.hitThreshold,
      enabled: task.enabled,
      priority: task.priority,
      channelIds: task.channelIds,
      tagIds: task.tagIds ?? task.tags?.map((item) => item.id) ?? [],
    });
    setError(null);
    setChannelQuery("");
    setTagQuery("");
    setFormOpen(true);
    void loadChannels();
  }

  async function save() {
    setSaving(true);
    setError(null);
    const payload = {
      name: form.name,
      prompt: form.prompt,
      batchSize: Number(form.batchSize),
      hitThreshold: Number(form.hitThreshold),
      enabled: form.enabled,
      priority: Number(form.priority),
      channelIds: form.channelIds,
      tagIds: form.tagIds,
    };
    try {
      if (editing) await api.updateTask(editing, payload);
      else await api.createTask(payload);
      await load(true);
      setEditing(null);
      setForm(emptyForm);
      setFormOpen(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm(m.tasks.confirmDelete)) return;
    await api.deleteTask(id);
    await load(true);
    if (editing === id) {
      setEditing(null);
      setForm(emptyForm);
      setFormOpen(false);
    }
  }

  async function toggleEnabled(task: Task) {
    if (togglingId) return;
    const next = !task.enabled;
    setTogglingId(task.id);
    setListError(null);
    try {
      const saved = await api.updateTask(task.id, { enabled: next });
      setTasks((current) =>
        current.map((item) => (item.id === task.id ? { ...item, ...saved, usage: item.usage } : item)),
      );
      if (editing === task.id) {
        setForm((current) => ({ ...current, enabled: saved.enabled }));
      }
      notifyTasksChanged();
    } catch (err) {
      setListError(errorText(err));
    } finally {
      setTogglingId(null);
    }
  }

  const shownChannels = useMemo(
    () => channels.filter((channel) => matchesQuery(channelQuery, channel.name, channel.platformId)),
    [channels, channelQuery],
  );

  function selectShownChannels() {
    const visible = shownChannels.map((channel) => channel.platformId);
    setForm((current) => ({
      ...current,
      channelIds: [...new Set([...current.channelIds, ...visible])],
    }));
  }

  function clearBoundChannels() {
    setForm((current) => ({ ...current, channelIds: [] }));
  }

  const shownTags = useMemo(
    () => tags.filter((tag) => matchesQuery(tagQuery, tag.label, tag.key, tag.description)),
    [tags, tagQuery],
  );
  const selectedTagCount = form.tagIds.length;

  return (
    <>
      <article className="module-card">
        <div className="module-head">
          <h2>
            {m.tasks.title} <span className="count-badge">{loading ? "…" : tasks.length}</span>
          </h2>
          <button type="button" className="mini-btn solid" onClick={startCreate}>
            {m.add}
          </button>
        </div>
        {listError ? (
          <p role="alert" className="module-kicker is-rose">
            {listError}
          </p>
        ) : null}
        {loading ? (
          <p className="module-kicker">{m.tasks.loading}</p>
        ) : tasks.length === 0 ? (
          <p className="module-kicker">{m.tasks.empty}</p>
        ) : (
          <div className="dense-list">
            {tasks.map((task) => {
              const total = task.pool?.total ?? 0;
              const analyzed = task.pool?.analyzed ?? 0;
              return (
              <div key={task.id} className={`dense-row task-card${task.enabled ? "" : " is-off"}`}>
                <div className="task-card-head">
                  <p className="task-card-title" title={task.name}>
                    {task.name}
                  </p>
                  <div className="task-card-actions">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={task.enabled}
                      aria-label={task.enabled ? m.tasks.switchOff(task.name) : m.tasks.switchOn(task.name)}
                      title={task.enabled ? m.tasks.switchOff(task.name) : m.tasks.switchOn(task.name)}
                      className={`task-switch${task.enabled ? " is-on" : ""}`}
                      disabled={togglingId === task.id}
                      onClick={() => void toggleEnabled(task)}
                    >
                      <span className="task-switch-knob" aria-hidden="true" />
                      {task.enabled ? m.tasks.enabled : m.tasks.disabled}
                    </button>
                    <button type="button" className="icon-btn" aria-label={m.edit} title={m.edit} onClick={() => startEdit(task)}>
                      <PencilMark />
                    </button>
                    <button type="button" className="icon-btn is-danger" aria-label={m.remove} title={m.remove} onClick={() => void remove(task.id)}>
                      <TrashMark />
                    </button>
                  </div>
                </div>
                <p className="task-card-stats">
                  <span className="task-card-batch">{m.tasks.perBatch(task.batchSize)}</span>
                  <span className="task-card-pool">{m.tasks.pool(total, analyzed)}</span>
                </p>
                {task.usage && task.usage.calls > 0 ? (
                  <p className="task-card-usage">
                    <span>{m.tasks.calls(task.usage.calls, formatTokens(task.usage.tokens))}</span>
                    <span>
                      {spendPrefix(task.usage.usdKind)}
                      {formatUsd(task.usage.spendUsd)}
                    </span>
                  </p>
                ) : null}
              </div>
              );
            })}
          </div>
        )}
      </article>

      <Dialog
        open={formOpen}
        title={editing ? m.tasks.editTitle : m.tasks.createTitle}
        onClose={() => setFormOpen(false)}
        wide
        footer={
          <button type="submit" form="task-form" disabled={saving} className="dlg-btn primary">
            {saving ? m.saving : m.tasks.save}
          </button>
        }
      >
        <form
          id="task-form"
          className="dialog-stack"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {error ? (
            <p role="alert" className="dialog-alert">
              {error}
            </p>
          ) : null}
          {editing ? null : (
            <Field label={m.tasks.template}>
              <div className="template-pick" role="listbox" aria-label={m.tasks.template}>
                <button
                  type="button"
                  role="option"
                  aria-selected={!templateId}
                  className={`template-chip${!templateId ? " is-active" : ""}`}
                  onClick={() => applyTemplate("")}
                >
                  {m.tasks.templateBlank}
                </button>
                {templates.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={templateId === item.id}
                    className={`template-chip${templateId === item.id ? " is-active" : ""}`}
                    onClick={() => applyTemplate(item.id)}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
            </Field>
          )}
          <Field label={m.tasks.name}>
            <input
              required
              className="field-input"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </Field>
          <Field label={m.tasks.prompt}>
            <textarea
              required
              rows={5}
              className="field-input"
              placeholder={m.tasks.promptPlaceholder}
              value={form.prompt}
              onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
            />
          </Field>
          <div className="trio">
            <Field label={m.tasks.batchSize}>
              <input
                type="number"
                min={1}
                className="field-input"
                value={form.batchSize}
                onChange={(event) => setForm((current) => ({ ...current, batchSize: Number(event.target.value) }))}
              />
            </Field>
            <Field label={m.tasks.threshold}>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                className="field-input"
                value={form.hitThreshold}
                onChange={(event) => setForm((current) => ({ ...current, hitThreshold: Number(event.target.value) }))}
              />
            </Field>
            <Field label={m.tasks.priority}>
              <input
                type="number"
                className="field-input"
                value={form.priority}
                onChange={(event) => setForm((current) => ({ ...current, priority: Number(event.target.value) }))}
              />
            </Field>
          </div>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
            />
            {m.tasks.enable}
          </label>
          <Field
            label={
              <span className="flex w-full items-center justify-between gap-2">
                <span>{m.tasks.bindChannels}</span>
                <span>{m.tasks.selectedCount(form.channelIds.length, channels.length)}</span>
              </span>
            }
          >
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <SearchBox label={m.tasks.searchChannelsLabel} placeholder={m.tasks.searchChannels} value={channelQuery} onChange={setChannelQuery} />
              </div>
              <div className="dialog-toolbar-actions shrink-0">
                <button
                  type="button"
                  className="dlg-btn sm"
                  onClick={selectShownChannels}
                  disabled={saving || shownChannels.length === 0}
                >
                  {m.telegram.selectAll}
                </button>
                <button
                  type="button"
                  className="dlg-btn sm"
                  onClick={clearBoundChannels}
                  disabled={saving || channels.length === 0}
                >
                  {m.telegram.clear}
                </button>
              </div>
            </div>
            <div className="pick-list" role="group" aria-label={m.tasks.channelsAria}>
              {channels.length === 0 ? (
                <p className="dialog-note is-center">{m.tasks.pickChannelsFirst}</p>
              ) : shownChannels.length === 0 ? (
                <p className="dialog-note is-center">{m.tasks.noChannelMatch(channelQuery)}</p>
              ) : (
                shownChannels.map((channel) => (
                  <label key={channel.platformId} className="check-row">
                    <input
                      type="checkbox"
                      checked={form.channelIds.includes(channel.platformId)}
                      onChange={(event) => {
                        setForm((current) => ({
                          ...current,
                          channelIds: event.target.checked
                            ? [...current.channelIds, channel.platformId]
                            : current.channelIds.filter((id) => id !== channel.platformId),
                        }));
                      }}
                    />
                    <span className="min-w-0 truncate">{channel.name}</span>
                  </label>
                ))
              )}
            </div>
          </Field>
          <Field
            hint={m.tasks.tagHint}
            labelTitle={m.tasks.tagTitle}
            label={
              <span className="flex w-full items-center justify-between gap-2">
                <span>{m.tasks.typeTags}</span>
                <PanelLink id="tags" className="dialog-link" beforeNavigate={() => setFormOpen(false)}>
                  {m.tasks.goTags}
                </PanelLink>
              </span>
            }
          >
            <SearchBox label={m.tasks.searchTagsLabel} placeholder={m.tasks.searchTags} value={tagQuery} onChange={setTagQuery} />
            <p className="dialog-note">{m.tasks.tagSelected(selectedTagCount, MAX_TASK_TAGS)}</p>
            <div className="pick-list" role="group" aria-label={m.tasks.tagsAria}>
              {tags.length === 0 ? (
                <p className="dialog-note is-center">{m.tasks.noTagsYet}</p>
              ) : shownTags.length === 0 ? (
                <p className="dialog-note is-center">{m.tasks.noTagMatch(tagQuery)}</p>
              ) : (
                shownTags.map((tag) => {
                  const checked = form.tagIds.includes(tag.id);
                  return (
                  <label key={tag.id} className="check-row is-top">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={tagPickDisabled(checked, selectedTagCount)}
                      onChange={(event) => {
                        const turnOn = event.target.checked;
                        setForm((current) => {
                          const already = current.tagIds.includes(tag.id);
                          if (turnOn) {
                            if (already || tagPickDisabled(false, current.tagIds.length)) return current;
                            return { ...current, tagIds: [...current.tagIds, tag.id] };
                          }
                          return { ...current, tagIds: current.tagIds.filter((id) => id !== tag.id) };
                        });
                      }}
                    />
                    <span className="min-w-0">
                      <span className="font-medium">{tag.label}</span>
                      <span className="ml-2 font-mono text-slate-500">{tag.key}</span>
                      {tag.description ? (
                        <span className="mt-0.5 block truncate text-slate-500" title={tag.description}>
                          {tag.description}
                        </span>
                      ) : null}
                    </span>
                  </label>
                  );
                })
              )}
            </div>
          </Field>
        </form>
      </Dialog>
    </>
  );
}

function PencilMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
      <path d="m13.5 6.5 3 3" />
    </svg>
  );
}

function TrashMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 7h16" />
      <path d="M9 7V5h6v2" />
      <path d="M7 7l1 12h8l1-12" />
    </svg>
  );
}
