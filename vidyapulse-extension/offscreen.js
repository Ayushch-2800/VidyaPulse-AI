// Offscreen documents can use chrome.runtime only (no chrome.storage), so the
// service worker keeps the recording state and this page just records and uploads.
let mediaRecorder = null;
let audioStream = null;
let outputAudio = null;
let chunkIndex = 0;
let pendingUploads = [];

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Supports both action naming conventions (legacy and new)
  if (message.action === "START_OFFSCREEN_RECORDING" || message.action === "startRecording") {
    const sessionId = message.sessionId || `session-${Date.now()}`;
    startRecording(message.streamId, sessionId)
      .then(() => sendResponse({ status: "recording_started" }))
      .catch((err) => sendResponse({ status: "error", error: err.message }));
    return true; // Keep async channel open
  }
  if (message.action === "STOP_OFFSCREEN_RECORDING" || message.action === "stopRecording") {
    stopRecording().then((result) => sendResponse({ status: "recording_stopped", ...result }));
    return true; // Keep async channel open
  }
  // Other messages (the popup's) are for the service worker
  return false;
});

/**
 * Starts tab audio capture, enables audio pass-through, and handles 30s chunk uploads.
 */
async function startRecording(streamId, sessionId) {
  chunkIndex = 0;
  pendingUploads = [];

  // 1. Capture raw tab audio stream
  audioStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId
      }
    },
    video: false
  });

  // ==========================================
  // AUDIO PASS-THROUGH FIX
  // Routes tab audio back to speakers so the student
  // can hear lecture video audio while recording.
  // ==========================================
  outputAudio = new Audio();
  outputAudio.srcObject = audioStream;
  await outputAudio.play().catch(err => console.warn("Audio playback issue:", err));

  // 2. Setup MediaRecorder for WebM chunks
  mediaRecorder = new MediaRecorder(audioStream, { mimeType: "audio/webm" });

  // 3. Upload each 30-second piece. Only the first piece has the WebM header, so the
  // index in the name lets the backend join them back in order.
  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      pendingUploads.push(sendChunkToBackend(event.data, sessionId, chunkIndex++));
    }
  };

  // Closing the lecture tab ends the stream: save what was recorded
  audioStream.getAudioTracks()[0].addEventListener("ended", () => {
    chrome.runtime.sendMessage({ action: "STOP_CAPTURE", reason: "tab_closed" }).catch(() => {});
  });

  // Emit chunk every 30,000 ms (30 seconds)
  mediaRecorder.start(30000);

  console.log(`✅ Offscreen capture started for session: ${sessionId}`);
}

/**
 * Stops recording, waits for the last piece to upload, then releases the tab audio.
 */
async function stopRecording() {
  // 1. The recorder hands over its last piece only after stop(), so wait for it
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    await new Promise((resolve) => {
      mediaRecorder.addEventListener("stop", resolve, { once: true });
      mediaRecorder.stop();
    });
  }
  mediaRecorder = null;

  // 2. Stop audio speaker pass-through
  if (outputAudio) {
    outputAudio.pause();
    outputAudio.srcObject = null;
    outputAudio = null;
  }

  // 3. Release media stream tracks (unmutes Chrome tab)
  if (audioStream) {
    audioStream.getTracks().forEach(track => track.stop());
    audioStream = null;
  }

  // 4. Wait for every upload, so the backend has the whole recording before it is finalized
  const results = await Promise.all(pendingUploads);
  pendingUploads = [];

  console.log("🛑 Offscreen capture stopped and media tracks released.");
  return { chunks: results.length, failed: results.filter((ok) => !ok).length };
}

/**
 * Uploads a WebM audio chunk to the FastAPI backend, retrying twice. Resolves to whether it arrived.
 */
async function sendChunkToBackend(blob, sessionId, index) {
  const filename = `chunk-${sessionId}-${String(index).padStart(5, "0")}.webm`;

  for (let attempt = 1; attempt <= 3; attempt++) {
    const formData = new FormData();
    formData.append("file", blob, filename);
    try {
      const response = await fetch(`${VIDYAPULSE_API_URL}/ingest/upload-chunk`, {
        method: "POST",
        body: formData
      });
      if (response.ok) {
        console.log(`📤 Chunk uploaded successfully: ${filename} (${blob.size} bytes)`);
        return true;
      }
      console.error(`⚠️ Backend error uploading chunk: ${response.status} ${response.statusText}`);
    } catch (error) {
      console.error("❌ Failed to send audio chunk to backend:", error);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  return false;
}
