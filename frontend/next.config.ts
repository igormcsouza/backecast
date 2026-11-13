import type { NextConfig } from "next";

// The site is served from the root of its own domain, so no base path is set in production. `NEXT_BASE_PATH` stays
// as an optional build-time override (read while building, hence no `NEXT_PUBLIC_` prefix).
const basePath = process.env.NEXT_BASE_PATH || "";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  basePath,
  assetPrefix: basePath || undefined,
};

export default nextConfig;
