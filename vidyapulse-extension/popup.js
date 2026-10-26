document.addEventListener("DOMContentLoaded", async () => {
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  const openBtn = document.getElementById("openBtn");
  const statusText = document.getElementById("status");
  let timer = null;

  function say(text, tone = "info") {
    statusText.textContent = text;
    statusText.dataset.tone = tone;
  }

  function elapsed(startedAt) {
    const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }

  /**
   * Synchronizes the buttons and status text with chrome.storage.local,
   * which the service worker keeps up to date
   */
  async function syncUI() {
    const { isRecording, startedAt, lastLecture, lastError } = await chrome.storage.local.get([
      "isRecording",
      "startedAt",
      "lastLecture",
      "lastError"
    ]);

    startBtn.style.display = isRecording ? "none" : "block";
    stopBtn.style.display = isRecording ? "block" : "none";
    openBtn.style.display = !isRecording && lastLecture?.id ? "block" : "none";
    clearInterval(timer);

    if (isRecording) {
      const tick = () => say(`🔴 Capturing lecture audio... ${startedAt ? elapsed(startedAt) : ""}`);
      tick();
      timer = setInterval(tick, 1000);
    } else if (lastError) {
      say(lastError, "error");
    } else if (lastLecture?.id) {
      say(`Saved "${lastLecture.title}". It is being transcribed, which takes a few minutes.`);
    } else {
      say("Play your class in this tab, then press Start Capture.");
    }
  }

  async function run(busyText, message) {
    startBtn.disabled = stopBtn.disabled = true;
    clearInterval(timer);
    say(busyText);
    try {
      const reply = await chrome.runtime.sendMessage(message);
      if (reply?.status === "error") console.error("VidyaPulse:", reply.error);
    } catch (err) {
      await chrome.storage.local.set({ lastError: err.message });
    } finally {
      startBtn.disabled = stopBtn.disabled = false;
      await syncUI();
    }
  }

  // Start Capture Event Handler
  startBtn.addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return say("No tab to record.", "error");
    await run("Starting...", { action: "START_CAPTURE", tabId: tab.id, title: tab.title });
  });

  // Stop Capture Event Handler
  stopBtn.addEventListener("click", () =>
    run("Saving the recording...", { action: "STOP_CAPTURE" })
  );

  openBtn.addEventListener("click", async () => {
    const { lastLecture } = await chrome.storage.local.get(["lastLecture"]);
    if (!lastLecture?.id) return;
    chrome.tabs.create({
      url: `${VIDYAPULSE_WEB_URL}/chat?lecture=${encodeURIComponent(lastLecture.id)}`
    });
  });

  // The service worker can finish a recording while the popup is open (the lecture tab was closed)
  chrome.storage.onChanged.addListener(() => {
    if (!startBtn.disabled) syncUI();
  });

  // Initial UI check on popup opening
  await syncUI();
});
