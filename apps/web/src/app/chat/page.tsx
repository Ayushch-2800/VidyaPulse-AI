"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";

import CitedAnswer from "@/components/chat/CitedAnswer";
import LecturePlayer, {
  type LectureMedia,
  type LecturePlayerHandle,
} from "@/components/chat/LecturePlayer";
import TranscriptSidebar from "@/components/chat/TranscriptSidebar";
import { API_URL } from "@/lib/api";
import type { Citation } from "@/lib/citations";
import { createClient } from "@/lib/supabase/client";

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

// Memoized so the transcript's frequent time updates don't re-render every answer's markdown
const ChatTurns = memo(function ChatTurns({
  turns,
  onSeek,
}: {
  turns: ChatTurn[];
  onSeek: (seconds: number) => void;
}) {
  return (
    <>
      {turns.map((turn, i) => (
        <div key={i}>
          <p style={{ fontWeight: 600, margin: "0 0 8px 0" }}>{turn.query}</p>
          <div
            style={{
              padding: "12px 16px",
              border: "1px solid #E5E7EB",
              borderRadius: "8px",
              backgroundColor: "#F9FAFB",
            }}
          >
            {turn.error ? (
              <p style={{ margin: 0, color: "#B91C1C" }}>{turn.error}</p>
            ) : turn.answer === undefined ? (
              <p style={{ margin: 0, color: "#6B7280" }}>Thinking…</p>
            ) : (
              <CitedAnswer
                answer={turn.answer}
                citations={turn.citations}
                onSeek={onSeek}
              />
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
  const player = useRef<LecturePlayerHandle>(null);

  const seek = useCallback((seconds: number) => {
    player.current?.seek(seconds);
  }, []);

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

  return (
    <div
      style={{
        maxWidth: "1200px",
        margin: "40px auto",
        padding: "24px",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1
        style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "16px" }}
      >
        Ask the Lecture
      </h1>

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
        {/* Wraps the transcript below the chat only when there isn't room for both */}
        <div style={{ flex: "1 1 0%", minWidth: "min(100%, 420px)" }}>
          {media && (
            <LecturePlayer
              key={media.url}
              ref={player}
              media={media}
              onTimeUpdate={setCurrentTime}
            />
          )}

          <div style={{ display: "grid", gap: "16px", margin: "24px 0" }}>
            <ChatTurns turns={turns} onSeek={seek} />
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
        </div>

        {UUID_PATTERN.test(lectureId.trim()) && (
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
              key={lectureId.trim()}
              lectureId={lectureId.trim()}
              currentTime={currentTime}
              onSeek={seek}
            />
          </div>
        )}
      </div>
    </div>
  );
}
