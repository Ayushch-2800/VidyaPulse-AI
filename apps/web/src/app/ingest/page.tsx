"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function IngestPage() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const supabase = createClient();

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) throw new Error("You must be logged in.");

      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/ingest/youtube`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({ youtube_url: url }),
        },
      );

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Ingestion failed.");

      setResult(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: "600px",
        margin: "40px auto",
        padding: "24px",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1>VidyaPulse AI Ingestion Engine</h1>
      <p style={{ color: "#666" }}>
        Enter a YouTube lecture link to extract audio, transcribe
        Hinglish/English speech, and build vector chunks.
      </p>

      <form onSubmit={handleIngest} style={{ marginTop: "20px" }}>
        <input
          type="url"
          required
          placeholder="https://www.youtube.com/watch?v=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          style={{
            width: "100%",
            padding: "12px",
            marginBottom: "12px",
            borderRadius: "6px",
            border: "1px solid #ccc",
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "12px 24px",
            backgroundColor: "#0070f3",
            color: "#fff",
            border: "none",
            borderRadius: "6px",
            cursor: "pointer",
          }}
        >
          {loading ? "Processing Lecture..." : "Process Lecture"}
        </button>
      </form>

      {error && <p style={{ color: "red", marginTop: "16px" }}>{error}</p>}

      {result && (
        <div
          style={{
            marginTop: "24px",
            padding: "16px",
            border: "1px solid #10B981",
            borderRadius: "8px",
            backgroundColor: "#ECFDF5",
          }}
        >
          <h3 style={{ color: "#065F46", margin: "0 0 8px 0" }}>
            Lecture Processed Successfully!
          </h3>
          <p>
            <strong>Title:</strong> {result.title}
          </p>
          <p>
            <strong>Lecture ID:</strong> {result.lecture_id}
          </p>
          <p>
            <strong>Semantic Chunks Created:</strong> {result.chunks_processed}
          </p>
        </div>
      )}
    </div>
  );
}
