"use client";

import Link from "next/link";
import { useState } from "react";

import Icon from "@/components/site/Icon";
import { API_URL } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { formatTimestamp, useElapsedSeconds } from "@/lib/workspace";

type IngestResult = {
  title: string;
  lecture_id: string;
  chunks_processed: number;
};

const PIPELINE = [
  "Downloading the video",
  "Transcribing Hinglish and English speech",
  "Reading the board and slides",
  "Building searchable chunks",
];

export default function IngestPage() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [supabase] = useState(createClient);
  const elapsed = useElapsedSeconds(loading ? startedAt : null);

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStartedAt(Date.now());
    setError("");
    setResult(null);
    setCopied(false);

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) throw new Error("You must be logged in.");

      const response = await fetch(`${API_URL}/ingest/youtube`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ youtube_url: url }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Ingestion failed.");

      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const copyId = () => {
    if (!result) return;
    navigator.clipboard.writeText(result.lecture_id).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  };

  return (
    <div className="vp-container vp-page">
      <div className="mx-auto max-w-3xl">
        <div className="vp-enter text-center">
          <p className="vp-eyebrow">Add a lecture</p>
          <h1 className="vp-page-title">
            Drop in a lecture.{" "}
            <span className="vp-gradient-text">We&apos;ll do the rest.</span>
          </h1>
          <p className="vp-lead mx-auto mt-4 max-w-2xl">
            Paste a YouTube link. VidyaPulse extracts the audio, transcribes
            Hinglish and English speech, reads the board and builds searchable
            chunks you can question and revise.
          </p>
        </div>

        <form
          onSubmit={handleIngest}
          className="vp-card vp-enter mt-10 p-5 sm:p-7"
          style={{ "--d": "0.1s" } as React.CSSProperties}
          aria-busy={loading}
        >
          <label htmlFor="youtube-url" className="vp-label">
            YouTube lecture link
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Icon
                name="video"
                className="pointer-events-none absolute top-1/2 left-3.5 h-5 w-5 -translate-y-1/2 text-muted"
              />
              <input
                id="youtube-url"
                type="url"
                required
                placeholder="https://www.youtube.com/watch?v=..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="vp-input pl-11"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="vp-btn vp-btn-primary vp-btn-lg"
            >
              {loading ? (
                <span className="vp-spinner" aria-hidden="true" />
              ) : (
                <Icon name="sparkles" />
              )}
              {loading ? "Processing Lecture..." : "Process Lecture"}
            </button>
          </div>
          <p className="mt-3 text-sm text-muted">
            You need to be logged in. Long lectures can take several minutes, so
            keep this tab open.
          </p>

          {loading && (
            <div className="mt-6" role="status">
              <div className="vp-indeterminate" aria-hidden="true" />
              <p className="mt-3 text-sm text-fg-2">
                Working on it
                {elapsed !== null && <> · {formatTimestamp(elapsed)} so far</>}
              </p>
              <ul className="mt-3 grid gap-2 text-sm text-muted sm:grid-cols-2">
                {PIPELINE.map((step) => (
                  <li key={step} className="flex items-center gap-2">
                    <Icon name="check" className="h-4 w-4 text-violet-soft" />
                    {step}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </form>

        {error && (
          <p role="alert" className="vp-status mt-6" data-tone="error">
            {error}
          </p>
        )}

        {result && (
          <section
            className="vp-card vp-enter mt-6 p-6 sm:p-7"
            style={{ borderColor: "rgba(74, 222, 128, 0.45)" }}
            aria-labelledby="ingest-done"
          >
            <div className="flex items-start gap-4">
              <span
                className="vp-icon-tile"
                style={{
                  background: "rgba(74, 222, 128, 0.16)",
                  color: "var(--vp-success)",
                }}
              >
                <Icon name="checkCircle" />
              </span>
              <div className="min-w-0 flex-1">
                <h2 id="ingest-done" className="font-display text-xl font-bold">
                  Lecture Processed Successfully!
                </h2>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-6">
                  <dt className="text-muted">Title</dt>
                  <dd className="font-semibold">{result.title}</dd>
                  <dt className="text-muted">Lecture ID</dt>
                  <dd className="flex flex-wrap items-center gap-2">
                    <code className="break-all">{result.lecture_id}</code>
                    <button
                      type="button"
                      onClick={copyId}
                      className="vp-btn vp-btn-ghost vp-btn-sm"
                      style={{ minHeight: 30, padding: "2px 10px" }}
                    >
                      <Icon name={copied ? "check" : "copy"} />
                      {copied ? "Copied" : "Copy"}
                    </button>
                  </dd>
                  <dt className="text-muted">Semantic Chunks Created</dt>
                  <dd>{result.chunks_processed}</dd>
                </dl>
                <Link
                  href={`/chat?lecture=${encodeURIComponent(result.lecture_id)}`}
                  className="vp-btn vp-btn-primary mt-6"
                >
                  Open in the workspace
                  <Icon name="arrowRight" />
                </Link>
              </div>
            </div>
          </section>
        )}

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          <Link
            href="/upload"
            className="vp-card vp-feature block p-6 no-underline"
          >
            <span className="vp-icon-tile">
              <Icon name="upload" />
            </span>
            <h2 className="mt-4 font-display text-lg font-bold">
              Have a recording instead?
            </h2>
            <p className="mt-1 text-sm text-fg-2">
              Upload an audio or video file to your private storage.
            </p>
          </Link>
          <div className="vp-card p-6">
            <span className="vp-icon-tile">
              <Icon name="live" />
            </span>
            <h2 className="mt-4 font-display text-lg font-bold">
              Capturing a live class?
            </h2>
            <p className="mt-1 text-sm text-fg-2">
              The VidyaPulse Chrome extension records the audio of a class
              playing in a browser tab.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
