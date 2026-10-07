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
      handleStartCapture(message.tabId)
        .then((res) => sendResponse({ status: "started", ...res }))
        .catch((err) => sendResponse({ status: "error", error: err.message }));
      return true; // Keep async channel open
    }
  
    if (action === "STOP_CAPTURE" || action === "STOPCAPTURE") {
      handleStopCapture()
        .then((res) => sendResponse({ status: "stopped", ...res }))
        .catch((err) => sendResponse({ status: "error", error: err.message }));
      return true; // Keep async channel open
    }
  });
  
  // ==========================================
  // CAPTURE CONTROLLERS
  // ==========================================
  
  async function handleStartCapture(providedTabId) {
    // 1. Force cleanup of any lingering previous session/stream
    await handleStopCapture();
  
    // 2. Identify target tab
    let targetTabId = providedTabId;
    if (!targetTabId) {
      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!activeTab) throw new Error("No active tab found to capture.");
      targetTabId = activeTab.id;
    }
  
    // 3. Create Offscreen Document if it doesn't exist
    await ensureOffscreenDocument();
  
    // 4. Generate unique Session ID
    const sessionId = `session-${Date.now()}`;
  
    // 5. Get Tab Media Stream ID
    const streamId = await new Promise((resolve, reject) => {
      chrome.tabCapture.getMediaStreamId({ targetTabId: targetTabId }, (id) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        resolve(id);
      });
    });
  
    // 6. Save state in storage
    await chrome.storage.local.set({
      isRecording: true,
      sessionId: sessionId,
      recordingTabId: targetTabId
    });
  
    // 7. Send message to offscreen document with safe retry fallback
    try {
      await chrome.runtime.sendMessage({
        action: "START_OFFSCREEN_RECORDING",
        streamId: streamId,
        sessionId: sessionId
      });
    } catch (err) {
      // Retry once if message failed on first attempt
      await new Promise((resolve) => setTimeout(resolve, 300));
      await chrome.runtime.sendMessage({
        action: "START_OFFSCREEN_RECORDING",
        streamId: streamId,
        sessionId: sessionId
      });
    }
  
    console.log(`▶️ Started capture session: ${sessionId} on tab: ${targetTabId}`);
    return { sessionId, tabId: targetTabId };
  }
  
  async function handleStopCapture() {
    const { sessionId } = await chrome.storage.local.get(["sessionId"]);
  
    // 1. Signal offscreen document to stop MediaRecorder & tracks
    try {
      await chrome.runtime.sendMessage({ action: "STOP_OFFSCREEN_RECORDING" });
    } catch (err) {
      // Safe to ignore if offscreen document was already closed
    }
  
    // 2. Close offscreen document cleanly
    await closeOffscreenDocument();
  
    // 3. Call Finalize API on FastAPI Backend
    if (sessionId) {
      try {
        await fetch("http://localhost:8000/ingest/finalize-stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId })
        });
      } catch (err) {
        console.error("Failed to finalize stream on backend:", err);
      }
    }
  
    // 4. Reset local storage state
    await chrome.storage.local.set({
      isRecording: false,
      sessionId: null,
      recordingTabId: null
    });
  
    console.log("🛑 Capture stopped and cleaned up.");
    return { sessionId };
  }