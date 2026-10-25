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
import { API_URL } from "@/lib/api";
import type { Citation } from "@/lib/citations";
import { createClient } from "@/lib/supabase/client";
import {
  LanguageContext,
  useLanguagePreference,
  useTranslation,
} from "@/lib/translate";
import { useNotes, type NewNote } from "@/lib/workspace";

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
  query: string;
  answer?: string;
  citations?: Citation[];
  error?: string;
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px",
  borderRadius: "6px",
  border: "1px solid #ccc",
  boxSizing: "border-box",
};

const buttonStyle: React.CSSProperties = {
  padding: "10px 20px",
  backgroundColor: "#0070f3",
  color: "#fff",
  border: "none",
  borderRadius: "6px",
  cursor: "pointer",
};

const TABS = [
  { id: "ask", label: "Ask" },
  { id: "summary", label: "Summary" },
  { id: "cheatsheet", label: "Cheat sheet" },
  { id: "flashcards", label: "Flashcards" },
  { id: "quiz", label: "Quiz" },
  { id: "notes", label: "My notes" },
] as const;

type Tab = (typeof TABS)[number]["id"];

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
          <p style={{ fontWeight: 600, margin: "0 0 8px 0" }}>{turn.query}</p>
          <div
            style={{
              padding: "12px 16px",
              border: "1px solid #E5E7EB",
              borderRadius: "8px",
              backgroundColor: "#F9FAFB",
              // Set explicitly: in dark mode the inherited text colour is near-white
              color: "#111827",
            }}
          >
            {turn.error ? (
              <p style={{ margin: 0, color: "#B91C1C" }}>{turn.error}</p>
            ) : turn.answer === undefined ? (
              <p style={{ margin: 0, color: "#6B7280" }}>Thinking…</p>
            ) : (
              <>
                <CitedAnswer
                  answer={translation.t(turn.answer)}
                  citations={turn.citations}
                  onSeek={onSeek}
                />
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
  const [lectureId, setLectureId] = useState("");
  const [mediaUrl, setMediaUrl] = useState("");
  const [media, setMedia] = useState<LectureMedia | null>(null);
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [tab, setTab] = useState<Tab>("ask");
  // Panels mount on first visit and stay mounted, so a half-done quiz survives a tab switch
  const [visited, setVisited] = useState<ReadonlySet<Tab>>(new Set(["ask"]));
  const player = useRef<LecturePlayerHandle>(null);
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
    setVisited((prev) => new Set(prev).add(next));
  };

  // Pick the player source for a lecture: its YouTube link, or a signed URL for an upload
  const showLectureMedia = (lecture: Lecture) => {
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
    setTurns([]);
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
        if (fromUrl) selectLecture(fromUrl, list);
      });
    // Runs once on mount; selectLecture only reads the list passed to it here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supabase]);

  const loadMediaUrl = () => {
    const url = mediaUrl.trim();
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

    setLoading(true);
    setQuery("");
    setTurns((prev) => [...prev, { query: question }]);

    const finish = (result: Partial<ChatTurn>) =>
      setTurns((prev) =>
        prev.map((turn, i) =>
          i === prev.length - 1 ? { ...turn, ...result } : turn,
        ),
      );

    try {
      const response = await fetch(`${API_URL}/chat/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question, lecture_id: lectureId.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The request failed.");
      finish({ answer: data.answer, citations: data.citations });
    } catch (err) {
      finish({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      setLoading(false);
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
          placeholder="Ask a question about this lecture"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={inputStyle}
        />
        <button
          type="submit"
          disabled={loading || !lectureId.trim()}
          style={buttonStyle}
        >
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
      <div
        style={{
          maxWidth: "1200px",
          margin: "40px auto",
          padding: "24px",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            marginBottom: "16px",
          }}
        >
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0 }}>
            Lecture Workspace
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <LanguageSelect />
            {workspaceLecture ? (
              <Link
                href={`/chat/export?lecture=${workspaceLecture}&print=1`}
                target="_blank"
                style={{ ...buttonStyle, textDecoration: "none" }}
                title="Open a print-ready copy of the summary, cheat sheet, flashcards, quiz and notes"
              >
                Export PDF
              </Link>
            ) : (
              <span
                style={{ ...buttonStyle, opacity: 0.5, cursor: "not-allowed" }}
                title="Choose a lecture first"
              >
                Export PDF
              </span>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gap: "10px", marginBottom: "20px" }}>
          {lectures.length > 0 ? (
            <select
              value={lectureId}
              onChange={(e) => selectLecture(e.target.value)}
              style={inputStyle}
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
              <p style={{ margin: 0, color: "#6B7280" }}>{lectureNote}</p>
            )
          )}
          <input
            placeholder="Lecture ID"
            value={lectureId}
            onChange={(e) => selectLecture(e.target.value)}
            style={inputStyle}
          />
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              placeholder="YouTube or media URL to play alongside the answers"
              value={mediaUrl}
              onChange={(e) => setMediaUrl(e.target.value)}
              style={inputStyle}
            />
            <button type="button" onClick={loadMediaUrl} style={buttonStyle}>
              Load
            </button>
          </div>
        </div>

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
            {media && (
              <LecturePlayer
                key={media.url}
                ref={player}
                media={media}
                onTimeUpdate={setCurrentTime}
              />
            )}

            <div
              role="tablist"
              aria-label="Study workspace"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "6px",
                margin: "24px 0 12px",
              }}
            >
              {TABS.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => openTab(id)}
                  style={{
                    padding: "8px 14px",
                    border: "none",
                    borderRadius: "999px",
                    backgroundColor: tab === id ? "#0070f3" : "#F3F4F6",
                    color: tab === id ? "#fff" : "#111827",
                    fontWeight: tab === id ? 600 : 400,
                    cursor: "pointer",
                  }}
                >
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
                visited.has(id) && (id === "ask" || workspaceLecture) ? (
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
