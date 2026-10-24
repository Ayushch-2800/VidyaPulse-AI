"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function StorageUploadTest() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  const [signedUrl, setSignedUrl] = useState("");
  const supabase = createClient();

  const handleUpload = async () => {
    if (!file) return setStatus("Please select a file first.");
    setStatus("Uploading...");

    // 1. Get current authenticated user
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return setStatus("You must be logged in to upload.");

    // 2. Upload directly to the private 'lectures-audio' bucket
    const filePath = `${user.id}/${Date.now()}_${file.name}`;
    const { data, error } = await supabase.storage
      .from("lectures-audio")
      .upload(filePath, file);

    if (error) {
      setStatus(`Upload failed: ${error.message}`);
      return;
    }

    setStatus("Upload successful! Generating Signed URL...");

    // 3. Generate a Signed URL valid for 60 seconds
    const { data: urlData, error: urlError } = await supabase.storage
      .from("lectures-audio")
      .createSignedUrl(data.path, 60);

    if (urlError) {
      setStatus(`Signed URL error: ${urlError.message}`);
    } else {
      setSignedUrl(urlData.signedUrl);
      setStatus("Complete. File securely stored.");
    }
  };

  return (
    <div
      style={{
        maxWidth: "400px",
        margin: "50px auto",
        padding: "20px",
        border: "1px solid #ccc",
        borderRadius: "8px",
      }}
    >
      <h2>Secure Media Upload Test</h2>
      <input
        type="file"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        style={{ marginBottom: "15px", display: "block" }}
      />
      <button
        onClick={handleUpload}
        style={{ padding: "8px 12px", cursor: "pointer" }}
      >
        Upload to Private Bucket
      </button>

      <p style={{ marginTop: "15px", fontSize: "14px", color: "#555" }}>
        {status}
      </p>

      {signedUrl && (
        <div style={{ marginTop: "15px" }}>
          <p>
            <strong>Secure Signed URL (Expires in 60s):</strong>
          </p>
          <a
            href={signedUrl}
            target="_blank"
            rel="noreferrer"
            style={{ wordBreak: "break-all", color: "blue" }}
          >
            {signedUrl}
          </a>
        </div>
      )}
    </div>
  );
}
