# syntax=docker/dockerfile:1
# FastAPI backend: local Whisper (faster-whisper), ffmpeg, OpenCV and the Gemini SDKs.
# Build from the repo root:  docker build -t vidyapulse-server apps/server
# Run:                       docker run --env-file apps/server/.env -p 8000:8000 vidyapulse-server

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---- 1. Install the Python packages into a virtualenv, with ffmpeg and Whisper baked in ----
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf-cache

RUN python -m venv /opt/venv
WORKDIR /build
COPY requirements.txt requirements-prod.txt ./
RUN pip install -r requirements-prod.txt

# main.py calls static_ffmpeg.add_paths() and asr_engine.py loads WhisperModel("base") on startup.
# Both download on first use, so fetch them now: the server then starts with no network calls.
# static_ffmpeg also takes a lock file next to its binaries and chmods any binary the user can't
# run, so make the lock writable and the binaries readable and executable for the app user.
# Some Hugging Face cache files are private to root; the app user needs to read them too.
RUN python -c "import static_ffmpeg; static_ffmpeg.add_paths()" \
 && python -c "import os, static_ffmpeg; open(os.path.join(os.path.dirname(static_ffmpeg.__file__), 'lock.file'), 'a').close()" \
 && chmod 666 /opt/venv/lib/python*/site-packages/static_ffmpeg/lock.file \
 && chmod -R a+rX /opt/venv/lib/python*/site-packages/static_ffmpeg/bin \
 && python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" \
 && chmod -R a+rX /opt/hf-cache

# ---- 2. Runtime image: the virtualenv, the model cache and the app code ----
FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    PORT=8000

RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf-cache /opt/hf-cache

WORKDIR /app
COPY . .
# temp_chunks holds uploads and the extension's audio pieces until they are processed
RUN mkdir -p temp_chunks && chown app:app temp_chunks

USER app
EXPOSE 8000

# Render, docker compose and ECS all read this; "/" answers without touching Supabase or Gemini
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# One worker: the Whisper model, background jobs and the extension's audio pieces live in
# this process, so more workers would multiply memory and split recordings between them.
# Hosts like Render pass the port in $PORT.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*'"]
