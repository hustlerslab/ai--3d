import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Defaults to Next's own ".next", so nothing changes unless you ask for it.
  // Set NEXT_DIST_DIR to build into a separate directory while a dev server is
  // running: `next dev` and `next build` otherwise share ".next", and a build
  // run underneath a live dev server corrupts what that server is serving.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
