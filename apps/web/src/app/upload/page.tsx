"use client";

import { useState } from "react";

import Icon from "@/components/site/Icon";
import { createClient } from "@/lib/supabase/client";

type Tone = "info" | "success" | "error";

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  const [tone, setTone] = useState<Tone>("info");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [signedUrl, setSignedUrl] = useState("");
  const [supabase] = useState(createClient);

  const say = (text: string, nextTone: Tone = "info") => {
    setStatus(text);
    setTone(nextTone);
  };

  const pick = (next: File | null) => {
    setFile(next);
    setSignedUrl("");
    say("");
  };

  const handleUpload = async () => {
    if (!file) return say("Please select a file first.", "error");
    setBusy(true);
    say("Uploading...");

    try {
      // 1. Get current authenticated user
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return say("You must be logged in to upload.", "error");

      // 2. Upload directly to the private 'lectures-audio' bucket
      const filePath = `${user.id}/${Date.now()}_${file.name}`;
      const { data, error } = await supabase.storage
        .from("lectures-audio")
        .upload(filePath, file);

      if (error) return say(`Upload failed: ${error.message}`, "error");

      say("Upload successful! Generating Signed URL...");

      // 3. Generate a Signed URL valid for 60 seconds
      const { data: urlData, error: urlError } = await supabase.storage
        .from("lectures-audio")
        .createSignedUrl(data.path, 60);

      if (urlError) {
        say(`Signed URL error: ${urlError.message}`, "error");
      } else {
        setSignedUrl(urlData.signedUrl);
        say("Complete. File securely stored.", "success");
      }
    } catch (err) {
      say(
        `Upload failed: ${err instanceof Error ? err.message : String(err)}`,
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) pick(dropped);
  };

  return (
    <div className="vp-container vp-page">
      <div className="mx-auto max-w-2xl">
        <div className="vp-enter text-center">
          <p className="vp-eyebrow">Upload a recording</p>
          <h1 className="vp-page-title">
            Your lecture,{" "}
            <span className="vp-gradient-text">stored securely.</span>
          </h1>
          <p className="vp-lead mx-auto mt-4 max-w-xl">
            Upload an audio or video file to your private bucket. You get a
            secure link to it that expires after 60 seconds.
          </p>
        </div>

        <div
          className="vp-card vp-enter mt-10 p-5 sm:p-7"
          style={{ "--d": "0.1s" } as React.CSSProperties}
        >
          <label
            htmlFor="lecture-file"
            className="vp-dropzone"
            data-dragging={dragging}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className="vp-icon-tile" style={{ width: 56, height: 56 }}>
              <Icon
                name={
                  !file
                    ? "upload"
                    : file.type.startsWith("video")
                      ? "video"
                      : "audio"
                }
              />
            </span>
            {file ? (
              <>
                <span className="font-display text-lg font-bold break-all">
                  {file.name}
                </span>
                <span className="text-sm text-muted">
                  {formatBytes(file.size)} · click to choose a different file
                </span>
              </>
            ) : (
              <>
                <span className="font-display text-lg font-bold">
                  Drop a file here, or click to browse
                </span>
                <span className="text-sm text-muted">
                  MP3, WAV, MP4, MKV and other audio or video files
                </span>
              </>
            )}
            <input
              id="lecture-file"
              type="file"
              accept="audio/*,video/*"
              className="vp-sr-only"
              onChange={(e) => pick(e.target.files?.[0] || null)}
            />
          </label>

          <button
            type="button"
            onClick={handleUpload}
            disabled={busy || !file}
            className="vp-btn vp-btn-primary vp-btn-lg mt-5 w-full"
          >
            {busy ? (
              <span className="vp-spinner" aria-hidden="true" />
            ) : (
              <Icon name="lock" />
            )}
            {busy ? "Uploading…" : "Upload to Private Bucket"}
          </button>

          <div role="status" aria-live="polite">
            {status && (
              <p className="vp-status mt-5" data-tone={tone}>
                {status}
              </p>
            )}
          </div>

          {signedUrl && (
            <div className="mt-5 rounded-2xl border border-line p-4">
              <p className="text-sm font-semibold">
                Secure Signed URL (Expires in 60s):
              </p>
              <a
                href={signedUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 block text-sm break-all"
                style={{ color: "var(--vp-link)" }}
              >
                {signedUrl}
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
