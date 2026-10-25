"use client";

import Link from "next/link";
import { memo, useCallback, useEffect, useRef, useState } from "react";

import CitedAnswer from "@/components/chat/CitedAnswer";
import LecturePlayer, {
  type LectureMedia,
  type LecturePlayerHandle,
} from "@/components/chat/LecturePlayer";
import TranscriptSidebar from "@/components/chat/TranscriptSidebar";
import CheatSheetPanel from "@/components/workspace/CheatSheetPanel";
import FlashcardsPanel from "@/components/workspace/FlashcardsPanel";
import LanguageSelect from "@/components/workspace/LanguageSelect";
import NotesPanel from "@/components/workspace/NotesPanel";
import QuizPanel from "@/components/workspace/QuizPanel";
import SaveNoteButton from "@/components/workspace/SaveNoteButton";
import SummaryPanel from "@/components/workspace/SummaryPanel";
import TranslationNote from "@/components/workspace/TranslationNote";
import { mutedText, panelStyle } from "@/components/workspace/styles";
import Icon from "@/components/site/Icon";
import { API_URL } from "@/lib/api";
import type { Citation } from "@/lib/citations";
import { createClient } from "@/lib/supabase/client";
import {
  LanguageContext,
  useLanguagePreference,
  useTranslation,
} from "@/lib/translate";
import { useNotes, type NewNote } from "@/lib/workspace";
import { readState, saveState, usePersistentState } from "@/lib/workspaceState";

// Lecture IDs are Supabase UUIDs; only fetch a transcript once a full one is entered
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Lecture = {
  id: string;
  title: string | null;
  source_type: string | null;
  source_url: string | null;
  media_bucket_path: string | null;
  status: string | null;
};

type ChatTurn = {
  /** Matches an answer to its question, even after leaving the workspace and coming back */
  id?: string;
  query: string;
  answer?: string;
  citations?: Citation[];
  error?: string;
  /** Answered from the stored lecture summary instead of a new Gemini call */
  cached?: boolean;
};

const TABS = [
  { id: "ask", label: "Ask", icon: "ask" },
  { id: "summary", label: "Summary", icon: "summary" },
  { id: "cheatsheet", label: "Cheat sheet", icon: "formula" },
  { id: "flashcards", label: "Flashcards", icon: "cards" },
  { id: "quiz", label: "Quiz", icon: "quiz" },
  { id: "notes", label: "My notes", icon: "notes" },
] as const;

type Tab = (typeof TABS)[number]["id"];

const NO_TURNS: ChatTurn[] = [];
const FIRST_TABS: Tab[] = ["ask"];

const isPending = (turn: ChatTurn) =>
  turn.answer === undefined && turn.error === undefined;

// A question still waiting when the page reloaded will never get its answer
const endInterruptedTurns = (turns: ChatTurn[]) =>
  turns.map((turn) =>
    isPending(turn)
      ? {
          ...turn,
          error:
            "This question was interrupted when the page reloaded. Please ask it again.",
        }
      : turn,
  );

/** Remembers playback per media file; a signed URL's token changes, its path does not. */
const positionKey = (url: string) => `position:${url.split("?")[0]}`;

// Memoized so the transcript's frequent time updates don't re-render every answer's markdown
const ChatTurns = memo(function ChatTurns({
  turns,
  active,
  onSeek,
  onSaveNote,
}: {
  turns: ChatTurn[];
  active: boolean;
  onSeek: (seconds: number) => void;
  onSaveNote?: (note: NewNote) => Promise<unknown>;
}) {
  const translation = useTranslation(
    turns.map((turn) => turn.answer ?? ""),
    active,
  );

  return (
    <>
      {turns.some((turn) => turn.answer) && (
        <TranslationNote translation={translation} />
      )}
      {turns.map((turn, i) => (
        <div key={i}>
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              marginBottom: "10px",
            }}
          >
            <p
              style={{
                margin: 0,
                maxWidth: "85%",
                padding: "10px 14px",
                borderRadius: "14px 14px 4px 14px",
                background: "var(--vp-gradient-btn)",
                color: "#fff",
                fontWeight: 500,
              }}
            >
              {turn.query}
            </p>
          </div>
          <div
            style={{
              padding: "14px 16px",
              border: "1px solid var(--vp-border)",
              borderRadius: "14px 14px 14px 4px",
              backgroundColor: "var(--vp-surface-2)",
              color: "var(--vp-text)",
            }}
          >
            {turn.error ? (
              <p style={{ margin: 0, color: "var(--vp-danger)" }}>
                {turn.error}
              </p>
            ) : turn.answer === undefined ? (
              <p
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  margin: 0,
                  ...mutedText,
                }}
              >
                <span className="vp-spinner" aria-hidden="true" />
                Thinking… Gemini&apos;s free tier can take up to a minute.
              </p>
            ) : (
              <>
                <CitedAnswer
                  answer={translation.t(turn.answer)}
                  citations={turn.citations}
                  onSeek={onSeek}
                />
                {turn.cached && (
                  <p
                    style={{
                      margin: "8px 0 0",
                      fontSize: "0.85em",
                      ...mutedText,
                    }}
                  >
                    From the saved lecture summary, so no wait for Gemini.
                  </p>
                )}
                {onSaveNote && (
                  <div style={{ marginTop: "10px" }}>
                    <SaveNoteButton
                      note={{
                        kind: "answer",
                        title: turn.query,
                        body: turn.answer,
                        timestamp_seconds: turn.citations?.[0]?.seconds ?? null,
                      }}
                      onSave={onSaveNote}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ))}
    </>
  );
});

export default function ChatPage() {
  const [supabase] = useState(createClient);
  const [lectures, setLectures] = useState<Lecture[]>([]);
  const [lectureNote, setLectureNote] = useState("");
  // The workspace is kept when the student opens another page and comes back (and across
  // reloads in the same tab): the lecture, video and position, questions and answers, open tab
  const [lectureId, setLectureId] = usePersistentState("lecture", "");
  const [mediaUrl, setMediaUrl] = usePersistentState("mediaUrl", "");
  const [media, setMedia] = usePersistentState<LectureMedia | null>(
    "media",
    null,
  );
  // Whether the media was picked with the lecture (and can be re-signed) or pasted in
  const [, setMediaSource] = usePersistentState<"lecture" | "custom">(
    "mediaSource",
    "lecture",
  );
  const [query, setQuery] = usePersistentState("query", "");
  const askedLecture = lectureId.trim();
  // Each lecture keeps its own conversation
  const [turns, setTurns] = usePersistentState<ChatTurn[]>(
    askedLecture ? `turns:${askedLecture}` : null,
    NO_TURNS,
    endInterruptedTurns,
  );
  const loading = turns.some(isPending);
  const [currentTime, setCurrentTime] = useState(0);
  const [tab, setTab] = usePersistentState<Tab>("tab", "ask");
  // Panels mount on first visit and stay mounted, so a half-done quiz survives a tab switch
  const [visited, setVisited] = usePersistentState<Tab[]>(
    "visited",
    FIRST_TABS,
  );
  const player = useRef<LecturePlayerHandle>(null);
  const lastSavedSecond = useRef(-1);
  const language = useLanguagePreference();

  const workspaceLecture = UUID_PATTERN.test(lectureId.trim())
    ? lectureId.trim()
    : null;
  const notes = useNotes(workspaceLecture);

  const seek = useCallback((seconds: number) => {
    player.current?.seek(seconds);
  }, []);

  const getCurrentTime = useCallback(
    () => player.current?.getCurrentTime() ?? 0,
    [],
  );

  const openTab = (next: Tab) => {
    setTab(next);
    setVisited((prev) => (prev.includes(next) ? prev : [...prev, next]));
  };

  const onTimeUpdate = useCallback(
    (seconds: number) => {
      setCurrentTime(seconds);
      const second = Math.floor(seconds);
      if (media && second !== lastSavedSecond.current) {
        lastSavedSecond.current = second;
        saveState(positionKey(media.url), second);
      }
    },
    [media],
  );

  // Pick the player source for a lecture: its YouTube link, or a signed URL for an upload
  const showLectureMedia = (lecture: Lecture) => {
    setMediaSource("lecture");
    if (lecture.source_type === "youtube" && lecture.source_url) {
      setMediaUrl(lecture.source_url);
      setMedia({ kind: "youtube", url: lecture.source_url });
    } else if (lecture.media_bucket_path) {
      supabase.storage
        .from("lectures")
        .createSignedUrl(lecture.media_bucket_path, 60 * 60)
        .then(({ data, error }) => {
          if (error) {
            setLectureNote(`Could not load lecture media: ${error.message}`);
            return;
          }
          setMediaUrl(data.signedUrl);
          setMedia({ kind: "file", url: data.signedUrl });
        });
    }
  };

  const selectLecture = (id: string, list: Lecture[] = lectures) => {
    setLectureId(id);
    const lecture = list.find((l) => l.id === id);
    if (!lecture) return;
    showLectureMedia(lecture);
  };

  // Lectures are RLS-protected, so the list only fills in for the logged-in owner
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("lecture");

    supabase
      .from("lectures")
      .select("id, title, source_type, source_url, media_bucket_path, status")
      .then(({ data, error }) => {
        const list = data ?? [];
        if (error) setLectureNote(`Could not load lectures: ${error.message}`);
        else if (!list.length)
          setLectureNote(
            "No lectures found. Log in as the lecture's owner, or paste a lecture ID below.",
          );
        setLectures(list);
        const saved = readState("lecture", "");
        if (fromUrl && fromUrl !== saved) {
          selectLecture(fromUrl, list);
        } else if (saved && readState("mediaSource", "lecture") === "lecture") {
          // Back in the workspace: reload the lecture's player, with a fresh signed URL
          const lecture = list.find((l) => l.id === saved);
          if (lecture) showLectureMedia(lecture);
        }
      });
    // Runs once on mount; selectLecture only reads the list passed to it here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supabase]);

  const loadMediaUrl = () => {
    const url = mediaUrl.trim();
    setMediaSource("custom");
    if (!url) return setMedia(null);
    setMedia({
      kind: /youtube\.com|youtu\.be/.test(url) ? "youtube" : "file",
      url,
    });
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    const question = query.trim();
    if (!question || !lectureId.trim()) return;

    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setQuery("");
    setTurns((prev) => [...prev, { id, query: question }]);

    // Still lands if the student has left the workspace by the time the answer arrives
    const finish = (result: Partial<ChatTurn>) =>
      setTurns((prev) =>
        prev.map((turn) => (turn.id === id ? { ...turn, ...result } : turn)),
      );

    try {
      const response = await fetch(`${API_URL}/chat/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question, lecture_id: lectureId.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The request failed.");
      finish({
        answer: data.answer,
        citations: data.citations,
        cached: data.cached === true,
      });
    } catch (err) {
      finish({ error: err instanceof Error ? err.message : String(err) });
    }
  };

  const askPanel = (
    <>
      <div style={{ display: "grid", gap: "16px", marginBottom: "16px" }}>
        {turns.length === 0 && (
          <p style={{ margin: 0, ...mutedText }}>
            Ask anything about the lecture, or ask for a summary. Answers cite
            the moments they come from; press a timestamp to jump there.
          </p>
        )}
        <ChatTurns
          turns={turns}
          active={tab === "ask"}
          onSeek={seek}
          onSaveNote={workspaceLecture ? notes.add : undefined}
        />
      </div>

      <form onSubmit={handleAsk} style={{ display: "flex", gap: "10px" }}>
        <input
          required
          aria-label="Your question"
          placeholder="Ask a question about this lecture"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="vp-input"
        />
        <button
          type="submit"
          disabled={loading || !lectureId.trim()}
          className="vp-btn vp-btn-primary"
        >
          {loading ? (
            <span className="vp-spinner" aria-hidden="true" />
          ) : (
            <Icon name="arrowRight" />
          )}
          {loading ? "Asking…" : "Ask"}
        </button>
      </form>
    </>
  );

  const panelFor = (id: Tab, lecture: string) => {
    const active = tab === id;
    switch (id) {
      case "ask":
        return askPanel;
      case "summary":
        return (
          <SummaryPanel
            lectureId={lecture}
            active={active}
            onSeek={seek}
            onSaveNote={notes.add}
          />
        );
      case "cheatsheet":
        return (
          <CheatSheetPanel
            lectureId={lecture}
            active={active}
            onSeek={seek}
            onSaveNote={notes.add}
          />
        );
      case "flashcards":
        return (
          <FlashcardsPanel
            lectureId={lecture}
            active={active}
            onSeek={seek}
            onSaveNote={notes.add}
          />
        );
      case "quiz":
        return <QuizPanel lectureId={lecture} active={active} onSeek={seek} />;
      case "notes":
        return (
          <NotesPanel
            notes={notes}
            active={active}
            onSeek={seek}
            getCurrentTime={getCurrentTime}
          />
        );
    }
  };

  return (
    <LanguageContext.Provider value={language}>
      <div className="vp-container vp-page vp-workspace">
        <div
          className="flex flex-wrap items-end justify-between gap-4"
          style={{ marginBottom: "20px" }}
        >
          <div>
            <p className="vp-eyebrow">Study workspace</p>
            <h1 className="vp-page-title">Lecture Workspace</h1>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <LanguageSelect />
            {workspaceLecture ? (
              <Link
                href={`/chat/export?lecture=${workspaceLecture}&print=1`}
                target="_blank"
                className="vp-btn vp-btn-primary"
                title="Open a print-ready copy of the summary, cheat sheet, flashcards, quiz and notes"
              >
                <Icon name="pdf" />
                Export PDF
              </Link>
            ) : (
              <span
                className="vp-btn vp-btn-primary"
                aria-disabled="true"
                title="Choose a lecture first"
              >
                <Icon name="pdf" />
                Export PDF
              </span>
            )}
          </div>
        </div>

        <section
          className="vp-card grid gap-3 p-4 md:grid-cols-2"
          style={{ marginBottom: "24px", borderRadius: "18px" }}
          aria-label="Choose a lecture"
        >
          {lectures.length > 0 ? (
            <select
              aria-label="Lecture"
              value={lectureId}
              onChange={(e) => selectLecture(e.target.value)}
              className="vp-input md:col-span-2"
            >
              <option value="">Choose a lecture…</option>
              {lectures.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.title || l.id}
                  {l.status && l.status !== "completed" ? ` (${l.status})` : ""}
                </option>
              ))}
            </select>
          ) : (
            lectureNote && (
              <p
                className="flex items-start gap-2 md:col-span-2"
                style={{ margin: 0, ...mutedText }}
              >
                <Icon name="alert" className="mt-1 h-4 w-4 flex-none" />
                {lectureNote}
              </p>
            )
          )}
          <input
            aria-label="Lecture ID"
            placeholder="Lecture ID"
            value={lectureId}
            onChange={(e) => selectLecture(e.target.value)}
            className="vp-input"
          />
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              aria-label="YouTube or media URL"
              placeholder="YouTube or media URL to play alongside the answers"
              value={mediaUrl}
              onChange={(e) => setMediaUrl(e.target.value)}
              className="vp-input"
            />
            <button
              type="button"
              onClick={loadMediaUrl}
              className="vp-btn vp-btn-ghost"
            >
              <Icon name="play" />
              Load
            </button>
          </div>
        </section>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "flex-start",
            gap: "24px",
          }}
        >
          {/* Wraps the transcript below the workspace only when there isn't room for both */}
          <div style={{ flex: "1 1 0%", minWidth: "min(100%, 420px)" }}>
            {media ? (
              <LecturePlayer
                key={media.url}
                ref={player}
                media={media}
                startAt={readState(positionKey(media.url), 0)}
                onTimeUpdate={onTimeUpdate}
              />
            ) : (
              <div className="vp-empty">
                <span className="vp-icon-tile">
                  <Icon name="video" />
                </span>
                <h2>
                  {workspaceLecture
                    ? "Watch while you study"
                    : "Pick a lecture to begin"}
                </h2>
                <p>
                  {workspaceLecture
                    ? "Paste the lecture's YouTube or media link above and press Load to play it beside your answers."
                    : "Choose one of your lectures above or paste a lecture ID. New here? Add your first lecture."}
                </p>
                {!workspaceLecture && (
                  <Link
                    href="/ingest"
                    className="vp-btn vp-btn-primary vp-btn-sm"
                  >
                    Add a lecture
                    <Icon name="arrowRight" />
                  </Link>
                )}
              </div>
            )}

            <div
              role="tablist"
              aria-label="Study workspace"
              className="vp-tabs"
              style={{ margin: "20px 0 14px" }}
            >
              {TABS.map(({ id, label, icon }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => openTab(id)}
                  className="vp-tab"
                >
                  <Icon name={icon} />
                  {label}
                  {id === "notes" && notes.notes.length > 0
                    ? ` (${notes.notes.length})`
                    : ""}
                </button>
              ))}
            </div>

            <div role="tabpanel" style={panelStyle}>
              {tab !== "ask" && !workspaceLecture ? (
                <p style={{ margin: 0, ...mutedText }}>
                  Choose a lecture above to see its{" "}
                  {TABS.find((t) => t.id === tab)?.label.toLowerCase()}.
                </p>
              ) : null}
              {TABS.map(({ id }) =>
                visited.includes(id) && (id === "ask" || workspaceLecture) ? (
                  <div
                    key={id === "ask" ? id : `${id}-${workspaceLecture}`}
                    hidden={tab !== id}
                  >
                    {panelFor(id, workspaceLecture ?? "")}
                  </div>
                ) : null,
              )}
            </div>
          </div>

          {workspaceLecture && (
            <div
              style={{
                flex: "0 0 360px",
                width: "360px",
                maxWidth: "100%",
                position: "sticky",
                top: "24px",
                height: "calc(100vh - 48px)",
              }}
            >
              <TranscriptSidebar
                key={workspaceLecture}
                lectureId={workspaceLecture}
                currentTime={currentTime}
                onSeek={seek}
              />
            </div>
          )}
        </div>
      </div>
    </LanguageContext.Provider>
  );
}
