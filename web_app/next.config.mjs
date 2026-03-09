/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable PWA-compatible output
  reactStrictMode: true,
  // Produces a self-contained .next/standalone dir — required for Docker runner stage
  output: "standalone",
  // Rewrites are not needed — frontend calls API directly via env var
};

export default nextConfig;
