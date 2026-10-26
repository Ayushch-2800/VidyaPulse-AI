# VidyaPulse Chrome extension

Records the audio of a class playing in a Chrome tab and turns it into a VidyaPulse lecture:
transcript, Ask, cheat sheet, flashcards, quiz and summary in the web app.

## Load it

1. Start the backend (`cd apps/server && source venv/bin/activate && python main.py`, port 8000)
   and the web app (`npm run dev:web` from the repo root, port 3000).
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick this
   `vidyapulse-extension` folder. After pulling new code, click the reload icon on its card.
3. Pin it from the puzzle-piece menu so the icon stays in the toolbar.

Chrome 116 or newer is needed.

## Use it

1. Open the class (YouTube, a recorded lecture, a live class in the browser) and press play.
2. Click the VidyaPulse icon, then **Start Capture**. You keep hearing the tab while it records.
3. Click the icon again and **Stop Capture** when the class ends. Closing the tab also stops and saves.
4. Click **Open in VidyaPulse**. Transcription runs on your machine with Whisper and takes a few
   minutes for an hour of class, then the study tools fill in.

## How it works

- `popup.js` starts and stops a recording and shows its state.
- `background.js` (service worker) gets the tab's audio stream, keeps the state in
  `chrome.storage`, and calls `POST /ingest/finalize-stream` when the recording stops.
- `offscreen.js` records the stream with `MediaRecorder` and uploads a 30-second WebM piece at a
  time to `POST /ingest/upload-chunk`, named `chunk-<session>-<n>.webm`.
- The backend joins the pieces in order (only the first has the WebM header), makes a lecture,
  stores the audio as MP3 in the `lectures` bucket, and runs Whisper, embeddings and the study tools.

The URLs live in `config.js`. Recordings are saved to the same dev account as YouTube lectures.
For a deployed API, change both URLs there and add the API to `host_permissions` in
`manifest.json` (see `docs/DEPLOYMENT.md`, step 6).
