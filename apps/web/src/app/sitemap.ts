import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

// The public pages; the workspace and uploads are per-student and stay out
export default function sitemap(): MetadataRoute.Sitemap {
  return ["", "/ingest", "/login"].map((path) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency: "monthly",
    priority: path ? 0.6 : 1,
  }));
}
