importScripts("config.js");

// ==========================================
// OFFSCREEN DOCUMENT MANAGEMENT
// ==========================================

async function ensureOffscreenDocument() {
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT']
  });

  if (existingContexts.length === 0) {
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Recording tab audio for VidyaPulse AI ingestion'
    });
    // Pause 300ms to allow offscreen.js scripts & listeners to initialize completely
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}

async function closeOffscreenDocument() {
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT']
  });
  if (existingContexts.length > 0) {
    await chrome.offscreen.closeDocument();
  }
}

// ==========================================
// MESSAGE LISTENER
// ==========================================

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const action = message.action ? message.action.toUpperCase() : "";

  if (action === "START_CAPTURE" || action === "STARTCAPTURE") {
    handleStartCapture(message.tabId, message.title)
      .then((res) => sendResponse({ status: "started", ...res }))
      .catch(async (err) => {
        await chrome.storage.local.set({ lastError: err.message });
        sendResponse({ status: "error", error: err.message });
      });
    return true; // Keep async channel open
  }

  if (action === "STOP_CAPTURE" || action === "STOPCAPTURE") {
    handleStopCapture()
      .then((res) => sendResponse({ status: "stopped", ...res }))
      .catch(async (err) => {
        await chrome.storage.local.set({ lastError: err.message });
        sendResponse({ status: "error", error: err.message });
      });
    return true; // Keep async channel open
  }
});

// ==========================================
// CAPTURE CONTROLLERS
// ==========================================

function backendDownMessage() {
  return `Could not reach the VidyaPulse backend at ${VIDYAPULSE_API_URL}. Is it running?`;
}

async function handleStartCapture(providedTabId, title) {
  // 1. Force cleanup of any lingering previous session/stream (and save it if it has audio)
  await handleStopCapture().catch((err) => console.warn("Previous session:", err.message));

  // 2. Identify target tab
  let targetTabId = providedTabId;
  if (!targetTabId) {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!activeTab) throw new Error("No active tab found to capture.");
    targetTabId = activeTab.id;
    title = title || activeTab.title;
  }

  // 3. Check the backend is up, so a class is not recorded into nowhere
  await fetch(`${VIDYAPULSE_API_URL}/`).catch(() => {
    throw new Error(backendDownMessage());
  });

  // 4. Create Offscreen Document if it doesn't exist
  await ensureOffscreenDocument();

  // 5. Generate unique Session ID
  const sessionId = `session-${Date.now()}`;

  // 6. Get Tab Media Stream ID
  const streamId = await new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: targetTabId }, (id) => {
      if (chrome.runtime.lastError) {
        return reject(new Error(chrome.runtime.lastError.message));
      }
      resolve(id);
    });
  });

  // 7. Send message to offscreen document with safe retry fallback
  const startMessage = {
    action: "START_OFFSCREEN_RECORDING",
    streamId: streamId,
    sessionId: sessionId
  };
  let reply;
  try {
    reply = await chrome.runtime.sendMessage(startMessage);
  } catch (err) {
    // Retry once if message failed on first attempt
    await new Promise((resolve) => setTimeout(resolve, 300));
    reply = await chrome.runtime.sendMessage(startMessage);
  }
  if (reply?.status !== "recording_started") {
    await closeOffscreenDocument();
    throw new Error(reply?.error || "Could not start recording this tab.");
  }

  // 8. Save state in storage
  await chrome.storage.local.set({
    isRecording: true,
    sessionId: sessionId,
    recordingTabId: targetTabId,
    recordingTitle: title || null,
    startedAt: Date.now(),
    lastError: null
  });

  console.log(`▶️ Started capture session: ${sessionId} on tab: ${targetTabId}`);
  return { sessionId, tabId: targetTabId };
}

async function handleStopCapture() {
  const { sessionId, recordingTitle } = await chrome.storage.local.get(["sessionId", "recordingTitle"]);

  // 1. Signal offscreen document to stop; it answers once the last chunk is uploaded
  let stopped = null;
  try {
    stopped = await chrome.runtime.sendMessage({ action: "STOP_OFFSCREEN_RECORDING" });
  } catch (err) {
    // Safe to ignore if offscreen document was already closed
  }

  // 2. Close offscreen document cleanly
  await closeOffscreenDocument();

  // 3. Reset local storage state
  await chrome.storage.local.set({
    isRecording: false,
    sessionId: null,
    recordingTabId: null,
    recordingTitle: null,
    startedAt: null
  });

  if (!sessionId) return {};
  console.log("🛑 Capture stopped.", stopped);

  // 4. Ask the FastAPI backend to turn the uploaded chunks into a lecture
  let response;
  try {
    response = await fetch(`${VIDYAPULSE_API_URL}/ingest/finalize-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, title: recordingTitle })
    });
  } catch (err) {
    throw new Error(backendDownMessage());
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `The backend could not save the recording (${response.status}).`);
  }

  const lastLecture = { id: data.lecture_id, title: data.title, savedAt: Date.now() };
  await chrome.storage.local.set({ lastLecture, lastError: null });
  console.log(`🏁 Saved recording as lecture ${data.lecture_id} (${data.chunks_found} chunks).`);
  return { sessionId, lecture: lastLecture };
}
