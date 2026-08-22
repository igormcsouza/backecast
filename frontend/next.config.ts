import type { NextConfig } from "next";

// GitHub Pages serves this app from `igormcsouza.github.io/backecast/`, a
// subpath, not the domain root — every internal link, asset, and route
// needs that prefix baked in at build time, or every asset request 404s
// once deployed (it works fine in local dev, where there's no subpath,
// which is exactly the kind of bug that only shows up after deploying).
// `NEXT_BASE_PATH` is a plain (non-`NEXT_PUBLIC_`) build-time env var —
// Next.js reads `basePath`/`assetPrefix` while *building*, not in the
// browser, so it doesn't need the `NEXT_PUBLIC_` prefix that marks vars
// for client-bundle inlining. Left unset locally (defaults to "", i.e. no
// prefix); the deploy workflow (Phase 8) sets
// `NEXT_BASE_PATH=/backecast` before `next build`.
const basePath = process.env.NEXT_BASE_PATH || "";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  basePath,
  assetPrefix: basePath || undefined,
};

export default nextConfig;
