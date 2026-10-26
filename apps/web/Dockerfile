# syntax=docker/dockerfile:1
# Next.js web app as a self-contained Node server (output: "standalone").
# Build from the repo root, since npm workspaces share the root package-lock.json:
#   docker build -f apps/web/Dockerfile -t vidyapulse-web \
#     --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
#     --build-arg NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co \
#     --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=... .
# NEXT_PUBLIC_* values are compiled into the browser code, so each environment needs its own build.

ARG NODE_IMAGE=node:22-bookworm-slim

# ---- 1. Install dependencies and build ----
FROM ${NODE_IMAGE} AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Lockfile and manifests first, so the install layer is reused until dependencies change.
# HUSKY=0 skips the git hook setup, which needs a .git folder the build doesn't have.
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
RUN HUSKY=0 npm ci

COPY apps/web apps/web

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SUPABASE_URL=
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ARG BUILD_COMMIT=unknown
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    BUILD_COMMIT=$BUILD_COMMIT \
    BUILD_STANDALONE=true

# Prerendering creates the Supabase client, so the build fails without these two
RUN if [ -z "$NEXT_PUBLIC_SUPABASE_URL" ] || [ -z "$NEXT_PUBLIC_SUPABASE_ANON_KEY" ]; then \
      echo "Pass --build-arg NEXT_PUBLIC_SUPABASE_URL=... and NEXT_PUBLIC_SUPABASE_ANON_KEY=..." >&2; exit 1; \
    fi \
 && npm run build --workspace=apps/web \
 && mkdir -p apps/web/public

# ---- 2. Runtime image: only the traced server files and static assets ----
FROM ${NODE_IMAGE} AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=node:node /app/apps/web/public ./apps/web/public

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 3000) + '/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "apps/web/server.js"]
