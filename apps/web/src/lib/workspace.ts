import { useCallback, useEffect, useState } from "react";

import { API_URL } from "@/lib/api";
import type { Citation } from "@/lib/citations";

/** An API error that keeps the HTTP status, so a 404 can mean "not generated yet". */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Calls the FastAPI backend and throws the backend's `detail` message on failure. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.detail || `The request failed (HTTP ${response.status}).`,
    );
  }
  return data as T;
}

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

// ---- Shapes written by the backend engines (Tasks 15, 16 and 18) ----

export type ExamTopic = { exam: string; subject: string; topic: string };

export type CheatSheetItem = {
  kind: "definition" | "theorem" | "formula";
  title: string;
  latex: string;
  explanation: string;
  timestamp_seconds: number | null;
  exam_topics?: (ExamTopic & { similarity: number })[];
};

export type CheatSheetContent = {
  definitions?: CheatSheetItem[];
  theorems?: CheatSheetItem[];
  formulas?: CheatSheetItem[];
};

export type LectureTopicTag = ExamTopic & {
  item_count: number;
  best_similarity: number;
};

export type Flashcard = {
  question: string;
  answer: string;
  timestamp_seconds: number | null;
};

export type QuizQuestion = {
  question: string;
  options: string[];
  correct_index: number;
  option_explanations: string[];
  timestamp_seconds: number | null;
};

export type SummaryContent = { answer: string; citations: Citation[] };

export type ArtifactRow<T> = {
  status: "pending" | "processing" | "completed" | "failed";
  content: T;
  error: string | null;
  updated_at: string;
  /** The Gemini model that wrote it; the summary may come from the faster fallback model. */
  model?: string | null;
  topic_tags?: LectureTopicTag[];
};

export type NoteKind = "note" | "answer" | "flashcard" | "formula";

export type Note = {
  id: string;
  lecture_id: string;
  kind: NoteKind;
  title: string;
  body: string;
  timestamp_seconds: number | null;
  created_at: string;
  updated_at: string;
};

export type NewNote = Pick<Note, "kind" | "title" | "body"> & {
  timestamp_seconds?: number | null;
};

export type ExportBundle = {
  lecture: {
    id: string;
    title: string | null;
    source_type: string | null;
    source_url: string | null;
  };
  summary: ArtifactRow<SummaryContent> | null;
  cheat_sheet: ArtifactRow<CheatSheetContent> | null;
  flashcards: ArtifactRow<Flashcard[]> | null;
  quiz: ArtifactRow<QuizQuestion[]> | null;
  notes: Note[];
  warnings: string[];
};

// ---- Generated artifacts: load, generate on demand, and poll while the backend works ----

export type ArtifactKind = "cheatsheet" | "summary" | "flashcards" | "quiz";

// The summary, flashcards and quiz are all rows of study_artifacts
const GET_PATH: Record<ArtifactKind, string> = {
  cheatsheet: "cheatsheet",
  summary: "study-artifacts",
  flashcards: "study-artifacts",
  quiz: "study-artifacts",
};
// Flashcards and quiz come from one Gemini call, so generating either makes both
const POST_PATH: Record<ArtifactKind, string> = {
  cheatsheet: "cheatsheet",
  summary: "summary",
  flashcards: "study-artifacts",
  quiz: "study-artifacts",
};

// Check soon after Generate, then less and less often: 3s, 4.5s, 6.8s, ... up to every 30s
const FIRST_POLL_MS = 3000;
const MAX_POLL_MS = 30000;
const POLL_BACKOFF = 1.5;
// A job still "processing" this long after it started has died with the server
export const STALL_MINUTES = 20;

function isBusy(row: ArtifactRow<unknown> | null): boolean {
  return row?.status === "pending" || row?.status === "processing";
}

export function pollDelay(polls: number): number {
  return Math.min(MAX_POLL_MS, FIRST_POLL_MS * POLL_BACKOFF ** polls);
}

/** False while the browser tab is in the background, so polling can pause. */
function usePageVisible(): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}

/** Whole seconds since `since` (epoch ms), ticking once a second; null when `since` is null. */
export function useElapsedSeconds(since: number | null): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (since === null) return;
    const update = () => setNow(Date.now());
    const first = window.setTimeout(update, 0);
    const timer = window.setInterval(update, 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [since]);
  if (since === null || now === null) return null;
  return Math.max(0, Math.floor((now - since) / 1000));
}

export type Artifact<T> = {
  row: ArtifactRow<T> | null;
  loading: boolean;
  error: string | null;
  generating: boolean;
  /** When the running generation started (epoch ms), for an elapsed-time display. */
  startedAt: number | null;
  stalled: boolean;
  generate: () => void;
  reload: () => void;
};

/**
 * Loads a lecture's cheat sheet, summary, flashcards or quiz. generate() asks the backend to
 * (re)build it, and while the backend reports it as in progress the hook polls with backoff:
 * after 3s, then less often up to every 30s, and not at all while the browser tab is hidden.
 * It fetches only while `active` (its panel is on screen), and again each time it is shown,
 * so the quiz picks up a study set generated from the flashcards panel.
 */
export function useArtifact<T>(
  lectureId: string,
  kind: ArtifactKind,
  active: boolean,
): Artifact<T> {
  const [result, setResult] = useState<{
    row: ArtifactRow<T> | null;
    error: string | null;
    /** When this response arrived (epoch ms) */
    at: number;
  } | null>(null);
  const [tick, setTick] = useState(0);
  const [polls, setPolls] = useState(0);
  // updated_at of the row on screen when Generate was pressed; null when not waiting
  const [waitingFor, setWaitingFor] = useState<string | null>(null);
  const [requestedAt, setRequestedAt] = useState<number | null>(null);
  const [postError, setPostError] = useState<string | null>(null);
  const visible = usePageVisible();

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    apiFetch<Record<string, ArtifactRow<T>>>(
      `/lectures/${encodeURIComponent(lectureId)}/${GET_PATH[kind]}`,
    )
      .then((data) => {
        const row = kind === "cheatsheet" ? data : data[kind];
        if (!cancelled)
          setResult({
            row: (row as ArtifactRow<T>) ?? null,
            error: null,
            at: Date.now(),
          });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setResult({ row: null, error: null, at: Date.now() });
        } else {
          // A failed poll keeps what is already on screen
          setResult((prev) => ({
            row: prev?.row ?? null,
            error: errorMessage(err),
            at: Date.now(),
          }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [lectureId, kind, tick, active]);

  const row = result?.row ?? null;
  const fresh = row !== null && row.updated_at !== waitingFor && !isBusy(row);
  const busy = isBusy(row);
  const generating = (waitingFor !== null && !fresh) || busy;
  // The backend stamps updated_at when it starts; before that, use when Generate was pressed
  const startedAt = !generating
    ? null
    : busy && row && row.updated_at !== waitingFor
      ? Date.parse(row.updated_at)
      : requestedAt;
  const stalled =
    generating &&
    startedAt !== null &&
    result !== null &&
    result.at - startedAt > STALL_MINUTES * 60 * 1000;

  useEffect(() => {
    if (!active || !visible || !generating || stalled) return;
    const timer = window.setTimeout(() => {
      setPolls((n) => n + 1);
      setTick((t) => t + 1);
    }, pollDelay(polls));
    return () => window.clearTimeout(timer);
  }, [active, visible, generating, stalled, polls, tick]);

  const rowUpdatedAt = row?.updated_at ?? "";
  const generate = useCallback(() => {
    setWaitingFor(rowUpdatedAt);
    setRequestedAt(Date.now());
    setPostError(null);
    setPolls(0);
    apiFetch(`/lectures/${encodeURIComponent(lectureId)}/${POST_PATH[kind]}`, {
      method: "POST",
    })
      .catch((err) => {
        setPostError(errorMessage(err));
        setWaitingFor(null);
      })
      .finally(() => setTick((t) => t + 1));
  }, [lectureId, kind, rowUpdatedAt]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  return {
    row,
    loading: result === null,
    error: postError ?? result?.error ?? null,
    generating,
    startedAt,
    stalled,
    generate,
    reload,
  };
}

// ---- Notes ----

type NotesState =
  | { lectureId: string; status: "ready"; notes: Note[] }
  | { lectureId: string; status: "error"; message: string };

export type Notes = {
  status: "idle" | "loading" | "ready" | "error";
  notes: Note[];
  error: string | null;
  add: (note: NewNote) => Promise<Note>;
  update: (
    id: string,
    changes: { title?: string; body?: string },
  ) => Promise<Note>;
  remove: (id: string) => Promise<void>;
};

/** The student's notes for a lecture, with add, edit and delete. */
export function useNotes(lectureId: string | null): Notes {
  const [state, setState] = useState<NotesState | null>(null);

  useEffect(() => {
    if (!lectureId) return;
    let cancelled = false;
    apiFetch<{ notes: Note[] }>(
      `/lectures/${encodeURIComponent(lectureId)}/notes`,
    )
      .then((data) => {
        if (!cancelled)
          setState({ lectureId, status: "ready", notes: data.notes });
      })
      .catch((err) => {
        if (!cancelled)
          setState({ lectureId, status: "error", message: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [lectureId]);

  // Notes loaded for a previous lecture are never shown for the new one
  const current = state && state.lectureId === lectureId ? state : null;

  const changeNotes = useCallback(
    (forLecture: string, change: (notes: Note[]) => Note[]) =>
      setState((prev) =>
        prev?.status === "ready" && prev.lectureId === forLecture
          ? { ...prev, notes: change(prev.notes) }
          : prev,
      ),
    [],
  );

  const add = useCallback(
    async (note: NewNote) => {
      if (!lectureId) throw new Error("Choose a lecture first.");
      const created = await apiFetch<Note>(
        `/lectures/${encodeURIComponent(lectureId)}/notes`,
        { method: "POST", body: JSON.stringify(note) },
      );
      changeNotes(lectureId, (notes) => [...notes, created]);
      return created;
    },
    [lectureId, changeNotes],
  );

  const update = useCallback(
    async (id: string, changes: { title?: string; body?: string }) => {
      const updated = await apiFetch<Note>(`/notes/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      changeNotes(updated.lecture_id, (notes) =>
        notes.map((n) => (n.id === id ? updated : n)),
      );
      return updated;
    },
    [changeNotes],
  );

  const remove = useCallback(
    async (id: string) => {
      await apiFetch(`/notes/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (lectureId)
        changeNotes(lectureId, (notes) => notes.filter((n) => n.id !== id));
    },
    [lectureId, changeNotes],
  );

  return {
    status: current ? current.status : lectureId ? "loading" : "idle",
    notes: current?.status === "ready" ? current.notes : [],
    error: current?.status === "error" ? current.message : null,
    add,
    update,
    remove,
  };
}
