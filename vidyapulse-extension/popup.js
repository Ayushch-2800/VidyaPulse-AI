document.addEventListener("DOMContentLoaded", async () => {
    // Select UI elements with fallback support for common ID naming conventions
    const startBtn = document.getElementById("start-btn") || document.getElementById("startBtn");
    const stopBtn = document.getElementById("stop-btn") || document.getElementById("stopBtn");
    const statusText = document.getElementById("status-text") || document.getElementById("status");
  
    if (!startBtn || !stopBtn || !statusText) {
      console.error("VidyaPulse Extension: Required UI elements not found in popup.html");
      return;
    }
  
    /**
     * Synchronizes button visibility and status text with chrome.storage.local
     */
    async function syncUI() {
      const { isRecording } = await chrome.storage.local.get(["isRecording"]);
  
      if (isRecording) {
        startBtn.style.display = "none";
        stopBtn.style.display = "inline-block";
        statusText.innerText = "🔴 Capturing lecture audio...";
      } else {
        startBtn.style.display = "inline-block";
        stopBtn.style.display = "none";
        statusText.innerText = "Ready to capture.";
      }
    }
  
    // Initial UI check on popup opening
    await syncUI();
  
    // Start Capture Event Handler
    startBtn.addEventListener("click", async () => {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab) {
          console.error("No active tab found.");
          return;
        }
  
        chrome.runtime.sendMessage(
          { action: "START_CAPTURE", tabId: tab.id },
          async (response) => {
            if (chrome.runtime.lastError) {
              console.error("Error starting capture:", chrome.runtime.lastError.message);
              return;
            }
            await chrome.storage.local.set({ isRecording: true });
            await syncUI();
          }
        );
      } catch (err) {
        console.error("Failed to query active tab:", err);
      }
    });
  
    // Stop Capture Event Handler
    stopBtn.addEventListener("click", () => {
      chrome.runtime.sendMessage({ action: "STOP_CAPTURE" }, async (response) => {
        if (chrome.runtime.lastError) {
          console.error("Error stopping capture:", chrome.runtime.lastError.message);
          return;
        }
        await chrome.storage.local.set({ isRecording: false });
        await syncUI();
      });
    });
  });