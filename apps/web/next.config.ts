import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

import type { NextConfig } from "next";

// Next.js silently ignores src/app when an app/ folder sits next to it, which
// serves stale copies of every page. Pages live in src/app, so stop early instead.
const strayAppDir = join(__dirname, "app");
if (existsSync(strayAppDir) && existsSync(join(__dirname, "src", "app"))) {
  throw new Error(
    `Found ${strayAppDir} next to src/app. Next.js would ignore src/app and serve ` +
      "the old pages from app/. Move anything you need into src/app, then delete app/.",
  );
}

function git(args: string): string {
  try {
    return execSync(`git ${args}`, {
      cwd: __dirname,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return "";
  }
}

// Stamped into the page footer and the dev server log, so it is obvious which
// checkout and commit is being served. Docker builds have no .git, so they pass BUILD_COMMIT.
const commit =
  process.env.BUILD_COMMIT ||
  process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 7) ||
  git("rev-parse --short HEAD") ||
  "unknown";
const dirty = git("status --porcelain -- .")
  ? " (with uncommitted changes)"
  : "";
const startedAt = new Date().toISOString();
console.log(
  `[web] Serving ${__dirname} at commit ${commit}${dirty}, started ${startedAt}`,
);

const nextConfig: NextConfig = {
  // The Docker image (apps/web/Dockerfile) runs Next's self-contained server. Vercel and
  // `next start` keep the normal build output.
  ...(process.env.BUILD_STANDALONE === "true" && {
    output: "standalone" as const,
    // npm workspaces install packages in the repo root, so trace files from there
    outputFileTracingRoot: join(__dirname, "..", ".."),
  }),
  env: {
    NEXT_PUBLIC_BUILD_COMMIT: commit + dirty,
    NEXT_PUBLIC_BUILD_DIR: __dirname,
    NEXT_PUBLIC_BUILD_TIME: startedAt,
  },
};

export default nextConfig;
