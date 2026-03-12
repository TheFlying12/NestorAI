/** @type {import('next').NextConfig} */
const nextConfig = {
  // Strict mode causes double-mount in dev which exhausts WS reconnect retries
  reactStrictMode: false,
  // Produces a self-contained .next/standalone dir — required for Docker runner stage
  output: "standalone",
  // Rewrites are not needed — frontend calls API directly via env var
};

export default nextConfig;
