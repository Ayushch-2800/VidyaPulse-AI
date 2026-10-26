# Deploying VidyaPulse AI (Task 20)

Production runs as three pieces, plus the Chrome extension:

```
 Browser ──► Vercel: Next.js web app (https://yourdomain.com)
    │                │ NEXT_PUBLIC_API_URL
    │                ▼
    │        Render: FastAPI API + local Whisper (https://api.yourdomain.com)
    │                │ service-role key            │ GEMINI_API_KEY
    ▼                ▼                             ▼
 Supabase: Postgres + pgvector, Auth, Storage     Google Gemini
    ▲
 Chrome extension ──► the same Render API
```

GitHub Actions (`.github/workflows/ci-cd.yml`) tests every pull request. On a push to `main` it
also builds both Docker images, starts them, pushes them to GitHub Container Registry and tells
Render to deploy the API. Vercel deploys the web app from its own GitHub integration.

You do the account steps below once. Everything else is in the repo. Replace `yourdomain.com`
with your real domain throughout.

---

## 0. Before anything: rotate the keys

Earlier screenshots showed API keys. Treat those keys as public and replace them before going live:

1. **Gemini**: [Google AI Studio](https://aistudio.google.com/apikey), create a new key, then
   delete the old one.
2. **Supabase service-role key and JWT secret**: Project Settings, API Keys. Create a new secret
   (service-role) key and revoke the old one. If the project still uses the legacy JWT secret,
   rotating it regenerates both the anon and service-role keys and signs everyone out, which is
   fine before launch; update the anon key in Vercel too.
3. Put the new values only in your local `apps/server/.env` and `apps/web/.env.local` (both are
   git-ignored) and in the hosting dashboards below. Never in a commit, an issue or a screenshot.

Git has never tracked a real env file in this repository (only `.env.example`), and no
key-shaped strings appear in its history; `.gitignore` keeps `.env` files out.

---

## 1. Supabase (production database)

The simplest choice is to keep using your current Supabase project as production: it already has
the base tables, the buckets and your data.

1. Open the project's **SQL Editor**, paste `apps/server/migrations/check_schema.sql` and run it.
   Every row should say `ok`. For a `missing` row, run the migration it names; the order is in
   `apps/server/migrations/README.md` (002, 003, 004, 005, then 006).
2. **Authentication, URL Configuration**: set **Site URL** to `https://yourdomain.com` and add
   `https://yourdomain.com/**` and `https://www.yourdomain.com/**` to **Redirect URLs**. Sign-up
   confirmation emails link to the Site URL.
3. Note these from **Project Settings, API**: the project URL, the anon (public) key and the
   service-role key.

Free plan limits to know about: a project pauses after a week with no activity, the database is
500 MB, and Storage uploads are capped at 50 MB per file (the API already compresses recordings
to stay under it). The Pro plan ($25/month) removes the pausing.

---

## 2. Render (the API)

### Which plan, honestly

The API transcribes with local Whisper inside the container, which is where the memory goes:

| What | Memory |
|---|---|
| API idle, before Whisper loads (measured in the container) | about 80 MB |
| Decoding a 1-hour recording into Whisper's input (measured) | peaks about 630 MB |
| Whisper `base` model loaded and transcribing (estimate, not measured here) | roughly 0.4 to 0.7 GB more |

So a one-hour lecture needs on the order of 1.1 to 1.4 GB at its peak.

| Render plan | RAM | Price | Verdict |
|---|---|---|---|
| Free | 512 MB | $0 | Runs out of memory on the first real lecture, and sleeps after 15 minutes idle. Only for checking the deploy works. |
| `0.5c-512mb` (Starter) | 512 MB | $7/month | Same memory problem. |
| **`1c-2g` (Standard)** | **2 GB** | **$25/month** | **Recommended.** Lectures up to about 1.5 hours. On one CPU, expect very roughly 15 to 30 minutes of transcription per hour of audio (an estimate). |
| `2c-4g` (Pro) | 4 GB | $85/month | Needed for 3 to 4 hour recordings with local Whisper. |

Using a hosted speech-to-text API instead of local Whisper would let the API run on the $7 plan,
but that is a code change (the app only calls local Whisper today; `transcriber.py` has an unused
Sarvam client) and it moves the cost to per-minute API charges. For now, local Whisper on `1c-2g`
is the simplest option that works. `render.yaml` uses `1c-2g`; change `plan:` there to pick another.

### Create the service

1. Sign in at [render.com](https://render.com) with GitHub and allow access to this repository.
2. **New, Blueprint**, pick `Ayushch-2800/VidyaPulse-AI`. Render reads `render.yaml` and shows one
   web service, `vidyapulse-api` (Docker, Singapore, `1c-2g`).
3. Fill in the values it asks for:
   - `NEXT_PUBLIC_SUPABASE_URL`: the Supabase project URL
   - `SUPABASE_SERVICE_ROLE_KEY`: the new service-role key
   - `GEMINI_API_KEY`: the new Gemini key
   - `CORS_ORIGINS`: for now, the Vercel URL you will get in step 3 (you can come back and edit
     it), later `https://yourdomain.com,https://www.yourdomain.com`
4. **Apply**. The first build takes about 10 minutes (it bakes ffmpeg and the Whisper model into
   the image). When it shows **Live**, open `https://vidyapulse-api.onrender.com/`; it should
   answer `{"message":"VidyaPulse AI Engine is running."}`.
5. **Settings, Deploy Hook**: copy the URL. You add it to GitHub in step 5.

`render.yaml` sets `autoDeployTrigger: off`, so Render deploys only when GitHub Actions calls the
deploy hook, after the tests and image builds have passed.

### Things to know about running it on Render

- **YouTube links may fail from Render.** YouTube often blocks downloads from cloud servers
  ("Sign in to confirm you're not a bot"). File uploads and the extension are not affected.
- **Keep one instance.** The extension's 30-second audio pieces are joined from files on the
  instance's disk, and background jobs run inside the process.
- **A deploy restarts the API.** A lecture that is transcribing at that moment stays in
  "processing"; upload it again. Avoid deploying while someone is recording.

---

## 3. Vercel (the web app)

1. Sign in at [vercel.com](https://vercel.com) with GitHub. **Add New, Project**, import
   `Ayushch-2800/VidyaPulse-AI`.
2. **Root Directory**: `apps/web`. Vercel detects Next.js and installs from the repo root's
   lockfile on its own. Leave the build and install commands at their defaults.
3. **Environment Variables** (Production and Preview):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://vidyapulse-api.onrender.com` (later `https://api.yourdomain.com`) |
   | `NEXT_PUBLIC_SUPABASE_URL` | the Supabase project URL |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the new anon key |
   | `NEXT_PUBLIC_SITE_URL` | `https://yourdomain.com` |

4. **Deploy**. Then put the `https://<project>.vercel.app` URL into `CORS_ORIGINS` on Render
   (Environment tab, Save, which redeploys).

From now on Vercel deploys `main` on every push and builds a preview for every pull request.
`NEXT_PUBLIC_*` values are compiled into the site, so after changing one, redeploy
(Deployments, the latest one, Redeploy).

Vercel's Hobby plan is free but limited to non-commercial use; Pro is $20/month.

---

## 4. Custom domain and HTTPS

Buy the domain at any registrar. Both hosts issue and renew HTTPS certificates for you once DNS
points at them.

1. **Web app**: Vercel project, **Settings, Domains**, add `yourdomain.com` and
   `www.yourdomain.com`. Create the DNS records Vercel shows at your registrar (an `A` record for
   `@` and a `CNAME` for `www`; use the exact values Vercel displays). Pick one as primary and let
   Vercel redirect the other.
2. **API**: Render service, **Settings, Custom Domains**, add `api.yourdomain.com`. At your
   registrar add a `CNAME` record `api` pointing to `vidyapulse-api.onrender.com`. Render shows
   **Certificate issued** when it is done.
3. DNS can take from minutes to a few hours. Both URLs then work only over HTTPS, and plain
   HTTP redirects to it.
4. Point everything at the new names:
   - Render: `CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com`
   - Vercel: `NEXT_PUBLIC_API_URL=https://api.yourdomain.com`, then redeploy
   - Supabase: Site URL and Redirect URLs from step 1
   - GitHub repository variables from step 5
   - The extension, step 6

To test preview deployments against the API too, set `CORS_ORIGIN_REGEX` on Render, for example
`https://vidyapulse-ai-[a-z0-9-]+\.vercel\.app` (match your Vercel project name).

---

## 5. GitHub (CI/CD)

In the repository, **Settings, Secrets and variables, Actions**:

- **Secrets** tab: `RENDER_DEPLOY_HOOK_URL` = the deploy hook URL from step 2.
- **Variables** tab (these are public values, used to build the web image):
  `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
  `NEXT_PUBLIC_SITE_URL`.

Then **Settings, Branches, Add branch ruleset** (or protection rule) for `main`: require a pull
request and require the status checks **Backend tests**, **Frontend lint and build**,
**API image** and **Web image**. That keeps untested code away from Vercel and Render.

What the pipeline does:

| Event | Jobs |
|---|---|
| Pull request | Backend tests (`pytest --cov`, offline), frontend lint and build, both Docker images built, started and health-checked |
| Push to `main` | All of the above, then both images pushed to `ghcr.io/ayushch-2800/vidyapulse-server` and `vidyapulse-web` (tags `latest` and `sha-<commit>`), then the Render deploy hook for that commit |

Without the secret, the deploy job prints a warning and the rest still runs. The images are
private packages by default; you see them under the repository owner's **Packages** tab. They can
run on any container host (AWS ECS or App Runner, Fly.io, a VPS) if you move off Render later.

The backend tests come with the Task 19 pull request (#18). Until it is merged, the test job
installs the dependencies and notes that there are no tests yet.

---

## 6. The Chrome extension

1. In `vidyapulse-extension/config.js` set:
   ```js
   const VIDYAPULSE_API_URL = "https://api.yourdomain.com";
   const VIDYAPULSE_WEB_URL = "https://yourdomain.com";
   ```
2. In `vidyapulse-extension/manifest.json`, add the API to `host_permissions`:
   ```json
   "host_permissions": ["http://localhost:8000/*", "https://api.yourdomain.com/*"]
   ```
3. `chrome://extensions`, click the reload icon on the VidyaPulse card. The API already accepts
   requests from any `chrome-extension://` origin.

---

## 7. Check the live site

1. `https://api.yourdomain.com/` answers with the "running" message.
2. `https://yourdomain.com` loads with a padlock, and the footer shows the commit you deployed.
3. Sign up with a new email, confirm it from the email, log in.
4. Upload a short MP3 on the upload page, wait for it to finish, ask a question about it.
5. Record a minute of a YouTube video with the extension, stop, open it in VidyaPulse.
6. Render, **Logs**: no errors; the line `Whisper model loaded successfully` appears at startup.

To roll back: Render, **Deploys**, pick the previous one, **Rollback**. Vercel, **Deployments**,
pick the previous one, **Promote to Production**.

---

## Environment variables

| Variable | Where | Secret | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Render, Vercel, GitHub variable | No | Supabase project URL. The API reads the same name. |
| `SUPABASE_SERVICE_ROLE_KEY` | Render only | **Yes** | Full database access. Never in the web app or a `NEXT_PUBLIC_` name. |
| `GEMINI_API_KEY` | Render only | **Yes** | Chat, embeddings, slide OCR, translation |
| `CORS_ORIGINS` | Render | No | Comma-separated web origins. Defaults to `http://localhost:3000`. |
| `CORS_ORIGIN_REGEX` | Render (optional) | No | Extra allowed origin pattern, e.g. Vercel previews |
| `GEMINI_CHAT_MODEL` | Render (optional) | No | Default `gemini-3.8-flash` |
| `GEMINI_FALLBACK_MODEL`, `GEMINI_TRANSLATE_MODEL`, `GEMINI_EMBEDDING_MODEL` | Render (optional) | No | Defaults in `gemini_utils.py`, `translator.py`, `embedding_engine.py` |
| `GEMINI_TIMEOUT_SECONDS`, `GEMINI_INTERACTIVE_TIMEOUT_SECONDS`, `GEMINI_THINKING_LEVEL`, `GEMINI_MAX_ANSWER_TOKENS`, `GEMINI_MIN_SECONDS_BETWEEN_CALLS` | Render (optional) | No | Tuning; see `.env.example` |
| `REDIS_URL` | Render (optional) | Yes if it has a password | Only after the Task 19 PR. A free Upstash `rediss://` URL keeps the cache across restarts. |
| `PORT` | Set by Render | No | The container listens on it (8000 by default) |
| `NEXT_PUBLIC_API_URL` | Vercel, GitHub variable | No | The API's public URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Vercel, GitHub variable | No | Public by design; row-level security protects the data |
| `NEXT_PUBLIC_SITE_URL` | Vercel, GitHub variable | No | Used for SEO metadata, the sitemap and robots.txt |
| `RENDER_DEPLOY_HOOK_URL` | GitHub secret | **Yes** | Anyone with it can trigger deploys |

---

## Run the production containers locally

With Docker Desktop running, from the repo root:

```bash
docker compose --env-file apps/web/.env.local up --build
```

The API reads `apps/server/.env`, the web build reads the `NEXT_PUBLIC_*` values from the file
passed with `--env-file`. Open http://localhost:3000. The first build takes several minutes.

Single images:

```bash
docker build -t vidyapulse-server apps/server
docker run --env-file apps/server/.env -p 8000:8000 vidyapulse-server

docker build -f apps/web/Dockerfile -t vidyapulse-web \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=... --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=... .
docker run -p 3000:3000 vidyapulse-web
```

---

## Known gaps before inviting real users

- **The API does not check who is calling.** Its routes don't verify the Supabase login token, and
  ingestion saves every lecture under one fixed development user ID. Anyone who finds the API URL
  can start ingestions (spending your CPU time and Gemini quota) or read a lecture by its ID. The
  next step is to require the token on the API routes and send it from the web app and the
  extension; the web app's ingest page already sends it.
- **One instance, in-process jobs.** Fine for a class or a demo; a queue and a worker would be the
  next step for many simultaneous uploads.
- **Gemini free tier.** Daily quotas apply. The app already shows a clear message when they run
  out; enabling billing on the key removes the limit.
