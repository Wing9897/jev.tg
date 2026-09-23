import { useEffect, useLayoutEffect, useMemo, useState, type FormEvent } from "react";
import { api, errorText } from "../api";
import { Dialog } from "../components/Dialog";
import { Field, matchesQuery, SearchBox } from "../components/fields";
import { useI18n } from "../i18n/context";
import { closeShellDialog, subscribeShellDialog } from "../shellDialogs";
import type { Tag } from "../types";

const emptyForm = { key: "", label: "", description: "" };

export default function TagsPage() {
  const { m } = useI18n();
  const [tags, setTags] = useState<Tag[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const [query, setQuery] = useState("");

  async function load() {
    const resp = await api.tags();
    setTags(resp.tags);
    setLoading(false);
  }

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(errorText(err));
      setLoading(false);
    });
  }, []);

  useLayoutEffect(() => subscribeShellDialog((id) => {
    setManagerOpen(id === "tags");
    if (id !== "tags") setFormOpen(false);
  }), []);

  function startCreate() {
    setEditing(null);
    setForm(emptyForm);
    setError(null);
    setFormOpen(true);
  }

  function startEdit(tag: Tag) {
    setEditing(tag.id);
    setForm({ key: tag.key, label: tag.label, description: tag.description });
    setError(null);
    setFormOpen(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      key: form.key.trim() || undefined,
      label: form.label.trim(),
      description: form.description.trim(),
    };
    try {
      if (editing) await api.updateTag(editing, { key: form.key.trim(), label: payload.label, description: payload.description });
      else await api.createTag(payload);
      await load();
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
    if (!window.confirm(m.tags.confirmDelete)) return;
    await api.deleteTag(id);
    await load();
    if (editing === id) {
      setEditing(null);
      setForm(emptyForm);
      setFormOpen(false);
    }
  }

  const shown = useMemo(
    () => tags.filter((tag) => matchesQuery(query, tag.label, tag.key, tag.description)),
    [tags, query],
  );
  const showOther = matchesQuery(query, "other", m.tags.reserved, m.tags.otherDesc);

  return (
    <>
      <Dialog
        open={managerOpen}
        title={m.tags.title}
        onClose={() => closeShellDialog("tags")}
        footer={
          <button type="button" className="dlg-btn primary" onClick={startCreate}>
            {m.add}
          </button>
        }
      >
        <div className="dialog-pin">
          <p className="field-hint" title={m.tags.introTitle}>
            {m.tags.intro}
          </p>
          <SearchBox label={m.tags.searchLabel} placeholder={m.tags.searchPlaceholder} value={query} onChange={setQuery} />
        </div>
        {error && !formOpen ? (
          <p role="alert" className="dialog-alert dialog-follow">
            {error}
          </p>
        ) : null}
        {loading ? (
          <p className="dialog-note dialog-follow">{m.tags.loading}</p>
        ) : (
          <div className="pick-list is-tall dialog-follow" role="list" aria-label={m.tags.listAria}>
            {showOther ? (
              <div className="dense-row">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium">other</p>
                  <p className="dense-meta truncate">{m.tags.reservedMeta}</p>
                </div>
                <span className="count-badge">{m.tags.reservedBadge}</span>
              </div>
            ) : null}
            {shown.map((tag) => (
              <div key={tag.id} className="dense-row">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium">
                    {tag.label}
                    <span className="ml-2 font-mono font-normal text-slate-400">{tag.key}</span>
                  </p>
                  {tag.description ? <p className="dense-meta truncate">{tag.description}</p> : null}
                </div>
                <div className="flex shrink-0 gap-1">
                  <button type="button" className="dlg-btn sm" onClick={() => startEdit(tag)}>
                    {m.edit}
                  </button>
                  <button type="button" className="dlg-btn sm danger" onClick={() => void remove(tag.id)}>
                    {m.remove}
                  </button>
                </div>
              </div>
            ))}
            {!showOther && shown.length === 0 ? <p className="dialog-note is-center">{m.tags.noMatch(query)}</p> : null}
          </div>
        )}
      </Dialog>

      <Dialog
        open={formOpen}
        title={editing ? m.tags.editTitle : m.tags.createTitle}
        onClose={() => setFormOpen(false)}
        footer={
          <button type="submit" form="tag-form" disabled={saving} className="dlg-btn primary">
            {saving ? m.saving : m.tags.save}
          </button>
        }
      >
        <form id="tag-form" className="dialog-stack" onSubmit={(event) => void save(event)}>
          {error ? (
            <p role="alert" className="dialog-alert">
              {error}
            </p>
          ) : null}
          <Field label={m.tags.name}>
            <input
              required
              className="field-input"
              value={form.label}
              onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
              placeholder={m.tags.namePlaceholder}
            />
          </Field>
          <Field label={m.tags.key} hint={m.tags.keyHint}>
            <input
              className="field-input font-mono"
              value={form.key}
              onChange={(event) => setForm((current) => ({ ...current, key: event.target.value }))}
              placeholder={m.tags.keyPlaceholder}
            />
          </Field>
          <Field label={m.tags.description}>
            <textarea
              rows={4}
              className="field-input"
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              placeholder={m.tags.descriptionPlaceholder}
            />
          </Field>
        </form>
      </Dialog>
    </>
  );
}
