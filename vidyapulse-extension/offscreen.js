let mediaRecorder = null;
let audioStream = null;
let outputAudio = null;
let currentSessionId = null;

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Supports both action naming conventions (legacy and new)
  if (message.action === "START_OFFSCREEN_RECORDING" || message.action === "startRecording") {
    const streamId = message.streamId;
    const sessionId = message.sessionId || `session-${Date.now()}`;
    startRecording(streamId, sessionId);
    sendResponse({ status: "recording_started" });
  } else if (message.action === "STOP_OFFSCREEN_RECORDING" || message.action === "stopRecording") {
    stopRecording();
    sendResponse({ status: "recording_stopped" });
  }
  return true;
});

/**
 * Starts tab audio capture, enables audio pass-through, and handles 30s chunk uploads.
 */
async function startRecording(streamId, sessionId) {
  try {
    currentSessionId = sessionId;

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

    // 3. Handle 30-second audio data chunks
    mediaRecorder.ondataavailable = async (event) => {
      if (event.data.size > 0) {
        await sendChunkToBackend(event.data, currentSessionId);
      }
    };

    // Emit chunk every 30,000 ms (30 seconds)
    mediaRecorder.start(30000);

    // 4. Update global storage state
    await chrome.storage.local.set({ 
      isRecording: true, 
      sessionId: currentSessionId 
    });

    console.log(`✅ Offscreen capture started for session: ${currentSessionId}`);

  } catch (err) {
    console.error("❌ Error starting capture in offscreen document:", err);
    await chrome.storage.local.set({ isRecording: false, sessionId: null });
  }
}

/**
 * Cleanly stops recording, stops speaker pass-through, and closes audio media tracks.
 */
async function stopRecording() {
  try {
    // 1. Stop MediaRecorder instance
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }

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

    // 4. Clear state in storage
    await chrome.storage.local.set({ isRecording: false, sessionId: null });
    currentSessionId = null;

    console.log("🛑 Offscreen capture stopped and media tracks released.");
  } catch (err) {
    console.error("❌ Error stopping offscreen capture:", err);
  }
}

/**
 * Uploads a WebM audio chunk to the FastAPI backend.
 */
async function sendChunkToBackend(blob, sessionId) {
  const activeSession = sessionId || currentSessionId || "default";
  const filename = `chunk-${activeSession}-${Date.now()}.webm`;

  const formData = new FormData();
  formData.append("file", blob, filename);

  try {
    const response = await fetch("http://localhost:8000/ingest/upload-chunk", {
      method: "POST",
      body: formData
    });

    if (response.ok) {
      console.log(`📤 Chunk uploaded successfully: ${filename} (${blob.size} bytes)`);
    } else {
      console.error(`⚠️ Backend error uploading chunk: ${response.statusText}`);
    }
  } catch (error) {
    console.error("❌ Failed to send audio chunk to backend:", error);
  }
}