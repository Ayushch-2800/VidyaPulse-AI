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

const nextConfig: NextConfig = {/* config options here */};

export default nextConfig;
