"use client";

import { useState } from "react";

import CitedAnswer, { SeekButton } from "@/components/chat/CitedAnswer";
import { useTranslation } from "@/lib/translate";
import {
  errorMessage,
  formatTimestamp,
  type Note,
  type NoteKind,
  type Notes,
} from "@/lib/workspace";

import InlineMath from "./InlineMath";
import TranslationNote from "./TranslationNote";
import {
  chipStyle,
  errorText,
  fieldStyle,
  itemStyle,
  mutedText,
  primaryButton,
  secondaryButton,
} from "./styles";

export const NOTE_KIND_LABELS: Record<NoteKind, string> = {
  note: "My note",
  answer: "AI answer",
  flashcard: "Flashcard",
  formula: "Formula",
};

function NoteEditor({
  initial,
  saveLabel,
  onSave,
  onCancel,
}: {
  initial: { title: string; body: string };
  saveLabel: string;
  onSave: (title: string, body: string) => Promise<unknown>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial.title);
  const [body, setBody] = useState(initial.body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    onSave(title, body).catch((err) => {
      setSaving(false);
      setError(errorMessage(err));
    });
  };

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: "8px" }}>
      <input
        placeholder="Title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        style={fieldStyle}
      />
      <textarea
        placeholder="Write your note. Markdown and $math$ work, and [MM:SS] links to that moment."
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        style={{ ...fieldStyle, resize: "vertical" }}
      />
      {error && <p style={{ margin: 0, ...errorText }}>{error}</p>}
      <div style={{ display: "flex", gap: "8px" }}>
        <button
          type="submit"
          disabled={saving || (!title.trim() && !body.trim())}
          style={primaryButton}
        >
          {saving ? "Saving…" : saveLabel}
        </button>
        <button type="button" onClick={onCancel} style={secondaryButton}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function NoteCard({
  note,
  title,
  body,
  notes,
  onSeek,
}: {
  note: Note;
  title: string;
  body: string;
  notes: Notes;
  onSeek: (seconds: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (editing) {
    return (
      <div style={itemStyle}>
        <NoteEditor
          initial={note}
          saveLabel="Save changes"
          onSave={(newTitle, newBody) =>
            notes
              .update(note.id, { title: newTitle, body: newBody })
              .then(() => setEditing(false))
          }
          onCancel={() => setEditing(false)}
        />
      </div>
    );
  }

  const remove = () => {
    if (!window.confirm("Delete this note?")) return;
    notes.remove(note.id).catch((err) => setError(errorMessage(err)));
  };

  return (
    <div style={itemStyle}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "8px",
          marginBottom: "6px",
        }}
      >
        <span style={chipStyle}>{NOTE_KIND_LABELS[note.kind]}</span>
        {title && (
          <strong>
            <InlineMath text={title} />
          </strong>
        )}
        {note.timestamp_seconds !== null && (
          <SeekButton
            label={formatTimestamp(note.timestamp_seconds)}
            seconds={note.timestamp_seconds}
            onSeek={onSeek}
          />
        )}
      </div>
      {body && <CitedAnswer answer={body} onSeek={onSeek} />}
      <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
        <button
          type="button"
          onClick={() => setEditing(true)}
          style={secondaryButton}
        >
          Edit
        </button>
        <button
          type="button"
          onClick={remove}
          style={{
            ...secondaryButton,
            color: "var(--vp-danger)",
            borderColor: "var(--vp-danger)",
          }}
        >
          Delete
        </button>
        {error && (
          <span style={{ fontSize: "0.85em", ...errorText }}>{error}</span>
        )}
      </div>
    </div>
  );
}

/**
 * The student's notes for this lecture: saved answers, flashcards and formulas, plus their
 * own notes, which can be pinned to the moment the player is at.
 */
export default function NotesPanel({
  notes,
  active,
  onSeek,
  getCurrentTime,
}: {
  notes: Notes;
  active: boolean;
  onSeek: (seconds: number) => void;
  getCurrentTime: () => number;
}) {
  const translation = useTranslation(
    notes.notes.flatMap((n) => [n.title, n.body]),
    active,
  );
  const [draftAt, setDraftAt] = useState<number | null>(null);
  const [drafting, setDrafting] = useState(false);

  if (notes.status === "loading")
    return <p style={{ margin: 0, ...mutedText }}>Loading notes…</p>;
  if (notes.status === "error")
    return <p style={{ margin: 0, ...errorText }}>{notes.error}</p>;

  const startDraft = () => {
    const seconds = getCurrentTime();
    setDraftAt(seconds > 0 ? Math.floor(seconds) : null);
    setDrafting(true);
  };

  return (
    <div>
      <TranslationNote translation={translation}>
        {drafting ? (
          <div style={{ ...itemStyle, marginBottom: "12px" }}>
            {draftAt !== null && (
              <p style={{ margin: "0 0 8px", fontSize: "0.9em", ...mutedText }}>
                Pinned to {formatTimestamp(draftAt)} in the lecture.
              </p>
            )}
            <NoteEditor
              initial={{ title: "", body: "" }}
              saveLabel="Save note"
              onSave={(title, body) =>
                notes
                  .add({
                    kind: "note",
                    title,
                    body,
                    timestamp_seconds: draftAt,
                  })
                  .then(() => setDrafting(false))
              }
              onCancel={() => setDrafting(false)}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={startDraft}
            style={{ ...primaryButton, marginBottom: "12px" }}
          >
            ＋ New note
          </button>
        )}

        {notes.notes.length === 0 ? (
          <p style={{ margin: 0, ...mutedText }}>
            No notes yet. Use ☆ Save to notes on an answer, flashcard or
            formula, or write your own.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "8px" }}>
            {[...notes.notes].reverse().map((note) => (
              <NoteCard
                key={note.id}
                note={note}
                title={translation.t(note.title)}
                body={translation.t(note.body)}
                notes={notes}
                onSeek={onSeek}
              />
            ))}
          </div>
        )}
      </TranslationNote>
    </div>
  );
}
