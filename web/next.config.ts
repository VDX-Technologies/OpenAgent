import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export → served by FastAPI from web/out (one app, one port).
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
