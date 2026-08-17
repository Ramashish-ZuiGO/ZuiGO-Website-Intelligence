import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The repo root also has its own package.json/package-lock.json (for an
  // unrelated Node script under scripts/), which otherwise makes Turbopack
  // infer the wrong workspace root and fail to resolve apps/web's own
  // dependencies (e.g. "Can't resolve 'tailwindcss'"). Pin the root
  // explicitly to this app.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
