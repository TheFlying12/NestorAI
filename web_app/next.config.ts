import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable PWA-compatible output
  reactStrictMode: true,
  // Rewrites are not needed — frontend calls API directly via env var
};

export default nextConfig;
